import asyncio

from core.level2_enhanced_matcher import Level2EnhancedMatcher


def test_birth_year_range_uses_datetime_format():
    matcher = Level2EnhancedMatcher("config/enhanced_rules.yaml")

    conditions = asyncio.run(matcher.match("1953年出生"))

    assert len(conditions) == 1
    condition = conditions[0]
    assert condition.field == "clientBirthday"
    assert condition.operator.value == "RANGE"
    assert condition.value.min == "1953-01-01 00:00:00"
    assert condition.value.max == "1953-12-31 00:00:00"


def test_exact_birthday_uses_datetime_format():
    matcher = Level2EnhancedMatcher("config/enhanced_rules.yaml")

    conditions = asyncio.run(matcher.match("出生于19900101的客户"))

    assert len(conditions) == 1
    condition = conditions[0]
    assert condition.field == "clientBirthday"
    assert condition.operator.value == "MATCH"
    assert condition.value == "1990-01-01 00:00:00"
