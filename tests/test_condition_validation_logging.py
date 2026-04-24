import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.modules.setdefault("redis", SimpleNamespace(Redis=object))

from loguru import logger

from core.query_router import QueryRouter
from models.schemas import Condition, Operator


def test_validate_conditions_logs_invalid_list_enum_values():
    router = QueryRouter.__new__(QueryRouter)
    router._valid_fields = {"newValueLabel"}
    router._enum_values = {"newValueLabel": ["A1", "A2", "A3", "A4", "B"]}

    messages = []
    sink_id = logger.add(lambda msg: messages.append(str(msg)), level="WARNING")
    try:
        result = router._validate_conditions([
            Condition(field="newValueLabel", operator=Operator.CONTAINS, value=["A1", "X"])
        ])
    finally:
        logger.remove(sink_id)

    assert result == []
    assert any("错误值=['X']" in message for message in messages)
    assert any("原始值=['A1', 'X']" in message for message in messages)


def test_validate_conditions_skips_enum_check_for_exists_operators():
    router = QueryRouter.__new__(QueryRouter)
    router._valid_fields = {"vipType"}
    router._enum_values = {"vipType": ["黄金V1", "黄金V2"]}

    exists_result = router._validate_conditions([
        Condition(field="vipType", operator=Operator.EXISTS, value="任意值")
    ])
    not_exists_result = router._validate_conditions([
        Condition(field="vipType", operator=Operator.NOT_EXISTS, value="任意值")
    ])

    assert len(exists_result) == 1
    assert len(not_exists_result) == 1


def test_validate_conditions_drops_exists_when_same_field_has_specific_operator():
    router = QueryRouter.__new__(QueryRouter)
    router._valid_fields = {"planAbbrNames"}
    router._enum_values = {"planAbbrNames": ["智能星", "颐享天年分红"]}

    result = router._validate_conditions([
        Condition(field="planAbbrNames", operator=Operator.EXISTS, value=None),
        Condition(field="planAbbrNames", operator=Operator.CONTAINS, value=["智能星"]),
    ])

    assert result == [
        Condition(field="planAbbrNames", operator=Operator.CONTAINS, value=["智能星"])
    ]


def test_validate_conditions_drops_not_exists_when_same_field_has_specific_negative_operator():
    router = QueryRouter.__new__(QueryRouter)
    router._valid_fields = {"planAbbrNames"}
    router._enum_values = {"planAbbrNames": ["智能星", "颐享天年分红"]}

    result = router._validate_conditions([
        Condition(field="planAbbrNames", operator=Operator.NOT_EXISTS, value=None),
        Condition(field="planAbbrNames", operator=Operator.NOT_CONTAINS, value=["智能星"]),
    ])

    assert result == [
        Condition(field="planAbbrNames", operator=Operator.NOT_CONTAINS, value=["智能星"])
    ]
