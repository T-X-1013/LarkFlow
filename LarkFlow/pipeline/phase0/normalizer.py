"""规则版需求规范化：从自然语言抽取 NormalizedDemand。

只用正则和关键词匹配，不调 LLM。目标是给下游提供比原始 NL 更干净的输入；
LLM 增强版作为后续 PR 叠加在 `source` 字段上。

规则来源与 `rules/skill-routing.yaml` 保持语义一致，但这里抽取的是"字段"
而非直接选 skill，避免和 router 职责重叠。
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

from pipeline.phase0.schema import (
    ApiSketch,
    NfrFlags,
    NormalizedDemand,
    OpenQuestion,
    PersistenceHint,
)

_LOG = logging.getLogger("larkflow.phase0.normalizer")

# ---------- 词表 ----------

_HTTP_METHOD_RE = re.compile(
    r"\b(GET|POST|PUT|DELETE|PATCH|gRPC|RPC)\b",
    re.IGNORECASE,
)
_PATH_RE = re.compile(r"(/[a-zA-Z0-9_{}\-:.\/]+)")
_API_KEYWORDS = (
    "http", "api", "rest", "grpc", "rpc", "接口", "路由", "router", "endpoint",
    "端点", "对外接口", "后端接口", "middleware", "中间件", "调用",
)
_LIST_KEYWORDS = ("列表", "分页", "pagination", "page", "cursor", "翻页", "分批")

_PERSISTENCE_KEYWORDS = (
    "mysql", "postgresql", "sql", "gorm", "database", "数据库", "数据表",
    "表结构", "落库", "持久化", "orm",
)
_MIGRATION_KEYWORDS = (
    "migration", "建表", "加字段", "新字段", "新增字段", "新增表", "新增..表",
    "改表结构", "增加字段", "添加字段", "加一列", "索引", "index",
    "新表", "新增一张", "创建表", "加一张表",
)
_TABLE_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]{1,})\s*表")
_CHINESE_TABLE_RE = re.compile(r"(?:新增|添加|建|创建|加)(?:一张)?\s*([一-龥A-Za-z_][一-龥A-Za-z0-9_]{0,20})表")
_TRANSACTION_KEYWORDS = ("事务", "transaction", "transactional", "原子操作")

_AUTH_KEYWORDS = (
    "auth", "认证", "授权", "登录", "登陆", "login", "jwt", "session",
    "oauth", "rbac", "权限", "鉴权", "访问控制",
)
_IDEMPOTENT_KEYWORDS = (
    "幂等", "idempotency", "idempotent", "dedup", "去重", "重放",
    "webhook", "回调", "callback", "at-least-once", "重复提交",
    "消费消息", "mq 消费",
)
_RATE_LIMIT_KEYWORDS = (
    "限流", "rate limit", "throttle", "令牌桶", "token bucket",
    "429", "quota", "频控",
)
_CONCURRENCY_KEYWORDS = (
    "高并发", "并发", "goroutine", "async", "异步", "协程", "热点", "高频",
)

_DOMAIN_MAP: dict[str, tuple[str, ...]] = {
    "order": (
        "order", "订单", "下单", "购物车", "checkout", "超卖", "库存", "商品",
    ),
    "user": (
        "user", "用户", "account", "账户", "register", "注册", "signup",
        "login", "登录", "登陆", "密码", "password", "爆破", "暴力破解",
        "昵称", "资料", "profile",
    ),
    "payment": (
        "payment", "支付", "付款", "refund", "退款", "对账",
        "reconciliation", "回调", "stripe", "微信支付", "支付宝", "结算",
    ),
}

_PYTHON_AREA_KEYWORDS = (
    "larkflow", "pipeline/", "tests/", "scripts/", "pytest",
    "注释规范", "docstring", "改 pipeline", "改 tests",
)

_OUT_OF_SCOPE_RE = re.compile(
    r"(不[包涉]?[含括涉及]|暂不|不做|不处理|排除|不考虑|out of scope)[：:\s]*(.+?)(?:[。\n]|$)",
    re.IGNORECASE,
)
_GOAL_HINT_RE = re.compile(
    r"^(为了|旨在|希望|目标[是为：:]|我们要|需要)(.+?)(?:[。\n]|$)",
)


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    """大小写无关地判断文本是否出现任一关键词。"""
    return any(kw.lower() in text for kw in keywords)


def _first_matching(text: str, keywords: Iterable[str]) -> str:
    for kw in keywords:
        if kw.lower() in text:
            return kw
    return ""


def _extract_goal(text: str) -> str:
    """抽一句"做什么"作为 goal；抽不到就回落到首句。"""
    match = _GOAL_HINT_RE.search(text.strip())
    if match:
        return match.group(2).strip()
    first_line = text.strip().split("\n", 1)[0]
    first_sent = re.split(r"[。.!?！？]", first_line, maxsplit=1)[0]
    return first_sent.strip()[:200]


def _extract_out_of_scope(text: str) -> list[str]:
    items: list[str] = []
    for match in _OUT_OF_SCOPE_RE.finditer(text):
        item = match.group(2).strip()
        if item:
            items.append(item[:200])
    return items


def _extract_apis(text: str, lower: str) -> list[ApiSketch]:
    apis: list[ApiSketch] = []
    if not _contains_any(lower, _API_KEYWORDS):
        return apis
    # 先看显式的 METHOD PATH 组合
    for method_match in _HTTP_METHOD_RE.finditer(text):
        method = method_match.group(1).upper()
        tail = text[method_match.end(): method_match.end() + 80]
        path_match = _PATH_RE.search(tail)
        path = path_match.group(1).rstrip(",.;，。；") if path_match else ""
        apis.append(ApiSketch(method=method, path=path, purpose=""))
    if apis:
        return apis
    # 没拿到显式 METHOD：记一个占位 sketch，method/path 让 Phase 1 补
    apis.append(ApiSketch(method="", path="", purpose="新增对外接口（由 Phase 1 补全 METHOD 和 PATH）"))
    return apis


def _extract_persistence(text: str, lower: str) -> PersistenceHint:
    needs_storage = _contains_any(lower, _PERSISTENCE_KEYWORDS)
    needs_migration = _contains_any(lower, _MIGRATION_KEYWORDS)
    tables_set: set[str] = {m.group(1) for m in _TABLE_RE.finditer(text)}
    for m in _CHINESE_TABLE_RE.finditer(text):
        name = m.group(1).strip()
        if name:
            tables_set.add(name)
            # 识别到"新增 X 表"同样算 migration
            needs_migration = True
    tables = sorted(tables_set)
    notes = ""
    if _contains_any(lower, ("唯一键", "unique", "唯一索引")):
        notes = "需要唯一性约束或索引"
    return PersistenceHint(
        needs_storage=needs_storage or needs_migration or bool(tables),
        needs_migration=needs_migration,
        tables=tables,
        notes=notes,
    )


def _extract_nfr(lower: str) -> NfrFlags:
    return NfrFlags(
        auth=_contains_any(lower, _AUTH_KEYWORDS),
        idempotent=_contains_any(lower, _IDEMPOTENT_KEYWORDS),
        rate_limit=_contains_any(lower, _RATE_LIMIT_KEYWORDS),
        transactional=_contains_any(lower, _TRANSACTION_KEYWORDS),
        high_concurrency=_contains_any(lower, _CONCURRENCY_KEYWORDS),
    )


def _extract_domain_tags(lower: str) -> list[str]:
    tags: list[str] = []
    for tag, keywords in _DOMAIN_MAP.items():
        if _contains_any(lower, keywords):
            tags.append(tag)
    return tags


def _extract_entities(text: str, persistence: PersistenceHint) -> list[str]:
    """实体名候选：优先表名；再补一些被大写开头的英文单词。"""
    seen: set[str] = set(persistence.tables)
    ordered: list[str] = list(persistence.tables)
    for match in re.finditer(r"\b([A-Z][a-zA-Z0-9]+)\b", text):
        name = match.group(1)
        if name in seen or len(name) <= 2:
            continue
        # 排除 HTTP 方法与常见协议词
        if name.upper() in {
            "GET", "POST", "PUT", "DELETE", "PATCH", "GRPC", "RPC", "API",
            "REST", "HTTP", "HTTPS", "JSON", "SQL", "JWT", "OAUTH", "RBAC",
            "MQ", "MYSQL", "REDIS", "KAFKA", "TTL", "URL", "URI", "ID",
        }:
            continue
        seen.add(name)
        ordered.append(name)
    return ordered[:10]


def _build_open_questions(
    lower: str,
    apis: list[ApiSketch],
    persistence: PersistenceHint,
) -> list[OpenQuestion]:
    """规则版只抛最明显的澄清问题；LLM 版再做分字段置信度。"""
    qs: list[OpenQuestion] = []
    if apis and not any(a.path for a in apis):
        qs.append(
            OpenQuestion(
                text="对外接口的 METHOD 和 PATH 未明确，请 Phase 1 在设计文档中补全并列出。",
                blocking=False,
            )
        )
    if persistence.needs_migration and not persistence.tables:
        qs.append(
            OpenQuestion(
                text="需要 DDL 变更，但未识别到具体表名，请确认变更目标表。",
                blocking=False,
            )
        )
    if _contains_any(lower, ("可能", "大概", "也许", "差不多")):
        qs.append(
            OpenQuestion(
                text="需求中包含模糊描述（可能/大概），请 reviewer 在设计审批前核对精确语义。",
                blocking=False,
            )
        )
    return qs


def normalize_demand(raw_demand: str) -> NormalizedDemand:
    """Phase 0 规范化入口。

    先跑规则版抽取出兜底产物；若 env `LARKFLOW_PHASE0_LLM_ENABLED` 开启且 LLM
    可用，再调 LLM 分类器并与规则版合并（source='hybrid'），否则返回规则版。

    @params:
        raw_demand: 原始自然语言需求

    @return:
        NormalizedDemand；source='rule' | 'hybrid'（未来 'llm' 用于纯 LLM 模式）。
    """
    rule_result = _normalize_rule(raw_demand)
    # 延迟 import 避免模块循环（llm_classifier 也 import schema）
    from pipeline.phase0 import llm_classifier
    if not llm_classifier.is_enabled():
        return rule_result
    return llm_classifier.classify(raw_demand, rule_fallback=rule_result)


def _normalize_rule(raw_demand: str) -> NormalizedDemand:
    """规则版实现，独立出来便于 LLM 版合并时当 fallback。"""
    text = raw_demand or ""
    lower = text.lower()

    goal = _extract_goal(text)
    out_of_scope = _extract_out_of_scope(text)
    apis = _extract_apis(text, lower)
    persistence = _extract_persistence(text, lower)
    nfr = _extract_nfr(lower)
    domain_tags = _extract_domain_tags(lower)
    entities = _extract_entities(text, persistence)
    touches_python = _contains_any(lower, _PYTHON_AREA_KEYWORDS)
    open_questions = _build_open_questions(lower, apis, persistence)

    # 列表类 API 也算 api 的一种特征，但不改 apis 列表，只是防止下游漏读 pagination
    if _contains_any(lower, _LIST_KEYWORDS) and not apis:
        apis.append(
            ApiSketch(
                method="GET",
                path="",
                purpose="列表 / 分页 API（由 Phase 1 补路径）",
            )
        )

    return NormalizedDemand(
        raw_demand=text,
        goal=goal,
        out_of_scope=out_of_scope,
        entities=entities,
        apis=apis,
        persistence=persistence,
        nfr=nfr,
        domain_tags=domain_tags,
        touches_python=touches_python,
        open_questions=open_questions,
        confidence=1.0,
        source="rule",
    )
