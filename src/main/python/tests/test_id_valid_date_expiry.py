import asyncio
from datetime import date, timedelta

from src.main.python.steps.field_registry import FieldRegistry
from src.main.python.steps.level2_enhanced_matcher import Level2EnhancedMatcher
from src.main.python.steps.level4_llm_parser import Level4LLMParser


def test_level2_matches_id_valid_date_recent_expiry():
    matcher = Level2EnhancedMatcher()

    conditions = asyncio.run(matcher.match("身份证有效期快到期的客户"))

    assert len(conditions) == 1
    condition = conditions[0]
    assert condition.field == "idValidDate"
    assert condition.operator.value == "RANGE"
    assert condition.value.min == (date.today() + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
    assert condition.value.max == (date.today() + timedelta(days=30)).strftime("%Y-%m-%d 00:00:00")


def test_level4_resolves_today_plus_30days_placeholder():
    parser = Level4LLMParser.__new__(Level4LLMParser)
    parser.field_registry = FieldRegistry.__new__(FieldRegistry)
    parser.field_registry._enum_values_by_field = {}
    parser.field_registry._value_mappings = {}

    conditions = parser._convert_conditions([
        {
            "field": "idValidDate",
            "operator": "LTE",
            "value": "<today+30days>",
        }
    ])

    assert len(conditions) == 1
    assert conditions[0].value == (date.today() + timedelta(days=30)).strftime("%Y-%m-%d 00:00:00")
