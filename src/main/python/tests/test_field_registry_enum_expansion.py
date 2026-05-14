import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from core.field_registry import FieldRegistry


def test_enum_ref_expansion_skips_value_mappings_yaml():
    registry = FieldRegistry.__new__(FieldRegistry)
    registry.yaml_path = settings.FIELD_DEFINITIONS_PATH

    intents = registry._load_yaml()
    by_id = {intent["id"]: intent for intent in intents}

    assert "意外伤害保险" in by_id["held_product_category"]["enum"]
    assert "e生保" in by_id["h_product_code"]["enum"]
    assert "平安e生保医疗保险" in by_id["policies_plan_fullname"]["enum"]
    assert "e生保" in by_id["policies_plan_abbr_name"]["enum"]
    assert "定期寿险" in by_id["policies_plan_type"]["enum"]
    assert "平安e生保医疗保险" in by_id["policies_claim_coverage"]["enum"]


def test_settings_exposes_configurable_path_locations():
    assert settings.ENHANCED_RULES_PATH.endswith("config/enhanced_rules_args.yaml")
    assert settings.ENUMS_DIR_PATH.endswith("config")
    assert settings.VALUE_MAPPINGS_PATH.endswith("config/value_mappings_args.yaml")
