import asyncio

from src.main.python.models.schemas import Operator
from src.main.python.steps.level2_enhanced_matcher import Level2EnhancedMatcher


def test_customer_suffix_pattern_var_is_expanded():
    matcher = Level2EnhancedMatcher()

    rendered_patterns = [
        pattern
        for rule in matcher.rules
        for pattern in rule.get("patterns", [])
    ]

    assert not any("{CUSTOMER_SUFFIX}" in pattern for pattern in rendered_patterns)
    assert any(
        "(?:的客户|客户|有哪些客户|有哪些人|名单|的人|人)?" in pattern
        for pattern in rendered_patterns
    )


def test_customer_suffix_pattern_var_preserves_high_value_suffix_match():
    matcher = Level2EnhancedMatcher()

    conditions = asyncio.run(matcher.match("高价值名单"))

    assert len(conditions) == 1
    condition = conditions[0]
    assert condition.field == "newValueLabel"
    assert condition.operator == Operator.CONTAINS
    assert condition.value == ["A1", "A2", "A3", "A4", "B", "C"]
