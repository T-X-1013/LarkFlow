# syntax=docker/dockerfile:1
FROM golang:1.22-alpine AS builder

RUN apk add --no-cache git make protoc protobuf-dev

# 网络稳健性：优先走 goproxy.cn，失败回落到官方代理；sum db 校验在 builder 阶段关闭，
# 避免 GOSUMDB 不可达导致的构建中断（go.sum 一旦落地仍由 go mod download 校验）
ENV GOPROXY=https://goproxy.cn,https://proxy.golang.org,direct
ENV GOSUMDB=off
# 模板未提交 go.sum；用 -mod=mod 允许 go 自动生成/更新 go.sum，避免 wire 的 go/packages 在默认 readonly 模式下加载失败
ENV GOFLAGS=-mod=mod

WORKDIR /src
COPY go.mod ./
# go.sum is optional on fresh skeleton; copy if it exists
COPY . .

RUN go mod download && go mod tidy

# Kratos cmd 子模块（protoc-gen-go-http / protoc-gen-go-errors）tag 与主库不同步，使用 @latest
RUN go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.33.0 \
    && go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.3.0 \
    && go install github.com/go-kratos/kratos/cmd/protoc-gen-go-http/v2@latest \
    && go install github.com/go-kratos/kratos/cmd/protoc-gen-go-errors/v2@latest \
    && go install github.com/google/wire/cmd/wire@v0.6.0

ENV PATH="/go/bin:${PATH}"

RUN make api && make wire && make build

# ----------------------------------------------------------
FROM alpine:3.19

RUN apk add --no-cache ca-certificates tzdata

WORKDIR /app
COPY --from=builder /src/bin/server /app/server
COPY --from=builder /src/configs /app/configs

EXPOSE 8080 9000

CMD ["/app/server", "-conf", "/app/configs"]
