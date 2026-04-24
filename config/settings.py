import os
from pathlib import Path
from typing import Optional, Dict, Any

import yaml


def _resolve_yaml_path() -> Path:
    """根据 ENV 解析当前配置文件路径。"""
    env = os.environ.get("ENV", "dev").lower()
    config_dir = Path(__file__).parent
    yaml_path = config_dir / f"{env}_client_search_args.yaml"
    return yaml_path


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


class Settings:
    def __init__(self):
        # API 服务配置
        self.API_HOST = _get("API_HOST", "0.0.0.0")
        self.API_PORT = _int(_get("API_PORT", 8000))
        self.API_RELOAD = _bool(_get("API_RELOAD", False))

        # LLM 配置
        self.LLM_MODEL = _get("LLM_MODEL", "qwen3.5-27b")
        self.LLM_API_KEY = _get("LLM_API_KEY", "")
        self.LLM_BASE_URL = _get("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.LLM_TEMPERATURE = _float(_get("LLM_TEMPERATURE", 0.1))
        self.LLM_MAX_TOKENS = _int(_get("LLM_MAX_TOKENS", 2000))

        # 搜索 API 配置
        self.SEARCH_API_BASE_URL = _get("SEARCH_API_BASE_URL", "http://localhost:8081")

        # Elasticsearch 配置
        self.ES_HOST = _get("ES_HOST", "http://localhost:9200")
        self.ES_USERNAME = _get("ES_USERNAME", None)
        self.ES_PASSWORD = _get("ES_PASSWORD", None)
        self.ES_FIELD_INDEX = _get("ES_FIELD_INDEX", "field_intents")
        self.ES_ANALYZER = _get("ES_ANALYZER", "ik_max_word")

        # Redis 配置
        self.REDIS_HOST = _get("REDIS_HOST", "localhost")
        self.REDIS_PORT = _int(_get("REDIS_PORT", 6379))
        self.REDIS_DB = _int(_get("REDIS_DB", 0))
        self.REDIS_PASSWORD = _get("REDIS_PASSWORD", None)

        # 缓存配置
        self.CACHE_TTL = _int(_get("CACHE_TTL", 3600))
        self.SEMANTIC_CACHE_THRESHOLD = _float(_get("SEMANTIC_CACHE_THRESHOLD", 0.85))

        # 性能配置
        self.MAX_WORKERS = _int(_get("MAX_WORKERS", 4))
        self.TIMEOUT_SECONDS = _int(_get("TIMEOUT_SECONDS", 30))

        # 各层开关
        self.ENABLE_L1 = _bool(_get("ENABLE_L1", True))
        self.ENABLE_L2 = _bool(_get("ENABLE_L2", True))
        self.ENABLE_L3 = _bool(_get("ENABLE_L3", True))
        self.ENABLE_L4 = _bool(_get("ENABLE_L4", True))
        self.ENABLE_L4_RAG_ES = _bool(_get("ENABLE_L4_RAG_ES", True))
        self.ENABLE_L4_RAG_TRIE = _bool(_get("ENABLE_L4_RAG_TRIE", True))
        self.ENABLE_L4_RAG_L2 = _bool(_get("ENABLE_L4_RAG_L2", True))
        self.L4_RAG_TOP_K = _int(_get("L4_RAG_TOP_K", 10))

        # 复杂查询阈值：query 长度超过此值直接走 L4，0 表示不启用
        self.L4_DIRECT_QUERY_LENGTH = _int(_get("L4_DIRECT_QUERY_LENGTH", 20))

        # 字段定义文件路径（相对于项目根目录）
        self.FIELD_DEFINITIONS_PATH = _get("FIELD_DEFINITIONS_PATH", "config/field_definitions.yaml")
        self.ENHANCED_RULES_PATH = _get("ENHANCED_RULES_PATH", "config/enhanced_rules.yaml")
        self.ENUMS_DIR_PATH = _get("ENUMS_DIR_PATH", "config/enums")
        self.VALUE_MAPPINGS_PATH = _get("VALUE_MAPPINGS_PATH", "config/value_mappings.yaml")
        self.FIELD_MAPPING_PATH = _get("FIELD_MAPPING_PATH", "config/field_mapping.yaml")

        # agent instructions
        self.AGENT_INSTRUCTIONS_BASE = _get("AGENT_INSTRUCTIONS_BASE", "")

        # parse 接口响应 AES 加密配置
        self.ENABLE_PARSE_RESPONSE_AES = _bool(_get("ENABLE_PARSE_RESPONSE_AES", False))
        self.PARSE_RESPONSE_AES_KEY = _get("PARSE_RESPONSE_AES_KEY", "")

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
