import asyncio
from src.main.python.steps.level1_rule_engine import Level1RuleEngine
from src.main.python.steps.level2_enhanced_matcher import Level2EnhancedMatcher
from src.main.python.steps.query_router import QueryRouter
from src.main.python.models.schemas import Condition, Operator, QueryLogic


class _StubFieldRegistry:
    def normalize_query(self, query: str) -> str:
        return query


class _StubLevel2:
    def __init__(self, conditions=None):
        self.conditions = conditions or []
        self._last_matched_patterns = []
        self.bare_value_weak_match = {
            "pattern": "[A-Za-z0-9]{1,64}",
            "operator": "MATCH",
            "confidence": 0.6,
        }

    async def match(self, query):
        return self.conditions

    def recall_candidate_conditions(self, query):
        return []

    def is_bare_value_weak_query(self, query):
        return bool(query.isalnum())

    def build_bare_value_weak_conditions(self, query):
        fields = ["clientNo", "polNo", "clientMobile", "idNo"] if query.isdigit() else ["clientNo", "polNo", "idNo"]
        return [Condition(field=field, operator=Operator.MATCH, value=query) for field in fields]

    def bare_value_weak_confidence(self):
        return 0.6


class _UnexpectedLevel4:
    async def parse(self, query):
        raise AssertionError("裸值弱命不应进入 L4")


def _build_router(level2=None):
    router = QueryRouter.__new__(QueryRouter)
    router.level1 = Level1RuleEngine()
    router.level2 = level2 or _StubLevel2()
    router.level3 = None
    router.level4 = _UnexpectedLevel4()
    router.field_registry = _StubFieldRegistry()
    router._valid_fields = {"clientNo", "polNo", "clientMobile", "idNo"}
    router._enum_values = {}
    router._last_rewritten_query = None
    router._last_matched_patterns = []
    router._last_name_candidate = None
    return router


def test_bare_numeric_without_confirmed_l1_l2_returns_weak_or_candidates():
    parsed = asyncio.run(_build_router().route_with_peeling("123456"))

    assert parsed.query_logic == QueryLogic.OR
    assert parsed.confidence == 0.6
    assert [condition.field for condition in parsed.conditions] == [
        "clientNo",
        "polNo",
        "clientMobile",
        "idNo",
    ]
    assert {condition.value for condition in parsed.conditions} == {"123456"}
    assert parsed.matched_patterns[-1]["rule_name"] == "裸值弱命"


def test_bare_alnum_without_confirmed_l1_l2_excludes_mobile_candidate():
    parsed = asyncio.run(_build_router().route_with_peeling("A12345"))

    assert parsed.query_logic == QueryLogic.OR
    assert [condition.field for condition in parsed.conditions] == [
        "clientNo",
        "polNo",
        "idNo",
    ]


def test_bare_four_digits_is_confirmed_mobile_not_weak_or():
    parsed = asyncio.run(_build_router(Level2EnhancedMatcher()).route_with_peeling("1234"))

    assert parsed.query_logic == QueryLogic.AND
    assert [(condition.field, condition.operator, condition.value) for condition in parsed.conditions] == [
        ("clientMobile", Operator.MATCH, "1234")
    ]


def test_l2_confirmed_match_wins_over_bare_weak_match():
    parsed = asyncio.run(
        _build_router(
            _StubLevel2([
                Condition(field="clientNo", operator=Operator.MATCH, value="123456")
            ])
        ).route_with_peeling("123456")
    )

    assert parsed.query_logic == QueryLogic.AND
    assert [(condition.field, condition.value) for condition in parsed.conditions] == [
        ("clientNo", "123456")
    ]


def test_level2_does_not_confirm_incomplete_bare_values():
    matcher = Level2EnhancedMatcher()

    assert asyncio.run(matcher.match("123456")) == []
    assert asyncio.run(matcher.match("P123456")) == []
    assert asyncio.run(matcher.match("C1234567890")) == []
    assert [(condition.field, condition.value) for condition in matcher.build_bare_value_weak_conditions("123456")] == [
        ("clientNo", "123456"),
        ("polNo", "123456"),
        ("clientMobile", "123456"),
        ("idNo", "123456"),
    ]


def test_bare_value_weak_fields_are_configurable_for_all_value_shapes():
    matcher = Level2EnhancedMatcher.__new__(Level2EnhancedMatcher)
    matcher.bare_value_weak_match = {
        "pattern": "[A-Za-z0-9]{1,64}",
        "operator": "MATCH",
        "fields": ["candidateField"],
    }

    assert [(condition.field, condition.value) for condition in matcher.build_bare_value_weak_conditions("123")] == [
        ("candidateField", "123")
    ]
    assert [(condition.field, condition.value) for condition in matcher.build_bare_value_weak_conditions("ABC")] == [
        ("candidateField", "ABC")
    ]
    assert [(condition.field, condition.value) for condition in matcher.build_bare_value_weak_conditions("A123")] == [
        ("candidateField", "A123")
    ]


def test_bare_value_weak_fields_keep_legacy_numeric_and_alnum_fallback():
    matcher = Level2EnhancedMatcher.__new__(Level2EnhancedMatcher)
    matcher.bare_value_weak_match = {
        "pattern": "[A-Za-z0-9]{1,64}",
        "operator": "MATCH",
        "numeric_fields": ["legacyNumericField"],
        "alnum_fields": ["legacyAlnumField"],
    }

    assert [(condition.field, condition.value) for condition in matcher.build_bare_value_weak_conditions("123")] == [
        ("legacyNumericField", "123")
    ]
    assert [(condition.field, condition.value) for condition in matcher.build_bare_value_weak_conditions("ABC")] == [
        ("legacyAlnumField", "ABC")
    ]


def test_level2_confirms_only_complete_policy_and_customer_number_formats():
    matcher = Level2EnhancedMatcher()

    policy = asyncio.run(matcher.match("P12345678901234A"))
    assert [(condition.field, condition.value) for condition in policy] == [
        ("polNo", "P12345678901234A")
    ]

    customer_c = asyncio.run(matcher.match("C12345678901"))
    assert [(condition.field, condition.value) for condition in customer_c] == [
        ("clientNo", "C12345678901")
    ]

    customer_00 = asyncio.run(matcher.match("001234567890"))
    assert [(condition.field, condition.value) for condition in customer_00] == [
        ("clientNo", "001234567890")
    ]


def test_level2_context_allows_loose_values_and_ignores_case():
    matcher = Level2EnhancedMatcher()

    policy = asyncio.run(matcher.match("保单号p123"))
    assert [(condition.field, condition.value) for condition in policy] == [
        ("polNo", "p123")
    ]

    customer = asyncio.run(matcher.match("客户号c123"))
    assert [(condition.field, condition.value) for condition in customer] == [
        ("clientNo", "c123")
    ]

    certificate = asyncio.run(matcher.match("护照号e12345"))
    assert [(condition.field, condition.value) for condition in certificate] == [
        ("idType", "护照"),
        ("idNo", "e12345")
    ]


def test_level2_identifier_oral_variants():
    matcher = Level2EnhancedMatcher()

    cases = [
        ("手机尾号为1234的客户", "clientMobile", "1234"),
        ("1234尾号的手机号", "clientMobile", "1234"),
        ("手机号138开头的客户", "clientMobile", "138"),
        ("客户编号尾号为7890的客户", "clientNo", "7890"),
        ("C123开头的客户号", "clientNo", "C123"),
        ("保单编号包含P123456的客户", "polNo", "P123456"),
        ("保单号P123结尾的客户", "polNo", "P123"),
        ("123456尾号的保单号", "polNo", "123456"),
        ("身份证后四位是123X的客户", "idNo", "123X"),
        ("E12345开头的护照号", "idNo", "E12345"),
    ]

    for query, expected_field, expected_value in cases:
        conditions = asyncio.run(matcher.match(query))
        assert (expected_field, expected_value) in [
            (condition.field, condition.value) for condition in conditions
        ], query
