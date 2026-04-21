# Logging Skills

## 🔴 CRITICAL: No `fmt.Println` / `log.Printf` for Application Logs
Never use `fmt.Println`, `fmt.Printf`, or the standard `log` package for application logs. They are unstructured, ungreppable, and cannot be aggregated. Use a structured logger (`slog`, `zap`, `zerolog`) that emits JSON.

```go
// ❌ WRONG: Unstructured, no level, no context
fmt.Println("user login:", userID)
log.Printf("failed to create order: %v", err)

// ✅ CORRECT: Structured JSON with level and fields
import "log/slog"

slog.Info("user login", "user_id", userID)
slog.Error("create order failed", "err", err, "order_id", orderID)
```

## 🔴 CRITICAL: Never Log Secrets or PII in Plaintext
Tokens, passwords, API keys, full card numbers, ID numbers, and raw request bodies that may contain them must never hit the log. A leaked log file becomes a credential dump.

```go
// ❌ WRONG: Secrets leak into logs
slog.Info("calling lark api", "token", accessToken, "body", reqBody)

// ✅ CORRECT: Redact before logging
slog.Info("calling lark api",
    "token_suffix", lastN(accessToken, 4),
    "body_size", len(reqBody),
)
```

## 🟡 HIGH: Every Log Line Must Carry `trace_id` / `demand_id`
Logs without a correlation ID are useless across a pipeline. Inject `trace_id` (or `demand_id` in LarkFlow) into a `context.Context` at the entry point and require handlers to log via a context-aware logger.

```go
// ✅ CORRECT
logger := slog.With("demand_id", demandID, "trace_id", traceID)
ctx = context.WithValue(ctx, loggerKey{}, logger)

// downstream
loggerFromCtx(ctx).Info("phase 2 coding started", "agent", "coder")
```

## 🟡 HIGH: Use Levels Deliberately
`Debug` = developer-only detail; `Info` = normal lifecycle events; `Warn` = recoverable anomaly; `Error` = an operation failed and a human should care. Do not log the same failure at multiple levels as it bubbles up — log once at the boundary that decides it is an error.

```go
// ❌ WRONG: Same error logged three times up the stack
slog.Error("db query failed", "err", err)  // in repo
slog.Error("load user failed", "err", err) // in service
slog.Error("handler failed", "err", err)   // in handler

// ✅ CORRECT: Wrap with context, log once at the top
return fmt.Errorf("load user %d: %w", id, err) // in repo & service
slog.Error("handler failed", "err", err)       // in handler only
```

## 🟡 HIGH: Log Request/Response Metadata, Not Bodies
Log status, latency, size, and a request ID. Avoid dumping full bodies — they blow up disk, leak PII, and are unreadable. If a body is needed for debugging, guard it behind a debug level and a size cap.

```go
// ✅ CORRECT
slog.Info("http request",
    "method", r.Method,
    "path", r.URL.Path,
    "status", status,
    "latency_ms", time.Since(start).Milliseconds(),
    "req_id", reqID,
)
```
