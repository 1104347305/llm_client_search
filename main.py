"""
FastAPI 应用主入口
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger
import sys
import os
import httpx
import routes as routes_module
from routes import router
from config.settings import settings

# 配置日志
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO"
)
logger.add(
    "logs/app.log",
    rotation="500 MB",
    retention="10 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
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
async def startup_reload_runtime_config():
    """服务启动时自动重载配置并刷新运行时组件。"""
    result = routes_module._reload_runtime_components(force_reindex_fields=True)
    logger.info(
        "Startup config reload completed | "
        f"env={result['env']} "
        f"config={result['config_path']} "
        f"field_intents={result['field_intent_total']}"
    )


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
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting server on {settings.API_HOST}:{settings.API_PORT}")
    uvicorn.run(
        "main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.API_RELOAD
    )
