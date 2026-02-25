"""Date/time parsing and normalization helpers."""

from __future__ import annotations

import datetime
import re
from typing import Any, Dict

from dateutil import parser as date_parser


def _parse_date(value: Any, default_date: datetime.date) -> datetime.date:
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError:
            try:
                return date_parser.parse(value).date()
            except (ValueError, TypeError, OverflowError):
                return default_date
    return default_date


def _safe_build_date(year: int, month: int, day: int) -> datetime.date | None:
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def _normalize_hhmm(value: Any, fallback: str = "00:00") -> str:
    if not isinstance(value, str):
        return fallback
    text = value.strip()
    if not text:
        return fallback

    colon_match = re.fullmatch(r"([01]?\d|2[0-3])\s*:\s*([0-5]\d)", text)
    if colon_match:
        hour = int(colon_match.group(1))
        minute = int(colon_match.group(2))
        return f"{hour:02d}:{minute:02d}"

    hour_match = re.fullmatch(r"([01]?\d|2[0-3])\s*時(?:\s*([0-5]?\d)\s*分?)?", text)
    if hour_match:
        hour = int(hour_match.group(1))
        minute = int(hour_match.group(2) or 0)
        return f"{hour:02d}:{minute:02d}"

    if text in {"正午"}:
        return "12:00"
    if text in {"深夜", "真夜中"}:
        return "00:00"

    return fallback


def _extract_explicit_time(text: str) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return None

    colon_match = re.search(r"([01]?\d|2[0-3])\s*:\s*([0-5]\d)", text)
    if colon_match:
        hour = int(colon_match.group(1))
        minute = int(colon_match.group(2))
        return f"{hour:02d}:{minute:02d}"

    ampm_match = re.search(
        r"(午前|午後)\s*([0-1]?\d)\s*時(?:\s*([0-5]?\d)\s*分?)?",
        text,
    )
    if ampm_match:
        marker = ampm_match.group(1)
        hour = int(ampm_match.group(2))
        minute = int(ampm_match.group(3) or 0)
        if hour > 12 or minute > 59:
            return None
        if marker == "午後" and hour < 12:
            hour += 12
        if marker == "午前" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"

    half_match = re.search(r"([01]?\d|2[0-3])\s*時\s*半", text)
    if half_match:
        hour = int(half_match.group(1))
        return f"{hour:02d}:30"

    hour_match = re.search(r"([01]?\d|2[0-3])\s*時(?:\s*([0-5]?\d)\s*分?)?", text)
    if hour_match:
        hour = int(hour_match.group(1))
        minute = int(hour_match.group(2) or 0)
        return f"{hour:02d}:{minute:02d}"

    if "正午" in text:
        return "12:00"
    if "深夜" in text or "真夜中" in text:
        return "00:00"

    return None


def _extract_relative_time_delta(text: str) -> datetime.timedelta | None:
    if not isinstance(text, str) or not text.strip():
        return None

    hours_minutes_match = re.search(
        r"(\d+)\s*時間(?:\s*(\d+)\s*分)?\s*(後|前|まえ)",
        text,
    )
    if hours_minutes_match:
        hours = int(hours_minutes_match.group(1))
        minutes = int(hours_minutes_match.group(2) or 0)
        direction = hours_minutes_match.group(3)
        sign = -1 if direction in {"前", "まえ"} else 1
        return datetime.timedelta(minutes=sign * (hours * 60 + minutes))

    minutes_match = re.search(r"(\d+)\s*分\s*(後|前|まえ)", text)
    if minutes_match:
        minutes = int(minutes_match.group(1))
        direction = minutes_match.group(2)
        sign = -1 if direction in {"前", "まえ"} else 1
        return datetime.timedelta(minutes=sign * minutes)

    return None


def _extract_weekday(text: str) -> int | None:
    if not isinstance(text, str) or not text.strip():
        return None

    ja_match = re.search(r"(月|火|水|木|金|土|日)(?:曜(?:日)?)", text)
    if ja_match:
        return {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}.get(ja_match.group(1))

    lower = text.lower()
    weekday_tokens = {
        "monday": 0,
        "mon": 0,
        "tuesday": 1,
        "tue": 1,
        "wednesday": 2,
        "wed": 2,
        "thursday": 3,
        "thu": 3,
        "friday": 4,
        "fri": 4,
        "saturday": 5,
        "sat": 5,
        "sunday": 6,
        "sun": 6,
    }
    for token, weekday in weekday_tokens.items():
        if re.search(rf"\b{re.escape(token)}\b", lower):
            return weekday

    return None


def _extract_relative_week_shift(text: str) -> int | None:
    if not isinstance(text, str) or not text.strip():
        return None

    if "再来週" in text or "翌々週" in text:
        return 2
    if "来週" in text or "翌週" in text:
        return 1
    if "先週" in text:
        return -1
    if "今週" in text:
        return 0
    return None


def _week_bounds(anchor_date: datetime.date) -> tuple[datetime.date, datetime.date]:
    start = anchor_date - datetime.timedelta(days=anchor_date.weekday())
    end = start + datetime.timedelta(days=6)
    return start, end


def _resolve_week_period(expression: str, base_date: datetime.date) -> tuple[datetime.date, datetime.date] | None:
    if not isinstance(expression, str) or not expression.strip():
        return None

    week_shift = _extract_relative_week_shift(expression)
    if week_shift is None:
        return None
    if _extract_weekday(expression) is not None:
        return None

    current_week_monday = base_date - datetime.timedelta(days=base_date.weekday())
    start_date = current_week_monday + datetime.timedelta(weeks=week_shift)
    end_date = start_date + datetime.timedelta(days=6)
    return start_date, end_date


def _resolve_date_expression(expression: str, base_date: datetime.date) -> tuple[datetime.date | None, str]:
    if not isinstance(expression, str) or not expression.strip():
        return None, "empty"

    text = expression.strip()

    explicit_patterns = [
        r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})",
        r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日?",
    ]
    for pattern in explicit_patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        candidate = _safe_build_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if candidate:
            return candidate, "explicit_date"

    month_day_match = re.search(r"(\d{1,2})月\s*(\d{1,2})日", text)
    if month_day_match:
        month = int(month_day_match.group(1))
        day = int(month_day_match.group(2))
        candidate = _safe_build_date(base_date.year, month, day)
        if candidate and candidate < base_date:
            candidate = _safe_build_date(base_date.year + 1, month, day) or candidate
        if candidate:
            return candidate, "month_day"

    slash_month_day_match = re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)", text)
    if slash_month_day_match:
        month = int(slash_month_day_match.group(1))
        day = int(slash_month_day_match.group(2))
        candidate = _safe_build_date(base_date.year, month, day)
        if candidate and candidate < base_date:
            candidate = _safe_build_date(base_date.year + 1, month, day) or candidate
        if candidate:
            return candidate, "month_day_slash"

    relative_keywords = {
        "一昨日": -2,
        "おととい": -2,
        "昨日": -1,
        "きのう": -1,
        "今日": 0,
        "本日": 0,
        "きょう": 0,
        "明日": 1,
        "あした": 1,
        "明後日": 2,
        "あさって": 2,
    }
    for token, offset in relative_keywords.items():
        if token in text:
            return base_date + datetime.timedelta(days=offset), "relative_keyword"

    day_shift_match = re.search(r"(\d+)\s*日\s*(後|前|まえ)", text)
    if day_shift_match:
        days = int(day_shift_match.group(1))
        direction = day_shift_match.group(2)
        sign = -1 if direction in {"前", "まえ"} else 1
        return base_date + datetime.timedelta(days=sign * days), "relative_day"

    week_shift_match = re.search(r"(\d+)\s*(?:週間|週)\s*(後|前|まえ)", text)
    if week_shift_match:
        weeks = int(week_shift_match.group(1))
        direction = week_shift_match.group(2)
        sign = -1 if direction in {"前", "まえ"} else 1
        return base_date + datetime.timedelta(days=sign * weeks * 7), "relative_week_count"

    week_shift = _extract_relative_week_shift(text)
    if week_shift is not None:
        weekday = _extract_weekday(text)
        if weekday is None:
            weekday = 0
        current_week_monday = base_date - datetime.timedelta(days=base_date.weekday())
        return current_week_monday + datetime.timedelta(weeks=week_shift, days=weekday), "relative_week"

    weekday = _extract_weekday(text)
    if weekday is not None and ("次の" in text or "今度の" in text):
        days_ahead = (weekday - base_date.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return base_date + datetime.timedelta(days=days_ahead), "next_weekday"

    if weekday is not None:
        days_ahead = (weekday - base_date.weekday()) % 7
        if days_ahead == 0 and "今週" not in text and "今日" not in text and "本日" not in text:
            days_ahead = 7
        return base_date + datetime.timedelta(days=days_ahead), "weekday"

    try:
        parsed = date_parser.parse(
            text,
            default=datetime.datetime.combine(base_date, datetime.time(hour=0, minute=0)),
        )
        return parsed.date(), "dateutil_parse"
    except (ValueError, TypeError, OverflowError):
        return None, "unresolved"


def _resolve_schedule_expression(
    expression: Any,
    base_date: datetime.date,
    base_time: str = "00:00",
    default_time: str = "00:00",
) -> Dict[str, Any]:
    text = str(expression).strip() if expression is not None else ""
    if not text:
        return {"ok": False, "error": "expression が空です。"}

    normalized_base_time = _normalize_hhmm(base_time, "00:00")
    normalized_default_time = _normalize_hhmm(default_time, normalized_base_time)
    base_hour, base_minute = [int(part) for part in normalized_base_time.split(":")]
    base_datetime = datetime.datetime.combine(
        base_date, datetime.time(hour=base_hour, minute=base_minute)
    )

    weekday_names_ja = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]

    relative_time_delta = _extract_relative_time_delta(text)
    if relative_time_delta is not None:
        resolved_datetime = base_datetime + relative_time_delta
        return {
            "ok": True,
            "date": resolved_datetime.date().isoformat(),
            "time": resolved_datetime.strftime("%H:%M"),
            "datetime": resolved_datetime.strftime("%Y-%m-%dT%H:%M"),
            "weekday": weekday_names_ja[resolved_datetime.weekday()],
            "source": "relative_time_delta",
        }

    resolved_date, date_source = _resolve_date_expression(text, base_date)
    if resolved_date is None:
        return {
            "ok": False,
            "error": f"日付表現を解釈できませんでした: {text}",
        }

    explicit_time = _extract_explicit_time(text)
    resolved_time = explicit_time or normalized_default_time
    resolved_datetime = datetime.datetime.strptime(
        f"{resolved_date.isoformat()} {resolved_time}",
        "%Y-%m-%d %H:%M",
    )

    source = date_source if not explicit_time else f"{date_source}+explicit_time"
    response: Dict[str, Any] = {
        "ok": True,
        "date": resolved_date.isoformat(),
        "time": resolved_time,
        "datetime": resolved_datetime.strftime("%Y-%m-%dT%H:%M"),
        "weekday": weekday_names_ja[resolved_date.weekday()],
        "source": source,
    }

    week_period = _resolve_week_period(text, base_date)
    if week_period is not None:
        period_start, period_end = week_period
        response["period_start"] = period_start.isoformat()
        response["period_end"] = period_end.isoformat()

    return response


def _is_relative_datetime_text(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False

    relative_tokens = [
        "今日",
        "本日",
        "明日",
        "明後日",
        "昨日",
        "一昨日",
        "来週",
        "再来週",
        "先週",
        "今週",
        "次の",
        "今度の",
        "きょう",
        "あした",
        "あさって",
        "きのう",
        "おととい",
    ]
    if any(token in text for token in relative_tokens):
        return True

    if re.search(r"(\d+)\s*(日|週|週間|時間|分)\s*(後|前|まえ)", text):
        return True

    if re.search(r"(月|火|水|木|金|土|日)(?:曜(?:日)?)", text):
        return True

    lower = text.lower()
    if re.search(
        r"\b(mon(day)?|tue(sday)?|wed(nesday)?|thu(rsday)?|fri(day)?|sat(urday)?|sun(day)?)\b",
        lower,
    ):
        return True

    return False


def _bool_from_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _try_parse_iso_date(value: Any) -> datetime.date | None:
    if isinstance(value, datetime.date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


_WEEKDAY_NAMES_JA = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]


def _calc_date_offset(base_date: datetime.date, offset_days: int) -> Dict[str, Any]:
    """base_date から offset_days 日後（負なら前）の日付を返す。"""
    result = base_date + datetime.timedelta(days=offset_days)
    return {
        "ok": True,
        "date": result.isoformat(),
        "weekday": _WEEKDAY_NAMES_JA[result.weekday()],
    }


def _calc_month_boundary(year: int, month: int, boundary: str) -> Dict[str, Any]:
    """指定月の月初(start)または月末(end)を返す。"""
    if month < 1 or month > 12:
        return {"ok": False, "error": f"month は 1〜12 で指定してください: {month}"}
    if boundary == "start":
        result = datetime.date(year, month, 1)
    elif boundary == "end":
        if month == 12:
            result = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
        else:
            result = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
    else:
        return {"ok": False, "error": f"boundary は 'start' または 'end' を指定してください: {boundary}"}
    return {
        "ok": True,
        "date": result.isoformat(),
        "weekday": _WEEKDAY_NAMES_JA[result.weekday()],
    }


def _calc_nearest_weekday(
    base_date: datetime.date, weekday: int, direction: str,
) -> Dict[str, Any]:
    """base_date から最も近い指定曜日を forward/backward で探す。当日が該当なら当日を返す。"""
    if weekday < 0 or weekday > 6:
        return {"ok": False, "error": f"weekday は 0(月)〜6(日) で指定してください: {weekday}"}
    current_wd = base_date.weekday()
    if current_wd == weekday:
        return {"ok": True, "date": base_date.isoformat(), "weekday": _WEEKDAY_NAMES_JA[weekday]}
    if direction == "forward":
        diff = (weekday - current_wd) % 7
    elif direction == "backward":
        diff = -((current_wd - weekday) % 7)
    else:
        return {"ok": False, "error": f"direction は 'forward' または 'backward' を指定してください: {direction}"}
    result = base_date + datetime.timedelta(days=diff)
    return {"ok": True, "date": result.isoformat(), "weekday": _WEEKDAY_NAMES_JA[result.weekday()]}


def _calc_week_weekday(
    base_date: datetime.date, week_offset: int, weekday: int,
) -> Dict[str, Any]:
    """base_date の週から week_offset 週後(負なら前)の指定曜日を返す。"""
    if weekday < 0 or weekday > 6:
        return {"ok": False, "error": f"weekday は 0(月)〜6(日) で指定してください: {weekday}"}
    current_monday = base_date - datetime.timedelta(days=base_date.weekday())
    target_monday = current_monday + datetime.timedelta(weeks=week_offset)
    result = target_monday + datetime.timedelta(days=weekday)
    return {"ok": True, "date": result.isoformat(), "weekday": _WEEKDAY_NAMES_JA[result.weekday()]}


def _calc_week_range(base_date: datetime.date) -> Dict[str, Any]:
    """base_date が含まれる週の月曜〜日曜の範囲を返す。"""
    monday = base_date - datetime.timedelta(days=base_date.weekday())
    sunday = monday + datetime.timedelta(days=6)
    return {
        "ok": True,
        "period_start": monday.isoformat(),
        "period_start_weekday": _WEEKDAY_NAMES_JA[monday.weekday()],
        "period_end": sunday.isoformat(),
        "period_end_weekday": _WEEKDAY_NAMES_JA[sunday.weekday()],
    }


def _calc_time_offset(
    base_date: datetime.date, base_time: str, offset_minutes: int,
) -> Dict[str, Any]:
    """base_date + base_time から offset_minutes 分加減算する。日跨ぎも対応。"""
    normalized = _normalize_hhmm(base_time, "")
    if not normalized:
        return {"ok": False, "error": f"base_time の形式が不正です: {base_time}"}
    hour, minute = (int(p) for p in normalized.split(":"))
    base_dt = datetime.datetime.combine(base_date, datetime.time(hour, minute))
    result_dt = base_dt + datetime.timedelta(minutes=offset_minutes)
    return {
        "ok": True,
        "date": result_dt.date().isoformat(),
        "time": result_dt.strftime("%H:%M"),
        "weekday": _WEEKDAY_NAMES_JA[result_dt.weekday()],
    }


def _get_date_info(target_date: datetime.date) -> Dict[str, Any]:
    """日付の曜日等の情報を返す。"""
    return {
        "ok": True,
        "date": target_date.isoformat(),
        "weekday": _WEEKDAY_NAMES_JA[target_date.weekday()],
        "year": target_date.year,
        "month": target_date.month,
        "day": target_date.day,
    }


def _requires_date_resolution(value: Any) -> bool:
    """YYYY-MM-DD 形式でなければ日付解決が必要と判定する。"""
    if not isinstance(value, str) or not value.strip():
        return False
    return re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()) is None


__all__ = [
    "_parse_date",
    "_normalize_hhmm",
    "_resolve_schedule_expression",
    "_is_relative_datetime_text",
    "_requires_date_resolution",
    "_bool_from_value",
    "_extract_weekday",
    "_extract_relative_week_shift",
    "_week_bounds",
    "_try_parse_iso_date",
    "_calc_date_offset",
    "_calc_month_boundary",
    "_calc_nearest_weekday",
    "_calc_week_weekday",
    "_calc_week_range",
    "_calc_time_offset",
    "_get_date_info",
]
