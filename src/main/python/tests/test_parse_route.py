"""
parse API 接口回归测试（AskBob 标准协议）
覆盖：成功返回、robot_text、trace_id 透传、空条件、异常场景
"""
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from main import app
from models.schemas import Condition, Operator, ParsedQuery, QueryLogic

URL = "/api/v1/parse"

BASE_REQUEST = {
    "source": "askbob",
    "user_text": "查找姓张的客户",
    "session_id": "sess-001",
    "trace_id": "trace-abc-123",
    "user_id": "A000001",
    "ts": 1700000000000,
    "user_action": "write",
    "action_scenario": "customerSearch",
    "extra_input_params": {},
}


def _make_parsed(conditions=None, matched_level=2, rewritten_query=None):
    conds = conditions if conditions is not None else [
        Condition(field="name", operator=Operator.MATCH, value="张")
    ]
    return ParsedQuery(
        conditions=conds,
        query_logic=QueryLogic.AND,
        confidence=0.95,
        matched_level=matched_level,
        rewritten_query=rewritten_query,
        matched_patterns=[],
    )


@pytest.fixture
def mock_logger():
    with patch("routes.get_request_logger") as m:
        logger_inst = AsyncMock()
        logger_inst.log = AsyncMock()
        m.return_value = logger_inst
        yield m


@pytest.mark.asyncio
async def test_full_request_returns_code_zero(mock_logger):
    parsed = _make_parsed()
    with patch("routes._query_router.route_with_peeling", new=AsyncMock(return_value=parsed)):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(URL, json=BASE_REQUEST)
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["msg"] == "操作成功"


@pytest.mark.asyncio
async def test_minimal_request_only_user_text_and_user_id(mock_logger):
    parsed = _make_parsed()
    with patch("routes._query_router.route_with_peeling", new=AsyncMock(return_value=parsed)):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(URL, json={"user_text": "VIP客户", "user_id": "A000002"})
    assert resp.status_code == 200
    assert resp.json()["code"] == 0


@pytest.mark.asyncio
async def test_trace_id_is_passed_through(mock_logger):
    parsed = _make_parsed()
    with patch("routes._query_router.route_with_peeling", new=AsyncMock(return_value=parsed)):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(URL, json=BASE_REQUEST)
    assert resp.json()["data"]["trace_id"] == "trace-abc-123"


@pytest.mark.asyncio
async def test_extra_output_contains_required_fields(mock_logger):
    parsed = _make_parsed()
    with patch("routes._query_router.route_with_peeling", new=AsyncMock(return_value=parsed)):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(URL, json=BASE_REQUEST)
    extra = resp.json()["data"]["extra_output_params"]
    for field in ("query", "query_logic", "conditions", "matched_level", "last_tims"):
        assert field in extra, f"缺少字段: {field}"


@pytest.mark.asyncio
async def test_query_field_echoes_user_text(mock_logger):
    parsed = _make_parsed()
    with patch("routes._query_router.route_with_peeling", new=AsyncMock(return_value=parsed)):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(URL, json=BASE_REQUEST)
    assert resp.json()["data"]["extra_output_params"]["query"] == BASE_REQUEST["user_text"]


@pytest.mark.asyncio
async def test_end_flag_is_one(mock_logger):
    parsed = _make_parsed()
    with patch("routes._query_router.route_with_peeling", new=AsyncMock(return_value=parsed)):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(URL, json=BASE_REQUEST)
    assert resp.json()["data"]["end_flag"] == 1


@pytest.mark.asyncio
async def test_robot_text_with_conditions(mock_logger):
    conds = [
        Condition(field="name", operator=Operator.MATCH, value="张"),
        Condition(field="vip_level", operator=Operator.EXISTS, value=None),
    ]
    parsed = _make_parsed(conditions=conds)
    with patch("routes._query_router.route_with_peeling", new=AsyncMock(return_value=parsed)):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(URL, json=BASE_REQUEST)
    assert resp.json()["data"]["robot_text"] == "已解析 2 个查询条件"


@pytest.mark.asyncio
async def test_robot_text_without_conditions(mock_logger):
    parsed = _make_parsed(conditions=[])
    with patch("routes._query_router.route_with_peeling", new=AsyncMock(return_value=parsed)):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(URL, json=BASE_REQUEST)
    assert resp.json()["data"]["robot_text"] == "未能解析查询条件"


@pytest.mark.asyncio
async def test_exception_returns_http_200_with_code_500(mock_logger):
    with patch(
        "routes._query_router.route_with_peeling",
        new=AsyncMock(side_effect=RuntimeError("解析器内部错误")),
    ):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(URL, json=BASE_REQUEST)
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 500
    assert "解析器内部错误" in body["msg"]
    assert body["data"] is None
