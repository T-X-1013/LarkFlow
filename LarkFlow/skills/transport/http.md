# HTTP 传输规范 (Kratos transport/http)

> 本项目默认用 **Kratos v2 `transport/http`**（基于 `net/http` + gorilla/mux）；对外 HTTP 接口由 proto 的
> `google.api.http` 注解自动生成路由、绑定与 OpenAPI。业务代码**不要**手写 `*gin.Engine` 或 `*http.ServeMux`。
> Gin 仅保留为"轻量脚本 / 单文件 demo"的 escape hatch，不出现在 `demo-app/` 产物中。

## 🔴 CRITICAL: 路由通过 proto 注解声明，禁止手工挂路由

```proto
// api/order/v1/order.proto
service Order {
  rpc CreateOrder(CreateOrderRequest) returns (CreateOrderReply) {
    option (google.api.http) = {
      post: "/v1/orders"
      body: "*"
    };
  }
  rpc GetOrder(GetOrderRequest) returns (Order) {
    option (google.api.http) = {
      get: "/v1/orders/{id}"
    };
  }
}
```

`make api` 会生成 `order_http.pb.go`，里面有 `RegisterOrderHTTPServer(srv, svc)`；服务端只需在
`internal/server/http.go` 调用一次。

```go
// ❌ WRONG: 跳过 proto 直接 srv.HandleFunc
srv := http.NewServer(...)
srv.HandleFunc("POST /v1/orders", createOrderHandler)   // 手工挂路由，OpenAPI 不同步，trace 属性缺失

// ✅ CORRECT: proto + 生成函数
orderv1.RegisterOrderHTTPServer(srv, orderService)       // 路由、绑定、响应序列化全自动
```

## 🔴 CRITICAL: 错误响应用 errors proto，不要直接 `c.JSON(400, ...)`

Kratos 的错误经过 `*_errors.pb.go` + HTTP encoder 自动映射到：

- HTTP status code（来自 `errors.code` 注解）
- JSON body：`{"code": <grpc.Code>, "reason": "<ENUM_NAME>", "message": "<fmt>", "metadata": {...}}`

```go
// ❌ WRONG: 手工构造 JSON，字段不一致、gRPC 端读不到
c.JSON(400, gin.H{"msg": "stock not enough"})

// ✅ CORRECT: 业务返回 errors proto 生成的错误
return nil, v1.ErrorInsufficientStock("sku=%s, want=%d", sku, qty)
// HTTP 自动回 400，body 含 reason=INSUFFICIENT_STOCK
```

详见 `transport/rpc.md` 的"错误用 errors proto"章节。

## 🔴 CRITICAL: 中间件顺序

`recovery` 必须在**最外层**，`tracing` 次之，业务中间件（auth / ratelimit / metrics）在内。顺序错会导致
panic 不被 recover 或 trace 丢链。

```go
// internal/server/http.go
srv := http.NewServer(
    http.Middleware(
        recovery.Recovery(),       // 1. 最外层兜住 panic
        tracing.Server(),          // 2. 产生根 span，注入 ctx
        logging.Server(logger),    // 3. 结构化访问日志（含 trace_id）
        // auth / ratelimit / metrics 按需加，但都在 tracing 之内
    ),
)
```

## 🟡 HIGH: 参数校验

proto 的 message 已经是结构化的；再用 `protovalidate`（Buf 提供）在 proto 里加 `(buf.validate.field)`
约束，`make api` 生成运行时校验。业务代码**不要**手写 `if req.Name == ""`。

```proto
import "buf/validate/validate.proto";

message CreateOrderRequest {
  string sku       = 1 [(buf.validate.field).string.min_len = 1];
  int32  quantity  = 2 [(buf.validate.field).int32.gt = 0];
}
```

接上 `validate.Middleware()`（Kratos contrib）后，非法请求在进 handler 前就返回 400。

## 🟡 HIGH: 超时与上下文

- 每个 HTTP server 必须设置顶层 `timeout`（见骨架 `configs/config.yaml`）
- 业务代码沿用 `ctx`，不新建 `context.Background()`
- 长任务用 `errgroup.WithContext(ctx)`（见 `lang/concurrency.md`），不要在 handler 里裸 `go func()`

```go
// ✅ CORRECT
func (s *OrderService) CreateOrder(ctx context.Context, req *v1.CreateOrderRequest) (*v1.Order, error) {
    ctx, cancel := context.WithTimeout(ctx, 800*time.Millisecond)
    defer cancel()
    return s.uc.Create(ctx, req.Sku, int(req.Quantity))
}
```

## 🟡 HIGH: 对外暴露的系统端点

健康检查、metrics、pprof **不要**通过 proto 注解；在 `internal/server/http.go` 里单独挂：

```go
import (
    "github.com/go-kratos/kratos/v2/transport/http/healthz"
    "github.com/prometheus/client_golang/prometheus/promhttp"
)

srv.Handle("/healthz", healthz.Handler())
srv.Handle("/metrics", promhttp.Handler())
```

详见 `governance/observability.md`。

## 🟢 JSON 序列化

Kratos 默认按 protobuf JSON（`google.golang.org/protobuf/encoding/protojson`）序列化；与 `encoding/json`
的差异：

- `int64` 默认序列化成**字符串**（避免 JS 精度丢失）；前端要改回数字的，请在 proto 里用 `int32`
- `oneof` 序列化扁平化
- `timestamp.proto` 序列化成 RFC3339 字符串

## 🟢 何时允许用 Gin / 标准库

**都不允许写进 `demo-app/`**。如果确实需要一个独立脚本（例如一次性数据迁移 HTTP 服务），应放在
独立仓库或 `scripts/` 下，不与骨架混合。Reviewer 在 `demo-app/**/*.go` 里发现 `github.com/gin-gonic/gin`
或 `net/http.ListenAndServe` 直接 🔴 block。
