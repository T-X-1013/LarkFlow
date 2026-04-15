# Redis Skills (go-redis)

## 🔴 CRITICAL: Always Set Expiration
Never set permanent keys unless explicitly required by the business logic. Permanent keys lead to memory leaks.

```go
// ❌ WRONG: Permanent memory usage
rdb.Set(ctx, "user:123", userData, 0)

// ✅ CORRECT: Set expiration (e.g., 1 hour)
rdb.Set(ctx, "user:123", userData, time.Hour)
```

## 🟡 HIGH: Use Pipelines for Batch Operations
When executing multiple independent Redis commands, use pipelines to reduce network round-trips.

```go
// ✅ CORRECT
pipe := rdb.Pipeline()
pipe.Set(ctx, "key1", "value1", time.Hour)
pipe.Incr(ctx, "counter")
_, err := pipe.Exec(ctx)
```

## 🟡 HIGH: Distributed Locks
When using Redis for distributed locks, always use `SetNX` with an expiration time to prevent deadlocks if the client crashes.

```go
// ✅ CORRECT
ok, err := rdb.SetNX(ctx, "lock:resource_name", "owner_id", 10*time.Second).Result()
if err != nil || !ok {
    return errors.New("failed to acquire lock")
}
// Do work...
// Release lock using Lua script to ensure atomicity (only owner can delete)
```
