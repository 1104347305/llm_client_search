import calendar
import re
from datetime import date, datetime, timedelta
from typing import Dict, Optional, Union

from models.schemas import RangeValue


def _normalize_now(now: Optional[Union[date, datetime]]) -> datetime:
    if now is None:
        return datetime.now()
    if isinstance(now, datetime):
        return now
    return datetime.combine(now, datetime.min.time())


def _format_date_value(target: date, fmt_str: str) -> str:
    fmt_upper = fmt_str.upper()
    if fmt_upper == "MM-DD":
        return target.strftime("%m-%d")

    date_fmt = "%Y-%m-%d" if "YYYY-MM-DD" in fmt_upper else "%Y%m%d"
    rendered = target.strftime(date_fmt)
    if "HH:MM:SS" in fmt_upper:
        return f"{rendered} 00:00:00"
    return rendered


def _next_week_bounds(today: date) -> tuple[date, date]:
    days_until_next_monday = (7 - today.weekday()) % 7
    if days_until_next_monday == 0:
        days_until_next_monday = 7
    next_monday = today + timedelta(days=days_until_next_monday)
    return next_monday, next_monday + timedelta(days=6)


def _next_month_bounds(today: date) -> tuple[date, date]:
    year = today.year + 1 if today.month == 12 else today.year
    month = 1 if today.month == 12 else today.month + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _current_month_bounds(today: date) -> tuple[date, date]:
    last_day = calendar.monthrange(today.year, today.month)[1]
    return date(today.year, today.month, 1), date(today.year, today.month, last_day)


def resolve_dynamic_date_range(config: Dict, match=None, now: Optional[Union[date, datetime]] = None):
    """按统一口径展开动态日期范围。"""
    base_now = _normalize_now(now)
    today = base_now.date()
    date_range = config.get("date_range", "")
    fmt_str = config.get("format", "YYYY-MM-DD")

    def _range(start: date, end: date) -> RangeValue:
        return RangeValue(
            min=_format_date_value(start, fmt_str),
            max=_format_date_value(end, fmt_str),
        )

    if date_range == "today":
        return _range(today, today)

    if date_range == "tomorrow":
        target = today + timedelta(days=1)
        return _range(target, target)

    if date_range == "day_after_tomorrow":
        target = today + timedelta(days=2)
        return _range(target, target)

    if date_range == "next_month":
        start, end = _next_month_bounds(today)
        return _range(start, end)

    if date_range == "current_month":
        start, end = _current_month_bounds(today)
        return _range(start, end)

    if date_range == "next_n_days":
        n = config.get("days", 30)
        days_group = config.get("days_group")
        if days_group and match:
            try:
                n = int(match.group(days_group))
            except (IndexError, ValueError):
                pass
        start = today + timedelta(days=1)
        end = start + timedelta(days=n - 1)
        return _range(start, end)

    if date_range == "today_plus_n_days":
        n = config.get("days", 30)
        days_group = config.get("days_group")
        if days_group and match:
            try:
                n = int(match.group(days_group))
            except (IndexError, ValueError):
                pass
        target = today + timedelta(days=n)
        return _format_date_value(target, fmt_str)

    if date_range == "next_week":
        start, end = _next_week_bounds(today)
        return _range(start, end)

    if date_range == "last_n_days":
        n = config.get("days", 30)
        days_group = config.get("days_group")
        if days_group and match:
            try:
                n = int(match.group(days_group))
            except (IndexError, ValueError):
                pass
        start = today - timedelta(days=n)
        return _range(start, today)

    if date_range == "last_month":
        if today.month == 1:
            start = date(today.year - 1, 12, 1)
            end = date(today.year - 1, 12, 31)
        else:
            last_day = calendar.monthrange(today.year, today.month - 1)[1]
            start = date(today.year, today.month - 1, 1)
            end = date(today.year, today.month - 1, last_day)
        return _range(start, end)

    if date_range == "last_year":
        if fmt_str.upper() == "MM-DD":
            return None
        return _range(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31))

    if date_range == "current_year":
        if fmt_str.upper() == "MM-DD":
            return None
        return _range(date(today.year, 1, 1), date(today.year, 12, 31))

    return None


def resolve_dynamic_date_placeholder(value, now: Optional[datetime] = None):
    """将 LLM 输出的相对时间占位符统一展开为具体日期。"""
    if not isinstance(value, str):
        return value

    base_now = _normalize_now(now)
    today = base_now.date()
    text = value.strip()
    normalized = text.lower()

    exact_mapping = {
        "<today>": _format_date_value(today, "YYYY-MM-DD HH:mm:ss"),
        "<tomorrow>": _format_date_value(today + timedelta(days=1), "YYYY-MM-DD HH:mm:ss"),
        "<day_after_tomorrow>": _format_date_value(today + timedelta(days=2), "YYYY-MM-DD HH:mm:ss"),
        "<current_month_start>": _format_date_value(_current_month_bounds(today)[0], "YYYY-MM-DD HH:mm:ss"),
        "<current_month_end>": _format_date_value(_current_month_bounds(today)[1], "YYYY-MM-DD HH:mm:ss"),
        "<current_year_start>": _format_date_value(date(today.year, 1, 1), "YYYY-MM-DD HH:mm:ss"),
        "<current_year_end>": _format_date_value(date(today.year, 12, 31), "YYYY-MM-DD HH:mm:ss"),
        "<next_month_start>": _format_date_value(_next_month_bounds(today)[0], "YYYY-MM-DD HH:mm:ss"),
        "<next_month_end>": _format_date_value(_next_month_bounds(today)[1], "YYYY-MM-DD HH:mm:ss"),
        "<next_week_start>": _format_date_value(_next_week_bounds(today)[0], "YYYY-MM-DD HH:mm:ss"),
        "<next_week_end>": _format_date_value(_next_week_bounds(today)[1], "YYYY-MM-DD HH:mm:ss"),
        "<next_7_days_start>": _format_date_value(today + timedelta(days=1), "YYYY-MM-DD HH:mm:ss"),
        "<next_7_days_end>": _format_date_value(today + timedelta(days=7), "YYYY-MM-DD HH:mm:ss"),
        "<next_30_days_start>": _format_date_value(today + timedelta(days=1), "YYYY-MM-DD HH:mm:ss"),
        "<next_30_days_end>": _format_date_value(today + timedelta(days=30), "YYYY-MM-DD HH:mm:ss"),
    }
    if normalized in exact_mapping:
        return exact_mapping[normalized]

    plus_days = re.fullmatch(r"<today\+(\d+)days>", normalized, re.IGNORECASE)
    if plus_days:
        target = today + timedelta(days=int(plus_days.group(1)))
        return _format_date_value(target, "YYYY-MM-DD HH:mm:ss")

    next_month_md = re.fullmatch(r"下个?月-(\d{2})", text)
    if next_month_md:
        day = int(next_month_md.group(1))
        _, month_end = _next_month_bounds(today)
        safe_day = min(day, month_end.day)
        return f"{month_end.month:02d}-{safe_day:02d}"

    return value
