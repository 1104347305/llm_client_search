import asyncio
import calendar
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.field_registry import FieldRegistry
from core.level2_enhanced_matcher import Level2EnhancedMatcher
from core.level4_llm_parser import Level4LLMParser
from core.time_range_resolver import resolve_dynamic_date_range, resolve_dynamic_date_placeholder


def test_level2_matches_birthday_recent_window():
    matcher = Level2EnhancedMatcher("config/enhanced_rules.yaml")

    conditions = asyncio.run(matcher.match("生日快到了的客户"))

    assert len(conditions) == 1
    condition = conditions[0]
    assert condition.field == "birthdayMd"
    assert condition.operator.value == "RANGE"
    assert condition.value.min == (date.today() + timedelta(days=1)).strftime("%m-%d")
    assert condition.value.max == (date.today() + timedelta(days=30)).strftime("%m-%d")


def test_level2_matches_policy_recent_expiry():
    matcher = Level2EnhancedMatcher("config/enhanced_rules.yaml")

    conditions = asyncio.run(matcher.match("保单即将到期的客户"))

    assert len(conditions) == 1
    condition = conditions[0]
    assert condition.field == "validSinsMatuDate"
    assert condition.operator.value == "LTE"
    assert condition.value == (date.today() + timedelta(days=30)).strftime("%Y-%m-%d 00:00:00")


def test_level4_resolves_current_period_placeholders_in_range():
    parser = Level4LLMParser.__new__(Level4LLMParser)
    parser.field_registry = FieldRegistry.__new__(FieldRegistry)
    parser.field_registry._enum_values_by_field = {}
    parser.field_registry._value_mappings = {}

    now = datetime.now()
    month_last_day = calendar.monthrange(now.year, now.month)[1]

    conditions = parser._convert_conditions([
        {
            "field": "effAppEndDate",
            "operator": "RANGE",
            "value": {
                "min": "<current_month_start>",
                "max": "<current_month_end>",
            },
        },
        {
            "field": "effAppEndDate",
            "operator": "RANGE",
            "value": {
                "min": "<current_year_start>",
                "max": "<current_year_end>",
            },
        },
    ])

    assert len(conditions) == 2
    assert conditions[0].value.min == now.replace(day=1).strftime("%Y-%m-%d 00:00:00")
    assert conditions[0].value.max == now.replace(day=month_last_day).strftime("%Y-%m-%d 00:00:00")
    assert conditions[1].value.min == now.replace(month=1, day=1).strftime("%Y-%m-%d 00:00:00")
    assert conditions[1].value.max == now.replace(month=12, day=31).strftime("%Y-%m-%d 00:00:00")


def test_level4_resolves_today_and_next_month_placeholders():
    parser = Level4LLMParser.__new__(Level4LLMParser)
    parser.field_registry = FieldRegistry.__new__(FieldRegistry)
    parser.field_registry._enum_values_by_field = {}
    parser.field_registry._value_mappings = {}

    now = datetime.now()
    next_month_year = now.year + 1 if now.month == 12 else now.year
    next_month = 1 if now.month == 12 else now.month + 1
    next_month_last_day = calendar.monthrange(next_month_year, next_month)[1]

    conditions = parser._convert_conditions([
        {
            "field": "effAppEndDate",
            "operator": "RANGE",
            "value": {
                "min": "<today>",
                "max": "<today+30days>",
            },
        },
        {
            "field": "birthdayMd",
            "operator": "RANGE",
            "value": {
                "min": "下个月-01",
                "max": "下个月-31",
            },
        },
    ])

    assert len(conditions) == 2
    assert conditions[0].value.min == now.strftime("%Y-%m-%d 00:00:00")
    assert conditions[0].value.max == (now + timedelta(days=30)).strftime("%Y-%m-%d 00:00:00")
    assert conditions[1].value.min == f"{next_month:02d}-01"
    assert conditions[1].value.max == f"{next_month:02d}-{next_month_last_day:02d}"


def test_unified_relative_time_ranges_are_stable():
    base_now = datetime(2026, 3, 25, 10, 30, 0)

    next_week_range = resolve_dynamic_date_range(
        {"date_range": "next_week", "format": "yyyy-MM-dd HH:mm:ss"},
        now=base_now,
    )
    assert next_week_range.min == "2026-03-30 00:00:00"
    assert next_week_range.max == "2026-04-05 00:00:00"

    next_month_range = resolve_dynamic_date_range(
        {"date_range": "next_month", "format": "yyyy-MM-dd HH:mm:ss"},
        now=base_now,
    )
    assert next_month_range.min == "2026-04-01 00:00:00"
    assert next_month_range.max == "2026-04-30 00:00:00"

    next_week_window = resolve_dynamic_date_range(
        {"date_range": "next_n_days", "days": 7, "format": "yyyy-MM-dd HH:mm:ss"},
        now=base_now,
    )
    assert next_week_window.min == "2026-03-26 00:00:00"
    assert next_week_window.max == "2026-04-01 00:00:00"

    next_month_window = resolve_dynamic_date_range(
        {"date_range": "next_n_days", "days": 30, "format": "yyyy-MM-dd HH:mm:ss"},
        now=base_now,
    )
    assert next_month_window.min == "2026-03-26 00:00:00"
    assert next_month_window.max == "2026-04-24 00:00:00"


def test_level4_resolves_new_relative_placeholders():
    parser = Level4LLMParser.__new__(Level4LLMParser)
    parser.field_registry = FieldRegistry.__new__(FieldRegistry)
    parser.field_registry._enum_values_by_field = {}
    parser.field_registry._value_mappings = {}

    base_now = datetime(2026, 3, 25, 10, 30, 0)

    assert resolve_dynamic_date_placeholder("<next_week_start>", now=base_now) == "2026-03-30 00:00:00"
    assert resolve_dynamic_date_placeholder("<next_week_end>", now=base_now) == "2026-04-05 00:00:00"
    assert resolve_dynamic_date_placeholder("<next_month_start>", now=base_now) == "2026-04-01 00:00:00"
    assert resolve_dynamic_date_placeholder("<next_month_end>", now=base_now) == "2026-04-30 00:00:00"
    assert resolve_dynamic_date_placeholder("<next_7_days_start>", now=base_now) == "2026-03-26 00:00:00"
    assert resolve_dynamic_date_placeholder("<next_7_days_end>", now=base_now) == "2026-04-01 00:00:00"
    assert resolve_dynamic_date_placeholder("<next_30_days_start>", now=base_now) == "2026-03-26 00:00:00"
    assert resolve_dynamic_date_placeholder("<next_30_days_end>", now=base_now) == "2026-04-24 00:00:00"
