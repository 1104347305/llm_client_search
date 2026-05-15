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
    conditions, matcher = _match("帮我查询一下投保险种名为e生保投保险种类型为健康险的客户")

    values = {(condition.field, condition.operator.value): condition.value for condition in conditions}

    assert values[("polNoInfo.plancodeinfo.abbrname", "MATCH")] == "e生保"
    assert values[("polNoInfo.plancodeinfo.plantypedesc", "MATCH")] == "健康险"


def test_l2_matches_policy_plan_type_and_abbr_in_reverse_order():
    conditions, matcher = _match("帮我查询一下投保险种类型为健康险投保险种简称为e生保的客户")

    values = {(condition.field, condition.operator.value): condition.value for condition in conditions}

    assert values[("polNoInfo.plancodeinfo.plantypedesc", "MATCH")] == "健康险"
    assert values[("polNoInfo.plancodeinfo.abbrname", "MATCH")] == "e生保"


def test_l2_matches_policy_plan_abbr_and_policy_status_as_and_conditions():
    conditions, matcher = _match("买了e生保产品，且保单状态为缴费有效的客户")

    values = {(condition.field, condition.operator.value): condition.value for condition in conditions}

    assert values[("polNoInfo.plancodeinfo.abbrname", "MATCH")] == "e生保"
    assert values[("polNoInfo.polStatus", "MATCH")] == "交费有效"


def test_l2_matches_policy_status_and_plan_abbr_in_reverse_order():
    conditions, matcher = _match("保单状态为缴费有效，买了e生保产品的客户")

    values = {(condition.field, condition.operator.value): condition.value for condition in conditions}

    assert values[("polNoInfo.polStatus", "MATCH")] == "交费有效"
    assert values[("polNoInfo.plancodeinfo.abbrname", "MATCH")] == "e生保"


def test_l2_matches_policy_plan_fullname_and_policy_status_as_and_conditions():
    conditions, matcher = _match("投保险种名称为平安e生保医疗保险，且保单状态为缴费有效的客户")

    values = {(condition.field, condition.operator.value): condition.value for condition in conditions}

    assert values[("polNoInfo.plancodeinfo.planfullname", "MATCH")] == "平安e生保医疗保险"
    assert values[("polNoInfo.polStatus", "MATCH")] == "交费有效"


def test_l2_matches_policy_plan_case_insensitive_variants():
    cases = [
        (
            "买了E生保产品，且保单状态为缴费有效的客户",
            "polNoInfo.plancodeinfo.abbrname",
            "e生保",
        ),
        (
            "投保险种名称为平安E生保医疗保险，且保单状态为缴费有效的客户",
            "polNoInfo.plancodeinfo.planfullname",
            "平安e生保医疗保险",
        ),
    ]

    for query, field, expected_value in cases:
        conditions, matcher = _match(query)
        values = {(condition.field, condition.operator.value): condition.value for condition in conditions}

        assert values[(field, "MATCH")] == expected_value
        assert values[("polNoInfo.polStatus", "MATCH")] == "交费有效"


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


def test_l2_maps_eshenbao_not_lapsed_customer_to_effective_policy_status():
    conditions, _ = _match("e生保未失效客户")

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


def test_l2_matches_policy_datetime_fields():
    conditions, _ = _match("保单应缴日是2026-12-31的客户")
    values = {(condition.field, condition.operator.value): condition.value for condition in conditions}
    assert values[("polNoInfo.paytodate", "RANGE")].min == "2026-12-31 00:00:00"
    assert values[("polNoInfo.paytodate", "RANGE")].max == "2026-12-31 00:00:00"

    conditions, _ = _match("在2026-06-30理赔的客户")
    values = {(condition.field, condition.operator.value): condition.value for condition in conditions}
    assert values[("polNoInfo.claimdatainfo.claimdate", "RANGE")].min == "2026-06-30 00:00:00"
    assert values[("polNoInfo.claimdatainfo.claimdate", "RANGE")].max == "2026-06-30 00:00:00"


def test_l2_matches_policy_pay_date_relative_ranges():
    matcher = Level2EnhancedMatcher()
    cases = [
        "有应缴日在下周的客户",
        "有应缴日在下下周的客户",
        "未来7天应缴的客户",
        "有应缴日在今天的客户",
    ]

    for query in cases:
        conditions = asyncio.run(matcher.match(query))
        values = {(condition.field, condition.operator.value): condition.value for condition in conditions}
        assert ("polNoInfo.paytodate", "RANGE") in values
        assert values[("polNoInfo.paytodate", "RANGE")].min
        assert values[("polNoInfo.paytodate", "RANGE")].max


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
