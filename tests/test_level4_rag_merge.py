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
        if "pcCategory" in fields:
            results.append(
                {
                    "id": "held_product_category",
                    "field": "pcCategory",
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

    def format_prompt_section(self, intents, query=""):
        return "FIELDS:" + ",".join(intent["field"] for intent in intents)


class _StubL2Recall:
    def recall_fields(self, query, top_k=10):
        return [
            {
                "field": "pcCategory",
                "rule_name": "险种-未配置",
                "pattern": "mock",
                "matched_text": "没有购买意外伤害保险",
                "priority": 9,
            },
            {
                "field": "extraField",
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
    assert "pcCategory" in message


def test_level4_rag_prioritizes_trie_and_l2_before_es(monkeypatch):
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
    assert "trieField" in message
    assert "pcCategory" in message
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
