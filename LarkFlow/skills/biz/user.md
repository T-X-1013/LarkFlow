# 用户账户业务规范 (User / Account Business Rules)

## 🔴 核心红线 (CRITICAL)

### 1. 密码存储 (Password Storage)
**绝对禁止**明文、MD5、SHA1、或任何无盐哈希存储密码。必须使用 bcrypt（cost ≥ 10）或 argon2id。登录校验使用常量时间比较。

```go
// ❌ WRONG: 明文或弱哈希
user.Password = req.Password
user.Password = fmt.Sprintf("%x", md5.Sum([]byte(req.Password)))

// ✅ CORRECT: bcrypt with cost 12
hash, err := bcrypt.GenerateFromPassword([]byte(req.Password), 12)
if err != nil { return err }
user.PasswordHash = string(hash)

// 登录校验
if err := bcrypt.CompareHashAndPassword([]byte(user.PasswordHash), []byte(req.Password)); err != nil {
    return ErrInvalidCredentials
}
```

### 2. 登录爆破防护 (Anti Brute-Force)
登录接口必须按 `用户名 + IP` 双维度限流。连续 N 次失败后锁定或触发验证码，失败计数持久化（Redis），TTL 15–30 分钟。

```go
// ✅ CORRECT
failKey := fmt.Sprintf("login_fail:%s:%s", username, clientIP)
fails, _ := rdb.Incr(ctx, failKey).Result()
if fails == 1 { rdb.Expire(ctx, failKey, 15*time.Minute) }
if fails > 5 {
    return ErrAccountLocked // or require captcha
}
// 登录成功后 rdb.Del(ctx, failKey)
```

### 3. 注册幂等 (Registration Idempotency)
邮箱 / 手机号 必须在数据库层加唯一索引。并发注册同一标识必须失败，而不是依赖先查询再插入的业务判断。

```go
// ❌ WRONG: 先查后插，并发下会重复
var exist User
if db.Where("email = ?", req.Email).First(&exist).Error == nil {
    return ErrEmailExists
}
db.Create(&user)

// ✅ CORRECT: 依赖唯一索引
// CREATE UNIQUE INDEX idx_user_email ON users(email);
if err := db.Create(&user).Error; err != nil {
    if isUniqueViolation(err) { return ErrEmailExists }
    return err
}
```

## 🟡 认证与会话 (Auth & Session)

### 1. Access Token + Refresh Token
Access token 短期（15 分钟–1 小时），Refresh token 长期（7–30 天）且服务端可撤销（存 Redis/DB）。登出必须使 refresh token 失效。

### 2. 敏感操作需二次认证
改密码、改手机/邮箱、删除账户、提现 — 必须要求当前密码或短信验证码，即便已登录。

```go
// ✅ CORRECT
if err := bcrypt.CompareHashAndPassword(user.PasswordHash, []byte(req.CurrentPassword)); err != nil {
    return ErrReAuthRequired
}
```

### 3. 风控钩子 (Risk Control Hook)
注册、登录、改密码必须有风控埋点：设备指纹、IP 归属、异常时间、多账号同 IP。无需自己实现完整风控，但必须有扩展点（接口/事件）供后续接入。

## 🟢 最佳实践

- **PII 脱敏**：手机号 / 身份证 / 邮箱在日志和非必要接口中必须脱敏（`138****1234`）。
- **用户 ID 对外不用自增**：用雪花 ID 或 UUID，防止遍历和枚举攻击。
- **软删除而非硬删除**：账户删除保留 30 天冷静期（监管要求），`deleted_at` 字段 + 唯一索引加 `WHERE deleted_at IS NULL`。
