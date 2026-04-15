# Concurrency Skills

## 🔴 CRITICAL: No Naked Goroutines
Never start a goroutine without a way to control its lifecycle, handle its panics, or wait for its completion.

```go
// ❌ WRONG: Naked goroutine (can leak or crash the app on panic)
go func() {
    doWork()
}()

// ✅ CORRECT: Use errgroup for bounded concurrency and error propagation
import "golang.org/x/sync/errgroup"

eg, ctx := errgroup.WithContext(context.Background())
eg.Go(func() error {
    return doWork(ctx)
})
if err := eg.Wait(); err != nil {
    // handle error
}
```

## 🟡 HIGH: Context Cancellation
Always pass `context.Context` as the first parameter to functions that perform I/O (DB, HTTP, Redis) or long-running operations. Respect context cancellation.

```go
// ✅ CORRECT
func fetchData(ctx context.Context, id int) error {
    select {
    case <-ctx.Done():
        return ctx.Err() // Context cancelled or timed out
    default:
        // Proceed with fetching data
    }
}
```

## 🟡 HIGH: WaitGroup for Fire-and-Forget
If you must run background tasks that don't return errors to the caller, use a `sync.WaitGroup` to ensure graceful shutdown, and recover from panics.

```go
// ✅ CORRECT
var wg sync.WaitGroup
wg.Add(1)
go func() {
    defer wg.Done()
    defer func() {
        if r := recover(); r != nil {
            log.Printf("Recovered from panic: %v", r)
        }
    }()
    backgroundTask()
}()
// Wait during application shutdown
wg.Wait()
```
