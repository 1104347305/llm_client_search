#!/usr/bin/env python3
"""
测试L2规则优化效果
"""
import sys
import asyncio
sys.path.append('/Users/mickey/project/PA-ALG/agentic_client_search_v4')

from app.core.level2_enhanced_matcher import Level2EnhancedMatcher

# 初始化L2匹配器
matcher = Level2EnhancedMatcher()

# 测试用例
test_cases = [
    # 测试"娃"同义词
    {
        "query": "有娃但没配置重疾险的客户",
        "expected_fields": ["family_members.relationship", "held_product_category"],
        "description": "测试'娃'映射到'子女'"
    },
    {
        "query": "35岁有小朋友友还没配置重疾险的客户",
        "expected_fields": ["age", "family_members.relationship", "held_product_category"],
        "description": "测试'小朋友'映射"
    },
    # 测试父母年龄
    {
        "query": "父母70岁以上的客户",
        "expected_fields": ["family_members.age", "family_members.relationship"],
        "description": "测试父母年龄-以上规则"
    },
    # 测试"家里"
    {
        "query": "家里有未成年子女的客户",
        "expected_fields": ["family_members.relationship", "family_members.age"],
        "description": "测试'家里有'模式"
    },
    {
        "query": "家里有未成年子女，没有买学平险",
        "expected_fields": ["family_members.relationship", "family_members.age", "held_cross_sell_category"],
        "description": "测试'家里有'+产品组合"
    },
    # 已有规则验证
    {
        "query": "30多岁客户",
        "expected_fields": ["age"],
        "description": "验证'多岁'规则"
    },
    {
        "query": "未配置重疾险的客户",
        "expected_fields": ["held_product_category"],
        "description": "验证'未配置'规则"
    },
    {
        "query": "A1有哪些",
        "expected_fields": ["customer_value"],
        "description": "验证客户价值简写"
    },
]

print("=" * 80)
print("L2规则优化测试")
print("=" * 80)

success_count = 0
fail_count = 0

async def run_tests():
    global success_count, fail_count

    for i, test in enumerate(test_cases, 1):
        query = test["query"]
        expected = test["expected_fields"]
        desc = test["description"]

        print(f"\n测试 {i}: {desc}")
        print(f"查询: {query}")
        print(f"期望字段: {expected}")

        # 执行匹配
        result = await matcher.match(query)

        if result:
            conditions, remaining_text, has_residual = result
            matched_fields = [cond.field for cond in conditions]
            print(f"匹配字段: {matched_fields}")
            print(f"条件数量: {len(conditions)}")
            print(f"剩余文本: '{remaining_text}'")

            # 检查是否包含所有期望字段
            all_matched = all(field in matched_fields for field in expected)

            if all_matched:
                print("✅ 通过")
                success_count += 1
            else:
                missing = [f for f in expected if f not in matched_fields]
                print(f"❌ 失败 - 缺少字段: {missing}")
                fail_count += 1
        else:
            print(f"匹配结果: 无匹配")
            print("❌ 失败 - 未匹配到任何规则")
            fail_count += 1

    print("\n" + "=" * 80)
    print(f"测试总结: 通过 {success_count}/{len(test_cases)}, 失败 {fail_count}/{len(test_cases)}")
    print("=" * 80)

# 运行异步测试
asyncio.run(run_tests())
