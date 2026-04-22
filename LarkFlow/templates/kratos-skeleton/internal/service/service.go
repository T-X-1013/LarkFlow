package service

import "github.com/google/wire"

// ProviderSet is service providers.
// Agent: append each service provider here, e.g.
//
//	wire.NewSet(NewOrderService, NewUserService)
var ProviderSet = wire.NewSet()
