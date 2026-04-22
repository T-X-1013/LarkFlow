# Error Handling Skills

## 🔴 CRITICAL: Wrap Errors with Context
Do not return raw errors up the stack. Wrap them using `fmt.Errorf` with the `%w` verb to provide traceablity and context.

```go
import "fmt"

// ❌ WRONG
if err != nil { return err }

// ✅ CORRECT
if err != nil { 
    return fmt.Errorf("failed to fetch user %d: %w", userID, err) 
}
```

## 🟡 HIGH: Use Sentinel Errors or Custom Error Types
For errors that need to be checked by the caller (e.g., Not Found, Unauthorized), define sentinel errors at the package level.

```go
// ✅ CORRECT
var ErrUserNotFound = errors.New("user not found")
var ErrInvalidPassword = errors.New("invalid password")

// Later in the caller...
if errors.Is(err, ErrUserNotFound) {
    // handle not found specifically (e.g., return 404)
}
```

## 🟢 BEST PRACTICE: Log Errors at the Top Level
Do not log an error and then return it. This leads to duplicate log entries. Log the error at the highest possible level (e.g., the HTTP handler or worker entry point) and just return it in the lower layers.
