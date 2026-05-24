from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from src.main.python.tools.iteration_pipeline.change_set import ChangeSet


ENHANCEMENT_SCHEMA_HINT = {
    "field_definitions_args.yaml": {
        "intents": [
            {
                "id": "field_match",
                "retrieval_text": "字段中文名 常见问法",
                "field": "fieldName",
                "operator": "MATCH",
                "value_type": "enum",
                "enum_ref": "fieldName",
                "description": "字段语义说明",
                "examples": [
                    {
                        "query": "代理人常见问法",
                        "output": {"field": "fieldName", "operator": "MATCH", "value": "标准值"},
                    }
                ],
                "negative_examples": [
                    {"query": "容易误召回问法", "reason": "为什么不是该字段"}
                ],
            }
        ]
    },
    "enhanced_rules_args.yaml": {
        "rules": [
            {
                "name": "规则名",
                "field": "fieldName",
                "operator": "MATCH",
                "value_type": "capture",
                "patterns": ["{SEARCH}..."],
                "value": {"group": 1},
                "priority": 8,
                "merge_to_llm": False,
            }
        ]
    },
    "field_enums_args.yaml": {
        "fieldName": {"values": ["标准值1", "标准值2"], "ordered": False}
    },
    "value_mappings_args.yaml": {
        "fieldName": {"口语别名": "标准值1"}
    },
    "test_cases": [
        {
            "id": "case_id",
            "query": "测试问题",
            "expected": {
                "query_logic": "AND",
                "conditions": [{"field": "fieldName", "operator": "MATCH", "value": "标准值"}],
            },
            "tags": ["positive", "codex_candidate"],
        }
    ],
}


def render_enhancement_prompt(change_set: ChangeSet, *, max_examples_per_field: int = 8) -> str:
    field_summaries = []
    for field_spec in change_set.fields:
        field_summaries.append(
            {
                "id": field_spec.get("id"),
                "field": field_spec.get("field"),
                "operator": field_spec.get("operator"),
                "value_type": field_spec.get("value_type"),
                "enum_ref": field_spec.get("enum_ref"),
                "format": field_spec.get("format"),
                "unit": field_spec.get("unit"),
                "description": field_spec.get("description"),
                "retrieval_text": field_spec.get("retrieval_text"),
                "examples": (field_spec.get("examples") or [])[:max_examples_per_field],
                "negative_examples": (field_spec.get("negative_examples") or [])[:max_examples_per_field],
            }
        )

    context = {
        "change_set": {
            "id": change_set.id,
            "title": change_set.title,
            "fields": field_summaries,
            "enums": change_set.enums,
            "existing_l2_rule_names": [rule.get("name") for rule in change_set.l2_rules],
            "existing_test_case_ids": [case.get("id") for case in change_set.test_cases],
        },
        "required_json_schema": ENHANCEMENT_SCHEMA_HINT,
    }

    return (
        "你是客户搜索意图解析配置专家。请基于输入 change_set 生成候选增强，不要修改字段英文名，不要编造不存在字段。\n"
        "目标：补充代理人常见问法、反例、多条件测试，以及可执行的 L2 候选规则。\n"
        "要求：\n"
        "1. 只输出 JSON 对象，不要 Markdown。\n"
        "2. 生成格式必须与项目配置文件一致：RAG 使用 field_definitions_args.yaml.intents，L2 使用 enhanced_rules_args.yaml.rules，枚举使用 field_enums_args.yaml，别名映射使用 value_mappings_args.yaml。\n"
        "3. 所有 condition.field 必须来自输入字段，除多条件测试可额外使用既有字段 clientSex。\n"
        "4. operator 必须是 MATCH、CONTAINS、NOT_CONTAINS、GT、GTE、LT、LTE、RANGE、EXISTS、NOT_EXISTS 之一。\n"
        "5. 枚举值必须来自输入 enums；EXISTS/NOT_EXISTS 不要带 value。\n"
        "6. L2 patterns 要沿用项目占位符 {SEARCH}、{CW}，避免过宽泛裸词误召回。\n"
        "7. 输出内容作为候选，需要带 codex_candidate tag 或清晰命名。\n\n"
        f"输入：\n{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


async def call_llm_for_enhancement(
    prompt: str,
    *,
    model: str,
    api_key: str,
    base_url: str | None,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:  # pragma: no cover - dependency is optional in unit tests
        raise RuntimeError("openai package is required for LLM enhancement") from exc

    client_kwargs: dict[str, Any] = {"api_key": api_key, "timeout": timeout_seconds}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = AsyncOpenAI(**client_kwargs)
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "你只输出严格 JSON。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=4000,
    )
    content = response.choices[0].message.content or "{}"
    return parse_enhancement_response(content)


def parse_enhancement_response(content: str) -> dict[str, Any]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("enhancement response must be a JSON object")
    return data


def write_enhanced_change_set(
    change_set: ChangeSet,
    enhancement: dict[str, Any],
    *,
    output: Path,
    promote: bool = False,
) -> dict[str, Any]:
    raw = deepcopy(change_set.raw)
    normalized = _normalize_enhancement(enhancement)
    raw["codex_enhancement"] = normalized
    if promote:
        _promote_enhancement(raw, normalized)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return raw


def _normalize_enhancement(enhancement: dict[str, Any]) -> dict[str, Any]:
    field_definitions = enhancement.get("field_definitions_args.yaml") or {}
    enhanced_rules = enhancement.get("enhanced_rules_args.yaml") or {}
    return {
        "field_definitions_args.yaml": {
            "intents": list(field_definitions.get("intents") or [])
        },
        "field_enums_args.yaml": dict(enhancement.get("field_enums_args.yaml") or {}),
        "value_mappings_args.yaml": dict(enhancement.get("value_mappings_args.yaml") or {}),
        "enhanced_rules_args.yaml": {
            "rules": list(enhanced_rules.get("rules") or enhancement.get("l2_rules") or [])
        },
        "field_enhancements": list(enhancement.get("field_enhancements") or []),
        "l2_rules": list(enhancement.get("l2_rules") or enhanced_rules.get("rules") or []),
        "test_cases": list(enhancement.get("test_cases") or []),
    }


def _promote_enhancement(raw: dict[str, Any], enhancement: dict[str, Any]) -> None:
    fields = raw.setdefault("fields", [])
    field_specs = {
        field_spec.get("field"): field_spec
        for field_spec in fields
        if isinstance(field_spec, dict) and field_spec.get("field")
    }
    for item in enhancement.get("field_enhancements") or []:
        field_name = item.get("field")
        target = field_specs.get(field_name)
        if not target:
            continue
        target.setdefault("examples", []).extend(item.get("examples") or [])
        target.setdefault("negative_examples", []).extend(item.get("negative_examples") or [])

    raw.setdefault("fields", []).extend(
        enhancement.get("field_definitions_args.yaml", {}).get("intents") or []
    )
    raw.setdefault("enums", {}).update(enhancement.get("field_enums_args.yaml") or {})
    for field_name, mappings in (enhancement.get("value_mappings_args.yaml") or {}).items():
        if isinstance(mappings, dict):
            raw.setdefault("value_mappings", {}).setdefault(field_name, {}).update(mappings)
    raw.setdefault("l2_rules", []).extend(
        enhancement.get("enhanced_rules_args.yaml", {}).get("rules")
        or enhancement.get("l2_rules")
        or []
    )
    raw.setdefault("test_cases", []).extend(enhancement.get("test_cases") or [])
