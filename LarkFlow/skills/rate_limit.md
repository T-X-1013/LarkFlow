# Rate Limit Skills

## 🔴 CRITICAL: Limit Per Identity, Not Globally
A single global counter means one abusive client can starve everyone else, and legitimate bursts from different users look like abuse. Key the limiter by user ID / API key / IP — whichever identifies the caller.

```go
// ❌ WRONG: One bucket for the whole service
var limiter = rate.NewLimiter(100, 200)
func handler(c *gin.Context) {
    if !limiter.Allow() { c.AbortWithStatus(429); return }
}

// ✅ CORRECT: Per-identity limiter
type Limiters struct {
    mu sync.Mutex
    m  map[string]*rate.Limiter
}
func (l *Limiters) get(key string) *rate.Limiter {
    l.mu.Lock(); defer l.mu.Unlock()
    if v, ok := l.m[key]; ok { return v }
    v := rate.NewLimiter(10, 20) // 10 rps, burst 20
    l.m[key] = v
    return v
}
```

## 🔴 CRITICAL: Never "Rate Limit" by `time.Sleep`
Sleeping inside a handler ties up a goroutine, a DB connection, and a socket. Under load it is a denial-of-service on yourself. Reject with `429` immediately and let the client back off.

```go
// ❌ WRONG
if overLimit(userID) {
    time.Sleep(500 * time.Millisecond) // blocks the handler
}

// ✅ CORRECT
if !limiters.get(userID).Allow() {
    c.Header("Retry-After", "1")
    c.AbortWithStatus(http.StatusTooManyRequests)
    return
}
```

## 🟡 HIGH: Use Redis for Multi-Instance Deployments
In-memory limiters reset per process and are bypassed by round-robin load balancing. For any service with more than one replica, move the counter to Redis (`INCR` + `EXPIRE`, or a token-bucket Lua script).

```go
// ✅ CORRECT: Fixed-window via Redis
func Allow(ctx context.Context, rdb *redis.Client, key string, limit int, window time.Duration) (bool, error) {
    n, err := rdb.Incr(ctx, key).Result()
    if err != nil { return false, err }
    if n == 1 {
        rdb.Expire(ctx, key, window)
    }
    return n <= int64(limit), nil
}
```

## 🟡 HIGH: Return `429` + `Retry-After`, Not `500` or `403`
Clients and CDNs understand `429 Too Many Requests` with a `Retry-After` header and will back off automatically. Other status codes either look like bugs or trigger retry storms.

```go
// ✅ CORRECT
c.Header("Retry-After", strconv.Itoa(resetSeconds))
c.Header("X-RateLimit-Limit", "60")
c.Header("X-RateLimit-Remaining", "0")
c.AbortWithStatus(http.StatusTooManyRequests)
```

## 🟡 HIGH: Tier the Limits by Endpoint Cost
A `POST /login` (expensive, abuse-prone) should have a tighter limit than `GET /health`. Do not apply one flat RPS to everything — mount different middlewares on different route groups.

```go
// ✅ CORRECT
r.POST("/login",    RateLimit("login",  5,  time.Minute), loginHandler)   // 5/min
r.POST("/orders",   RateLimit("write", 60, time.Minute), createOrder)     // 60/min
r.GET("/products",  RateLimit("read", 600, time.Minute), listProducts)    // 600/min
```
