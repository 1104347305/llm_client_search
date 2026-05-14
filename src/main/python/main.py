"""
FastAPI 应用主入口
"""
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger
import sys
import os
import time

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parents[3]
for path in (str(PACKAGE_ROOT), str(PROJECT_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from src.main.python.api import client_search_query_parse_post as routes_module
from src.main.python.api.client_search_query_parse_post import router
from src.main.python.config.settings import settings

# 配置日志
logger.remove()
logger.configure(extra={"session_id": "-"})
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | session_id={extra[session_id]} | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO"
)
logger.add(
    "logs/app.log",
    rotation="500 MB",
    retention="10 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | session_id={extra[session_id]} | {name}:{function}:{line} - {message}",
    level="DEBUG"
)

# 创建 FastAPI 应用
app = FastAPI(
    title="Agentic Client Search API",
    description="智能客户搜索系统 - 四层分流漏斗架构 V4",
    version="4.0.0"
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(router, prefix="/api/v1", tags=["search"])


@app.on_event("startup")
async def startup_background_load_query_router():
    """服务启动后后台预热规则引擎。"""
    startTime = time.perf_counter()
    routes_module.start_background_query_router_load(delay_seconds=0.0)
    routes_module.start_runtime_reload_marker_watcher()
    logger.info(f"预加载耗时：{time.perf_counter() - startTime}")


@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "Agentic Client Search API",
        "version": "4.0.0",
        "status": "running",
        "description": "V4: 使用 Agno Agent 替换 LLM Parser"
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    readiness = routes_module.runtime_readiness_status()
    if not readiness["ready"]:
        raise HTTPException(status_code=503, detail=readiness)

    endpoint_readiness = await routes_module.check_parse_endpoint_ready()
    if not endpoint_readiness["ready"]:
        raise HTTPException(
            status_code=503,
            detail={
                "ready": False,
                "status": "parse_endpoint_check_failed",
                "readiness": readiness,
                "endpoint_readiness": endpoint_readiness,
            },
        )
    return {
        "status": "healthy",
        "readiness": readiness,
        "endpoint_readiness": endpoint_readiness,
    }


if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting server on {settings.API_HOST}:{settings.API_PORT}")
    uvicorn.run(
        "src.main.python.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.API_RELOAD
    )
