"""
parse 路由调试输出测试（已迁移至 AskBob 协议）
原有字段检查已迁移至 test_parse_route.py
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_parse_route_uses_build_debug_patterns():
    """路由层仍使用 _build_debug_patterns 组装调试信息"""
    content = (PROJECT_ROOT / "routes.py").read_text(encoding="utf-8")
    assert "_build_debug_patterns(parsed)" in content


def test_parse_route_l4_prompt_merged_into_patterns():
    """L4 prompt 通过 matched_patterns 中 llm_prompt 条目透出，不作为顶层字段"""
    content = (PROJECT_ROOT / "routes.py").read_text(encoding="utf-8")
    assert '"rule_name": "L4_PROMPT"' in content
    assert '"match_type": "llm_prompt"' in content
