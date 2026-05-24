from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.main.python.tools.iteration_pipeline.change_set import ChangeSet


def build_config_fragments(change_set: ChangeSet) -> dict[str, Any]:
    """Render a change set as config-file-shaped YAML fragments."""
    return build_config_fragments_from_raw(
        {
            "fields": change_set.fields,
            "enums": change_set.enums,
            "value_mappings": change_set.value_mappings,
            "l2_rules": change_set.l2_rules,
        }
    )


def build_config_fragments_from_raw(raw: dict[str, Any]) -> dict[str, Any]:
    """Render raw generated content as config-file-shaped YAML fragments."""
    fields = list(raw.get("fields") or [])
    enums, alias_mappings = _normalize_enums(dict(raw.get("enums") or {}))
    value_mappings = _merge_value_mappings(alias_mappings, dict(raw.get("value_mappings") or {}))
    l2_rules = list(raw.get("l2_rules") or [])

    fragments: dict[str, Any] = {}
    if fields:
        fragments["field_definitions_args.yaml"] = {
            "intents": [_field_to_intent(field) for field in fields]
        }
    if enums:
        fragments["field_enums_args.yaml"] = enums
    if value_mappings:
        fragments["value_mappings_args.yaml"] = value_mappings
    if l2_rules:
        fragments["enhanced_rules_args.yaml"] = {
            "rules": [dict(rule) for rule in l2_rules]
        }
    return fragments


def write_config_fragments(
    change_set: ChangeSet,
    output: Path,
    *,
    split_files: bool = False,
) -> dict[str, Path]:
    fragments = build_config_fragments(change_set)
    output = output.resolve()
    written: dict[str, Path] = {}

    if split_files:
        output.mkdir(parents=True, exist_ok=True)
        for filename, data in fragments.items():
            path = output / filename
            path.write_text(_dump_yaml(data), encoding="utf-8")
            written[filename] = path
        return written

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_dump_yaml(fragments), encoding="utf-8")
    written["config_fragments"] = output
    return written


def write_config_fragments_from_raw(
    raw: dict[str, Any],
    output: Path,
    *,
    split_files: bool = True,
) -> dict[str, Path]:
    fragments = build_config_fragments_from_raw(raw)
    output = output.resolve()
    written: dict[str, Path] = {}

    if split_files:
        output.mkdir(parents=True, exist_ok=True)
        for filename, data in fragments.items():
            path = output / filename
            path.write_text(_dump_yaml(data), encoding="utf-8")
            written[filename] = path
        return written

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_dump_yaml(fragments), encoding="utf-8")
    written["config_fragments"] = output
    return written


def _field_to_intent(field_spec: dict[str, Any]) -> dict[str, Any]:
    intent = {
        key: value
        for key, value in field_spec.items()
        if key not in {"update_existing"}
    }
    if "enum" in intent and "enum_ref" not in intent:
        intent["enum_ref"] = intent.pop("enum")
    return intent


def _normalize_enums(enums: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    normalized_enums: dict[str, Any] = {}
    alias_mappings: dict[str, dict[str, Any]] = {}
    for enum_name, enum_spec in enums.items():
        if isinstance(enum_spec, dict):
            normalized = dict(enum_spec)
            aliases = normalized.pop("aliases", None)
            normalized["values"] = list(normalized.get("values") or [])
        else:
            normalized = {"values": list(enum_spec or [])}
            aliases = None
        normalized_enums[str(enum_name)] = normalized
        if aliases:
            alias_mappings[str(enum_name)] = dict(aliases)
    return normalized_enums, alias_mappings


def _merge_value_mappings(
    alias_mappings: dict[str, dict[str, Any]],
    value_mappings: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {
        field_name: dict(mappings)
        for field_name, mappings in alias_mappings.items()
    }
    for field_name, mappings in value_mappings.items():
        if not isinstance(mappings, dict):
            continue
        merged.setdefault(str(field_name), {}).update(mappings)
    return merged


def _dump_yaml(data: Any) -> str:
    return yaml.safe_dump(
        _clean_yaml(data),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )


def _clean_yaml(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _clean_yaml(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_clean_yaml(item) for item in value]
    return value
