import asyncio
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.level4_llm_parser import Level4LLMParser
from config.settings import settings


class _StubFieldRegistry:
    def retrieve(self, query, top_k=10):
        return [
            {
                "id": "es_only",
                "field": "esField",
                "operator": "MATCH",
                "value_type": "string",
                "examples": [],
            }
        ]

    def retrieve_by_enum(self, query):
        return [
            {
                "id": "trie_only",
                "field": "trieField",
                "operator": "MATCH",
                "value_type": "enum",
                "examples": [],
            }
        ]

    def retrieve_by_fields(self, fields):
        results = []
        if "pCategorys" in fields:
            results.append(
                {
                    "id": "held_product_category",
                    "field": "pCategorys",
                    "operator": "MATCH",
                    "value_type": "enum",
                    "examples": [],
                }
            )
        if "extraField" in fields:
            results.append(
                {
                    "id": "l2_extra",
                    "field": "extraField",
                    "operator": "MATCH",
                    "value_type": "string",
                    "examples": [],
                }
            )
        if results:
            return results
        return []

    def retrieve_by_field_operator_pairs(self, pairs):
        results = []
        wanted = set(pairs)
        if ("pCategorys", "NOT_CONTAINS") in wanted:
            results.append(
                {
                    "id": "held_product_category",
                    "field": "pCategorys",
                    "operator": "NOT_CONTAINS",
                    "value_type": "enum",
                    "examples": [],
                }
            )
        if ("extraField", "MATCH") in wanted:
            results.append(
                {
                    "id": "l2_extra",
                    "field": "extraField",
                    "operator": "MATCH",
                    "value_type": "string",
                    "examples": [],
                }
            )
        return results

    def format_prompt_section(self, intents, query=""):
        return "FIELDS:" + ",".join(intent["field"] for intent in intents)


class _StubL2Recall:
    def recall_candidates(self, query, top_k=10):
        return [
            {
                "field": "pCategorys",
                "operator": "NOT_CONTAINS",
                "rule_name": "险种-未配置",
                "pattern": "mock",
                "matched_text": "没有购买意外伤害保险",
                "priority": 9,
            },
            {
                "field": "extraField",
                "operator": "MATCH",
                "rule_name": "额外字段",
                "pattern": "mock2",
                "matched_text": "额外",
                "priority": 8,
            },
        ]


def test_level4_rag_message_merges_l2_field_recall(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_ES", True)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_TRIE", True)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_L2", True)
    monkeypatch.setattr(settings, "L4_RAG_TOP_K", 10)

    parser = Level4LLMParser.__new__(Level4LLMParser)
    parser.field_registry = _StubFieldRegistry()
    parser.level2_recall = _StubL2Recall()

    message, has_intents = asyncio.run(
        parser._build_rag_message("买了车险，但没有购买意外险的客户")
    )

    assert has_intents is True
    assert "### 当前时间" in message
    assert "### 今天星期" in message
    assert "Asia/Shanghai" in message
    assert "pCategorys" in message


def test_level4_rag_prioritizes_l2_and_trie_before_es(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_ES", True)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_TRIE", True)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_L2", True)
    monkeypatch.setattr(settings, "L4_RAG_TOP_K", 2)

    parser = Level4LLMParser.__new__(Level4LLMParser)
    parser.field_registry = _StubFieldRegistry()
    parser.level2_recall = _StubL2Recall()

    message, has_intents = asyncio.run(
        parser._build_rag_message("买了车险，但没有购买意外险的客户")
    )

    assert has_intents is True
    assert "pCategorys" in message
    assert "extraField" in message
    assert "trieField" not in message
    assert "esField" not in message


def test_level4_rag_message_respects_l2_switch(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_ES", False)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_TRIE", False)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_L2", False)

    parser = Level4LLMParser.__new__(Level4LLMParser)
    parser.field_registry = _StubFieldRegistry()
    parser.level2_recall = None

    message, has_intents = asyncio.run(
        parser._build_rag_message("买了车险，但没有购买意外险的客户")
    )

    assert has_intents is False
    assert message == "买了车险，但没有购买意外险的客户"


def test_level4_rag_deduplicates_same_field_before_top_k(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_ES", True)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_TRIE", True)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_L2", True)
    monkeypatch.setattr(settings, "L4_RAG_TOP_K", 3)

    parser = Level4LLMParser.__new__(Level4LLMParser)
    parser.level2_recall = _StubL2Recall()

    class _FieldHeavyRegistry(_StubFieldRegistry):
        def retrieve(self, query, top_k=10):
            return [
                {"id": "es_1", "field": "sameField", "operator": "MATCH", "value_type": "string", "examples": []},
                {"id": "es_2", "field": "sameField", "operator": "MATCH", "value_type": "string", "examples": []},
                {"id": "es_3", "field": "esField", "operator": "MATCH", "value_type": "string", "examples": []},
            ]

        def retrieve_by_enum(self, query):
            return [
                {"id": "trie_1", "field": "sameField", "operator": "MATCH", "value_type": "string", "examples": []},
                {"id": "trie_2", "field": "trieField", "operator": "MATCH", "value_type": "string", "examples": []},
            ]

        def retrieve_by_fields(self, fields):
            return [
                {"id": "l2_1", "field": "pCategorys", "operator": "MATCH", "value_type": "enum", "examples": []}
            ]

        def retrieve_by_field_operator_pairs(self, pairs):
            return [
                {"id": "l2_1", "field": "pCategorys", "operator": "NOT_CONTAINS", "value_type": "enum", "examples": []}
            ]

    parser.field_registry = _FieldHeavyRegistry()

    message, has_intents = asyncio.run(parser._build_rag_message("测试查询"))

    assert has_intents is True
    assert "sameField" in message
    assert "pCategorys" in message
    assert "trieField" in message
    assert "esField" not in message


def test_level4_rag_keeps_same_field_with_different_operators(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_ES", True)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_TRIE", True)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_L2", True)
    monkeypatch.setattr(settings, "L4_RAG_TOP_K", 5)

    parser = Level4LLMParser.__new__(Level4LLMParser)
    parser.level2_recall = _StubL2Recall()

    class _OperatorAwareRegistry(_StubFieldRegistry):
        def retrieve(self, query, top_k=10):
            return [
                {"id": "es_contains", "field": "planAbbrNames", "operator": "CONTAINS", "value_type": "enum", "examples": []},
                {"id": "es_exists", "field": "planAbbrNames", "operator": "EXISTS", "value_type": "none", "examples": []},
                {"id": "es_other", "field": "otherField", "operator": "MATCH", "value_type": "string", "examples": []},
            ]

        def retrieve_by_enum(self, query):
            return []

        def retrieve_by_fields(self, fields):
            return []

        def retrieve_by_field_operator_pairs(self, pairs):
            return []

        def format_prompt_section(self, intents, query=""):
            return "FIELDS:" + ",".join(f"{intent['field']}:{intent['operator']}" for intent in intents)

    parser.field_registry = _OperatorAwareRegistry()

    message, has_intents = asyncio.run(parser._build_rag_message("测试查询"))

    assert has_intents is True
    assert "planAbbrNames:CONTAINS" in message
    assert "planAbbrNames:EXISTS" in message


def test_level4_rag_same_field_only_keeps_l2_operators(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_ES", True)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_TRIE", True)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_L2", True)
    monkeypatch.setattr(settings, "L4_RAG_TOP_K", 6)

    parser = Level4LLMParser.__new__(Level4LLMParser)

    class _L2OnlyContains:
        def recall_candidates(self, query, top_k=10):
            return [
                {
                    "field": "planAbbrNames",
                    "operator": "CONTAINS",
                    "rule_name": "寿险产品-持有",
                    "matched_text": "买过盛世金越",
                    "priority": 9,
                }
            ]

    class _MixedRegistry(_StubFieldRegistry):
        def retrieve(self, query, top_k=10):
            return [
                {"id": "es_exists", "field": "planAbbrNames", "operator": "EXISTS", "value_type": "none", "examples": []},
                {"id": "es_not_exists", "field": "planAbbrNames", "operator": "NOT_EXISTS", "value_type": "none", "examples": []},
                {"id": "es_other", "field": "otherField", "operator": "MATCH", "value_type": "string", "examples": []},
            ]

        def retrieve_by_enum(self, query):
            return [
                {"id": "trie_exists", "field": "planAbbrNames", "operator": "EXISTS", "value_type": "none", "examples": []}
            ]

        def retrieve_by_field_operator_pairs(self, pairs):
            wanted = set(pairs)
            results = []
            if ("planAbbrNames", "CONTAINS") in wanted:
                results.append(
                    {"id": "l2_contains", "field": "planAbbrNames", "operator": "CONTAINS", "value_type": "enum", "examples": []}
                )
            return results

        def format_prompt_section(self, intents, query=""):
            return "FIELDS:" + ",".join(f"{intent['field']}:{intent['operator']}" for intent in intents)

    parser.level2_recall = _L2OnlyContains()
    parser.field_registry = _MixedRegistry()

    message, has_intents = asyncio.run(parser._build_rag_message("买过盛世金越的客户"))

    assert has_intents is True
    assert "planAbbrNames:CONTAINS" in message
    assert "planAbbrNames:EXISTS" not in message
    assert "planAbbrNames:NOT_EXISTS" not in message
    assert "otherField:MATCH" in message


def test_level4_rag_keeps_multiple_planabbrnames_intents_with_same_operator(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_ES", True)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_TRIE", True)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_L2", False)
    monkeypatch.setattr(settings, "L4_RAG_TOP_K", 5)

    parser = Level4LLMParser.__new__(Level4LLMParser)
    parser.level2_recall = None

    class _ProductRegistry(_StubFieldRegistry):
        def retrieve(self, query, top_k=10):
            return [
                {
                    "id": "life_insurance_product_million_medical",
                    "field": "planAbbrNames",
                    "operator": "CONTAINS",
                    "value_type": "enum",
                    "examples": [],
                },
                {
                    "id": "life_insurance_product_tax_preferred",
                    "field": "planAbbrNames",
                    "operator": "CONTAINS",
                    "value_type": "enum",
                    "examples": [],
                },
                {
                    "id": "life_insurance_product",
                    "field": "planAbbrNames",
                    "operator": "CONTAINS",
                    "value_type": "enum",
                    "examples": [],
                },
            ]

        def retrieve_by_enum(self, query):
            return []

        def format_prompt_section(self, intents, query=""):
            return "FIELDS:" + ",".join(intent["id"] for intent in intents)

    parser.field_registry = _ProductRegistry()

    message, has_intents = asyncio.run(parser._build_rag_message("税优养老产品或盛世金越"))

    assert has_intents is True
    assert "life_insurance_product_million_medical" in message
    assert "life_insurance_product_tax_preferred" in message
    assert "life_insurance_product" in message


def test_level4_rag_fuses_scores_for_same_key():
    merged = Level4LLMParser._merge_rag_intents_by_field(
        trie_intents=[
            {"id": "trie_same", "field": "sameField", "operator": "MATCH", "value_type": "enum"}
        ],
        l2_intents=[
            {"id": "l2_same", "field": "sameField", "operator": "MATCH", "value_type": "string"}
        ],
        es_intents=[
            {"id": "es_same", "field": "sameField", "operator": "MATCH", "value_type": "string"}
        ],
        top_k=5,
    )

    assert [intent["id"] for intent in merged] == ["l2_same"]


def test_level4_rag_orders_results_by_source_score():
    merged = Level4LLMParser._merge_rag_intents_by_field(
        trie_intents=[
            {"id": "trie_field", "field": "trieField", "operator": "MATCH", "value_type": "enum"}
        ],
        l2_intents=[
            {"id": "l2_field", "field": "l2Field", "operator": "MATCH", "value_type": "string"}
        ],
        es_intents=[
            {"id": "es_field", "field": "esField", "operator": "MATCH", "value_type": "string"}
        ],
        top_k=5,
    )

    assert [intent["id"] for intent in merged] == ["l2_field", "trie_field", "es_field"]


def test_level4_rag_multi_route_consensus_outranks_single_route():
    merged = Level4LLMParser._merge_rag_intents_by_field(
        trie_intents=[
            {"id": "consensus_trie", "field": "sameField", "operator": "MATCH", "value_type": "enum"}
        ],
        l2_intents=[
            {"id": "l2_only", "field": "l2Field", "operator": "MATCH", "value_type": "string"}
        ],
        es_intents=[
            {"id": "consensus_es", "field": "sameField", "operator": "MATCH", "value_type": "string"}
        ],
        top_k=5,
    )

    assert [intent["field"] for intent in merged] == ["sameField", "l2Field"]
    assert merged[0]["id"] in {"consensus_trie", "consensus_es"}
