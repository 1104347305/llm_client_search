import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.field_registry import FieldRegistry


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
