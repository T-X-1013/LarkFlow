# Auth Skills (JWT / Session)

## 🔴 CRITICAL: Never Accept `alg: none` or Let the Token Pick the Algorithm
JWT libraries historically let attackers flip `alg` to `none` or swap HS256 ↔ RS256 to forge tokens. Pin the expected algorithm when parsing, and fail if it does not match.

```go
// ❌ WRONG: Trusts whatever alg the token claims
token, _ := jwt.Parse(raw, func(t *jwt.Token) (any, error) {
    return secret, nil
})

// ✅ CORRECT: Pin the algorithm
token, err := jwt.Parse(raw, func(t *jwt.Token) (any, error) {
    if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
        return nil, fmt.Errorf("unexpected alg: %v", t.Header["alg"])
    }
    return []byte(cfg.JWTSecret), nil
})
```

## 🔴 CRITICAL: Auth Middleware Must Run Before Business Handlers
Mount the auth middleware on the router group, not inside each handler. A handler that "forgot" to call `requireAuth()` is an open endpoint. Centralize the rule so new routes are protected by default.

```go
// ❌ WRONG: Each handler calls auth manually — one miss leaks an endpoint
r.GET("/orders", func(c *gin.Context) {
    if !checkAuth(c) { return }
    // ...
})

// ✅ CORRECT: Middleware on the protected group
protected := r.Group("/", AuthMiddleware(cfg))
protected.GET("/orders", listOrders)
protected.POST("/orders", createOrder)
```

## 🟡 HIGH: Authorization Belongs at the Handler Boundary, Not Deep in Services
Check "can this user do this action on this resource" at the entry point (handler or middleware). Embedding permission checks inside repositories couples auth to storage and makes audits hard.

```go
// ❌ WRONG: Permission check buried in the repo
func (r *OrderRepo) Get(ctx context.Context, id int) (*Order, error) {
    user := userFromCtx(ctx)
    if user.Role != "admin" { return nil, ErrForbidden }
    // ...
}

// ✅ CORRECT: Handler decides, repo just fetches
func getOrder(c *gin.Context) {
    if !policy.CanReadOrder(user, orderID) {
        c.AbortWithStatus(403); return
    }
    order, _ := repo.Get(ctx, orderID)
}
```

## 🟡 HIGH: Short-Lived Access Tokens + Refresh Tokens
Access tokens should expire quickly (15 min – 1 h). Long-lived refresh tokens live server-side (revocable) and are used to mint new access tokens. Do not issue 30-day access tokens — a leak is then a 30-day breach.

```go
// ✅ CORRECT
access := issueJWT(userID, 15*time.Minute, cfg.JWTSecret)
refresh := issueOpaqueRefresh(userID) // stored in DB/Redis, revocable
```

## 🟡 HIGH: Constant-Time Comparison for Tokens and Signatures
Comparing tokens or HMAC signatures with `==` leaks length/prefix via timing. Use `subtle.ConstantTimeCompare` for any secret comparison, including webhook signature verification.

```go
// ❌ WRONG
if providedSig == expectedSig { ... }

// ✅ CORRECT
if subtle.ConstantTimeCompare([]byte(providedSig), []byte(expectedSig)) == 1 { ... }
```
