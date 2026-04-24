import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.field_registry import FieldRegistry


def test_field_registry_normalizes_query_by_value_mappings():
    registry = FieldRegistry.__new__(FieldRegistry)
    registry._value_mappings = {
        "vipType": {
            "黄金VIP": "原黄金VIP",
        },
        "pCategorys": {
            "意外险": "意外伤害保险",
        },
        "familyRelation": {
            "孩子": "子女",
        },
    }
    registry._build_query_normalizer()

    query = "黄金VIP意外险客户，家里有孩子"
    normalized = registry.normalize_query(query)

    assert normalized == "原黄金VIP意外伤害保险客户，家里有子女"
