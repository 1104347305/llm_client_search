from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml


_NO_VALUE = object()


def build_change_set_from_field_spec(
    *,
    field: str,
    chinese_name: str,
    field_type: str,
    output: Path | None = None,
    enum_values: list[str] | None = None,
    date_format: str | None = None,
    numeric_unit: str | None = None,
    ordered: bool = False,
    owner: str | None = None,
    change_id: str | None = None,
    title: str | None = None,
    reason: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    spec = {
        "field": field,
        "name": chinese_name,
        "type": field_type,
        "enum_values": enum_values,
        "format": date_format,
        "unit": numeric_unit,
        "ordered": ordered,
    }
    return build_change_set_from_field_specs(
        specs=[spec],
        output=output,
        owner=owner,
        change_id=change_id,
        title=title,
        reason=reason,
        today=today,
    )


def build_change_set_from_field_specs(
    *,
    specs: list[dict[str, Any]],
    output: Path | None = None,
    owner: str | None = None,
    change_id: str | None = None,
    title: str | None = None,
    reason: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    if not specs:
        raise ValueError("at least one field spec is required")
    current = today or date.today()
    first_name = _spec_name(specs[0])
    generated_id = change_id or "_".join(_slug(str(spec.get("field") or "")) for spec in specs[:3])
    change_set: dict[str, Any] = {
        "id": generated_id,
        "title": title or (f"{first_name}等字段自动生成" if len(specs) > 1 else f"{first_name}字段自动生成"),
        "owner": owner,
        "reason": reason or f"支持新增{len(specs)}个字段筛选客户",
        "fields": [],
        "enums": {},
        "l2_rules": [],
        "testset_path": "generated_testset.jsonl",
        "test_cases": [],
        "acceptance": {
            "min_exact_match_rate": 0.95,
            "max_empty_rate": 0.05,
            "max_false_positive_rate": 0.02,
            "max_avg_latency_ms": 3000,
        },
    }
    if owner is None:
        change_set.pop("owner")

    for spec in specs:
        field_name = str(spec.get("field") or "").strip()
        chinese_name = _spec_name(spec)
        normalized_type = str(spec.get("type") or spec.get("field_type") or "").lower()
        if not field_name:
            raise ValueError("field spec is missing field")
        if not chinese_name:
            raise ValueError(f"field spec {field_name} is missing name")

        if normalized_type == "enum":
            values = _spec_enum_values(spec)
            if not values:
                raise ValueError(f"enum field {field_name} requires enum_values")
            _add_enum_field(change_set, field_name, chinese_name, values, bool(spec.get("ordered")))
        elif normalized_type == "date":
            _add_date_field(change_set, field_name, chinese_name, spec.get("format") or "yyyy-MM-dd", current)
        elif normalized_type == "numeric":
            _add_numeric_field(change_set, field_name, chinese_name, spec.get("unit"))
        elif normalized_type in {"text", "string"}:
            _add_text_field(change_set, field_name, chinese_name)
        else:
            raise ValueError(f"unsupported field_type for {field_name}: {normalized_type}")

    _add_multi_condition_cases(change_set)

    if not change_set["enums"]:
        change_set.pop("enums")

    if output is not None:
        _write_yaml(output, change_set)
    return change_set


def build_change_set_from_spec_file(
    *,
    spec_path: Path,
    output: Path | None = None,
    owner: str | None = None,
    change_id: str | None = None,
    title: str | None = None,
    reason: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    spec_doc = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    if isinstance(spec_doc, list):
        specs = spec_doc
        defaults: dict[str, Any] = {}
    elif isinstance(spec_doc, dict):
        specs = spec_doc.get("fields") or []
        defaults = spec_doc
    else:
        raise ValueError("field spec file must be a YAML object or list")
    return build_change_set_from_field_specs(
        specs=list(specs),
        output=output,
        owner=owner if owner is not None else defaults.get("owner"),
        change_id=change_id if change_id is not None else defaults.get("id"),
        title=title if title is not None else defaults.get("title"),
        reason=reason if reason is not None else defaults.get("reason"),
        today=today,
    )


def parse_list_arg(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[,，]", value) if item.strip()]


def _spec_name(spec: dict[str, Any]) -> str:
    return str(spec.get("name") or spec.get("chinese_name") or spec.get("field_chinese_name") or "").strip()


def _spec_enum_values(spec: dict[str, Any]) -> list[str]:
    enum_values = spec.get("enum_values")
    if enum_values is None:
        enum_values = spec.get("values")
    if isinstance(enum_values, str):
        return parse_list_arg(enum_values)
    return [str(value) for value in (enum_values or [])]


def _add_enum_field(change_set: dict[str, Any], field: str, chinese_name: str, values: list[str], ordered: bool) -> None:
    retrieval_text = " ".join([chinese_name, field, *values, *(f"{value}{chinese_name}" for value in values)])
    semantic_name = _semantic_name(chinese_name)
    first_value = values[0]
    second_value = values[1] if len(values) > 1 else values[0]
    third_value = values[2] if len(values) > 2 else second_value

    enum_intents = [
        ("match", "MATCH", "enum", f"{chinese_name}为{first_value}的客户", first_value, f"{chinese_name} 等于 是 为 {retrieval_text}"),
        ("contains", "CONTAINS", "enum", f"{chinese_name}包含{first_value}或{second_value}的客户", [first_value, second_value], f"{chinese_name} 包含 任一 其中之一 {retrieval_text}"),
        ("not_contains", "NOT_CONTAINS", "enum", f"未配置{first_value}{chinese_name}的客户", [first_value], f"{chinese_name} 不包含 未配置 没有 缺少 非 {retrieval_text}"),
        ("exists", "EXISTS", "exists", f"有{chinese_name}信息的客户", _NO_VALUE, f"有{chinese_name}信息 {chinese_name}不为空 已配置{chinese_name}"),
        ("not_exists", "NOT_EXISTS", "not_exists", f"没有{chinese_name}信息的客户", _NO_VALUE, f"没有{chinese_name}信息 {chinese_name}为空 未配置{chinese_name}"),
    ]
    for suffix, operator, value_type, query, value, operator_text in enum_intents:
        change_set["fields"].append(
            {
                "id": f"{_slug(field)}_{suffix}",
                "field": field,
                "operator": operator,
                "value_type": value_type,
                "enum_ref": field if operator in {"MATCH", "CONTAINS", "NOT_CONTAINS"} else None,
                "retrieval_text": operator_text,
                "description": f"表示{semantic_name}，枚举值为：{'、'.join(values)}；支持 {operator} 查询",
                "examples": [
                    {
                        "query": query,
                        "output": _condition(field, operator, value),
                    }
                ],
                "negative_examples": [
                    {
                        "query": f"今天{chinese_name}很高的客户",
                        "reason": f"自然语言中的高低描述不一定是{chinese_name}标准枚举值",
                    }
                ] if operator == "MATCH" else None,
            }
        )
    change_set.setdefault("enums", {})[field] = {"values": values, "ordered": ordered}
    change_set.setdefault("l2_rules", []).extend(
        [
            _enum_rule(chinese_name, field, "MATCH", "枚举匹配", [
                f'{{SEARCH}}{chinese_name}[为是：:]?{{enum}}(?:的客户|客户|名单|的人|人)?',
                f'{{SEARCH}}(?:想找|帮我找|筛选)?{{enum}}{chinese_name}(?:的客户|客户|名单|的人|人)?',
                f'{{SEARCH}}{{enum}}客户',
            ]),
            _enum_rule(chinese_name, field, "CONTAINS", "枚举包含", [
                f'{{SEARCH}}{chinese_name}(?:包含|含有|有|任一|其中之一)[：:]?{{multi_enum}}(?:的客户|客户|名单|的人|人)?',
                f'{{SEARCH}}(?:配置了|持有|买了|购买了|有){{multi_enum}}(?:{chinese_name})?(?:的客户|客户|名单|的人|人)?',
            ]),
            _enum_rule(chinese_name, field, "NOT_CONTAINS", "枚举不包含", [
                f'{{SEARCH}}(?:未配置|未持有|未购买|没有|没买|缺少|不含|不包含){{multi_enum}}(?:{chinese_name})?(?:的客户|客户|名单|的人|人)?',
                f'{{SEARCH}}{chinese_name}(?:不包含|不含|没有|缺少)[：:]?{{multi_enum}}(?:的客户|客户|名单|的人|人)?',
            ]),
            _exists_rule(chinese_name, field, "EXISTS", [
                f'{{SEARCH}}(?:有|存在|已维护|已配置){chinese_name}(?:信息|标签|字段)?(?:的客户|客户|名单|的人|人)?',
                f'{{SEARCH}}{chinese_name}(?:不为空|非空|有值)(?:的客户|客户|名单|的人|人)?',
            ]),
            _exists_rule(chinese_name, field, "NOT_EXISTS", [
                f'{{SEARCH}}(?:没有|无|未维护|未配置){chinese_name}(?:信息|标签|字段)?(?:的客户|客户|名单|的人|人)?',
                f'{{SEARCH}}{chinese_name}(?:为空|空白|没值|无值)(?:的客户|客户|名单|的人|人)?',
            ]),
        ]
    )
    change_set["test_cases"].extend(
        [
            _case(f"{_slug(field)}_001", f"{chinese_name}为{first_value}的客户", field, "MATCH", first_value, ["positive", "l2", "enum"]),
            _case(f"{_slug(field)}_002", f"{chinese_name}包含{first_value}或{second_value}的客户", field, "CONTAINS", [first_value, second_value], ["positive", "l2", "enum"]),
            _case(f"{_slug(field)}_003", f"未配置{third_value}{chinese_name}的客户", field, "NOT_CONTAINS", [third_value], ["positive", "l2", "enum"]),
            _case(f"{_slug(field)}_004", f"有{chinese_name}信息的客户", field, "EXISTS", _NO_VALUE, ["positive", "l2", "exists"]),
            _case(f"{_slug(field)}_005", f"没有{chinese_name}信息的客户", field, "NOT_EXISTS", _NO_VALUE, ["positive", "l2", "exists"]),
            {
                "id": f"{_slug(field)}_negative_001",
                "query": f"今天{chinese_name}很高的客户",
                "expected": {"query_logic": "AND", "conditions": []},
                "tags": ["negative", "boundary"],
            },
        ]
    )


def _add_date_field(change_set: dict[str, Any], field: str, chinese_name: str, date_format: str, today: date) -> None:
    semantic_name = _semantic_name(chinese_name)
    year_min = _format_date_value(date(today.year, 1, 1), date_format, end=False)
    year_max = _format_date_value(date(today.year, 12, 31), date_format, end=True)
    last_year_min = _format_date_value(date(today.year - 1, 1, 1), date_format, end=False)
    last_year_max = _format_date_value(date(today.year - 1, 12, 31), date_format, end=True)
    compare_value = _format_date_value(date(today.year, 6, 1), date_format, end=False)

    date_intents = [
        ("gt", "GT", f"{chinese_name}晚于2026年6月1日的客户", compare_value, f"{chinese_name} 晚于 之后 大于 超过 {field}"),
        ("gte", "GTE", f"{chinese_name}不早于2026年6月1日的客户", compare_value, f"{chinese_name} 不早于 之后及当天 大于等于 起始 {field}"),
        ("lt", "LT", f"{chinese_name}早于2026年6月1日的客户", compare_value, f"{chinese_name} 早于 之前 小于 {field}"),
        ("lte", "LTE", f"{chinese_name}不晚于2026年6月1日的客户", compare_value, f"{chinese_name} 不晚于 之前及当天 小于等于 截止 {field}"),
        ("range", "RANGE", f"今年{chinese_name}的客户", {"min": year_min, "max": year_max}, f"{chinese_name} 区间 范围 今年 去年 本月 最近一年 {field}"),
        ("exists", "EXISTS", f"有{chinese_name}信息的客户", _NO_VALUE, f"有{chinese_name}信息 {chinese_name}不为空"),
        ("not_exists", "NOT_EXISTS", f"没有{chinese_name}信息的客户", _NO_VALUE, f"没有{chinese_name}信息 {chinese_name}为空"),
    ]
    for suffix, operator, query, value, retrieval_text in date_intents:
        change_set["fields"].append(
            {
                "id": f"{_slug(field)}_{suffix}",
                "field": field,
                "operator": operator,
                "value_type": "date" if operator not in {"EXISTS", "NOT_EXISTS"} else ("exists" if operator == "EXISTS" else "not_exists"),
                "format": date_format,
                "retrieval_text": retrieval_text,
                "description": f"表示{semantic_name}，日期格式 {date_format}；支持 {operator} 查询",
                "examples": [{"query": query, "output": _condition(field, operator, value)}],
            }
        )
    change_set.setdefault("l2_rules", []).extend(
        [
            _date_compare_rule(chinese_name, field, "GT", "晚于|在.*之后|大于|超过", "year_start_datetime"),
            _date_compare_rule(chinese_name, field, "GTE", "不早于|不小于|大于等于|从", "year_start_datetime"),
            _date_compare_rule(chinese_name, field, "LT", "早于|在.*之前|小于", "year_end_datetime"),
            _date_compare_rule(chinese_name, field, "LTE", "不晚于|不大于|小于等于|截止到|截至", "year_end_datetime"),
            _date_rule(chinese_name, "今年", field, "current_year", date_format),
            _date_rule(chinese_name, "去年", field, "last_year", date_format),
            _date_rule(chinese_name, "本月", field, "current_month", date_format),
            _exists_rule(chinese_name, field, "EXISTS", [
                f'{{SEARCH}}(?:有|存在|已维护){chinese_name}(?:信息|字段)?(?:的客户|客户|名单|的人|人)?',
                f'{{SEARCH}}{chinese_name}(?:不为空|非空|有值)(?:的客户|客户|名单|的人|人)?',
            ]),
            _exists_rule(chinese_name, field, "NOT_EXISTS", [
                f'{{SEARCH}}(?:没有|无|未维护){chinese_name}(?:信息|字段)?(?:的客户|客户|名单|的人|人)?',
                f'{{SEARCH}}{chinese_name}(?:为空|空白|没值|无值)(?:的客户|客户|名单|的人|人)?',
            ]),
        ]
    )
    change_set["test_cases"].extend(
        [
            _case(f"{_slug(field)}_001", f"{chinese_name}晚于2026年6月1日的客户", field, "GT", compare_value, ["positive", "l2", "date"]),
            _case(f"{_slug(field)}_002", f"{chinese_name}不早于2026年6月1日的客户", field, "GTE", compare_value, ["positive", "l2", "date"]),
            _case(f"{_slug(field)}_003", f"{chinese_name}早于2026年6月1日的客户", field, "LT", compare_value, ["positive", "l2", "date"]),
            _case(f"{_slug(field)}_004", f"{chinese_name}不晚于2026年6月1日的客户", field, "LTE", compare_value, ["positive", "l2", "date"]),
            _case(f"{_slug(field)}_005", f"今年{chinese_name}的客户", field, "RANGE", {"min": year_min, "max": year_max}, ["positive", "l2", "date"]),
            _case(f"{_slug(field)}_006", f"去年{chinese_name}的客户", field, "RANGE", {"min": last_year_min, "max": last_year_max}, ["positive", "l2", "date"]),
            _case(f"{_slug(field)}_007", f"有{chinese_name}信息的客户", field, "EXISTS", _NO_VALUE, ["positive", "l2", "exists"]),
            _case(f"{_slug(field)}_008", f"没有{chinese_name}信息的客户", field, "NOT_EXISTS", _NO_VALUE, ["positive", "l2", "exists"]),
        ]
    )


def _add_numeric_field(change_set: dict[str, Any], field: str, chinese_name: str, numeric_unit: str | None) -> None:
    intent_base = _slug(field)
    unit = numeric_unit or ""
    unit_note = f"，单位：{unit}" if unit else ""
    change_set["fields"].extend(
        [
            _numeric_intent(intent_base, field, chinese_name, "GT", "大于", unit_note),
            _numeric_intent(intent_base, field, chinese_name, "GTE", "以上", unit_note),
            _numeric_intent(intent_base, field, chinese_name, "LT", "小于", unit_note),
            _numeric_intent(intent_base, field, chinese_name, "LTE", "以下", unit_note),
            _numeric_range_intent(intent_base, field, chinese_name, unit_note),
            _exists_intent(intent_base, field, chinese_name, "EXISTS"),
            _exists_intent(intent_base, field, chinese_name, "NOT_EXISTS"),
        ]
    )
    change_set.setdefault("l2_rules", []).extend(
        [
            _numeric_rule(chinese_name, field, "GT", "大于|超过|高于|多于"),
            _numeric_rule(chinese_name, field, "GTE", "以上|及以上|不少于|大于等于"),
            _numeric_rule(chinese_name, field, "LT", "小于|低于|少于|不足"),
            _numeric_rule(chinese_name, field, "LTE", "以下|及以下|不超过|小于等于"),
            _numeric_range_rule(chinese_name, field),
            _exists_rule(chinese_name, field, "EXISTS", [
                f'{{SEARCH}}(?:有|存在|已维护){chinese_name}(?:信息|字段)?(?:的客户|客户|名单|的人|人)?',
                f'{{SEARCH}}{chinese_name}(?:不为空|非空|有值)(?:的客户|客户|名单|的人|人)?',
            ]),
            _exists_rule(chinese_name, field, "NOT_EXISTS", [
                f'{{SEARCH}}(?:没有|无|未维护){chinese_name}(?:信息|字段)?(?:的客户|客户|名单|的人|人)?',
                f'{{SEARCH}}{chinese_name}(?:为空|空白|没值|无值)(?:的客户|客户|名单|的人|人)?',
            ]),
        ]
    )
    change_set["test_cases"].extend(
        [
            _case(f"{intent_base}_001", f"{chinese_name}大于30{unit}的客户", field, "GT", 30, ["positive", "l2", "numeric"]),
            _case(f"{intent_base}_002", f"{chinese_name}30{unit}以上的客户", field, "GTE", 30, ["positive", "l2", "numeric"]),
            _case(f"{intent_base}_003", f"{chinese_name}小于10{unit}的客户", field, "LT", 10, ["positive", "l2", "numeric"]),
            _case(f"{intent_base}_004", f"{chinese_name}10{unit}以下的客户", field, "LTE", 10, ["positive", "l2", "numeric"]),
            _case(f"{intent_base}_005", f"{chinese_name}10到30{unit}的客户", field, "RANGE", {"min": 10, "max": 30}, ["positive", "l2", "numeric"]),
            _case(f"{intent_base}_006", f"有{chinese_name}信息的客户", field, "EXISTS", _NO_VALUE, ["positive", "l2", "exists"]),
            _case(f"{intent_base}_007", f"没有{chinese_name}信息的客户", field, "NOT_EXISTS", _NO_VALUE, ["positive", "l2", "exists"]),
        ]
    )


def _add_text_field(change_set: dict[str, Any], field: str, chinese_name: str) -> None:
    intent_id = f"{_slug(field)}_match"
    semantic_name = _semantic_name(chinese_name)
    change_set["fields"].append(
        {
            "id": intent_id,
            "field": field,
            "operator": "MATCH",
            "value_type": "extract",
            "retrieval_text": f"{chinese_name} {field} {chinese_name}是 {chinese_name}为 {chinese_name}包含",
            "description": f"表示{semantic_name}，从查询文本中提取匹配值",
            "examples": [
                {
                    "query": f"{chinese_name}为示例值的客户",
                    "output": {"field": field, "operator": "MATCH", "value": "示例值"},
                }
            ],
        }
    )
    change_set.setdefault("l2_rules", []).append(
        {
            "name": f"{chinese_name}-文本匹配",
            "patterns": [f'{{SEARCH}}{chinese_name}(?:为|是|匹配|包含|含有)[：:\\s]?([\\u4e00-\\u9fa5A-Za-z0-9_\\-]+)(?:的客户|客户)?'],
            "field": field,
            "operator": "MATCH",
            "value_type": "capture",
            "value": {"group": 1},
            "priority": 8,
            "merge_to_llm": False,
        }
    )
    change_set["test_cases"].append(
        _case(f"{_slug(field)}_001", f"{chinese_name}为示例值的客户", field, "MATCH", "示例值", ["positive", "l2", "text"])
    )


def _numeric_intent(intent_base: str, field: str, chinese_name: str, operator: str, label: str, unit_note: str) -> dict[str, Any]:
    semantic_name = _semantic_name(chinese_name)
    return {
        "id": f"{intent_base}_{operator.lower()}",
        "field": field,
        "operator": operator,
        "value_type": "numeric",
        "unit": unit_note.lstrip("，") or None,
        "retrieval_text": f"{chinese_name} {label} 大于 小于 不少于 不超过 {field}",
        "description": f"表示{semantic_name}{label}筛选{unit_note}",
        "examples": [
            {
                "query": f"{chinese_name}30以上的客户",
                "output": {"field": field, "operator": operator, "value": 30},
            }
        ],
    }


def _numeric_range_intent(intent_base: str, field: str, chinese_name: str, unit_note: str) -> dict[str, Any]:
    semantic_name = _semantic_name(chinese_name)
    return {
        "id": f"{intent_base}_range",
        "field": field,
        "operator": "RANGE",
        "value_type": "numeric",
        "unit": unit_note.lstrip("，") or None,
        "retrieval_text": f"{chinese_name} 区间 范围 之间 从 到 {field}",
        "description": f"表示{semantic_name}区间筛选{unit_note}",
        "examples": [
            {
                "query": f"{chinese_name}10到30的客户",
                "output": {"field": field, "operator": "RANGE", "value": {"min": 10, "max": 30}},
            }
        ],
    }


def _exists_intent(intent_base: str, field: str, chinese_name: str, operator: str) -> dict[str, Any]:
    is_exists = operator == "EXISTS"
    semantic_name = _semantic_name(chinese_name)
    return {
        "id": f"{intent_base}_{operator.lower()}",
        "field": field,
        "operator": operator,
        "value_type": "exists" if is_exists else "not_exists",
        "retrieval_text": f"{'有' if is_exists else '没有'}{chinese_name}信息 {chinese_name}{'不为空' if is_exists else '为空'} {field}",
        "description": f"表示{semantic_name}{'存在' if is_exists else '不存在'}信息",
        "examples": [
            {
                "query": f"{'有' if is_exists else '没有'}{chinese_name}信息的客户",
                "output": _condition(field, operator, _NO_VALUE),
            }
        ],
    }


def _enum_rule(chinese_name: str, field: str, operator: str, label: str, patterns_template: list[str]) -> dict[str, Any]:
    return {
        "name": f"{chinese_name}-{label}",
        "field": field,
        "operator": operator,
        "value_type": "capture",
        "enum_ref": field,
        "patterns_template": patterns_template,
        "value": {"group": 1},
        "priority": 9 if operator != "NOT_CONTAINS" else 10,
        "merge_to_llm": False,
    }


def _exists_rule(chinese_name: str, field: str, operator: str, patterns: list[str]) -> dict[str, Any]:
    return {
        "name": f"{chinese_name}-{'存在' if operator == 'EXISTS' else '不存在'}",
        "patterns": patterns,
        "field": field,
        "operator": operator,
        "value_type": "static",
        "priority": 8 if operator == "EXISTS" else 9,
        "merge_to_llm": False,
    }


def _date_rule(chinese_name: str, label: str, field: str, date_range: str, date_format: str) -> dict[str, Any]:
    return {
        "name": f"{chinese_name}-{label}",
        "field": field,
        "operator": "RANGE",
        "value_type": "date_range_dynamic",
        "value": {"date_range": date_range, "format": date_format},
        "patterns": [
            f'{{SEARCH}}(?:{label}){{CW}}{{0,2}}{chinese_name}(?:的客户|客户)?',
            f'{{SEARCH}}{chinese_name}{{CW}}{{0,2}}(?:在)?{label}(?:的客户|客户)?',
        ],
        "priority": 9,
    }


def _date_compare_rule(chinese_name: str, field: str, operator: str, relation_pattern: str, transform: str) -> dict[str, Any]:
    return {
        "name": f"{chinese_name}-{operator}",
        "patterns": [
            f'{{SEARCH}}{chinese_name}(?:{relation_pattern})(\\d{{4}})年(?:的客户|客户|名单|的人|人)?',
            f'{{SEARCH}}(\\d{{4}})年(?:{relation_pattern}){chinese_name}(?:的客户|客户|名单|的人|人)?',
        ],
        "field": field,
        "operator": operator,
        "value_type": "capture",
        "value": {"group": 1, "transform": transform},
        "priority": 8,
        "merge_to_llm": False,
    }


def _numeric_rule(chinese_name: str, field: str, operator: str, suffix_pattern: str) -> dict[str, Any]:
    return {
        "name": f"{chinese_name}-{operator}",
        "patterns": [
            f'{{SEARCH}}{chinese_name}{{CW}}{{0,2}}(\\d+)(?:元|万|岁|次|分)?(?:{suffix_pattern})(?:的客户|客户)?',
        ],
        "field": field,
        "operator": operator,
        "value_type": "capture",
        "value": {"group": 1, "transform": "int"},
        "priority": 8,
        "merge_to_llm": False,
    }


def _numeric_range_rule(chinese_name: str, field: str) -> dict[str, Any]:
    return {
        "name": f"{chinese_name}-RANGE",
        "patterns": [
            f'{{SEARCH}}{chinese_name}{{CW}}{{0,2}}(\\d+)(?:元|万|岁|次|分)?(?:到|至|-|~)(\\d+)(?:元|万|岁|次|分)?(?:的客户|客户|名单|的人|人)?',
            f'{{SEARCH}}{chinese_name}(?:在)?(\\d+)(?:元|万|岁|次|分)?(?:和|到|至)(\\d+)(?:元|万|岁|次|分)?之间(?:的客户|客户|名单|的人|人)?',
        ],
        "field": field,
        "operator": "RANGE",
        "value_type": "range",
        "value": {"min_group": 1, "max_group": 2, "transform": "int"},
        "priority": 9,
        "merge_to_llm": False,
    }


def _case(case_id: str, query: str, field: str, operator: str, value: Any, tags: list[str]) -> dict[str, Any]:
    condition = _condition(field, operator, value)
    return {
        "id": case_id,
        "query": query,
        "expected": {
            "query_logic": "AND",
            "conditions": [condition],
        },
        "tags": tags,
    }


def _condition(field: str, operator: str, value: Any) -> dict[str, Any]:
    condition = {"field": field, "operator": operator}
    if value is not _NO_VALUE:
        condition["value"] = value
    return condition


def _add_multi_condition_cases(change_set: dict[str, Any]) -> None:
    positive_cases = [
        case
        for case in change_set.get("test_cases", [])
        if "positive" in (case.get("tags") or []) and (case.get("expected") or {}).get("conditions")
    ]
    if not positive_cases:
        return

    first = positive_cases[0]
    first_condition = first["expected"]["conditions"][0]
    change_set["test_cases"].append(
        {
            "id": "multi_existing_gender_001",
            "query": f"男性客户并且{first['query']}",
            "expected": {
                "query_logic": "AND",
                "conditions": [
                    {"field": "clientSex", "operator": "MATCH", "value": "男"},
                    first_condition,
                ],
            },
            "tags": ["positive", "multi_condition", "existing_field"],
        }
    )

    second = next(
        (
            case
            for case in positive_cases[1:]
            if case["expected"]["conditions"][0].get("field") != first_condition.get("field")
        ),
        None,
    )
    if second:
        change_set["test_cases"].append(
            {
                "id": "multi_generated_fields_001",
                "query": f"{first['query']}并且{second['query']}",
                "expected": {
                    "query_logic": "AND",
                    "conditions": [
                        first_condition,
                        second["expected"]["conditions"][0],
                    ],
                },
                "tags": ["positive", "multi_condition", "generated_fields"],
            }
        )


def _format_date_value(value: date, date_format: str, *, end: bool) -> str:
    if "HH:mm:ss" in date_format:
        suffix = "23:59:59" if end else "00:00:00"
        return f"{value:%Y-%m-%d} {suffix}"
    return f"{value:%Y-%m-%d}"


def _slug(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z]+", "_", value).strip("_").lower()
    return normalized or "field"


def _semantic_name(chinese_name: str) -> str:
    return chinese_name if chinese_name.startswith("客户") else f"客户{chinese_name}"


def _write_yaml(output: Path, data: dict[str, Any]) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(_clean_yaml(data), allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return output


def _clean_yaml(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _clean_yaml(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_clean_yaml(item) for item in value if item is not None]
    return value
