import asyncio
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from core.level4_llm_parser import Level4LLMParser


class _SlowFieldRegistry:
    def retrieve(self, query, top_k=10):
        time.sleep(0.1)
        return [{
            "id": "es_intent",
            "field": "esField",
            "operator": "MATCH",
            "value_type": "string",
            "examples": [],
        }]

    def retrieve_by_enum(self, query):
        time.sleep(0.1)
        return [{
            "id": "trie_intent",
            "field": "trieField",
            "operator": "MATCH",
            "value_type": "enum",
            "examples": [],
        }]

    def retrieve_by_fields(self, fields):
        time.sleep(0.1)
        if "l2Field" not in fields:
            return []
        return [{
            "id": "l2_intent",
            "field": "l2Field",
            "operator": "MATCH",
            "value_type": "string",
            "examples": [],
        }]

    def retrieve_by_field_operator_pairs(self, pairs):
        time.sleep(0.1)
        if ("l2Field", "MATCH") not in set(pairs):
            return []
        return [{
            "id": "l2_intent",
            "field": "l2Field",
            "operator": "MATCH",
            "value_type": "string",
            "examples": [],
        }]

    def format_prompt_section(self, intents, query=""):
        return "FIELDS:" + ",".join(intent["field"] for intent in intents)


class _SlowL2Recall:
    def recall_candidates(self, query, top_k=10):
        time.sleep(0.1)
        return [{"field": "l2Field", "operator": "MATCH"}]


def test_level4_rag_runs_in_parallel(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_ES", True)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_TRIE", True)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_L2", True)

    parser = Level4LLMParser.__new__(Level4LLMParser)
    parser.field_registry = _SlowFieldRegistry()
    parser.level2_recall = _SlowL2Recall()

    start = time.perf_counter()
    message, has_intents = asyncio.run(parser._build_rag_message("测试查询"))
    elapsed = time.perf_counter() - start

    assert has_intents is True
    assert "esField" in message
    assert "trieField" in message
    assert "l2Field" in message
    assert elapsed < 0.25


def test_level4_rag_switches_can_disable_routes(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_ES", False)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_TRIE", True)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_L2", False)

    parser = Level4LLMParser.__new__(Level4LLMParser)
    parser.field_registry = _SlowFieldRegistry()
    parser.level2_recall = None

    message, has_intents = asyncio.run(parser._build_rag_message("测试查询"))

    assert has_intents is True
    assert "trieField" in message
    assert "esField" not in message
    assert "l2Field" not in message
