from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.main.python.models.schemas import Operator, QueryLogic


@dataclass
class LintMessage:
    level: str
    message: str


def _load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _config_dir() -> Path:
    return _repo_root() / "src" / "main" / "python" / "config"


def _known_enum_names(config_dir: Path) -> set[str]:
    names: set[str] = set()
    field_enums_path = config_dir / "field_enums_args.yaml"
    if field_enums_path.exists():
        field_enums = _load_yaml(field_enums_path)
        if isinstance(field_enums, dict):
            names.update(field_enums.keys())

    for enum_path in config_dir.glob("*_enums_args.yaml"):
        names.add(enum_path.name.removesuffix("_enums_args.yaml"))
    return names


def _known_intent_ids(config_dir: Path) -> set[str]:
    definitions_path = config_dir / "field_definitions_args.yaml"
    if not definitions_path.exists():
        return set()
    definitions = _load_yaml(definitions_path)
    return {
        str(item.get("id"))
        for item in definitions.get("intents", [])
        if isinstance(item, dict) and item.get("id")
    }


def lint_change_set(raw: dict[str, Any]) -> list[LintMessage]:
    messages: list[LintMessage] = []
    config_dir = _config_dir()
    enum_names = _known_enum_names(config_dir)
    enum_names.update((raw.get("enums") or {}).keys())
    known_intent_ids = _known_intent_ids(config_dir)
    seen_intent_ids: set[str] = set()

    if not raw.get("id"):
        messages.append(LintMessage("error", "missing required field: id"))
    if not raw.get("title"):
        messages.append(LintMessage("warning", "missing optional field: title"))

    for index, field in enumerate(raw.get("fields") or [], start=1):
        prefix = f"fields[{index}]"
        intent_id = field.get("id")
        if not intent_id:
            messages.append(LintMessage("error", f"{prefix} missing id"))
        elif intent_id in seen_intent_ids:
            messages.append(LintMessage("error", f"{prefix}.id duplicated: {intent_id}"))
        elif intent_id in known_intent_ids and not field.get("update_existing"):
            messages.append(
                LintMessage(
                    "error",
                    f"{prefix}.id already exists: {intent_id}; set update_existing: true if this change set modifies an existing intent",
                )
            )
        else:
            seen_intent_ids.add(str(intent_id))

        if not field.get("field"):
            messages.append(LintMessage("error", f"{prefix} missing field"))

        operator = field.get("operator")
        if operator not in Operator.__members__:
            messages.append(LintMessage("error", f"{prefix}.operator is invalid: {operator}"))

        enum_ref = field.get("enum_ref") or field.get("enum")
        if enum_ref and enum_ref not in enum_names and not isinstance(enum_ref, list):
            messages.append(LintMessage("warning", f"{prefix}.enum_ref not found in known enums: {enum_ref}"))

    for enum_name, enum_spec in (raw.get("enums") or {}).items():
        if isinstance(enum_spec, dict):
            values = enum_spec.get("values") or []
        else:
            values = enum_spec or []
        if not values:
            messages.append(LintMessage("warning", f"enums.{enum_name} has no values"))
        if len(values) != len(set(map(str, values))):
            messages.append(LintMessage("error", f"enums.{enum_name} contains duplicate values"))

    for field_name, mappings in (raw.get("value_mappings") or {}).items():
        if not isinstance(mappings, dict):
            messages.append(LintMessage("error", f"value_mappings.{field_name} must be an object"))

    pattern_vars = {"enum", "multi_enum", "SEARCH", "CW"}
    for index, rule in enumerate(raw.get("l2_rules") or [], start=1):
        prefix = f"l2_rules[{index}]"
        if not rule.get("name"):
            messages.append(LintMessage("error", f"{prefix} missing name"))
        if not rule.get("field"):
            messages.append(LintMessage("error", f"{prefix} missing field"))
        if rule.get("operator") not in Operator.__members__:
            messages.append(LintMessage("error", f"{prefix}.operator is invalid: {rule.get('operator')}"))
        enum_ref = rule.get("enum_ref")
        if enum_ref and enum_ref not in enum_names:
            messages.append(LintMessage("warning", f"{prefix}.enum_ref not found in known enums: {enum_ref}"))

        for pattern in rule.get("patterns") or []:
            try:
                re.compile(str(pattern))
            except re.error as exc:
                messages.append(LintMessage("error", f"{prefix}.patterns has invalid regex {pattern!r}: {exc}"))

        for template in rule.get("patterns_template") or []:
            for var_name in re.findall(r"{([^{}]+)}", str(template)):
                if var_name not in pattern_vars:
                    messages.append(LintMessage("warning", f"{prefix}.patterns_template references unknown variable: {var_name}"))

    for index, case in enumerate(raw.get("test_cases") or [], start=1):
        prefix = f"test_cases[{index}]"
        if not case.get("id"):
            messages.append(LintMessage("error", f"{prefix} missing id"))
        if not case.get("query"):
            messages.append(LintMessage("error", f"{prefix} missing query"))
        expected = case.get("expected") or {}
        logic = expected.get("query_logic")
        if logic and logic not in QueryLogic.__members__:
            messages.append(LintMessage("error", f"{prefix}.expected.query_logic is invalid: {logic}"))
        for cond_index, condition in enumerate(expected.get("conditions") or [], start=1):
            operator = condition.get("operator")
            if operator not in Operator.__members__:
                messages.append(LintMessage("error", f"{prefix}.expected.conditions[{cond_index}].operator is invalid: {operator}"))

    return messages


def has_errors(messages: list[LintMessage]) -> bool:
    return any(message.level == "error" for message in messages)
