import asyncio
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.modules.setdefault("redis", types.ModuleType("redis"))

from core.query_router import QueryRouter
from models.schemas import Condition, Operator, ParsedQuery, QueryLogic
from utils.name_candidate import detect_name_candidate


class _StubFieldRegistry:
    def normalize_query(self, query: str) -> str:
        return query


class _StubLevel1:
    async def extract(self, query):
        self._last_matched_patterns = []
        return []


class _StubLevel2:
    async def match(self, query):
        self._last_matched_patterns = []
        return []

    def recall_candidate_conditions(self, query):
        return []


class _StubLevel3:
    async def get(self, query):
        return None

    async def set(self, query, parsed):
        self.last_set_query = query
        self.last_set_parsed = parsed


class _StubLevel4WrongSurname:
    async def parse(self, query):
        return ParsedQuery(
            conditions=[
                Condition(
                    field="searchClientNameNew",
                    operator=Operator.MATCH,
                    value="张",
                )
            ],
            query_logic=QueryLogic.AND,
            confidence=0.8,
            matched_level=4,
        )


class _StubLevel4Empty:
    async def parse(self, query):
        return ParsedQuery(
            conditions=[],
            query_logic=QueryLogic.AND,
            confidence=0.0,
            matched_level=4,
        )


class _StubLevel4WrongMobile:
    async def parse(self, query):
        return ParsedQuery(
            conditions=[
                Condition(
                    field="clientMobile",
                    operator=Operator.MATCH,
                    value="13900139000",
                )
            ],
            query_logic=QueryLogic.AND,
            confidence=0.6,
            matched_level=4,
        )


def _build_router(level4):
    router = QueryRouter.__new__(QueryRouter)
    router.level1 = _StubLevel1()
    router.level2 = _StubLevel2()
    router.level3 = _StubLevel3()
    router.level4 = level4
    router.field_registry = _StubFieldRegistry()
    router._valid_fields = {"searchClientNameNew"}
    router._enum_values = {}
    router._last_rewritten_query = None
    router._last_matched_patterns = []
    return router


def _build_router_with_l2_candidates(level4, l2_candidates):
    router = _build_router(level4)

    class _StubLevel2WithCandidates(_StubLevel2):
        def recall_candidate_conditions(self, query):
            return l2_candidates

    router.level2 = _StubLevel2WithCandidates()
    return router


def test_extract_explicit_client_full_name_supports_two_character_names():
    assert QueryRouter._extract_explicit_client_full_name("张无的客户") == "张无"
    assert QueryRouter._extract_explicit_client_full_name("金美本人") == "金美"
    assert QueryRouter._extract_explicit_client_full_name("叫李保的客户") == "李保"
    assert QueryRouter._extract_explicit_client_full_name("查询叫兴浩的客户") == "兴浩"


def test_extract_explicit_client_full_name_skips_surname_and_family_context():
    assert QueryRouter._extract_explicit_client_full_name("姓张的客户") is None
    assert QueryRouter._extract_explicit_client_full_name("子女叫张无的客户") is None
    assert QueryRouter._extract_explicit_client_full_name("张无") is None


def test_detect_name_candidate_uses_surname_rule_for_bare_name_queries():
    assert detect_name_candidate("张无").is_candidate is True
    assert detect_name_candidate("张无").reason == "single_surname_match"
    assert detect_name_candidate("王小明").is_candidate is True
    assert detect_name_candidate("欧阳娜娜").is_candidate is True
    assert detect_name_candidate("黄金").is_candidate is False
    assert detect_name_candidate("高温").is_candidate is False


def test_route_with_peeling_replaces_surname_with_full_name_for_llm_output():
    router = _build_router(_StubLevel4WrongSurname())

    parsed = asyncio.run(router.route_with_peeling("张无的客户"))

    assert [(cond.field, cond.operator, cond.value) for cond in parsed.conditions] == [
        ("searchClientNameNew", Operator.MATCH, "张无")
    ]


def test_route_with_peeling_adds_missing_full_name_for_empty_llm_output():
    router = _build_router(_StubLevel4Empty())

    parsed = asyncio.run(router.route_with_peeling("金美本人"))

    assert [(cond.field, cond.operator, cond.value) for cond in parsed.conditions] == [
        ("searchClientNameNew", Operator.MATCH, "金美")
    ]


def test_route_with_peeling_materializes_bare_name_candidate_when_no_conditions():
    router = _build_router(_StubLevel4Empty())

    parsed = asyncio.run(router.route_with_peeling("张无"))

    assert [(cond.field, cond.operator, cond.value) for cond in parsed.conditions] == [
        ("searchClientNameNew", Operator.MATCH, "张无")
    ]
    assert parsed.matched_patterns == [
        {
            "rule_name": "疑似姓名候选",
            "pattern": "surname+len(2-3|compound-4)",
            "matched_text": "张无",
            "match_type": "candidate",
            "confidence": 0.72,
            "needs_verification": True,
            "reason": "single_surname_match",
        }
    ]


def test_route_with_peeling_does_not_materialize_candidate_when_other_conditions_exist():
    router = _build_router(_StubLevel4Empty())

    parsed = router._materialize_name_candidate_if_needed([
        Condition(field="clientMobile", operator=Operator.MATCH, value="13800138000")
    ])

    assert [(cond.field, cond.operator, cond.value) for cond in parsed] == [
        ("clientMobile", Operator.MATCH, "13800138000")
    ]


def test_route_with_peeling_uses_l2_candidate_conditions_to_override_l4():
    router = _build_router_with_l2_candidates(
        _StubLevel4WrongMobile(),
        [
            Condition(field="clientMobile", operator=Operator.MATCH, value="13800138000"),
            Condition(field="clientSex", operator=Operator.MATCH, value="男"),
        ],
    )
    router._valid_fields = {"clientMobile", "clientSex"}

    parsed = asyncio.run(router.route_with_peeling("手机号13800138000的男客户"))

    assert [(cond.field, cond.operator, cond.value) for cond in parsed.conditions] == [
        ("clientMobile", Operator.MATCH, "13800138000"),
        ("clientSex", Operator.MATCH, "男"),
    ]
