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


def test_resolve_reload_file_selection_accepts_alias():
    selected, scope = routes._resolve_reload_file_selection(["intent_summary"])

    assert scope == "intent_summary"
    assert len(selected) == 1
    assert selected[0]["alias"] == "intent_summary"


def test_resolve_reload_file_selection_accepts_file_name():
    selected, scope = routes._resolve_reload_file_selection(["enhanced_rules_args.yaml"])

    assert scope == "full"
    assert len(selected) == 1
    assert selected[0]["alias"] == "enhanced_rules"


def test_resolve_reload_file_selection_rejects_unknown_file():
    try:
        routes._resolve_reload_file_selection(["unknown.yaml"])
    except ValueError as exc:
        assert "不支持热刷新的文件" in str(exc)
    else:
        raise AssertionError("unknown file should be rejected")
