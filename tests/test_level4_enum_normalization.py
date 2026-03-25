from core.field_registry import FieldRegistry
from core.level4_llm_parser import Level4LLMParser


def test_field_registry_normalizes_enum_alias():
    registry = FieldRegistry.__new__(FieldRegistry)
    registry._enum_values_by_field = {
        "kangyangClientGrade": ["康养预达标会员", "逸享会员"]
    }
    registry._value_mappings = {
        "kangyangClientGrade": {
            "预达标会员": "康养预达标会员",
            "预达标": "康养预达标会员",
        }
    }

    assert registry.normalize_field_value("kangyangClientGrade", "预达标会员") == "康养预达标会员"
    assert registry.normalize_field_value("kangyangClientGrade", "康养预达标会员") == "康养预达标会员"


def test_level4_convert_conditions_normalizes_enum_alias():
    parser = Level4LLMParser.__new__(Level4LLMParser)

    registry = FieldRegistry.__new__(FieldRegistry)
    registry._enum_values_by_field = {
        "kangyangClientGrade": ["康养预达标会员", "逸享会员"]
    }
    registry._value_mappings = {
        "kangyangClientGrade": {
            "预达标会员": "康养预达标会员",
        }
    }
    parser.field_registry = registry

    conditions = parser._convert_conditions([
        {
            "field": "kangyangClientGrade",
            "operator": "MATCH",
            "value": "预达标会员",
        }
    ])

    assert len(conditions) == 1
    assert conditions[0].field == "kangyangClientGrade"
    assert conditions[0].value == "康养预达标会员"
