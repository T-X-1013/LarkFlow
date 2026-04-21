# 支付业务规范 (Payment Business Rules)

## 🔴 核心红线 (CRITICAL)

### 1. 回调必须验签 + 幂等
支付渠道（微信 / 支付宝 / Stripe）的异步回调是对外暴露的公网接口，任何人都能 POST。**必须先验签，后处理**；同一 `out_trade_no` / `event_id` 的回调必须幂等，重复回调不得重复发货、重复加余额。

```go
// ❌ WRONG: 直接信任回调体
func payCallback(c *gin.Context) {
    var cb Callback
    c.BindJSON(&cb)
    db.Model(&Order{}).Where("id=?", cb.OrderID).Update("status", "PAID")
}

// ✅ CORRECT: 验签 + 幂等
func payCallback(c *gin.Context) {
    raw, _ := io.ReadAll(c.Request.Body)
    if !verifySignature(raw, c.GetHeader("X-Signature"), cfg.PayPubKey) {
        c.AbortWithStatus(400); return
    }
    var cb Callback
    json.Unmarshal(raw, &cb)

    // 幂等：事务内校验当前状态
    err := db.Transaction(func(tx *gorm.DB) error {
        var o Order
        if err := tx.Where("out_trade_no = ?", cb.OutTradeNo).First(&o).Error; err != nil {
            return err
        }
        if o.Status == "PAID" { return nil } // 已处理，直接返回成功
        if o.Status != "PENDING" { return ErrInvalidState }
        return tx.Model(&o).Updates(map[string]any{
            "status": "PAID", "paid_at": time.Now(),
        }).Error
    })
    if err != nil { c.AbortWithStatus(500); return }
    c.String(200, "success") // 渠道要求的成功响应
}
```

### 2. 金额用整数分，禁止浮点
`float64` 有精度误差（`0.1 + 0.2 != 0.3`），用于金额会累积出错账。所有金额字段必须用 `int64` 存"分"（或最小货币单位），展示时再除。

```go
// ❌ WRONG
type Order struct {
    Amount float64 // 1.1 + 2.2 可能等于 3.3000000000000003
}

// ✅ CORRECT
type Order struct {
    AmountCents int64 // 110 分 = 1.10 元
    Currency    string // "CNY", "USD"
}
```

### 3. 状态机单向流转
订单支付状态必须定义清楚，**只允许单向前进**，不得从 `PAID` 回到 `PENDING`，不得跳过中间态。

```
PENDING → PAID → REFUNDING → REFUNDED
   ↓
CANCELLED (仅 PENDING 可取消)
```

```go
// ✅ CORRECT: 用 UPDATE ... WHERE status=? 保证并发安全
res := db.Exec(
    "UPDATE orders SET status='PAID' WHERE id=? AND status='PENDING'",
    orderID,
)
if res.RowsAffected == 0 { return ErrInvalidState }
```

## 🟡 对账与风控 (Reconciliation & Risk)

### 1. 每日对账任务
凌晨拉取渠道昨日账单，与本地订单按 `out_trade_no` 比对。必须告警：本地有单渠道无、渠道有单本地无、金额不一致三种情况。

### 2. 退款独立建模，不改原订单金额
退款是独立的业务对象（`refunds` 表），一个订单可有多次部分退款。原订单的 `amount_cents` 不可变，退款累计额不得超过。

```go
// ✅ CORRECT
type Refund struct {
    ID          int64
    OrderID     int64  `gorm:"index"`
    AmountCents int64
    Status      string // REQUESTED / SUCCESS / FAILED
    ChannelTxn  string `gorm:"uniqueIndex"` // 渠道退款号
}
```

### 3. 敏感字段加密
持卡人号、银行卡号、身份证号落库必须加密（KMS 或应用层 AES-GCM）。日志禁止出现完整卡号，只留后 4 位。

## 🟢 最佳实践

- **主动查询兜底**：回调可能丢失，要有定时任务对 `PENDING` 超 N 分钟的订单主动调渠道查询接口。
- **回调响应必须是渠道要求的字符串**（微信要 `<xml>...<return_code>SUCCESS</return_code>...</xml>`），不是 JSON，否则渠道会持续重推。
- **out_trade_no 自己生成**：不要复用订单自增 ID；用雪花/UUID，失败后重试可用同一个号码幂等。
