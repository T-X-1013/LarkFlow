"""Skill 路由语义通道：向量化 skill 语料并做 cosine 召回。

对外只暴露两个入口：
- `semantic_match(demand_text)`：对一条需求做语义召回，返回 `{skill: score}`。
- `is_enabled()`：env 开关，默认关闭。

设计要点：
- 失败安全：任何异常（API key 缺失、网络错误、JSON 坏）都降级到空召回，router 自动回退到纯关键词通道。
- 缓存优先：skill 语料做一次 sha1，落 telemetry/skill-embeddings.json；命中直接复用。
- Provider 抽象：当前只实现 OpenAI 兼容协议（OpenAI/DashScope/Ark 都走同一个 SDK）；
  Anthropic 不做 embedding API，选它跑主 agent 时这条通道仍可接一个 OPENAI_API_KEY 即可。
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

_LOG = logging.getLogger("larkflow.skill_router.semantic")

# workspace_root = LarkFlow/ 目录本身
_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
_CACHE_PATH = _WORKSPACE_ROOT / "telemetry" / "skill-embeddings.json"
_DEFAULT_MODEL = "text-embedding-3-small"

# 语义召回阈值；通过 LARKFLOW_SEMANTIC_ROUTER_THRESHOLD 覆盖
_DEFAULT_THRESHOLD = 0.45


def is_enabled() -> bool:
    """开关：env LARKFLOW_SEMANTIC_ROUTER_ENABLED in {1,true,yes}。

    默认关闭，保证 PR-4 落盘后 router 行为与 PR-3 完全一致；需要显式开启后才走语义召回。
    """
    val = os.getenv("LARKFLOW_SEMANTIC_ROUTER_ENABLED", "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def threshold() -> float:
    """相似度阈值；非法值回落默认。"""
    raw = os.getenv("LARKFLOW_SEMANTIC_ROUTER_THRESHOLD", "").strip()
    if not raw:
        return _DEFAULT_THRESHOLD
    try:
        val = float(raw)
    except ValueError:
        return _DEFAULT_THRESHOLD
    if not 0.0 <= val <= 1.0:
        return _DEFAULT_THRESHOLD
    return val


# ---------------------------------------------------------------------------
# 语料抽取
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SkillCorpus:
    """单个 skill 的待 embedding 语料。"""

    skill: str       # 相对 workspace_root 的路径，如 skills/infra/redis.md
    title: str       # skill 文档 `# ...` 一级标题
    description: str # YAML 里 routes.description / conditional.reason，可空
    excerpt: str     # skill 文件首段摘要（去代码块）

    @property
    def text(self) -> str:
        """embedding 的实际输入文本。"""
        parts = [self.title, self.description, self.excerpt]
        return "\n".join(p for p in parts if p).strip()

    @property
    def content_hash(self) -> str:
        """语料 sha1，缓存 key；语料变了即失效。"""
        return hashlib.sha1(self.text.encode("utf-8")).hexdigest()


_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_HEADING_RE = re.compile(r"^#{2,6}\s+.*$", re.MULTILINE)


def _read_skill_excerpt(skill_path: Path, max_chars: int = 600) -> tuple[str, str]:
    """读取 skill 文件，返回 (title, excerpt)。

    excerpt 取文件开头去掉代码块与子标题后的前 N 字符，够覆盖第一段语义即可。
    """
    try:
        text = skill_path.read_text(encoding="utf-8")
    except OSError as exc:
        _LOG.warning("read skill failed: %s (%s)", skill_path, exc)
        return "", ""
    title_match = _TITLE_RE.search(text)
    title = title_match.group(1).strip() if title_match else skill_path.stem
    body = text
    if title_match:
        body = text[title_match.end():]
    body = _CODE_BLOCK_RE.sub(" ", body)
    body = _HEADING_RE.sub(" ", body)
    # 压缩多余空白
    body = re.sub(r"\s+", " ", body).strip()
    excerpt = body[:max_chars]
    return title, excerpt


def build_corpora(
    table: dict[str, Any],
    workspace_root: Optional[Path] = None,
) -> list[SkillCorpus]:
    """从路由表收集全部 skill 的语料。

    覆盖 baseline / conditional / routes 三段：baseline 也会被 embed 进去，
    这样即使以后把某个 skill 从 baseline 降级到 conditional，缓存依然复用。

    @params:
        table          : load_routing_table() 返回的 dict
        workspace_root : LarkFlow/ 根目录；None 时使用模块默认
    @return:
        去重后的语料列表；找不到物理文件的 skill 跳过。
    """
    root = workspace_root or _WORKSPACE_ROOT
    seen: dict[str, SkillCorpus] = {}

    def _register(skill: str, description: str) -> None:
        if not skill or skill in seen:
            return
        skill_path = root / skill
        if not skill_path.exists():
            _LOG.warning("skill file missing, skipped: %s", skill)
            return
        title, excerpt = _read_skill_excerpt(skill_path)
        seen[skill] = SkillCorpus(
            skill=skill,
            title=title,
            description=str(description or "").strip(),
            excerpt=excerpt,
        )

    for item in table.get("baseline", []) or []:
        _register(str(item.get("skill", "")), item.get("reason", ""))
    for item in table.get("conditional", []) or []:
        _register(str(item.get("skill", "")), item.get("reason", ""))
    for item in table.get("routes", []) or []:
        _register(str(item.get("skill", "")), item.get("description", ""))

    return list(seen.values())


# ---------------------------------------------------------------------------
# Embedding provider（OpenAI 兼容协议）
# ---------------------------------------------------------------------------

EmbedFn = Callable[[list[str]], list[list[float]]]


def _build_openai_embed_fn() -> Optional[EmbedFn]:
    """构造 OpenAI 兼容的 embedding 调用；缺 key 返回 None。"""
    api_key = os.getenv("LARKFLOW_EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        _LOG.info("semantic router disabled: no embedding API key")
        return None
    base_url = (
        os.getenv("LARKFLOW_EMBEDDING_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or None
    )
    model = os.getenv("LARKFLOW_EMBEDDING_MODEL", _DEFAULT_MODEL)
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        _LOG.warning("openai SDK not installed; semantic router falls back to keyword only")
        return None
    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)

    def _call(texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = client.embeddings.create(model=model, input=texts)
        return [item.embedding for item in response.data]

    return _call


def _resolve_embed_fn(override: Optional[EmbedFn] = None) -> Optional[EmbedFn]:
    """单测可注入 override，业务路径按 env 构造。"""
    if override is not None:
        return override
    return _build_openai_embed_fn()


# ---------------------------------------------------------------------------
# 缓存
# ---------------------------------------------------------------------------

def _load_cache(cache_path: Path = _CACHE_PATH) -> dict[str, Any]:
    if not cache_path.exists():
        return {}
    try:
        return json.loads(cache_path.read_text(encoding="utf-8")) or {}
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning("embedding cache unreadable, ignored: %s", exc)
        return {}


def _save_cache(cache: dict[str, Any], cache_path: Path = _CACHE_PATH) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError as exc:
        _LOG.warning("embedding cache write failed: %s", exc)


def _ensure_skill_embeddings(
    corpora: list[SkillCorpus],
    embed_fn: EmbedFn,
    cache_path: Path = _CACHE_PATH,
) -> dict[str, list[float]]:
    """按 content_hash 判断缓存命中；缺的再调一次 embedding API。

    返回 {skill_path: vector}；调用失败时已缓存条目仍可用。
    """
    cache = _load_cache(cache_path)
    embeddings: dict[str, list[float]] = {}
    pending: list[SkillCorpus] = []
    for corpus in corpora:
        entry = cache.get(corpus.skill)
        if isinstance(entry, dict) and entry.get("hash") == corpus.content_hash:
            vec = entry.get("vector")
            if isinstance(vec, list) and vec:
                embeddings[corpus.skill] = [float(v) for v in vec]
                continue
        pending.append(corpus)

    if pending:
        try:
            vectors = embed_fn([c.text for c in pending])
        except Exception as exc:  # embedding SDK 各家异常不统一，统一降级
            _LOG.warning("embedding provider call failed: %s", exc)
            vectors = []
        if len(vectors) == len(pending):
            for corpus, vec in zip(pending, vectors):
                vec_list = [float(v) for v in vec]
                embeddings[corpus.skill] = vec_list
                cache[corpus.skill] = {
                    "hash": corpus.content_hash,
                    "vector": vec_list,
                }
            _save_cache(cache, cache_path)

    return embeddings


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------

def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / math.sqrt(na * nb)


def semantic_match(
    demand_text: str,
    *,
    table: dict[str, Any],
    embed_fn: Optional[EmbedFn] = None,
    cache_path: Path = _CACHE_PATH,
    min_score: Optional[float] = None,
) -> dict[str, float]:
    """对一条需求执行语义召回，返回超过阈值的 `{skill: score}`。

    @params:
        demand_text : 需求文本
        table       : router 路由表（load_routing_table 的产物）
        embed_fn    : 注入的 embedding 函数；None 时按 env 构造
        cache_path  : 缓存路径；单测可指向 tmp
        min_score   : 覆盖阈值；None 走 env / 默认
    @return:
        dict：key 是 skill 路径，value 是 cosine 相似度；异常时空 dict。
    """
    if not (demand_text or "").strip():
        return {}
    fn = _resolve_embed_fn(embed_fn)
    if fn is None:
        return {}
    corpora = build_corpora(table)
    if not corpora:
        return {}
    try:
        skill_vecs = _ensure_skill_embeddings(corpora, fn, cache_path)
        if not skill_vecs:
            return {}
        demand_vec_list = fn([demand_text])
    except Exception as exc:
        _LOG.warning("semantic match failed: %s", exc)
        return {}
    if not demand_vec_list:
        return {}
    demand_vec = [float(v) for v in demand_vec_list[0]]
    threshold_value = min_score if min_score is not None else threshold()
    hits: dict[str, float] = {}
    for skill, vec in skill_vecs.items():
        score = _cosine(demand_vec, vec)
        if score >= threshold_value:
            hits[skill] = score
    return hits
