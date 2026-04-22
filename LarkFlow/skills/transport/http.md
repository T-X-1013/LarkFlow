# HTTP API Skills (Gin Framework)

## 🔴 CRITICAL: Standard Response Format
All HTTP APIs must return a standardized JSON structure. Do not return raw strings or inconsistent JSON.

```go
// Standard Response Structure
type Response struct {
    Code    int         `json:"code"`    // Business error code (0 = success)
    Message string      `json:"message"` // Human-readable message
    Data    interface{} `json:"data"`    // Payload
}

// ✅ CORRECT (Gin example)
func Success(c *gin.Context, data interface{}) {
    c.JSON(http.StatusOK, Response{
        Code:    0,
        Message: "success",
        Data:    data,
    })
}

func Error(c *gin.Context, httpCode int, errCode int, msg string) {
    c.JSON(httpCode, Response{
        Code:    errCode,
        Message: msg,
        Data:    nil,
    })
}
```

## 🟡 HIGH: Parameter Binding & Validation
Always use framework binding and validation tags instead of manual parsing.

```go
// ✅ CORRECT
type CreateUserReq struct {
    Username string `json:"username" binding:"required,min=3,max=32"`
    Age      int    `json:"age" binding:"gte=0,lte=130"`
}

func CreateUser(c *gin.Context) {
    var req CreateUserReq
    if err := c.ShouldBindJSON(&req); err != nil {
        Error(c, http.StatusBadRequest, 40001, err.Error())
        return
    }
    // ...
}
```
