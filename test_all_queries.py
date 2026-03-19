#!/usr/bin/env python3
"""
测试所有48条查询的L2匹配效果
"""
import sys
import asyncio
sys.path.append('/Users/mickey/project/PA-ALG/agentic_client_search_v4')

from app.core.level2_enhanced_matcher import Level2EnhancedMatcher

# 初始化L2匹配器
matcher = Level2EnhancedMatcher()

# 所有测试查询
test_queries = [
    "35岁有小朋友友还没配置重疾险的客户",
    "所有万能险客户名单",
    "被保人手机号为133XXXXXXxxx",
    "未配置养老保险的人员名单",
    "找45岁以上没有配置保险的",
    "帮我找A1有哪些客户",
    "给我看看50岁A1医疗险客户",
    "帮我找A类低温名单",
    "给我看看意外险名单",
    "帮我查30多岁客户",
    "A1意外险客户",
    "帮我查40岁左右车险客户",
    "找40岁左右有哪些人",
    "A1有哪些",
    "给我看看40岁低温分红险客户",
    "查50岁以上的人",
    "姓张，45岁左右的客户",
    "姓张，购买过盛世金越的客户",
    "30-40岁的已婚有娃姓女性客户",
    "有重疾险和医疗险的客户",
    "未配置重疾险的客户",
    "有娃但没配置重疾险的客户",
    "有车的，未配置百万医疗的客户",
    "未领取过生存金的客户",
    "男性年交保费30万以上",
    "年交保费20万以上但缴费期满的客户",
    "下个月生日的低温客户",
    "客户价值B以上的客户",
    "中温及以上的有车客户",
    "本科及以上的高温客户",
    "做老师的客户",
    "已婚但未配置养老险的高温客户",
    "购买了车险且客户价值为A1的客户",
    "中温及以上年收入超过20万的客户",
    "客户价值B以上，且家庭成员中有未成年子女的客户",
    "父母70岁以上的客户",
    "35-35岁，已婚有娃的男性客户",
    "查找学历是本科以上的客户",
    "家里有未成年子女的客户",
    "已投保e生保的客户",
    "哪些客户生存金还没有领取",
    "买了车险，但没有购买意外险的客户",
    "家里有未成年子女，没有买学平险",
    "找个客户是女性、30多岁、买过年金险的",
    "查有没有年缴保费超过1万，产品总保额超过50万的客户",
    "女性客户、30多岁、买过年金险的",
    "找个客户是男性、年龄在50岁左右、买过终身寿险的",
    "客户是寿险VIP，男性，年龄大于50岁",
]

async def run_tests():
    print("=" * 100)
    print("L2规则全量测试 - 48条查询")
    print("=" * 100)

    matched_count = 0
    partial_count = 0
    failed_count = 0

    for i, query in enumerate(test_queries, 1):
        print(f"\n[{i}/48] {query}")

        try:
            result = await matcher.match(query)

            if result:
                conditions, remaining_text, has_residual = result

                if conditions:
                    matched_fields = [cond.field for cond in conditions]
                    print(f"  ✅ 匹配成功: {len(conditions)}个条件")
                    print(f"     字段: {', '.join(matched_fields)}")

                    if remaining_text.strip():
                        print(f"     ⚠️  剩余文本: '{remaining_text}'")
                        partial_count += 1
                    else:
                        matched_count += 1

                    # 显示条件详情
                    for cond in conditions:
                        if hasattr(cond, 'operator') and hasattr(cond, 'value'):
                            print(f"       - {cond.field} {cond.operator} {cond.value}")
                else:
                    print(f"  ❌ 无匹配条件")
                    print(f"     剩余文本: '{remaining_text}'")
                    failed_count += 1
            else:
                print(f"  ❌ 完全未匹配")
                failed_count += 1

        except Exception as e:
            print(f"  ❌ 错误: {str(e)}")
            failed_count += 1

    print("\n" + "=" * 100)
    print("测试总结")
    print("=" * 100)
    print(f"完全匹配: {matched_count}/48 ({matched_count/48*100:.1f}%)")
    print(f"部分匹配: {partial_count}/48 ({partial_count/48*100:.1f}%)")
    print(f"未匹配:   {failed_count}/48 ({failed_count/48*100:.1f}%)")
    print("=" * 100)

# 运行异步测试
asyncio.run(run_tests())
