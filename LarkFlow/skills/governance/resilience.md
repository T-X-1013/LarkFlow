# 韧性规范 (Resilience: Timeout Budget / Retry / Circuit Breaker)

> 韧性三要素——超时 / 重试 / 熔断——任何一个做错都会**放大故障**而不是吸收故障。本 skill 规定 Kratos 骨架下的
> 默认做法，与 `governance/rate_limit.md`（入口限流）、`governance/idempotency.md`（幂等）互补，不重叠。
>
> **边界划分**：
> - 入口保护流量不被打满 → `rate_limit.md`
> - 重放/重试不重复执行 → `idempotency.md`
> - 下游抖动不扩散到上游 → 本文件

## 🔴 CRITICAL: 超时预算（Upstream > Σ Downstream）

上游 ctx 的 deadline 必须大于所有下游调用预算之和，否则重试还没跑完上游就超时了。

```
客户端 HTTP timeout = 800ms
 ├─ order-svc.CreateOrder     总预算 750ms
 │    ├─ inventory.Deduct     单次 200ms × 最多 2 次 = 400ms
 │    └─ user.GetProfile      单次 150ms × 最多 1 次 = 150ms
 │    └─ 余量（DB + 自身开销）≈ 200ms
 └─ 50ms 回传给客户端的余量
```

```go
// ❌ WRONG: 下游超时 > 上游剩余，重试 0 次空跑完
func (uc *OrderUsecase) Create(ctx context.Context, ...) error {
    // 上游 ctx 只剩 300ms，这里设 500ms 没意义
    cctx, cancel := context.WithTimeout(ctx, 500*time.Millisecond)
    defer cancel()
    return uc.inv.Deduct(cctx, ...)
}

// ✅ CORRECT: 取 min(上游剩余, 本级预算)
func (uc *OrderUsecase) Create(ctx context.Context, ...) error {
    budget := 200 * time.Millisecond
    if dl, ok := ctx.Deadline(); ok {
        if remain := time.Until(dl); remain < budget {
            budget = remain  // 上游吃紧时收敛
        }
    }
    cctx, cancel := context.WithTimeout(ctx, budget)
    defer cancel()
    return uc.inv.Deduct(cctx, ...)
}
```

## 🔴 CRITICAL: 重试前必须满足两个前提

1. 调用是**幂等**的（GET / 或写接口带 `Idempotency-Key`，见 `idempotency.md`）
2. 错误是**可重试**的——`codes.Unavailable` / `codes.DeadlineExceeded`，而不是 `codes.InvalidArgument`

裸跑 `for i:=0; i<3; i++ { err := Call(); if err != nil { continue } }` 在非幂等接口上会产生多份副作用；在
业务异常上重试只是把错误多报几次。

```go
// ❌ WRONG: 什么错都重试 + 非幂等
for i := 0; i < 3; i++ {
    err := client.CreateOrder(ctx, req)   // 可能重复下单
    if err == nil { break }
}

// ✅ CORRECT: Kratos middleware 配合 errors proto 的 reason 判定
import (
    "github.com/go-kratos/kratos/v2/errors"
    "google.golang.org/grpc/codes"
    "google.golang.org/grpc/status"
)

func isRetryable(err error) bool {
    if err == nil {
        return false
    }
    // gRPC 层错误
    if s, ok := status.FromError(err); ok {
        switch s.Code() {
        case codes.Unavailable, codes.DeadlineExceeded, codes.ResourceExhausted:
            return true
        }
    }
    // Kratos errors proto：按 reason 判定
    if se := errors.FromError(err); se != nil {
        return se.Code >= 500 && se.Code < 600
    }
    return false
}
```

## 🔴 CRITICAL: 重试间隔必须是指数退避 + 抖动

固定间隔重试在集群失败时会产生**同步风暴**（所有客户端同时重试压垮下游）。必须 jitter。

```go
// ❌ WRONG: 固定 100ms 间隔，1000 个客户端同时踩节奏
time.Sleep(100 * time.Millisecond)

// ✅ CORRECT: exp backoff + full jitter
import "math/rand/v2"

func backoff(attempt int, base, cap time.Duration) time.Duration {
    // base=50ms, cap=2s, attempt=0..3
    d := base << attempt
    if d > cap {
        d = cap
    }
    // full jitter: [0, d)
    return time.Duration(rand.Int64N(int64(d)))
}
```

推荐参数：`base=50ms, cap=2s, max_attempts=3`（含首次）。

## 🟡 HIGH: 熔断用 Kratos `circuitbreaker` middleware，别手写

手写熔断器很容易做错阈值（连续失败 N 次？失败率？窗口大小？）。用官方中间件，配置即可。

```go
// internal/data/inventory_client.go
import (
    "github.com/go-kratos/aegis/circuitbreaker/sre"
    "github.com/go-kratos/kratos/v2/middleware/circuitbreaker"
    "github.com/go-kratos/kratos/v2/transport/grpc"
)

conn, err := grpc.DialInsecure(ctx,
    grpc.WithEndpoint("discovery:///inventory-svc"),
    grpc.WithMiddleware(
        tracing.Client(),
        circuitbreaker.Client(circuitbreaker.WithCircuitBreaker(func() circuitbreaker.CircuitBreaker {
            return sre.NewBreaker(
                sre.WithRequest(100),       // 窗口内至少 100 次才参与判定
                sre.WithBucket(10),         // 窗口分 10 桶
                sre.WithWindow(3*time.Second),
                sre.WithSuccess(0.6),       // 成功率 < 60% 触发
            )
        })),
    ),
)
```

- **窗口太小**：对突发毛刺过敏，误熔断
- **窗口太大**：对真正的故障反应迟钝
- 默认 3 秒 / 100 请求 / 60% 成功率，是 Kratos aegis 的经验值

## 🟡 HIGH: 重试 + 熔断 + 限流的顺序

middleware 链的顺序决定语义，错一步就失效。正确链路：

```
client 端:  tracing → circuitbreaker → retry → ratelimit → rpc call
server 端:  recovery → tracing → ratelimit → logging → metrics → handler
```

- `circuitbreaker` 在 `retry` 外层：熔断打开时直接拒绝，不要重试空转
- `ratelimit` 在 `retry` 内层：每次重试都算一次配额（防止重试把自身限流耗尽）
- 不要把 `retry` 放在 server 端——**重试是客户端职责**，server 端重试只会放大压力

## 🟡 HIGH: 超时层级衰减

跨 N 级调用时，每级扣除一定比例用作本级开销，避免最内层完全没预算：

```
入口 1000ms
 → svcA  拿到 900ms（入口扣 10% 作自身开销 + 回传余量）
   → svcB  拿到 800ms
     → DB  拿到 700ms
```

Kratos middleware 自动向下传递 deadline，业务只需**不吞 ctx**（见 `transport/rpc.md`），层级衰减就自动发生。

## 🟢 与 rate_limit.md / idempotency.md 的边界

| 问题 | 归属 skill | 重点 |
|---|---|---|
| 入口 QPS 限制（/v1/orders 每秒 100） | `rate_limit.md` | token bucket / Redis counter |
| 同一 `Idempotency-Key` 只处理一次 | `idempotency.md` | 唯一索引 / `SETNX` |
| 下游不稳定时不被拖垮（超时 + 熔断 + 退避重试） | 本 skill | timeout budget / circuitbreaker / exp backoff |
| 慢下游占满连接池（bulkhead） | 本 skill 未覆盖 | 一般用独立 gRPC ClientConn 或 `selector` 隔离 |

## 🟢 可选：客户端 selector 熔断（节点级）

当下游有多个实例（见 `service_discovery.md`），`selector` 可以在节点级做短路熔断——连续失败的节点从
负载均衡列表里暂时踢掉，不用等全局熔断器打开。

```go
grpc.DialInsecure(ctx,
    grpc.WithEndpoint("discovery:///inventory-svc"),
    grpc.WithNodeFilter(filter.Version("v1")),  // 版本灰度
    // p2c 默认就带节点级错误统计；无需额外配置
)
```
