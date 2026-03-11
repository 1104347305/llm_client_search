"""
搜索服务 - 整合查询路由和 API 调用
"""
from typing import Dict, Any
from loguru import logger
from app.models.schemas import (
    SearchRequest,
    NaturalLanguageSearchRequest,
    SearchResponse,
    RequestHeader
)
from app.core.query_router import QueryRouter
from app.services.search_api_client import SearchAPIClient


class SearchService:
    """搜索服务"""

    def __init__(self):
        """初始化搜索服务"""
        self.router = QueryRouter()
        self.api_client = SearchAPIClient()
        logger.info("Search service initialized")

    async def natural_language_search(
        self,
        request: NaturalLanguageSearchRequest
    ) -> SearchResponse:
        """
        自然语言搜索

        Args:
            request: 自然语言搜索请求

        Returns:
            搜索响应
        """
        try:
            logger.info(f"Processing natural language query: {request.query}")

            # 使用剥离式流水线路由
            parsed = await self.router.route_with_peeling(request.query)

            # 条件为空时直接返回空结果，不调用后端 API
            if not parsed.conditions:
                logger.info("No conditions parsed, returning empty result")
                return SearchResponse(
                    success=True,
                    message="success",
                    data={"total": 0, "list": []},
                    matched_level=parsed.matched_level,
                    confidence=parsed.confidence,
                    conditions=[],
                    query_logic=parsed.query_logic
                )

            # 构建结构化搜索请求
            search_request = SearchRequest(
                header=RequestHeader(
                    agent_id=request.agent_id,
                    page=request.page,
                    size=request.size
                ),
                query_logic=parsed.query_logic,
                conditions=parsed.conditions,
                sort=request.sort or parsed.sort
            )

            # 调用搜索 API
            result = await self.api_client.search(search_request)

            return SearchResponse(
                success=True,
                message="success",
                data=result,
                matched_level=parsed.matched_level,
                confidence=parsed.confidence,
                conditions=parsed.conditions,
                query_logic=parsed.query_logic
            )

        except Exception as e:
            logger.error(f"Natural language search failed: {e}")
            return SearchResponse(
                success=False,
                message=str(e),
                data={},
                matched_level=0,
                confidence=0.0
            )

    async def structured_search(self, request: SearchRequest) -> SearchResponse:
        """
        结构化搜索

        Args:
            request: 结构化搜索请求

        Returns:
            搜索响应
        """
        try:
            logger.info(f"Processing structured search with {len(request.conditions)} conditions")

            # 条件为空时直接返回空结果，不调用后端 API
            if not request.conditions:
                logger.info("No conditions provided, returning empty result")
                return SearchResponse(
                    success=True,
                    message="success",
                    data={"total": 0, "list": []},
                    matched_level=0,
                    confidence=1.0,
                    conditions=[],
                    query_logic=request.query_logic
                )

            # 直接调用搜索 API
            result = await self.api_client.search(request)

            return SearchResponse(
                success=True,
                message="success",
                data=result,
                matched_level=0,
                confidence=1.0,
                conditions=request.conditions,
                query_logic=request.query_logic
            )

        except Exception as e:
            logger.error(f"Structured search failed: {e}")
            return SearchResponse(
                success=False,
                message=str(e),
                data={},
                matched_level=0,
                confidence=0.0
            )