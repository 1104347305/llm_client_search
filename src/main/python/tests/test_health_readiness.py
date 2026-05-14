import pytest
from fastapi import HTTPException

from src.main.python import main
from src.main.python.api import client_search_query_parse_post as routes


@pytest.mark.asyncio
async def test_health_returns_503_until_runtime_ready(monkeypatch):
    monkeypatch.setattr(
        main.routes_module,
        "runtime_readiness_status",
        lambda: {"ready": False, "status": "loading"},
    )

    with pytest.raises(HTTPException) as exc_info:
        await main.health_check()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["status"] == "loading"


@pytest.mark.asyncio
async def test_health_returns_healthy_when_runtime_ready(monkeypatch):
    async def parse_endpoint_ready():
        return {"ready": True, "status": "parse_endpoint_ready"}

    monkeypatch.setattr(
        main.routes_module,
        "runtime_readiness_status",
        lambda: {"ready": True, "status": "ready"},
    )
    monkeypatch.setattr(main.routes_module, "check_parse_endpoint_ready", parse_endpoint_ready)

    response = await main.health_check()

    assert response["status"] == "healthy"
    assert response["readiness"]["ready"] is True
    assert response["endpoint_readiness"]["ready"] is True


@pytest.mark.asyncio
async def test_health_returns_503_when_parse_endpoint_unavailable(monkeypatch):
    async def parse_endpoint_unavailable():
        return {"ready": False, "status": "parse_endpoint_unreachable"}

    monkeypatch.setattr(
        main.routes_module,
        "runtime_readiness_status",
        lambda: {"ready": True, "status": "ready"},
    )
    monkeypatch.setattr(main.routes_module, "check_parse_endpoint_ready", parse_endpoint_unavailable)

    with pytest.raises(HTTPException) as exc_info:
        await main.health_check()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["status"] == "parse_endpoint_check_failed"
    assert exc_info.value.detail["endpoint_readiness"]["status"] == "parse_endpoint_unreachable"


def test_runtime_reload_failure_marks_health_unready_until_worker_updates(monkeypatch):
    monkeypatch.setattr(routes, "_query_router", object())
    monkeypatch.setattr(routes, "_runtime_reload_task", None)
    monkeypatch.setattr(routes, "_last_runtime_reload_error", "bad config")
    monkeypatch.setattr(routes, "_last_runtime_reload_result", None)
    monkeypatch.setattr(routes, "_ensure_runtime_config_current", lambda: None)

    status = routes.runtime_readiness_status()

    assert status["ready"] is False
    assert status["status"] == "reload_failed_previous_runtime_available"
    assert status["serving_previous_runtime"] is True


def test_health_readiness_reports_pending_runtime_reload_without_starting_reload(monkeypatch, tmp_path):
    marker_path = tmp_path / ".client_search_runtime_reload.json"
    marker_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(routes, "_query_router", object())
    monkeypatch.setattr(routes, "_runtime_reload_task", None)
    monkeypatch.setattr(routes, "_last_runtime_reload_error", None)
    monkeypatch.setattr(routes, "_last_runtime_reload_result", None)
    monkeypatch.setattr(routes, "_runtime_reload_marker_path", lambda: marker_path)
    monkeypatch.setattr(routes, "_reload_marker_seen_mtime_ns", None)
    monkeypatch.setattr(routes, "_schedule_runtime_reload", lambda **kwargs: calls.append(kwargs))
    calls = []

    status = routes.runtime_readiness_status()

    assert calls == []
    assert status["ready"] is False
    assert status["status"] == "reload_pending_previous_runtime_available"
