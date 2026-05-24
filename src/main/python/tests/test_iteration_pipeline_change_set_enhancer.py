from pathlib import Path

import yaml

from src.main.python.tools.iteration_pipeline.change_set import load_change_set
from src.main.python.tools.iteration_pipeline.change_set_enhancer import (
    parse_enhancement_response,
    render_enhancement_prompt,
    write_enhanced_change_set,
)


def _write_change_set(path: Path) -> None:
    path.write_text(
        """
id: enhance_test
title: 增强测试
fields:
  - id: client_temperature_match
    field: clientTemperature
    operator: MATCH
    value_type: enum
    enum_ref: clientTemperature
    retrieval_text: 客户温度 高温客户
    examples:
      - query: 高温客户
        output: {field: clientTemperature, operator: MATCH, value: 高温}
enums:
  clientTemperature:
    values: [低温, 中温, 高温]
l2_rules: []
test_cases: []
""",
        encoding="utf-8",
    )


def test_render_enhancement_prompt_contains_constraints(tmp_path: Path):
    change_set_path = tmp_path / "change_set.yaml"
    _write_change_set(change_set_path)

    prompt = render_enhancement_prompt(load_change_set(change_set_path))

    assert "只输出 JSON 对象" in prompt
    assert "clientTemperature" in prompt
    assert "不要编造不存在字段" in prompt
    assert "clientSex" in prompt
    assert "field_definitions_args.yaml" in prompt
    assert "enhanced_rules_args.yaml" in prompt


def test_parse_enhancement_response_extracts_json_from_markdown():
    response = """
```json
{"field_enhancements":[],"l2_rules":[],"test_cases":[]}
```
"""

    assert parse_enhancement_response(response) == {
        "field_enhancements": [],
        "l2_rules": [],
        "test_cases": [],
    }


def test_write_enhanced_change_set_accepts_config_shaped_candidates(tmp_path: Path):
    change_set_path = tmp_path / "change_set.yaml"
    output = tmp_path / "enhanced.yaml"
    _write_change_set(change_set_path)

    write_enhanced_change_set(
        load_change_set(change_set_path),
        {
            "field_definitions_args.yaml": {
                "intents": [
                    {
                        "id": "client_temperature_contains_codex",
                        "field": "clientTemperature",
                        "operator": "CONTAINS",
                        "value_type": "enum",
                        "enum_ref": "clientTemperature",
                        "retrieval_text": "客户温度包含 高温 中温",
                    }
                ]
            },
            "field_enums_args.yaml": {
                "clientTemperature": {"values": ["低温", "中温", "高温"], "ordered": True}
            },
            "value_mappings_args.yaml": {
                "clientTemperature": {"热客户": "高温"}
            },
            "enhanced_rules_args.yaml": {
                "rules": [
                    {
                        "name": "客户温度-配置格式候选",
                        "field": "clientTemperature",
                        "operator": "MATCH",
                        "value_type": "capture",
                    }
                ]
            },
            "test_cases": [{"id": "codex_config_001", "query": "热客户"}],
        },
        output=output,
        promote=True,
    )

    raw = yaml.safe_load(output.read_text(encoding="utf-8"))

    assert raw["fields"][-1]["id"] == "client_temperature_contains_codex"
    assert raw["enums"]["clientTemperature"]["values"] == ["低温", "中温", "高温"]
    assert raw["value_mappings"]["clientTemperature"]["热客户"] == "高温"
    assert raw["l2_rules"][-1]["name"] == "客户温度-配置格式候选"


def test_write_enhanced_change_set_candidate_only(tmp_path: Path):
    change_set_path = tmp_path / "change_set.yaml"
    output = tmp_path / "enhanced.yaml"
    _write_change_set(change_set_path)

    write_enhanced_change_set(
        load_change_set(change_set_path),
        {
            "field_enhancements": [
                {
                    "field": "clientTemperature",
                    "examples": [
                        {
                            "query": "帮我看看高温客户",
                            "output": {"field": "clientTemperature", "operator": "MATCH", "value": "高温"},
                        }
                    ],
                }
            ],
            "l2_rules": [{"name": "客户温度-候选", "field": "clientTemperature", "operator": "MATCH"}],
            "test_cases": [{"id": "codex_001", "query": "帮我看看高温客户"}],
        },
        output=output,
        promote=False,
    )

    raw = yaml.safe_load(output.read_text(encoding="utf-8"))

    assert raw["codex_enhancement"]["field_enhancements"][0]["field"] == "clientTemperature"
    assert raw["fields"][0]["examples"] == [
        {
            "query": "高温客户",
            "output": {"field": "clientTemperature", "operator": "MATCH", "value": "高温"},
        }
    ]
    assert raw["l2_rules"] == []
    assert raw["test_cases"] == []


def test_write_enhanced_change_set_promotes_candidates(tmp_path: Path):
    change_set_path = tmp_path / "change_set.yaml"
    output = tmp_path / "enhanced.yaml"
    _write_change_set(change_set_path)

    write_enhanced_change_set(
        load_change_set(change_set_path),
        {
            "field_enhancements": [
                {
                    "field": "clientTemperature",
                    "examples": [
                        {
                            "query": "帮我看看高温客户",
                            "output": {"field": "clientTemperature", "operator": "MATCH", "value": "高温"},
                        }
                    ],
                    "negative_examples": [{"query": "今天温度高", "reason": "天气温度"}],
                }
            ],
            "l2_rules": [{"name": "客户温度-候选", "field": "clientTemperature", "operator": "MATCH"}],
            "test_cases": [{"id": "codex_001", "query": "帮我看看高温客户"}],
        },
        output=output,
        promote=True,
    )

    raw = yaml.safe_load(output.read_text(encoding="utf-8"))

    assert raw["fields"][0]["examples"][-1]["query"] == "帮我看看高温客户"
    assert raw["fields"][0]["negative_examples"][-1]["query"] == "今天温度高"
    assert raw["l2_rules"][-1]["name"] == "客户温度-候选"
    assert raw["test_cases"][-1]["id"] == "codex_001"
