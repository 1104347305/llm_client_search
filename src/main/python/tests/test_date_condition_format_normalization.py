import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.main.python.models.schemas import Condition, Operator, RangeValue
from src.main.python.steps.query_router import QueryRouter


def _router_with_formats() -> QueryRouter:
    router = QueryRouter.__new__(QueryRouter)
    router._field_time_formats = {
        "dateCreated": "yyyy-MM-dd HH:mm:ss",
        "latelyUndwrtSegTime": "yyyy-MM-dd",
    }
    return router


def test_loads_date_field_formats_from_field_enums_config():
    router = QueryRouter.__new__(QueryRouter)

    formats = router._load_field_time_formats()

    assert formats["dateCreated"] == "yyyy-MM-dd HH:mm:ss"
    assert formats["latelyUndwrtSegTime"] == "yyyy-MM-dd"


def test_datetime_range_values_are_padded_from_configured_format():
    router = _router_with_formats()

    result = router.normalize_date_condition_formats([
        Condition(
            field="dateCreated",
            operator=Operator.RANGE,
            value=RangeValue(min="2026-05-01", max="2026-05-31"),
        )
    ])

    assert result[0].value == RangeValue(
        min="2026-05-01 23:59:59",
        max="2026-05-31 00:00:00",
    )


def test_datetime_scalar_uses_operator_boundary_when_time_is_missing():
    router = _router_with_formats()

    result = router.normalize_date_condition_formats([
        Condition(field="dateCreated", operator=Operator.LTE, value="2026-05-01"),
        Condition(field="dateCreated", operator=Operator.GTE, value="2026-05-31"),
    ])

    assert result[0].value == "2026-05-01 23:59:59"
    assert result[1].value == "2026-05-31 00:00:00"


def test_date_only_field_strips_time_from_scalar_and_range():
    router = _router_with_formats()

    result = router.normalize_date_condition_formats([
        Condition(field="latelyUndwrtSegTime", operator=Operator.GTE, value="2026-05-01 00:00:00"),
        Condition(
            field="latelyUndwrtSegTime",
            operator=Operator.RANGE,
            value=RangeValue(min="2026-05-01 00:00:00", max="2026-05-31 23:59:59"),
        ),
    ])

    assert result[0].value == "2026-05-01"
    assert result[1].value == RangeValue(min="2026-05-01", max="2026-05-31")
