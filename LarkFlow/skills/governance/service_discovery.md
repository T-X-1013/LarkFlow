# 服务发现规范 (Service Discovery via Kratos Registry)

> Kratos 用 `registry.Registrar` / `registry.Discovery` 抽象服务注册与发现，实现层可换：
> **etcd**（默认，云原生中立） / `consul` / `nacos` / `zookeeper`。本 skill 以 etcd 为例；换实现只动 contrib
> import 和 wire，不动业务代码。

## 🔴 CRITICAL: 服务端必须 Register，客户端用 discovery:// 拨号

没注册的服务，客户端的 `discovery:///svc-name` 拨号会拿到空节点列表直接挂；客户端用固定 IP 拨号则
丧失弹性伸缩和滚动发布能力。

### 服务端注册

```go
// cmd/server/main.go
import (
    "github.com/go-kratos/kratos/v2"
    etcdclient "go.etcd.io/etcd/client/v3"
    "github.com/go-kratos/kratos/contrib/registry/etcd/v2"
)

func newRegistrar() (registry.Registrar, error) {
    cli, err := etcdclient.New(etcdclient.Config{
        Endpoints: strings.Split(os.Getenv("ETCD_ENDPOINTS"), ","),  // e.g. "etcd:2379"
    })
    if err != nil {
        return nil, err
    }
    return etcd.New(cli), nil
}

func newApp(logger log.Logger, r registry.Registrar, hs *http.Server, gs *grpc.Server) *kratos.App {
    return kratos.New(
        kratos.ID(id),
        kratos.Name(Name),
        kratos.Version(Version),
        kratos.Metadata(map[string]string{}),
        kratos.Logger(logger),
        kratos.Registrar(r),                  // ← 服务端注册
        kratos.Server(hs, gs),
    )
}
```

`kratos.App.Start()` 会自动把 HTTP + gRPC 的监听地址写到 etcd 的 `kratos/<service-name>/<instance-id>`
下；`Stop()` 时自动注销。

### 客户端发现

```go
// internal/data/inventory_client.go
func newDiscovery() (registry.Discovery, error) {
    cli, err := etcdclient.New(etcdclient.Config{
        Endpoints: strings.Split(os.Getenv("ETCD_ENDPOINTS"), ","),
    })
    if err != nil {
        return nil, err
    }
    return etcd.New(cli), nil
}

func NewInventoryClient(r registry.Discovery, logger log.Logger) (biz.InventoryRepo, func(), error) {
    conn, err := grpc.DialInsecure(context.Background(),
        grpc.WithEndpoint("discovery:///inventory-svc"),   // ← 关键：discovery scheme
        grpc.WithDiscovery(r),                              // ← 注入 Discovery 实现
        grpc.WithMiddleware(tracing.Client()),
        grpc.WithTimeout(2*time.Second),
    )
    if err != nil {
        return nil, nil, err
    }
    cleanup := func() { _ = conn.Close() }
    return &inventoryClient{cli: v1.NewInventoryClient(conn)}, cleanup, nil
}
```

`discovery:///inventory-svc` 里**三个斜杠**很重要——前两个是 scheme 分隔，第三个是 authority（留空），
然后是服务名。拼错会拿到空节点。

## 🔴 CRITICAL: 负载均衡默认走 p2c，不要改成 round-robin

Kratos 客户端默认 `p2c`（Power of Two Choices），根据节点历史 RTT + 错误率动态选择。相比 round-robin：

- 慢节点会被**自动降权**，不均匀分配不会踩到恶化节点
- 故障节点会被**淘汰出选择池**（见 `resilience.md` 的 selector 熔断）
- 不需要对下游延迟分布做任何假设

```go
// ❌ WRONG: round-robin 在节点 RTT 差异大时表现糟糕
grpc.DialInsecure(ctx, grpc.WithBalancerName("round_robin"))

// ✅ CORRECT: 保持默认 p2c
grpc.DialInsecure(ctx, grpc.WithEndpoint("discovery:///xxx"), grpc.WithDiscovery(r))
```

## 🟡 HIGH: 健康检查 + 优雅下线

Kratos 注册时默认只写入"已启动"，如果进程未正常 Shutdown（kill -9 / OOM），etcd 里的条目要等 lease TTL
超时才会消失（默认约 15 秒），这期间客户端仍会把流量打给死实例。两条措施：

1. **信号捕获 + 优雅下线**：`kratos.App.Stop(ctx)` 会主动 `Deregister`，让发现端立刻剔除节点
2. **Readiness endpoint**：`/healthz` 返回本节点真实状态（DB 连接、依赖健康）；部署平台（K8s）据此下线

```go
// cmd/server/main.go（骨架已有 graceful shutdown 的脚手架，下面是补充示例）
sigs := make(chan os.Signal, 1)
signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM)

go func() {
    <-sigs
    stopCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
    defer cancel()
    _ = app.Stop()  // 触发 Deregister + 关闭 server
    _ = cancel      // 避免 lint 报 unused
    _ = stopCtx
}()
```

## 🟡 HIGH: 元数据与版本灰度

注册时带上 `kratos.Metadata(map[string]string{"version": "v1", "region": "cn-east"})`，客户端用
`filter.Version("v1")` 做灰度定向路由：

```go
import "github.com/go-kratos/kratos/v2/selector/filter"

grpc.DialInsecure(ctx,
    grpc.WithEndpoint("discovery:///inventory-svc"),
    grpc.WithDiscovery(r),
    grpc.WithNodeFilter(filter.Version("v1")),   // 只打到 version=v1 的节点
)
```

灰度发布标准流程：

1. 新版实例以 `version=canary` 注册
2. 内部调用方按 header 或比例切到 `filter.Version("canary")`
3. 观察 metrics + trace
4. metadata 改 `version=v1`，淘汰旧实例

## 🟢 换注册中心的改动点

以换到 **nacos** 为例：

```go
// go.mod: 新增 github.com/go-kratos/kratos/contrib/registry/nacos/v2
// cmd/server/main.go: 只改两处 import + 构造函数，其他代码不动
import "github.com/go-kratos/kratos/contrib/registry/nacos/v2"

func newRegistrar() (registry.Registrar, error) {
    // nacos 客户端配置...
    return nacos.New(nacosCli), nil
}
```

业务代码、client 拨号方式、wire 绑定都不变——这是 Kratos `registry.Registrar` 抽象的意义。

## 🟢 常用 env 约定

| 变量 | 默认 | 作用 |
|---|---|---|
| `ETCD_ENDPOINTS` | `etcd:2379` | etcd 集群地址，逗号分隔 |
| `ETCD_USERNAME` / `ETCD_PASSWORD` | — | 带认证时使用 |
| `SERVICE_VERSION` | `v1` | 注册到 metadata，灰度依据 |
| `SERVICE_REGION` | — | 可选，跨区域调度时使用 |

读取集中在 `newRegistrar()` 和 `newDiscovery()`，不在业务层 `os.Getenv`。

## 🟢 本地不装 etcd 怎么办

开发期可以用 **memory registry**（Kratos 自带），单进程内 Register/Discovery 自环：

```go
import "github.com/go-kratos/kratos/v2/registry/memory"

r := memory.NewRegistry()
// 同时作为 Registrar 和 Discovery 注入
```

只适合**单机 all-in-one 启动**（比如本地测 bench）。任何涉及多服务的测试都得起 etcd。
