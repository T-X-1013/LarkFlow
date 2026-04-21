# Pagination Skills

## 🔴 CRITICAL: Never Return Unbounded Lists
A `GET /orders` that returns every row will OOM the process and flood the client the day the table crosses a million rows. Every list endpoint must impose a server-side maximum page size regardless of what the client asks for.

```go
// ❌ WRONG
func listOrders(c *gin.Context) {
    var orders []Order
    db.Find(&orders) // no limit
    c.JSON(200, orders)
}

// ✅ CORRECT
const maxPageSize = 100
size := clamp(parseInt(c.Query("page_size"), 20), 1, maxPageSize)
db.Limit(size).Offset(offset).Find(&orders)
```

## 🔴 CRITICAL: Always Validate and Clamp `page_size` / `page`
Trusting raw query params lets a caller send `page_size=1000000` (OOM) or `page=-1` (SQL error, or worse, undefined driver behavior). Parse, clamp to a hard ceiling, and reject negatives.

```go
// ✅ CORRECT
func parsePaging(c *gin.Context) (page, size int) {
    page = max(parseInt(c.Query("page"), 1), 1)
    size = clamp(parseInt(c.Query("page_size"), 20), 1, 100)
    return
}
```

## 🟡 HIGH: Prefer Cursor Pagination for Large / Append-Heavy Tables
`OFFSET N` makes the DB scan and discard N rows — fine at page 5, brutal at page 50 000. For feeds, logs, and any table where new rows keep arriving, use a cursor on an indexed, monotonic column (`id` or `created_at`).

```go
// ❌ WRONG: Slow at high offsets, and skips/duplicates rows as new data arrives
db.Offset(offset).Limit(size).Order("id DESC").Find(&rows)

// ✅ CORRECT: Cursor pagination
var rows []Order
q := db.Limit(size + 1).Order("id DESC")
if cursor != 0 {
    q = q.Where("id < ?", cursor)
}
q.Find(&rows)

hasNext := len(rows) > size
if hasNext { rows = rows[:size] }
nextCursor := 0
if hasNext { nextCursor = rows[len(rows)-1].ID }
```

## 🟡 HIGH: Total Count Is Optional and Explicit
`SELECT COUNT(*)` on a large table is expensive. Do not run it on every list call. Make it an opt-in query param (`?with_total=true`) or return only `has_next`, which is all most UIs actually need.

```go
// ✅ CORRECT
resp := ListResp{Items: rows, HasNext: hasNext}
if c.Query("with_total") == "true" {
    var total int64
    db.Model(&Order{}).Count(&total)
    resp.Total = &total
}
```

## 🟡 HIGH: Keep Sort Order Stable and Indexed
Pagination with a non-deterministic sort (e.g., `ORDER BY status`) will duplicate or skip rows between pages as ties shift. Always include a tiebreaker on a unique column, and make sure the sort columns are indexed.

```go
// ❌ WRONG: Non-unique sort — rows with same status reshuffle between pages
db.Order("status").Limit(20).Offset(offset).Find(&rows)

// ✅ CORRECT: Tiebreaker on primary key
db.Order("status ASC, id ASC").Limit(20).Offset(offset).Find(&rows)
```
