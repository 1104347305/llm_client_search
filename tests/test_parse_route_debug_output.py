from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_parse_route_returns_rewritten_query_and_matched_patterns():
    content = (PROJECT_ROOT / "routes.py").read_text(encoding="utf-8")

    assert '"rewritten_query": parsed.rewritten_query' in content
    assert '"matched_patterns": _build_debug_patterns(parsed)' in content


def test_parse_route_hides_prompt_and_merges_l4_prompt_into_patterns():
    content = (PROJECT_ROOT / "routes.py").read_text(encoding="utf-8")

    assert '"prompt": None' in content
    assert '"rule_name": "L4_PROMPT"' in content
    assert '"match_type": "llm_prompt"' in content
