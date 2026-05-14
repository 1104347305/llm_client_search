import asyncio
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.modules.setdefault("redis", types.ModuleType("redis"))

from core.query_router import QueryRouter
from models.schemas import ParsedQuery, QueryLogic


class _StubFieldRegistry:
    def __init__(self):
        self.seen_queries = []

    def normalize_query(self, query: str) -> str:
        self.seen_queries.append(query)
        return query.replace("黄金VIP", "原黄金VIP")


class _StubLevel1:
    async def extract(self, query):
        self.last_query = query
        self._last_matched_patterns = [
            {
                "rule_name": "手机号",
                "pattern": "1[3-9]\\d{9}",
                "matched_text": query,
                "match_type": "regex",
            }
        ]
        return []


class _StubLevel2:
    async def extract(self, query):
        return []

    async def match(self, query):
        self.last_query = query
        self._last_matched_patterns = [
            {
                "rule_name": "寿险VIP+险种",
                "pattern": "mock-pattern",
                "matched_text": query,
                "match_type": "composite",
            }
        ]
        return []

    async def get(self, query):
        self.last_query = query
        return None

    async def set(self, query, parsed):
        self.last_set_query = query
        self.last_set_parsed = parsed


class _StubLevel4:
    async def parse(self, query):
        self.last_query = query
        return ParsedQuery(
            conditions=[],
            query_logic=QueryLogic.AND,
            confidence=0.0,
            matched_level=4,
        )


def test_query_router_normalizes_query_before_routing():
    router = QueryRouter.__new__(QueryRouter)
    router.level1 = _StubLevel1()
    router.level2 = _StubLevel2()
    router.level3 = _StubLevel2()
    router.level4 = _StubLevel4()
    router.field_registry = _StubFieldRegistry()
    router._valid_fields = set()
    router._enum_values = {}

    parsed = asyncio.run(router.route_with_peeling("黄金VIP客户"))

    assert router.field_registry.seen_queries == ["黄金VIP客户"]
    assert router.level2.last_query == "原黄金VIP客户"
    assert router.level3.last_query == "原黄金VIP客户"
    assert router.level4.last_query == "原黄金VIP客户"
    assert parsed.rewritten_query == "原黄金VIP客户"
    assert parsed.matched_patterns == [
        {
            "rule_name": "手机号",
            "pattern": "1[3-9]\\d{9}",
            "matched_text": "原黄金VIP客户",
            "match_type": "regex",
        },
        {
            "rule_name": "寿险VIP+险种",
            "pattern": "mock-pattern",
            "matched_text": "原黄金VIP客户",
            "match_type": "composite",
        }
    ]
