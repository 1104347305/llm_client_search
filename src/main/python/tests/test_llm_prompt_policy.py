from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_llm_prompt_requires_empty_conditions_when_any_clause_is_unsupported():
    files = [
        PROJECT_ROOT / "config" / "dev_client_search_args.yaml",
        PROJECT_ROOT / "config" / "stg_client_search_args.yaml",
        PROJECT_ROOT / "config" / "prd_client_search_args.yaml",
    ]

    required_text = '若用户查询包含多个条件，只要其中任意一个条件无法映射到参考字段定义，则必须返回空条件：{"query_logic":"AND","conditions":[]}'

    for path in files:
        content = path.read_text(encoding="utf-8")
        assert required_text in content, f"missing policy in {path.name}"
