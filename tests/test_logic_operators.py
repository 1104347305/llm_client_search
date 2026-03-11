"""测试逻辑运算符支持"""
import sys
sys.path.insert(0, '/Users/mickey/project/PA-ALG/agentic_client_search_v3')

from app.core.query_router import QueryRouter

router = QueryRouter()

test_queries = [
    "未配置养老险和重疾险的客户",
    "未配置养老险或重疾险的客户",
    "35岁已婚、有子女、未配置重疾险的客户",
    "5岁以上、已婚、有子女、未配置养老险和居家养老的客户",
]

for query in test_queries:
    print(f"\n查询: {query}")
    print("=" * 60)
    result = router.route_with_peeling(query)
    print(f"匹配层级: L{result.matched_level}")
    print(f"逻辑类型: {result.query_logic}")
    print(f"条件数量: {len(result.conditions)}")
    print(f"逻辑树: {result.logic_tree}")
    print(f"条件列表:")
    for i, cond in enumerate(result.conditions, 1):
        print(f"  {i}. {cond.field} {cond.operator} {cond.value}")
