import tempfile
import unittest
from pathlib import Path


def _template_root() -> Path:
    return Path(__file__).resolve().parents[1] / "templates" / "kratos-skeleton"


def _provider_set_files(root: Path) -> list[Path]:
    matches = []
    for path in root.rglob("*.go"):
        if "var ProviderSet =" in path.read_text(encoding="utf-8"):
            matches.append(path.relative_to(root))
    return sorted(matches)


def _forbidden_domain_provider_sets(root: Path) -> list[Path]:
    allowed = {
        Path("internal/biz/biz.go"),
        Path("internal/data/data.go"),
        Path("internal/service/service.go"),
        Path("internal/server/server.go"),
    }
    return [path for path in _provider_set_files(root) if path not in allowed]


class KratosScaffoldContractTestCase(unittest.TestCase):
    def setUp(self):
        self.root = _template_root()

    def test_required_proto_dependencies_exist(self):
        required = [
            self.root / "third_party/google/api/annotations.proto",
            self.root / "third_party/google/api/http.proto",
            self.root / "third_party/validate/validate.proto",
        ]
        for path in required:
            self.assertTrue(path.is_file(), f"missing required proto dependency: {path}")

    def test_google_api_proto_files_define_go_package(self):
        for relative in [
            "third_party/google/api/annotations.proto",
            "third_party/google/api/http.proto",
        ]:
            content = (self.root / relative).read_text(encoding="utf-8")
            self.assertIn("option go_package =", content, f"{relative} must define go_package")

    def test_template_has_no_domain_level_provider_set_definitions(self):
        self.assertEqual(_forbidden_domain_provider_sets(self.root), [])

    def test_template_wire_go_keeps_center_provider_sets_enabled(self):
        content = (self.root / "cmd/server/wire.go").read_text(encoding="utf-8")
        self.assertIn('"demo-app/internal/biz"', content)
        self.assertIn('"demo-app/internal/data"', content)
        self.assertIn('"demo-app/internal/service"', content)
        self.assertIn("biz.ProviderSet,", content)
        self.assertIn("data.ProviderSet,", content)
        self.assertIn("service.ProviderSet,", content)
        self.assertNotIn("// biz.ProviderSet,", content)
        self.assertNotIn("// data.ProviderSet,", content)
        self.assertNotIn("// service.ProviderSet,", content)

    def test_domain_level_provider_sets_are_detected(self):
        with tempfile.TemporaryDirectory(prefix="provider-set-contract-") as tmp:
            root = Path(tmp)
            (root / "internal/biz").mkdir(parents=True)
            (root / "internal/data").mkdir(parents=True)
            (root / "internal/service").mkdir(parents=True)
            (root / "internal/server").mkdir(parents=True)
            (root / "internal/biz/biz.go").write_text(
                'package biz\nvar ProviderSet = wire.NewSet()\n',
                encoding="utf-8",
            )
            (root / "internal/data/data.go").write_text(
                'package data\nvar ProviderSet = wire.NewSet()\n',
                encoding="utf-8",
            )
            (root / "internal/service/service.go").write_text(
                'package service\nvar ProviderSet = wire.NewSet()\n',
                encoding="utf-8",
            )
            (root / "internal/server/server.go").write_text(
                'package server\nvar ProviderSet = wire.NewSet()\n',
                encoding="utf-8",
            )
            (root / "internal/service/user.go").write_text(
                'package service\nvar ProviderSet = wire.NewSet(NewUserService)\n',
                encoding="utf-8",
            )

            self.assertEqual(
                _forbidden_domain_provider_sets(root),
                [Path("internal/service/user.go")],
            )


if __name__ == "__main__":
    unittest.main()
