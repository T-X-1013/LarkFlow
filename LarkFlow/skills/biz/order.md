# 电商订单业务规范 (E-commerce Order Business Rules)

## 🔴 核心红线 (CRITICAL)

### 1. 接口幂等性 (Idempotency)
所有创建订单、支付回调、取消订单的接口**必须保证绝对幂等**。
- 必须使用 Redis 分布式锁防止并发请求。
- 必须在数据库中建立唯一索引（如 `request_id` 或 `out_trade_no`）防止重复插入。

```go
// ❌ WRONG: 无并发控制，可能导致重复下单
db.Create(&order)

// ✅ CORRECT: 使用分布式锁 + 唯一键防重
ok, _ := redis.SetNX(ctx, "lock:create_order:"+req.RequestID, 1, 10*time.Second).Result()
if !ok {
    return ErrDuplicateRequest
}
// 业务逻辑...
```

### 2. 库存扣减防超卖 (Inventory Deduction)
绝对禁止出现超卖现象。库存扣减必须在数据库事务中通过 `UPDATE ... WHERE stock >= ?` 实现，或者使用 Redis Lua 脚本预扣减。

```go
// ❌ WRONG: 查出来再扣减，并发下必超卖
var stock int
db.Select("stock").Where("sku_id = ?", skuID).Scan(&stock)
if stock >= count {
    db.Model(&Sku{}).Where("sku_id = ?", skuID).Update("stock", stock-count)
}

// ✅ CORRECT: 数据库层面的乐观锁/原子扣减
res := db.Exec("UPDATE sku SET stock = stock - ? WHERE sku_id = ? AND stock >= ?", count, skuID, count)
if res.RowsAffected == 0 {
    return ErrInsufficientStock
}
```

## 🟡 业务状态机 (State Machine)

订单状态流转必须严格遵守以下顺序，禁止跨状态流转：
1. `PENDING` (待支付)
2. `PAID` (已支付)
3. `SHIPPED` (已发货)
4. `COMPLETED` (已完成)
5. `CANCELLED` (已取消)

**状态流转约束**：
- 只能从 `PENDING` 流转到 `PAID` 或 `CANCELLED`。
- 只能从 `PAID` 流转到 `SHIPPED`。
- 只有处于 `PENDING` 状态的订单才能被取消。

## 🟢 最佳实践

- **订单号生成规则**：禁止使用数据库自增 ID 作为对外展示的订单号。必须使用雪花算法（Snowflake）或 `YYMMDDHHmmss + 用户ID后4位 + 随机数` 来生成，以防止竞争对手推测订单量。
