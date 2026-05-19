import asyncio

from steps.level2_enhanced_matcher import Level2EnhancedMatcher


_MATCHER = None


def _conditions(query):
    global _MATCHER
    if _MATCHER is None:
        _MATCHER = Level2EnhancedMatcher()
    return asyncio.run(_MATCHER.match(query))


def test_name_plus_two_digit_birth_year_maps_name_and_birthday():
    conditions = _conditions("王萍86年")

    assert [(condition.field, condition.operator.value) for condition in conditions] == [
        ("searchClientName", "MATCH"),
        ("clientBirthday", "RANGE"),
    ]
    assert conditions[0].value == "王萍"
    assert conditions[1].value.min == "1986-01-01 00:00:00"
    assert conditions[1].value.max == "1986-12-31 00:00:00"


def test_name_plus_four_digit_birth_year_maps_name_and_birthday():
    conditions = _conditions("王萍1983年出生")

    assert [(condition.field, condition.operator.value) for condition in conditions] == [
        ("searchClientName", "MATCH"),
        ("clientBirthday", "RANGE"),
    ]
    assert conditions[0].value == "王萍"
    assert conditions[1].value.min == "1983-01-01 00:00:00"
    assert conditions[1].value.max == "1983-12-31 00:00:00"


def test_chinese_month_birth_query_maps_to_birthday_md():
    conditions = _conditions("一月出生的客户")

    assert len(conditions) == 1
    assert conditions[0].field == "birthdayMd"
    assert conditions[0].operator.value == "RANGE"
    assert conditions[0].value.min == "01-01"
    assert conditions[0].value.max == "01-31"


def test_two_digit_birth_year_maps_to_client_birthday():
    conditions = _conditions("94年的客户")

    assert len(conditions) == 1
    assert conditions[0].field == "clientBirthday"
    assert conditions[0].value.min == "1994-01-01 00:00:00"
    assert conditions[0].value.max == "1994-12-31 00:00:00"


def test_home_care_generic_terms_map_to_grade_range():
    expected = ["v0.5", "v1", "v1.5", "v2", "v2.5", "v3"]

    for query in ["居家客户", "居家养老客户", "居家会员", "居家达标客户", "有居家权益的客户"]:
        conditions = _conditions(query)
        assert len(conditions) == 1, query
        assert conditions[0].field == "jujiaClientGrade"
        assert conditions[0].operator.value == "CONTAINS"
        assert conditions[0].value == expected


def test_kangyang_generic_terms_map_to_grade_range():
    expected = ["逸享会员", "逸享PLUS会员", "颐享家会员", "臻享会员V1", "臻享会员V2", "臻享会员V3"]

    for query in ["康养客户", "康养达标客户", "康养会员", "有康养权益的客户"]:
        conditions = _conditions(query)
        assert len(conditions) == 1, query
        assert conditions[0].field == "kangyangClientGrade"
        assert conditions[0].operator.value == "CONTAINS"
        assert conditions[0].value == expected


def test_an_you_hu_generic_terms_map_to_grade_range():
    expected = ["安有护(国际版)", "安有护(国内版)"]

    for query in ["安有护客户", "安有护达标客户", "安有护会员", "有安有护权益的客户"]:
        conditions = _conditions(query)
        assert len(conditions) == 1, query
        assert conditions[0].field == "zhenxiangRunEquityGrade"
        assert conditions[0].operator.value == "CONTAINS"
        assert conditions[0].value == expected


def test_hyphenated_mobile_maps_to_client_mobile_digits():
    conditions = _conditions("0012-9800-4983")

    assert len(conditions) == 1
    assert conditions[0].field == "clientMobile"
    assert conditions[0].operator.value == "MATCH"
    assert conditions[0].value == "001298004983"


def test_customer_value_shorthand_above_excludes_boundary():
    conditions = _conditions("客价B以上的客户")

    assert len(conditions) == 1
    assert conditions[0].field == "newValueLabel"
    assert conditions[0].operator.value == "CONTAINS"
    assert conditions[0].value == ["A4", "A3", "A2", "A1"]


def test_customer_value_shorthand_gte_includes_boundary():
    conditions = _conditions("客价B及以上的客户")

    assert len(conditions) == 1
    assert conditions[0].field == "newValueLabel"
    assert conditions[0].operator.value == "CONTAINS"
    assert conditions[0].value == ["B", "A4", "A3", "A2", "A1"]
