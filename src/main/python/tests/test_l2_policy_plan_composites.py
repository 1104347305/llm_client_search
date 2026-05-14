import asyncio
import sys
from pathlib import Path

from loguru import logger


PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.main.python.steps.level2_enhanced_matcher import Level2EnhancedMatcher


logger.remove()
logger.add(sys.stderr, level="ERROR")


def _match(query: str):
    matcher = Level2EnhancedMatcher()
    return asyncio.run(matcher.match(query)), matcher


def test_l2_matches_policy_plan_abbr_and_plan_type_as_and_conditions():
    conditions, matcher = _match("帮我查询一下投保险种名为i康保投保险种类型为健康险的客户")

    values = {(condition.field, condition.operator.value): condition.value for condition in conditions}

    assert values[("polNoInfo.plancodeinfo.abbrname", "MATCH")] == "i康保"
    assert values[("polNoInfo.plancodeinfo.plantypedesc", "MATCH")] == "健康险"
    assert any(
        item["rule_name"] == "投保险种简称+投保险种类型"
        for item in matcher._last_matched_patterns
    )


def test_l2_matches_policy_plan_type_and_abbr_in_reverse_order():
    conditions, matcher = _match("帮我查询一下投保险种类型为健康险投保险种简称为i康保的客户")

    values = {(condition.field, condition.operator.value): condition.value for condition in conditions}

    assert values[("polNoInfo.plancodeinfo.plantypedesc", "MATCH")] == "健康险"
    assert values[("polNoInfo.plancodeinfo.abbrname", "MATCH")] == "i康保"
    assert any(
        item["rule_name"] == "投保险种简称+投保险种类型"
        for item in matcher._last_matched_patterns
    )


def test_l2_matches_policy_plan_abbr_and_policy_status_as_and_conditions():
    conditions, matcher = _match("买了i康保产品，且保单状态为缴费有效的客户")

    values = {(condition.field, condition.operator.value): condition.value for condition in conditions}

    assert values[("polNoInfo.plancodeinfo.abbrname", "MATCH")] == "i康保"
    assert values[("polNoInfo.polStatus", "MATCH")] == "缴费有效"
    assert any(
        item["rule_name"] == "投保险种简称+保单状态"
        for item in matcher._last_matched_patterns
    )


def test_l2_matches_policy_status_and_plan_abbr_in_reverse_order():
    conditions, matcher = _match("保单状态为缴费有效，买了i康保产品的客户")

    values = {(condition.field, condition.operator.value): condition.value for condition in conditions}

    assert values[("polNoInfo.polStatus", "MATCH")] == "缴费有效"
    assert values[("polNoInfo.plancodeinfo.abbrname", "MATCH")] == "i康保"
    assert any(
        item["rule_name"] == "投保险种简称+保单状态"
        for item in matcher._last_matched_patterns
    )


def test_l2_matches_policy_plan_fullname_and_policy_status_as_and_conditions():
    conditions, matcher = _match("投保险种名称为平安i康保医疗保险，且保单状态为缴费有效的客户")

    values = {(condition.field, condition.operator.value): condition.value for condition in conditions}

    assert values[("polNoInfo.plancodeinfo.planfullname", "MATCH")] == "平安i康保医疗保险"
    assert values[("polNoInfo.polStatus", "MATCH")] == "缴费有效"
    assert any(
        item["rule_name"] == "投保险种名称+保单状态"
        for item in matcher._last_matched_patterns
    )


def test_l2_matches_policy_status_oral_variants():
    cases = {
        "自垫停效状态的客户": "自垫停效",
        "贷款超停的客户名单": "贷款超停",
        "犹豫期退保的客户有哪些": "犹豫期退保",
        "哪些客户的保单还在交费有效": "交费有效",
    }

    for query, expected in cases.items():
        conditions, _ = _match(query)
        values = {(condition.field, condition.operator.value): condition.value for condition in conditions}
        assert values[("polNoInfo.polStatus", "MATCH")] == expected


def test_l2_maps_eshenbao_effective_customer_to_policy_status_not_effective_date():
    conditions, _ = _match("e生保生效客户")

    values = {(condition.field, condition.operator.value): condition.value for condition in conditions}

    assert values[("polNoInfo.plancodeinfo.abbrname", "MATCH")] == "e生保"
    assert values[("polNoInfo.polStatus", "CONTAINS")] == [
        "交费有效",
        "自垫交清",
        "交清",
        "减额交清",
        "免交",
        "自垫有效",
    ]
    assert not any(condition.field == "polNoInfo.poleffdate" for condition in conditions)


def test_l2_maps_cross_sell_product_exists_to_agent_persp_product_type():
    conditions, _ = _match("有综拓产品的客户")
    assert [(condition.field, condition.operator.value, condition.value) for condition in conditions] == [
        ("agentPerspProductType", "EXISTS", None)
    ]


def test_l2_candidate_recall_maps_policy_expiry_status_and_cross_sell_product():
    matcher = Level2EnhancedMatcher()

    conditions = matcher.recall_candidate_conditions(
        "找个客户保单到期时间在2026年10月、保单状态有效、有综拓产品的"
    )
    values = {(condition.field, condition.operator.value): condition.value for condition in conditions}

    assert values[("agentPerspProductType", "EXISTS")] is None
    assert values[("polNoInfo.polStatus", "CONTAINS")] == [
        "交费有效",
        "自垫交清",
        "交清",
        "减额交清",
        "免交",
        "自垫有效",
    ]
    assert values[("validSinsMatuDateTime", "RANGE")].min == "2026-10-01 00:00:00"
    assert values[("validSinsMatuDateTime", "RANGE")].max == "2026-10-31 23:59:59"
    assert not any(condition.field == "validSinsPol" for condition in conditions)


def test_l2_candidate_recall_maps_single_to_marital_status():
    matcher = Level2EnhancedMatcher()

    conditions = matcher.recall_candidate_conditions("20多岁单身有e生保的")
    values = {(condition.field, condition.operator.value): condition.value for condition in conditions}

    assert values[("mariSts", "CONTAINS")] == ["未婚", "离婚"]


def test_l2_matches_policy_datetime_fields_with_time_part():
    conditions, _ = _match("保单应缴日是2026-12-31 23:59:59的客户")
    values = {(condition.field, condition.operator.value): condition.value for condition in conditions}
    assert values[("polNoInfo.payToDate", "RANGE")].min == "2026-12-31 23:59:59"
    assert values[("polNoInfo.payToDate", "RANGE")].max == "2026-12-31 23:59:59"

    conditions, _ = _match("在2026-06-30 23:59:59发生理赔的客户")
    values = {(condition.field, condition.operator.value): condition.value for condition in conditions}
    assert values[("polNoInfo.claimdatainfo.claimdate", "MATCH")].min == "2026-06-30 23:59:59"
    assert values[("polNoInfo.claimdatainfo.claimdate", "MATCH")].max == "2026-06-30 23:59:59"


def test_l2_matches_policy_beneficiary_without_trailing_de():
    conditions, _ = _match("查询受益人是李四的保单客户")
    values = {(condition.field, condition.operator.value): condition.value for condition in conditions}
    assert values[("polNoInfo.benefinfo.benefname", "MATCH")] == "李四"


def test_l2_matches_survival_unclaimed_boolean_oral_variants():
    cases = {
        "未领取生存金金额是否大于0为是的客户": "是",
        "生存金都领完了的客户": "否",
    }

    for query, expected in cases.items():
        conditions, _ = _match(query)
        values = {(condition.field, condition.operator.value): condition.value for condition in conditions}
        assert values[("polNoInfo.payamountdue", "MATCH")] == expected
