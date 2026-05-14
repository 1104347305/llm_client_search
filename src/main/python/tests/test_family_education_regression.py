import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.main.python.steps.query_router import QueryRouter
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
