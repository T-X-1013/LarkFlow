"""pipeline/skills/router.py 单测。

覆盖：
1. Tier-0 baseline 对所有样本无条件出现（含零命中样本）。
2. Tier-1 conditional 触发器命中即注入，不受 top-K 截断。
3. Tier-2 routes 关键词召回 + weight 排序 + top-K 截断。
4. 黄金集：20 条自然语言需求样本的整体断言。
5. 辅助：去重、reason 归因、render_prompt_block 输出。
"""
from __future__ import annotations

import unittest

from pipeline.skills.router import (
    DEFAULT_TOP_K,
    MatchReason,
    SkillRouting,
    load_routing_table,
    route_from_text,
)


BASELINE_SKILLS = {
    "skills/framework/kratos.md",
    "skills/lang/error.md",
    "skills/governance/observability.md",
    "skills/governance/logging.md",
}


class BaselineTierTests(unittest.TestCase):
    """Tier-0：任何输入都必须包含 baseline 四项。"""

    def test_baseline_always_present_even_for_empty_text(self):
        routing = route_from_text("")
        self.assertTrue(BASELINE_SKILLS.issubset(set(routing.skills)))

    def test_baseline_always_present_for_zero_match_text(self):
        # 纯业务描述且不含任何关键词：只应得到 baseline 四项
        routing = route_from_text("把所有 feature 抽象一下")
        self.assertEqual(set(routing.skills), BASELINE_SKILLS)

    def test_baseline_skills_come_first(self):
        routing = route_from_text("新增支付回调，需要幂等")
        self.assertEqual(routing.skills[: len(BASELINE_SKILLS)][0:4], [
            "skills/framework/kratos.md",
            "skills/lang/error.md",
            "skills/governance/observability.md",
            "skills/governance/logging.md",
        ])


class ConditionalTierTests(unittest.TestCase):
    """Tier-1：trigger.keywords_any 命中即必读。"""

    def test_http_api_keyword_triggers_http_skill(self):
        routing = route_from_text("提供一个 REST 接口用来更新用户资料")
        self.assertIn("skills/transport/http.md", routing.skills)

    def test_database_keyword_triggers_database_skill(self):
        routing = route_from_text("users 表加字段 nickname")
        self.assertIn("skills/infra/database.md", routing.skills)

    def test_config_keyword_triggers_config_skill(self):
        routing = route_from_text("加一个 feature flag 控制是否开启")
        self.assertIn("skills/infra/config.md", routing.skills)

    def test_python_area_triggers_python_comments_skill(self):
        routing = route_from_text("修改 pipeline/ 下的 Python 注释规范")
        self.assertIn("skills/lang/python-comments.md", routing.skills)

    def test_pagination_keyword_triggers_pagination_skill(self):
        routing = route_from_text("查询订单列表需要分页")
        self.assertIn("skills/transport/pagination.md", routing.skills)

    def test_idempotency_keyword_triggers_idempotency_skill(self):
        routing = route_from_text("支付回调必须幂等")
        self.assertIn("skills/governance/idempotency.md", routing.skills)

    def test_conditional_not_triggered_without_keywords(self):
        routing = route_from_text("把所有 feature 抽象一下")
        self.assertNotIn("skills/transport/http.md", routing.skills)
        self.assertNotIn("skills/infra/database.md", routing.skills)
        self.assertNotIn("skills/infra/config.md", routing.skills)


class RoutesTierTests(unittest.TestCase):
    """Tier-2：关键词召回 + weight 排序 + top-K 截断。"""

    def test_domain_order_matched_by_chinese_keyword(self):
        routing = route_from_text("做一个下单流程，防止超卖")
        self.assertIn("skills/domain/order.md", routing.skills)

    def test_redis_matched(self):
        routing = route_from_text("热点数据加 Redis 缓存 TTL")
        self.assertIn("skills/infra/redis.md", routing.skills)

    def test_mq_matched(self):
        routing = route_from_text("引入 Kafka 消费者处理事件")
        self.assertIn("skills/transport/mq.md", routing.skills)

    def test_rate_limit_matched(self):
        routing = route_from_text("API 加令牌桶限流，超限返回 429")
        self.assertIn("skills/governance/rate_limit.md", routing.skills)

    def test_top_k_truncation(self):
        # 构造同时命中多个 route 的文本，验证 top_k 生效
        text = "订单 支付 用户 Redis gRPC MQ 限流 重试 服务发现 goroutine 鉴权"
        routing = route_from_text(text, top_k=3)
        route_skills = [
            r.skill for r in routing.reasons if r.tier == "route"
        ]
        self.assertLessEqual(len(route_skills), 3)

    def test_top_k_default_is_five(self):
        text = "订单 支付 用户 Redis gRPC MQ 限流 重试 服务发现 goroutine 鉴权"
        routing = route_from_text(text)
        route_skills = [
            r.skill for r in routing.reasons if r.tier == "route"
        ]
        self.assertLessEqual(len(route_skills), DEFAULT_TOP_K)

    def test_business_skills_outrank_generic_on_ties(self):
        # 业务 weight=1.2 > rpc weight=1.1 > redis weight=1.0
        text = "订单流程里调用 gRPC 并写入 Redis 缓存"
        routing = route_from_text(text)
        route_reasons = [r for r in routing.reasons if r.tier == "route"]
        ordered = [r.skill for r in route_reasons]
        self.assertLess(
            ordered.index("skills/domain/order.md"),
            ordered.index("skills/infra/redis.md"),
            "domain/order.md (weight=1.2) 应排在 infra/redis.md (weight=1.0) 之前",
        )


class DeduplicationTests(unittest.TestCase):
    """同一个 skill 被多层选中时应只在 skills 中出现一次。"""

    def test_skill_appears_once_in_skills_list(self):
        # kratos 是 baseline，不会在 conditional/routes 重复（已从 YAML 移除），
        # 但我们仍可构造 baseline + domain 触发场景，确保 skills 列表去重
        routing = route_from_text("用户注册需要密码 bcrypt 并且走 HTTP API")
        self.assertEqual(len(routing.skills), len(set(routing.skills)))


class ReasonAttributionTests(unittest.TestCase):
    """reason 列表应如实记录每条 skill 是从哪一层匹配来的。"""

    def test_every_returned_skill_has_at_least_one_reason(self):
        routing = route_from_text("用户注册 + Redis 缓存 + HTTP 接口")
        reason_skills = {r.skill for r in routing.reasons}
        for skill in routing.skills:
            self.assertIn(skill, reason_skills)

    def test_conditional_reason_includes_trigger_keyword(self):
        routing = route_from_text("提供 REST 接口更新资料")
        http_reasons = [
            r for r in routing.reasons
            if r.skill == "skills/transport/http.md" and r.tier == "conditional"
        ]
        self.assertTrue(http_reasons)
        self.assertIn("触发关键词", http_reasons[0].detail)

    def test_baseline_tier_label(self):
        routing = route_from_text("")
        baseline_reasons = [r for r in routing.reasons if r.tier == "baseline"]
        self.assertEqual(
            {r.skill for r in baseline_reasons}, BASELINE_SKILLS
        )


class PromptRenderingTests(unittest.TestCase):
    """render_prompt_block 的输出格式。"""

    def test_empty_routing_renders_empty_string(self):
        self.assertEqual(SkillRouting().render_prompt_block(), "")

    def test_prompt_block_lists_each_skill_once(self):
        routing = route_from_text("支付回调幂等 + Redis 缓存")
        block = routing.render_prompt_block()
        for skill in routing.skills:
            self.assertEqual(
                block.count(f"`{skill}`"),
                1,
                f"{skill} 应该只出现一次",
            )

    def test_prompt_block_contains_tier_label(self):
        routing = route_from_text("支付回调幂等")
        block = routing.render_prompt_block()
        self.assertIn("[baseline]", block)
        self.assertIn("[conditional]", block)


class GoldenNaturalLanguageTests(unittest.TestCase):
    """20 条真实业务描述的黄金集回归。

    每条样本断言至少一个必含 skill 在 skills 中，且 baseline 四项必现。
    目的是保证"自然语言 → 命中的核心 skill 不被错过"。
    """

    CASES: list[tuple[str, set[str]]] = [
        ("让用户可以修改昵称，最多 30 字", {"skills/domain/user.md"}),
        ("给用户加一个 HTTP 接口更新资料", {"skills/transport/http.md", "skills/domain/user.md"}),
        ("新增订单表，字段包含 amount 和 status", {"skills/infra/database.md"}),
        ("支付完成后回调必须幂等，金额用 int64", {"skills/governance/idempotency.md", "skills/domain/payment.md"}),
        ("每日对账任务，把失败单推飞书群", {"skills/domain/payment.md"}),
        ("订单列表需要分页，按创建时间倒序", {"skills/transport/pagination.md", "skills/domain/order.md"}),
        ("登录接口加频控，防暴力破解", {"skills/governance/rate_limit.md", "skills/domain/user.md"}),
        ("注册接口要防爆破，密码用 bcrypt", {"skills/domain/user.md"}),
        ("用 Redis 做热点 key 的分布式锁", {"skills/infra/redis.md"}),
        ("通过 Kafka 异步解耦订单和库存扣减", {"skills/transport/mq.md"}),
        ("通过 gRPC 调用内部风控服务，需要超时和重试", {"skills/transport/rpc.md", "skills/governance/resilience.md"}),
        ("加一个 feature flag 控制是否启用新算法", {"skills/infra/config.md"}),
        ("修改 LarkFlow pipeline/ 里的 Python 模块", {"skills/lang/python-comments.md"}),
        ("提供 REST endpoint 查询用户资料", {"skills/transport/http.md", "skills/domain/user.md"}),
        ("给 auth 中间件加 JWT 校验", {"skills/governance/auth.md"}),
        ("使用 etcd 注册中心做服务发现", {"skills/governance/service_discovery.md"}),
        ("goroutine 里跑批处理，通过 context 取消", {"skills/lang/concurrency.md"}),
        ("微信支付回调验签 + 幂等", {"skills/governance/idempotency.md", "skills/domain/payment.md"}),
        ("购物车 checkout 流程防超卖", {"skills/domain/order.md"}),
        ("把所有 feature 抽象一下", set()),  # 零命中，仅 baseline
    ]

    def test_each_case_includes_baseline(self):
        for text, _expected in self.CASES:
            with self.subTest(text=text):
                routing = route_from_text(text)
                self.assertTrue(
                    BASELINE_SKILLS.issubset(set(routing.skills)),
                    f"baseline 缺失: {text}",
                )

    def test_each_case_includes_expected_skills(self):
        for text, expected in self.CASES:
            with self.subTest(text=text):
                routing = route_from_text(text)
                missing = expected - set(routing.skills)
                self.assertFalse(
                    missing,
                    f"用例「{text}」缺少必含 skill：{missing}\n"
                    f"实际命中：{routing.skills}",
                )


class LoadRoutingTableTests(unittest.TestCase):
    """YAML 加载的降级行为。"""

    def test_default_path_loads_successfully(self):
        table = load_routing_table()
        self.assertIn("baseline", table)
        self.assertIn("conditional", table)
        self.assertIn("routes", table)
        # baseline 四项存在
        baseline_skills = {item["skill"] for item in table["baseline"]}
        self.assertEqual(baseline_skills, BASELINE_SKILLS)


if __name__ == "__main__":
    unittest.main()
