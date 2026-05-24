import asyncio
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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

from src.main.python.steps.query_router import QueryRouter
from src.main.python.models.schemas import Condition, Operator, QueryLogic
from src.main.python.config.settings import settings


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

    def recall_candidate_conditions(self, query: str, **kwargs):
        return []


class _StubLevel3:
    async def get(self, query: str):
        return None


class _StubLevel4:
    async def parse(self, query: str):
        raise AssertionError("L4 should not be used in this test")


class _StubFieldRegistry:
    def normalize_query(self, query: str):
        return query


def test_single_value_field_contains_list_promotes_outer_query_logic_to_or(monkeypatch):
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

    parsed = asyncio.run(router.route_with_peeling("A类客户", ""))

    assert parsed.query_logic == QueryLogic.OR
    assert len(parsed.conditions) == 1
    assert parsed.conditions[0].field == "newValueLabel"
    assert parsed.conditions[0].value == ["A1", "A2", "A3", "A4"]


def test_contains_list_keeps_and_for_non_single_value_field(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_L1", True)
    monkeypatch.setattr(settings, "ENABLE_L2", True)
    monkeypatch.setattr(settings, "ENABLE_L3", False)
    monkeypatch.setattr(settings, "ENABLE_L4", False)

    class _StubLevel2Product:
        async def match(self, query: str):
            return [
                Condition(
                    field="pCategorys",
                    operator=Operator.CONTAINS,
                    value=["疾病保险", "医疗保险"],
                )
            ]

        def recall_candidate_conditions(self, query: str, **kwargs):
            return []

    router = QueryRouter.__new__(QueryRouter)
    router.level1 = _StubLevel1()
    router.level2 = _StubLevel2Product()
    router.level3 = _StubLevel3()
    router.level4 = _StubLevel4()
    router.field_registry = _StubFieldRegistry()
    router._valid_fields = {"pCategorys"}
    router._enum_values = {}

    parsed = asyncio.run(router.route_with_peeling("买了重疾和医疗险的客户", ""))

    assert parsed.query_logic == QueryLogic.AND
    assert len(parsed.conditions) == 1
    assert parsed.conditions[0].field == "pCategorys"
    assert parsed.conditions[0].value == ["疾病保险", "医疗保险"]
