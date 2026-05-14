from core.level2_enhanced_matcher import Level2EnhancedMatcher
from loguru import logger
import sys
import asyncio

logger.remove()
logger.add(sys.stderr, level="INFO")

matcher = Level2EnhancedMatcher("config/enhanced_rules.yaml")


def test_load_config_keeps_rules_marked_is_supported_false(tmp_path):
    config_path = tmp_path / "enhanced_rules.yaml"
    config_path.write_text(
        """
pattern_vars: {}
rules:
  - name: "启用规则"
    patterns:
      - "启用"
    field: "clientSex"
    operator: "MATCH"
    value_type: "static"
    value: "男"
  - name: "停用规则"
    is_supported: false
    patterns:
      - "停用"
    field: "clientSex"
    operator: "MATCH"
    value_type: "static"
    value: "女"
composite_rules:
  - name: "启用组合"
    patterns:
      - "【启用规则】"
  - name: "停用组合"
    is_supported: false
    patterns:
      - "【停用规则】"
        """.strip(),
        encoding="utf-8",
    )

    matcher = Level2EnhancedMatcher(str(config_path))

    assert {rule["name"] for rule in matcher.rules} == {"启用规则", "停用规则"}
    assert {rule["name"] for rule in matcher.composite_rules} == {"启用组合", "停用组合"}

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
