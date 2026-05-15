import asyncio

from src.main.python.steps.level2_enhanced_matcher import Level2EnhancedMatcher


def test_level2_claim_case_no_mc_format_variants():
    matcher = Level2EnhancedMatcher()

    cases = [
        ("理赔案件号为MC20240509000001的客户", "MC20240509000001"),
        ("MC20240509000002的客户", "MC20240509000002"),
        ("理赔案件号MC2024开头的客户", "MC2024"),
        ("理赔案件号尾号000001的客户", "000001"),
        ("000001尾号的理赔案件号", "000001"),
    ]

    for query, expected_value in cases:
        conditions = asyncio.run(matcher.match(query))
        assert ("polNoInfo.claimdatainfo.claimno", "MATCH", expected_value) in [
            (condition.field, condition.operator.value, condition.value)
            for condition in conditions
        ], query
