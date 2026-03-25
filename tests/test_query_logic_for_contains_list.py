import asyncio
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if "redis" not in sys.modules:
    fake_redis = types.ModuleType("redis")

    class _FakeRedisClient:
        def __init__(self, *args, **kwargs):
            pass

        def ping(self):
            return True

    fake_redis.Redis = _FakeRedisClient
    sys.modules["redis"] = fake_redis

if "openai" not in sys.modules:
    fake_openai = types.ModuleType("openai")

    class _FakeAsyncOpenAI:
        def __init__(self, *args, **kwargs):
            pass

    fake_openai.AsyncOpenAI = _FakeAsyncOpenAI
    sys.modules["openai"] = fake_openai

if "elasticsearch" not in sys.modules:
    fake_elasticsearch = types.ModuleType("elasticsearch")

    class _FakeElasticsearch:
        def __init__(self, *args, **kwargs):
            pass

    class _FakeNotFoundError(Exception):
        pass

    fake_elasticsearch.Elasticsearch = _FakeElasticsearch
    fake_elasticsearch.NotFoundError = _FakeNotFoundError
    sys.modules["elasticsearch"] = fake_elasticsearch

if "elasticsearch.helpers" not in sys.modules:
    fake_es_helpers = types.ModuleType("elasticsearch.helpers")

    def _fake_bulk(*args, **kwargs):
        return None

    fake_es_helpers.bulk = _fake_bulk
    sys.modules["elasticsearch.helpers"] = fake_es_helpers

from core.query_router import QueryRouter
from models.schemas import Condition, Operator, QueryLogic
from config.settings import settings


class _StubLevel1:
    async def extract(self, query: str):
        return []


class _StubLevel2:
    async def match(self, query: str):
        return [
            Condition(
                field="newValueLabel",
                operator=Operator.CONTAINS,
                value=["A1", "A2", "A3", "A4"],
            )
        ]


class _StubLevel3:
    async def get(self, query: str):
        return None


class _StubLevel4:
    async def parse(self, query: str):
        raise AssertionError("L4 should not be used in this test")


class _StubFieldRegistry:
    def normalize_query(self, query: str):
        return query


def test_contains_list_does_not_promote_outer_query_logic_to_or(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_L1", True)
    monkeypatch.setattr(settings, "ENABLE_L2", True)
    monkeypatch.setattr(settings, "ENABLE_L3", False)
    monkeypatch.setattr(settings, "ENABLE_L4", False)

    router = QueryRouter.__new__(QueryRouter)
    router.level1 = _StubLevel1()
    router.level2 = _StubLevel2()
    router.level3 = _StubLevel3()
    router.level4 = _StubLevel4()
    router.field_registry = _StubFieldRegistry()
    router._valid_fields = {"newValueLabel"}
    router._enum_values = {"newValueLabel": ["A1", "A2", "A3", "A4", "B", "C", "D", "E", "F"]}

    parsed = asyncio.run(router.route_with_peeling("A类客户"))

    assert parsed.query_logic == QueryLogic.AND
    assert len(parsed.conditions) == 1
    assert parsed.conditions[0].field == "newValueLabel"
    assert parsed.conditions[0].value == ["A1", "A2", "A3", "A4"]
