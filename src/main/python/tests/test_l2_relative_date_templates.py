import asyncio
import calendar
from datetime import date, timedelta

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


def test_l2_matches_id_card_next_week_expiry_with_document_type():
    matcher = Level2EnhancedMatcher()

    conditions = asyncio.run(matcher.match("身份证下周即将过期的客户"))
    by_field = {condition.field: condition for condition in conditions}

    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    next_monday = this_monday + timedelta(days=7)
    next_sunday = next_monday + timedelta(days=6)

    assert by_field["idType"].operator.value == "MATCH"
    assert by_field["idType"].value == "身份证"
    assert by_field["idValidDate"].operator.value == "RANGE"
    assert by_field["idValidDate"].value.min == next_monday.strftime("%Y-%m-%d 00:00:00")
    assert by_field["idValidDate"].value.max == next_sunday.strftime("%Y-%m-%d 00:00:00")


def test_l2_matches_policy_expiry_at_next_month_end():
    matcher = Level2EnhancedMatcher()

    conditions = asyncio.run(matcher.match("下个月底保单到期的客户"))

    assert len(conditions) == 1
    condition = conditions[0]
    today = date.today()
    year = today.year + 1 if today.month == 12 else today.year
    month = 1 if today.month == 12 else today.month + 1
    last_day = calendar.monthrange(year, month)[1]

    assert condition.field == "validSinsMatuDateTime"
    assert condition.operator.value == "RANGE"
    assert condition.value.min == f"{year:04d}-{month:02d}-20"
    assert condition.value.max == f"{year:04d}-{month:02d}-{last_day:02d}"
