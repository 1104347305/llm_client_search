import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.main.python.steps.level2_enhanced_matcher import Level2EnhancedMatcher
from src.main.python.models.schemas import Operator


matcher = Level2EnhancedMatcher()


def _match(query: str):
    return asyncio.run(matcher.match(query))


def test_education_above_excludes_boundary():
    conditions = _match("本科学历以上的客户")
    assert len(conditions) == 1
    condition = conditions[0]
    assert condition.field == "education"
    assert condition.operator == Operator.CONTAINS
    assert condition.value == ["硕士研究生", "博士研究生", "博士后"]


def test_education_and_above_includes_boundary():
    conditions = _match("本科及以上学历的客户")
    assert len(conditions) == 1
    condition = conditions[0]
    assert condition.field == "education"
    assert condition.operator == Operator.CONTAINS
    assert condition.value == ["大学本科生", "硕士研究生", "博士研究生", "博士后"]


def test_education_exact_college_matches_level2():
    conditions = _match("学历为大学专科的客户")
    assert len(conditions) == 1
    condition = conditions[0]
    assert condition.field == "education"
    assert condition.operator == Operator.MATCH
    assert condition.value == "大学专科"


def test_education_exact_college_without_education_word_is_not_range():
    conditions = _match("查询大学专科客户")
    assert len(conditions) == 1
    condition = conditions[0]
    assert condition.field == "education"
    assert condition.operator == Operator.MATCH
    assert condition.value == "大学专科"


def test_education_college_aliases_are_exact_matches():
    for query in ["查询大专客户", "专科客户"]:
        conditions = _match(query)
        assert len(conditions) == 1
        condition = conditions[0]
        assert condition.field == "education"
        assert condition.operator == Operator.MATCH
        assert condition.value == "大学专科"
