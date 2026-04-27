//go:build wireinject
// +build wireinject

package main

import (
	"demo-app/internal/conf"
	"demo-app/internal/server"

	"github.com/go-kratos/kratos/v2"
	"github.com/go-kratos/kratos/v2/log"
	"github.com/google/wire"
)

// 空骨架默认只注入 server.ProviderSet + newApp，保证模板在“尚未添加任何 domain”
// 的状态下也能通过 make wire / make build。
//
// 当 Agent 新增 domain（例如 order）时，再把对应层的 ProviderSet 加回本文件：
//  1. internal/biz/order.go：声明 NewOrderUsecase 并加入 biz.ProviderSet
//  2. internal/data/order.go：声明 NewOrderRepo 并加入 data.ProviderSet（同时让 NewData 被串联）
//  3. internal/service/order.go：声明 NewOrderService，在 server 里注册，加入 service.ProviderSet
//  4. 回到本文件，把 biz.ProviderSet / data.ProviderSet / service.ProviderSet 加入 wire.Build
//  5. 跑 make wire 重新生成 wire_gen.go
func wireApp(*conf.Server, *conf.Data, log.Logger) (*kratos.App, func(), error) {
	panic(wire.Build(
		server.ProviderSet,
		newApp,
	))
}
