package biz

import "github.com/google/wire"

// ProviderSet is biz providers.
// Agent: append each domain usecase provider here, e.g.
//
//	wire.NewSet(NewOrderUsecase, NewUserUsecase)
var ProviderSet = wire.NewSet()
