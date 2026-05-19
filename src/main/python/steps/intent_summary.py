"""
将结构化条件列表转换为人类可读的查询意图摘要。
"""
from __future__ import annotations

import calendar
import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

import yaml

from src.main.python.config.settings import settings
from src.main.python.models.schemas import Condition, Operator, QueryLogic, RangeValue


class IntentSummaryService:
    """意图摘要服务，负责加载配置、过滤不支持字段、生成摘要。"""

    def __init__(
        self
    ) -> None:
        self.labels_path = Path(
            settings.INTENT_SUMMARY_PATH
        )
        self.field_definitions_path = Path(
            settings.FIELD_DEFINITIONS_PATH
        )
        self._labels: dict[str, Any] = {}
        self.field_labels: dict[str, str] = {}
        self.op_labels: dict[str, str] = {}
        self.messages: dict[str, str] = {}
        self.date_labels: dict[str, str] = {}
        self.family_templates: dict[str, Any] = {}
        self.profile_phrases: dict[str, dict[str, str]] = {}
        self.bare_value_weak_summary: Optional[str] = None
        self.bare_value_weak_fields: frozenset[str] = frozenset()
        self.unsupported_fields: frozenset[str] = frozenset()

    def load(self) -> "IntentSummaryService":
        self._load_labels()
        self._load_bare_value_weak_summary()
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

        bare_value_summary = self._bare_value_weak_summary(conditions, query_logic)
        if bare_value_summary:
            return bare_value_summary

        supported_parts: list[str] = []
        unsupported_labels: list[str] = []
        seen_unsupported: set[str] = set()

        supported_conditions: list[Condition] = []
        for cond in conditions:
            if cond.field in self.unsupported_fields:
                label = self._unsupported_display_text(cond)
                if label not in seen_unsupported:
                    unsupported_labels.append(label)
                    seen_unsupported.add(label)
            else:
                supported_conditions.append(cond)

        for group in self._group_conditions_for_display(supported_conditions, query_logic):
            if len(group) == 1:
                supported_parts.append(self._condition_to_text(group[0], conditions))
                continue

            group_texts: list[str] = []
            seen_texts: set[str] = set()
            for cond in group:
                text = self._condition_to_text(cond, conditions)
                if text in seen_texts:
                    continue
                seen_texts.add(text)
                group_texts.append(text)

            if group_texts:
                if query_logic == QueryLogic.AND:
                    group_connector = self._message("connector_and", "\n并且")
                else:
                    group_connector = self._message("connector_or", "\n或者")
                supported_parts.append(group_connector.join(group_texts))

        connector = (
            self._message("connector_and", "\n并且")
            if query_logic == QueryLogic.AND
            else self._message("connector_or", "\n或者")
        )
        if supported_parts:
            supported_parts[-1] = self._append_customer_suffix(supported_parts[-1])

        supported_summary = connector.join(supported_parts)
        unsupported_summary = ""
        if unsupported_labels:
            unsupported_suffix_key = (
                "unsupported_suffix_with_supported"
                if supported_summary
                else "unsupported_suffix_without_supported"
            )
            unsupported_suffix_default = (
                "暂不支持搜索，系统将按可支持字段搜索。"
                if supported_summary
                else "暂不支持搜索，无法进行查询。"
            )
            unsupported_summary = (
                self._message("unsupported_prefix", "提示：")
                + "、".join(unsupported_labels)
                + self._message(unsupported_suffix_key, unsupported_suffix_default)
            )
        if not supported_summary and not unsupported_summary:
            return self._message("no_conditions", "未识别到明确查询条件")
        if not supported_summary and unsupported_summary:
            return unsupported_summary
        summary_prefix = self._message("summary_prefix", "系统识别查询条件：\n")
        if supported_summary and unsupported_summary:
            return f"{summary_prefix}{supported_summary}\n{unsupported_summary}"
        return f"{summary_prefix}{supported_summary or unsupported_summary}"

    def _group_conditions_for_display(self, conditions: list[Condition], query_logic: QueryLogic = QueryLogic.AND) -> list[list[Condition]]:
        """将“同值命中多个字段”的条件按 OR 分组，仅用于摘要展示。"""

        if query_logic == QueryLogic.AND:
            return [[cond] for cond in self._reorder_family_conditions_for_display(conditions)]

        groups: list[list[Condition]] = []
        group_index_by_key: dict[str, int] = {}

        for cond in self._reorder_family_conditions_for_display(conditions):
            key = self._display_or_group_key(cond)
            if key is None:
                groups.append([cond])
                continue

            existing_index = group_index_by_key.get(key)
            if existing_index is None:
                groups.append([cond])
                group_index_by_key[key] = len(groups) - 1
                continue

            existing_group = groups[existing_index]
            existing_fields = {item.field for item in existing_group}
            if cond.field in existing_fields:
                groups.append([cond])
                continue

            existing_group.append(cond)

        return groups

    def _reorder_family_conditions_for_display(self, conditions: list[Condition]) -> tuple:
        '''将家庭成员相关意图做顺序调整'''
        ordered = list(conditions)
        family_relation_indices = [
            idx for idx, cond in enumerate(ordered)
            if cond.field == "familyInfo.familyrelation"
        ]
        family_detail_indices = [
            idx for idx, cond in enumerate(ordered)
            if cond.field.startswith("family") and cond.field != "familyInfo.familyrelation"
        ]
        if not family_relation_indices or not family_detail_indices:
            return ordered

        first_relation_idx = family_relation_indices[0]
        first_detail_idx = family_detail_indices[0]
        if family_relation_indices < family_detail_indices:
            return ordered

        relation_cond = ordered.pop(first_relation_idx)
        ordered.insert(first_detail_idx, relation_cond)
        return ordered

    def _display_or_group_key(self, cond: Condition) -> Optional[str]:
        op = cond.operator.value if hasattr(cond.operator, "value") else str(cond.operator)
        if op not in {"MATCH", "CONTAINS"}:
            return None

        value_signature = self._display_value_signature(cond.value)
        if value_signature is None:
            return None

        return value_signature

    def _display_value_signature(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, RangeValue):
            return None
        if isinstance(value, list):
            if not value:
                return None
            if len(value) == 1:
                return f"scalar:{value[0]}"
            return "list:" + "|".join(str(v) for v in value)
        if isinstance(value, dict):
            return None
        return f"scalar:{value}"

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

    def _load_bare_value_weak_summary(self) -> None:
        self.bare_value_weak_summary = None
        self.bare_value_weak_fields = frozenset()
        try:
            with open(settings.ENHANCED_RULES_PATH, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            config = data.get("bare_value_weak_match", {}) or {}
            fields = config.get("fields") or []
            summary = self._message("bare_value_weak_match", "")
            if summary.strip():
                self.bare_value_weak_summary = summary.strip()
            if isinstance(fields, list):
                self.bare_value_weak_fields = frozenset(str(field) for field in fields)
        except Exception:
            self.bare_value_weak_summary = None
            self.bare_value_weak_fields = frozenset()

    def _message(self, key: str, default: str) -> str:
        return self.messages.get(key, default)

    def _bare_value_weak_summary(
        self,
        conditions: list[Condition],
        query_logic: QueryLogic,
    ) -> Optional[str]:
        if query_logic != QueryLogic.OR or not self.bare_value_weak_summary:
            return None
        if len(conditions) < 2:
            return None

        values: set[str] = set()
        fields: set[str] = set()
        for cond in conditions:
            if cond.operator != Operator.MATCH:
                return None
            if cond.value is None or isinstance(cond.value, (RangeValue, dict, list)):
                return None
            fields.add(cond.field)
            values.add(str(cond.value))

        if len(values) != 1:
            return None
        if not self.bare_value_weak_fields:
            return None
        if not fields.issubset(self.bare_value_weak_fields):
            return None
        return self.bare_value_weak_summary

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

    @staticmethod
    def _format_value_for_summary(value: Any) -> str:
        """仅用于意图摘要展示：日期时间去掉时分秒，不改变原始条件值。"""
        text = str(value)
        return re.sub(r"^(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}$", r"\1", text)

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

        if (
            min_d.year == max_d.year
            and min_d.month == max_d.month
            and min_d.day == 1
            and max_d.day == calendar.monthrange(max_d.year, max_d.month)[1]
        ):
            return self._date_label(
                "month_label",
                "{year}年{month}月",
                year=min_d.year,
                month=min_d.month,
            )

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

        # if min_d == tomorrow:
        #     n = (max_d - min_d).days + 1
        #     if n in (7, 30):
        #         return self._format_date_range(min_d, max_d)
        #     return self._date_label("future_n_days", "未来{n}天", n=n)

        # if max_d == today:
        #     n = (max_d - min_d).days + 1
        #     if n in (7, 30, 365):
        #         return self._format_date_range(min_d, max_d)
        #     if n == 90:
        #         return self._date_label("recent_3months", "近三个月")
        #     if n == 180:
        #         return self._date_label("recent_half_year", "近半年")
        #     return self._date_label("recent_n_days", "近{n}天", n=n)

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
        # if min_d == date(today.year, 1, 1) and max_d == date(today.year, 6, 30):
        #     return self._date_label("first_half", "{year}年上半年", year=today.year)
        # if min_d == date(today.year, 7, 1) and max_d == date(today.year, 12, 31):
        #     return self._date_label("second_half", "{year}年下半年", year=today.year)
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
            if cond.field != "familyInfo.familyrelation":
                continue
            if cond.operator not in (Operator.CONTAINS, Operator.MATCH):
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

    def _append_customer_suffix(self, text: str) -> str:
        stripped = text.rstrip()
        if not stripped or stripped.endswith("客户"):
            return text
        return f"{stripped}的客户"

    def _condition_to_text(self, cond: Condition, all_conditions: Optional[list[Condition]] = None) -> str:
        relation = self._get_family_relation(all_conditions or [])
        family_field_label = self._family_field_label(cond.field, relation)
        field_label = family_field_label or self.field_labels.get(cond.field, cond.field)
        op = cond.operator.value if hasattr(cond.operator, "value") else str(cond.operator)
        op_label = self.op_labels.get(op, op)

        profile_phrase = self._profile_phrase(cond)
        if profile_phrase:
            return profile_phrase

        if cond.field == "familyInfo.familyrelation":
            value = cond.value
            if isinstance(value, list):
                if len(value) == 1 and (op == "CONTAINS" or op == "MATCH"):
                    return self._family_template("relation_contains", "有{value}", value=value[0])
                if len(value) == 1 and op == "NOT_CONTAINS":
                    return self._family_template("relation_not_contains", "没有{value}", value=value[0])
            elif value is not None and (op == "CONTAINS" or op == "MATCH"):
                return self._family_template("relation_contains", "有{value}", value=value)
            elif value is not None and op == "NOT_CONTAINS":
                return self._family_template("relation_not_contains", "没有{value}", value=value)

        if op in ("EXISTS", "NOT_EXISTS"):
            prefix = self.op_labels.get(op, "有" if op == "EXISTS" else "没有")
            return f"{prefix}{field_label}"

        value = cond.value
        if isinstance(value, RangeValue):
            min_v = self._format_value_for_summary(value.min) if value.min is not None else ""
            max_v = self._format_value_for_summary(value.max) if value.max is not None else ""
            if cond.field == "familyInfo.familyclientage" and family_field_label and min_v and max_v:
                if min_v == max_v:
                    return self._family_template("age_exact", "{label}={value}岁", label=family_field_label, value=min_v)
                return self._family_template("age_range", "{label}在{min}-{max}岁之间", label=family_field_label, min=min_v, max=max_v)
            try:
                if min_v == max_v and min_v != "":
                    float(min_v)
                    if cond.field == "familyInfo.familyclientage" and family_field_label:
                        return self._family_template("age_exact", "{label}={value}岁", label=family_field_label, value=min_v)
                    if cond.field == "ClientAge":
                        return f"{field_label}={min_v}"
                    return f"{field_label}{self._message('range_equal', '等于')}{min_v}"
            except ValueError:
                pass
            if min_v and not max_v:
                if cond.field == "familyInfo.familyclientage" and family_field_label:
                    return self._family_template("age_gte", "{label}≥{value}", label=family_field_label, value=min_v)
                return f"{field_label}≥{min_v}"
            if max_v and not min_v:
                if cond.field == "familyInfo.familyclientage" and family_field_label:
                    return self._family_template("age_lte", "{label}≤{value}", label=family_field_label, value=max_v)
                return f"{field_label}≤{max_v}"
            if min_v and max_v:
                label = self._infer_date_label(min_v, max_v)
                if label:
                    return f"{field_label}{self._message('range_date_prefix', '在')}{label}"
                return f"{field_label}{self._message('range_between', '在{min}~{max}之间').format(min=min_v, max=max_v)}"
            return f"{field_label}{self._message('range_invalid', '区间无效')}"

        if op == "GTE":
            if cond.field == "familyInfo.familyclientage" and family_field_label:
                return self._family_template("age_gte", "{label}≥{value}", label=family_field_label, value=value)
            return f"{field_label}≥{self._format_value_for_summary(value)}"
        if op == "LTE":
            if cond.field == "familyInfo.familyclientage" and family_field_label:
                return self._family_template("age_lte", "{label}≤{value}", label=family_field_label, value=value)
            return f"{field_label}{op_label}{value}"

        if isinstance(value, list):
            val_str = "、".join(str(v) for v in value)
            return f"{field_label}{op_label}{val_str}"
        return f"{field_label}{op_label}{self._format_value_for_summary(value)}"


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
