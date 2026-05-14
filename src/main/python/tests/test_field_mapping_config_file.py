import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from models import field_mapping


def test_settings_exposes_field_mapping_path():
    assert settings.FIELD_MAPPING_PATH.endswith("config/field_mapping.yaml")


def test_field_mapping_loads_from_yaml_config():
    assert "没购买" in field_mapping.NEGATION_WORDS


def test_field_mapping_exposes_runtime_field_helpers():
    assert field_mapping.get_query_field("customer_name") == "searchClientNameNew"
    assert "clientAge" in field_mapping.get_field_context_group("client")
    assert "familyClientMobile" in field_mapping.get_sensitive_field_group("mobile")
