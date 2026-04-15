# Database Skills (GORM / standard SQL)

## 🔴 CRITICAL: Prevent SQL Injection
Never concatenate strings to build SQL queries. Always use parameterized queries.

```go
// ❌ WRONG: SQL Injection Risk
db.Raw(fmt.Sprintf("SELECT * FROM users WHERE name='%s'", userName))

// ✅ CORRECT: Parameterized Query
db.Where("name = ?", userName).Find(&users)
```

## 🔴 CRITICAL: Connection/Resource Leaks
If using `database/sql` directly, always close `Rows`.

```go
// ✅ CORRECT
rows, err := db.QueryContext(ctx, "SELECT * FROM users")
if err != nil { return err }
defer rows.Close() // Must defer close
```

## 🟡 HIGH: Transaction Safety
Always defer a rollback when starting a transaction to prevent hanging transactions on panic or early return.

```go
// ✅ CORRECT (GORM example)
tx := db.Begin()
defer func() {
    if r := recover(); r != nil {
        tx.Rollback()
    }
}()
if err := tx.Error; err != nil {
    return err
}

// ... operations ...
if err := tx.Commit().Error; err != nil {
    return err
}
```

## 🟡 HIGH: Pagination for Large Queries
Never query unbounded datasets. Always use `LIMIT` and `OFFSET` (or cursor pagination).

```go
// ❌ WRONG
db.Find(&users)

// ✅ CORRECT
db.Limit(pageSize).Offset(offset).Find(&users)
```
