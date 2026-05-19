import sys
from pathlib import Path
import textwrap

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.main.python.steps.intent_summary import IntentSummaryService
from src.main.python.models.schemas import Condition, Operator, QueryLogic, RangeValue


def test_build_intent_summary_groups_same_value_different_fields_with_or():
    service = IntentSummaryService().load()
    service.unsupported_fields = frozenset()

    conditions = [
        Condition(field="planAbbrNames", operator=Operator.CONTAINS, value="e生保"),
        Condition(field="policies_product_name", operator=Operator.MATCH, value="e生保"),
    ]

    summary = service.build_intent_summary(conditions, QueryLogic.AND)

    assert "寿险产品包含e生保" in summary
    assert "保单产品名称匹配e生保" in summary
    assert "\n或者" in summary
    assert "\n并且" not in summary


def test_build_intent_summary_uses_bare_value_weak_intent_copy():
    service = IntentSummaryService().load()
    service.unsupported_fields = frozenset()

    conditions = [
        Condition(field="clientNo", operator=Operator.MATCH, value="123456"),
        Condition(field="polNo", operator=Operator.MATCH, value="123456"),
        Condition(field="clientMobile", operator=Operator.MATCH, value="123456"),
        Condition(field="idNo", operator=Operator.MATCH, value="123456"),
    ]

    summary = service.build_intent_summary(conditions, QueryLogic.OR)

    assert summary == "暂时没判读出这组数据代表什么，已帮您在手机号、客户号、保单号、证件号中一起查找匹配的客户"


def test_build_intent_summary_keeps_outer_and_for_other_conditions():
    service = IntentSummaryService().load()
    service.unsupported_fields = frozenset()

    conditions = [
        Condition(field="planAbbrNames", operator=Operator.CONTAINS, value="e生保"),
        Condition(field="policies_product_name", operator=Operator.MATCH, value="e生保"),
        Condition(field="clientTemperature", operator=Operator.CONTAINS, value=["高温"]),
    ]

    summary = service.build_intent_summary(conditions, QueryLogic.AND)

    assert summary.count("\n或者") == 1
    assert "\n并且" in summary
    assert summary.endswith("的客户")


def test_build_intent_summary_formats_full_month_range_as_year_month():
    service = IntentSummaryService().load()
    service.unsupported_fields = frozenset()

    conditions = [
        Condition(
            field="effAnniversaryDate",
            operator=Operator.RANGE,
            value=RangeValue(min="2026-10-01 00:00:00", max="2026-10-31 23:59:59"),
        )
    ]

    summary = service.build_intent_summary(conditions, QueryLogic.AND)

    assert "2026年10月" in summary
    assert "2026-10-01 00:00:00 至 2026-10-31 23:59:59" not in summary


def test_build_intent_summary_formats_exact_age_with_equals_sign():
    service = IntentSummaryService().load()
    service.unsupported_fields = frozenset()

    conditions = [
        Condition(
            field="clientAge",
            operator=Operator.RANGE,
            value=RangeValue(min=30, max=30),
        )
    ]

    summary = service.build_intent_summary(conditions, QueryLogic.AND)

    assert "客户年龄=30" in summary
    assert "客户年龄等于30" not in summary


def test_build_intent_summary_merges_gte_and_lte_into_range_before_rendering():
    service = IntentSummaryService().load()
    service.unsupported_fields = frozenset()

    conditions = [
        Condition(field="clientAge", operator=Operator.GTE, value=30),
        Condition(field="clientAge", operator=Operator.LTE, value=60),
    ]

    summary = service.build_intent_summary(conditions, QueryLogic.AND)

    assert "客户年龄在30~60之间" in summary
    assert "客户年龄≥30" not in summary
    assert "客户年龄≤60" not in summary


def test_build_intent_summary_strips_time_from_datetime_values_only_in_summary():
    service = IntentSummaryService().load()
    service.unsupported_fields = frozenset()

    condition = Condition(
        field="clientBirthday",
        operator=Operator.LTE,
        value="2023-09-17 00:00:00",
    )

    summary = service.build_intent_summary([condition], QueryLogic.AND)

    assert "客户出生日期≤2023-09-17" in summary
    assert "00:00:00" not in summary
    assert condition.value == "2023-09-17 00:00:00"


def test_build_intent_summary_unsupported_only_uses_cannot_query_copy():
    service = IntentSummaryService().load()
    service.unsupported_fields = frozenset({"policies_status", "policies_survival_unclaimed_amount"})

    conditions = [
        Condition(field="policies_status", operator=Operator.MATCH, value="有效"),
        Condition(field="policies_survival_unclaimed_amount", operator=Operator.EXISTS),
    ]

    summary = service.build_intent_summary(conditions, QueryLogic.AND)

    assert summary == "提示：保单状态、生存金未领取金额暂不支持搜索，无法进行查询"


def test_build_intent_summary_supported_and_unsupported_keeps_original_suffix():
    service = IntentSummaryService().load()
    service.unsupported_fields = frozenset({"policies_status"})

    conditions = [
        Condition(field="clientTemperature", operator=Operator.CONTAINS, value=["高温"]),
        Condition(field="policies_status", operator=Operator.MATCH, value="有效"),
    ]

    summary = service.build_intent_summary(conditions, QueryLogic.AND)

    assert "高温的客户" in summary
    assert "提示：保单状态暂不支持搜索，系统将按可支持字段搜索" in summary


def test_build_intent_summary_puts_family_relation_before_family_details():
    service = IntentSummaryService().load()
    service.unsupported_fields = frozenset()

    conditions = [
        Condition(field="familyClientAge", operator=Operator.GTE, value=10),
        Condition(field="familyRelation", operator=Operator.CONTAINS, value=["子女"]),
    ]

    summary = service.build_intent_summary(conditions, QueryLogic.AND)

    assert summary.index("有子女") < summary.index("子女年龄")


def test_build_intent_summary_formats_exact_family_age_range():
    service = IntentSummaryService().load()
    service.unsupported_fields = frozenset()

    conditions = [
        Condition(field="familyInfo.familyrelation", operator=Operator.MATCH, value="父母"),
        Condition(
            field="familyInfo.familyclientage",
            operator=Operator.RANGE,
            value=RangeValue(min=70, max=70),
        ),
    ]

    summary = service.build_intent_summary(conditions, QueryLogic.AND)

    assert "有父母" in summary
    assert "父母年龄=70岁" in summary


def test_build_intent_summary_only_reorders_family_conditions():
    service = IntentSummaryService().load()
    service.unsupported_fields = frozenset()

    conditions = [
        Condition(field="clientTemperature", operator=Operator.CONTAINS, value=["高温"]),
        Condition(field="familyClientAge", operator=Operator.GTE, value=10),
        Condition(field="familyRelation", operator=Operator.CONTAINS, value=["子女"]),
        Condition(field="clientAge", operator=Operator.RANGE, value=RangeValue(min=30, max=30)),
    ]

    summary = service.build_intent_summary(conditions, QueryLogic.AND)

    assert summary.index("高温") < summary.index("有子女")
    assert summary.index("有子女") < summary.index("子女年龄")
    assert summary.index("子女年龄") < summary.index("客户年龄=30")


def test_intent_summary_loads_unsupported_fields_from_field_definitions(tmp_path):
    field_definitions_path = tmp_path / "field_definitions.yaml"
    field_definitions_path.write_text(
        textwrap.dedent(
            """
            intents:
              - id: unsupported_intent
                field: searchKangyangClientGrade
                operator: MATCH
                value_type: static
                is_supported: false
                examples: []
            """
        ).strip() + "\n",
        encoding="utf-8",
    )

    enhanced_rules_path = tmp_path / "enhanced_rules.yaml"
    enhanced_rules_path.write_text(
        textwrap.dedent(
            """
            rules:
              - name: "不支持规则"
                is_supported: false
                field: "searchKangyangClientGrade"
                operator: "MATCH"
                value_type: "static"
                value: "颐享家会员"
            composite_rules: []
            """
        ).strip(),
        encoding="utf-8",
    )

    service = IntentSummaryService()
    service.field_definitions_path = field_definitions_path
    service.load()

    assert service.unsupported_fields == frozenset({"searchKangyangClientGrade"})
