# Skill Routing Table

> **⚠️ Source of truth**: `rules/skill-routing.yaml`. This Markdown file is a
> human-readable mirror — if the two disagree, the YAML wins. When adding or
> changing a route, edit the YAML first, then update this table to match.

**Rule**: When the user's requirement or the technical design involves the following keywords, you **MUST IMMEDIATELY** use the `file_editor` tool to read the corresponding `Ref File` before writing any code. When multiple routes match, read them in descending order of `weight` (business skills default to 1.2, generic to 1.0).

| Keywords / Domain | Ref File | Weight | Description |
|-------------------|----------|--------|-------------|
| MySQL, PostgreSQL, SQL, GORM, Database, 数据库, ORM, Transaction, 事务, Migration | `skills/database.md` | 1.0 | SQL injection prevention, transactions, resource leaks |
| Redis, Cache, 缓存, 分布式锁, Pipeline, Expiration, TTL | `skills/redis.md` | 1.0 | Redis client, key expiration, pipelines |
| HTTP, API, REST, Gin, Router, 路由, 中间件, Request, Response | `skills/http.md` | 1.0 | HTTP framework, JSON responses, parameter binding |
| Error, 错误, Exception, 异常, Wrap, fmt.Errorf, Sentinel | `skills/error.md` | 1.0 | Error wrapping and sentinel errors |
| Goroutine, Concurrency, 并发, Async, WaitGroup, errgroup, Channel, Context | `skills/concurrency.md` | 1.0 | Goroutine lifecycle, context cancellation |
| Log, Logging, 日志, slog, zap, trace_id, 结构化日志 | `skills/logging.md` | 1.0 | Structured JSON logging, trace IDs, PII redaction |
| Config, 配置, Env, Secret, 密钥, dotenv | `skills/config.md` | 1.0 | Env-var config loading, secret handling, startup validation |
| Auth, 认证, 授权, Login, 登录, JWT, Session, OAuth, RBAC, 权限 | `skills/auth.md` | 1.0 | JWT pinning, middleware placement, constant-time compare |
| Rate Limit, 限流, Throttle, 令牌桶, 429, Quota | `skills/rate_limit.md` | 1.0 | Per-identity limiting, 429 semantics, Redis-backed counters |
| Idempotency, 幂等, Dedup, 去重, Retry, 重放, Webhook | `skills/idempotency.md` | 1.0 | Idempotency keys, webhook dedup, response persistence |
| Pagination, 分页, Page, Cursor, Offset, Limit | `skills/pagination.md` | 1.0 | Bounded page size, cursor pagination, stable sort |
| Python, pipeline, tests, 注释, docstring, dataclass | `skills/python-comments.md` | 0.8 | Python 注释与 docstring 规范 (pipeline / tests) |
| 订单, 下单, 购物车, Checkout, 超卖, 库存 | `skills/biz/order.md` | **1.2** | 电商订单状态机、接口幂等、防超卖 |
| 用户, Account, 注册, Register, 密码, Password, 爆破 | `skills/biz/user.md` | **1.2** | 密码 bcrypt、登录防爆破、注册幂等、风控 |
| 支付, Payment, Refund, 退款, 对账, 回调, Callback, Stripe, 微信支付, 支付宝 | `skills/biz/payment.md` | **1.2** | 回调验签 + 幂等、金额 int64、状态机、对账 |

**Path Prefix**: `skills/` (relative to the workspace root)

**Defaults** (read when nothing else matches): `skills/error.md`, `skills/http.md`
