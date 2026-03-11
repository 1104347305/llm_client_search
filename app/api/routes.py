"""
API 路由定义
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Any, Optional, Dict
from loguru import logger
from app.models.schemas import (
    SearchRequest,
    NaturalLanguageSearchRequest,
    SearchResponse
)
from app.services.search_service import SearchService
from app.core.field_registry import get_field_registry
from app.core.query_router import QueryRouter
from app.db.request_logger import get_request_logger

router = APIRouter()
search_service = SearchService()
_query_router = QueryRouter()


# ==================== RAG 检索接口 ====================

class FieldRetrievalRequest(BaseModel):
    query: str = Field(..., description="自然语言查询")
    top_k: int = Field(default=8, ge=1, le=20, description="返回意图数量")


class IntentItem(BaseModel):
    id: str
    field: str
    operator: str
    value_type: str
    retrieval_text: str
    enum: Optional[List[str]] = None
    unit: Optional[str] = None
    notes: Optional[str] = None
    examples: Optional[List[Any]] = None


class FieldRetrievalResponse(BaseModel):
    query: str
    total: int
    intents: List[IntentItem]
    prompt_section: str


class ParseRequest(BaseModel):
    query: str = Field(..., description="自然语言查询")


@router.post("/parse", summary="解析查询条件（不执行搜索）")
async def parse_query(request: ParseRequest):
    """
    解析自然语言查询，返回结构化条件和逻辑关系，不执行实际搜索。
    前端可在发送 Agent 消息的同时调用此接口，快速展示查询条件。
    """
    try:
        parsed = await _query_router.route_with_peeling(request.query)
        conditions = []
        for c in parsed.conditions:
            val = c.value
            if hasattr(val, "min"):
                val = f"{val.min}~{val.max}"
            elif isinstance(val, list):
                val = " / ".join(str(v) for v in val)
            else:
                val = str(val)
            conditions.append({
                "field": c.field,
                "operator": c.operator.value,
                "value": val,
            })
        return {
            "query": request.query,
            "matched_level": parsed.matched_level,
            "confidence": round(parsed.confidence, 4),
            "query_logic": parsed.query_logic if parsed.query_logic else "AND",
            "conditions": conditions,
        }
    except Exception as e:
        logger.error(f"Parse error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fields/reindex", summary="重建字段意图 ES 索引")
async def reindex_fields():
    """
    强制重建 ES 字段意图索引（知识库更新后调用）

    重新加载 field_definitions.yaml 并写入 ES，全局单例同步刷新。
    """
    try:
        import app.core.field_registry as reg_module
        reg_module._registry = None  # 清除单例
        registry = reg_module.FieldRegistry(force_reindex=True)
        reg_module._registry = registry
        return {"success": True, "total": len(registry.intents), "message": "索引重建完成"}
    except Exception as e:
        logger.error(f"Reindex error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fields/retrieve", response_model=FieldRetrievalResponse)
async def retrieve_fields(request: FieldRetrievalRequest):
    """
    RAG 字段检索接口

    根据自然语言查询，从知识库中召回最相关的字段意图，
    返回字段定义及可直接注入 LLM Prompt 的文本段落。

    Args:
        request: 包含 query（查询文本）和 top_k（返回数量）

    Returns:
        匹配的字段意图列表及格式化的 prompt 片段
    """
    try:
        registry = get_field_registry()
        intents = registry.retrieve(request.query, top_k=request.top_k)
        prompt_section = registry.format_prompt_section(intents)

        return FieldRetrievalResponse(
            query=request.query,
            total=len(intents),
            intents=[
                IntentItem(
                    id=intent.get("id", ""),
                    field=intent.get("field", ""),
                    operator=intent.get("operator", ""),
                    value_type=intent.get("value_type", ""),
                    retrieval_text=intent.get("retrieval_text", ""),
                    enum=intent.get("enum"),
                    unit=intent.get("unit"),
                    notes=intent.get("notes"),
                    examples=intent.get("examples"),
                )
                for intent in intents
            ],
            prompt_section=prompt_section,
        )
    except Exception as e:
        logger.error(f"Field retrieval error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search/natural", response_model=SearchResponse)
async def natural_language_search(request: NaturalLanguageSearchRequest):
    """
    自然语言搜索接口

    Args:
        request: 自然语言搜索请求

    Returns:
        搜索响应
    """
    try:
        logger.info(f"Received natural language search request: {request.query}")
        response = await search_service.natural_language_search(request)
        await get_request_logger().log(
            agent_id=request.agent_id,
            query=request.query,
            request_payload=request.model_dump(),
            response_data=response.data,
            matched_level=response.matched_level,
            confidence=response.confidence,
        )
        return response
    except Exception as e:
        logger.error(f"Natural language search error: {e}")
        await get_request_logger().log(
            agent_id=request.agent_id,
            query=request.query,
            request_payload=request.model_dump(),
            response_data={},
            matched_level=0,
            confidence=0.0,
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search/structured", response_model=SearchResponse)
async def structured_search(request: SearchRequest):
    """
    结构化搜索接口

    Args:
        request: 结构化搜索请求

    Returns:
        搜索响应
    """
    try:
        logger.info(f"Received structured search request with {len(request.conditions)} conditions")
        response = await search_service.structured_search(request)
        await get_request_logger().log(
            agent_id=request.header.agent_id,
            query="",
            request_payload=request.model_dump(),
            response_data=response.data,
            matched_level=response.matched_level,
            confidence=response.confidence,
        )
        return response
    except Exception as e:
        logger.error(f"Structured search error: {e}")
        await get_request_logger().log(
            agent_id=request.header.agent_id,
            query="",
            request_payload=request.model_dump(),
            response_data={},
            matched_level=0,
            confidence=0.0,
        )
        raise HTTPException(status_code=500, detail=str(e))
