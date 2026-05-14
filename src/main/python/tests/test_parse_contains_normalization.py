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

from src.main.python.api.client_search_query_parse_post import _promote_single_value_contains_to_match
from src.main.python.models.schemas import Condition, Operator


def test_parse_output_promotes_single_contains_list_to_match():
    [condition] = _promote_single_value_contains_to_match([
        Condition(field="familyInfo.familyrelation", operator=Operator.CONTAINS, value=["子女"])
    ])

    assert condition.operator == Operator.MATCH
    assert condition.value == "子女"


def test_parse_output_keeps_multi_contains_list():
    [condition] = _promote_single_value_contains_to_match([
        Condition(field="familyInfo.familyrelation", operator=Operator.CONTAINS, value=["子女", "父母"])
    ])

    assert condition.operator == Operator.CONTAINS
    assert condition.value == ["子女", "父母"]
