package data

import (
	"demo-app/internal/conf"

	"github.com/go-kratos/kratos/v2/log"
	"github.com/google/wire"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

// ProviderSet is data providers.
// Agent: append each repo provider here, e.g.
//
//	wire.NewSet(NewData, NewOrderRepo, NewUserRepo)
var ProviderSet = wire.NewSet(NewData)

type Data struct {
	DB  *gorm.DB
	log *log.Helper
}

func NewData(c *conf.Data, logger log.Logger) (*Data, func(), error) {
	l := log.NewHelper(logger)
	db, err := gorm.Open(sqlite.Open(c.Database.Source), &gorm.Config{})
	if err != nil {
		return nil, nil, err
	}
	cleanup := func() {
		l.Info("closing the data resources")
		sqlDB, _ := db.DB()
		if sqlDB != nil {
			_ = sqlDB.Close()
		}
	}
	return &Data{DB: db, log: l}, cleanup, nil
}
