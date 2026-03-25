import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from core.level2_enhanced_matcher import Level2EnhancedMatcher


def test_level2_defaults_to_settings_enhanced_rules_path():
    matcher = Level2EnhancedMatcher()
    assert str(matcher.config_path).endswith(settings.ENHANCED_RULES_PATH)
