from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # API Configuration
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_RELOAD: bool = True

    # LLM Configuration
    LLM_MODEL: str = "qwen3.5-27b"
    LLM_API_KEY: str = "sk-03b30a83b16d4b40b7da585d54776712"
    LLM_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_TOKENS: int = 2000

    # Search API Configuration
    SEARCH_API_BASE_URL: str = "http://localhost:8081"

    # Bocha Search Configuration (Optional)
    BOCHA_API_KEY: Optional[str] = None
    BOCHA_API_URL: str = "https://api.bochaai.com/v1/web-search"
    BOCHA_TIMEOUT: int = 30

    # Elasticsearch Configuration
    ES_HOST: str = "http://localhost:9200"
    ES_USERNAME: Optional[str] = None
    ES_PASSWORD: Optional[str] = None
    ES_FIELD_INDEX: str = "field_intents"          # 字段意图索引名
    ES_ANALYZER: str = "ik_max_word"               # ik_max_word / smartcn / standard

    # Redis Configuration
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None

    # Cache Configuration
    CACHE_TTL: int = 3600
    SEMANTIC_CACHE_THRESHOLD: float = 0.85

    # Performance Configuration
    MAX_WORKERS: int = 4
    TIMEOUT_SECONDS: int = 30

    # Layer Toggle（各层开关，默认全部开启）
    ENABLE_L1: bool = True   # L1 规则引擎（Jieba 实体提取）
    ENABLE_L2: bool = True   # L2 增强模板匹配器（YAML 规则）
    ENABLE_L3: bool = True   # L3 语义缓存（Redis）
    ENABLE_L4: bool = True   # L4 LLM 解析器（兜底）

    # 复杂查询阈值：query 长度（去空格后）超过此值直接走 L4，0 表示不启用
    L4_DIRECT_QUERY_LENGTH: int = 20

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
