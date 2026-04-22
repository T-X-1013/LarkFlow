# Kratos Skeleton (per-demand template)

LarkFlow 的 Phase 2 Agent 会把这份骨架作为**只读模板**复制到 `<repo>/demo-app/`（即 `target_dir`），再往其中填入业务代码。本目录本身是 git 追踪的，**禁止**在本目录直接写业务代码。

## 分层约定

```
api/<domain>/v1/*.proto        # Agent 新增：对外 HTTP / gRPC 接口定义
internal/
  biz/                         # Agent 新增：领域层 usecase
  conf/                        # 配置 proto（基础设施，不要乱改）
  data/                        # Agent 新增：数据访问 repo
  server/                      # HTTP + gRPC server（基础设施，加新 Service 时在对应文件里注册）
  service/                     # Agent 新增：对 proto service 的 Go 实现
cmd/server/                    # 启动入口 + wire
configs/config.yaml            # 运行时配置
third_party/                   # google/api 等外部 proto
```

### 硬约束

- **禁止跨层调用**：`service` 只能调 `biz`；`biz` 只能调 `data`；`data` 只操作 DB；`server` 不直接访问任何层，只做注册。
- **新增一个 domain** 必须同时出现：`api/<domain>/v1/<domain>.proto` + `internal/biz/<domain>.go` + `internal/data/<domain>.go` + `internal/service/<domain>.go`，并在对应层的 `ProviderSet` 里追加 wire provider。
- **金额** 一律 `int64`（单位：分），不使用 `float`。
- **时间** 传递用 `time.Time`，存储用 `int64` Unix 毫秒。

## 生成工具链（本地开发）

```bash
make init        # 一次性：安装 protoc-gen-* 和 wire
make api         # 从 api/**/*.proto 和 internal/conf/*.proto 生成 Go 代码
make wire        # 生成 cmd/server/wire_gen.go
make build       # go build 到 bin/server
make test        # go test ./...
make run         # 本地启动：-conf ../../configs
```

## Docker 构建

`Dockerfile` 两阶段：builder 用 `golang:1.21-alpine`，自带 codegen 工具，一次性 `make api && make wire && make build`；runtime 用 `alpine:3.19`。

```bash
docker build -t demo-app .
docker run --rm -p 8080:8080 -p 9000:9000 demo-app
```

HTTP 端口 `8080`，gRPC 端口 `9000`。

## 已知事项

- **未提交生成物**：`*.pb.go` / `*_grpc.pb.go` / `*_http.pb.go` / `wire_gen.go` 全部通过 `make api` / `make wire` 实时生成。首次构建必须先 `make init && make api && make wire`。
- **宿主 Go 版本**：本骨架需 Go ≥ 1.21；如果宿主只有旧版本，使用 Docker 构建或在容器内跑测试（Phase B 会在 engine 里统一处理）。
