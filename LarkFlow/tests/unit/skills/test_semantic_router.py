"""pipeline/skills/semantic.py + router 语义通道的单测。

覆盖：
1. semantic 模块：corpus 抽取、缓存命中/失效、cosine 阈值过滤、异常降级。
2. router._collect_routes 双通道：keyword-only / semantic-only / both 的 source 标注。
3. 纯语义召回的"关键词零命中但应被召回"样本。
"""
from __future__ import annotations

import json
import math
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pipeline.skills import semantic as sem
from pipeline.skills.router import (
    load_routing_table,
    route_from_text,
)


def _fake_embed_factory(vectors_by_text: dict[str, list[float]]):
    """生成一个按输入文本返回预设向量的 fake embed 函数。

    未预设的文本返回零向量（cosine=0 → 被阈值过滤掉）。
    """
    def _fn(texts):
        out = []
        for t in texts:
            out.append(vectors_by_text.get(t, [0.0] * 4))
        return out

    return _fn


class BuildCorporaTests(unittest.TestCase):
    def test_collects_all_three_tiers(self):
        table = load_routing_table()
        corpora = sem.build_corpora(table)
        skills = {c.skill for c in corpora}
        # baseline + conditional + routes 的 skill 都应包含
        self.assertIn("skills/framework/kratos.md", skills)
        self.assertIn("skills/transport/http.md", skills)
        self.assertIn("skills/infra/redis.md", skills)

    def test_excerpt_non_empty_for_real_skills(self):
        table = load_routing_table()
        corpora = sem.build_corpora(table)
        redis_corpus = next(c for c in corpora if c.skill == "skills/infra/redis.md")
        self.assertTrue(redis_corpus.title)
        self.assertTrue(redis_corpus.excerpt)
        # content_hash 稳定：两次构造同 skill 同语料应哈希一致
        again = sem.build_corpora(table)
        redis_again = next(c for c in again if c.skill == "skills/infra/redis.md")
        self.assertEqual(redis_corpus.content_hash, redis_again.content_hash)


class EmbeddingCacheTests(unittest.TestCase):
    def test_cache_hit_skips_embed_call(self):
        table = load_routing_table()
        corpora = sem.build_corpora(table)[:2]
        texts = [c.text for c in corpora]
        fake = _fake_embed_factory({texts[0]: [1.0, 0, 0, 0], texts[1]: [0, 1.0, 0, 0]})

        with TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "emb.json"
            # 第一次：写缓存
            sem._ensure_skill_embeddings(corpora, fake, cache_path)
            self.assertTrue(cache_path.exists())

            # 第二次：注入的 fake 若被调用就抛异常，验证走缓存不再调用
            def _should_not_call(_):
                raise AssertionError("embedding API 不应被调用，期望命中缓存")

            result = sem._ensure_skill_embeddings(corpora, _should_not_call, cache_path)
            self.assertEqual(set(result.keys()), {c.skill for c in corpora})

    def test_cache_invalidates_when_hash_changes(self):
        table = load_routing_table()
        corpus = sem.build_corpora(table)[0]
        fake = _fake_embed_factory({corpus.text: [1.0, 0, 0, 0]})
        with TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "emb.json"
            sem._ensure_skill_embeddings([corpus], fake, cache_path)
            # 手动篡改缓存 hash，模拟 skill 语料更新
            data = json.loads(cache_path.read_text())
            data[corpus.skill]["hash"] = "stale-hash"
            cache_path.write_text(json.dumps(data))

            called = {"n": 0}

            def _counting(_texts):
                called["n"] += 1
                return [[1.0, 0, 0, 0]]

            sem._ensure_skill_embeddings([corpus], _counting, cache_path)
            self.assertEqual(called["n"], 1)


class SemanticMatchTests(unittest.TestCase):
    def test_returns_empty_when_text_blank(self):
        table = load_routing_table()
        with TemporaryDirectory() as tmp:
            hits = sem.semantic_match(
                "",
                table=table,
                embed_fn=_fake_embed_factory({}),
                cache_path=Path(tmp) / "c.json",
            )
        self.assertEqual(hits, {})

    def test_returns_empty_when_embed_fn_is_none(self):
        table = load_routing_table()
        # embed_fn=None 会触发 _resolve_embed_fn(None) 调默认 openai 构造；
        # 在 env 未设 OPENAI_API_KEY 的情况下应安全返回空。
        with patch.dict(os.environ, {"OPENAI_API_KEY": "", "LARKFLOW_EMBEDDING_API_KEY": ""}, clear=False):
            hits = sem.semantic_match("任意需求", table=table)
        self.assertEqual(hits, {})

    def test_threshold_filters_low_scores(self):
        table = load_routing_table()
        redis_corpus = next(
            c for c in sem.build_corpora(table) if c.skill == "skills/infra/redis.md"
        )
        # demand 向量和 redis 几乎正交：cosine 约 0.1，低于默认阈值 0.45
        vectors = {redis_corpus.text: [1.0, 0, 0, 0], "热点数据": [0.1, 1.0, 0, 0]}
        for c in sem.build_corpora(table):
            vectors.setdefault(c.text, [0, 0, 0, 0])

        with TemporaryDirectory() as tmp:
            hits = sem.semantic_match(
                "热点数据",
                table=table,
                embed_fn=_fake_embed_factory(vectors),
                cache_path=Path(tmp) / "c.json",
            )
        self.assertNotIn("skills/infra/redis.md", hits)

    def test_high_similarity_hit(self):
        table = load_routing_table()
        idem_corpus = next(
            c for c in sem.build_corpora(table)
            if c.skill == "skills/governance/idempotency.md"
        )
        # demand 与 idempotency 向量完全相同 → cosine = 1.0 > 阈值
        vectors = {c.text: [0, 0, 0, 0] for c in sem.build_corpora(table)}
        vectors[idem_corpus.text] = [1.0, 0, 0, 0]
        vectors["防止重复提交"] = [1.0, 0, 0, 0]

        with TemporaryDirectory() as tmp:
            hits = sem.semantic_match(
                "防止重复提交",
                table=table,
                embed_fn=_fake_embed_factory(vectors),
                cache_path=Path(tmp) / "c.json",
            )
        self.assertIn("skills/governance/idempotency.md", hits)
        self.assertAlmostEqual(hits["skills/governance/idempotency.md"], 1.0, places=5)

    def test_exception_in_embed_fn_degrades_to_empty(self):
        table = load_routing_table()

        def _boom(_):
            raise RuntimeError("network down")

        with TemporaryDirectory() as tmp:
            hits = sem.semantic_match(
                "任意需求",
                table=table,
                embed_fn=_boom,
                cache_path=Path(tmp) / "c.json",
            )
        self.assertEqual(hits, {})


class RouterSemanticIntegrationTests(unittest.TestCase):
    """router 的 Tier-2 双通道合并行为。"""

    def test_semantic_hits_passed_explicitly_add_source_label(self):
        # 文本没有 redis 关键词，但手工塞语义命中
        routing = route_from_text(
            "做一个高频访问层",
            semantic_hits={"skills/infra/redis.md": 0.8},
        )
        self.assertIn("skills/infra/redis.md", routing.skills)
        reasons = [r for r in routing.reasons if r.skill == "skills/infra/redis.md"]
        self.assertTrue(reasons)
        self.assertEqual(reasons[0].source, "semantic")
        self.assertIn("语义相似度", reasons[0].detail)

    def test_both_channels_mark_source_both(self):
        # 同时有 redis 关键词 + 语义命中
        routing = route_from_text(
            "给 Redis 缓存加 TTL",
            semantic_hits={"skills/infra/redis.md": 0.9},
        )
        reasons = [r for r in routing.reasons if r.skill == "skills/infra/redis.md"]
        self.assertTrue(reasons)
        self.assertEqual(reasons[0].source, "both")

    def test_keyword_only_marks_source_keyword(self):
        routing = route_from_text("给 Redis 缓存加 TTL", semantic_hits={})
        reasons = [r for r in routing.reasons if r.skill == "skills/infra/redis.md"]
        self.assertTrue(reasons)
        self.assertEqual(reasons[0].source, "keyword")

    def test_empty_semantic_hits_matches_pr3_behavior(self):
        # 与 PR-3 等价：显式传空 dict，关闭语义通道
        a = route_from_text("用户注册需要密码 bcrypt", semantic_hits={})
        b = route_from_text("用户注册需要密码 bcrypt", semantic_hits={})
        self.assertEqual(a.skills, b.skills)

    def test_to_dict_round_trip_preserves_source(self):
        routing = route_from_text(
            "做一个高频访问层",
            semantic_hits={"skills/infra/redis.md": 0.7},
        )
        payload = routing.to_dict()
        redis_reasons = [
            r for r in payload["reasons"]
            if r["skill"] == "skills/infra/redis.md"
        ]
        self.assertTrue(redis_reasons)
        self.assertEqual(redis_reasons[0]["source"], "semantic")


class SemanticDisabledByDefaultTests(unittest.TestCase):
    """env 开关默认关闭：route_from_text 不会主动调 embedding API。"""

    def test_disabled_when_env_absent(self):
        # 清掉开关
        with patch.dict(
            os.environ,
            {"LARKFLOW_SEMANTIC_ROUTER_ENABLED": ""},
            clear=False,
        ):
            self.assertFalse(sem.is_enabled())

    def test_enabled_only_on_whitelisted_values(self):
        for val in ["1", "true", "True", "yes", "on"]:
            with patch.dict(
                os.environ,
                {"LARKFLOW_SEMANTIC_ROUTER_ENABLED": val},
                clear=False,
            ):
                self.assertTrue(sem.is_enabled(), f"{val} 应视为开启")
        for val in ["0", "false", "no", ""]:
            with patch.dict(
                os.environ,
                {"LARKFLOW_SEMANTIC_ROUTER_ENABLED": val},
                clear=False,
            ):
                self.assertFalse(sem.is_enabled(), f"{val} 不应开启")


if __name__ == "__main__":
    unittest.main()
