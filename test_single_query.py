from app.core.level2_enhanced_matcher import Level2EnhancedMatcher
from loguru import logger
import sys
import asyncio

logger.remove()
logger.add(sys.stderr, level="INFO")

matcher = Level2EnhancedMatcher("config/enhanced_rules.yaml")

test_queries = [
    "45岁保费10万以上",
    "50岁年缴保费20万以上",
    "30岁保费5000以上"
]

async def test():
    for query in test_queries:
        print(f"\n{'='*60}")
        print(f"测试查询: {query}")
        print('='*60)
        conditions, remaining_text, has_logic = await matcher.match(query)
        print(f"匹配结果: {len(conditions)} 个条件")
        for cond in conditions:
            print(f"  - {cond}")
        if remaining_text:
            print(f"剩余文本: {remaining_text}")

asyncio.run(test())
