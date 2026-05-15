import asyncio
import sys
from pathlib import Path
from datetime import date

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.main.python.steps.query_router import QueryRouter
from src.main.python.steps.level2_enhanced_matcher import Level2EnhancedMatcher
from src.main.python.models.schemas import Condition, RangeValue
from src.main.python.models.schemas import Operator


def test_age_around_with_daughter_in_middle_school_parses():
    parsed = asyncio.run(
        QueryRouter().route_with_peeling("35岁左右有女儿上初中的")
    )

    values = {(condition.field, condition.operator): condition.value for condition in parsed.conditions}

    assert parsed.matched_level == 2
    assert values[("clientAge", Operator.RANGE)].min == 30
    assert values[("clientAge", Operator.RANGE)].max == 40
    assert values[("familyInfo.familyclientage", Operator.RANGE)].min == 12
    assert values[("familyInfo.familyclientage", Operator.RANGE)].max == 15
    assert values[("familyInfo.familyrelation", Operator.MATCH)] == "子女"
    assert values[("familyInfo.familyclientsex", Operator.MATCH)] == "女"


def test_child_age_range_with_optional_zai_parses():
    conditions = asyncio.run(Level2EnhancedMatcher().match("子女在3-5周岁"))
    values = {(condition.field, condition.operator): condition.value for condition in conditions}

    assert values[("familyInfo.familyclientage", Operator.RANGE)].min == 3
    assert values[("familyInfo.familyclientage", Operator.RANGE)].max == 5
    assert values[("familyInfo.familyrelation", Operator.CONTAINS)] == ["子女"]


def test_family_age_converts_to_precise_birthday_range():
    router = QueryRouter.__new__(QueryRouter)
    conditions = [
        Condition(
            field="familyInfo.familyclientage",
            operator=Operator.RANGE,
            value=RangeValue(min=3, max=5),
        )
    ]

    converted = router.convert_age_to_birthday(conditions, today=date(2026, 5, 14))

    assert len(converted) == 1
    assert converted[0].field == "familyInfo.familyclientbirthday"
    assert converted[0].operator == Operator.RANGE
    assert converted[0].value.min == "2020-05-15 00:00:00"
    assert converted[0].value.max == "2023-05-14 23:59:59"


def test_customer_value_with_elderly_family_member_parses():
    parsed = asyncio.run(
        QueryRouter().route_with_peeling("B类客户家里有老人的")
    )

    values = {(condition.field, condition.operator): condition.value for condition in parsed.conditions}

    assert parsed.matched_level == 2
    assert values[("newValueLabel", Operator.MATCH)] == "B"
    assert values[("familyInfo.familyclientage", Operator.GTE)] == 55


def test_child_name_from_parent_policy_phrase_parses():
    for query, child_name in [
        ("李美爸爸保单", "李美"),
        ("贾小丽父亲", "贾小丽"),
        ("李辛的父亲", "李辛"),
    ]:
        parsed = asyncio.run(QueryRouter().route_with_peeling(query))
        values = {(condition.field, condition.operator): condition.value for condition in parsed.conditions}

        assert parsed.matched_level == 2
        assert values[("familyInfo.familyrelation", Operator.MATCH)] == "子女"
        assert values[("familyInfo.familyclientname", Operator.MATCH)] == child_name
