"""
API 路由定义
"""
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Any, Optional, Dict
from loguru import logger
from models.schemas import (
    SearchRequest,
    NaturalLanguageSearchRequest,
    SearchResponse,
    ParseApiRequest,
    ParseApiExtraOutput,
    ParseApiData,
    ParseApiResponse,
)
from services.search_service import SearchService
from core.field_registry import get_field_registry
from core.query_router import QueryRouter
from db.request_logger import get_request_logger
from config.settings import settings

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


class ConfigReloadRequest(BaseModel):
    force_reindex_fields: bool = Field(
        default=True,
        description="是否按最新内容重载全部 YAML 配置，并同步重建字段意图索引"
    )


def _build_debug_patterns(parsed) -> Optional[List[Dict[str, Any]]]:
    """统一组装调试信息：规则层 matched_patterns + L4 prompt。"""
    patterns = list(parsed.matched_patterns or [])
    if parsed.matched_level == 4 and parsed.prompt:
        patterns.append({
            "rule_name": "L4_PROMPT",
            "pattern": None,
            "matched_text": None,
            "match_type": "llm_prompt",
            "prompt": parsed.prompt,
        })
    return patterns or None


def _collect_config_yaml_files() -> List[str]:
    """收集当前服务依赖的全部配置 YAML 文件。"""
    config_dir = Path(__file__).parent / "config"
    return sorted(
        str(path.resolve())
        for path in config_dir.rglob("*.yaml")
    )


def _reload_runtime_components(force_reindex_fields: bool = True) -> Dict[str, Any]:
    """热更新运行时配置与依赖组件。"""
    global search_service, _query_router

    reload_meta = settings.reload()
    reloaded_yaml_files = _collect_config_yaml_files()

    import core.field_registry as reg_module

    reg_module._registry = None
    registry = reg_module.FieldRegistry(force_reindex=force_reindex_fields)
    reg_module._registry = registry

    search_service = SearchService()
    _query_router = QueryRouter()

    search_service.router = _query_router

    return {
        "env": reload_meta["env"],
        "config_path": reload_meta["config_path"],
        "field_definitions_path": str(Path(settings.FIELD_DEFINITIONS_PATH)),
        "force_reindex_fields": force_reindex_fields,
        "reloaded_yaml_files": reloaded_yaml_files,
        "field_intent_total": len(registry.intents),
    }


@router.post("/parse", summary="解析查询条件（不执行搜索）", response_model=ParseApiResponse)
async def parse_query(request: ParseApiRequest):
    """
    解析自然语言查询，返回结构化条件和逻辑关系，不执行实际搜索。
    遵循 AskBob 标准 Bot 接入协议，入参和出参均为标准包装格式。
    """
    try:
        start_time = time.perf_counter()
        parsed = await _query_router.route_with_peeling(request.user_text)
        elapsed = time.perf_counter() - start_time

        conditions = parsed.conditions or []
        robot_text = f"已解析 {len(conditions)} 个查询条件" if conditions else "未能解析查询条件"

        await get_request_logger().log(
            agent_id=request.user_id or "",
            query=request.user_text,
            request_payload=request.model_dump(),
            response_data={},
            matched_level=parsed.matched_level,
            confidence=parsed.confidence,
        )

        return ParseApiResponse(
            code=0,
            msg="操作成功",
            data=ParseApiData(
                robot_text=robot_text,
                end_flag=1,
                trace_id=request.trace_id,
                extra_output_params=ParseApiExtraOutput(
                    query=request.user_text,
                    query_logic=parsed.query_logic,
                    conditions=conditions,
                    matched_level=parsed.matched_level,
                    rewritten_query=parsed.rewritten_query,
                    matched_patterns=_build_debug_patterns(parsed),
                    last_tims=round(elapsed, 6),
                ),
            ),
        )
    except Exception as e:
        logger.error(f"Parse error: {e}")
        return ParseApiResponse(code=500, msg=str(e), data=None)


@router.post("/config/reload", summary="热更新运行时配置")
async def reload_config(request: Optional[ConfigReloadRequest] = None):
    """
    重新加载当前环境 YAML 配置，并同步刷新运行时组件。

    默认同时按最新内容重载全部 YAML 配置，并重建字段意图索引，
    适用于更新了字段定义、规则配置、枚举映射、LLM 提示词等场景。
    """
    try:
        request = request or ConfigReloadRequest()
        result = _reload_runtime_components(force_reindex_fields=request.force_reindex_fields)
        return {
            "success": True,
            "message": "配置热更新完成",
            **result,
        }
    except Exception as e:
        logger.error(f"Config reload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fields/reindex", summary="重建字段意图 ES 索引")
async def reindex_fields():
    """
    强制重建 ES 字段意图索引（知识库更新后调用）

    重新加载 field_definitions.yaml 并写入 ES，全局单例同步刷新。
    """
    try:
        import core.field_registry as reg_module
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
        prompt_section = registry.format_prompt_section(intents, query=request.query)

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
