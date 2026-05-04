"""Phase 0 结构化需求 schema。

用 dataclass 而非 Pydantic，避免和 `pipeline/core/contracts.py` 的 pydantic
版本混淆；contracts 那边单独再定义一份对外 Pydantic 契约，这里只做内部数据结构。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ApiSketch:
    """草拟的 API 形态；方法/路径不强制，purpose 描述意图。"""

    method: str = ""                  # GET / POST / PUT / DELETE / gRPC / ""
    path: str = ""                    # /users/{id}/nickname 或空
    purpose: str = ""                 # 一句话描述这个接口要做什么

    def to_dict(self) -> dict[str, Any]:
        return {"method": self.method, "path": self.path, "purpose": self.purpose}


@dataclass
class PersistenceHint:
    """持久化层的结构化推断。"""

    needs_storage: bool = False       # 是否需要持久化
    needs_migration: bool = False     # 是否需要 DDL（加字段/建表/加索引）
    tables: list[str] = field(default_factory=list)   # 涉及的表名候选
    notes: str = ""                   # 规则识别出的细节

    def to_dict(self) -> dict[str, Any]:
        return {
            "needs_storage": self.needs_storage,
            "needs_migration": self.needs_migration,
            "tables": list(self.tables),
            "notes": self.notes,
        }


@dataclass
class NfrFlags:
    """非功能性约束开关；用于驱动 Tier-1 触发器。"""

    auth: bool = False
    idempotent: bool = False
    rate_limit: bool = False
    transactional: bool = False
    high_concurrency: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "auth": self.auth,
            "idempotent": self.idempotent,
            "rate_limit": self.rate_limit,
            "transactional": self.transactional,
            "high_concurrency": self.high_concurrency,
        }


@dataclass
class OpenQuestion:
    """需求里未说清、需要 reviewer 澄清的疑问。"""

    text: str = ""
    blocking: bool = False            # True 表示缺这条答案就不该往下走
    candidates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "blocking": self.blocking,
            "candidates": list(self.candidates),
        }


@dataclass
class NormalizedDemand:
    """规范化后的需求，Phase 1/2/4 的权威输入。"""

    raw_demand: str = ""
    goal: str = ""
    out_of_scope: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    apis: list[ApiSketch] = field(default_factory=list)
    persistence: PersistenceHint = field(default_factory=PersistenceHint)
    nfr: NfrFlags = field(default_factory=NfrFlags)
    domain_tags: list[str] = field(default_factory=list)   # ["order","user","payment"] 的交集
    touches_python: bool = False                           # 改动是否落在 LarkFlow Python 代码区
    open_questions: list[OpenQuestion] = field(default_factory=list)
    confidence: float = 1.0                                # 规则版恒为 1.0；LLM 版再细化
    source: str = "rule"                                   # "rule" | "llm" | "hybrid"

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_demand": self.raw_demand,
            "goal": self.goal,
            "out_of_scope": list(self.out_of_scope),
            "entities": list(self.entities),
            "apis": [api.to_dict() for api in self.apis],
            "persistence": self.persistence.to_dict(),
            "nfr": self.nfr.to_dict(),
            "domain_tags": list(self.domain_tags),
            "touches_python": self.touches_python,
            "open_questions": [q.to_dict() for q in self.open_questions],
            "confidence": self.confidence,
            "source": self.source,
        }

    def derived_text(self) -> str:
        """面向 router 的"语义化文本"：把结构化字段拼出一段可被 router 子串匹配的语料。

        这条路径确保规则版 Phase 0 不引入 LLM 依赖也能给 router 提供更干净的输入：
        结构化字段里的关键词（domain_tags / apis.purpose / persistence.notes）会
        覆盖原 NL 里可能缺失的词。
        """
        parts: list[str] = [self.raw_demand, self.goal]
        for api in self.apis:
            if api.method:
                parts.append(api.method)
            if api.path:
                parts.append(api.path)
            if api.purpose:
                parts.append(api.purpose)
        if self.persistence.needs_storage:
            parts.append("数据库 持久化")
        if self.persistence.needs_migration:
            parts.append("migration 建表 加字段")
        if self.persistence.tables:
            parts.extend(self.persistence.tables)
        if self.persistence.notes:
            parts.append(self.persistence.notes)
        if self.nfr.auth:
            parts.append("auth 鉴权")
        if self.nfr.idempotent:
            parts.append("幂等 idempotent")
        if self.nfr.rate_limit:
            parts.append("限流 rate limit")
        if self.nfr.transactional:
            parts.append("事务 transaction")
        if self.nfr.high_concurrency:
            parts.append("并发 concurrency")
        parts.extend(self.domain_tags)
        if self.touches_python:
            parts.append("larkflow pipeline/ python")
        parts.extend(self.entities)
        return "\n".join(p for p in parts if p)

    def render_prompt_block(self) -> str:
        """生成给 Phase 1 system prompt 尾部注入的 Markdown 段。"""
        if not self.raw_demand and not self.goal:
            return ""
        lines: list[str] = [
            "## Normalized Demand (authoritative)",
            "",
            (
                "以下结构化需求由 `pipeline/phase0/normalizer.py` 从自然语言需求中"
                "解析得到。Phase 1 设计必须逐项对齐此清单；若此处缺字段，请在 "
                "`## Open Questions` 中列出，不要自行编造。"
            ),
            "",
        ]
        if self.goal:
            lines.append(f"- **Goal**: {self.goal}")
        if self.entities:
            lines.append(f"- **Entities**: {', '.join(self.entities)}")
        if self.apis:
            lines.append("- **APIs**:")
            for api in self.apis:
                sig = " ".join(p for p in [api.method, api.path] if p)
                if not sig and not api.purpose:
                    continue
                if api.purpose:
                    lines.append(f"  - `{sig or 'TBD'}` — {api.purpose}")
                else:
                    lines.append(f"  - `{sig}`")
        persistence_bits: list[str] = []
        if self.persistence.needs_storage:
            persistence_bits.append("需要持久化")
        if self.persistence.needs_migration:
            persistence_bits.append("需要 DDL 变更")
        if self.persistence.tables:
            persistence_bits.append(f"涉及表：{', '.join(self.persistence.tables)}")
        if self.persistence.notes:
            persistence_bits.append(self.persistence.notes)
        if persistence_bits:
            lines.append(f"- **Persistence**: {'; '.join(persistence_bits)}")
        nfr_bits: list[str] = []
        if self.nfr.auth:
            nfr_bits.append("auth")
        if self.nfr.idempotent:
            nfr_bits.append("idempotent")
        if self.nfr.rate_limit:
            nfr_bits.append("rate_limit")
        if self.nfr.transactional:
            nfr_bits.append("transactional")
        if self.nfr.high_concurrency:
            nfr_bits.append("high_concurrency")
        if nfr_bits:
            lines.append(f"- **NFR**: {', '.join(nfr_bits)}")
        if self.domain_tags:
            lines.append(f"- **Domain tags**: {', '.join(self.domain_tags)}")
        if self.touches_python:
            lines.append("- **Touches Python**: LarkFlow 代码区改动")
        if self.out_of_scope:
            lines.append(f"- **Out of scope**: {'; '.join(self.out_of_scope)}")
        if self.open_questions:
            lines.append("- **Open Questions**:")
            for q in self.open_questions:
                tag = "[BLOCKING] " if q.blocking else ""
                lines.append(f"  - {tag}{q.text}")
        lines.append(f"- **Confidence**: {self.confidence:.2f} (source: {self.source})")
        lines.append("")
        return "\n".join(lines)
