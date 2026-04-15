# Skill Routing Table

**Rule**: When the user's requirement or the technical design involves the following keywords, you **MUST IMMEDIATELY** use the `file_editor` tool to read the corresponding `Ref File` before writing any code.

| Keywords / Domain | Ref File | Description |
|-------------------|----------|-------------|
| MySQL, PostgreSQL, SQL, GORM, Database, DB, ORM, Query, Transaction | `skills/database.md` | Database access, SQL injection prevention, transactions, pagination |
| Redis, Cache, Distributed Lock, Pipeline, Expiration | `skills/redis.md` | Redis client usage, key expiration rules, pipelines |
| HTTP, API, REST, Gin, Router, Middleware, Request, Response | `skills/http.md` | HTTP server framework, standard JSON responses, parameter binding |
| Error, Exception, Wrap, fmt.Errorf, Sentinel Error | `skills/error.md` | Error handling, wrapping, and standard error definitions |
| Goroutine, Concurrency, Async, WaitGroup, errgroup, Channel | `skills/concurrency.md` | Safe concurrency, avoiding goroutine leaks, context cancellation |
| 订单, 下单, 支付, 购物车, Order, Payment, Checkout | `skills/biz/order.md` | 电商订单状态机、接口幂等性要求、防超卖库存扣减规范 |

**Path Prefix**: `skills/` (relative to the workspace root)
