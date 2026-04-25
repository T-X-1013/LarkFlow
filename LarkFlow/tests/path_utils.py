from pathlib import Path


def project_root() -> Path:
    """Return the LarkFlow package root regardless of the test file location."""
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pipeline").is_dir() and (candidate / "agents").is_dir():
            return candidate
    raise RuntimeError("Unable to locate LarkFlow project root")


def repo_root() -> Path:
    return project_root().parent
