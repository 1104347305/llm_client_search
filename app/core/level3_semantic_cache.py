"""
Level 3: 语义缓存 - 基于 Redis 的查询缓存
"""
import json
import hashlib
from typing import Optional
from loguru import logger
import redis
from config.settings import settings
from app.models.schemas import ParsedQuery, Condition, QueryLogic, Sort, Operator, RangeValue


class Level3SemanticCache:
    """语义缓存"""

    def __init__(self):
        """初始化缓存"""
        try:
            self.redis_client = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                password=settings.REDIS_PASSWORD,
                decode_responses=True
            )
            self.redis_client.ping()
            logger.info("Redis cache initialized successfully")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}, cache disabled")
            self.redis_client = None

    def _generate_key(self, query: str) -> str:
        """生成缓存键"""
        return f"query_cache:{hashlib.md5(query.encode()).hexdigest()}"

    async def get(self, query: str) -> Optional[ParsedQuery]:
        """
        获取缓存的查询结果

        Args:
            query: 用户查询

        Returns:
            ParsedQuery 或 None
        """
        if not self.redis_client:
            return None

        try:
            key = self._generate_key(query)
            cached = self.redis_client.get(key)

            if cached:
                data = json.loads(cached)
                parsed_query = self._deserialize(data)
                logger.info(f"Cache hit for query: {query}")
                return parsed_query

            logger.debug(f"Cache miss for query: {query}")
            return None

        except Exception as e:
            logger.error(f"Cache get error: {e}")
            return None

    async def set(self, query: str, parsed_query: ParsedQuery) -> bool:
        """
        设置缓存

        Args:
            query: 用户查询
            parsed_query: 解析结果

        Returns:
            是否成功
        """
        if not self.redis_client:
            return False

        try:
            key = self._generate_key(query)
            data = self._serialize(parsed_query)
            self.redis_client.setex(
                key,
                settings.CACHE_TTL,
                json.dumps(data, ensure_ascii=False)
            )
            logger.info(f"Cached query: {query}")
            return True

        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False

    def _serialize(self, parsed_query: ParsedQuery) -> dict:
        """序列化 ParsedQuery"""
        return {
            "conditions": [
                {
                    "field": c.field,
                    "operator": c.operator.value,
                    "value": self._serialize_value(c.value)
                }
                for c in parsed_query.conditions
            ],
            "query_logic": parsed_query.query_logic.value,
            "sort": [
                {"field": s.field, "order": s.order.value}
                for s in (parsed_query.sort or [])
            ] if parsed_query.sort else None,
            "confidence": parsed_query.confidence,
            "matched_level": parsed_query.matched_level
        }

    def _serialize_value(self, value):
        """序列化值"""
        if isinstance(value, RangeValue):
            return {"min": value.min, "max": value.max, "_type": "range"}
        return value

    def _deserialize(self, data: dict) -> ParsedQuery:
        """反序列化为 ParsedQuery"""
        conditions = [
            Condition(
                field=c["field"],
                operator=Operator(c["operator"]),
                value=self._deserialize_value(c["value"])
            )
            for c in data["conditions"]
        ]

        sort = None
        if data.get("sort"):
            from app.models.schemas import Sort, SortOrder
            sort = [
                Sort(field=s["field"], order=SortOrder(s["order"]))
                for s in data["sort"]
            ]

        return ParsedQuery(
            conditions=conditions,
            query_logic=QueryLogic(data["query_logic"]),
            sort=sort,
            confidence=data["confidence"],
            matched_level=data["matched_level"]
        )

    def _deserialize_value(self, value):
        """反序列化值"""
        if isinstance(value, dict) and value.get("_type") == "range":
            return RangeValue(min=value.get("min"), max=value.get("max"))
        return value
