"""Skill feedback digest: 把 telemetry/skill_feedback.jsonl 聚合成人工可看的 backlog。

用法：
  python scripts/skill_feedback_digest.py                      # 打印全量聚合
  python scripts/skill_feedback_digest.py --since 7d           # 仅近 7 天
  python scripts/skill_feedback_digest.py --out docs/SKILL_BACKLOG.md  # 写 backlog 文件（追加、去重）

输出两类 gap:
  - routing gap: suggested_skill 在 injected_skills 里出现率 < 50%  → 路由没覆盖到
  - content gap: suggested_skill 每次都被注入却仍复发 → skill 内容不够

Feedback 行来自 Phase 4 review agent 的 <skill-feedback> XML 块，
由 pipeline.skills.feedback.capture_feedback() 在 reviewing 阶段结束时落盘。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_LOG = Path(__file__).resolve().parents[1] / "telemetry" / "skill_feedback.jsonl"


def _parse_since(s: Optional[str]) -> Optional[float]:
    """'7d' / '48h' / '30m' → epoch seconds 下界；None 表示不过滤。"""
    if not s:
        return None
    unit = s[-1].lower()
    try:
        n = float(s[:-1])
    except ValueError:
        return None
    mult = {"d": 86400, "h": 3600, "m": 60, "s": 1}.get(unit)
    if not mult:
        return None
    return time.time() - n * mult


def _load_rows(path: Path, since_ts: Optional[float]) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if since_ts is not None and float(row.get("ts", 0) or 0) < since_ts:
                continue
            rows.append(row)
    return rows


def _classify(rows: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """按 (gap_type, category, suggested_skill) 聚合；gap_type 优先用行里已有字段。"""
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        # 行里已有 gap_type（capture_feedback 写入时已分类），兜底再算一次
        gap = (r.get("gap_type") or "").lower()
        if gap not in ("routing", "content"):
            suggested = r.get("suggested_skill", "")
            injected = set(r.get("injected_skills", []) or [])
            gap = "content" if (suggested and suggested in injected) else "routing"
        buckets[gap].append(r)
    return buckets


def _render(buckets: Dict[str, List[Dict[str, Any]]]) -> str:
    lines: List[str] = []
    lines.append("# Skill Feedback Digest\n")
    total = sum(len(v) for v in buckets.values())
    lines.append(f"_Total findings: **{total}**_\n")

    for gap in ("routing", "content"):
        items = buckets.get(gap, [])
        if not items:
            continue
        header = {
            "routing": "## Routing gaps — suggested-skill NOT injected (fix: extend tech_tags enum / keyword fallback)",
            "content": "## Content gaps — suggested-skill WAS injected but rule missing (fix: edit skills/*.md)",
        }[gap]
        lines.append(header)
        # 子聚合：按 (category, suggested_skill, severity)
        agg: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
        for r in items:
            key = (
                r.get("category", "") or "(no-category)",
                r.get("suggested_skill", "") or "(no-skill)",
                r.get("severity", "") or "(no-severity)",
            )
            agg[key].append(r)
        # 次数降序
        sorted_keys = sorted(agg.keys(), key=lambda k: len(agg[k]), reverse=True)
        lines.append("")
        lines.append("| count | severity | category | suggested-skill | latest summary |")
        lines.append("|------:|----------|----------|-----------------|----------------|")
        for key in sorted_keys:
            cat, skill, sev = key
            rs = agg[key]
            latest = max(rs, key=lambda r: float(r.get("ts", 0) or 0))
            summary = (latest.get("summary") or "").replace("\n", " ").strip()[:100]
            lines.append(
                f"| {len(rs)} | {sev} | {cat} | `{skill}` | {summary} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def _write_backlog(out: Path, md: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    ts_header = f"\n---\n\n<!-- regenerated at {time.strftime('%Y-%m-%d %H:%M:%S')} -->\n"
    out.write_text(md + ts_header, encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", type=Path, default=DEFAULT_LOG, help="skill_feedback.jsonl path")
    ap.add_argument("--since", default=None, help="window like 7d / 48h / 30m")
    ap.add_argument("--out", type=Path, default=None, help="write markdown to this path instead of stdout")
    args = ap.parse_args(argv)

    since_ts = _parse_since(args.since)
    rows = _load_rows(args.log, since_ts)
    if not rows:
        sys.stderr.write(f"no skill-feedback rows in {args.log}" + (f" since {args.since}" if args.since else "") + "\n")
        return 0

    md = _render(_classify(rows))
    if args.out:
        _write_backlog(args.out, md)
        sys.stderr.write(f"wrote {args.out}\n")
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
