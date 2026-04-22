GOHOSTOS:=$(shell go env GOHOSTOS)
GOPATH:=$(shell go env GOPATH)
VERSION=$(shell git describe --tags --always 2>/dev/null || echo v0.0.0)

# ===========================================================
# Kratos skeleton Makefile
# Agent 常用流程：
#   make init    # 一次性安装代码生成工具
#   make api     # 根据 api/**/*.proto 和 internal/conf/*.proto 生成 Go 代码
#   make wire    # 重新生成 cmd/server/wire_gen.go
#   make build   # 编译二进制到 bin/
#   make test    # go test ./...
#   make run     # 本地运行（需先 make api && make wire）
# ===========================================================

.PHONY: init
init:
	go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.33.0
	go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.3.0
	go install github.com/go-kratos/kratos/cmd/kratos/v2@v2.7.3
	go install github.com/go-kratos/kratos/cmd/protoc-gen-go-http/v2@v2.7.3
	go install github.com/go-kratos/kratos/cmd/protoc-gen-go-errors/v2@v2.7.3
	go install github.com/google/wire/cmd/wire@v0.6.0

.PHONY: api
api:
	@proto_files=$$(find api internal/conf -name '*.proto' 2>/dev/null); \
	if [ -n "$$proto_files" ]; then \
		protoc --proto_path=. \
		       --proto_path=./third_party \
		       --go_out=paths=source_relative:. \
		       --go-grpc_out=paths=source_relative:. \
		       --go-http_out=paths=source_relative:. \
		       --go-errors_out=paths=source_relative:. \
		       $$proto_files; \
	else \
		echo "No .proto files found."; \
	fi

.PHONY: wire
wire:
	cd cmd/server && wire

.PHONY: build
build:
	mkdir -p bin/
	go build -ldflags "-X main.Version=$(VERSION)" -o ./bin/server ./cmd/server

.PHONY: test
test:
	go test ./...

.PHONY: run
run:
	cd cmd/server && go run . -conf ../../configs

.PHONY: all
all: api wire build
