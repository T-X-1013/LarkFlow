# 消息队列规范 (Message Queue: Kafka 默认，兼顾 RocketMQ/RabbitMQ/Pulsar/NATS)

> MQ 的复杂度不在"怎么发一条消息"，而在**投递语义 / 顺序 / 位点 / 重试 / 毒消息**这五件事上——任何一个做错，
> 轻则重复扣款、重则整个分区卡死。本 skill 只约束 Kratos 骨架下的 Producer/Consumer 语义，与以下 skill 互补、不重叠：
>
> **边界划分**：
> - 入口 QPS 限流 → `governance/rate_limit.md`
> - 消费端幂等去重（同一条消息处理一次） → `governance/idempotency.md`
> - Consumer 调下游抖动（超时/重试/熔断） → `governance/resilience.md`
> - trace_id 跨 Producer/Consumer 透传 → `governance/observability.md`
> - 同步 RPC 调用 → `transport/rpc.md`
> - 本文件：Producer/Consumer 语义、分区键、位点提交、DLQ、outbox
>
> 默认客户端：`github.com/segmentio/kafka-go`（纯 Go，无 CGO）。其他 MQ 差异见文末对比表。

## 🔴 CRITICAL: 默认"至少一次"，消费端必须幂等

Kafka / RocketMQ / RabbitMQ 默认语义都是 **at-least-once**——Producer 重试、Consumer 重平衡、网络抖动都会
让同一条消息被处理多次。禁止在业务代码里假设 exactly-once。

```go
// ❌ WRONG: 直接执行业务副作用，重复消费即重复扣款
func (c *Consumer) Handle(ctx context.Context, msg kafka.Message) error {
    return c.wallet.Deduct(ctx, parse(msg).UserID, parse(msg).Amount)
}

// ✅ CORRECT: 以消息头里的 event_id 作为幂等键（见 governance/idempotency.md）
func (c *Consumer) Handle(ctx context.Context, msg kafka.Message) error {
    eventID := headerValue(msg, "event_id")
    if eventID == "" {
        return fmt.Errorf("missing event_id header, drop to DLQ")
    }
    ok, err := c.idem.Claim(ctx, "mq:"+msg.Topic+":"+eventID, 7*24*time.Hour)
    if err != nil { return err }
    if !ok { return nil } // 已处理过，静默跳过
    return c.wallet.Deduct(ctx, parse(msg).UserID, parse(msg).Amount)
}
```

Kafka **事务/exactly-once 语义只在 Kafka→Kafka 链路内有效**；一旦下游是 DB/HTTP/RPC，必须回落到幂等。

## 🔴 CRITICAL: Producer 必须 `acks=all` + `enable.idempotence=true`

默认 `acks=1` 只等 leader 确认，leader 切换瞬间未同步到 follower 的消息会丢。幂等 producer 防止 Producer
重试造成的单分区内重复。

```go
// ❌ WRONG: 默认 acks=1，宕机窗口内丢消息
w := &kafka.Writer{Addr: kafka.TCP(brokers...), Topic: "orders.events"}

// ✅ CORRECT
w := &kafka.Writer{
    Addr:         kafka.TCP(brokers...),
    Topic:        "orders.events",
    Balancer:     &kafka.Hash{},            // 按 Key 分区（见下条）
    RequiredAcks: kafka.RequireAll,         // acks=all
    Async:        false,                    // 同步 Write，错误才能冒泡
    BatchTimeout: 10 * time.Millisecond,
    // segmentio/kafka-go 的幂等 producer 依赖 client-level 配置；
    // 如果用 confluent-kafka-go，必须设 enable.idempotence=true + max.in.flight=5
}
```

对应 RocketMQ：事务消息 + `SendSync`；RabbitMQ：Publisher Confirm + `mandatory=true`。

## 🔴 CRITICAL: Consumer 关闭 auto-commit，先处理后提交

`enable.auto.commit=true` 的语义是"定时把最新 poll 的 offset 无条件提交"——崩溃时会出现**已提交但未处理**的
消息（丢消息），或者处理了但没提交（重复消费，靠幂等兜）。必须手动提交。

```go
// ❌ WRONG: 自动提交 + rebalance 时未处理完的消息被永久跳过
r := kafka.NewReader(kafka.ReaderConfig{
    Brokers: brokers, GroupID: "order-svc", Topic: "orders.events",
    CommitInterval: time.Second, // 自动提交 = 丢消息风险
})

// ✅ CORRECT: ReadMessage → 处理 → CommitMessages
r := kafka.NewReader(kafka.ReaderConfig{
    Brokers: brokers, GroupID: "order-svc", Topic: "orders.events",
    // CommitInterval 为 0 时，FetchMessage 返回后必须手动 CommitMessages
})
for {
    m, err := r.FetchMessage(ctx)
    if err != nil { return err }
    if err := handle(ctx, m); err != nil {
        // 走 DLQ 分支，见下文；不要 commit，否则会丢消息
        if err := toDLQ(ctx, m, err); err != nil { return err }
    }
    if err := r.CommitMessages(ctx, m); err != nil { return err }
}
```

RocketMQ 对应 `ConsumeOrderlyContext` / `ConsumeConcurrentlyContext` 的返回值；RabbitMQ 对应 `autoAck=false`
+ 显式 `Ack/Nack`。

## 🟡 HIGH: 分区键 = 同实体顺序保证

同一个业务实体（order_id、user_id、account_id）**必须**路由到同一分区，否则 `OrderCreated` 和 `OrderPaid`
可能被不同消费者并发处理，破坏状态机。禁止用随机 key 或不设 key（轮询分区）。

```go
// ❌ WRONG: 无 Key，轮询分区 → 同一订单的事件可能乱序
w.WriteMessages(ctx, kafka.Message{Value: payload})

// ✅ CORRECT: 用 order_id 作分区键
w.WriteMessages(ctx, kafka.Message{
    Key:   []byte(event.OrderID),
    Value: payload,
    Headers: []kafka.Header{
        {Key: "event_id",       Value: []byte(event.ID)},
        {Key: "schema_version", Value: []byte("v1")},
        {Key: "trace_id",       Value: []byte(tracing.TraceID(ctx))},
        {Key: "occurred_at",    Value: []byte(event.OccurredAt.Format(time.RFC3339Nano))},
    },
})
```

**分区数选择**：写入并发上限 = 分区数；消费并行度上限 = 分区数。扩分区会打破旧 Key 的分区映射，只增不减
且上线前规划。

## 🟡 HIGH: 消息 schema：Protobuf + 仅兼容性变更

JSON 看着省事，但字段名拼错、类型变更没人拦得住。Protobuf 的 tag 是强约束。

- 字段**只增不删不改 tag**；删字段改 `reserved`
- 必备 header：`event_id`、`schema_version`、`occurred_at`、`trace_id`
- 消费者必须处理**未知字段**和**缺失可选字段**，不 panic
- 禁止在 payload 里塞大文件（>1MB 改放对象存储传引用 URL）

## 🟡 HIGH: 毒消息进 DLQ，不能阻塞分区

一条反序列化失败 / 业务 panic 的消息，如果原地无限重试，会让**整个分区**停在这里不动，下游彻底断流。
策略：**同步重试 N 次（指数退避）→ 转投 `${topic}.dlq` → commit 原 topic 的 offset 继续消费**。

```go
const maxRetry = 3

func (c *Consumer) handleWithRetry(ctx context.Context, m kafka.Message) error {
    var lastErr error
    for i := 0; i < maxRetry; i++ {
        err := c.handle(ctx, m)
        if err == nil { return nil }
        if !isRetryable(err) { lastErr = err; break } // 参考 resilience.md
        lastErr = err
        time.Sleep(backoff(i, 50*time.Millisecond, 2*time.Second)) // jitter 见 resilience.md
    }
    return c.dlq.Publish(ctx, m, lastErr) // 原样转投 + 记录失败原因到 header
}
```

DLQ 命名约定：`${topic}.dlq`；DLQ 消息必须带 `x-original-topic`、`x-failure-reason`、`x-failed-at` header，
便于人工排查后手动重放。DLQ 自身也是一个 topic，积压要有告警。

## 🟡 HIGH: 消费端并发模型——分区内串行，分区间并行

同一分区内绝不能起 goroutine 并发处理：破坏顺序 + offset 跳序提交。想提速就加分区。

```go
// ❌ WRONG: 破坏同分区顺序 + 位点乱
for {
    m, _ := r.FetchMessage(ctx)
    go handle(ctx, m) // 错！
}

// ✅ CORRECT: 每个分区一个 Reader(GroupID 相同)，kafka-go 自动分区分配
// 如果需要分区内多条并发（顺序不敏感），用 worker pool + 按 key hash 分派，
// 处理完才 CommitMessages，且 commit 必须按 offset 单调递增顺序。
```

## 🟡 HIGH: 优雅关闭——停 poll → 处理完 in-flight → commit → close

收到 SIGTERM 立刻关 Reader 会丢掉正在处理的消息。必须串行：

1. 停止拉取（退出外层 for 循环）
2. 等当前 handler 返回
3. CommitMessages
4. `r.Close()`

在 Kratos 里把 Consumer 封装成 `transport.Server`：

```go
// internal/server/mq.go
type MQServer struct {
    r        *kafka.Reader
    consumer *biz.OrderEventConsumer
    cancel   context.CancelFunc
    done     chan struct{}
}

func (s *MQServer) Start(ctx context.Context) error {
    ctx, s.cancel = context.WithCancel(ctx)
    s.done = make(chan struct{})
    go func() {
        defer close(s.done)
        for {
            m, err := s.r.FetchMessage(ctx)
            if err != nil { return } // ctx 取消正常退出
            if err := s.consumer.Handle(ctx, m); err == nil {
                _ = s.r.CommitMessages(context.Background(), m)
            }
        }
    }()
    return nil
}

func (s *MQServer) Stop(ctx context.Context) error {
    s.cancel()
    <-s.done
    return s.r.Close()
}

// wire.go: ProvideMQServer 后挂到 kratos.Server(mqServer)
```

## 🟡 HIGH: 跨 DB+MQ 原子性用 outbox，不用 XA

"先写库再发消息"和"先发消息再写库"都会在宕机窗口里漏发/错发。正确做法是 **transactional outbox**：

1. 业务事务里把事件写到 `outbox` 表（与业务表同库同事务，天然原子）
2. 独立的 relay worker 轮询 `outbox` 未发送记录 → 发 Kafka → 标记已发
3. relay 崩溃重启只会重发（靠消费端幂等兜底）

```sql
CREATE TABLE outbox (
    id           BIGINT PRIMARY KEY AUTO_INCREMENT,
    aggregate_id VARCHAR(64) NOT NULL,  -- 作为 Kafka partition key
    topic        VARCHAR(128) NOT NULL,
    payload      BLOB NOT NULL,
    headers      JSON,
    created_at   DATETIME NOT NULL,
    published_at DATETIME,              -- NULL 表示未发送
    INDEX idx_unpublished (published_at, id)
);
```

禁止用 XA / 两阶段提交——实现复杂、性能差、故障恢复更难。

## 🟢 顺序 vs 吞吐

单分区严格有序、不可并发 → 吞吐 = 单核。追求吞吐就按 Key 拆分区，让无关实体并行；追求严格全局顺序就
只开一个分区（等于没用 MQ 的扩展性，慎用）。

## 🟢 延迟消息

Kafka 原生不支持，常见方案：按延迟档位建多级 topic（`delay.5s` / `delay.1m` / ...） + 定时转投；或用
RocketMQ / RabbitMQ TTL+DLX / NATS JetStream 的原生延迟能力。选 MQ 时先看这个需求。

## 🟢 MQ 对比速查

| 维度 | Kafka | RocketMQ | RabbitMQ | Pulsar | NATS JetStream |
|---|---|---|---|---|---|
| 顺序 | 分区内 | 队列内 | 队列内 | 分区内 | 流内 |
| 延迟消息 | 不原生 | 原生（18 档） | TTL+DLX | 原生 | 原生 |
| 事务消息 | Kafka→Kafka | 两阶段 | 无 | 有 | 无 |
| 模型 | Pull | Pull/Push | Push | Pull | Pull/Push |
| 典型场景 | 日志/事件流/大吞吐 | 金融订单/事务 | 传统 AMQP 路由 | 多租户/冷热分层 | 云原生轻量 |

## 🟢 与相邻 skill 的边界

| 问题 | 归属 skill |
|---|---|
| 同一条消息处理一次（event_id 去重） | `governance/idempotency.md` |
| Consumer 调下游 RPC 的超时/重试/熔断 | `governance/resilience.md` |
| Producer/Consumer trace_id 透传 | `governance/observability.md`（注入/提取 Kafka Headers） |
| 订单状态机、防超卖 | `domain/order.md`（本 skill 负责事件传输，不管状态机） |
| 消息体里的金额类型 | `domain/payment.md`（int64，分为单位） |
