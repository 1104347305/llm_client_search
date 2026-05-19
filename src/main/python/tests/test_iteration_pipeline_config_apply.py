from pathlib import Path

import yaml

from src.main.python.tools.iteration_pipeline.change_set import load_change_set
from src.main.python.tools.iteration_pipeline.config_apply import apply_change_set_to_config


def _write_config_files(config_dir: Path) -> None:
    config_dir.mkdir(parents=True)
    (config_dir / "field_definitions_args.yaml").write_text(
        yaml.safe_dump(
            {
                "intents": [
                    {
                        "id": "existing_temperature",
                        "field": "clientTemperature",
                        "operator": "MATCH",
                        "value_type": "enum",
                    }
                ]
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config_dir / "field_enums_args.yaml").write_text(
        yaml.safe_dump(
            {"clientTemperature": {"values": ["低温"], "ordered": True}},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config_dir / "value_mappings_args.yaml").write_text(
        yaml.safe_dump(
            {"clientTemperature": {"最近没联系": "冷却"}},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config_dir / "enhanced_rules_args.yaml").write_text(
        yaml.safe_dump(
            {
                "pattern_vars": {"SEARCH": "(?:查找)?"},
                "rules": [
                    {
                        "name": "已有规则",
                        "field": "clientTemperature",
                        "operator": "MATCH",
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_change_set(path: Path) -> None:
    path.write_text(
        """
id: apply_config_test
title: 配置自动应用测试
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
test_cases:
  - id: ct_001
    query: 高温客户
    expected:
      query_logic: AND
      conditions:
        - field: clientTemperature
          operator: MATCH
          value: 高温
""",
        encoding="utf-8",
    )


def test_apply_change_set_dry_run_writes_patch_without_changing_config(tmp_path: Path):
    config_dir = tmp_path / "config"
    _write_config_files(config_dir)
    change_set_path = tmp_path / "change_set.yaml"
    _write_change_set(change_set_path)
    before = (config_dir / "field_definitions_args.yaml").read_text(encoding="utf-8")

    result = apply_change_set_to_config(
        load_change_set(change_set_path),
        config_dir=config_dir,
        apply=False,
    )

    assert result.changed_files
    assert result.patch_path == tmp_path / "config_diff.patch"
    assert "client_temperature_match" in result.patch_text
    assert (config_dir / "field_definitions_args.yaml").read_text(encoding="utf-8") == before


def test_apply_change_set_updates_config_files(tmp_path: Path):
    config_dir = tmp_path / "config"
    _write_config_files(config_dir)
    change_set_path = tmp_path / "change_set.yaml"
    _write_change_set(change_set_path)

    apply_change_set_to_config(
        load_change_set(change_set_path),
        config_dir=config_dir,
        apply=True,
    )

    definitions = yaml.safe_load((config_dir / "field_definitions_args.yaml").read_text(encoding="utf-8"))
    enums = yaml.safe_load((config_dir / "field_enums_args.yaml").read_text(encoding="utf-8"))
    mappings = yaml.safe_load((config_dir / "value_mappings_args.yaml").read_text(encoding="utf-8"))
    rules = yaml.safe_load((config_dir / "enhanced_rules_args.yaml").read_text(encoding="utf-8"))

    assert definitions["intents"][-1]["id"] == "client_temperature_match"
    assert enums["clientTemperature"]["values"] == ["低温", "中温", "高温"]
    assert mappings["clientTemperature"]["最近没联系"] == "冷却"
    assert mappings["clientTemperature"]["热客户"] == "高温"
    assert mappings["clientTemperature"]["暖客户"] == "中温"
    assert rules["rules"][-1]["name"] == "客户温度匹配"
