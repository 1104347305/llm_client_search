from pathlib import Path

import yaml


def _load_intents():
    path = Path(__file__).resolve().parents[1] / "config" / "field_definitions.yaml"
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {item["id"]: item for item in data.get("intents", [])}


def test_name_exact_preserves_two_character_full_names():
    intents = _load_intents()
    examples = intents["name_exact"]["examples"]
    outputs = {item["query"]: item["output"]["value"] for item in examples}

    assert outputs["陈成的客户"] == "陈成"
    assert outputs["李保本人"] == "李保"
    assert outputs["张无的客户"] == "张无"
    assert outputs["金美本人"] == "金美"


def test_name_surname_marks_two_character_full_names_as_negative_examples():
    intents = _load_intents()
    negatives = {item["query"]: item["reason"] for item in intents["name_surname"]["negative_examples"]}

    assert "陈成的客户" in negatives
    assert "完整姓名" in negatives["陈成的客户"]
    assert "李保本人" in negatives
    assert "完整姓名" in negatives["李保本人"]
    assert "张无的客户" in negatives
    assert "完整姓名" in negatives["张无的客户"]
    assert "金美本人" in negatives
    assert "完整姓名" in negatives["金美本人"]
