import os
from pathlib import Path
from typing import Optional

import yaml


def _load_yaml_config() -> dict:
    """
    根据环境变量 ENV 加载对应的 YAML 配置文件。
    ENV 取值：dev（默认）、stg、prd
    """
    env = os.environ.get("ENV", "dev").lower()
    config_dir = Path(__file__).parent
    yaml_path = config_dir / f"{env}_client_search_args.yaml"

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
    # API 服务配置
    API_HOST: str = _get("API_HOST", "0.0.0.0")
    API_PORT: int = _int(_get("API_PORT", 8000))
    API_RELOAD: bool = _bool(_get("API_RELOAD", False))

    # LLM 配置
    LLM_MODEL: str = _get("LLM_MODEL", "qwen3.5-27b")
    LLM_API_KEY: str = _get("LLM_API_KEY", "")
    LLM_BASE_URL: str = _get("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    LLM_TEMPERATURE: float = _float(_get("LLM_TEMPERATURE", 0.1))
    LLM_MAX_TOKENS: int = _int(_get("LLM_MAX_TOKENS", 2000))

    # 搜索 API 配置
    SEARCH_API_BASE_URL: str = _get("SEARCH_API_BASE_URL", "http://localhost:8081")


    # Elasticsearch 配置
    ES_HOST: str = _get("ES_HOST", "http://localhost:9200")
    ES_USERNAME: Optional[str] = _get("ES_USERNAME", None)
    ES_PASSWORD: Optional[str] = _get("ES_PASSWORD", None)
    ES_FIELD_INDEX: str = _get("ES_FIELD_INDEX", "field_intents")
    ES_ANALYZER: str = _get("ES_ANALYZER", "ik_max_word")

    # Redis 配置
    REDIS_HOST: str = _get("REDIS_HOST", "localhost")
    REDIS_PORT: int = _int(_get("REDIS_PORT", 6379))
    REDIS_DB: int = _int(_get("REDIS_DB", 0))
    REDIS_PASSWORD: Optional[str] = _get("REDIS_PASSWORD", None)

    # 缓存配置
    CACHE_TTL: int = _int(_get("CACHE_TTL", 3600))
    SEMANTIC_CACHE_THRESHOLD: float = _float(_get("SEMANTIC_CACHE_THRESHOLD", 0.85))

    # 性能配置
    MAX_WORKERS: int = _int(_get("MAX_WORKERS", 4))
    TIMEOUT_SECONDS: int = _int(_get("TIMEOUT_SECONDS", 30))

    # 各层开关
    ENABLE_L1: bool = _bool(_get("ENABLE_L1", True))
    ENABLE_L2: bool = _bool(_get("ENABLE_L2", True))
    ENABLE_L3: bool = _bool(_get("ENABLE_L3", True))
    ENABLE_L4: bool = _bool(_get("ENABLE_L4", True))

    # 复杂查询阈值：query 长度超过此值直接走 L4，0 表示不启用
    L4_DIRECT_QUERY_LENGTH: int = _int(_get("L4_DIRECT_QUERY_LENGTH", 20))

    # 字段定义文件路径（相对于项目根目录）
    FIELD_DEFINITIONS_PATH: str = _get("FIELD_DEFINITIONS_PATH", "config/field_definitions.yaml")


settings = Settings()
