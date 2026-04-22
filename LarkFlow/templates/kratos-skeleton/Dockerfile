# syntax=docker/dockerfile:1
FROM golang:1.21-alpine AS builder

RUN apk add --no-cache git make protoc

WORKDIR /src
COPY go.mod ./
# go.sum is optional on fresh skeleton; copy if it exists
COPY . .

RUN go mod download

# Install codegen tools pinned to Kratos v2.7.3
RUN go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.33.0 \
    && go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.3.0 \
    && go install github.com/go-kratos/kratos/cmd/protoc-gen-go-http/v2@v2.7.3 \
    && go install github.com/go-kratos/kratos/cmd/protoc-gen-go-errors/v2@v2.7.3 \
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
