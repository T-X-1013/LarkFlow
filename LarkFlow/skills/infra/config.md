# Configuration Skills

## 🔴 CRITICAL: Secrets Must Never Be Hardcoded or Committed
API keys, DB passwords, JWT signing keys, and webhook tokens must come from environment variables or a secret manager — never from source code, never from a committed file. `.env` files belong in `.gitignore`; only `.env.example` with placeholders ships.

```go
// ❌ WRONG: Secret compiled into the binary
const larkAppSecret = "cli_a1b2c3d4e5f6"

// ❌ WRONG: Loading a committed file
cfg := loadFromFile("config/prod.yaml") // contains real secrets

// ✅ CORRECT: From environment, with a loader
secret := os.Getenv("LARK_APP_SECRET")
if secret == "" {
    return fmt.Errorf("LARK_APP_SECRET is required")
}
```

## 🔴 CRITICAL: Validate All Required Config at Startup
A missing or malformed config value must crash the process on boot, not surface as a nil-pointer panic three hours later during a request. Fail fast with a clear message listing the offending key.

```go
// ✅ CORRECT
type Config struct {
    DatabaseURL string `env:"DATABASE_URL,required"`
    LarkSecret  string `env:"LARK_APP_SECRET,required"`
    Port        int    `env:"PORT" envDefault:"8000"`
}

func Load() (*Config, error) {
    var c Config
    if err := env.Parse(&c); err != nil {
        return nil, fmt.Errorf("config: %w", err)
    }
    return &c, nil
}
```

## 🟡 HIGH: Environment-Based Layering, Not If-Else
Do not branch on `if env == "prod"` inside business code. Keep a single `Config` struct; let the environment (env vars, k8s ConfigMap, `.env.local`) provide different values. Code stays the same across dev/staging/prod.

```go
// ❌ WRONG
if os.Getenv("ENV") == "prod" {
    timeout = 30 * time.Second
} else {
    timeout = 2 * time.Second
}

// ✅ CORRECT
timeout := cfg.HTTPTimeout // loaded per-env via env var
```

## 🟡 HIGH: Config Is Read Once and Passed Down
Read config once at `main()` and pass the resulting struct (or just the values) into constructors. Do not call `os.Getenv` inside handlers or repositories — it hides dependencies and breaks tests.

```go
// ❌ WRONG: os.Getenv scattered through the codebase
func (s *OrderService) Charge(...) {
    key := os.Getenv("STRIPE_KEY") // hidden dependency
}

// ✅ CORRECT: Injected
func NewOrderService(stripeKey string) *OrderService { ... }
```

## 🟡 HIGH: Provide and Maintain `.env.example`
Every required env var must appear in `.env.example` with a safe placeholder and a one-line comment. New contributors should be able to `cp .env.example .env` and know what to fill in without reading source.

```bash
# .env.example
# Lark application credentials — get from open.feishu.cn
LARK_APP_ID=cli_xxxxxxxxxxxx
LARK_APP_SECRET=xxxxxxxxxxxxxxxx

# Primary database (SQLite for dev, MySQL DSN for prod)
DATABASE_URL=sqlite:///.larkflow/app.db
```
