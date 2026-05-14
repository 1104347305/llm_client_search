import asyncio
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.modules.setdefault("redis", types.ModuleType("redis"))

from models.schemas import NaturalLanguageSearchRequest, ParsedQuery, QueryLogic
from services.search_service import SearchService


class _StubRouter:
    async def route_with_peeling(self, query: str) -> ParsedQuery:
        return ParsedQuery(
            conditions=[],
            query_logic=QueryLogic.AND,
            confidence=0.95,
            matched_level=2,
            prompt="this should not be exposed",
            rewritten_query=query,
            matched_patterns=[{"rule_name": "mock", "pattern": "p", "matched_text": query, "match_type": "regular"}],
        )


class _StubAPIClient:
    async def search(self, request):
        return {"total": 0, "list": []}


def test_non_l4_response_hides_prompt():
    service = SearchService.__new__(SearchService)
    service.router = _StubRouter()
    service.api_client = _StubAPIClient()

    response = asyncio.run(service.natural_language_search(
        NaturalLanguageSearchRequest(query="测试", agent_id="a1")
    ))

    assert response.matched_level == 2
    assert response.prompt is None
    assert response.rewritten_query == "测试"
    assert response.matched_patterns == [
        {"rule_name": "mock", "pattern": "p", "matched_text": "测试", "match_type": "regular"}
    ]


class _StubL4Router:
    async def route_with_peeling(self, query: str) -> ParsedQuery:
        return ParsedQuery(
            conditions=[],
            query_logic=QueryLogic.AND,
            confidence=0.8,
            matched_level=4,
            prompt="### 用户查询\n测试",
            rewritten_query=query,
            matched_patterns=[{"rule_name": "L2_RULE", "pattern": "x", "matched_text": query, "match_type": "regular"}],
        )


def test_l4_response_merges_prompt_into_matched_patterns():
    service = SearchService.__new__(SearchService)
    service.router = _StubL4Router()
    service.api_client = _StubAPIClient()

    response = asyncio.run(service.natural_language_search(
        NaturalLanguageSearchRequest(query="测试", agent_id="a1")
    ))

    assert response.matched_level == 4
    assert response.prompt is None
    assert response.matched_patterns == [
        {"rule_name": "L2_RULE", "pattern": "x", "matched_text": "测试", "match_type": "regular"},
        {
            "rule_name": "L4_PROMPT",
            "pattern": None,
            "matched_text": None,
            "match_type": "llm_prompt",
            "prompt": "### 用户查询\n测试",
        },
    ]
