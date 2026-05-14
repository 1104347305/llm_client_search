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


def test_march_birthday_maps_to_month_range():
    matcher = Level2EnhancedMatcher("config/enhanced_rules.yaml")

    conditions = asyncio.run(matcher.match("3月份过生日的客户"))

    assert len(conditions) == 1
    condition = conditions[0]
    assert condition.field == "birthdayMd"
    assert condition.operator.value == "RANGE"
    assert condition.value.min == "03-01"
    assert condition.value.max == "03-31"


def test_policy_anniversary_in_july_maps_to_month_range():
    matcher = Level2EnhancedMatcher("config/enhanced_rules.yaml")

    conditions = asyncio.run(matcher.match("保单周年日在7月的客户"))

    assert len(conditions) == 1
    condition = conditions[0]
    assert condition.field == "effAnniversaryDate"
    assert condition.operator.value == "RANGE"
    assert condition.value.min == "07-01"
    assert condition.value.max == "07-31"


def test_customer_birthday_in_march_maps_to_month_range():
    matcher = Level2EnhancedMatcher("config/enhanced_rules.yaml")

    conditions = asyncio.run(matcher.match("客户生日在3月的客户"))

    assert len(conditions) == 1
    condition = conditions[0]
    assert condition.field == "birthdayMd"
    assert condition.operator.value == "RANGE"
    assert condition.value.min == "03-01"
    assert condition.value.max == "03-31"
