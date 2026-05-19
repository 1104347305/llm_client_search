"""
API 路由定义
"""
import asyncio
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, HTTPException
import httpx
from pydantic import BaseModel, Field
from typing import List, Any, Optional, Dict
from loguru import logger
from src.main.python.models.schemas import (
    SearchRequest,
    NaturalLanguageSearchRequest,
    SearchResponse,
    ParseApiRequest,
    ParseApiExtraOutput,
    ParseApiData,
    ParseApiResponse,
    Condition,
    Operator,
)
from src.main.python.services.search_service import SearchService
from src.main.python.steps.field_registry import get_field_registry
from src.main.python.steps.query_router import QueryRouter
from src.main.python.steps.intent_summary import (
    build_intent_summary,
    filter_supported_conditions,
    reload_intent_summary_service,
)
from src.main.python.db.request_logger import get_request_logger
from src.main.python.config.settings import settings
from src.main.python.utils.sensitive_masking import mask_for_log
from src.main.python.utils.response_crypto import encrypt_parse_response_fields

router = APIRouter()
_query_router: Optional[QueryRouter] = None
_query_router_load_task: Optional[asyncio.Task] = None
_query_router_load_delayed = False
BACKGROUND_QUERY_ROUTER_LOAD_DELAY_SECONDS = 5.0
_reload_marker_seen_mtime_ns: Optional[int] = None
_reload_marker_failed_mtime_ns: Optional[int] = None
_runtime_reload_task: Optional[asyncio.Task] = None
_runtime_reload_marker_watcher_task: Optional[asyncio.Task] = None
_runtime_reload_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="runtime-reload")
_last_runtime_reload_result: Optional[Dict[str, Any]] = None
_last_runtime_reload_error: Optional[str] = None
RUNTIME_RELOAD_MARKER_WATCH_INTERVAL_SECONDS = 2.0

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
        default=False,
        description="是否按最新内容重载全部 YAML 配置，并同步重建字段意图索引；默认不更新 ES 索引"
    )
    wait: bool = Field(
        default=False,
        description="是否等待当前 worker 完成刷新；默认 false，后台刷新以避免阻塞请求"
    )


class SelectiveConfigReloadRequest(BaseModel):
    files: List[str] = Field(
        ...,
        min_length=1,
        description="要热刷新的配置文件；支持别名、文件名或绝对路径，传 all 等同全量刷新"
    )
    force_reindex_fields: bool = Field(
        default=False,
        description="涉及字段意图时是否同步重建 ES 字段索引"
    )
    wait: bool = Field(
        default=False,
        description="是否等待当前 worker 完成刷新；默认 false，后台刷新以避免阻塞请求"
    )


def _collect_config_yaml_files() -> List[str]:
    """收集当前服务依赖的全部配置 YAML 文件。"""
    config_dirs = []
    field_definitions_path = str(Path(settings.FIELD_DEFINITIONS_PATH))
    if field_definitions_path:
        config_dirs.append(field_definitions_path)

    enhanced_rules_path = str(Path(settings.ENHANCED_RULES_PATH))
    if enhanced_rules_path:
        config_dirs.append(enhanced_rules_path)

    enums_dir_path = Path(settings.ENUMS_DIR_PATH)
    if enums_dir_path:
        enums_files = enums_dir_path.rglob("*_enums_args.yaml")
        config_dirs.extend([str(enums_file) for enums_file in enums_files])

    value_mappings_path = str(Path(settings.VALUE_MAPPINGS_PATH))
    if value_mappings_path:
        config_dirs.append(value_mappings_path)

    intent_summary_path = str(Path(settings.INTENT_SUMMARY_PATH))
    if intent_summary_path:
        config_dirs.append(intent_summary_path)

    field_mapping_path = str(Path(settings.FIELD_MAPPING_PATH))
    if field_mapping_path:
        config_dirs.append(field_mapping_path)

    logger.info(f"所有配置 YAML 文件：{config_dirs}")

    return sorted(config_dirs)


def _current_env_config_path() -> Path:
    env = os.environ.get("ENV", "dev").lower()
    return Path(__file__).resolve().parents[1] / "config" / f"{env}_client_search_args.yaml"


def _reloadable_config_file_map() -> Dict[str, Dict[str, Any]]:
    """返回可按文件热刷新的白名单。key 支持别名，path 用于最终去重。"""
    entries: Dict[str, Dict[str, Any]] = {}

    def add(alias: str, path: str | Path, scope: str) -> None:
        resolved = Path(path).resolve()
        item = {
            "alias": alias,
            "path": str(resolved),
            "scope": scope,
        }
        entries[alias] = item
        entries[resolved.name] = item
        entries[str(resolved)] = item

    add("runtime_config", _current_env_config_path(), "full")
    add("field_definitions", settings.FIELD_DEFINITIONS_PATH, "full")
    add("enhanced_rules", settings.ENHANCED_RULES_PATH, "full")
    add("value_mappings", settings.VALUE_MAPPINGS_PATH, "full")
    add("intent_summary", settings.INTENT_SUMMARY_PATH, "intent_summary")
    add("field_mapping", settings.FIELD_MAPPING_PATH, "full")

    enums_dir = Path(settings.ENUMS_DIR_PATH)
    if enums_dir.exists():
        for enum_file in sorted(enums_dir.glob("*_enums_args.yaml")):
            add(enum_file.stem, enum_file, "full")
            if enum_file.name == "field_enums_args.yaml":
                add("field_enums", enum_file, "full")

    return entries


def _list_reloadable_config_files() -> List[Dict[str, str]]:
    seen_paths: set[str] = set()
    files: List[Dict[str, str]] = []
    for item in _reloadable_config_file_map().values():
        path = item["path"]
        if path in seen_paths:
            continue
        seen_paths.add(path)
        files.append({
            "alias": item["alias"],
            "path": path,
            "scope": item["scope"],
        })
    return sorted(files, key=lambda item: item["alias"])


def _resolve_reload_file_selection(files: List[str]) -> tuple[List[Dict[str, str]], str]:
    registry = _reloadable_config_file_map()
    requested = [str(item).strip() for item in files if str(item).strip()]
    if any(item.lower() == "all" for item in requested):
        selected = _list_reloadable_config_files()
    else:
        selected_by_path: Dict[str, Dict[str, str]] = {}
        invalid: List[str] = []
        for item in requested:
            match = registry.get(item)
            if match is None:
                match = registry.get(Path(item).name)
            if match is None:
                resolved = str(Path(item).resolve())
                match = registry.get(resolved)
            if match is None:
                invalid.append(item)
                continue
            selected_by_path[match["path"]] = match

        if invalid:
            allowed = [item["alias"] for item in _list_reloadable_config_files()]
            raise ValueError(f"不支持热刷新的文件: {invalid}; 可选别名: {allowed}")
        selected = sorted(selected_by_path.values(), key=lambda item: item["alias"])

    scope = "intent_summary" if selected and all(item["scope"] == "intent_summary" for item in selected) else "full"
    return selected, scope


def _runtime_reload_marker_path() -> Path:
    """跨 worker 热更新标记文件，同一台机器上的多进程共享。"""
    return Path(settings.FIELD_DEFINITIONS_PATH).resolve().parent / ".client_search_runtime_reload.json"


def _get_reload_marker_mtime_ns() -> Optional[int]:
    try:
        return _runtime_reload_marker_path().stat().st_mtime_ns
    except FileNotFoundError:
        return None
    except Exception as e:
        logger.warning(f"读取热更新标记失败：{e}")
        return None


def _mark_reload_marker_seen() -> None:
    global _reload_marker_seen_mtime_ns
    _reload_marker_seen_mtime_ns = _get_reload_marker_mtime_ns()


def _write_runtime_reload_marker(result: Dict[str, Any]) -> None:
    marker_path = _runtime_reload_marker_path()
    payload = {
        "pid": os.getpid(),
        "time": time.time(),
        "env": result.get("env"),
        "config_path": result.get("config_path"),
        "force_reindex_fields": result.get("force_reindex_fields", False),
        "selected_files": result.get("selected_files", []),
        "reload_scope": result.get("reload_scope", "full"),
    }
    tmp_path = marker_path.with_suffix(f".{os.getpid()}.tmp")
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(marker_path)
    _mark_reload_marker_seen()


def _runtime_reload_done_callback(task: asyncio.Task) -> None:
    """消费后台任务异常，避免未处理异常丢日志。"""
    try:
        task.result()
    except asyncio.CancelledError:
        logger.info("后台配置热更新任务已取消")
    except Exception:
        logger.exception("后台配置热更新任务失败")


async def _run_runtime_reload_background(
    force_reindex_fields: bool = False,
    publish_marker: bool = False,
    marker_mtime_ns: Optional[int] = None,
    selected_files: Optional[List[Dict[str, str]]] = None,
    reload_scope: str = "full",
) -> None:
    """在线程池构建新运行时组件，完成后一次性切换。"""
    global _runtime_reload_task, _last_runtime_reload_result, _last_runtime_reload_error
    global _reload_marker_seen_mtime_ns, _reload_marker_failed_mtime_ns
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _runtime_reload_executor,
            reload_runtime_components,
            force_reindex_fields,
            selected_files,
            reload_scope,
        )
        if publish_marker:
            await loop.run_in_executor(_runtime_reload_executor, _write_runtime_reload_marker, result)
        elif marker_mtime_ns is not None:
            _reload_marker_seen_mtime_ns = marker_mtime_ns
        else:
            _mark_reload_marker_seen()
        _last_runtime_reload_result = result
        _last_runtime_reload_error = None
        _reload_marker_failed_mtime_ns = None
        logger.info(
            f"后台配置热更新完成：field_intent_total={result.get('field_intent_total')}, "
            f"force_reindex_fields={force_reindex_fields}"
        )
    except Exception as e:
        _last_runtime_reload_error = str(e)
        if marker_mtime_ns is not None:
            _reload_marker_failed_mtime_ns = marker_mtime_ns
        logger.exception(f"后台配置热更新失败：{e}")
    finally:
        _runtime_reload_task = None


def _schedule_runtime_reload(
    force_reindex_fields: bool = False,
    publish_marker: bool = False,
    marker_mtime_ns: Optional[int] = None,
    selected_files: Optional[List[Dict[str, str]]] = None,
    reload_scope: str = "full",
) -> bool:
    """启动后台刷新；已有刷新任务时复用当前任务，避免请求堆积。"""
    global _runtime_reload_task
    if _runtime_reload_task is not None and not _runtime_reload_task.done():
        logger.info("配置热更新任务已在运行，本次请求复用当前后台任务")
        return False

    if _query_router_load_task is not None and not _query_router_load_task.done():
        _query_router_load_task.cancel()

    _runtime_reload_task = asyncio.create_task(
        _run_runtime_reload_background(
            force_reindex_fields=force_reindex_fields,
            publish_marker=publish_marker,
            marker_mtime_ns=marker_mtime_ns,
            selected_files=selected_files,
            reload_scope=reload_scope,
        )
    )
    _runtime_reload_task.add_done_callback(_runtime_reload_done_callback)
    return True


def _runtime_reload_status() -> Dict[str, Any]:
    return {
        "reload_running": _runtime_reload_task is not None and not _runtime_reload_task.done(),
        "last_reload_error": _last_runtime_reload_error,
        "last_reload_result": _last_runtime_reload_result,
    }


def _runtime_reload_marker_is_stale() -> bool:
    marker_mtime_ns = _get_reload_marker_mtime_ns()
    if marker_mtime_ns is None:
        return False
    return _reload_marker_seen_mtime_ns is None or marker_mtime_ns > _reload_marker_seen_mtime_ns


def _ensure_runtime_config_current() -> None:
    """
    多 worker 模式下，每个进程有独立内存单例。
    其它 worker 收到 reload 标记后，在下一次请求前刷新自己的内存缓存；ES 索引不重复重建。
    """
    marker_mtime_ns = _get_reload_marker_mtime_ns()
    if marker_mtime_ns is None:
        return
    if _reload_marker_seen_mtime_ns is not None and marker_mtime_ns <= _reload_marker_seen_mtime_ns:
        return
    if _reload_marker_failed_mtime_ns == marker_mtime_ns and _last_runtime_reload_error:
        return

    logger.info("检测到其它 worker 触发配置热更新，启动当前 worker 后台刷新")
    _schedule_runtime_reload(force_reindex_fields=False, marker_mtime_ns=marker_mtime_ns)


async def _runtime_reload_marker_watch_loop(interval_seconds: float) -> None:
    """后台轮询热更新标记，避免由业务请求或健康检查触发重载。"""
    try:
        while True:
            _ensure_runtime_config_current()
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logger.info("热更新标记 watcher 已取消")
        raise


def start_runtime_reload_marker_watcher(
    interval_seconds: float = RUNTIME_RELOAD_MARKER_WATCH_INTERVAL_SECONDS,
) -> None:
    """启动当前 worker 的热更新标记 watcher。"""
    global _runtime_reload_marker_watcher_task
    if (
        _runtime_reload_marker_watcher_task is None
        or _runtime_reload_marker_watcher_task.done()
    ):
        _runtime_reload_marker_watcher_task = asyncio.create_task(
            _runtime_reload_marker_watch_loop(interval_seconds)
        )


def reload_runtime_components(
    force_reindex_fields: bool = False,
    selected_files: Optional[List[Dict[str, str]]] = None,
    reload_scope: str = "full",
) -> Dict[str, Any]:
    """热更新运行时配置与依赖组件。"""
    global search_service, _query_router, _query_router_load_task, _query_router_load_delayed

    reload_meta = settings.reload()
    reloaded_yaml_files = _collect_config_yaml_files()

    if reload_scope == "intent_summary":
        intent_summary_service = reload_intent_summary_service()
        return {
            "env": reload_meta["env"],
            "config_path": reload_meta["config_path"],
            "field_definitions_path": settings.FIELD_DEFINITIONS_PATH,
            "force_reindex_fields": False,
            "reloaded_yaml_files": [item["path"] for item in selected_files or []],
            "selected_files": selected_files or [],
            "reload_scope": reload_scope,
            "field_intent_total": None,
            "intent_summary_labels_path": str(intent_summary_service.labels_path),
        }

    import src.main.python.models.field_mapping as field_mapping_module
    import src.main.python.steps.level2_enhanced_matcher as level2_module
    import src.main.python.steps.field_registry as reg_module

    field_mapping_module.reload_field_mapping()
    level2_module.NEGATION_WORDS = field_mapping_module.NEGATION_WORDS

    registry = reg_module.FieldRegistry(force_reindex=force_reindex_fields)
    reg_module._registry = registry

    intent_summary_service = reload_intent_summary_service()

    _query_router = QueryRouter()
    _query_router_load_task = None
    _query_router_load_delayed = False

    return {
        "env": reload_meta["env"],
        "config_path": reload_meta["config_path"],
        "field_definitions_path": settings.FIELD_DEFINITIONS_PATH,
        "force_reindex_fields": force_reindex_fields,
        "reloaded_yaml_files": [item["path"] for item in selected_files] if selected_files else reloaded_yaml_files,
        "selected_files": selected_files or [],
        "reload_scope": reload_scope,
        "field_intent_total": len(registry.intents),
        "intent_summary_labels_path": str(intent_summary_service.labels_path),
    }


async def _load_query_router() -> QueryRouter:
    """在线程池中加载规则引擎，避免阻塞 FastAPI 事件循环。"""
    global _query_router
    if _query_router is None:
        logger.info("Query router background loading started")
        _query_router = await asyncio.to_thread(QueryRouter)
        logger.info("Query router background loading completed")
    return _query_router


async def _load_query_router_after_delay(delay_seconds: float) -> QueryRouter:
    """延迟预热，给 uvicorn 完成端口监听和健康检查响应留出时间。"""
    global _query_router_load_delayed
    try:
        await asyncio.sleep(delay_seconds)
        _query_router_load_delayed = False
        return await _load_query_router()
    except asyncio.CancelledError:
        _query_router_load_delayed = False
        raise


def start_background_query_router_load(delay_seconds: float = 0.0) -> None:
    """服务启动时后台预热规则引擎。"""
    global _query_router_load_task, _query_router_load_delayed
    if _query_router is not None:
        return
    if _query_router_load_task is None or _query_router_load_task.done():
        _query_router_load_delayed = delay_seconds > 0
        _query_router_load_task = asyncio.create_task(
            _load_query_router_after_delay(delay_seconds)
        )


def runtime_readiness_status() -> Dict[str, Any]:
    """返回当前 worker 的运行时配置/规则加载状态，用于健康检查。"""
    if _query_router is not None:
        if _runtime_reload_task is not None and not _runtime_reload_task.done():
            return {
                "ready": True,
                "status": "ready_reloading_previous_runtime_available",
                "serving_previous_runtime": True,
                **_runtime_reload_status(),
            }
        if _last_runtime_reload_error:
            return {
                "ready": False,
                "status": "reload_failed_previous_runtime_available",
                "serving_previous_runtime": True,
                "detail": _last_runtime_reload_error,
                **_runtime_reload_status(),
            }
        if _runtime_reload_marker_is_stale():
            return {
                "ready": True,
                "status": "ready_reload_pending_previous_runtime_available",
                "serving_previous_runtime": True,
                **_runtime_reload_status(),
            }
        return {
            "ready": True,
            "status": "ready",
            **_runtime_reload_status(),
        }

    if _last_runtime_reload_error:
        return {
            "ready": False,
            "status": "reload_failed",
            "detail": _last_runtime_reload_error,
            **_runtime_reload_status(),
        }

    if _runtime_reload_task is not None and not _runtime_reload_task.done():
        return {
            "ready": False,
            "status": "reloading",
            **_runtime_reload_status(),
        }

    if _runtime_reload_marker_is_stale():
        return {
            "ready": False,
            "status": "reload_pending",
            **_runtime_reload_status(),
        }

    if _query_router_load_task is None:
        return {
            "ready": False,
            "status": "not_started",
            **_runtime_reload_status(),
        }

    if not _query_router_load_task.done():
        return {
            "ready": False,
            "status": "loading",
            "delayed": _query_router_load_delayed,
            **_runtime_reload_status(),
        }

    exc = _query_router_load_task.exception()
    if exc is not None:
        return {
            "ready": False,
            "status": "load_failed",
            "detail": str(exc),
            **_runtime_reload_status(),
        }

    return {
        "ready": False,
        "status": "not_ready",
        **_runtime_reload_status(),
    }


async def check_parse_endpoint_ready() -> Dict[str, Any]:
    """通过本机端口探测核心解析接口是否可用。"""
    url = f"http://localhost:{settings.API_PORT}/api/v1/client_search_query_parse_no_encipher"
    payload = {
        "user_text": "手机号13800138000",
        "trace_id": "health-check",
        "user_id": "health-check",
    }
    try:
        timeout = httpx.Timeout(2.0, connect=0.5)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
        if response.status_code != 200:
            return {
                "ready": False,
                "status": "parse_endpoint_unavailable",
                "url": url,
                "http_status": response.status_code,
                "detail": response.text[:500],
            }
        body = response.json()
        if body.get("code") != 0:
            return {
                "ready": False,
                "status": "parse_endpoint_error",
                "url": url,
                "detail": body,
            }
        return {
            "ready": True,
            "status": "parse_endpoint_ready",
            "url": url,
        }
    except Exception as e:
        return {
            "ready": False,
            "status": "parse_endpoint_unreachable",
            "url": url,
            "detail": str(e),
        }


async def get_query_router() -> QueryRouter:
    """获取已加载的查询路由器；未加载时复用后台加载任务。"""
    global _query_router_load_task, _query_router_load_delayed
    _ensure_runtime_config_current()
    if _query_router is not None:
        return _query_router

    if _query_router_load_task is not None and _query_router_load_delayed:
        _query_router_load_task.cancel()
        _query_router_load_task = None
        _query_router_load_delayed = False

    if _query_router_load_task is None:
        logger.info("Query router not ready; loading before handling request")
        _query_router_load_task = asyncio.create_task(_load_query_router())

    try:
        return await _query_router_load_task
    except asyncio.CancelledError:
        # 任务被取消，检查是否有其他任务已经加载完成
        _query_router_load_task = None
        if _query_router is not None:
            return _query_router
        logger.info("Query router loading was cancelled; reloading for request")
        _query_router_load_task = asyncio.create_task(_load_query_router())
        return await _query_router_load_task
    except Exception:
        _query_router_load_task = None
        logger.exception("Query router loading failed")
        raise

def _build_debug_pattern_text(parsed) -> Optional[str]:
    """/parse 接口调试文本：L4 返回 prompt，其他层返回首个 pattern。"""
    if parsed.matched_level == 4:
        return parsed.prompt

    patterns = list(parsed.matched_patterns or [])
    for item in patterns:
        pattern = item.get("pattern")
        if pattern:
            return str(pattern)
    return None

def _get_parse_response_aes_key() -> bytes:
    raw_key = settings.PARSE_RESPONSE_AES_KEY
    if not raw_key:
        raise ValueError("PARSE_RESPONSE_AES_KEY 未配置")
    return raw_key.encode('utf-8')


def _log_session_id(request: ParseApiRequest) -> str:
    return request.session_id or "-"


def _promote_single_value_contains_to_match(conditions: List[Condition]) -> List[Condition]:
    """Parse 输出前：CONTAINS 只有一个值时按 MATCH 输出，保留多值 CONTAINS 的 IN 语义。"""
    normalized: List[Condition] = []
    for cond in conditions:
        if cond.operator != Operator.CONTAINS:
            normalized.append(cond)
            continue

        value = cond.value
        if isinstance(value, list):
            if len(value) != 1:
                normalized.append(cond)
                continue
            value = value[0]

        normalized.append(
            Condition(
                field=cond.field,
                operator=Operator.MATCH,
                value=value,
            )
        )
    return normalized


@router.post("/client_search_query_parse", summary="解析查询条件（不执行搜索）", response_model=ParseApiResponse)
async def client_search_query_parse(request: ParseApiRequest):
    """
    解析自然语言查询，返回结构化条件和逻辑关系，不执行实际搜索。
    遵循 AskBob 标准 Bot 接入协议，入参和出参均为标准包装格式。
    """
    with logger.contextualize(session_id=_log_session_id(request)):
        try:
            start_time = time.perf_counter()
            logger.info(
                f"Parse request received | trace_id={request.trace_id or '-'} "
                f"user_id={request.user_id or '-'} query={mask_for_log(request.user_text)}"
            )
            query_router = await get_query_router()
            parsed = await query_router.route_with_peeling(request.user_text)
            logger.info(f"query解析总耗时：{time.perf_counter() - start_time}")

            raw_conditions = query_router.normalize_date_condition_formats(parsed.conditions or [])
            intent_summary = build_intent_summary(raw_conditions, parsed.query_logic)
            conditions = filter_supported_conditions(raw_conditions)
            conditions = query_router.convert_age_to_birthday(conditions)
            robot_text = intent_summary.replace(' 00:00:00', '').replace(' 23:59:59', '')
            elapsed = int((time.perf_counter() - start_time) * 1000)

            extra_output_payload = {
                "query": request.user_text,
                "query_logic": parsed.query_logic,
                "conditions": [item.model_dump(mode="json") for item in conditions],
                "matched_level": parsed.matched_level,
                "rewritten_query": parsed.rewritten_query,
                "matched_patterns": _build_debug_pattern_text(parsed),
                "cost_times": elapsed,
                "confidence": parsed.confidence,
                "intent_summary": intent_summary,
            }

            if settings.ENABLE_PARSE_RESPONSE_AES:
                encrypted_payload = encrypt_parse_response_fields(
                    robot_text=robot_text,
                    extra_output_params=extra_output_payload,
                    key=_get_parse_response_aes_key(),
                )
                return ParseApiResponse(
                    code=0,
                    msg="操作成功",
                    data=ParseApiData(
                        robot_text=encrypted_payload["robot_text"],
                        end_flag=1,
                        trace_id=request.trace_id,
                        extra_output_params=encrypted_payload["extra_output_params"],
                    ),
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
                        matched_patterns=_build_debug_pattern_text(parsed),
                        cost_times=elapsed,
                        confidence=parsed.confidence,
                        intent_summary=intent_summary
                    ),
                ),
            )
        except Exception as e:
            logger.exception(f"Parse error: {e}")
            return ParseApiResponse(code=500, msg=str(e), data=None)


@router.post("/client_search_query_parse_no_encipher", summary="解析查询条件（不执行搜索）", response_model=ParseApiResponse)
async def client_search_query_parse_no_encipher(request: ParseApiRequest):
    """
    解析自然语言查询，返回结构化条件和逻辑关系，不执行实际搜索。
    遵循 AskBob 标准 Bot 接入协议，入参和出参均为标准包装格式。
    """
    with logger.contextualize(session_id=_log_session_id(request)):
        try:
            start_time = time.perf_counter()
            logger.info(
                f"Parse request received | trace_id={request.trace_id or '-'} "
                f"user_id={request.user_id or '-'} query={mask_for_log(request.user_text)}"
            )
            query_router = await get_query_router()
            parsed = await query_router.route_with_peeling(request.user_text)
            logger.info(f"query解析总耗时：{time.perf_counter() - start_time}")

            raw_conditions = query_router.normalize_date_condition_formats(parsed.conditions or [])
            intent_summary = build_intent_summary(raw_conditions, parsed.query_logic)
            conditions = filter_supported_conditions(raw_conditions)
            conditions = query_router.convert_age_to_birthday(conditions)
            robot_text = intent_summary.replace(' 00:00:00', '').replace(' 23:59:59', '')
            elapsed = int((time.perf_counter() - start_time) * 1000)

            # extra_output_payload = {
            #     "query": request.user_text,
            #     "query_logic": parsed.query_logic,
            #     "conditions": [item.model_dump(mode="json") for item in conditions],
            #     "matched_level": parsed.matched_level,
            #     "rewritten_query": parsed.rewritten_query,
            #     "matched_patterns": _build_debug_pattern_text(parsed),
            #     "cost_times": elapsed,
            #     "confidence": parsed.confidence,
            #     "intent_summary": intent_summary,
            # }
            #
            # if settings.ENABLE_PARSE_RESPONSE_AES:
            #     encrypted_payload = encrypt_parse_response_fields(
            #         robot_text=robot_text,
            #         extra_output_params=extra_output_payload,
            #         key=_get_parse_response_aes_key(),
            #     )
            #     return ParseApiResponse(
            #         code=0,
            #         msg="操作成功",
            #         data=ParseApiData(
            #             robot_text=encrypted_payload["robot_text"],
            #             end_flag=1,
            #             trace_id=request.trace_id,
            #             extra_output_params=encrypted_payload["extra_output_params"],
            #         ),
            #     )

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
                        matched_patterns=_build_debug_pattern_text(parsed),
                        cost_times=elapsed,
                        confidence=parsed.confidence,
                        intent_summary=intent_summary
                    ),
                ),
            )
        except Exception as e:
            logger.exception(f"Parse error: {e}")
            return ParseApiResponse(code=500, msg=str(e), data=None)


@router.post("/reload_config", summary="热更新运行时配置")
async def reload_config(request: Optional[ConfigReloadRequest] = None):
    """
    重新加载当前环境 YAML 配置，并同步刷新运行时组件。

    默认按最新内容重载全部 YAML 配置，但不重建字段意图 ES 索引。
    如需更新 RAG ES 索引，请手动调用 /api/v1/fields/reindex。
    """
    try:
        request = request or ConfigReloadRequest()
        started = _schedule_runtime_reload(
            force_reindex_fields=request.force_reindex_fields,
            publish_marker=True,
        )
        if request.wait and _runtime_reload_task is not None:
            await _runtime_reload_task
            if _last_runtime_reload_error:
                raise RuntimeError(_last_runtime_reload_error)

        return {
            "success": True,
            "message": "配置热更新已提交后台执行" if not request.wait else "配置热更新完成",
            "started": started,
            "force_reindex_fields": request.force_reindex_fields,
            **_runtime_reload_status(),
            "reload_marker": str(_runtime_reload_marker_path()),
        }
    except Exception as e:
        logger.error(f"Config reload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config/reload/files", summary="查看支持按文件热刷新的配置")
async def list_reloadable_config_files():
    """返回可用于 /config/reload/files 的文件别名、路径与刷新范围。"""
    return {
        "success": True,
        "files": _list_reloadable_config_files(),
    }


@router.post("/config/reload/files", summary="按文件热更新运行时配置")
async def reload_config_files(request: SelectiveConfigReloadRequest):
    """
    按配置文件选择性热刷新。

    files 支持：
    - alias：如 field_definitions、enhanced_rules、value_mappings、intent_summary、field_mapping、field_enums
    - 文件名：如 field_definitions_args.yaml
    - 绝对路径：必须命中白名单中的配置文件
    - all：等同全量刷新
    """
    try:
        selected_files, reload_scope = _resolve_reload_file_selection(request.files)
        started = _schedule_runtime_reload(
            force_reindex_fields=request.force_reindex_fields and reload_scope == "full",
            publish_marker=True,
            selected_files=selected_files,
            reload_scope=reload_scope,
        )
        if request.wait and _runtime_reload_task is not None:
            await _runtime_reload_task
            if _last_runtime_reload_error:
                raise RuntimeError(_last_runtime_reload_error)

        return {
            "success": True,
            "message": "文件热更新已提交后台执行" if not request.wait else "文件热更新完成",
            "started": started,
            "selected_files": selected_files,
            "reload_scope": reload_scope,
            "force_reindex_fields": request.force_reindex_fields and reload_scope == "full",
            **_runtime_reload_status(),
            "reload_marker": str(_runtime_reload_marker_path()),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Selective config reload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fields/reindex", summary="重建字段意图 ES 索引")
async def reindex_fields():
    """
    强制重建 ES 字段意图索引（知识库更新后调用）

    重新加载 field_definitions.yaml 并写入 ES，全局单例同步刷新。
    """
    try:
        started = _schedule_runtime_reload(
            force_reindex_fields=True,
            publish_marker=True,
        )
        return {
            "success": True,
            "started": started,
            "message": "索引重建已提交后台执行",
            **_runtime_reload_status(),
            "reload_marker": str(_runtime_reload_marker_path()),
        }
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
        _ensure_runtime_config_current()
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
