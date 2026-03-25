import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.level2_enhanced_matcher import Level2EnhancedMatcher
from models.schemas import Operator


def test_a_customer_pattern_matches_a1_to_a4():
    matcher = Level2EnhancedMatcher("config/enhanced_rules.yaml")

    conditions = asyncio.run(matcher.match("A类客户"))

    assert len(conditions) == 1
    condition = conditions[0]
    assert condition.field == "newValueLabel"
    assert condition.operator == Operator.CONTAINS
    assert condition.value == ["A1", "A2", "A3", "A4"]


def test_a_customer_pattern_works_in_composite_rule():
    matcher = Level2EnhancedMatcher("config/enhanced_rules.yaml")

    conditions = asyncio.run(matcher.match("高温A类客户"))

    assert len(conditions) == 2
    values = {(cond.field, cond.operator.value): cond.value for cond in conditions}
    assert values[("clientTemperature", "MATCH")] == "高温"
    assert values[("newValueLabel", "CONTAINS")] == ["A1", "A2", "A3", "A4"]
