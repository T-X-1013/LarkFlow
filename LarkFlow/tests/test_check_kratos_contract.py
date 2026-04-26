import tempfile
import unittest
from pathlib import Path

from scripts.check_kratos_contract import validate_project


class CheckKratosContractTestCase(unittest.TestCase):
    def _make_project(self) -> Path:
        tmp = tempfile.TemporaryDirectory(prefix="kratos-contract-")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "api/user/v1").mkdir(parents=True)
        (root / "internal/biz").mkdir(parents=True)
        (root / "internal/data").mkdir(parents=True)
        (root / "internal/service").mkdir(parents=True)
        (root / "internal/server").mkdir(parents=True)
        (root / "cmd/server").mkdir(parents=True)
        (root / "third_party/google/api").mkdir(parents=True)
        (root / "third_party/validate").mkdir(parents=True)
        (root / "go.mod").write_text("module demo-app\n\ngo 1.21\n", encoding="utf-8")
        (root / "api/user/v1/user.proto").write_text(
            'syntax = "proto3";\n'
            'import "google/api/annotations.proto";\n'
            'import "validate/validate.proto";\n'
            'option go_package = "demo-app/api/user/v1;v1";\n',
            encoding="utf-8",
        )
        (root / "third_party/google/api/annotations.proto").write_text(
            'syntax = "proto3";\noption go_package = "google.golang.org/genproto/googleapis/api/annotations;annotations";\n',
            encoding="utf-8",
        )
        (root / "third_party/validate/validate.proto").write_text(
            'syntax = "proto2";\n',
            encoding="utf-8",
        )
        (root / "internal/biz/biz.go").write_text(
            'package biz\nimport "github.com/google/wire"\nvar ProviderSet = wire.NewSet(NewUserUsecase)\n',
            encoding="utf-8",
        )
        (root / "internal/data/data.go").write_text(
            'package data\nimport "github.com/google/wire"\nvar ProviderSet = wire.NewSet(NewData, NewUserRepo)\n',
            encoding="utf-8",
        )
        (root / "internal/service/service.go").write_text(
            'package service\nimport "github.com/google/wire"\nvar ProviderSet = wire.NewSet(NewUserService)\n',
            encoding="utf-8",
        )
        (root / "internal/server/server.go").write_text(
            'package server\nimport "github.com/google/wire"\nvar ProviderSet = wire.NewSet(NewHTTPServer, NewGRPCServer)\n',
            encoding="utf-8",
        )
        (root / "cmd/server/wire.go").write_text(
            'package main\n'
            'import (\n'
            '  "demo-app/internal/biz"\n'
            '  "demo-app/internal/data"\n'
            '  "demo-app/internal/service"\n'
            '  "github.com/google/wire"\n'
            ')\n'
            'func wireApp() {\n'
            '  panic(wire.Build(\n'
            '    biz.ProviderSet,\n'
            '    data.ProviderSet,\n'
            '    service.ProviderSet,\n'
            '  ))\n'
            '}\n',
            encoding="utf-8",
        )
        return root

    def test_accepts_valid_project_contract(self):
        root = self._make_project()
        self.assertEqual(validate_project(root), [])

    def test_detects_wrong_module_imports(self):
        root = self._make_project()
        (root / "internal/service/user.go").write_text(
            'package service\nimport v1 "github.com/demo-app/api/user/v1"\nvar _ = v1.User{}\n',
            encoding="utf-8",
        )
        findings = validate_project(root)
        self.assertTrue(any("wrong local Go imports" in item for item in findings))

    def test_detects_wrong_proto_go_package(self):
        root = self._make_project()
        (root / "api/user/v1/user.proto").write_text(
            'syntax = "proto3";\noption go_package = "github.com/demo-app/api/user/v1;v1";\n',
            encoding="utf-8",
        )
        findings = validate_project(root)
        self.assertTrue(any("wrong proto go_package" in item for item in findings))

    def test_detects_commented_out_provider_set_usage(self):
        root = self._make_project()
        (root / "cmd/server/wire.go").write_text(
            'package main\n'
            'import (\n'
            '  "demo-app/internal/biz"\n'
            '  "demo-app/internal/data"\n'
            '  "demo-app/internal/service"\n'
            ')\n'
            'func wireApp() {\n'
            '  // biz.ProviderSet,\n'
            '  // data.ProviderSet,\n'
            '  // service.ProviderSet,\n'
            '}\n',
            encoding="utf-8",
        )
        findings = validate_project(root)
        self.assertTrue(any("wire.go must enable biz.ProviderSet" in item for item in findings))

    def test_detects_invalid_data_db_call_style(self):
        root = self._make_project()
        (root / "internal/data/user.go").write_text(
            'package data\n'
            'import "context"\n'
            'func (r *userRepo) Update(ctx context.Context) error {\n'
            '  return r.data.DB(ctx).Error\n'
            '}\n',
            encoding="utf-8",
        )
        findings = validate_project(root)
        self.assertTrue(any("invalid data-layer DB usage" in item for item in findings))

    def test_allows_gorm_db_method_call_in_new_data_cleanup(self):
        root = self._make_project()
        (root / "internal/data/data.go").write_text(
            'package data\n'
            'import "gorm.io/gorm"\n'
            'type Data struct { DB *gorm.DB }\n'
            'func NewData(db *gorm.DB) *Data {\n'
            '  sqlDB, _ := db.DB()\n'
            '  _ = sqlDB\n'
            '  return &Data{DB: db}\n'
            '}\n',
            encoding="utf-8",
        )
        findings = validate_project(root)
        self.assertFalse(any("invalid data-layer DB usage" in item for item in findings))


if __name__ == "__main__":
    unittest.main()
