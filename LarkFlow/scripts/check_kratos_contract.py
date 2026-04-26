"""
Kratos 骨架契约检查脚本

检查目标：
1. `ProviderSet` 只能定义在中心文件 (`biz.go` / `data.go` / `service.go` / `server.go`)
2. 若中心 `ProviderSet` 已接入具体 domain provider，则 `cmd/server/wire.go` 不得继续注释对应 set
3. 本地模块导入路径必须与 `go.mod` 中的 module 一致
4. 若 proto 引用 `google/api/*.proto` 或 `validate/validate.proto`，对应文件必须位于 `third_party/`
5. 本地 `api/...` 的 `go_package` 必须与 module 前缀一致
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


_PROVIDER_SET_PATTERN = re.compile(r"var\s+ProviderSet\s*=")
_WIRE_NEW_SET_PATTERN = re.compile(r"wire\.NewSet\((.*?)\)", re.DOTALL)
_GO_IMPORT_PATTERN = re.compile(r'"([^"]+)"')
_PROTO_IMPORT_PATTERN = re.compile(r'^\s*import\s+"([^"]+)";', re.MULTILINE)
_PROTO_GO_PACKAGE_PATTERN = re.compile(r'option\s+go_package\s*=\s*"([^"]+)";')
_INVALID_DATA_FIELD_CALL_PATTERN = re.compile(r"\b\w+\.data\.DB\s*\(")


def _read_module_name(project_root: Path) -> str:
    go_mod = project_root / "go.mod"
    if not go_mod.exists():
        return ""
    for line in go_mod.read_text(encoding="utf-8").splitlines():
        if line.startswith("module "):
            return line.split(None, 1)[1].strip()
    return ""


def _provider_set_files(project_root: Path) -> list[Path]:
    matches = []
    for path in project_root.rglob("*.go"):
        if _PROVIDER_SET_PATTERN.search(path.read_text(encoding="utf-8")):
            matches.append(path.relative_to(project_root))
    return sorted(matches)


def _forbidden_provider_sets(project_root: Path) -> list[Path]:
    allowed = {
        Path("internal/biz/biz.go"),
        Path("internal/data/data.go"),
        Path("internal/service/service.go"),
        Path("internal/server/server.go"),
    }
    return [path for path in _provider_set_files(project_root) if path not in allowed]


def _provider_set_tokens(path: Path) -> list[str]:
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8")
    match = _WIRE_NEW_SET_PATTERN.search(content)
    if not match:
        return []
    raw_items = [item.strip() for item in match.group(1).split(",")]
    return [item for item in raw_items if item]


def _provider_set_is_active(project_root: Path, provider_expr: str) -> bool:
    wire_go = project_root / "cmd/server/wire.go"
    if not wire_go.exists():
        return False
    for line in wire_go.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == provider_expr:
            return True
    return False


def _expected_active_provider_sets(project_root: Path) -> list[str]:
    expectations = []
    biz_tokens = _provider_set_tokens(project_root / "internal/biz/biz.go")
    if any(token != "wire.NewSet()" for token in biz_tokens):
        if any(token for token in biz_tokens):
            expectations.append("biz.ProviderSet,")

    data_tokens = _provider_set_tokens(project_root / "internal/data/data.go")
    if any(token not in {"NewData"} and not token.startswith("wire.") for token in data_tokens):
        expectations.append("data.ProviderSet,")

    service_tokens = _provider_set_tokens(project_root / "internal/service/service.go")
    if any(token for token in service_tokens):
        expectations.append("service.ProviderSet,")

    return expectations


def _find_missing_third_party_imports(project_root: Path) -> list[str]:
    roots = [project_root, project_root / "third_party", Path("/usr/include")]
    missing: set[str] = set()
    for proto in list((project_root / "api").rglob("*.proto")) + list((project_root / "internal/conf").rglob("*.proto")):
        content = proto.read_text(encoding="utf-8")
        for imported in _PROTO_IMPORT_PATTERN.findall(content):
            if imported.startswith("google/protobuf/"):
                continue
            if any((root / imported).exists() for root in roots):
                continue
            missing.add(imported)
    return sorted(missing)


def _find_wrong_local_imports(project_root: Path, module_name: str) -> list[str]:
    wrong = []
    for path in project_root.rglob("*.go"):
        for imported in _GO_IMPORT_PATTERN.findall(path.read_text(encoding="utf-8")):
            if imported.startswith("github.com/") and f"/{module_name}/" in imported:
                wrong.append(f"{path.relative_to(project_root)}: {imported}")
            if imported.startswith("internal/") or imported.startswith("api/"):
                wrong.append(f"{path.relative_to(project_root)}: {imported}")
    return sorted(set(wrong))


def _find_wrong_proto_go_packages(project_root: Path, module_name: str) -> list[str]:
    wrong = []
    for path in (project_root / "api").rglob("*.proto"):
        content = path.read_text(encoding="utf-8")
        match = _PROTO_GO_PACKAGE_PATTERN.search(content)
        if not match:
            wrong.append(f"{path.relative_to(project_root)}: missing go_package")
            continue
        go_package = match.group(1)
        if "/api/" in go_package and not go_package.startswith(f"{module_name}/"):
            wrong.append(f"{path.relative_to(project_root)}: {go_package}")
    return sorted(wrong)


def _find_invalid_db_calls(project_root: Path) -> list[str]:
    wrong = []
    data_root = project_root / "internal" / "data"
    if not data_root.exists():
        return wrong
    for path in data_root.rglob("*.go"):
        content = path.read_text(encoding="utf-8")
        if _INVALID_DATA_FIELD_CALL_PATTERN.search(content):
            wrong.append(
                f"{path.relative_to(project_root)}: use Data.DB.WithContext(ctx), not Data.DB(ctx)"
            )
    return sorted(wrong)


def validate_project(project_root: Path) -> list[str]:
    project_root = project_root.resolve()
    findings: list[str] = []

    forbidden_sets = _forbidden_provider_sets(project_root)
    if forbidden_sets:
        findings.append(
            "forbidden ProviderSet definitions: "
            + ", ".join(str(path) for path in forbidden_sets)
        )

    for provider_expr in _expected_active_provider_sets(project_root):
        if not _provider_set_is_active(project_root, provider_expr):
            findings.append(f"wire.go must enable {provider_expr.rstrip(',')}")

    missing_imports = _find_missing_third_party_imports(project_root)
    if missing_imports:
        findings.append(
            "missing third_party proto imports: " + ", ".join(missing_imports)
        )

    module_name = _read_module_name(project_root)
    if module_name:
        wrong_imports = _find_wrong_local_imports(project_root, module_name)
        if wrong_imports:
            findings.append("wrong local Go imports: " + "; ".join(wrong_imports))

        wrong_go_packages = _find_wrong_proto_go_packages(project_root, module_name)
        if wrong_go_packages:
            findings.append("wrong proto go_package: " + "; ".join(wrong_go_packages))

    invalid_db_calls = _find_invalid_db_calls(project_root)
    if invalid_db_calls:
        findings.append("invalid data-layer DB usage: " + "; ".join(invalid_db_calls))

    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Kratos scaffold contract")
    parser.add_argument("target", nargs="?", default="demo-app", help="target project directory")
    args = parser.parse_args(argv)

    findings = validate_project(Path(args.target))
    if findings:
        for finding in findings:
            print(finding, file=sys.stderr)
        return 1

    print(f"Kratos contract OK: {Path(args.target).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
