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

func wireApp(*conf.Server, *conf.Data, log.Logger) (*kratos.App, func(), error) {
	panic(wire.Build(
		server.ProviderSet,
		data.ProviderSet,
		biz.ProviderSet,
		service.ProviderSet,
		newApp,
	))
}
