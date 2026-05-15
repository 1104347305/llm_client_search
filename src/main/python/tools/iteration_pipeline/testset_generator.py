from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.main.python.tools.iteration_pipeline.change_set import ChangeSet


def _condition_from_example(field: dict[str, Any], example: dict[str, Any]) -> dict[str, Any] | None:
    output = example.get("output")
    if isinstance(output, dict):
        return output

    if "value" not in example:
        return None

    return {
        "field": field.get("field"),
        "operator": field.get("operator"),
        "value": example.get("value"),
    }


def generate_cases(change_set: ChangeSet) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    used_signatures: set[str] = set()

    for case in change_set.test_cases:
        case_id = str(case.get("id") or f"case_{len(cases) + 1:03d}")
        used_ids.add(case_id)
        used_signatures.add(_case_signature(case))
        cases.append({**case, "id": case_id})

    for field in change_set.fields:
        field_id = str(field.get("id") or field.get("field") or "field")
        for index, example in enumerate(field.get("examples") or [], start=1):
            if not isinstance(example, dict) or not example.get("query"):
                continue
            case_id = f"{field_id}_example_{index:03d}"
            if case_id in used_ids:
                continue
            condition = _condition_from_example(field, example)
            if not condition:
                continue
            candidate = {
                "query": example["query"],
                "expected": {
                    "query_logic": "AND",
                    "conditions": [condition],
                },
            }
            if _case_signature(candidate) in used_signatures:
                continue
            cases.append(
                {
                    "id": case_id,
                    **candidate,
                    "tags": ["positive", "generated", "example"],
                }
            )
            used_ids.add(case_id)
            used_signatures.add(_case_signature(candidate))

        for index, example in enumerate(field.get("negative_examples") or [], start=1):
            if not isinstance(example, dict) or not example.get("query"):
                continue
            case_id = f"{field_id}_negative_{index:03d}"
            if case_id in used_ids:
                continue
            candidate = {
                "query": example["query"],
                "expected": {
                    "query_logic": "AND",
                    "conditions": [],
                },
            }
            if _case_signature(candidate) in used_signatures:
                continue
            cases.append(
                {
                    "id": case_id,
                    **candidate,
                    "tags": ["negative", "generated"],
                }
            )
            used_ids.add(case_id)
            used_signatures.add(_case_signature(candidate))

    return cases


def _case_signature(case: dict[str, Any]) -> str:
    return json.dumps(
        {
            "query": case.get("query"),
            "expected": case.get("expected") or {},
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def write_jsonl(cases: list[dict[str, Any]], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for case in cases:
            file.write(json.dumps(case, ensure_ascii=False, sort_keys=True))
            file.write("\n")
    return output_path


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                case = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number} invalid JSON: {exc}") from exc
            cases.append(case)
    return cases
