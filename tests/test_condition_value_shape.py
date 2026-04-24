import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models.schemas import Condition, Operator


def test_contains_value_is_coerced_to_list():
    condition = Condition(field="familyRelation", operator=Operator.CONTAINS, value="父母")
    assert condition.value == ["父母"]


def test_match_value_list_is_coerced_to_scalar():
    condition = Condition(field="vipType", operator=Operator.MATCH, value=["黄金V1", "铂金V1"])
    assert condition.value == "黄金V1"
