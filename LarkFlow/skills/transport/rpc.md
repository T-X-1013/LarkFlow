# gRPC / Kratos RPC 规范 (Inter-Service Call Rules)

> 本骨架里**服务间调用**一律走 Kratos `transport/grpc`；HTTP 只用于对外暴露（见 `transport/http.md`）。
> 所有在 `api/<domain>/v1/*.proto` 里定义的 service 都会生成 `*_grpc.pb.go`（gRPC 服务端 stub）和
> `*_http.pb.go`（HTTP gateway stub），二者共用同一个业务实现。

## 🔴 CRITICAL: 禁止裸用 `grpc.Dial`

服务间调用必须经由 Kratos 的 `transport/grpc` 客户端，它内置了 trace / metrics / logging / recovery /
metadata 透传 / 重试；裸 `grpc.Dial` 等于放弃整条可观测链路。

```go
// ❌ WRONG: 裸 grpc.Dial，没有 trace/metrics/metadata，也不会走 discovery
conn, err := grpc.Dial("order-svc:9000", grpc.WithInsecure())
client := v1.NewOrderClient(conn)

// ✅ CORRECT: Kratos transport/grpc，接 selector + tracing + metadata
import (
    "github.com/go-kratos/kratos/v2/middleware/tracing"
    "github.com/go-kratos/kratos/v2/transport/grpc"
)

conn, err := grpc.DialInsecure(ctx,
    grpc.WithEndpoint("discovery:///order-svc"),   // Q2 之后看 service_discovery.md
    grpc.WithMiddleware(tracing.Client()),
    grpc.WithTimeout(2*time.Second),
)
if err != nil {
    return err
}
client := v1.NewOrderClient(conn)
```

## 🔴 CRITICAL: 超时必须沿调用链传递

Kratos 的 `ctx` 会携带 deadline 沿 gRPC 传下去；服务端收到时 deadline 自动转到 `context.Context`。
**严禁**在服务端代码里 `context.Background()` 吞掉入参 ctx。

```go
// ❌ WRONG: 吃掉上游 deadline，下游查询永不超时
func (s *OrderService) CreateOrder(ctx context.Context, in *v1.CreateReq) (*v1.Order, error) {
    return s.uc.Create(context.Background(), in.Sku, in.Count)  // 吞 ctx
}

// ✅ CORRECT: 一路传 ctx
func (s *OrderService) CreateOrder(ctx context.Context, in *v1.CreateReq) (*v1.Order, error) {
    return s.uc.Create(ctx, in.Sku, in.Count)
}
```

## 🔴 CRITICAL: 错误用 errors proto，不要 `fmt.Errorf`

Kratos 通过 `api/<domain>/v1/<domain>_error.proto` 生成 `*_errors.pb.go`，里面是 `func IsXxx(err) bool` 和
`func ErrorXxx(fmt, args...)`。这套返回值在 gRPC status code、HTTP status code、错误码、日志字段之间
是**自动映射**的；换成 `fmt.Errorf` 就全丢失。

```proto
// api/order/v1/order_error.proto
syntax = "proto3";
package api.order.v1;
import "errors/errors.proto";
option go_package = "demo-app/api/order/v1;v1";

enum ErrorReason {
  option (errors.default_code) = 500;
  ORDER_NOT_FOUND = 0 [(errors.code) = 404];
  INSUFFICIENT_STOCK = 1 [(errors.code) = 400];
}
```

```go
// ❌ WRONG: fmt.Errorf → 对端拿到 codes.Unknown，没有 reason
return nil, fmt.Errorf("order %d not found", id)

// ✅ CORRECT: 生成函数 → gRPC status.Code=NotFound, HTTP 404, Reason="ORDER_NOT_FOUND"
return nil, v1.ErrorOrderNotFound("order %d not found", id)
```

## 🟡 HIGH: metadata 透传跨层上下文

跨 service 调用时，把 `trace_id` / `tenant_id` / `user_id` 这类请求上下文通过 gRPC metadata 带下去，
不要塞 `*v1.Xxx` 请求体。Kratos 的 `metadata` middleware 自动做好了这件事。

```go
// server: cmd/server/wire.go 或 internal/server/grpc.go
import kmd "github.com/go-kratos/kratos/v2/middleware/metadata"

grpc.NewServer(
    grpc.Middleware(
        tracing.Server(),
        kmd.Server(kmd.WithConstants(kmd.Metadata{
            "x-md-global-tenant-id": "", // 声明白名单，避免泄漏
        })),
    ),
)

// client: 拨号时对称添加
grpc.DialInsecure(ctx,
    grpc.WithMiddleware(tracing.Client(), kmd.Client()),
)

// 业务里读取
if md, ok := kmd.FromServerContext(ctx); ok {
    tenant := md.Get("x-md-global-tenant-id")
    _ = tenant
}
```

## 🟡 HIGH: proto 设计约定

- 每个 domain 一个目录：`api/<domain>/v1/<domain>.proto`，`option go_package = "demo-app/api/<domain>/v1;v1"`
- 外部暴露字段用 `snake_case`，proto 生成的 Go 字段自动变 `CamelCase`
- **分页请求**统一字段：`int32 page = 1; int32 page_size = 2;`（与 `skills/transport/pagination.md` 对齐）
- **金额**用 `int64` 分（与 `skills/domain/payment.md` 对齐），不要用 `double` / `float`
- 不要在 proto 里直接暴露数据库枚举值（`int = 0/1/2`），用有语义的 `enum`

## 🟢 客户端初始化的常见模式

Kratos 推荐在 `internal/data/<downstream>_client.go` 里把 gRPC 客户端也当成一个 Repo，由 `NewXxxClient`
注入到 biz 层：

```go
// internal/data/inventory_client.go
type inventoryClient struct {
    cli v1.InventoryClient
}

func NewInventoryClient(r registry.Discovery, logger log.Logger) (biz.InventoryRepo, func(), error) {
    conn, err := grpc.DialInsecure(context.Background(),
        grpc.WithEndpoint("discovery:///inventory-svc"),
        grpc.WithDiscovery(r),
        grpc.WithMiddleware(tracing.Client()),
        grpc.WithTimeout(2*time.Second),
    )
    if err != nil {
        return nil, nil, err
    }
    cleanup := func() { _ = conn.Close() }
    return &inventoryClient{cli: v1.NewInventoryClient(conn)}, cleanup, nil
}

func (c *inventoryClient) Deduct(ctx context.Context, sku string, qty int32) error {
    _, err := c.cli.Deduct(ctx, &v1.DeductReq{Sku: sku, Qty: qty})
    return err
}
```

在 `data.ProviderSet` 追加 `NewInventoryClient`，biz 层对 `biz.InventoryRepo` 接口编程，就像本地
Repo 一样；换 discovery 实现、加熔断都只改 wire 而不改业务。

## 🟢 什么时候只开 gRPC / 只开 HTTP

- **内部服务**：只开 gRPC（`configs/config.yaml` 可以把 `server.http` 留空或只 bind 内网）
- **对外 API**：HTTP + gRPC 双开；proto 的 `google.api.http` 注解把一个方法同时暴露两端，业务只写一份
- 健康检查、Prometheus `/metrics`、pprof：走 HTTP（见 `governance/observability.md`）
