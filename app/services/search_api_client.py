"""
搜索 API 客户端 - 调用外部搜索服务
"""
import httpx
from typing import Dict, Any
from loguru import logger
from config.settings import settings
from app.models.schemas import SearchRequest, Operator, RangeValue


class SearchAPIClient:
    """搜索 API 客户端"""

    def __init__(self):
        """初始化客户端"""
        self.base_url = settings.SEARCH_API_BASE_URL
        self.timeout = settings.TIMEOUT_SECONDS
        logger.info(f"Search API client initialized with base URL: {self.base_url}")

    async def search(self, request: SearchRequest) -> Dict[str, Any]:
        """
        调用搜索 API

        Args:
            request: 搜索请求

        Returns:
            搜索结果
        """
        try:
            # 构建请求体
            payload = self._build_payload(request)

            logger.info(f"Calling search API with payload: {payload}")

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/search/customer",
                    json=payload
                )
                response.raise_for_status()
                result = response.json()

                logger.info(f"Search API returned {result.get('total', 0)} results")
                return result

        except httpx.HTTPError as e:
            logger.error(f"Search API HTTP error: {e}")
            raise
        except Exception as e:
            logger.error(f"Search API error: {e}")
            raise

    def _build_payload(self, request: SearchRequest) -> Dict[str, Any]:
        """
        构建 V3 接口请求体，将内部操作符转换为下游 API 支持的标准操作符：

        内部操作符 → V3 操作符：
          ENUM_GTE / ENUM_LTE  → CONTAINS（value 为列表，API 按 IN 语义处理）
          NESTED_MATCH         → MATCH（V3 通过点号自动识别嵌套字段）
          EXISTS / NOT_EXISTS  → 透传，无 value 字段
          其余操作符            → 透传
        """
        conditions = []

        for condition in request.conditions:
            op = condition.operator.value

            if op == "NESTED_MATCH":
                # V3 MATCH 通过点号自动识别嵌套
                conditions.append({
                    "field": condition.field,
                    "operator": "MATCH",
                    "value": condition.value
                })

            elif op in ("EXISTS", "NOT_EXISTS"):
                # 无需 value
                conditions.append({
                    "field": condition.field,
                    "operator": op
                })

            else:
                cond_dict = {
                    "field": condition.field,
                    "operator": op,
                }
                if isinstance(condition.value, RangeValue):
                    cond_dict["value"] = {"min": condition.value.min, "max": condition.value.max}
                else:
                    cond_dict["value"] = condition.value
                conditions.append(cond_dict)

        payload = {
            "header": {
                "agent_id": request.header.agent_id,
                "page": request.header.page,
                "size": request.header.size
            },
            "query_logic": request.query_logic.value,
            "conditions": conditions
        }

        if request.sort:
            payload["sort"] = [
                {"field": s.field, "order": s.order.value}
                for s in request.sort
            ]

        return payload
