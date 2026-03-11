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
from app.api.routes import router
from config.settings import settings

# AgentOS 本地地址（服务器内部通信，无跨域问题）
_AGENT_OS_BASE = "http://localhost:7777"

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


@app.get("/chat")
async def chat_ui():
    """前端聊天界面"""
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "chat.html")
    return FileResponse(path, media_type="text/html")


@app.api_route("/agent/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def agent_proxy(path: str, request: Request):
    """反向代理：将 /agent/* 转发到 AgentOS（localhost:7777），解决跨域问题"""
    url = f"{_AGENT_OS_BASE}/{path}"
    body = await request.body()
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in ("host", "content-length")}

    async def _iter(resp: httpx.Response):
        async for chunk in resp.aiter_bytes(chunk_size=512):
            yield chunk

    client = httpx.AsyncClient(timeout=120)
    resp = await client.send(
        client.build_request(
            method=request.method,
            url=url,
            headers=headers,
            params=dict(request.query_params),
            content=body,
        ),
        stream=True,
    )
    content_type = resp.headers.get("content-type", "application/json")
    extra = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"} \
        if "text/event-stream" in content_type else {}
    return StreamingResponse(
        _iter(resp),
        status_code=resp.status_code,
        media_type=content_type,
        headers=extra,
        background=None,
    )


if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting server on {settings.API_HOST}:{settings.API_PORT}")
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.API_RELOAD
    )
