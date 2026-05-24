from pathlib import Path

import yaml

from src.main.python.tools.iteration_pipeline.change_set import load_change_set
from src.main.python.tools.iteration_pipeline.change_set_generator import build_change_set_from_spec_file
from src.main.python.tools.iteration_pipeline.config_fragments import (
    build_config_fragments,
    write_config_fragments,
    write_config_fragments_from_raw,
)


def _write_change_set(path: Path) -> None:
    path.write_text(
        """
id: fragment_test
title: 配置片段测试
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
    ordered: true
    aliases:
      热客户: 高温
value_mappings:
  clientTemperature:
    暖客户: 中温
l2_rules:
  - name: 客户温度匹配
    field: clientTemperature
    operator: MATCH
    value_type: capture
    enum_ref: clientTemperature
    patterns_template:
      - "{enum}客户"
test_cases: []
""",
        encoding="utf-8",
    )


def test_build_config_fragments_uses_runtime_config_shapes(tmp_path: Path):
    change_set_path = tmp_path / "change_set.yaml"
    _write_change_set(change_set_path)

    fragments = build_config_fragments(load_change_set(change_set_path))

    assert fragments["field_definitions_args.yaml"]["intents"][0]["id"] == "client_temperature_match"
    assert fragments["field_enums_args.yaml"]["clientTemperature"] == {
        "values": ["低温", "中温", "高温"],
        "ordered": True,
    }
    assert fragments["value_mappings_args.yaml"]["clientTemperature"] == {
        "热客户": "高温",
        "暖客户": "中温",
    }
    assert fragments["enhanced_rules_args.yaml"]["rules"][0]["name"] == "客户温度匹配"


def test_write_config_fragments_split_files(tmp_path: Path):
    change_set_path = tmp_path / "change_set.yaml"
    output_dir = tmp_path / "fragments"
    _write_change_set(change_set_path)

    written = write_config_fragments(load_change_set(change_set_path), output_dir, split_files=True)

    definitions = yaml.safe_load((output_dir / "field_definitions_args.yaml").read_text(encoding="utf-8"))
    rules = yaml.safe_load((output_dir / "enhanced_rules_args.yaml").read_text(encoding="utf-8"))

    assert set(written) == {
        "field_definitions_args.yaml",
        "field_enums_args.yaml",
        "value_mappings_args.yaml",
        "enhanced_rules_args.yaml",
    }
    assert definitions["intents"][0]["field"] == "clientTemperature"
    assert rules["rules"][0]["field"] == "clientTemperature"


def test_generate_config_fragments_directly_from_field_spec(tmp_path: Path):
    spec_path = tmp_path / "fields.yaml"
    output_dir = tmp_path / "config_fragments"
    spec_path.write_text(
        """
id: direct_config_test
title: 直接配置片段生成
fields:
  - field: clientTemperature
    name: 客户温度
    type: enum
    enum_values: [低温, 中温, 高温]
    ordered: true
""",
        encoding="utf-8",
    )

    generated = build_change_set_from_spec_file(spec_path=spec_path, output=None)
    written = write_config_fragments_from_raw(generated, output_dir)

    definitions = yaml.safe_load((output_dir / "field_definitions_args.yaml").read_text(encoding="utf-8"))
    enums = yaml.safe_load((output_dir / "field_enums_args.yaml").read_text(encoding="utf-8"))
    rules = yaml.safe_load((output_dir / "enhanced_rules_args.yaml").read_text(encoding="utf-8"))

    assert "change_set.yaml" not in {path.name for path in written.values()}
    assert definitions["intents"][0]["field"] == "clientTemperature"
    assert definitions["intents"][0]["enum_ref"] == "clientTemperature"
    assert enums["clientTemperature"]["values"] == ["低温", "中温", "高温"]
    assert rules["rules"][0]["field"] == "clientTemperature"
