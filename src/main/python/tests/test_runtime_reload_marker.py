import asyncio
import sys
import types
import pytest
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

from src.main.python.api import client_search_query_parse_post as routes


def test_runtime_reload_marker_refreshes_current_worker(monkeypatch, tmp_path):
    marker_path = tmp_path / ".client_search_runtime_reload.json"
    calls = []

    monkeypatch.setattr(routes, "_runtime_reload_marker_path", lambda: marker_path)
    monkeypatch.setattr(routes, "_reload_marker_seen_mtime_ns", None)
    monkeypatch.setattr(routes, "_reload_marker_failed_mtime_ns", None)
    monkeypatch.setattr(routes, "_last_runtime_reload_error", None)
    monkeypatch.setattr(
        routes,
        "_schedule_runtime_reload",
        lambda force_reindex_fields=False, marker_mtime_ns=None, **kwargs: calls.append(
            (force_reindex_fields, marker_mtime_ns)
        ) or True,
    )

    marker_path.write_text("{}", encoding="utf-8")
    routes._ensure_runtime_config_current()

    assert calls == [(False, marker_path.stat().st_mtime_ns)]


def test_runtime_reload_marker_skips_when_already_seen(monkeypatch, tmp_path):
    marker_path = tmp_path / ".client_search_runtime_reload.json"
    marker_path.write_text("{}", encoding="utf-8")
    calls = []

    monkeypatch.setattr(routes, "_runtime_reload_marker_path", lambda: marker_path)
    monkeypatch.setattr(routes, "_reload_marker_seen_mtime_ns", marker_path.stat().st_mtime_ns)
    monkeypatch.setattr(routes, "_reload_marker_failed_mtime_ns", None)
    monkeypatch.setattr(routes, "_last_runtime_reload_error", None)
    monkeypatch.setattr(
        routes,
        "_schedule_runtime_reload",
        lambda force_reindex_fields=False, marker_mtime_ns=None, **kwargs: calls.append(
            (force_reindex_fields, marker_mtime_ns)
        ) or True,
    )

    routes._ensure_runtime_config_current()

    assert calls == []


class _RunningTask:
    def done(self):
        return False


@pytest.mark.asyncio
async def test_get_query_router_schedules_stale_marker_without_blocking_current_router(monkeypatch, tmp_path):
    marker_path = tmp_path / ".client_search_runtime_reload.json"
    marker_path.write_text("{}", encoding="utf-8")
    current_router = object()
    calls = []

    monkeypatch.setattr(routes, "_query_router", current_router)
    monkeypatch.setattr(routes, "_runtime_reload_marker_path", lambda: marker_path)
    monkeypatch.setattr(routes, "_reload_marker_seen_mtime_ns", None)
    monkeypatch.setattr(routes, "_reload_marker_failed_mtime_ns", None)
    monkeypatch.setattr(routes, "_last_runtime_reload_error", None)
    monkeypatch.setattr(
        routes,
        "_schedule_runtime_reload",
        lambda force_reindex_fields=False, marker_mtime_ns=None, **kwargs: calls.append(
            (force_reindex_fields, marker_mtime_ns)
        ) or True,
    )

    router = await routes.get_query_router()

    assert router is current_router
    assert calls == [(False, marker_path.stat().st_mtime_ns)]


@pytest.mark.asyncio
async def test_get_query_router_fails_fast_when_reloading_without_previous_runtime(monkeypatch):
    async def load_query_router():
        raise AssertionError("query router should not load during runtime reload")

    monkeypatch.setattr(routes, "_query_router", None)
    monkeypatch.setattr(routes, "_query_router_load_task", None)
    monkeypatch.setattr(routes, "_runtime_reload_task", _RunningTask())
    monkeypatch.setattr(routes, "_last_runtime_reload_error", None)
    monkeypatch.setattr(routes, "_last_runtime_reload_result", None)
    monkeypatch.setattr(routes, "_ensure_runtime_config_current", lambda: None)
    monkeypatch.setattr(routes, "_load_query_router", load_query_router)

    with pytest.raises(routes.HTTPException) as exc_info:
        await routes.get_query_router()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["status"] == "runtime_reloading"


@pytest.mark.asyncio
async def test_get_query_router_uses_existing_load_task_while_reloading(monkeypatch):
    expected_router = object()
    load_task = asyncio.create_task(asyncio.sleep(0, result=expected_router))

    monkeypatch.setattr(routes, "_query_router", None)
    monkeypatch.setattr(routes, "_query_router_load_task", load_task)
    monkeypatch.setattr(routes, "_query_router_load_delayed", False)
    monkeypatch.setattr(routes, "_runtime_reload_task", _RunningTask())
    monkeypatch.setattr(routes, "_last_runtime_reload_error", None)
    monkeypatch.setattr(routes, "_last_runtime_reload_result", None)
    monkeypatch.setattr(routes, "_ensure_runtime_config_current", lambda: None)

    router = await routes.get_query_router()

    assert router is expected_router


def test_resolve_reload_file_selection_accepts_alias():
    selected, scope = routes._resolve_reload_file_selection(["intent_summary"])

    assert scope == "intent_summary"
    assert len(selected) == 1
    assert selected[0]["alias"] == "intent_summary"


def test_reload_runtime_components_keeps_previous_runtime_on_failure(monkeypatch):
    from src.main.python.models import field_mapping as field_mapping_module
    from src.main.python.steps import field_registry as reg_module
    from src.main.python.steps import level2_enhanced_matcher as level2_module

    old_router = object()
    old_registry = object()
    old_api_port = routes.settings.API_PORT
    old_config = {"query_fields": {"customer_name": "oldName"}, "negation_words": ["旧"]}
    old_query_fields = {"customer_name": "oldName"}
    old_negation_words = ["旧"]
    old_level2_negation_words = ["旧"]

    monkeypatch.setattr(routes, "_query_router", old_router)
    monkeypatch.setattr(reg_module, "_registry", old_registry)
    monkeypatch.setattr(field_mapping_module, "_CONFIG", old_config)
    monkeypatch.setattr(field_mapping_module, "_CONFIG_MTIME_NS", 123)
    monkeypatch.setattr(field_mapping_module, "QUERY_FIELDS", old_query_fields)
    monkeypatch.setattr(field_mapping_module, "NEGATION_WORDS", old_negation_words)
    monkeypatch.setattr(level2_module, "NEGATION_WORDS", old_level2_negation_words)
    monkeypatch.setattr(routes, "_collect_config_yaml_files", lambda: [])

    def reload_settings():
        routes.settings.API_PORT = 18000
        return {"env": "dev", "config_path": "new.yaml"}

    def reload_field_mapping():
        field_mapping_module._CONFIG = {"query_fields": {"customer_name": "newName"}}
        field_mapping_module._CONFIG_MTIME_NS = 456
        field_mapping_module.QUERY_FIELDS = {"customer_name": "newName"}
        field_mapping_module.NEGATION_WORDS = ["新"]

    class FakeRegistry:
        intents = []

        def __init__(self, force_reindex=False):
            self.force_reindex = force_reindex

    class FakeIntentSummaryService:
        labels_path = "new-labels.yaml"

        def load(self):
            return self

    def build_query_router(*args, **kwargs):
        raise RuntimeError("bad router")

    monkeypatch.setattr(routes.settings, "reload", reload_settings)
    monkeypatch.setattr(field_mapping_module, "reload_field_mapping", reload_field_mapping)
    monkeypatch.setattr(reg_module, "FieldRegistry", FakeRegistry)
    monkeypatch.setattr(routes, "IntentSummaryService", FakeIntentSummaryService)
    monkeypatch.setattr(routes, "QueryRouter", build_query_router)

    with pytest.raises(RuntimeError, match="bad router"):
        routes.reload_runtime_components()

    assert routes._query_router is old_router
    assert reg_module._registry is old_registry
    assert routes.settings.API_PORT == old_api_port
    assert field_mapping_module._CONFIG == old_config
    assert field_mapping_module._CONFIG_MTIME_NS == 123
    assert field_mapping_module.QUERY_FIELDS == old_query_fields
    assert field_mapping_module.NEGATION_WORDS == old_negation_words
    assert level2_module.NEGATION_WORDS == old_level2_negation_words


def test_resolve_reload_file_selection_accepts_file_name():
    selected, scope = routes._resolve_reload_file_selection(["enhanced_rules_args.yaml"])

    assert scope == "full"
    assert len(selected) == 1
    assert selected[0]["alias"] == "enhanced_rules"


def test_resolve_reload_file_selection_accepts_time_knowledge():
    selected, scope = routes._resolve_reload_file_selection(["time_knowledge"])

    assert scope == "full"
    assert len(selected) == 1
    assert selected[0]["alias"] == "time_knowledge"
    assert selected[0]["path"].endswith("time_knowledge_args.yaml")


def test_resolve_reload_file_selection_rejects_unknown_file():
    try:
        routes._resolve_reload_file_selection(["unknown.yaml"])
    except ValueError as exc:
        assert "不支持热刷新的文件" in str(exc)
    else:
        raise AssertionError("unknown file should be rejected")
