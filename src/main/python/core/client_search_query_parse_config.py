import os
from pathlib import Path
from typing import Any, Dict

import yaml


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PACKAGE_ROOT / "config"
DATA_DIR = PACKAGE_ROOT / "data"


def _resolve_yaml_path() -> Path:
    """根据 ENV 解析当前配置文件路径。"""
    env = os.environ.get("ENV", "dev").lower()
    return CONFIG_DIR / f"{env}_client_search_args.yaml"


def _load_yaml_config() -> dict:
    """
    根据环境变量 ENV 加载对应的 YAML 配置文件。
    ENV 取值：dev（默认）、stg、prd
    """
    env = os.environ.get("ENV", "dev").lower()
    yaml_path = _resolve_yaml_path()

    if not yaml_path.exists():
        raise FileNotFoundError(
            f"配置文件不存在: {yaml_path}，请检查 ENV 环境变量（当前: {env}）"
        )

    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_cfg = _load_yaml_config()


def _get(key: str, default=None):
    """优先从环境变量读取，其次从 YAML 配置读取，最后使用默认值。"""
    env_val = os.environ.get(key)
    if env_val is not None:
        return env_val
    return _cfg.get(key, default)


def _bool(val) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return bool(val)


def _int(val) -> int:
    return int(val)


def _float(val) -> float:
    return float(val)


def _path(value: str, default: Path) -> str:
    """Resolve configured resource paths against the refactored package layout."""
    raw = Path(value)
    if raw.is_absolute():
        return str(raw)

    candidates = [
        PACKAGE_ROOT / raw,
        PACKAGE_ROOT / raw.name,
        CONFIG_DIR / raw.name,
        DATA_DIR / raw.name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    if default.name == "enums" and (CONFIG_DIR / "field_enums_args.yaml").exists():
        return str(CONFIG_DIR)
    return str(default)


class Settings:
    def __init__(self):
        self.API_HOST = _get("API_HOST", "0.0.0.0")
        self.API_PORT = _int(_get("API_PORT", 8000))
        self.API_RELOAD = _bool(_get("API_RELOAD", False))

        self.LLM_MODEL = _get("LLM_MODEL", "qwen3.5-27b")
        self.LLM_API_KEY = _get("LLM_API_KEY", "")
        self.LLM_BASE_URL = _get("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.LLM_TEMPERATURE = _float(_get("LLM_TEMPERATURE", 0.1))
        self.LLM_MAX_TOKENS = _int(_get("LLM_MAX_TOKENS", 2000))

        self.SEARCH_API_BASE_URL = _get("SEARCH_API_BASE_URL", "http://localhost:8081")

        self.ES_HOST = _get("ES_HOST", "http://localhost:9200")
        self.ES_USERNAME = _get("ES_USERNAME", None)
        self.ES_PASSWORD = _get("ES_PASSWORD", None)
        self.ES_FIELD_INDEX = _get("ES_FIELD_INDEX", "field_intents")
        self.ES_ANALYZER = _get("ES_ANALYZER", "ik_max_word")

        self.REDIS_HOST = _get("REDIS_HOST", "localhost")
        self.REDIS_PORT = _int(_get("REDIS_PORT", 6379))
        self.REDIS_DB = _int(_get("REDIS_DB", 0))
        self.REDIS_PASSWORD = _get("REDIS_PASSWORD", None)

        self.CACHE_TTL = _int(_get("CACHE_TTL", 3600))
        self.SEMANTIC_CACHE_THRESHOLD = _float(_get("SEMANTIC_CACHE_THRESHOLD", 0.85))

        self.MAX_WORKERS = _int(_get("MAX_WORKERS", 4))
        self.TIMEOUT_SECONDS = _int(_get("TIMEOUT_SECONDS", 30))

        self.ENABLE_L1 = _bool(_get("ENABLE_L1", True))
        self.ENABLE_L2 = _bool(_get("ENABLE_L2", True))
        self.ENABLE_L3 = _bool(_get("ENABLE_L3", True))
        self.ENABLE_L4 = _bool(_get("ENABLE_L4", True))
        self.ENABLE_L4_RAG_ES = _bool(_get("ENABLE_L4_RAG_ES", True))
        self.ENABLE_L4_RAG_TRIE = _bool(_get("ENABLE_L4_RAG_TRIE", True))
        self.ENABLE_L4_RAG_L2 = _bool(_get("ENABLE_L4_RAG_L2", True))
        self.ENABLE_RAGE_L2_CANDIDATES = _bool(_get("ENABLE_RAGE_L2_CANDIDATES", False))

        # L2-L4 合并控制
        self.L4_L2_MERGE_STRATEGY = _get("L4_L2_MERGE_STRATEGY", "llm_only")
        self.L4_L2_REMOVE_MERGED_FROM_PROMPT = _bool(_get("L4_L2_REMOVE_MERGED_FROM_PROMPT", False))

        self.L4_RAG_TOP_K = _int(_get("L4_RAG_TOP_K", 10))
        self.L4_ES_TOP_K = _int(_get("L4_ES_TOP_K", 5))

        self.L4_DIRECT_QUERY_LENGTH = _int(_get("L4_DIRECT_QUERY_LENGTH", 20))
        self.L4_PROMPT_CHAR_BUDGET = _int(_get("L4_PROMPT_CHAR_BUDGET", 4000))
        self.L4_ENUM_OVERLAP_FILTER = _bool(_get("L4_ENUM_OVERLAP_FILTER", True))

        # 字段定义文件路径（相对于项目根目录）
        self.ENABLE_PARSE_RESPONSE_AES = _bool(_get("ENABLE_PARSE_RESPONSE_AES", False))
        self.PARSE_RESPONSE_AES_KEY = _get("PARSE_RESPONSE_AES_KEY", "")

        self.FIELD_DEFINITIONS_PATH = _path(
            _get("FIELD_DEFINITIONS_PATH", str(CONFIG_DIR / "field_definitions_args.yaml")),
            CONFIG_DIR / "field_definitions_args.yaml",
        )
        self.ENHANCED_RULES_PATH = _path(
            _get("ENHANCED_RULES_PATH", str(CONFIG_DIR / "enhanced_rules_args.yaml")),
            CONFIG_DIR / "enhanced_rules_args.yaml",
        )
        self.ENUMS_DIR_PATH = _path(
            _get("ENUMS_DIR_PATH", str(CONFIG_DIR / "enums")),
            CONFIG_DIR / "enums",
        )
        self.VALUE_MAPPINGS_PATH = _path(
            _get("VALUE_MAPPINGS_PATH", str(CONFIG_DIR / "value_mappings_args.yaml")),
            CONFIG_DIR / "value_mappings_args.yaml",
        )
        self.TIME_KNOWLEDGE_PATH = _path(
            _get("TIME_KNOWLEDGE_PATH", str(CONFIG_DIR / "time_knowledge_args.yaml")),
            CONFIG_DIR / "time_knowledge_args.yaml",
        )
        self.INTENT_SUMMARY_PATH = _path(
            _get("INTENT_SUMMARY_PATH", str(DATA_DIR / "intent_summary_labels_args.yaml")),
            DATA_DIR / "intent_summary_labels_args.yaml",
        )
        self.FIELD_MAPPING_PATH = _path(
            _get("FIELD_MAPPING_PATH", str(CONFIG_DIR / "field_mapping.yaml")),
            CONFIG_DIR / "field_mapping.yaml",
        )

        self.AGENT_INSTRUCTIONS_BASE = _get("AGENT_INSTRUCTIONS_BASE", "")


    def reload(self) -> Dict[str, Any]:
        """从当前环境对应的 YAML 重新加载配置，并原地更新实例属性。"""
        global _cfg
        _cfg = _load_yaml_config()

        refreshed = Settings()
        self.__dict__.update(refreshed.__dict__)

        return {
            "env": os.environ.get("ENV", "dev").lower(),
            "config_path": str(_resolve_yaml_path()),
        }


settings = Settings()
