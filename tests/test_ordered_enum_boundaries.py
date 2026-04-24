import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.level2_enhanced_matcher import Level2EnhancedMatcher
from models.schemas import Operator


matcher = Level2EnhancedMatcher("config/enhanced_rules.yaml")


def _match(query: str):
    return asyncio.run(matcher.match(query))


def _single(query: str):
    conditions = _match(query)
    assert len(conditions) == 1
    condition = conditions[0]
    assert condition.operator == Operator.CONTAINS
    return condition


def test_customer_value_above_excludes_boundary():
    condition = _single("客户价值B以上的客户")
    assert condition.field == "newValueLabel"
    assert condition.value == ["A4", "A3", "A2", "A1"]


def test_customer_value_and_above_includes_boundary():
    condition = _single("客户价值B及以上的客户")
    assert condition.field == "newValueLabel"
    assert condition.value == ["B", "A4", "A3", "A2", "A1"]


def test_customer_temperature_above_excludes_boundary():
    condition = _single("中温以上的客户")
    assert condition.field == "clientTemperature"
    assert condition.value == ["高温"]


def test_customer_temperature_and_above_includes_boundary():
    condition = _single("中温及以上的客户")
    assert condition.field == "clientTemperature"
    assert condition.value == ["中温", "高温"]


def test_vip_above_excludes_boundary():
    condition = _single("黄金V2以上的客户")
    assert condition.field == "vipType"
    assert condition.value == [
        "黄金V3",
        "原黄金VIP",
        "铂金V1",
        "铂金V2",
        "原铂金VIP",
        "钻石VIP",
        "金钻VIP",
        "黑钻VIP",
    ]


def test_vip_and_above_includes_boundary():
    condition = _single("黄金V2及以上的客户")
    assert condition.field == "vipType"
    assert condition.value == [
        "黄金V2",
        "黄金V3",
        "原黄金VIP",
        "铂金V1",
        "铂金V2",
        "原铂金VIP",
        "钻石VIP",
        "金钻VIP",
        "黑钻VIP",
    ]


def test_jujia_below_excludes_boundary():
    condition = _single("居家v2以下的客户")
    assert condition.field == "searchJujiaClientGrade"
    assert condition.value == ["居家潜客", "v0.5", "v1", "v1.5"]


def test_jujia_and_below_includes_boundary():
    condition = _single("居家v2及以下的客户")
    assert condition.field == "searchJujiaClientGrade"
    assert condition.value == ["居家潜客", "v0.5", "v1", "v1.5", "v2"]


def test_kangyang_above_excludes_boundary():
    condition = _single("逸享PLUS会员以上的客户")
    assert condition.field == "searchKangyangClientGrade"
    assert condition.value == ["颐享家会员", "臻享会员V1", "臻享会员V2", "臻享会员V3"]


def test_kangyang_and_above_includes_boundary():
    condition = _single("逸享PLUS会员及以上的客户")
    assert condition.field == "searchKangyangClientGrade"
    assert condition.value == ["逸享PLUS会员", "颐享家会员", "臻享会员V1", "臻享会员V2", "臻享会员V3"]
