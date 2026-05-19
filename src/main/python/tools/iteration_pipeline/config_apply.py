from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.main.python.tools.iteration_pipeline.change_set import ChangeSet


CONFIG_FILENAMES = {
    "field_definitions": "field_definitions_args.yaml",
    "field_enums": "field_enums_args.yaml",
    "value_mappings": "value_mappings_args.yaml",
    "enhanced_rules": "enhanced_rules_args.yaml",
}


@dataclass
class ApplyResult:
    changed_files: list[Path] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    patch_text: str = ""
    patch_path: Path | None = None


def default_config_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "config"


def apply_change_set_to_config(
    change_set: ChangeSet,
    *,
    config_dir: Path | None = None,
    apply: bool = False,
    patch_output: Path | None = None,
) -> ApplyResult:
    target_dir = (config_dir or default_config_dir()).resolve()
    before_after: dict[Path, tuple[str, str]] = {}
    messages: list[str] = []
    collected_value_mappings: dict[str, dict[str, Any]] = {}

    if change_set.fields:
        path = target_dir / CONFIG_FILENAMES["field_definitions"]
        before, after, file_messages = _merge_field_definitions(path, change_set.fields)
        before_after[path] = (before, after)
        messages.extend(file_messages)

    if change_set.enums:
        path = target_dir / CONFIG_FILENAMES["field_enums"]
        before, after, file_messages, alias_mappings = _merge_field_enums(path, change_set.enums)
        before_after[path] = (before, after)
        messages.extend(file_messages)
        _merge_mapping_specs(collected_value_mappings, alias_mappings)

    if change_set.value_mappings:
        _merge_mapping_specs(collected_value_mappings, change_set.value_mappings)

    if collected_value_mappings:
        path = target_dir / CONFIG_FILENAMES["value_mappings"]
        before, after, file_messages = _merge_value_mappings(path, collected_value_mappings)
        before_after[path] = (before, after)
        messages.extend(file_messages)

    if change_set.l2_rules:
        path = target_dir / CONFIG_FILENAMES["enhanced_rules"]
        before, after, file_messages = _merge_l2_rules(path, change_set.l2_rules)
        before_after[path] = (before, after)
        messages.extend(file_messages)

    patch_text = _build_patch(before_after)
    changed_files = [path for path, (before, after) in before_after.items() if before != after]

    if patch_output is None:
        patch_output = change_set.iteration_dir / "config_diff.patch"
    patch_output.parent.mkdir(parents=True, exist_ok=True)
    patch_output.write_text(patch_text, encoding="utf-8")

    if apply:
        for path in changed_files:
            path.write_text(before_after[path][1], encoding="utf-8")

    return ApplyResult(
        changed_files=changed_files,
        messages=messages,
        patch_text=patch_text,
        patch_path=patch_output,
    )


def _merge_field_definitions(path: Path, fields: list[dict[str, Any]]) -> tuple[str, str, list[str]]:
    raw = _load_yaml_file(path)
    data = _load_yaml_object(raw, default={"intents": []})
    intents = data.setdefault("intents", [])
    if not isinstance(intents, list):
        raise ValueError(f"{path} must contain an intents list")

    index_by_id = {
        str(item.get("id")): index
        for index, item in enumerate(intents)
        if isinstance(item, dict) and item.get("id")
    }
    messages: list[str] = []

    for field_spec in fields:
        intent = _field_to_intent(field_spec)
        intent_id = str(intent.get("id") or "")
        if not intent_id:
            raise ValueError("field intent is missing id")
        if intent_id in index_by_id:
            intents[index_by_id[intent_id]] = intent
            messages.append(f"updated field intent: {intent_id}")
        else:
            intents.append(intent)
            index_by_id[intent_id] = len(intents) - 1
            messages.append(f"added field intent: {intent_id}")

    return raw, _dump_yaml(data), messages


def _field_to_intent(field_spec: dict[str, Any]) -> dict[str, Any]:
    intent = {
        key: value
        for key, value in field_spec.items()
        if key not in {"update_existing"}
    }
    if "enum" in intent and "enum_ref" not in intent:
        intent["enum_ref"] = intent.pop("enum")
    return intent


def _merge_field_enums(
    path: Path,
    enums: dict[str, Any],
) -> tuple[str, str, list[str], dict[str, dict[str, Any]]]:
    raw = _load_yaml_file(path)
    data = _load_yaml_object(raw, default={})
    messages: list[str] = []
    alias_mappings: dict[str, dict[str, Any]] = {}

    for enum_name, enum_spec in enums.items():
        normalized = _normalize_enum_spec(enum_spec)
        aliases = normalized.pop("aliases", None)
        if aliases:
            alias_mappings[str(enum_name)] = dict(aliases)

        existing = data.get(enum_name)
        if isinstance(existing, dict):
            values = _merge_unique(existing.get("values") or [], normalized.get("values") or [])
            merged = {**existing, **normalized, "values": values}
            data[enum_name] = merged
            messages.append(f"merged enum: {enum_name}")
        else:
            data[enum_name] = normalized
            messages.append(f"added enum: {enum_name}")

    return raw, _dump_yaml(data), messages, alias_mappings


def _normalize_enum_spec(enum_spec: Any) -> dict[str, Any]:
    if isinstance(enum_spec, dict):
        normalized = dict(enum_spec)
        normalized["values"] = list(normalized.get("values") or [])
        return normalized
    return {"values": list(enum_spec or [])}


def _merge_value_mappings(
    path: Path,
    value_mappings: dict[str, Any],
) -> tuple[str, str, list[str]]:
    raw = _load_yaml_file(path)
    data = _load_yaml_object(raw, default={})
    messages: list[str] = []

    for field_name, mappings in value_mappings.items():
        if not isinstance(mappings, dict):
            raise ValueError(f"value_mappings.{field_name} must be an object")
        existing = data.get(field_name)
        if not isinstance(existing, dict):
            existing = {}
        data[field_name] = {**existing, **mappings}
        messages.append(f"merged value mappings: {field_name}")

    return raw, _dump_yaml(data), messages


def _merge_l2_rules(path: Path, rules: list[dict[str, Any]]) -> tuple[str, str, list[str]]:
    raw = _load_yaml_file(path)
    data = _load_yaml_object(raw, default={"rules": []})
    existing_rules = data.setdefault("rules", [])
    if not isinstance(existing_rules, list):
        raise ValueError(f"{path} must contain a rules list")

    index_by_name = {
        str(rule.get("name")): index
        for index, rule in enumerate(existing_rules)
        if isinstance(rule, dict) and rule.get("name")
    }
    messages: list[str] = []

    for rule in rules:
        rule_name = str(rule.get("name") or "")
        if not rule_name:
            raise ValueError("l2 rule is missing name")
        if rule_name in index_by_name:
            existing_rules[index_by_name[rule_name]] = dict(rule)
            messages.append(f"updated l2 rule: {rule_name}")
        else:
            existing_rules.append(dict(rule))
            index_by_name[rule_name] = len(existing_rules) - 1
            messages.append(f"added l2 rule: {rule_name}")

    return raw, _dump_yaml(data), messages


def _load_yaml_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _load_yaml_object(raw: str, *, default: Any) -> Any:
    if not raw.strip():
        return default.copy() if isinstance(default, dict) else default
    loaded = yaml.safe_load(raw) or default
    if not isinstance(loaded, type(default)):
        raise ValueError(f"expected YAML {type(default).__name__}, got {type(loaded).__name__}")
    return loaded


def _dump_yaml(data: Any) -> str:
    return yaml.safe_dump(
        data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )


def _merge_unique(existing: list[Any], incoming: list[Any]) -> list[Any]:
    merged: list[Any] = []
    seen: set[str] = set()
    for value in [*existing, *incoming]:
        signature = str(value)
        if signature in seen:
            continue
        seen.add(signature)
        merged.append(value)
    return merged


def _merge_mapping_specs(target: dict[str, dict[str, Any]], incoming: dict[str, Any]) -> None:
    for field_name, mappings in incoming.items():
        if not isinstance(mappings, dict):
            raise ValueError(f"value_mappings.{field_name} must be an object")
        target.setdefault(str(field_name), {}).update(mappings)


def _build_patch(before_after: dict[Path, tuple[str, str]]) -> str:
    chunks: list[str] = []
    for path, (before, after) in before_after.items():
        if before == after:
            continue
        chunks.extend(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
    return "".join(chunks)
