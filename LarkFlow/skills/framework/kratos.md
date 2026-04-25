# Kratos 骨架规范 (Kratos v2.7 Skeleton Rules)

> 本项目所有生成到 `demo-app/` 的 Go 代码必须遵守 Kratos 四层布局。Phase 1 Design 前置已把
> `LarkFlow/templates/kratos-skeleton/` 物化到 `demo-app/`，Agent 只需**往已有骨架里补业务代码**，
> 禁止在根目录或非约定位置创建 .go 文件。

## 🔴 CRITICAL: 严禁跨层调用

依赖方向是**单向的**：`api/<domain>/v1/*.proto` → `service` → `biz` → `data` → DB。任何逆向或跨越都是架构错误。

| 层 | 允许依赖 | 禁止依赖 |
|---|---|---|
| `internal/service` | `internal/biz` | `internal/data`、`gorm`、`redis`、HTTP 框架 |
| `internal/biz` | 自己定义的 Repo interface | `internal/data` 具体实现、`internal/service`、HTTP/gRPC 原语 |
| `internal/data` | 数据库驱动、`gorm`、`redis`、`internal/biz` 中定义的 Repo interface | `internal/service` |
| `internal/server` | 注册 Service（`pb.Register<X>HTTPServer`） | 直接访问 biz / data |

```go
// ❌ WRONG: service 绕过 biz 直接查 DB
func (s *OrderService) GetOrder(ctx context.Context, req *v1.GetReq) (*v1.Order, error) {
    var o data.OrderPO
    s.db.First(&o, req.Id)         // 不允许 service 持有 *gorm.DB
    return &v1.Order{Id: o.ID}, nil
}

// ✅ CORRECT: service 调 biz，biz 调 data.Repo
func (s *OrderService) GetOrder(ctx context.Context, req *v1.GetReq) (*v1.Order, error) {
    o, err := s.uc.Get(ctx, req.Id)  // uc 是 *biz.OrderUsecase
    if err != nil {
        return nil, err
    }
    return &v1.Order{Id: o.ID, Amount: o.Amount}, nil
}
```

## 🔴 CRITICAL: 新增一个 domain 必须走完整 5 步

以新增 `order` domain 为例：

```
1. api/order/v1/order.proto          # 定义 service Order { rpc CreateOrder(...) ... }
   → run_bash: cd <target_dir> && make api   # 生成 order.pb.go / order_grpc.pb.go / order_http.pb.go
2. internal/biz/order.go              # OrderUsecase + Repo interface + NewOrderUsecase
   → 把 NewOrderUsecase 加入 biz.ProviderSet
3. internal/data/order.go             # orderRepo struct + NewOrderRepo + 实现 biz.OrderRepo interface
   → 把 NewOrderRepo 加入 data.ProviderSet
4. internal/service/order.go          # OrderService + NewOrderService + 实现 pb.OrderServer
   → 把 NewOrderService 加入 service.ProviderSet
5. internal/server/http.go + grpc.go  # 注册：pb.RegisterOrderHTTPServer(srv, svc) 等
   cmd/server/wire.go                 # 保持 biz/data/service.ProviderSet 常驻启用
   → run_bash: cd <target_dir> && python ../LarkFlow/scripts/check_kratos_contract.py . && make wire && make build
```

**缺任何一步**：编译不过 / wire 报未绑定 / HTTP 路由 404 / gRPC 方法未注册。

## 🔴 CRITICAL: wire ProviderSet 的累积规则

`wire.Build` 中列出的每个 `ProviderSet` 必须有**至少一个 provider 被依赖链消费**，否则 wire 直接拒绝生成。

- 骨架默认始终启用 `server.ProviderSet + biz.ProviderSet + data.ProviderSet + service.ProviderSet + newApp`
- `biz.ProviderSet` / `service.ProviderSet` 允许为空 `wire.NewSet()`；`data.ProviderSet` 至少保留 `NewData`
- Agent 不要把 `cmd/server/wire.go` 中的中心 ProviderSet 改回注释态；新增 domain 时只需要往中心 `ProviderSet` 里追加 provider
- 修改完 `ProviderSet` 后，先跑 `python ../LarkFlow/scripts/check_kratos_contract.py .`，再跑 `make wire` 和 `make build`

## 🟡 HIGH: Repo interface 放在 biz 层

Kratos 的抽象方向：**biz 定义接口**，**data 实现接口**。这样 biz 不依赖具体数据库。

```go
// internal/biz/order.go
type OrderRepo interface {
    Create(ctx context.Context, o *Order) error
    Get(ctx context.Context, id int64) (*Order, error)
}

type OrderUsecase struct {
    repo OrderRepo
    log  *log.Helper
}

func NewOrderUsecase(repo OrderRepo, logger log.Logger) *OrderUsecase {
    return &OrderUsecase{repo: repo, log: log.NewHelper(logger)}
}
```

```go
// internal/data/order.go
type orderRepo struct {
    data *Data
    log  *log.Helper
}

func NewOrderRepo(data *Data, logger log.Logger) biz.OrderRepo {   // 注意返回值是接口
    return &orderRepo{data: data, log: log.NewHelper(logger)}
}

func (r *orderRepo) Create(ctx context.Context, o *biz.Order) error {
    po := convertBizToPO(o)
    return r.data.DB.WithContext(ctx).Create(&po).Error
}
```

- `Data.DB` 是字段，不是函数。Repo 层一律从 `r.data.DB.WithContext(ctx)` 起 query，禁止写 `r.data.DB(ctx)`
- 如果持久化模型嵌入了 `gorm.Model`，其 `ID` 是 `uint`；映射回 biz 结构体时要显式转成 biz 字段类型，例如 `int64(po.ID)`

## 🟡 HIGH: proto 组织与 errors

- 每个 domain 一个目录：`api/<domain>/v1/<domain>.proto`，`option go_package = "demo-app/api/<domain>/v1;v1"`
- 错误用独立的 proto 枚举：`api/<domain>/v1/<domain>_error.proto`，生成 `*_errors.pb.go`；在 biz/service 层用 `v1.ErrorReason_ORDER_NOT_FOUND` 而不是 `errors.New("not found")`
- HTTP 路由用 `google.api.http` 注解：
  ```proto
  import "google/api/annotations.proto";
  service Order {
    rpc CreateOrder(CreateOrderRequest) returns (CreateOrderReply) {
      option (google.api.http) = { post: "/v1/orders", body: "*" };
    }
  }
  ```
  骨架已把 `google/api/annotations.proto` 放在 `third_party/google/api/`，直接 import 即可

## 🟢 配套命令（都在 `<target_dir>` 下跑，不要跑宿主 `go` 命令）

| 命令 | 场景 |
|---|---|
| `make api` | 修改了任何 `.proto` 后必跑 |
| `make wire` | 修改了任何层的 `ProviderSet` 或 wire.go 后必跑 |
| `make build` | 本地编译二进制到 `bin/server` |
| `make test` | 运行 `go test ./...`（Agent 在 Phase 3 用） |
| `make run` | 本地起服务（仅调试；CI/部署走 docker） |

## 🟢 常见错配地雷

1. **conf proto 类型**：`*conf.Server` 里的 HTTP 和 gRPC 字段名叫 `Http` / `Grpc`（Go 风格，不是 `HTTP` 全大写），写代码时写错会编译不过
2. **wireinject 标签**：`cmd/server/wire.go` 开头必须保留 `//go:build wireinject` 和 `// +build wireinject` 两行，删了会让 `go build` 冲突
3. **go.sum 缺失**：首次 `make wire` 失败时先 `go mod tidy` 生成 go.sum，否则 wire 的 `go/packages` 加载报 `invalid package name: ""`
