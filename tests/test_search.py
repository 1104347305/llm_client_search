"""
测试脚本
"""
import asyncio
import httpx
import pytest
from loguru import logger


@pytest.mark.asyncio
async def test_structured_search():
    """测试结构化搜索"""
    logger.info("Testing structured search...")

    payload = {
        "header": {
            "agent_id": "test_agent",
            "page": 1,
            "size": 10
        },
        "query_logic": "AND",
        "conditions": [
            {
                "field": "age",
                "operator": "GTE",
                "value": 30
            },
            {
                "field": "gender",
                "operator": "MATCH",
                "value": "男"
            }
        ]
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/api/v1/search/structured",
            json=payload,
            timeout=30.0
        )
        result = response.json()
        logger.info(f"Structured search result: {result}")
        return result


@pytest.mark.asyncio
async def test_natural_language_search():
    """测试自然语言搜索"""
    logger.info("Testing natural language search...")

    test_queries = [
        "查找30岁以上的男性客户",
        "找出购买了养老险且年收入50万以上的客户",
        "查询手机号13800138000的客户",
        "找出有子女且配置了重疾险的客户",
        "查找未配置医疗险的高净值客户"
    ]

    async with httpx.AsyncClient() as client:
        for query in test_queries:
            logger.info(f"\nTesting query: {query}")
            payload = {
                "query": query,
                "agent_id": "test_agent",
                "page": 1,
                "size": 10
            }

            try:
                response = await client.post(
                    "http://localhost:8000/api/v1/search/natural",
                    json=payload,
                    timeout=30.0
                )
                result = response.json()
                logger.info(f"Result: matched_level={result.get('matched_level')}, "
                           f"confidence={result.get('confidence')}, "
                           f"conditions_count={len(result.get('data', {}).get('conditions', []))}")
            except Exception as e:
                logger.error(f"Error: {e}")


async def main():
    """主测试函数"""
    logger.info("Starting tests...")

    # 测试结构化搜索
    await test_structured_search()

    # 测试自然语言搜索
    await test_natural_language_search()

    logger.info("Tests completed!")


if __name__ == "__main__":
    asyncio.run(main())
