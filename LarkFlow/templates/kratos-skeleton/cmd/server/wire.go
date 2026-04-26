//go:build wireinject
// +build wireinject

package main

import (
	"demo-app/internal/biz"
	"demo-app/internal/conf"
	"demo-app/internal/data"
	"demo-app/internal/server"
	"demo-app/internal/service"

	"github.com/go-kratos/kratos/v2"
	"github.com/go-kratos/kratos/v2/log"
	"github.com/google/wire"
)

// wireApp 默认始终包含 server/biz/data/service 四个中心 ProviderSet + newApp。
// 空的 ProviderSet 可以安全保留，Agent 不要把这些 import 或 wire.Build 条目注释掉。
// 当 Agent 新增 domain（例如 order）时，流程：
//  1. internal/biz/order.go：声明 NewOrderUsecase 并加入 biz.ProviderSet
//  2. internal/data/order.go：声明 NewOrderRepo 并加入 data.ProviderSet（同时让 NewData 被串联）
//  3. internal/service/order.go：声明 NewOrderService，在 server 里注册，加入 service.ProviderSet
//  4. 回到本文件，确认 biz/data/service.ProviderSet 仍保持启用
//  5. 跑 make wire 重新生成 wire_gen.go
func wireApp(*conf.Server, *conf.Data, log.Logger) (*kratos.App, func(), error) {
	panic(wire.Build(
		server.ProviderSet,
		biz.ProviderSet,
		data.ProviderSet,
		service.ProviderSet,
		newApp,
	))
}
