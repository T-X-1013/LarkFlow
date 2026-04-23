# 可观测性 (Observability: Trace / Metric / Log Bridging)

> 本项目默认用 **OpenTelemetry（OTel）+ OTLP gRPC exporter**。trace 导出到 Tempo / Jaeger / SigNoz 都走同一份配置；
> metrics 默认暴露 Prometheus `/metrics`；log 与 trace 的联动通过 `trace_id` / `span_id` 字段（见 `governance/logging.md`）。

## 🔴 CRITICAL: 每个服务都必须注册 tracing middleware

server 和 client 两端都要接。漏掉任何一端都会让 trace 断链。

```go
// ❌ WRONG: 只 server 接 tracing，client 没接 → 跨服务调用看不到串联
grpc.NewServer(grpc.Middleware(tracing.Server()))

// ✅ CORRECT: server + client 都接
import "github.com/go-kratos/kratos/v2/middleware/tracing"

// internal/server/http.go
http.NewServer(http.Middleware(recovery.Recovery(), tracing.Server()))

// internal/server/grpc.go
grpc.NewServer(grpc.ServerOption{/* ... */}, grpc.Middleware(recovery.Recovery(), tracing.Server()))

// internal/data/xxx_client.go（见 skills/transport/rpc.md）
grpc.DialInsecure(ctx, grpc.WithMiddleware(tracing.Client()))
```

## 🔴 CRITICAL: TracerProvider 必须在 `main.go` 启动前初始化，退出前 Shutdown

否则 span 在内存里堆积不被导出，进程崩时全丢。

```go
// cmd/server/main.go
import (
    "go.opentelemetry.io/otel"
    "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
    sdktrace "go.opentelemetry.io/otel/sdk/trace"
    "go.opentelemetry.io/otel/sdk/resource"
    semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
)

func setTracerProvider(ctx context.Context, serviceName, version string) (func(context.Context) error, error) {
    // endpoint 从 env 读，默认本地 otel-collector
    exp, err := otlptracegrpc.New(ctx,
        otlptracegrpc.WithEndpointURL(
            os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),  // e.g. http://otel-collector:4317
        ),
        otlptracegrpc.WithInsecure(),
    )
    if err != nil {
        return nil, err
    }
    tp := sdktrace.NewTracerProvider(
        sdktrace.WithBatcher(exp),
        sdktrace.WithResource(resource.NewWithAttributes(
            semconv.SchemaURL,
            semconv.ServiceName(serviceName),
            semconv.ServiceVersion(version),
        )),
    )
    otel.SetTracerProvider(tp)
    return tp.Shutdown, nil
}

func main() {
    ctx := context.Background()
    shutdown, err := setTracerProvider(ctx, Name, Version)
    if err != nil {
        panic(err)
    }
    defer func() {
        // 5 秒内批量 flush 剩余 span
        shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
        defer cancel()
        _ = shutdown(shutdownCtx)
    }()
    // ... 后续原 main 逻辑
}
```

## 🔴 CRITICAL: trace_id 必须写进日志

log 只有时间戳和业务字段是不够的；没有 trace_id 就没法从一条错误日志反查完整调用链。`logging.md`
已规定字段名叫 `trace_id`。

```go
// ❌ WRONG: 日志里没有 trace_id，跨服务定位靠肉眼拼时间
log.NewHelper(logger).Infof("create order: %d", id)

// ✅ CORRECT: Kratos 的 log.With + tracing middleware 自动注入
import (
    "github.com/go-kratos/kratos/v2/log"
    ktrace "github.com/go-kratos/kratos/v2/middleware/tracing"
)

logger = log.With(logger,
    "ts", log.DefaultTimestamp,
    "caller", log.DefaultCaller,
    "trace_id", ktrace.TraceID(),   // 从 ctx 抽 traceID，没有就空串
    "span_id", ktrace.SpanID(),
)
// 业务代码
log.NewHelper(logger).WithContext(ctx).Infof("create order: %d", id)   // ctx 必传！
```

关键点：**调用 `WithContext(ctx)` 才能让 `TraceID()` 看到当前 span**。忘传 ctx 就退化成空字符串。

## 🟡 HIGH: metrics middleware + Prometheus /metrics

Kratos 内置 `middleware/metrics` 产 RED 指标（Rate / Error / Duration），`prometheus/client_golang` 暴露 `/metrics`。

```go
// internal/server/http.go
import (
    kprom "github.com/go-kratos/kratos/v2/middleware/metrics"
    "github.com/prometheus/client_golang/prometheus/promhttp"
    "go.opentelemetry.io/otel/metric/global"
)

srv := http.NewServer(
    http.Middleware(
        recovery.Recovery(),
        tracing.Server(),
        kprom.Server(
            kprom.WithSeconds(metricRequests),   // Counter
            kprom.WithHistogram(metricSeconds),  // Histogram
        ),
    ),
)
srv.Handle("/metrics", promhttp.Handler())   // Prometheus 抓取点
srv.Handle("/healthz", healthz.Handler())    // liveness / readiness
```

Prometheus 抓取配置（只是示例，不由 Agent 写）：

```yaml
- job_name: demo-app
  static_configs: [{ targets: ['demo-app:8080'] }]
  metrics_path: /metrics
```

## 🟡 HIGH: 采样策略

生产 100% 采样会炸 tempo/jaeger；开发 100% 没问题。

```go
// ❌ WRONG: 固定全采样，QPS 上来后链路系统炸
sdktrace.WithSampler(sdktrace.AlwaysSample())

// ✅ CORRECT: 父 span 决定 + 根 span 按比例（示例 10%）
sdktrace.WithSampler(
    sdktrace.ParentBased(sdktrace.TraceIDRatioBased(0.1)),
)
```

采样比从 env `OTEL_TRACES_SAMPLER_ARG` 读。

## 🟢 常用 env 约定

| 变量 | 默认 | 作用 |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | OTLP gRPC exporter 地址 |
| `OTEL_TRACES_SAMPLER_ARG` | `0.1` | 头部采样比例 |
| `OTEL_SERVICE_NAME` | 同 `kratos.Name` | 资源语义属性 |
| `OTEL_RESOURCE_ATTRIBUTES` | — | 额外 tag，如 `env=prod,region=cn-east` |

读取这些 env 的逻辑集中在 `cmd/server/main.go` 的 `setTracerProvider`，**不要**在业务代码里 `os.Getenv`。

## 🟢 Span 属性的语义约定

按 OTel SemConv 写，不要乱造 key：

- HTTP: `http.method` / `http.route` / `http.status_code`（Kratos middleware 自动）
- RPC: `rpc.system=grpc` / `rpc.service=order.v1.Order` / `rpc.method=CreateOrder`（Kratos middleware 自动）
- DB: 手动打 `db.system=mysql` / `db.statement`（**禁止把 SQL 的参数 inline 进 statement**，会泄漏 PII）
- Custom: `biz.order.id` / `biz.tenant.id`（**禁止**把手机号/身份证号打进 span）

## 🟢 本地观察链路

开发时最小 stack：`otel-collector` + `Tempo`（或 `Jaeger`）+ `Grafana`。`docker-compose` 跑一套：

```yaml
# 示意，不归 Agent 写
services:
  otel-collector: { image: otel/opentelemetry-collector-contrib, ports: ["4317:4317"] }
  tempo:         { image: grafana/tempo,  ports: ["3200:3200"] }
  grafana:       { image: grafana/grafana, ports: ["3000:3000"] }
```

`OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317` 就能看到链路。
