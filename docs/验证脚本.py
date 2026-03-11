"""
项目功能验证脚本
测试四层漏斗架构的各个层级
"""
from app.core.query_router import QueryRouter
from loguru import logger
import sys

# 配置日志
logger.remove()
logger.add(sys.stdout, level="INFO")


def test_level1():
    """测试 Level 1: 规则引擎"""
    print("\n" + "="*60)
    print("测试 Level 1: 规则引擎（确定性实体提取）")
    print("="*60)

    router = QueryRouter()
    test_cases = [
        "手机号13800138000的客户",
        "客户号C123456",
        "姓名张三的客户",
    ]

    for query in test_cases:
        result = router.route_with_peeling(query)
        print(f"\n查询: {query}")
        print(f"  匹配层级: Level {result.matched_level}")
        print(f"  条件数: {len(result.conditions)}")
        print(f"  置信度: {result.confidence}")
        if result.conditions:
            for cond in result.conditions:
                print(f"    - {cond.field} {cond.operator.value} {cond.value}")


def test_level2():
    """测试 Level 2: 增强模板匹配"""
    print("\n" + "="*60)
    print("测试 Level 2: 增强模板匹配（模式识别）")
    print("="*60)

    router = QueryRouter()
    test_cases = [
        "45岁以上的客户",
        "30-40岁的客户",
        "年收入50万以上的客户",
        "已婚的客户",
    ]

    for query in test_cases:
        result = router.route_with_peeling(query)
        print(f"\n查询: {query}")
        print(f"  匹配层级: Level {result.matched_level}")
        print(f"  条件数: {len(result.conditions)}")
        print(f"  置信度: {result.confidence}")
        if result.conditions:
            for cond in result.conditions:
                print(f"    - {cond.field} {cond.operator.value} {cond.value}")


def test_level4():
    """测试 Level 4: LLM 解析器（需要 API 配置）"""
    print("\n" + "="*60)
    print("测试 Level 4: LLM 解析器（复杂查询兜底）")
    print("="*60)

    router = QueryRouter()
    test_cases = [
        "45岁以上且已婚的客户",  # 包含逻辑词，会触发 LLM
        "高价值潜力客户",  # 语义推断
    ]

    for query in test_cases:
        print(f"\n查询: {query}")
        print("  注意: 此查询需要 LLM API 配置才能正常工作")
        print("  如果 API 未配置，将返回空结果")
        try:
            result = router.route_with_peeling(query)
            print(f"  匹配层级: Level {result.matched_level}")
            print(f"  条件数: {len(result.conditions)}")
            print(f"  置信度: {result.confidence}")
            if result.conditions:
                for cond in result.conditions:
                    print(f"    - {cond.field} {cond.operator.value} {cond.value}")
        except Exception as e:
            print(f"  错误: {e}")


def test_combined():
    """测试组合查询"""
    print("\n" + "="*60)
    print("测试组合查询（多层级协同）")
    print("="*60)

    router = QueryRouter()
    test_cases = [
        "手机号13800138000且45岁以上的客户",  # L1 + L2
        "姓名张三且年收入50万以上的客户",  # L1 + L2
    ]

    for query in test_cases:
        result = router.route_with_peeling(query)
        print(f"\n查询: {query}")
        print(f"  匹配层级: Level {result.matched_level}")
        print(f"  条件数: {len(result.conditions)}")
        print(f"  置信度: {result.confidence}")
        if result.conditions:
            for cond in result.conditions:
                print(f"    - {cond.field} {cond.operator.value} {cond.value}")


def main():
    """主函数"""
    print("\n" + "="*60)
    print("Agentic Client Search V4 - 功能验证")
    print("="*60)

    try:
        test_level1()
        test_level2()
        test_combined()
        test_level4()

        print("\n" + "="*60)
        print("验证完成！")
        print("="*60)
        print("\n说明:")
        print("  - Level 1/2 测试应该正常工作")
        print("  - Level 3 需要 Redis 配置")
        print("  - Level 4 需要 LLM API 配置（DashScope）")
        print("  - 完整功能需要启动 FastAPI 服务: python app/main.py")

    except Exception as e:
        print(f"\n验证过程中出现错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
