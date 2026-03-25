import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.level2_enhanced_matcher import Level2EnhancedMatcher
from core.level4_llm_parser import Level4LLMParser
from core.field_registry import FieldRegistry


def test_level2_matches_id_valid_date_recent_expiry():
    matcher = Level2EnhancedMatcher("config/enhanced_rules.yaml")

    conditions = asyncio.run(matcher.match("身份证有效期快到期的客户"))

    assert len(conditions) == 1
    condition = conditions[0]
    assert condition.field == "idValidDate"
    assert condition.operator.value == "LTE"
    assert condition.value == (date.today() + timedelta(days=30)).strftime("%Y-%m-%d 00:00:00")


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
