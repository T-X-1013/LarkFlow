//go:build wireinject
// +build wireinject

package main

import (
	"demo-app/internal/conf"
	"demo-app/internal/server"

	// Agent: 当 biz / data / service 有了被 newApp 依赖链消费的 provider 后，取消下面对应 import 的注释
	// "demo-app/internal/biz"
	// "demo-app/internal/data"
	// "demo-app/internal/service"

	"github.com/go-kratos/kratos/v2"
	"github.com/go-kratos/kratos/v2/log"
	"github.com/google/wire"
)

// wireApp 的 provider 图初始只包含 server.ProviderSet（构造 HTTP/gRPC server）+ newApp。
// 当 Agent 新增 domain（例如 order）时，流程：
//  1. internal/biz/order.go：声明 NewOrderUsecase 并加入 biz.ProviderSet
//  2. internal/data/order.go：声明 NewOrderRepo 并加入 data.ProviderSet（同时让 NewData 被串联）
//  3. internal/service/order.go：声明 NewOrderService，在 server 里注册，加入 service.ProviderSet
//  4. 回到本文件，取消对应 import + wire.Build 条目的注释
//  5. 跑 make wire 重新生成 wire_gen.go
func wireApp(*conf.Server, *conf.Data, log.Logger) (*kratos.App, func(), error) {
	panic(wire.Build(
		server.ProviderSet,
		// biz.ProviderSet,
		// data.ProviderSet,
		// service.ProviderSet,
		newApp,
	))
}
