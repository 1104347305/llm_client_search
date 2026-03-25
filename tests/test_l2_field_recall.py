import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.level2_enhanced_matcher import Level2EnhancedMatcher


def test_l2_partial_field_recall_hits_pc_category_for_accident_gap_query():
    matcher = Level2EnhancedMatcher("config/enhanced_rules.yaml")

    fields = matcher.recall_fields("买了车险，但没有购买意外险的客户", top_k=20)
    recalled_fields = {item["field"] for item in fields}

    assert "pcCategory" in recalled_fields
