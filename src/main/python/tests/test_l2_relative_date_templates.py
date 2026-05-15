import asyncio

from src.main.python.steps.level2_enhanced_matcher import Level2EnhancedMatcher


def test_l2_matches_relative_date_templates_for_policy_dates():
    matcher = Level2EnhancedMatcher()
    cases = [
        ("下周保单周年日的客户", "effAnniversaryDate"),
        ("今天保单周年日的客户", "effAnniversaryDate"),
        ("明天保单周年日的客户", "effAnniversaryDate"),
        ("后天保单周年日的客户", "effAnniversaryDate"),
        ("下下周证件到期的客户", "idValidDate"),
        ("下周缴费期满的客户", "effAppEndDate"),
        ("明天缴费期满的客户", "effAppEndDate"),
        ("下下周保单到期的客户", "validSinsMatuDateTime"),
        ("本周承保的客户", "latelyUndwrtSegTime"),
        ("上周理赔的客户", "polNoInfo.claimdatainfo.claimdate"),
        ("下周保单生效的客户", "polNoInfo.poleffdate"),
        ("后天保单生效的客户", "polNoInfo.poleffdate"),
        ("本周新增的客户", "dateCreated"),
    ]

    for query, expected_field in cases:
        conditions = asyncio.run(matcher.match(query))
        assert any(
            condition.field == expected_field
            and condition.operator.value == "RANGE"
            and condition.value.min
            and condition.value.max
            for condition in conditions
        ), query
