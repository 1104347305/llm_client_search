"""字段映射配置加载。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Set

import yaml

from config.settings import settings


_CONFIG: Dict[str, Any] = {}
_CONFIG_MTIME_NS: int | None = None


def _resolve_config_path() -> Path:
    path = Path(settings.FIELD_MAPPING_PATH)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parents[1] / path


def _load_field_mapping_config() -> Dict[str, Any]:
    path = _resolve_config_path()
    if not path.exists():
        raise FileNotFoundError(f"字段映射配置文件不存在: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ValueError(f"字段映射配置格式非法: {path}")
    return data


def _dict_from(config: Dict[str, Any], name: str) -> Dict[str, Any]:
    value = config.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"字段映射配置项 '{name}' 必须是对象")
    return value


def _list_from(config: Dict[str, Any], name: str) -> List[Any]:
    value = config.get(name, [])
    if not isinstance(value, list):
        raise ValueError(f"字段映射配置项 '{name}' 必须是数组")
    return value


def _refresh_exports() -> None:
    global QUERY_FIELDS
    global NEGATION_WORDS

    QUERY_FIELDS = _dict_from(_CONFIG, "query_fields")
    NEGATION_WORDS = _list_from(_CONFIG, "negation_words")


def _ensure_config_loaded(force: bool = False) -> None:
    global _CONFIG
    global _CONFIG_MTIME_NS

    path = _resolve_config_path()
    stat = path.stat()
    if not force and _CONFIG and _CONFIG_MTIME_NS == stat.st_mtime_ns:
        return

    _CONFIG = _load_field_mapping_config()
    _CONFIG_MTIME_NS = stat.st_mtime_ns
    _refresh_exports()


def reload_field_mapping() -> None:
    """强制重载字段映射配置。"""
    _ensure_config_loaded(force=True)


def _nested_dict(name: str) -> Dict[str, Any]:
    _ensure_config_loaded()
    value = _CONFIG.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"字段映射配置项 '{name}' 必须是对象")
    return value


def get_query_field(key: str) -> str:
    _ensure_config_loaded()
    value = QUERY_FIELDS.get(key)
    if not isinstance(value, str) or not value:
        raise KeyError(f"未配置 query_fields.{key}")
    return value


def get_field_context_group(group: str) -> Set[str]:
    groups = _nested_dict("field_context_groups")
    value = groups.get(group, [])
    if not isinstance(value, list):
        raise ValueError(f"字段映射配置项 'field_context_groups.{group}' 必须是数组")
    return {str(item) for item in value}


def get_sensitive_field_group(group: str) -> Set[str]:
    groups = _nested_dict("sensitive_field_groups")
    value = groups.get(group, [])
    if not isinstance(value, list):
        raise ValueError(f"字段映射配置项 'sensitive_field_groups.{group}' 必须是数组")
    return {str(item) for item in value}


def _pipe_split(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split("|") if item.strip()]
    raise ValueError("字段映射配置项必须是数组或以'|'分隔的字符串")


def get_name_candidate_values(key: str) -> List[str]:
    config = _nested_dict("name_candidate")
    return _pipe_split(config.get(key, ""))


_ensure_config_loaded(force=True)
