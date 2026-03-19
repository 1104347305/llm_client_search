from app.core.level2_enhanced_matcher import Level2EnhancedMatcher
from loguru import logger
import sys
import asyncio

logger.remove()
logger.add(sys.stderr, level="INFO")

matcher = Level2EnhancedMatcher("config/enhanced_rules.yaml")

test_queries = [
    "45岁女性投保保费在30万以上的客户",
    "45岁女性保费10万以上",
    "总保费90万以上",
    "查保费一万以上有哪些",
    "查30多岁保费超过5000都有谁"
]

async def test():
    for query in test_queries:
        print(f"\n{'='*60}")
        print(f"测试查询: {query}")
        print('='*60)
        conditions, remaining_text, has_logic = await matcher.match(query)
        if conditions:
            print(f"✓ 匹配成功: {len(conditions)} 个条件")
            for cond in conditions:
                print(f"  - {cond}")
        else:
            print(f"✗ 未匹配")
        if remaining_text:
            print(f"剩余文本: {remaining_text}")

asyncio.run(test())
