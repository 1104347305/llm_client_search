"""
测试 Level2 模板匹配器的配置化规则
"""
from app.core.level2_template_matcher import Level2TemplateMatcher
from loguru import logger

def test_level2_matcher():
    """测试配置化的规则匹配"""
    matcher = Level2TemplateMatcher()

    # 测试用例
    test_cases = [
        "找30岁以上的男客户",
        "二十几岁的女性客户",
        "本科学历的客户",
        "已婚客户",
        "A1类客户",
        "高温客户",
        "医生职业的客户",
        "黄金V1客户",
        "平安VIP客户",
    ]

    logger.info(f"规则数量: {matcher.get_rules_count()}")
    logger.info(f"调试信息: {matcher.debug_info()}")

    for query in test_cases:
        logger.info(f"\n{'='*60}")
        logger.info(f"查询: {query}")
        conditions, remaining, has_residual = matcher.match(query)

        logger.info(f"提取的条件数: {len(conditions)}")
        for i, cond in enumerate(conditions, 1):
            logger.info(f"  条件{i}: field={cond.field}, operator={cond.operator}, value={cond.value}")

        logger.info(f"剩余文本: '{remaining}'")
        logger.info(f"有残留: {has_residual}")

if __name__ == "__main__":
    test_level2_matcher()
