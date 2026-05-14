"""
Level 1 规则引擎测试脚本
"""
import asyncio
import sys
import os

from sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.level1_rule_engine import Level1RuleEngine


TEST_CASES = [
    # (查询文本, 期望命中的 field 列表)
    ("13812345678",                          ["mobile_phone"]),
    ("查询手机号13912345678的客户",            ["mobile_phone"]),
    ("110101199001011234",                   ["id_card"]),
    ("身份证号110101199001011234的客户",       ["id_card"]),
    ("P966073446746215",                    ["policy_no"]),
    ("保单号P966073446746215",               ["policy_no"]),
    ("C335906420260306",                    ["customer_id"]),
    ("客户号C335906420260306",               ["customer_id"]),
    ("张三",                                ["name"]),
    ("查找张三的保单",                        ["name"]),
    # 多实体
    ("张三的手机号13812345678",               ["name", "mobile_phone"]),
    # 无实体
    ("45岁以上已婚客户",                      []),
    ("高收入女性客户",                        []),
]


async def run_tests():
    engine = Level1RuleEngine()
    passed = 0
    failed = 0

    print(f"{'查询':<30} {'期望字段':<30} {'实际字段':<30} {'结果'}")
    print("-" * 100)

    for query, expected_fields in TEST_CASES:
        conditions = await engine.extract(query)
        actual_fields = [c.field for c in conditions]

        ok = sorted(actual_fields) == sorted(expected_fields)
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1

        print(f"{query:<30} {str(expected_fields):<30} {str(actual_fields):<30} {status}")
        if ok and conditions:
            for c in conditions:
                val = c.value
                print(f"  └─ field={c.field}, operator={c.operator.value}, value={val}")

    print("-" * 100)
    print(f"共 {len(TEST_CASES)} 个用例，通过 {passed}，失败 {failed}")
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
