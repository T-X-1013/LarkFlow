"""pipeline/phase0/normalizer.py 单测。

覆盖：
1. 基本字段抽取：goal / apis / persistence / nfr / domain_tags / touches_python
2. 20 条自然语言黄金集：断言关键字段命中
3. derived_text 与 render_prompt_block 的形状
"""
from __future__ import annotations

import unittest

from pipeline.phase0 import normalize_demand


class BasicExtractionTests(unittest.TestCase):
    def test_goal_picks_first_sentence(self):
        nd = normalize_demand("让用户可以改昵称，最多 30 字。其他细节待定。")
        self.assertIn("昵称", nd.goal)

    def test_api_method_and_path(self):
        nd = normalize_demand("提供 REST 接口 PATCH /users/{id}/nickname 更新资料")
        self.assertEqual(len(nd.apis), 1)
        self.assertEqual(nd.apis[0].method, "PATCH")
        self.assertIn("/users/{id}/nickname", nd.apis[0].path)

    def test_api_placeholder_when_keyword_only(self):
        nd = normalize_demand("新增一个对外接口让前端调用")
        self.assertEqual(len(nd.apis), 1)
        self.assertEqual(nd.apis[0].method, "")
        self.assertTrue(nd.apis[0].purpose)

    def test_persistence_needs_migration(self):
        nd = normalize_demand("在 users 表加字段 nickname，长度 30")
        self.assertTrue(nd.persistence.needs_migration)
        self.assertTrue(nd.persistence.needs_storage)
        self.assertIn("users", nd.persistence.tables)

    def test_nfr_idempotent_from_callback(self):
        nd = normalize_demand("支付回调必须幂等")
        self.assertTrue(nd.nfr.idempotent)

    def test_nfr_auth_from_login(self):
        nd = normalize_demand("登录接口加 JWT 鉴权")
        self.assertTrue(nd.nfr.auth)

    def test_nfr_rate_limit(self):
        nd = normalize_demand("API 加令牌桶限流，超限返回 429")
        self.assertTrue(nd.nfr.rate_limit)

    def test_domain_tags_multiple(self):
        nd = normalize_demand("订单的支付回调接口")
        self.assertIn("order", nd.domain_tags)
        self.assertIn("payment", nd.domain_tags)

    def test_touches_python_flag(self):
        nd = normalize_demand("修改 LarkFlow pipeline/ 下的 docstring 规范")
        self.assertTrue(nd.touches_python)

    def test_out_of_scope_captured(self):
        nd = normalize_demand("做一个退款接口。不包括对账报表和 UI 改动。")
        self.assertTrue(any("对账" in s or "报表" in s or "UI" in s for s in nd.out_of_scope))

    def test_open_question_for_api_without_path(self):
        nd = normalize_demand("新增一个对外接口")
        self.assertTrue(any("METHOD" in q.text for q in nd.open_questions))

    def test_open_question_for_migration_without_table(self):
        nd = normalize_demand("加字段，支持新业务")
        self.assertTrue(nd.persistence.needs_migration)
        self.assertTrue(
            any("表名" in q.text for q in nd.open_questions),
            f"open_questions={[q.text for q in nd.open_questions]}",
        )

    def test_entities_excludes_protocol_words(self):
        nd = normalize_demand("REST HTTP JSON 接口")
        self.assertNotIn("REST", nd.entities)
        self.assertNotIn("HTTP", nd.entities)
        self.assertNotIn("JSON", nd.entities)

    def test_list_keyword_adds_get_sketch(self):
        nd = normalize_demand("查询订单列表，需要分页")
        self.assertTrue(nd.apis)

    def test_zero_keyword_still_produces_goal(self):
        nd = normalize_demand("简化抽象层")
        self.assertTrue(nd.goal)
        self.assertEqual(nd.apis, [])
        self.assertFalse(nd.persistence.needs_storage)


class DerivedTextAndPromptBlockTests(unittest.TestCase):
    def test_derived_text_includes_structured_signals(self):
        nd = normalize_demand("订单退款接口，PATCH /orders/{id}/refund，需要幂等")
        text = nd.derived_text()
        self.assertIn("幂等", text)
        self.assertIn("order", text.lower())

    def test_render_prompt_block_contains_headings_and_goal(self):
        nd = normalize_demand("登录接口加 JWT 鉴权")
        block = nd.render_prompt_block()
        self.assertIn("Normalized Demand (authoritative)", block)
        self.assertIn("Goal", block)
        self.assertIn("NFR", block)

    def test_empty_raw_yields_empty_block(self):
        nd = normalize_demand("")
        self.assertEqual(nd.render_prompt_block(), "")


class GoldenNaturalLanguageCoverageTests(unittest.TestCase):
    CASES: list[tuple[str, dict]] = [
        ("让用户可以修改昵称，最多 30 字", {"domain": "user"}),
        ("新增订单表，字段包含 amount 和 status", {"migration": True}),
        ("支付完成后回调必须幂等，金额用 int64", {"idempotent": True, "domain": "payment"}),
        ("每日对账任务，把失败单推飞书群", {"domain": "payment"}),
        ("订单列表需要分页，按创建时间倒序", {"api": True, "domain": "order"}),
        ("登录接口加频控，防暴力破解", {"rate_limit": True, "auth": True}),
        ("注册接口要防爆破，密码用 bcrypt", {"domain": "user", "api": True}),
        ("用 Redis 做热点 key 的分布式锁", {"concurrency": True}),
        ("通过 Kafka 异步解耦订单和库存扣减", {"domain": "order"}),
        ("通过 gRPC 调用内部风控服务，需要超时和重试", {"api": True}),
        ("加一个 feature flag 控制是否启用新算法", {}),
        ("修改 LarkFlow pipeline/ 里的 Python 模块", {"touches_python": True}),
        ("提供 REST endpoint 查询用户资料", {"api": True, "domain": "user"}),
        ("给 auth 中间件加 JWT 校验", {"auth": True}),
        ("使用 etcd 注册中心做服务发现", {}),
        ("goroutine 里跑批处理，通过 context 取消", {"concurrency": True}),
        ("微信支付回调验签 + 幂等", {"idempotent": True, "domain": "payment"}),
        ("购物车 checkout 流程防超卖", {"domain": "order"}),
        ("users 表加字段 created_at", {"migration": True, "domain": "user"}),
        ("把所有 feature 抽象一下", {}),
    ]

    def test_each_case_structured(self):
        for text, expect in self.CASES:
            with self.subTest(text=text):
                nd = normalize_demand(text)
                if "domain" in expect:
                    self.assertIn(expect["domain"], nd.domain_tags)
                if expect.get("api"):
                    self.assertTrue(nd.apis, f"{text} 应识别出 API")
                if expect.get("migration"):
                    self.assertTrue(
                        nd.persistence.needs_migration,
                        f"{text} 应识别出 DDL",
                    )
                if expect.get("idempotent"):
                    self.assertTrue(nd.nfr.idempotent)
                if expect.get("auth"):
                    self.assertTrue(nd.nfr.auth)
                if expect.get("rate_limit"):
                    self.assertTrue(nd.nfr.rate_limit)
                if expect.get("concurrency"):
                    self.assertTrue(nd.nfr.high_concurrency)
                if expect.get("touches_python"):
                    self.assertTrue(nd.touches_python)


class SchemaSerializationTests(unittest.TestCase):
    def test_to_dict_roundtrip_stable(self):
        nd = normalize_demand("支付回调幂等")
        d = nd.to_dict()
        self.assertEqual(d["source"], "rule")
        self.assertIn("nfr", d)
        self.assertIn("persistence", d)
        self.assertIn("open_questions", d)


if __name__ == "__main__":
    unittest.main()
