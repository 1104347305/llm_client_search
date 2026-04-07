"""
将结构化条件列表转换为人类可读的查询意图摘要。
"""
from __future__ import annotations

import calendar
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

import yaml

from models.schemas import Condition, Operator, QueryLogic, RangeValue


class IntentSummaryService:
    """意图摘要服务，负责加载配置、过滤不支持字段、生成摘要。"""

    def __init__(
        self,
        labels_path: Optional[str] = None,
        field_definitions_path: Optional[str] = None,
    ) -> None:
        self.labels_path = Path(
            labels_path or os.environ.get("INTENT_SUMMARY_LABELS_PATH", "config/intent_summary_labels.yaml")
        )
        self.field_definitions_path = Path(
            field_definitions_path or os.environ.get("FIELD_DEFINITIONS_PATH", "config/field_definitions.yaml")
        )
        self._labels: dict[str, Any] = {}
        self.field_labels: dict[str, str] = {}
        self.op_labels: dict[str, str] = {}
        self.messages: dict[str, str] = {}
        self.date_labels: dict[str, str] = {}
        self.family_templates: dict[str, Any] = {}
        self.profile_phrases: dict[str, dict[str, str]] = {}
        self.unsupported_fields: frozenset[str] = frozenset()

    def load(self) -> "IntentSummaryService":
        self._load_labels()
        self._load_unsupported_fields()
        return self

    def reload(self) -> "IntentSummaryService":
        return self.load()

    def get_unsupported_fields(self) -> frozenset[str]:
        return self.unsupported_fields

    def filter_supported_conditions(self, conditions: list[Condition]) -> list[Condition]:
        return [cond for cond in conditions if cond.field not in self.unsupported_fields]

    def build_intent_summary(
        self,
        conditions: list[Condition],
        query_logic: QueryLogic = QueryLogic.AND,
    ) -> str:
        if not conditions:
            return self._message("no_conditions", "未识别到明确查询条件")

        supported_parts: list[str] = []
        unsupported_labels: list[str] = []
        seen_unsupported: set[str] = set()

        for cond in conditions:
            if cond.field in self.unsupported_fields:
                label = self._unsupported_display_text(cond)
                if label not in seen_unsupported:
                    unsupported_labels.append(label)
                    seen_unsupported.add(label)
            else:
                supported_parts.append(self._condition_to_text(cond, conditions))

        connector = (
            self._message("connector_and", "\n并且")
            if query_logic == QueryLogic.AND
            else self._message("connector_or", "\n或者")
        )
        parts = list(supported_parts)
        if unsupported_labels:
            parts.append(
                self._message("unsupported_prefix", "提示：")
                + "、".join(unsupported_labels)
                + self._message("unsupported_suffix", "暂不支持搜索，系统将按可支持字段搜索")
            )
        if not parts:
            return self._message("no_conditions", "未识别到明确查询条件")
        summary_prefix = self._message("summary_prefix", "系统识别查询条件：\n")
        return f"{summary_prefix}{connector.join(parts)}"

    def _load_labels(self) -> None:
        try:
            with open(self.labels_path, encoding="utf-8") as f:
                self._labels = yaml.safe_load(f) or {}
        except Exception:
            self._labels = {}

        self.field_labels = self._labels.get("field_labels", {})
        self.op_labels = self._labels.get("op_labels", {})
        self.messages = self._labels.get("messages", {})
        self.date_labels = self._labels.get("date_labels", {})
        self.family_templates = self._labels.get("family_templates", {})
        self.profile_phrases = self._labels.get("profile_phrases", {})

    def _load_unsupported_fields(self) -> None:
        try:
            with open(self.field_definitions_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self.unsupported_fields = frozenset(
                intent["field"]
                for intent in data.get("intents", [])
                if intent.get("is_supported") is False
            )
        except Exception:
            self.unsupported_fields = frozenset()

    def _message(self, key: str, default: str) -> str:
        return self.messages.get(key, default)

    def _date_label(self, key: str, default: str, **kwargs: object) -> str:
        template = self.date_labels.get(key, default)
        try:
            return template.format(**kwargs)
        except Exception:
            return default.format(**kwargs) if kwargs else default

    def _family_template(self, key: str, default: str, **kwargs: object) -> str:
        template = self.family_templates.get(key, default)
        try:
            return template.format(**kwargs)
        except Exception:
            return default.format(**kwargs) if kwargs else default

    def _format_date(self, d: date) -> str:
        return self._date_label(
            "exact_day",
            "{year}年{month}月{day}日",
            year=d.year,
            month=f"{d.month:02d}",
            day=f"{d.day:02d}",
        )

    def _format_date_range(self, min_d: date, max_d: date) -> str:
        return self._date_label(
            "exact_date_range",
            "{min}至{max}",
            min=self._format_date(min_d),
            max=self._format_date(max_d),
        )

    def _infer_date_label(self, min_val: str, max_val: str) -> Optional[str]:
        today = date.today()

        def parse_mmdd(value: str) -> Optional[tuple[int, int]]:
            try:
                parts = value.strip().split("-")
                if len(parts) == 2 and len(parts[0]) == 2:
                    return int(parts[0]), int(parts[1])
            except Exception:
                return None
            return None

        def parse_ymd(value: str) -> Optional[date]:
            try:
                value = value.strip().split(" ")[0]
                parts = value.split("-")
                if len(parts) == 3 and len(parts[0]) == 4:
                    return date(int(parts[0]), int(parts[1]), int(parts[2]))
            except Exception:
                return None
            return None

        min_md = parse_mmdd(min_val)
        max_md = parse_mmdd(max_val)
        if min_md and max_md:
            if min_md == max_md:
                return self._date_label(
                    "mmdd_exact",
                    "{month}月{day}日",
                    month=f"{min_md[0]:02d}",
                    day=f"{min_md[1]:02d}",
                )
            last_day = calendar.monthrange(today.year, today.month)[1]
            if min_md == (today.month, 1) and max_md == (today.month, last_day):
                return self._date_label("mm_month_label", "{month}月", month=f"{today.month}")
            next_month = today.month % 12 + 1
            next_year = today.year + 1 if today.month == 12 else today.year
            next_last_day = calendar.monthrange(next_year, next_month)[1]
            if min_md == (next_month, 1) and max_md == (next_month, next_last_day):
                return self._date_label("mm_month_label", "{month}月", month=f"{next_month}")
            return self._date_label("mmdd_range", "{min} 至 {max}", min=min_val, max=max_val)

        min_d = parse_ymd(min_val)
        max_d = parse_ymd(max_val)
        if not min_d or not max_d:
            return None

        if min_d.month == 1 and min_d.day == 1 and max_d.month == 12 and max_d.day == 31 and min_d.year == max_d.year:
            return self._date_label("year_label", "{year}年", year=min_d.year)
        if min_d == today and max_d == today:
            return self._format_date(today)

        tomorrow = today + timedelta(days=1)
        if min_d == tomorrow and max_d == tomorrow:
            return self._format_date(tomorrow)

        days_to_monday = (7 - today.weekday()) % 7 or 7
        next_mon = today + timedelta(days=days_to_monday)
        next_sun = next_mon + timedelta(days=6)
        if min_d == next_mon and max_d == next_sun:
            return self._format_date_range(next_mon, next_sun)

        if min_d == tomorrow:
            n = (max_d - min_d).days + 1
            if n in (7, 30):
                return self._format_date_range(min_d, max_d)
            return self._date_label("future_n_days", "未来{n}天", n=n)

        if max_d == today:
            n = (max_d - min_d).days + 1
            if n in (7, 30, 365):
                return self._format_date_range(min_d, max_d)
            if n == 90:
                return self._date_label("recent_3months", "近三个月")
            if n == 180:
                return self._date_label("recent_half_year", "近半年")
            return self._date_label("recent_n_days", "近{n}天", n=n)

        cm_start = date(today.year, today.month, 1)
        cm_end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
        if min_d == cm_start and max_d == cm_end:
            return self._date_label("month_label", "{year}年{month}月", year=today.year, month=f"{today.month:02d}")

        nm = today.month % 12 + 1
        ny = today.year + 1 if today.month == 12 else today.year
        nm_start = date(ny, nm, 1)
        nm_end = date(ny, nm, calendar.monthrange(ny, nm)[1])
        if min_d == nm_start and max_d == nm_end:
            return self._date_label("month_label", "{year}年{month}月", year=ny, month=f"{nm:02d}")

        if min_d == date(today.year, 1, 1) and max_d == date(today.year, 12, 31):
            return self._date_label("year_label", "{year}年", year=today.year)
        if min_d == date(today.year - 1, 1, 1) and max_d == date(today.year - 1, 12, 31):
            return self._date_label("year_label", "{year}年", year=today.year - 1)
        if min_d == date(today.year, 1, 1) and max_d == date(today.year, 6, 30):
            return self._date_label("first_half", "{year}年上半年", year=today.year)
        if min_d == date(today.year, 7, 1) and max_d == date(today.year, 12, 31):
            return self._date_label("second_half", "{year}年下半年", year=today.year)
        if min_d == max_d:
            return self._date_label(
                "exact_day",
                "{year}年{month}月{day}日",
                year=min_d.year,
                month=f"{min_d.month:02d}",
                day=f"{min_d.day:02d}",
            )
        return self._date_label("date_range", "{min} 至 {max}", min=min_val, max=max_val)

    def _get_family_relation(self, conditions: list[Condition]) -> Optional[str]:
        relation: Optional[str] = None
        for cond in conditions:
            if cond.field != "familyRelation":
                continue
            if cond.operator not in (Operator.CONTAINS, Operator.MATCH, Operator.NESTED_MATCH):
                continue
            value = cond.value
            if isinstance(value, list):
                if len(value) != 1:
                    return None
                current = str(value[0])
            elif value is not None:
                current = str(value)
            else:
                return None
            if relation is None:
                relation = current
            elif relation != current:
                return None
        return relation

    def _family_field_label(self, field: str, relation: Optional[str]) -> Optional[str]:
        if not relation:
            return None
        template = self.family_templates.get("field_labels", {}).get(field)
        if not template:
            return None
        try:
            return template.format(relation=relation)
        except Exception:
            return None

    def _profile_phrase(self, cond: Condition) -> Optional[str]:
        op = cond.operator.value if hasattr(cond.operator, "value") else str(cond.operator)
        value = cond.value
        if op not in ("MATCH", "CONTAINS") or value is None:
            return None
        return self.profile_phrases.get(cond.field, {}).get(str(value))

    def _unsupported_display_text(self, cond: Condition) -> str:
        return self._profile_phrase(cond) or self.field_labels.get(cond.field, cond.field)

    def _condition_to_text(self, cond: Condition, all_conditions: Optional[list[Condition]] = None) -> str:
        relation = self._get_family_relation(all_conditions or [])
        family_field_label = self._family_field_label(cond.field, relation)
        field_label = family_field_label or self.field_labels.get(cond.field, cond.field)
        op = cond.operator.value if hasattr(cond.operator, "value") else str(cond.operator)
        op_label = self.op_labels.get(op, op)

        profile_phrase = self._profile_phrase(cond)
        if profile_phrase:
            return profile_phrase

        if cond.field == "familyRelation":
            value = cond.value
            if isinstance(value, list):
                if len(value) == 1 and op == "CONTAINS":
                    return self._family_template("relation_contains", "有{value}", value=value[0])
                if len(value) == 1 and op == "NOT_CONTAINS":
                    return self._family_template("relation_not_contains", "没有{value}", value=value[0])
            elif value is not None and op == "CONTAINS":
                return self._family_template("relation_contains", "有{value}", value=value)
            elif value is not None and op == "NOT_CONTAINS":
                return self._family_template("relation_not_contains", "没有{value}", value=value)

        if op in ("EXISTS", "NOT_EXISTS"):
            prefix = self.op_labels.get(op, "有" if op == "EXISTS" else "没有")
            return f"{prefix}{field_label}"

        value = cond.value
        if isinstance(value, RangeValue):
            min_v = str(value.min) if value.min is not None else ""
            max_v = str(value.max) if value.max is not None else ""
            if cond.field == "familyClientAge" and family_field_label and min_v and max_v:
                return self._family_template("age_range", "{label}在{min}-{max}岁之间", label=family_field_label, min=min_v, max=max_v)
            try:
                if min_v == max_v and min_v != "":
                    float(min_v)
                    if cond.field == "familyClientAge" and family_field_label:
                        return self._family_template("age_exact", "{label}{value}岁", label=family_field_label, value=min_v)
                    return f"{field_label}{self._message('range_equal', '等于')}{min_v}"
            except ValueError:
                pass
            if min_v and not max_v:
                if cond.field == "familyClientAge" and family_field_label:
                    return self._family_template("age_gte", "{label}≥{value}", label=family_field_label, value=min_v)
                return f"{field_label}≥{min_v}"
            if max_v and not min_v:
                if cond.field == "familyClientAge" and family_field_label:
                    return self._family_template("age_lte", "{label}≤{value}", label=family_field_label, value=max_v)
                return f"{field_label}≤{max_v}"
            if min_v and max_v:
                label = self._infer_date_label(min_v, max_v)
                if label:
                    return f"{field_label}{self._message('range_date_prefix', '在')}{label}"
                return f"{field_label}{self._message('range_between', '在{min}~{max}之间').format(min=min_v, max=max_v)}"
            return f"{field_label}{self._message('range_invalid', '区间无效')}"

        if op == "GTE":
            if cond.field == "familyClientAge" and family_field_label:
                return self._family_template("age_gte", "{label}≥{value}", label=family_field_label, value=value)
            return f"{field_label}≥{value}"
        if op == "LTE":
            if cond.field == "familyClientAge" and family_field_label:
                return self._family_template("age_lte", "{label}≤{value}", label=family_field_label, value=value)
            return f"{field_label}≤{value}"

        if isinstance(value, list):
            val_str = "、".join(str(v) for v in value)
            return f"{field_label}{op_label}{val_str}"
        return f"{field_label}{op_label}{value}"


_intent_summary_service: Optional[IntentSummaryService] = None


def get_intent_summary_service() -> IntentSummaryService:
    global _intent_summary_service
    if _intent_summary_service is None:
        _intent_summary_service = IntentSummaryService().load()
    return _intent_summary_service


def initialize_intent_summary_service() -> IntentSummaryService:
    global _intent_summary_service
    _intent_summary_service = IntentSummaryService().load()
    return _intent_summary_service


def reload_intent_summary_service() -> IntentSummaryService:
    service = get_intent_summary_service()
    service.reload()
    return service


def get_unsupported_fields() -> frozenset[str]:
    return get_intent_summary_service().get_unsupported_fields()


def filter_supported_conditions(conditions: list[Condition]) -> list[Condition]:
    return get_intent_summary_service().filter_supported_conditions(conditions)


def build_intent_summary(
    conditions: list[Condition],
    query_logic: QueryLogic = QueryLogic.AND,
) -> str:
    return get_intent_summary_service().build_intent_summary(conditions, query_logic)
