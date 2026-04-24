import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.level2_enhanced_matcher import Level2EnhancedMatcher
from models.schemas import Condition, Operator


def test_l2_partial_field_recall_hits_pc_category_for_accident_gap_query():
    matcher = Level2EnhancedMatcher("config/enhanced_rules.yaml")

    fields = matcher.recall_fields("买了车险，但没有购买意外险的客户", top_k=20)
    recalled_fields = {item["field"] for item in fields}

    assert "pCategorys" in recalled_fields


def test_l2_recall_candidates_keeps_field_and_operator_for_age_gte():
    matcher = Level2EnhancedMatcher("config/enhanced_rules.yaml")

    candidates = matcher.recall_candidates("年龄大于30岁的客户", top_k=20)
    pairs = {(item["field"], item["operator"]) for item in candidates}

    assert ("clientAge", "GTE") in pairs
    assert ("clientAge", "LTE") not in pairs


def test_l2_recall_fields_respects_require_paired_field():
    matcher = Level2EnhancedMatcher("config/enhanced_rules.yaml")

    fields = matcher.recall_fields("家庭成员姓名张三的客户", top_k=20)
    recalled_fields = {item["field"] for item in fields}

    assert "familyClientName" not in recalled_fields


def test_l2_recall_candidates_respects_require_paired_field():
    matcher = Level2EnhancedMatcher("config/enhanced_rules.yaml")

    candidates = matcher.recall_candidates("家庭成员姓名张三的客户", top_k=20)
    pairs = {(item["field"], item["operator"]) for item in candidates}

    assert ("familyClientName", "NESTED_MATCH") not in pairs


def test_l2_candidate_conditions_same_value_keeps_highest_priority():
    items = [
        {
            "priority": 8,
            "condition": Condition(field="fieldA", operator=Operator.MATCH, value="张三"),
        },
        {
            "priority": 10,
            "condition": Condition(field="fieldB", operator=Operator.MATCH, value="张三"),
        },
        {
            "priority": 7,
            "condition": Condition(field="fieldC", operator=Operator.MATCH, value="李四"),
        },
    ]

    filtered = Level2EnhancedMatcher._filter_recalled_condition_items_by_value_priority(items)

    assert [item["priority"] for item in filtered] == [10, 7]
