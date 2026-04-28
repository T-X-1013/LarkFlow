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
- **`cmd/server/wire.go` 在空骨架下默认只保留 `server.ProviderSet`**：这样模板在尚未新增任何 domain 时也能直接通过 `make wire` / `make build`。当新增 domain 后，再把 `biz.ProviderSet`、`data.ProviderSet`、`service.ProviderSet` 加回 `wire.Build(...)`。
- **Repo 层 DB 入口固定**：`internal/data/*.go` 一律从 `r.data.DB.WithContext(ctx)` 开始查询，禁止写 `r.data.DB(ctx)`。
- **持久化模型映射要显式转型**：如果 persistence model 嵌入 `gorm.Model`，其 `ID` 是 `uint`；映射回 biz struct 时要显式转成目标类型，例如 `int64(po.ID)`。
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
python ../LarkFlow/scripts/check_kratos_contract.py .  # 部署前契约检查
```

## Docker 构建

`Dockerfile` 两阶段：builder 用 `golang:1.22-alpine`，自带固定 revision 的 Kratos codegen 工具，一次性 `make api && make wire && make build`；runtime 用 `alpine:3.19`。

```bash
docker build -t demo-app .
docker run --rm -p 8080:8080 -p 9000:9000 demo-app
```

HTTP 端口 `8080`，gRPC 端口 `9000`。

## 本地可观测性

模板内置了最小 OTEL 接入和一套本地观测栈配置，物化到 `demo-app/` 后可直接使用：

```bash
cd otel
docker compose -f docker-compose.yml up -d --build
```

默认会启动：

- `demo-app`
- `otel-collector`
- `tempo`
- `grafana`
- `prometheus`
- `loki`
- `promtail`

其中：

- `OTEL_EXPORTER_OTLP_ENDPOINT` 未设置时，应用 OTEL 为 no-op，不影响原始启动链路
- 宿主机运行 `LarkFlow` 时，若需要把 `logs/*.jsonl` 和 `logs/*.log` 一并送入 Loki，可设置 `LARKFLOW_LOGS_DIR`
- Grafana 默认账号密码为 `admin / admin`

模板当前是**空骨架**：默认不注册任何业务路由，因此 `http://localhost:8080/` 以及 `/v1/greeter/tao` 返回 `404` 都是正常的。

如果需要验证 trace：

- 先让 Agent 物化并注册真实业务接口
- 或者后续为骨架补一个专用的 `healthz` / `ping` 示例端点

## 已知事项

- **未提交生成物**：`*.pb.go` / `*_grpc.pb.go` / `*_http.pb.go` / `wire_gen.go` 全部通过 `make api` / `make wire` 实时生成。首次构建必须先 `make init && make api && make wire`。
- **宿主 Go 版本**：本骨架 `go.mod` 声明 `go 1.21`，但当前固定 revision 的 Kratos codegen 工具仍建议 Go ≥ 1.22。Docker 构建走 `golang:1.22-alpine` 不受影响；本地 `make init` / `make test` 建议宿主同样升到 Go 1.22+（Phase B 会在 engine 里统一处理）。
- **Kratos codegen 工具版本**：`protoc-gen-go-http` / `protoc-gen-go-errors` / `kratos` CLI 在仓库里是独立 Go module，tag 节奏与主库不同步（主库有 `v2.7.3` 但这些 cmd 子模块没有对应 tag）。因此 `Makefile` 和 `Dockerfile` 统一固定到已验证 revision：`kratos` / `protoc-gen-go-http` 使用 `f149714c1d54`，`protoc-gen-go-errors` 使用 `fb8e43efb207`；主库 Kratos v2.7.3 仍在 `go.mod` 中锁定，运行时行为稳定。
