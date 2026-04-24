import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.field_registry import FieldRegistry


def test_format_prompt_section_supports_multi_condition_examples():
    registry = FieldRegistry.__new__(FieldRegistry)
    prompt = registry.format_prompt_section([
        {
            "field": "familyClientAge",
            "operator": "RANGE",
            "value_type": "numeric",
            "notes": "出现关系词时应同时输出familyRelation条件",
            "examples": [
                {
                    "query": "子女5到10岁的客户",
                    "output": {
                        "query_logic": "AND",
                        "conditions": [
                            {"field": "familyRelation", "operator": "CONTAINS", "value": "子女"},
                            {"field": "familyClientAge", "operator": "RANGE", "value": {"min": 5, "max": 10}},
                        ],
                    },
                }
            ],
        }
    ])

    assert '"query_logic": "AND"' in prompt
    assert '"field": "familyRelation"' in prompt
    assert '"field": "familyClientAge"' in prompt
    assert '"min": 5' in prompt
    assert '"max": 10' in prompt


def test_format_prompt_section_supports_multiple_family_attributes_examples():
    registry = FieldRegistry.__new__(FieldRegistry)
    prompt = registry.format_prompt_section([
        {
            "field": "familyClientName",
            "operator": "NESTED_MATCH",
            "value_type": "extract",
            "examples": [
                {
                    "query": "子女叫张三的客户",
                    "output": {
                        "query_logic": "AND",
                        "conditions": [
                            {"field": "familyRelation", "operator": "CONTAINS", "value": "子女"},
                            {"field": "familyClientName", "operator": "NESTED_MATCH", "value": "张三"},
                        ],
                    },
                }
            ],
        }
    ])

    assert '"field": "familyRelation"' in prompt
    assert '"field": "familyClientName"' in prompt
    assert '"value": "张三"' in prompt


def test_format_prompt_section_preserves_multiple_family_synonym_examples():
    registry = FieldRegistry.__new__(FieldRegistry)
    prompt = registry.format_prompt_section([
        {
            "field": "familyClientSex",
            "operator": "NESTED_MATCH",
            "value_type": "enum",
            "examples": [
                {
                    "query": "爸妈是女性的客户",
                    "output": {
                        "query_logic": "AND",
                        "conditions": [
                            {"field": "familyRelation", "operator": "CONTAINS", "value": "父母"},
                            {"field": "familyClientSex", "operator": "NESTED_MATCH", "value": "女"},
                        ],
                    },
                },
                {
                    "query": "爱人1988年出生的客户",
                    "output": {
                        "query_logic": "AND",
                        "conditions": [
                            {"field": "familyRelation", "operator": "CONTAINS", "value": "配偶"},
                            {
                                "field": "familyClientBirthday",
                                "operator": "RANGE",
                                "value": {"min": "1988-01-01 00:00:00", "max": "1988-12-31 00:00:00"},
                            },
                        ],
                    },
                },
            ],
        }
    ])

    assert '爸妈是女性的客户' in prompt
    assert '爱人1988年出生的客户' in prompt
    assert '"value": "父母"' in prompt
    assert '"value": "配偶"' in prompt
    assert '1988-01-01 00:00:00' not in prompt
    assert '1988-12-31 00:00:00' not in prompt
    assert '"min": "1988-01-01"' in prompt
    assert '"max": "1988-12-31"' in prompt


def test_format_prompt_section_includes_description_and_negative_examples():
    registry = FieldRegistry.__new__(FieldRegistry)
    prompt = registry.format_prompt_section([
        {
            "field": "clientMobile",
            "operator": "MATCH",
            "value_type": "extract",
            "description": "仅表示客户本人手机号，不表示被保人、投保人手机号",
            "notes": "只有查询对象明确是客户本人，或未指明对象仅说手机号时，才可映射到该字段",
            "examples": [
                {
                    "query": "客户手机号为133",
                    "output": {"field": "clientMobile", "operator": "MATCH", "value": "133"},
                }
            ],
            "negative_examples": [
                {
                    "query": "被保人手机号为133XXXXXXxxx",
                    "reason": "当前没有被保人手机号字段，不能映射到 clientMobile",
                }
            ],
        }
    ])

    assert "定义: 仅表示客户本人手机号" in prompt
    assert "反例: \"被保人手机号为133XXXXXXxxx\" → 不输出该字段" in prompt
    assert "原因: 当前没有被保人手机号字段" in prompt


def test_format_prompt_section_preserves_family_negative_examples():
    registry = FieldRegistry.__new__(FieldRegistry)
    prompt = registry.format_prompt_section([
        {
            "field": "familyClientName",
            "operator": "NESTED_MATCH",
            "value_type": "extract",
            "description": "表示家庭成员姓名，不表示客户本人姓名；出现关系词时应与 familyRelation 组合",
            "negative_examples": [
                {
                    "query": "叫张三的客户",
                    "reason": "这是客户本人姓名，应映射到 searchClientNameNew，不是 familyClientName",
                }
            ],
        }
    ])

    assert "定义: 表示家庭成员姓名，不表示客户本人姓名" in prompt
    assert "反例: \"叫张三的客户\" → 不输出该字段" in prompt
    assert "原因: 这是客户本人姓名，应映射到 searchClientNameNew" in prompt


def test_format_prompt_section_preserves_client_family_boundary_examples():
    registry = FieldRegistry.__new__(FieldRegistry)
    prompt = registry.format_prompt_section([
        {
            "field": "clientSex",
            "operator": "MATCH",
            "value_type": "enum",
            "description": "表示客户本人性别，不表示家庭成员性别",
            "negative_examples": [
                {
                    "query": "子女是男性的客户",
                    "reason": "这是家庭成员性别，应映射到 familyClientSex 并组合 familyRelation",
                }
            ],
        },
        {
            "field": "familyClientAge",
            "operator": "RANGE",
            "value_type": "numeric",
            "description": "表示家庭成员年龄，不表示客户本人年龄",
            "negative_examples": [
                {
                    "query": "45岁以上的客户",
                    "reason": "这是客户本人年龄，应映射到 clientAge，不是 familyClientAge",
                }
            ],
        },
    ])

    assert "反例: \"子女是男性的客户\" → 不输出该字段" in prompt
    assert "原因: 这是家庭成员性别，应映射到 familyClientSex" in prompt
    assert "反例: \"45岁以上的客户\" → 不输出该字段" in prompt
    assert "原因: 这是客户本人年龄，应映射到 clientAge" in prompt


def test_format_prompt_section_preserves_status_vs_existence_boundaries():
    registry = FieldRegistry.__new__(FieldRegistry)
    prompt = registry.format_prompt_section([
        {
            "field": "searchZhenxiangRunEquityGrade",
            "operator": "MATCH",
            "value_type": "enum",
            "description": "表示安有护权益等级版本；也可用 EXISTS 表示是否持有该权益",
            "negative_examples": [
                {
                    "query": "安有护开通时间在2024年的客户",
                    "reason": "这是开通时间，不是权益等级",
                }
            ],
        },
        {
            "field": "searchZxjyEquityGrade",
            "operator": "MATCH",
            "value_type": "enum",
            "description": "表示臻享家医达标状态，不表示开通时间、使用次数",
            "negative_examples": [
                {
                    "query": "持有臻享家医权益的客户",
                    "reason": "这更接近权益是否存在语义；当前字段仅表达达标状态，不能凭空扩展为开通/持有关系",
                }
            ],
        },
    ])

    assert "反例: \"安有护开通时间在2024年的客户\" → 不输出该字段" in prompt
    assert "原因: 这是开通时间，不是权益等级" in prompt
    assert "反例: \"持有臻享家医权益的客户\" → 不输出该字段" in prompt
    assert "原因: 这更接近权益是否存在语义" in prompt


def test_format_prompt_section_falls_back_to_registry_enum_values():
    registry = FieldRegistry.__new__(FieldRegistry)
    registry._enum_values_by_field = {
        "gProductCode": ["一年期综合意外保险", "一年期交通意外保险"]
    }
    prompt = registry.format_prompt_section([
        {
            "field": "gProductCode",
            "operator": "CONTAINS",
            "value_type": "enum",
            "examples": [
                {
                    "query": "持有一年期综合意外保险的客户",
                    "output": {"field": "gProductCode", "operator": "CONTAINS", "value": "一年期综合意外保险"},
                }
            ],
        }
    ])

    assert "枚举:" in prompt
    assert "一年期综合意外保险" in prompt
    assert "一年期交通意外保险" in prompt


def test_format_prompt_section_can_hide_large_enum_lists():
    registry = FieldRegistry.__new__(FieldRegistry)
    registry._enum_values_by_field = {
        "planAbbrNames": ["生财宝", "智能星", "金利多"]
    }
    prompt = registry.format_prompt_section([
        {
            "field": "planAbbrNames",
            "operator": "CONTAINS",
            "value_type": "enum",
            "show_enum_in_prompt": False,
            "description": "表示具体寿险产品名称",
            "examples": [
                {
                    "query": "持有平安永福的客户",
                    "output": {"field": "planAbbrNames", "operator": "CONTAINS", "value": "平安永福"},
                }
            ],
        }
    ])

    assert "**planAbbrNames**" in prompt
    assert "表示具体寿险产品名称" in prompt
    assert "枚举:" not in prompt


def test_format_prompt_section_still_shows_small_enums_by_default():
    registry = FieldRegistry.__new__(FieldRegistry)
    registry._enum_values_by_field = {
        "clientSex": ["男", "女"]
    }
    prompt = registry.format_prompt_section([
        {
            "field": "clientSex",
            "operator": "MATCH",
            "value_type": "enum",
            "examples": [
                {
                    "query": "男性客户",
                    "output": {"field": "clientSex", "operator": "MATCH", "value": "男"},
                }
            ],
        }
    ])

    assert "枚举:" in prompt
    assert "男" in prompt
    assert "女" in prompt


def test_format_prompt_section_shows_candidate_enums_for_hidden_large_enum():
    registry = FieldRegistry.__new__(FieldRegistry)
    registry._enum_values_by_field = {
        "planAbbrNames": ["生财宝", "智能星", "金利多", "平安永福", "盛世金越"]
    }
    registry._value_mappings = {
        "planAbbrNames": {"永福": "平安永福"}
    }

    prompt = registry.format_prompt_section([
        {
            "field": "planAbbrNames",
            "operator": "CONTAINS",
            "value_type": "enum",
            "show_enum_in_prompt": False,
            "examples": [],
        }
    ], query="买过永福的客户")

    assert "| 枚举:" not in prompt
    assert "候选枚举:" in prompt
    assert "平安永福" in prompt


def test_format_prompt_section_hides_large_enum_without_candidates():
    registry = FieldRegistry.__new__(FieldRegistry)
    registry._enum_values_by_field = {
        "planAbbrNames": ["生财宝", "智能星", "金利多", "平安永福", "盛世金越"]
    }
    registry._value_mappings = {"planAbbrNames": {}}

    prompt = registry.format_prompt_section([
        {
            "field": "planAbbrNames",
            "operator": "CONTAINS",
            "value_type": "enum",
            "show_enum_in_prompt": False,
            "examples": [],
        }
    ], query="寿险客户")

    assert "| 枚举:" not in prompt
    assert "候选枚举:" not in prompt


def test_format_prompt_section_respects_candidate_limit():
    registry = FieldRegistry.__new__(FieldRegistry)
    registry._enum_values_by_field = {
        "planAbbrNames": ["平安永福", "金利多", "盛世金越", "智能星"]
    }
    registry._value_mappings = {
        "planAbbrNames": {
            "永福": "平安永福",
            "金利": "金利多",
            "盛世": "盛世金越",
        }
    }

    prompt = registry.format_prompt_section([
        {
            "field": "planAbbrNames",
            "operator": "CONTAINS",
            "value_type": "enum",
            "show_enum_in_prompt": False,
            "enum_candidate_limit_in_prompt": 2,
            "examples": [],
        }
    ], query="买过永福、金利、盛世的客户")

    assert "候选枚举:" in prompt
    assert "平安永福" in prompt
    assert "金利多" in prompt
    assert "盛世金越" not in prompt
