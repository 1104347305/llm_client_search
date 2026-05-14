"""轻量日志脱敏工具。"""
from __future__ import annotations

import re
from typing import Any

from src.main.python.models.field_mapping import get_sensitive_field_group


_MOBILE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_ID_CARD_RE = re.compile(r"(?<![A-Za-z0-9])(\d{17}[\dXx]|\d{15})(?![A-Za-z0-9])")
_POLICY_NO_RE = re.compile(r"(?<![A-Za-z0-9])(P\d{10,})(?![A-Za-z0-9])")
_CUSTOMER_NO_RE = re.compile(r"(?<![A-Za-z0-9])(C\d{10,})(?![A-Za-z0-9])")
_NAME_HINT_RE = re.compile(
    r"((?:姓名|名字|名叫|叫|客户叫)(?:是|为)?)([\u4e00-\u9fa5]{2,4})(?=的客户|客户|[，,。；;、\s]|$)"
)

def _name_fields() -> set[str]:
    return get_sensitive_field_group("name")


def _mobile_fields() -> set[str]:
    return get_sensitive_field_group("mobile")


def _id_fields() -> set[str]:
    return get_sensitive_field_group("id")


def _policy_fields() -> set[str]:
    return get_sensitive_field_group("policy")


def _customer_fields() -> set[str]:
    return get_sensitive_field_group("customer")


def _mask_name(value: str) -> str:
    if not value:
        return value
    if len(value) == 1:
        return "*"
    return value[0] + "*" * (len(value) - 1)


def _mask_mobile(value: str) -> str:
    if len(value) < 7:
        return "*" * len(value)
    return value[:3] + "****" + value[-4:]


def _mask_id_card(value: str) -> str:
    if len(value) <= 10:
        return "*" * len(value)
    return value[:6] + "*" * (len(value) - 10) + value[-4:]


def _mask_code(value: str) -> str:
    if len(value) <= 5:
        return value[:1] + "*" * max(0, len(value) - 1)
    return value[:1] + "*" * (len(value) - 5) + value[-4:]


def mask_text(text: str) -> str:
    if not isinstance(text, str) or not text:
        return text

    masked = _MOBILE_RE.sub(lambda m: _mask_mobile(m.group(1)), text)
    masked = _ID_CARD_RE.sub(lambda m: _mask_id_card(m.group(1)), masked)
    masked = _POLICY_NO_RE.sub(lambda m: _mask_code(m.group(1)), masked)
    masked = _CUSTOMER_NO_RE.sub(lambda m: _mask_code(m.group(1)), masked)
    def _replace_name(m: re.Match[str]) -> str:
        name = m.group(2)
        suffix = ""
        if name.endswith("的"):
            name = name[:-1]
            suffix = "的"
        return f"{m.group(1)}{_mask_name(name)}{suffix}"

    masked = _NAME_HINT_RE.sub(_replace_name, masked)
    return masked


def mask_for_log(value: Any) -> Any:
    if isinstance(value, str):
        return mask_text(value)

    if isinstance(value, list):
        return [mask_for_log(item) for item in value]

    if isinstance(value, tuple):
        return tuple(mask_for_log(item) for item in value)

    if isinstance(value, dict):
        masked: dict[str, Any] = {}
        field_name = value.get("field")
        name_fields = _name_fields()
        mobile_fields = _mobile_fields()
        id_fields = _id_fields()
        policy_fields = _policy_fields()
        customer_fields = _customer_fields()
        for key, item in value.items():
            if key in name_fields and isinstance(item, str):
                masked[key] = _mask_name(item)
            elif key in mobile_fields and isinstance(item, str):
                masked[key] = _mask_mobile(item)
            elif key in id_fields and isinstance(item, str):
                masked[key] = _mask_id_card(item)
            elif key in policy_fields and isinstance(item, str):
                masked[key] = _mask_code(item)
            elif key in customer_fields and isinstance(item, str):
                masked[key] = _mask_code(item)
            elif key == "value" and isinstance(field_name, str) and isinstance(item, str):
                if field_name in name_fields:
                    masked[key] = _mask_name(item)
                elif field_name in mobile_fields:
                    masked[key] = _mask_mobile(item)
                elif field_name in id_fields:
                    masked[key] = _mask_id_card(item)
                elif field_name in policy_fields:
                    masked[key] = _mask_code(item)
                elif field_name in customer_fields:
                    masked[key] = _mask_code(item)
                else:
                    masked[key] = mask_for_log(item)
            else:
                masked[key] = mask_for_log(item)
        return masked

    return value
