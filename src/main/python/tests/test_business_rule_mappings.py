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


def test_high_value_customer_maps_to_abc_groups():
    conditions = _match("客户高价值")
    assert len(conditions) == 1
    condition = conditions[0]
    assert condition.field == "newValueLabel"
    assert condition.operator == Operator.CONTAINS
    assert condition.value == ["A1", "A2", "A3", "A4", "B", "C"]


def test_million_medical_maps_to_specific_products():
    conditions = _match("百万医疗的客户")
    assert len(conditions) == 1
    condition = conditions[0]
    assert condition.field == "planAbbrNames"
    assert condition.operator == Operator.CONTAINS
    assert condition.value == [
        "百万任我行18",
        "倍享百万",
        "百万任我行",
        "百万任我行17",
        "百万随行",
        "百万任我行22",
        "百万任我行23",
        "百万任我行25",
    ]


def test_high_sum_insured_maps_to_300k_threshold():
    conditions = _match("高保额客户")
    assert len(conditions) == 1
    condition = conditions[0]
    assert condition.field == "insnoSumInsSeq"
    assert condition.operator == Operator.GTE
    assert condition.value == 300000


def test_tax_preferred_pension_maps_to_product_group():
    conditions = _match("税优养老产品的客户")
    assert len(conditions) == 1
    condition = conditions[0]
    assert condition.field == "planAbbrNames"
    assert condition.operator == Operator.CONTAINS
    assert "税优养老" in condition.value
    assert "智盈倍护23" in condition.value
    assert "盛世优享24" in condition.value
    assert "金越养老年金（分红）25" in condition.value


def test_level2_can_read_grouped_enum_values_from_config():
    assert "millionMedicalProducts" in matcher.enum_values
    assert "taxPreferredPensionProducts" in matcher.enum_values
    assert "百万任我行18" in matcher.enum_values["millionMedicalProducts"]
    assert "税优养老23" in matcher.enum_values["taxPreferredPensionProducts"]


def test_no_car_insurance_but_has_house_does_not_fall_back_to_no_house_no_car():
    conditions = _match("没有车险但是名下有房的客户")

    assert [(condition.field, condition.operator, condition.value) for condition in conditions] == [
        ("isBuyPregnancyCar", Operator.MATCH, "非车险"),
        ("assetsCondition", Operator.CONTAINS, ["有房", "有房有车"]),
    ]


def test_family_has_elderly_maps_to_parent_and_grandparent_relations():
    conditions = _match("家里有老人的客户")

    assert [(condition.field, condition.operator, condition.value) for condition in conditions] == [
        ("familyRelation", Operator.CONTAINS, ["父母", "（外）祖父母"]),
    ]


def test_non_car_insurance_does_not_match_car_insurance_rule():
    conditions = _match("非车险客户")

    assert [(condition.field, condition.operator, condition.value) for condition in conditions] == [
        ("isBuyPregnancyCar", Operator.MATCH, "非车险"),
    ]


def test_simple_gender_rule_does_not_extract_female_from_child_relation():
    conditions = _match("有子女的客户")

    assert ("clientSex", Operator.MATCH, "女") not in [
        (condition.field, condition.operator, condition.value) for condition in conditions
    ]


def test_has_insurance_maps_to_policy_no_exists():
    conditions = _match("有没有买过保险的客户")

    assert [(condition.field, condition.operator) for condition in conditions] == [
        ("policyNo", Operator.EXISTS),
    ]


def test_no_insurance_maps_to_policy_no_not_exists():
    conditions = _match("没有买过保单的客户")

    assert [(condition.field, condition.operator) for condition in conditions] == [
        ("policyNo", Operator.NOT_EXISTS),
    ]


def test_exact_sum_insured_maps_to_match():
    conditions = _match("总保额50万的客户")

    assert [(condition.field, condition.operator, condition.value) for condition in conditions] == [
        ("insnoSumInsSeq", Operator.MATCH, 500000),
    ]


def test_house_without_car_maps_to_house_asset_status():
    conditions = _match("有房无车的客户")

    assert [(condition.field, condition.operator, condition.value) for condition in conditions] == [
        ("assetsCondition", Operator.CONTAINS, ["有房"]),
    ]


def test_house_rule_does_not_overmatch_but_no_car_phrase():
    conditions = _match("名下有房但是没车的客户")

    assert [(condition.field, condition.operator, condition.value) for condition in conditions] == [
        ("assetsCondition", Operator.CONTAINS, ["有房"]),
    ]


def test_only_house_no_car_phrase_maps_to_house_asset_status():
    conditions = _match("帮我查只有房没有车的客户")

    assert [(condition.field, condition.operator, condition.value) for condition in conditions] == [
        ("assetsCondition", Operator.CONTAINS, ["有房"]),
    ]


def test_only_car_no_house_phrase_maps_to_car_asset_status():
    conditions = _match("找那种有车但是没有房的客户")

    assert [(condition.field, condition.operator, condition.value) for condition in conditions] == [
        ("assetsCondition", Operator.CONTAINS, ["有车"]),
    ]


def test_age_gte_life_product_and_life_insurance_customer_combo():
    conditions = _match('帮我查一下50岁以上购买过“智能星”产品的寿险客户')
    values = {(condition.field, condition.operator.value): condition.value for condition in conditions}

    assert values[("clientAge", "GTE")] == 50
    assert values[("planAbbrNames", "CONTAINS")] == "智能星"
    assert ("planAbbrNames", "EXISTS") not in values
