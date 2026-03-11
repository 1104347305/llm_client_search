"""
博查(Bocha)互联网搜索工具

为 Agent (Layer 4) 提供互联网搜索能力，用于获取实时信息（当前日期、节假日等）。

使用方式：
    from app.tools.bocha_search_tool import bocha_web_search
"""
from typing import Dict, Any
import httpx
from loguru import logger
from config.settings import settings


def bocha_web_search(query: str) -> Dict[str, Any]:
    """
    使用博查 API 搜索互联网信息

    使用场景：
    - 获取当前日期、节假日等时间相关信息
    - 查询保险产品特点和适用人群
    - 获取行业知识和市场信息

    Args:
        query: 搜索关键词

    Returns:
        搜索结果，包含 results 列表和 summary
    """
    logger.info(f"博查搜索: {query}")

    try:
        # 检查是否配置了 Bocha API
        if not hasattr(settings, 'BOCHA_API_KEY') or not settings.BOCHA_API_KEY:
            logger.warning("Bocha API key not configured, skipping search")
            return {"error": "Bocha API not configured", "results": [], "summary": "搜索功能未配置"}

        headers = {
            "Authorization": f"Bearer {settings.BOCHA_API_KEY}",
            "Content-Type": "application/json",
        }

        payload = {
            "query": query,
            "summary": True,
            "freshness": "noLimit",
            "count": 5,
        }

        bocha_url = getattr(settings, 'BOCHA_API_URL', 'https://api.bochaai.com/v1/web-search')
        timeout = getattr(settings, 'BOCHA_TIMEOUT', 30)

        with httpx.Client(timeout=float(timeout)) as client:
            response = client.post(bocha_url, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()

        results_count = len(result.get("results", []))
        logger.info(f"博查搜索完成: {query}, 结果数: {results_count}")

        return result

    except httpx.HTTPError as e:
        logger.error(f"博查搜索 HTTP 错误: {query}, error: {e}")
        return {"error": str(e), "results": [], "summary": f"搜索失败: {e}"}
    except Exception as e:
        logger.error(f"博查搜索异常: {query}, error: {e}")
        return {"error": str(e), "results": [], "summary": f"搜索失败: {e}"}
