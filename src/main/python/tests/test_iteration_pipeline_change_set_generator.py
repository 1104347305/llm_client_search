from datetime import date
from pathlib import Path

import yaml

from src.main.python.tools.iteration_pipeline.change_set import load_change_set
from src.main.python.tools.iteration_pipeline.change_set_generator import build_change_set_from_field_spec
from src.main.python.tools.iteration_pipeline.change_set_generator import build_change_set_from_spec_file
from src.main.python.tools.iteration_pipeline.config_lint import has_errors, lint_change_set
from src.main.python.tools.iteration_pipeline.testset_generator import generate_cases


def test_generate_enum_change_set_from_minimal_field_spec(tmp_path: Path):
    output = tmp_path / "change_set.yaml"

    change_set = build_change_set_from_field_spec(
        field="clientTemperature",
        chinese_name="客户温度",
        field_type="enum",
        enum_values=["低温", "中温", "高温"],
        ordered=True,
        output=output,
        today=date(2026, 5, 19),
    )

    raw = yaml.safe_load(output.read_text(encoding="utf-8"))
    loaded = load_change_set(output)

    assert change_set["enums"]["clientTemperature"]["values"] == ["低温", "中温", "高温"]
    assert {field["operator"] for field in raw["fields"]} == {
        "MATCH",
        "CONTAINS",
        "NOT_CONTAINS",
        "EXISTS",
        "NOT_EXISTS",
    }
    assert raw["fields"][0]["enum_ref"] == "clientTemperature"
    assert any(rule.get("operator") == "NOT_CONTAINS" for rule in raw["l2_rules"])
    assert any("multi_condition" in case.get("tags", []) for case in raw["test_cases"])
    assert not has_errors(lint_change_set(loaded.raw))
    assert generate_cases(loaded)


def test_generate_date_change_set_from_minimal_field_spec(tmp_path: Path):
    output = tmp_path / "change_set.yaml"

    build_change_set_from_field_spec(
        field="policies_insure_date",
        chinese_name="投保日期",
        field_type="date",
        date_format="yyyy-MM-dd HH:mm:ss",
        output=output,
        today=date(2026, 5, 19),
    )

    raw = yaml.safe_load(output.read_text(encoding="utf-8"))

    assert {field["operator"] for field in raw["fields"]} == {
        "GT",
        "GTE",
        "LT",
        "LTE",
        "RANGE",
        "EXISTS",
        "NOT_EXISTS",
    }
    range_field = next(field for field in raw["fields"] if field["operator"] == "RANGE")
    assert range_field["examples"][0]["output"]["value"] == {
        "min": "2026-01-01 00:00:00",
        "max": "2026-12-31 23:59:59",
    }
    assert any(rule.get("value", {}).get("date_range") == "current_year" for rule in raw["l2_rules"])
    assert any(
        case["expected"]["conditions"][0].get("value", {}).get("min") == "2025-01-01 00:00:00"
        for case in raw["test_cases"]
        if case["expected"]["conditions"][0]["operator"] == "RANGE"
    )


def test_generate_numeric_change_set_from_minimal_field_spec(tmp_path: Path):
    output = tmp_path / "change_set.yaml"

    build_change_set_from_field_spec(
        field="clientAge",
        chinese_name="客户年龄",
        field_type="numeric",
        numeric_unit="岁",
        output=output,
        today=date(2026, 5, 19),
    )

    raw = yaml.safe_load(output.read_text(encoding="utf-8"))

    assert [field["operator"] for field in raw["fields"]] == [
        "GT",
        "GTE",
        "LT",
        "LTE",
        "RANGE",
        "EXISTS",
        "NOT_EXISTS",
    ]
    assert {rule["operator"] for rule in raw["l2_rules"]} == {
        "GT",
        "GTE",
        "LT",
        "LTE",
        "RANGE",
        "EXISTS",
        "NOT_EXISTS",
    }
    assert any(case["query"] == "客户年龄10到30岁的客户" for case in raw["test_cases"])


def test_generate_batch_change_set_from_spec_file(tmp_path: Path):
    spec_path = tmp_path / "fields.yaml"
    output = tmp_path / "change_set.yaml"
    spec_path.write_text(
        """
id: batch_fields
title: 多字段自动生成
fields:
  - field: clientTemperature
    name: 客户温度
    type: enum
    enum_values: [低温, 中温, 高温]
    ordered: true
  - field: policies_insure_date
    name: 投保日期
    type: date
    format: "yyyy-MM-dd HH:mm:ss"
  - field: clientAge
    name: 客户年龄
    type: numeric
    unit: 岁
""",
        encoding="utf-8",
    )

    build_change_set_from_spec_file(
        spec_path=spec_path,
        output=output,
        today=date(2026, 5, 19),
    )

    raw = yaml.safe_load(output.read_text(encoding="utf-8"))
    loaded = load_change_set(output)

    assert raw["id"] == "batch_fields"
    assert len(raw["fields"]) == 19
    assert len(raw["l2_rules"]) == 21
    assert len(raw["test_cases"]) == 23
    assert raw["enums"]["clientTemperature"]["values"] == ["低温", "中温", "高温"]
    assert {item["field"] for item in raw["fields"]} == {
        "clientTemperature",
        "policies_insure_date",
        "clientAge",
    }
    assert not has_errors(lint_change_set(loaded.raw))
    assert len(generate_cases(loaded)) >= len(raw["test_cases"])
    assert any("existing_field" in case.get("tags", []) for case in raw["test_cases"])
    assert any("generated_fields" in case.get("tags", []) for case in raw["test_cases"])
