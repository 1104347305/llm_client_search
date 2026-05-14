import asyncio
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.modules.setdefault("redis", types.ModuleType("redis"))

from core.level4_llm_parser import Level4LLMParser
from core.query_router import QueryRouter
from config.settings import settings
from models.schemas import Condition, Operator


class _BusinessIntentRegistry:
    def retrieve(self, query, top_k=8):
        if "百万医疗" in query:
            return [
                {
                    "id": "life_insurance_product",
                    "field": "planAbbrNames",
                    "operator": "CONTAINS",
                    "value_type": "enum",
                    "examples": [
                        {
                            "query": "百万医疗的客户",
                            "output": {
                                "field": "planAbbrNames",
                                "operator": "CONTAINS",
                                "value": ["百万任我行18", "倍享百万"],
                            },
                        }
                    ],
                }
            ]
        if "税优养老产品" in query:
            return [
                {
                    "id": "life_insurance_product",
                    "field": "planAbbrNames",
                    "operator": "CONTAINS",
                    "value_type": "enum",
                    "examples": [
                        {
                            "query": "税优养老产品的客户",
                            "output": {
                                "field": "planAbbrNames",
                                "operator": "CONTAINS",
                                "value": ["税优养老", "智盈倍护23", "盛世优享24"],
                            },
                        }
                    ],
                }
            ]
        if "高保额" in query:
            return [
                {
                    "id": "total_coverage_gte",
                    "field": "insnoSumInsSeq",
                    "operator": "GTE",
                    "value_type": "numeric",
                    "examples": [
                        {
                            "query": "高保额客户",
                            "output": {
                                "field": "insnoSumInsSeq",
                                "operator": "GTE",
                                "value": 300000,
                            },
                        }
                    ],
                }
            ]
        return []

    def retrieve_by_enum(self, query):
        return []

    def format_prompt_section(self, intents, query=""):
        lines = []
        for intent in intents:
            lines.append(f"- **{intent['field']}** | 操作符: {intent['operator']}")
            for ex in intent.get("examples", []):
                lines.append(f"  示例: \"{ex['query']}\"")
        return "\n".join(lines)


def test_level4_rag_message_includes_million_medical_business_intent(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_ES", True)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_TRIE", False)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_L2", False)
    monkeypatch.setattr(settings, "L4_RAG_TOP_K", 8)

    parser = Level4LLMParser.__new__(Level4LLMParser)
    parser.field_registry = _BusinessIntentRegistry()
    parser.level2_recall = None

    message, has_intents = asyncio.run(parser._build_rag_message("百万医疗的客户"))

    assert has_intents is True
    assert "planAbbrNames" in message
    assert "百万医疗的客户" in message


def test_level4_rag_message_includes_tax_preferred_business_intent(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_ES", True)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_TRIE", False)
    monkeypatch.setattr(settings, "ENABLE_L4_RAG_L2", False)
    monkeypatch.setattr(settings, "L4_RAG_TOP_K", 8)

    parser = Level4LLMParser.__new__(Level4LLMParser)
    parser.field_registry = _BusinessIntentRegistry()
    parser.level2_recall = None

    message, has_intents = asyncio.run(parser._build_rag_message("税优养老产品的客户"))

    assert has_intents is True
    assert "planAbbrNames" in message
    assert "税优养老产品的客户" in message


def test_query_router_validation_accepts_new_business_plan_abbr_values():
    router = QueryRouter.__new__(QueryRouter)
    router._valid_fields = {"planAbbrNames"}
    router._enum_values = {
        "planAbbrNames": [
            "百万任我行18",
            "倍享百万",
            "百万任我行",
            "百万任我行17",
            "百万随行",
            "百万任我行22",
            "百万任我行23",
            "百万任我行25",
            "税优养老",
            "智盈倍护23",
            "盛世优享24",
            "金越养老年金（分红）25",
        ]
    }

    conditions = [
        Condition(
            field="planAbbrNames",
            operator=Operator.CONTAINS,
            value=["百万任我行18", "百万随行", "税优养老", "金越养老年金（分红）25"],
        )
    ]

    validated = router._validate_conditions(conditions)

    assert validated == conditions


def test_query_router_validation_accepts_high_value_business_group():
    router = QueryRouter.__new__(QueryRouter)
    router._valid_fields = {"newValueLabel"}
    router._enum_values = {
        "newValueLabel": ["F", "E", "D", "C", "B", "A4", "A3", "A2", "A1"]
    }

    conditions = [
        Condition(
            field="newValueLabel",
            operator=Operator.CONTAINS,
            value=["A1", "A2", "A3", "A4", "B", "C"],
        )
    ]

    validated = router._validate_conditions(conditions)

    assert validated == conditions
