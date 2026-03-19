from app.core.level2_enhanced_matcher import Level2EnhancedMatcher
from loguru import logger
import sys
import asyncio

logger.remove()
logger.add(sys.stderr, level="INFO")

matcher = Level2EnhancedMatcher("config/enhanced_rules.yaml")

test_queries = [
    "所有万能险客户名单",
    "有生存金未领取",
    "未领取生存金的人",
    "被保人手机号为133XXXXXXxxx",
    "45岁以上的博士",
    "未配置养老保险的人员名单",
    "找45岁以上没有配置保险的",
    "把近一个月新添加的客户查询出来",
    "搜索已配置万能险的客户",
    "查医疗险客户",
    "帮我找A1有哪些客户",
    "谁是A1客户",
    "查保额超过10万的人",
    "找40岁左右保额10万以上名单",
    "40岁左右黄金VIP有哪些人"
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