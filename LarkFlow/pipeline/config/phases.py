"""engine 阶段配置（prompt / kickoff / banner）的 YAML 加载层。

数据落在 `LarkFlow/config/phases.yaml`，和代码分离；engine.py 在模块加载时
调用 `load_phase_config()` / `load_phase_banner()` 得到与原 `_PHASE_CONFIG` /
`_PHASE_BANNER` 等价的字典结构。

首次加载后结果缓存；`reload()` 便于测试或热更新。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml


_REQUIRED_PHASES = ("design", "coding", "testing", "reviewing", "deploying")

_cache_raw: Optional[Dict[str, Dict[str, Any]]] = None


def _yaml_path() -> Path:
    """返回 phases.yaml 的绝对路径。

    结构：`<LarkFlow>/pipeline/config/phases.py` → parents[2] == `<LarkFlow>/`
    """
    return Path(__file__).resolve().parents[2] / "config" / "phases.yaml"


def _load_raw() -> Dict[str, Dict[str, Any]]:
    global _cache_raw
    if _cache_raw is not None:
        return _cache_raw

    path = _yaml_path()
    if not path.is_file():
        raise FileNotFoundError(f"phases config not found: {path}")

    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    phases = data.get("phases")
    if not isinstance(phases, dict):
        raise ValueError(f"phases.yaml 顶层必须有 `phases` mapping: {path}")

    missing = [name for name in _REQUIRED_PHASES if name not in phases]
    if missing:
        raise ValueError(f"phases.yaml 缺少阶段定义: {missing}")

    _cache_raw = phases
    return phases


def load_phase_config() -> Dict[str, Dict[str, Any]]:
    """返回与原 `_PHASE_CONFIG` 等价的 `{phase: {prompt, kickoff}}` 字典。"""
    raw = _load_raw()
    return {
        name: {"prompt": spec.get("prompt"), "kickoff": spec.get("kickoff")}
        for name, spec in raw.items()
    }


def load_phase_banner() -> Dict[str, Tuple[int, str]]:
    """返回与原 `_PHASE_BANNER` 等价的 `{phase: (index, label)}` 字典。"""
    raw = _load_raw()
    banner: Dict[str, Tuple[int, str]] = {}
    for name, spec in raw.items():
        index = spec.get("banner_index")
        label = spec.get("banner_label")
        if index is None or not label:
            continue
        banner[name] = (int(index), str(label))
    return banner


def reload() -> None:
    """清除缓存；下次调用 load_* 会重新读 yaml。"""
    global _cache_raw
    _cache_raw = None
