# Idempotency Skills

## 🔴 CRITICAL: All Non-GET Write Endpoints Must Be Idempotent
Networks retry. Clients retry. Webhooks retry. A `POST /orders` that creates two orders because the client timed out and retried is a bug, not a feature. Every write endpoint must either be naturally idempotent or accept an idempotency key.

```go
// ❌ WRONG: Naive create — a retry creates a second row
func createOrder(c *gin.Context) {
    order := parse(c)
    db.Create(&order)
    c.JSON(200, order)
}

// ✅ CORRECT: Idempotency-Key is required and deduplicated
func createOrder(c *gin.Context) {
    key := c.GetHeader("Idempotency-Key")
    if key == "" { c.AbortWithStatus(400); return }
    if existing, ok := idem.Get(ctx, key); ok {
        c.JSON(200, existing); return
    }
    order := parse(c)
    db.Create(&order)
    idem.Save(ctx, key, order, 24*time.Hour)
    c.JSON(200, order)
}
```

## 🔴 CRITICAL: Dedup via Storage, Not Application Memory
An in-process map loses state on restart and does not dedupe across replicas. Use Redis `SETNX` with a TTL, or a DB table with a unique index on the idempotency key.

```go
// ✅ CORRECT: Redis SETNX — atomic claim
ok, err := rdb.SetNX(ctx, "idem:"+key, "processing", 24*time.Hour).Result()
if err != nil { return err }
if !ok {
    // Someone else is processing or already processed
    return loadPreviousResult(ctx, key)
}

// ✅ CORRECT: DB unique constraint
// CREATE UNIQUE INDEX idx_idem_key ON idempotency_records(key);
```

## 🟡 HIGH: Store the Response, Not Just the Key
Recording only "this key was seen" means a retry has no way to get the original result back — the client sees a 409 or a fresh execution. Persist the response payload (or a pointer to the created resource) alongside the key.

```go
// ✅ CORRECT
type IdemRecord struct {
    Key        string `gorm:"uniqueIndex"`
    StatusCode int
    Response   []byte
    CreatedAt  time.Time
}
```

## 🟡 HIGH: Webhook Handlers Must Dedupe on Provider Event ID
Lark, Stripe, and most webhook providers retry on non-2xx and may deliver the same event twice even on success. Use the provider's `event_id` as the idempotency key; the first delivery does the work, the rest return 200 OK immediately.

```go
// ✅ CORRECT
eventID := r.Header.Get("X-Lark-Request-Nonce") // or body.header.event_id
if seen, _ := idem.Exists(ctx, "lark:"+eventID); seen {
    w.WriteHeader(200); return
}
idem.Mark(ctx, "lark:"+eventID, 24*time.Hour)
handleEvent(ctx, body)
```

## 🟡 HIGH: Key Scope Must Include the User / Tenant
Idempotency keys from different users must not collide. Always namespace: `idem:{user_id}:{key}` or `idem:{tenant}:{key}`. A bare `key` that a client reused from another request can accidentally return another user's response.

```go
// ❌ WRONG
rdb.SetNX(ctx, key, ...)

// ✅ CORRECT
rdb.SetNX(ctx, fmt.Sprintf("idem:%d:%s", userID, key), ...)
```
