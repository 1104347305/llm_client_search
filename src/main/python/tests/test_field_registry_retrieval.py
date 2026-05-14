import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.main.python.steps.field_registry import FieldRegistry


class _FakeES:
    def __init__(self):
        self.last_index = None
        self.last_body = None
        self.calls = []

    def search(self, index=None, body=None):
        self.last_index = index
        self.last_body = body
        query = body["query"]["bool"]["should"][0]["multi_match"]["query"]
        self.calls.append(query)
        if query == "保单号匹配P100000000000010":
            return {"hits": {"hits": [{"_source": {"id": "policy_no"}}]}}
        if query == "寿险产品包含平安康泰":
            return {"hits": {"hits": [{"_source": {"id": "life_insurance_product"}}]}}
        if query == "客户温度为高温的客户":
            return {"hits": {"hits": [{"_source": {"id": "customer_temperature_exact"}}]}}
        return {"hits": {"hits": [{"_source": {"id": "x1"}}]}}


class _FakeIndices:
    def __init__(self, exists=True):
        self._exists = exists
        self.deleted = False
        self.created = False

    def exists(self, index=None):
        return self._exists

    def delete(self, index=None):
        self.deleted = True

    def create(self, index=None, body=None):
        self.created = True


class _FakeIndexInitES:
    def __init__(self, exists=True):
        self.indices = _FakeIndices(exists=exists)


def test_retrieve_uses_normalized_query_and_phrase_boosts():
    registry = FieldRegistry.__new__(FieldRegistry)
    registry.index = "field_intents"
    registry.es = _FakeES()
    registry.normalize_query = lambda q: q.replace("精英白领", "都市白领")

    results = registry.retrieve("精英白领客户", top_k=5)

    assert results == [{"id": "x1"}]
    should = registry.es.last_body["query"]["bool"]["should"]
    assert should[0]["multi_match"]["query"] == "都市白领客户"
    assert should[1]["match_phrase"]["retrieval_text"]["query"] == "都市白领客户"
    assert should[2]["match_phrase"]["examples_text"]["query"] == "都市白领客户"


def test_flatten_examples_text_only_keeps_queries():
    examples = [
        {"query": "高温客户", "output": {"field": "clientTemperature", "operator": "MATCH", "value": "高温"}},
        {"query": "中高温客户"},
    ]

    assert FieldRegistry._flatten_examples_text(examples) == "高温客户 中高温客户"


def test_retrieve_merges_clause_level_results():
    registry = FieldRegistry.__new__(FieldRegistry)
    registry.index = "field_intents"
    registry.es = _FakeES()
    registry.normalize_query = lambda q: q

    results = registry.retrieve(
        "保单号匹配P100000000000010、寿险产品包含平安康泰且客户温度为高温的客户",
        top_k=5,
    )

    assert [item["id"] for item in results] == [
        "x1",
        "policy_no",
        "life_insurance_product",
        "customer_temperature_exact",
    ]
    assert registry.es.calls[:4] == [
        "保单号匹配P100000000000010、寿险产品包含平安康泰且客户温度为高温的客户",
        "保单号匹配P100000000000010",
        "寿险产品包含平安康泰",
        "客户温度为高温的客户",
    ]


def test_init_index_does_not_reindex_without_force():
    registry = FieldRegistry.__new__(FieldRegistry)
    registry.index = "field_intents"
    registry.es = _FakeIndexInitES(exists=True)
    registry.es_available = True

    registry._init_index(force_reindex=False)

    assert registry.es_available is True
    assert registry.es.indices.deleted is False
    assert registry.es.indices.created is False


def test_init_index_marks_es_unavailable_when_manual_index_missing():
    registry = FieldRegistry.__new__(FieldRegistry)
    registry.index = "field_intents"
    registry.es = _FakeIndexInitES(exists=False)
    registry.es_available = True

    registry._init_index(force_reindex=False)

    assert registry.es_available is False
    assert registry.es.indices.deleted is False
    assert registry.es.indices.created is False


def test_retrieve_by_field_operator_pairs_returns_first_match_per_pair_in_yaml_order():
    registry = FieldRegistry.__new__(FieldRegistry)
    registry.intents = [
        {"id": "age_exists", "field": "clientAge", "operator": "EXISTS"},
        {"id": "age_not_exists", "field": "clientAge", "operator": "NOT_EXISTS"},
        {"id": "age_exists_duplicate", "field": "clientAge", "operator": "EXISTS"},
        {"id": "birthday_exists", "field": "clientBirthday", "operator": "EXISTS"},
    ]

    results = registry.retrieve_by_field_operator_pairs(
        [("clientBirthday", "EXISTS"), ("clientAge", "EXISTS"), ("clientAge", "NOT_EXISTS")]
    )

    assert [item["id"] for item in results] == [
        "age_exists",
        "age_not_exists",
        "birthday_exists",
    ]


def test_retrieve_by_field_operator_pairs_skips_unknown_pairs():
    registry = FieldRegistry.__new__(FieldRegistry)
    registry.intents = [
        {"id": "vip_exists", "field": "vipType", "operator": "EXISTS"},
        {"id": "vip_not_exists", "field": "vipType", "operator": "NOT_EXISTS"},
    ]

    results = registry.retrieve_by_field_operator_pairs(
        [("vipType", "EXISTS"), ("vipType", "MATCH"), ("missingField", "EXISTS")]
    )

    assert results == [{"id": "vip_exists", "field": "vipType", "operator": "EXISTS"}]


def test_hidden_enum_prompt_uses_recalled_candidates_not_first_values():
    registry = FieldRegistry.__new__(FieldRegistry)
    registry._intents_by_id = {}
    registry._enum_values_by_field = {}
    registry._value_mappings = {}
    registry.normalize_query = lambda query: query

    prompt = registry.format_prompt_section(
        [
            {
                "id": "plan_abbr",
                "field": "polNoInfo.plancodeinfo.abbrname",
                "operator": "MATCH",
                "value_type": "string",
                "description": "投保险种简称",
                "show_enum_in_prompt": False,
                "enum_candidate_limit_in_prompt": 2,
                "enum": ["平安福", "鑫祥", "e生保", "平安e生保医疗保险"],
            }
        ],
        query="买了e生保的客户",
    )

    assert "候选枚举: ['e生保']" in prompt
    assert "平安福" not in prompt
    assert "鑫祥" not in prompt


def test_hidden_enum_prompt_does_not_fallback_to_first_values_without_recall():
    registry = FieldRegistry.__new__(FieldRegistry)
    registry._intents_by_id = {}
    registry._enum_values_by_field = {}
    registry._value_mappings = {}
    registry.normalize_query = lambda query: query

    prompt = registry.format_prompt_section(
        [
            {
                "id": "plan_abbr",
                "field": "polNoInfo.plancodeinfo.abbrname",
                "operator": "MATCH",
                "value_type": "string",
                "description": "投保险种简称",
                "show_enum_in_prompt": False,
                "enum_candidate_limit_in_prompt": 2,
                "enum": ["平安福", "鑫祥", "守护百分百"],
            }
        ],
        query="买了e生保的客户",
    )

    assert "候选枚举" not in prompt
    assert "平安福" not in prompt
    assert "鑫祥" not in prompt
