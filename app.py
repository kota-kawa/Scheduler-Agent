import calendar
import datetime
import json
import os
import re
import threading
from urllib.parse import urlencode, urlparse
from typing import Any, Dict, Iterator, List, Union

from dateutil import parser as date_parser
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Column, Text, delete
from sqlmodel import Field, Relationship, SQLModel, Session, create_engine, select
try:
    from starlette.middleware.proxy_headers import ProxyHeadersMiddleware
except ModuleNotFoundError:  # pragma: no cover - fallback for older/newer Starlette
    class ProxyHeadersMiddleware:  # type: ignore[no-redef]
        def __init__(self, app, trusted_hosts="*"):
            self.app = app

        async def __call__(self, scope, receive, send):
            await self.app(scope, receive, send)

from starlette.middleware.sessions import SessionMiddleware

from llm_client import (
    UnifiedClient,
    _content_to_text,
    call_scheduler_llm,
)
from model_selection import apply_model_selection, current_available_models, update_override

# 日本語: secrets.env から環境変数を読み込む / English: Load environment variables from secrets.env
load_dotenv("secrets.env")

# 日本語: アプリのベースディレクトリ / English: Base directory for resolving paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 日本語: PostgreSQL 接続文字列（未設定ならローカル既定値） / English: PostgreSQL URL with local fallback
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://scheduler:scheduler@localhost:5432/scheduler",
)

# 日本語: PostgreSQL 専用の SQLAlchemy エンジンを構築 / English: Build a PostgreSQL-only SQLAlchemy engine
def _build_engine(database_url: str):
    normalized_url = database_url
    if normalized_url.startswith("postgres://"):
        normalized_url = normalized_url.replace("postgres://", "postgresql+psycopg2://", 1)
    if not normalized_url.startswith("postgresql"):
        raise ValueError("DATABASE_URL must be PostgreSQL (postgresql+psycopg2://...).")
    return create_engine(normalized_url)


# 日本語: DB エンジンと初期化フラグ / English: DB engine and init guard
engine = _build_engine(DATABASE_URL)
_db_initialized = False
_db_init_lock = threading.Lock()

# 日本語: ルーチン（習慣）モデル / English: Routine (habit) model
class Routine(SQLModel, table=True):
    __tablename__ = "routine"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    days: str = Field(default="0,1,2,3,4", max_length=50)
    description: str | None = Field(default=None, max_length=200)
    steps: list["Step"] = Relationship(
        back_populates="routine", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

# 日本語: ルーチン内のステップモデル / English: Step model inside a routine
class Step(SQLModel, table=True):
    __tablename__ = "step"

    id: int | None = Field(default=None, primary_key=True)
    routine_id: int = Field(foreign_key="routine.id")
    name: str = Field(max_length=100)
    time: str = Field(default="00:00", max_length=10)
    category: str = Field(default="Other", max_length=50)
    memo: str | None = Field(default=None, max_length=200)

    routine: Routine | None = Relationship(back_populates="steps")

# 日本語: 日次ステップログ / English: Daily log for each step
class DailyLog(SQLModel, table=True):
    __tablename__ = "daily_log"

    id: int | None = Field(default=None, primary_key=True)
    date: datetime.date
    step_id: int = Field(foreign_key="step.id")
    done: bool = Field(default=False)
    memo: str | None = Field(default=None, max_length=200)

    step: Step | None = Relationship()

# 日本語: 任意のカスタムタスク / English: Ad-hoc custom task
class CustomTask(SQLModel, table=True):
    __tablename__ = "custom_task"

    id: int | None = Field(default=None, primary_key=True)
    date: datetime.date
    name: str = Field(max_length=100)
    time: str = Field(default="00:00", max_length=10)
    done: bool = Field(default=False)
    memo: str | None = Field(default=None, max_length=200)

# 日本語: 日報（1日単位のメモ） / English: Day log (daily memo)
class DayLog(SQLModel, table=True):
    __tablename__ = "day_log"

    id: int | None = Field(default=None, primary_key=True)
    date: datetime.date
    content: str | None = Field(default=None, sa_column=Column(Text))

# 日本語: チャット履歴 / English: Chat history storage
class ChatHistory(SQLModel, table=True):
    __tablename__ = "chat_history"

    id: int | None = Field(default=None, primary_key=True)
    role: str = Field(max_length=20)
    content: str = Field(sa_column=Column(Text, nullable=False))
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.now)

# 日本語: 評価用の結果ログ / English: Evaluation result storage
class EvaluationResult(SQLModel, table=True):
    __tablename__ = "evaluation_result"

    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.now)
    model_name: str | None = Field(default=None, max_length=100)
    task_prompt: str | None = Field(default=None, sa_column=Column(Text))
    agent_reply: str | None = Field(default=None, sa_column=Column(Text))
    tool_calls: str | None = Field(default=None, sa_column=Column(Text))
    is_success: bool | None = Field(default=None)
    comments: str | None = Field(default=None, sa_column=Column(Text))

# 日本語: FastAPI アプリ本体 / English: Main FastAPI application
app = FastAPI(root_path=os.getenv("PROXY_PREFIX", ""))
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

if not os.getenv("SESSION_SECRET"):
    raise ValueError("SESSION_SECRET environment variable is not set. Please set it in secrets.env.")

# 日本語: セッションでフラッシュメッセージを扱う / English: Enable session storage for flash messages
app.add_middleware(SessionMiddleware, secret_key=os.environ["SESSION_SECRET"])

# 日本語: 静的ファイルとテンプレートの設定 / English: Static files and template setup
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


# 日本語: 起動時にDBスキーマを一度だけ作成 / English: Create DB schema once at startup
def _ensure_db_initialized() -> None:
    global _db_initialized
    if _db_initialized:
        return
    with _db_init_lock:
        if _db_initialized:
            return
        SQLModel.metadata.create_all(bind=engine)
        _db_initialized = True


@app.on_event("startup")
def _init_db() -> None:
    # 日本語: アプリ起動時のDB初期化 / English: Initialize DB on app startup
    _ensure_db_initialized()


def create_session() -> Session:
    # 日本語: 背景タスク等で直接セッション生成 / English: Create a session for background usage
    _ensure_db_initialized()
    return Session(engine)


def get_db() -> Iterator[Session]:
    # 日本語: FastAPI の依存性注入用 DB セッション / English: DB session dependency for FastAPI
    _ensure_db_initialized()
    with Session(engine) as db:
        yield db


def flash(request: Request, message: str) -> None:
    # 日本語: セッションにフラッシュメッセージを追加 / English: Add a flash message to session
    flashes = request.session.setdefault("_flashes", [])
    flashes.append(message)
    request.session["_flashes"] = flashes


def pop_flashed_messages(request: Request) -> List[str]:
    # 日本語: フラッシュメッセージを取得し削除 / English: Pop and clear flash messages
    return request.session.pop("_flashes", [])


@app.get("/api/flash", name="api_flash")
def api_flash(request: Request):
    # 日本語: フラッシュメッセージ取得API / English: API to retrieve flash messages
    return {"messages": pop_flashed_messages(request)}


def template_response(request: Request, template_name: str, context: Dict[str, Any]) -> HTMLResponse:
    # 日本語: Jinja テンプレートへ共通コンテキストを付与 / English: Render template with shared context
    payload = dict(context)
    payload.setdefault("request", request)

    # 日本語: 逆プロキシ配下でもURL生成が崩れないように補正 / English: Adjust URL generation for reverse proxy
    forwarded_prefix = (request.headers.get("x-forwarded-prefix") or "").strip()
    if "," in forwarded_prefix:
        forwarded_prefix = forwarded_prefix.split(",", 1)[0].strip()
    proxy_prefix = forwarded_prefix or request.scope.get("root_path", "")
    if proxy_prefix and not proxy_prefix.startswith("/"):
        proxy_prefix = f"/{proxy_prefix}"
    proxy_prefix = proxy_prefix.rstrip("/") if proxy_prefix not in {"", "/"} else ""

    payload.setdefault("proxy_prefix", proxy_prefix)

    def _apply_proxy_prefix(path: str) -> str:
        if not proxy_prefix:
            return path
        if path.startswith(proxy_prefix):
            return path
        return f"{proxy_prefix}{path}"

    def _url_for(endpoint: str, **values: Any) -> str:
        param_names: set[str] = set()
        for route in request.app.router.routes:
            if getattr(route, "name", None) == endpoint:
                param_names = set(getattr(route, "param_convertors", {}).keys())
                break
        if values and not param_names:
            try:
                raw_url = str(request.url_for(endpoint, **values))
                parsed = urlparse(raw_url)
                path = parsed.path or "/"
                query = parsed.query
                path = _apply_proxy_prefix(path)
                return f"{path}?{query}" if query else path
            except Exception:
                pass
        path_params = {k: v for k, v in values.items() if k in param_names}
        query_params = {k: v for k, v in values.items() if k not in param_names}
        raw_url = str(request.url_for(endpoint, **path_params))
        parsed = urlparse(raw_url)
        path = parsed.path or "/"
        path = _apply_proxy_prefix(path)
        if query_params:
            return f"{path}?{urlencode(query_params)}"
        return path

    payload.setdefault("url_for", _url_for)
    payload.setdefault("get_flashed_messages", lambda: pop_flashed_messages(request))
    return templates.TemplateResponse(template_name, payload)


# 日本語: ヘルパー群 / English: Helper functions

def get_weekday_routines(db: Session, weekday_int: int) -> List[Routine]:
    # 日本語: 曜日（0=月）に紐づくルーチン一覧 / English: Routines scheduled for the given weekday
    all_routines = db.exec(select(Routine)).all()
    matched = []
    for r in all_routines:
        if str(weekday_int) in (r.days or "").split(","):
            matched.append(r)
    return matched


def _parse_date(value: Any, default_date: datetime.date) -> datetime.date:
    # 日本語: 多様な入力を安全に日付へ変換 / English: Safely coerce inputs into a date
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
    # 日本語: 例外なく日付を生成 / English: Build a date safely without raising
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def _normalize_hhmm(value: Any, fallback: str = "00:00") -> str:
    # 日本語: 時刻文字列を HH:MM に正規化 / English: Normalize time strings to HH:MM
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
    # 日本語: テキスト中の明示時刻を抽出 / English: Extract explicit time from text
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
    # 日本語: 「2時間後」等を差分へ変換 / English: Parse relative time phrases into timedelta
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
    # 日本語: 曜日トークンを 0=月..6=日 へ変換 / English: Convert weekday token to 0=Mon..6=Sun
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


def _resolve_date_expression(expression: str, base_date: datetime.date) -> tuple[datetime.date | None, str]:
    # 日本語: 相対/絶対日付表現を日付へ解決 / English: Resolve relative/absolute date expression into date
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

    week_shift = None
    if "再来週" in text or "翌々週" in text:
        week_shift = 2
    elif "来週" in text or "翌週" in text:
        week_shift = 1
    elif "先週" in text:
        week_shift = -1
    elif "今週" in text:
        week_shift = 0

    if week_shift is not None:
        weekday = _extract_weekday(text)
        if weekday is None:
            weekday = base_date.weekday()
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
    # 日本語: 相対日時表現を絶対日時に解決 / English: Resolve relative date/time expression to absolute datetime
    text = str(expression).strip() if expression is not None else ""
    if not text:
        return {"ok": False, "error": "expression が空です。"}

    normalized_base_time = _normalize_hhmm(base_time, "00:00")
    normalized_default_time = _normalize_hhmm(default_time, normalized_base_time)
    base_hour, base_minute = [int(part) for part in normalized_base_time.split(":")]
    base_datetime = datetime.datetime.combine(
        base_date, datetime.time(hour=base_hour, minute=base_minute)
    )

    relative_time_delta = _extract_relative_time_delta(text)
    if relative_time_delta is not None:
        resolved_datetime = base_datetime + relative_time_delta
        return {
            "ok": True,
            "date": resolved_datetime.date().isoformat(),
            "time": resolved_datetime.strftime("%H:%M"),
            "datetime": resolved_datetime.strftime("%Y-%m-%dT%H:%M"),
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
    return {
        "ok": True,
        "date": resolved_date.isoformat(),
        "time": resolved_time,
        "datetime": resolved_datetime.strftime("%Y-%m-%dT%H:%M"),
        "source": source,
    }


def _is_relative_datetime_text(value: Any) -> bool:
    # 日本語: 相対日時表現らしさを判定 / English: Detect likely relative date/time expression
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
    # 日本語: 文字列/数値を boolean に正規化 / English: Normalize string/number to boolean
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


def _remove_no_schedule_lines(text: str) -> str:
    # 日本語: 「予定なし」を含む行を最終返信から除去 / English: Remove lines that include "no schedule" from replies
    if not isinstance(text, str):
        return str(text)

    filtered_lines = []
    for line in text.splitlines():
        # 日本語: 文脈付き（例: 「2/12 予定なし」）でも確実に除去 / English: Remove contextual variants like "2/12 no schedule"
        if re.search(r"予定\s*(?:な\s*し|無し)", line):
            continue
        filtered_lines.append(line)

    cleaned = "\n".join(filtered_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def _get_timeline_data(db: Session, date_obj: datetime.date):
    # 日本語: 日付のタイムライン項目と達成率を構築 / English: Build timeline items and completion rate
    routines = get_weekday_routines(db, date_obj.weekday())
    custom_tasks = db.exec(select(CustomTask).where(CustomTask.date == date_obj)).all()

    timeline_items = []
    total_items = 0
    completed_items = 0

    for r in routines:
        for s in r.steps:
            log = db.exec(
                select(DailyLog).where(DailyLog.date == date_obj, DailyLog.step_id == s.id)
            ).first()
            timeline_items.append(
                {
                    "type": "routine",
                    "routine": r,
                    "step": s,
                    "log": log,
                    "time": s.time,
                    "id": s.id,
                }
            )
            total_items += 1
            if log and log.done:
                completed_items += 1

    for ct in custom_tasks:
        timeline_items.append(
            {
                "type": "custom",
                "routine": {"name": "Personal"},
                "step": {"name": ct.name, "category": "Custom", "id": ct.id},
                "log": {"done": ct.done, "memo": ct.memo},
                "time": ct.time,
                "id": ct.id,
                "real_obj": ct,
            }
        )
        total_items += 1
        if ct.done:
            completed_items += 1

    timeline_items.sort(key=lambda x: x["time"])

    completion_rate = 0
    if total_items > 0:
        completion_rate = int((completed_items / total_items) * 100)

    return timeline_items, completion_rate


def _build_scheduler_context(db: Session, today: datetime.date | None = None) -> str:
    # 日本語: LLM へ渡す当日コンテキストを生成 / English: Build LLM context for the scheduler
    today = today or datetime.date.today()
    routines = db.exec(select(Routine)).all()
    today_logs = {
        log.step_id: log for log in db.exec(select(DailyLog).where(DailyLog.date == today)).all()
    }
    custom_tasks = db.exec(select(CustomTask).where(CustomTask.date == today)).all()

    recent_day_logs = []
    for i in range(3):
        d = today - datetime.timedelta(days=i)
        dl = db.exec(select(DayLog).where(DayLog.date == d)).first()
        if dl and dl.content:
            recent_day_logs.append(f"Date: {d.isoformat()} | Content: {dl.content}")

    routine_lines = []
    for r in routines:
        days_label = r.days or ""
        steps = (
            ", ".join(
                f"[{s.id}] {s.time} {s.name} ({s.category})"
                for s in sorted(r.steps, key=lambda item: item.time)
            )
            or "no steps"
        )
        routine_lines.append(f"- Routine {r.id}: {r.name} | days={days_label} | {steps}")

    custom_lines = []
    for task in sorted(custom_tasks, key=lambda t: t.time):
        memo = f" memo={task.memo}" if task.memo else ""
        custom_lines.append(
            f"- CustomTask {task.id}: {task.time} {task.name} done={task.done}{memo}"
        )

    log_lines = []
    for step_id, log in today_logs.items():
        memo = f" memo={log.memo}" if log.memo else ""
        log_lines.append(f"- StepLog step_id={step_id} done={log.done}{memo}")

    context_parts = [
        f"today_date: {today.isoformat()}",
        "routines:",
        *routine_lines,
        "today_custom_tasks:",
        *(custom_lines or ["(none)"]),
        "today_step_logs:",
        *(log_lines or ["(none)"]),
        "recent_day_logs:",
        *(recent_day_logs or ["(none)"]),
    ]
    return "\n".join(context_parts)


def _apply_actions(db: Session, actions: List[Dict[str, Any]], default_date: datetime.date):
    # 日本語: LLM のアクション指示を DB へ適用 / English: Apply LLM action directives to the DB
    results = []
    errors = []
    modified_ids = []
    dirty = False

    if not isinstance(actions, list) or not actions:
        return results, errors, modified_ids

    try:
        # 日本語: アクション種別ごとに処理を分岐 / English: Dispatch by action type
        for action in actions:
            if not isinstance(action, dict):
                continue
            action_type = action.get("type")

            if action_type == "resolve_schedule_expression":
                expression = action.get("expression")
                if not isinstance(expression, str) or not expression.strip():
                    errors.append("resolve_schedule_expression: expression が指定されていません。")
                    continue
                base_date_value = _parse_date(action.get("base_date"), default_date)
                fallback_base_time = datetime.datetime.now().strftime("%H:%M")
                base_time_value = _normalize_hhmm(action.get("base_time"), fallback_base_time)
                default_time_value = _normalize_hhmm(
                    action.get("default_time"),
                    base_time_value,
                )
                calc = _resolve_schedule_expression(
                    expression=expression,
                    base_date=base_date_value,
                    base_time=base_time_value,
                    default_time=default_time_value,
                )
                if not calc.get("ok"):
                    errors.append(
                        "resolve_schedule_expression: "
                        + str(calc.get("error") or "日時の計算に失敗しました。")
                    )
                    continue
                results.append(
                    "計算結果: "
                    f"expression={expression.strip()} "
                    f"date={calc.get('date')} "
                    f"time={calc.get('time')} "
                    f"datetime={calc.get('datetime')} "
                    f"source={calc.get('source')}"
                )
                continue

            if action_type == "create_custom_task":
                name = action.get("name")
                if not isinstance(name, str) or not name.strip():
                    errors.append("create_custom_task: name が指定されていません。")
                    continue
                raw_date_value = action.get("date")
                if _is_relative_datetime_text(raw_date_value):
                    errors.append(
                        "create_custom_task: date に相対表現が含まれています。"
                        " resolve_schedule_expression で先に絶対日時へ変換してください。"
                    )
                    continue
                raw_time_value = action.get("time")
                if _is_relative_datetime_text(raw_time_value):
                    errors.append(
                        "create_custom_task: time に相対表現が含まれています。"
                        " resolve_schedule_expression で先に絶対日時へ変換してください。"
                    )
                    continue
                date_value = _parse_date(raw_date_value, default_date)
                time_value = raw_time_value if isinstance(raw_time_value, str) else "00:00"
                memo = action.get("memo") if isinstance(action.get("memo"), str) else ""
                new_task = CustomTask(
                    date=date_value, name=name.strip(), time=time_value.strip(), memo=memo.strip()
                )
                db.add(new_task)
                db.flush()
                results.append(
                    f"カスタムタスク「{new_task.name}」(ID: {new_task.id}) を {date_value} の {new_task.time} に追加しました。"
                )
                modified_ids.append(f"item_custom_{new_task.id}")
                dirty = True
                continue

            if action_type == "delete_custom_task":
                task_id = action.get("task_id")
                try:
                    task_id_int = int(task_id)
                except (TypeError, ValueError):
                    errors.append("delete_custom_task: task_id が不正です。")
                    continue
                task_obj = db.get(CustomTask, task_id_int)
                if not task_obj:
                    errors.append(f"task_id={task_id_int} が見つかりませんでした。")
                    continue
                db.delete(task_obj)
                results.append(f"カスタムタスク「{task_obj.name}」を削除しました。")
                dirty = True
                continue

            if action_type == "toggle_step":
                step_id = action.get("step_id")
                try:
                    step_id_int = int(step_id)
                except (TypeError, ValueError):
                    errors.append("toggle_step: step_id が不正です。")
                    continue
                step_obj = db.get(Step, step_id_int)
                if not step_obj:
                    errors.append(f"step_id={step_id_int} が見つかりませんでした。")
                    continue
                raw_date_value = action.get("date")
                if _is_relative_datetime_text(raw_date_value):
                    errors.append(
                        "toggle_step: date に相対表現が含まれています。"
                        " resolve_schedule_expression で先に絶対日付へ変換してください。"
                    )
                    continue
                date_value = _parse_date(raw_date_value, default_date)
                log = db.exec(
                    select(DailyLog).where(
                        DailyLog.date == date_value, DailyLog.step_id == step_obj.id
                    )
                ).first()
                if not log:
                    log = DailyLog(date=date_value, step_id=step_obj.id)
                    db.add(log)
                log.done = _bool_from_value(action.get("done"), True)
                memo = action.get("memo")
                if isinstance(memo, str):
                    log.memo = memo.strip()
                results.append(
                    f"ステップ「{step_obj.name}」({date_value}) を {'完了' if log.done else '未完了'} に更新しました。"
                )
                modified_ids.append(f"item_routine_{step_obj.id}")
                dirty = True
                continue

            if action_type == "toggle_custom_task":
                task_id = action.get("task_id")
                try:
                    task_id_int = int(task_id)
                except (TypeError, ValueError):
                    errors.append("toggle_custom_task: task_id が不正です。")
                    continue
                task_obj = db.get(CustomTask, task_id_int)
                if not task_obj:
                    errors.append(f"task_id={task_id_int} が見つかりませんでした。")
                    continue
                task_obj.done = _bool_from_value(action.get("done"), True)
                memo = action.get("memo")
                if isinstance(memo, str):
                    task_obj.memo = memo.strip()
                results.append(
                    f"カスタムタスク「{task_obj.name}」を {'完了' if task_obj.done else '未完了'} に更新しました。"
                )
                modified_ids.append(f"item_custom_{task_obj.id}")
                dirty = True
                continue

            if action_type == "update_custom_task_time":
                task_id = action.get("task_id")
                new_time = action.get("new_time")
                if not new_time:
                    errors.append("update_custom_task_time: new_time が指定されていません。")
                    continue
                try:
                    task_id_int = int(task_id)
                except (TypeError, ValueError):
                    errors.append("update_custom_task_time: task_id が不正です。")
                    continue
                task_obj = db.get(CustomTask, task_id_int)
                if not task_obj:
                    errors.append(f"task_id={task_id_int} が見つかりませんでした。")
                    continue
                task_obj.time = new_time.strip()
                results.append(f"カスタムタスク「{task_obj.name}」の時刻を {task_obj.time} に更新しました。")
                modified_ids.append(f"item_custom_{task_obj.id}")
                dirty = True
                continue

            if action_type == "rename_custom_task":
                task_id = action.get("task_id")
                new_name = action.get("new_name")
                if not new_name:
                    errors.append("rename_custom_task: new_name が指定されていません。")
                    continue
                try:
                    task_id_int = int(task_id)
                except (TypeError, ValueError):
                    errors.append("rename_custom_task: task_id が不正です。")
                    continue
                task_obj = db.get(CustomTask, task_id_int)
                if not task_obj:
                    errors.append(f"task_id={task_id_int} が見つかりませんでした。")
                    continue
                old_name = task_obj.name
                task_obj.name = new_name.strip()
                results.append(f"カスタムタスク「{old_name}」の名前を「{task_obj.name}」に更新しました。")
                modified_ids.append(f"item_custom_{task_obj.id}")
                dirty = True
                continue

            if action_type == "update_custom_task_memo":
                task_id = action.get("task_id")
                new_memo = action.get("new_memo")
                if new_memo is None:
                    errors.append("update_custom_task_memo: new_memo が指定されていません。")
                    continue
                try:
                    task_id_int = int(task_id)
                except (TypeError, ValueError):
                    errors.append("update_custom_task_memo: task_id が不正です。")
                    continue
                task_obj = db.get(CustomTask, task_id_int)
                if not task_obj:
                    errors.append(f"task_id={task_id_int} が見つかりませんでした。")
                    continue
                task_obj.memo = new_memo.strip()
                results.append(f"カスタムタスク「{task_obj.name}」のメモを更新しました。")
                modified_ids.append(f"item_custom_{task_obj.id}")
                dirty = True
                continue

            if action_type == "update_log":
                content = action.get("content")
                if not isinstance(content, str) or not content.strip():
                    errors.append("update_log: content が指定されていません。")
                    continue
                raw_date_value = action.get("date")
                if _is_relative_datetime_text(raw_date_value):
                    errors.append(
                        "update_log: date に相対表現が含まれています。"
                        " resolve_schedule_expression で先に絶対日付へ変換してください。"
                    )
                    continue
                date_value = _parse_date(raw_date_value, default_date)
                day_log = db.exec(select(DayLog).where(DayLog.date == date_value)).first()
                if not day_log:
                    day_log = DayLog(date=date_value)
                    db.add(day_log)
                day_log.content = content.strip()
                results.append(f"{date_value} の日報を更新しました。")
                modified_ids.append("daily-log-card")
                dirty = True
                continue

            if action_type == "append_day_log":
                content = action.get("content")
                if not isinstance(content, str) or not content.strip():
                    errors.append("append_day_log: content が指定されていません。")
                    continue
                raw_date_value = action.get("date")
                if _is_relative_datetime_text(raw_date_value):
                    errors.append(
                        "append_day_log: date に相対表現が含まれています。"
                        " resolve_schedule_expression で先に絶対日付へ変換してください。"
                    )
                    continue
                date_value = _parse_date(raw_date_value, default_date)
                day_log = db.exec(select(DayLog).where(DayLog.date == date_value)).first()
                if not day_log:
                    day_log = DayLog(date=date_value)
                    day_log.content = content.strip()
                    db.add(day_log)
                else:
                    current_content = day_log.content or ""
                    if current_content:
                        day_log.content = current_content + "\n" + content.strip()
                    else:
                        day_log.content = content.strip()

                results.append(f"{date_value} の日報に追記しました。")
                modified_ids.append("daily-log-card")
                dirty = True
                continue

            if action_type == "get_day_log":
                raw_date_value = action.get("date")
                if _is_relative_datetime_text(raw_date_value):
                    errors.append(
                        "get_day_log: date に相対表現が含まれています。"
                        " resolve_schedule_expression で先に絶対日付へ変換してください。"
                    )
                    continue
                date_value = _parse_date(raw_date_value, default_date)
                day_log = db.exec(select(DayLog).where(DayLog.date == date_value)).first()
                if day_log and day_log.content:
                    results.append(f"{date_value} の日報:\n{day_log.content}")
                else:
                    results.append(f"{date_value} の日報は見つかりませんでした。")
                continue

            if action_type == "add_routine":
                name = action.get("name")
                if not name:
                    errors.append("add_routine: name is required")
                    continue
                days = action.get("days", "0,1,2,3,4")
                desc = action.get("description", "")
                r = Routine(name=name, days=days, description=desc)
                db.add(r)
                db.flush()
                results.append(f"ルーチン「{name}」(ID: {r.id}) を追加しました。")
                dirty = True
                continue

            if action_type == "delete_routine":
                rid = action.get("routine_id")
                r = db.get(Routine, int(rid)) if rid else None
                if r:
                    db.delete(r)
                    results.append(f"ルーチン「{r.name}」を削除しました。")
                    dirty = True
                else:
                    errors.append("delete_routine: not found")
                continue

            if action_type == "update_routine_days":
                routine_id = action.get("routine_id")
                new_days = action.get("new_days")
                if not new_days:
                    errors.append("update_routine_days: new_days が指定されていません。")
                    continue
                try:
                    routine_id_int = int(routine_id)
                except (TypeError, ValueError):
                    errors.append("update_routine_days: routine_id が不正です。")
                    continue
                routine_obj = db.get(Routine, routine_id_int)
                if not routine_obj:
                    errors.append(f"routine_id={routine_id_int} が見つかりませんでした。")
                    continue
                routine_obj.days = new_days.strip()
                results.append(f"ルーチン「{routine_obj.name}」の曜日を {routine_obj.days} に更新しました。")
                dirty = True
                continue

            if action_type == "add_step":
                rid = action.get("routine_id")
                name = action.get("name")
                if not rid or not name:
                    errors.append("add_step: routine_id and name required")
                    continue
                s = Step(
                    routine_id=int(rid),
                    name=name,
                    time=action.get("time", "00:00"),
                    category=action.get("category", "Other"),
                )
                db.add(s)
                db.flush()
                results.append(f"ルーチン(ID:{rid})にステップ「{name}」(ID: {s.id}) を追加しました。")
                modified_ids.append(f"item_routine_{s.id}")
                dirty = True
                continue

            if action_type == "delete_step":
                sid = action.get("step_id")
                s = db.get(Step, int(sid)) if sid else None
                if s:
                    db.delete(s)
                    results.append(f"ステップ「{s.name}」を削除しました。")
                    dirty = True
                else:
                    errors.append("delete_step: not found")
                continue

            if action_type == "update_step_time":
                step_id = action.get("step_id")
                new_time = action.get("new_time")
                if not new_time:
                    errors.append("update_step_time: new_time が指定されていません。")
                    continue
                try:
                    step_id_int = int(step_id)
                except (TypeError, ValueError):
                    errors.append("update_step_time: step_id が不正です。")
                    continue
                step_obj = db.get(Step, step_id_int)
                if not step_obj:
                    errors.append(f"step_id={step_id_int} が見つかりませんでした。")
                    continue
                step_obj.time = new_time.strip()
                results.append(f"ステップ「{step_obj.name}」の時刻を {step_obj.time} に更新しました。")
                modified_ids.append(f"item_routine_{step_obj.id}")
                dirty = True
                continue

            if action_type == "rename_step":
                step_id = action.get("step_id")
                new_name = action.get("new_name")
                if not new_name:
                    errors.append("rename_step: new_name が指定されていません。")
                    continue
                try:
                    step_id_int = int(step_id)
                except (TypeError, ValueError):
                    errors.append("rename_step: step_id が不正です。")
                    continue
                step_obj = db.get(Step, step_id_int)
                if not step_obj:
                    errors.append(f"step_id={step_id_int} が見つかりませんでした。")
                    continue
                old_name = step_obj.name
                step_obj.name = new_name.strip()
                results.append(f"ステップ「{old_name}」の名前を「{step_obj.name}」に更新しました。")
                modified_ids.append(f"item_routine_{step_obj.id}")
                dirty = True
                continue

            if action_type == "update_step_memo":
                step_id = action.get("step_id")
                new_memo = action.get("new_memo")
                if new_memo is None:
                    errors.append("update_step_memo: new_memo が指定されていません。")
                    continue
                try:
                    step_id_int = int(step_id)
                except (TypeError, ValueError):
                    errors.append("update_step_memo: step_id が不正です。")
                    continue
                step_obj = db.get(Step, step_id_int)
                if not step_obj:
                    errors.append(f"step_id={step_id_int} が見つかりませんでした。")
                    continue
                step_obj.memo = new_memo.strip()
                results.append(f"ステップ「{step_obj.name}」のメモを更新しました。")
                modified_ids.append(f"item_routine_{step_obj.id}")
                dirty = True
                continue

            if action_type == "list_tasks_in_period":
                raw_start_date = action.get("start_date")
                raw_end_date = action.get("end_date")
                if _is_relative_datetime_text(raw_start_date) or _is_relative_datetime_text(raw_end_date):
                    errors.append(
                        "list_tasks_in_period: 相対日付が含まれています。"
                        " resolve_schedule_expression で先に絶対日付へ変換してください。"
                    )
                    continue
                start_date = _parse_date(raw_start_date, default_date)
                end_date = _parse_date(raw_end_date, default_date)

                if start_date > end_date:
                    errors.append("list_tasks_in_period: 開始日が終了日より後です。")
                    continue

                tasks_info = []

                custom_tasks = db.exec(
                    select(CustomTask)
                    .where(CustomTask.date.between(start_date, end_date))
                    .order_by(CustomTask.date, CustomTask.time)
                ).all()
                for ct in custom_tasks:
                    tasks_info.append(
                        f"カスタムタスク [{ct.id}]: {ct.date.isoformat()} {ct.time} - {ct.name} (完了: {ct.done}) (メモ: {ct.memo if ct.memo else 'なし'})"
                    )

                current_date = start_date
                while current_date <= end_date:
                    routines_for_day = get_weekday_routines(db, current_date.weekday())
                    for r in routines_for_day:
                        for s in r.steps:
                            log = db.exec(
                                select(DailyLog).where(
                                    DailyLog.date == current_date, DailyLog.step_id == s.id
                                )
                            ).first()
                            status = "完了" if log and log.done else "未完了"
                            memo = log.memo if log and log.memo else (s.memo if s.memo else "なし")
                            tasks_info.append(
                                f"ルーチンステップ [{s.id}]: {current_date.isoformat()} {s.time} - {r.name} - {s.name} (完了: {status}) (メモ: {memo})"
                            )
                    current_date += datetime.timedelta(days=1)

                if tasks_info:
                    results.append(
                        f"{start_date.isoformat()} から {end_date.isoformat()} までのタスク:\n"
                        + "\n".join(tasks_info)
                    )
                else:
                    results.append(
                        f"{start_date.isoformat()} から {end_date.isoformat()} までのタスクは見つかりませんでした。"
                    )
                continue

            if action_type == "get_daily_summary":
                raw_date_value = action.get("date")
                if _is_relative_datetime_text(raw_date_value):
                    errors.append(
                        "get_daily_summary: date に相対表現が含まれています。"
                        " resolve_schedule_expression で先に絶対日付へ変換してください。"
                    )
                    continue
                target_date = _parse_date(raw_date_value, default_date)

                summary_parts = []

                day_log = db.exec(select(DayLog).where(DayLog.date == target_date)).first()
                if day_log and day_log.content:
                    summary_parts.append(f"日報: {day_log.content}")
                else:
                    summary_parts.append("日報: なし")

                custom_tasks = db.exec(
                    select(CustomTask).where(CustomTask.date == target_date)
                ).all()
                if custom_tasks:
                    summary_parts.append("カスタムタスク:")
                    for ct in custom_tasks:
                        status = "完了" if ct.done else "未完了"
                        summary_parts.append(
                            f"- {ct.time} {ct.name} ({status}) (メモ: {ct.memo if ct.memo else 'なし'})"
                        )
                else:
                    summary_parts.append("カスタムタスク: なし")

                routines_for_day = get_weekday_routines(db, target_date.weekday())
                if routines_for_day:
                    summary_parts.append("ルーチンステップ:")
                    for r in routines_for_day:
                        for s in r.steps:
                            log = db.exec(
                                select(DailyLog).where(
                                    DailyLog.date == target_date, DailyLog.step_id == s.id
                                )
                            ).first()
                            status = "完了" if log and log.done else "未完了"
                            memo = log.memo if log and log.memo else (s.memo if s.memo else "なし")
                            summary_parts.append(
                                f"- {s.time} {r.name} - {s.name} ({status}) (メモ: {memo})"
                            )
                else:
                    summary_parts.append("ルーチンステップ: なし")

                results.append(f"{target_date.isoformat()} の活動概要:\n" + "\n".join(summary_parts))
                continue

            errors.append(f"未知のアクション: {action_type}")
        if dirty:
            db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        errors.append(f"操作の適用に失敗しました: {exc}")
        results = []

    return results, errors, modified_ids


def _get_max_action_rounds() -> int:
    # 日本語: 複数ステップ実行の上限ラウンド / English: Maximum rounds for multi-step execution
    raw_value = os.getenv("SCHEDULER_MAX_ACTION_ROUNDS", "4")
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        parsed = 4
    return max(1, min(parsed, 8))


READ_ONLY_ACTION_TYPES = {
    "resolve_schedule_expression",
    "get_day_log",
    "list_tasks_in_period",
    "get_daily_summary",
}


def _action_signature(actions: List[Dict[str, Any]]) -> str:
    # 日本語: アクション配列を比較用シグネチャへ / English: Build comparable signature for action list
    signatures: List[str] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        try:
            signatures.append(json.dumps(action, ensure_ascii=False, sort_keys=True))
        except TypeError:
            signatures.append(str(action))
    return "|".join(signatures)


def _action_fingerprint(action: Dict[str, Any]) -> str:
    # 日本語: 1アクションを一意判定用の文字列へ / English: Canonical fingerprint for one action
    if not isinstance(action, dict):
        return ""
    try:
        return json.dumps(action, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(action)


def _dedupe_modified_ids(modified_ids: List[Any]) -> List[str]:
    # 日本語: 更新IDを順序維持で重複排除 / English: Dedupe modified ids while preserving order
    unique: List[str] = []
    seen: set[str] = set()
    for item in modified_ids:
        if not isinstance(item, str):
            continue
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def _get_last_user_message_from_messages(formatted_messages: List[Dict[str, str]]) -> str:
    # 日本語: 会話履歴から最新 user 発言を取得 / English: Extract latest user message from formatted history
    for msg in reversed(formatted_messages or []):
        if isinstance(msg, dict) and msg.get("role") == "user":
            content = msg.get("content", "")
            return content if isinstance(content, str) else str(content)
    return ""


def _infer_requested_steps(user_message: str) -> List[Dict[str, Any]]:
    # 日本語: ユーザー要求を簡易ステップへ分解 / English: Infer coarse-grained requested steps from user text
    if not isinstance(user_message, str) or not user_message.strip():
        return []

    events: List[tuple[int, str]] = []
    step_patterns: List[tuple[str, str]] = [
        ("confirm", r"(確認|見せて|見せる|一覧|表示|サマリー)"),
        ("add", r"(追加|入れて|登録)"),
        ("complete", r"(完了に|完了して|終わったら|チェックして)"),
        ("append_log", r"(日報.*追記|追記.*日報|日報.*メモ|メモ.*日報)"),
        ("reschedule", r"(ずらして|後ろに|前倒し|時間.*変更|時刻.*変更)"),
    ]

    for step_id, pattern in step_patterns:
        for match in re.finditer(pattern, user_message):
            events.append((match.start(), step_id))

    if _is_relative_datetime_text(user_message):
        events.append((0, "calculate"))

    if not events:
        return []

    events.sort(key=lambda item: item[0])

    step_definitions: Dict[str, Dict[str, Any]] = {
        "calculate": {
            "label": "日時計算",
            "action_types": {"resolve_schedule_expression"},
        },
        "confirm": {
            "label": "予定確認",
            "action_types": {"list_tasks_in_period", "get_daily_summary", "get_day_log"},
        },
        "add": {
            "label": "予定追加",
            "action_types": {"create_custom_task", "add_routine", "add_step"},
        },
        "complete": {
            "label": "完了更新",
            "action_types": {"toggle_custom_task", "toggle_step"},
        },
        "append_log": {
            "label": "日報更新",
            "action_types": {"append_day_log", "update_log"},
        },
        "reschedule": {
            "label": "時刻変更",
            "action_types": {"update_custom_task_time", "update_step_time"},
        },
    }

    steps: List[Dict[str, Any]] = []
    for _, step_id in events:
        definition = step_definitions.get(step_id)
        if not definition:
            continue
        # 同一カテゴリの連続重複は圧縮
        if steps and steps[-1].get("id") == step_id:
            continue
        steps.append(
            {
                "id": step_id,
                "label": definition["label"],
                "action_types": set(definition["action_types"]),
            }
        )
    return steps


def _format_step_progress(steps: List[Dict[str, Any]], completed_steps: int) -> str:
    # 日本語: 推定ステップ進捗をテキスト化 / English: Format inferred step progress as text
    if not steps:
        return "(none)"

    lines: List[str] = []
    next_step_label = ""
    for idx, step in enumerate(steps, start=1):
        done = idx <= completed_steps
        marker = "x" if done else " "
        label = step.get("label", step.get("id", "step"))
        lines.append(f"- [{marker}] {idx}. {label}")
        if not done and not next_step_label:
            next_step_label = str(label)

    if next_step_label:
        lines.append(f"next_expected_step: {next_step_label}")
    else:
        lines.append("next_expected_step: (all completed)")

    return "\n".join(lines)


def _extract_resolved_memory_from_actions(
    actions: List[Dict[str, Any]],
    default_date: datetime.date,
) -> List[Dict[str, str]]:
    # 日本語: resolve アクションから計算済み日時メモリを抽出 / English: Extract resolved datetime memory from actions
    memories: List[Dict[str, str]] = []
    fallback_base_time = datetime.datetime.now().strftime("%H:%M")
    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("type") != "resolve_schedule_expression":
            continue
        expression = action.get("expression")
        if not isinstance(expression, str) or not expression.strip():
            continue
        base_date_value = _parse_date(action.get("base_date"), default_date)
        base_time_value = _normalize_hhmm(action.get("base_time"), fallback_base_time)
        default_time_value = _normalize_hhmm(action.get("default_time"), base_time_value)
        calc = _resolve_schedule_expression(
            expression=expression,
            base_date=base_date_value,
            base_time=base_time_value,
            default_time=default_time_value,
        )
        if not calc.get("ok"):
            continue
        memories.append(
            {
                "expression": expression.strip(),
                "date": str(calc.get("date", "")),
                "time": str(calc.get("time", "")),
                "datetime": str(calc.get("datetime", "")),
            }
        )
    return memories


def _build_round_feedback(
    round_index: int,
    actions: List[Dict[str, Any]],
    results: List[str],
    errors: List[str],
    inferred_steps: List[Dict[str, Any]] | None = None,
    completed_steps: int = 0,
    resolved_memory: List[Dict[str, str]] | None = None,
    duplicate_warning: str = "",
) -> str:
    # 日本語: 次ラウンドへ渡す実行ログ / English: Execution feedback passed to the next round
    action_lines = "\n".join(
        f"- {json.dumps(action, ensure_ascii=False, sort_keys=True)}" for action in actions
    ) or "- (none)"
    result_lines = "\n".join(f"- {item}" for item in results) or "- (none)"
    error_lines = "\n".join(f"- {item}" for item in errors) or "- (none)"
    progress_lines = _format_step_progress(inferred_steps or [], completed_steps)
    resolved_lines = "\n".join(
        f"- expression={item.get('expression')} => date={item.get('date')} time={item.get('time')} datetime={item.get('datetime')}"
        for item in (resolved_memory or [])[-3:]
    ) or "- (none)"
    duplicate_lines = f"duplicate_warning:\n- {duplicate_warning}\n" if duplicate_warning else ""

    return (
        f"Execution round {round_index} completed.\n"
        "inferred_request_progress:\n"
        f"{progress_lines}\n"
        "resolved_datetime_memory:\n"
        f"{resolved_lines}\n"
        f"{duplicate_lines}"
        "executed_actions:\n"
        f"{action_lines}\n"
        "execution_results:\n"
        f"{result_lines}\n"
        "execution_errors:\n"
        f"{error_lines}\n"
        "元のユーザー要望を満たすために追加操作が必要ならツールを続けて呼んでください。\n"
        "要望が満たされた場合はツールを呼ばず、自然な日本語の最終回答のみを返してください。\n"
        "日付・時刻が相対表現（例: 3日後、来週、2時間後）なら resolve_schedule_expression を先に実行してから更新系ツールを呼んでください。\n"
        "直前と同じ参照/計算アクションを繰り返さず、next_expected_step を優先してください。\n"
        "同じ作成・更新系のアクションを重複して実行しないでください。"
    )


def _run_scheduler_multi_step(
    db: Session,
    formatted_messages: List[Dict[str, str]],
    today: datetime.date,
    max_rounds: int | None = None,
) -> Dict[str, Any]:
    # 日本語: LLM 呼び出しとアクション適用を複数ラウンド実行 / English: Run LLM/action cycle for multiple rounds
    rounds_limit = max_rounds if isinstance(max_rounds, int) and max_rounds > 0 else _get_max_action_rounds()
    working_messages = list(formatted_messages)
    user_message = _get_last_user_message_from_messages(formatted_messages)
    inferred_steps = _infer_requested_steps(user_message)

    all_actions: List[Dict[str, Any]] = []
    all_results: List[str] = []
    all_errors: List[str] = []
    all_modified_ids: List[str] = []
    raw_replies: List[str] = []
    execution_trace: List[Dict[str, Any]] = []
    resolved_memory: List[Dict[str, str]] = []

    previous_signature = ""
    previous_round_had_write = False
    stale_read_repeat_count = 0
    no_progress_rounds = 0
    completed_steps = 0
    executed_write_fingerprints: set[str] = set()

    if inferred_steps:
        planning_message = (
            "requested_steps_plan:\n"
            f"{_format_step_progress(inferred_steps, completed_steps)}\n"
            "この順序を意識して実行してください。"
        )
        working_messages = [*working_messages, {"role": "system", "content": planning_message}]

    for round_index in range(1, rounds_limit + 1):
        context = _build_scheduler_context(db, today)

        try:
            reply_text, actions = call_scheduler_llm(working_messages, context)
        except Exception as exc:
            all_errors.append(f"LLM 呼び出しに失敗しました: {exc}")
            break

        reply_text = reply_text or ""
        raw_replies.append(reply_text)

        current_actions = [a for a in actions if isinstance(a, dict)] if isinstance(actions, list) else []
        if not current_actions:
            break

        current_action_types = [
            str(action.get("type", "")) for action in current_actions if isinstance(action, dict)
        ]
        all_read_only = bool(current_action_types) and all(
            action_type in READ_ONLY_ACTION_TYPES for action_type in current_action_types
        )
        signature = _action_signature(current_actions)
        if signature and signature == previous_signature:
            if all_read_only and not previous_round_had_write:
                stale_read_repeat_count += 1
                duplicate_warning = (
                    "同じ参照/計算アクションが連続しました。"
                    " 次は next_expected_step に沿って別アクションを実行してください。"
                )
                trace_actions = []
                for action in current_actions:
                    action_type = action.get("type") if isinstance(action, dict) else None
                    params = {}
                    if isinstance(action, dict):
                        params = {k: v for k, v in action.items() if k != "type"}
                    trace_actions.append(
                        {
                            "type": str(action_type or "unknown"),
                            "params": params,
                        }
                    )
                execution_trace.append(
                    {
                        "round": round_index,
                        "actions": trace_actions,
                        "results": [],
                        "errors": [duplicate_warning],
                        "skipped": True,
                    }
                )
                feedback = _build_round_feedback(
                    round_index,
                    current_actions,
                    [],
                    [],
                    inferred_steps=inferred_steps,
                    completed_steps=completed_steps,
                    resolved_memory=resolved_memory,
                    duplicate_warning=duplicate_warning,
                )
                assistant_feedback = reply_text.strip() or "了解しました。"
                working_messages = [
                    *working_messages,
                    {"role": "assistant", "content": assistant_feedback},
                    {"role": "system", "content": feedback},
                ]
                if stale_read_repeat_count >= 2:
                    all_errors.append("同じ参照/計算アクションが続いたため処理を終了しました。")
                    break
                continue

            all_errors.append("同一アクションが連続して提案されたため、重複実行を停止しました。")
            break

        stale_read_repeat_count = 0
        previous_signature = signature

        actions_to_execute: List[Dict[str, Any]] = []
        skipped_write_duplicates: List[Dict[str, Any]] = []
        for action in current_actions:
            action_type = str(action.get("type", ""))
            if action_type in READ_ONLY_ACTION_TYPES:
                actions_to_execute.append(action)
                continue
            fingerprint = _action_fingerprint(action)
            if fingerprint and fingerprint in executed_write_fingerprints:
                skipped_write_duplicates.append(action)
                continue
            if fingerprint:
                executed_write_fingerprints.add(fingerprint)
            actions_to_execute.append(action)

        duplicate_warning = ""
        if skipped_write_duplicates:
            duplicate_warning = "同一の更新アクションが再提案されたため再実行をスキップしました。"

        if not actions_to_execute:
            no_progress_rounds += 1
            trace_actions = []
            for action in current_actions:
                action_type = action.get("type") if isinstance(action, dict) else None
                params = {}
                if isinstance(action, dict):
                    params = {k: v for k, v in action.items() if k != "type"}
                trace_actions.append(
                    {
                        "type": str(action_type or "unknown"),
                        "params": params,
                    }
                )
            execution_trace.append(
                {
                    "round": round_index,
                    "actions": trace_actions,
                    "results": [],
                    "errors": [duplicate_warning] if duplicate_warning else [],
                    "skipped": True,
                }
            )
            feedback = _build_round_feedback(
                round_index,
                current_actions,
                [],
                [],
                inferred_steps=inferred_steps,
                completed_steps=completed_steps,
                resolved_memory=resolved_memory,
                duplicate_warning=duplicate_warning,
            )
            assistant_feedback = reply_text.strip() or "了解しました。"
            working_messages = [
                *working_messages,
                {"role": "assistant", "content": assistant_feedback},
                {"role": "system", "content": feedback},
            ]
            if no_progress_rounds >= 2:
                all_errors.append("進捗が得られない状態が続いたため処理を終了しました。")
                break
            continue

        results, errors, modified_ids = _apply_actions(db, actions_to_execute, today)
        all_actions.extend(actions_to_execute)
        all_results.extend(results)
        all_errors.extend(errors)
        all_modified_ids.extend(modified_ids)

        before_completed_steps = completed_steps
        for action in actions_to_execute:
            action_type = str(action.get("type", ""))
            if completed_steps >= len(inferred_steps):
                break
            expected_types = inferred_steps[completed_steps].get("action_types", set())
            if action_type in expected_types:
                completed_steps += 1

        new_resolved_items = _extract_resolved_memory_from_actions(actions_to_execute, today)
        existing_keys = {
            (item.get("expression", ""), item.get("date", ""), item.get("time", ""))
            for item in resolved_memory
        }
        for item in new_resolved_items:
            key = (item.get("expression", ""), item.get("date", ""), item.get("time", ""))
            if key in existing_keys:
                continue
            existing_keys.add(key)
            resolved_memory.append(item)

        trace_actions = []
        for action in actions_to_execute:
            action_type = action.get("type") if isinstance(action, dict) else None
            params = {}
            if isinstance(action, dict):
                params = {k: v for k, v in action.items() if k != "type"}
            trace_actions.append(
                {
                    "type": str(action_type or "unknown"),
                    "params": params,
                }
            )
        execution_trace.append(
            {
                "round": round_index,
                "actions": trace_actions,
                "results": list(results),
                "errors": list(errors),
            }
        )

        has_progress = bool(modified_ids) or bool(results) or completed_steps > before_completed_steps
        if has_progress:
            no_progress_rounds = 0
        else:
            no_progress_rounds += 1

        previous_round_had_write = any(
            str(action.get("type", "")) not in READ_ONLY_ACTION_TYPES for action in actions_to_execute
        )

        feedback = _build_round_feedback(
            round_index,
            actions_to_execute,
            results,
            errors,
            inferred_steps=inferred_steps,
            completed_steps=completed_steps,
            resolved_memory=resolved_memory,
            duplicate_warning=duplicate_warning,
        )
        assistant_feedback = reply_text.strip() or "了解しました。"
        working_messages = [
            *working_messages,
            {"role": "assistant", "content": assistant_feedback},
            {"role": "system", "content": feedback},
        ]

        if no_progress_rounds >= 2:
            all_errors.append("進捗が得られない状態が続いたため処理を終了しました。")
            break
    else:
        all_errors.append(f"複数ステップ実行の上限（{rounds_limit}ラウンド）に達したため処理を終了しました。")

    return {
        "reply_text": raw_replies[-1] if raw_replies else "",
        "raw_replies": raw_replies,
        "actions": all_actions,
        "results": all_results,
        "errors": all_errors,
        "modified_ids": _dedupe_modified_ids(all_modified_ids),
        "execution_trace": execution_trace,
    }


def _build_final_reply(
    user_message: str,
    reply_text: str,
    results: List[str],
    errors: List[str],
) -> str:
    # 日本語: 実行結果を踏まえて最終返信を整形 / English: Build final user-facing reply from execution outputs
    if not results and not errors:
        final_reply = reply_text if reply_text else "了解しました。"
        return _remove_no_schedule_lines(final_reply)

    summary_client = UnifiedClient()

    result_text = ""
    if results:
        result_text += "【実行結果】\n" + "\n".join(f"- {item}" for item in results) + "\n"
    if errors:
        result_text += "【エラー】\n" + "\n".join(f"- {err}" for err in errors) + "\n"

    summary_system_prompt = (
        "あなたはユーザーのスケジュール管理をサポートする親しみやすいAIパートナーです。\n"
        "ユーザーの要望に対してシステムがアクションを実行しました。\n"
        "その「実行結果」をもとに、ユーザーへの最終的な回答を作成してください。\n"
        "\n"
        "## ガイドライン\n"
        "1. **フレンドリーに**: 絵文字（📅, ✅, ✨, 👍など）を適度に使用し、硬苦しくない丁寧語（です・ます）で話してください。\n"
        "2. **分かりやすく**: 実行結果の羅列（「カスタムタスク[2]...」のような形式）は避け、人間が読みやすい文章に整形してください。\n"
        "   - 例: 「12月10日の9時から『カラオケ』の予定が入っていますね！楽しんできてください🎤」\n"
        "   - 予定がない日は `予定なし` と書かず、その行自体を省略してください。\n"
        "3. **エラーへの対応**: エラーがある場合は、優しくその旨を伝え、どうすればよいか（もし分かれば）示唆してください。\n"
        "4. **元の文脈を維持**: ユーザーの元の発言に対する返答として自然になるようにしてください。\n"
    )

    summary_messages = [
        {"role": "system", "content": summary_system_prompt},
        {"role": "user", "content": f"ユーザーの発言: {user_message}\n\n{result_text}"},
    ]

    try:
        resp = summary_client.create(messages=summary_messages, temperature=0.7, max_tokens=1000)
        final_reply = _content_to_text(resp.choices[0].message.content)
    except Exception as e:
        final_reply = (reply_text or "") + ("\n\n" + result_text if result_text else "")
        print(f"Summary LLM failed: {e}")

    return _remove_no_schedule_lines(final_reply)


# 日本語: 月間カレンダーの集計 API / English: Monthly calendar summary API
@app.get("/api/calendar", name="api_calendar")
def api_calendar(request: Request, db: Session = Depends(get_db)):
    today = datetime.date.today()
    year = int(request.query_params.get("year", today.year))
    month = int(request.query_params.get("month", today.month))

    if month > 12:
        month = 1
        year += 1
    elif month < 1:
        month = 12
        year -= 1

    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdatescalendar(year, month)

    calendar_data = []
    for week in month_days:
        week_data = []
        for day in week:
            is_current_month = day.month == month

            weekday = day.weekday()
            routines = get_weekday_routines(db, weekday)
            total_steps = sum(len(r.steps) for r in routines)

            logs = db.exec(select(DailyLog).where(DailyLog.date == day)).all()
            completed_count = sum(1 for l in logs if l.done)

            custom_tasks = db.exec(select(CustomTask).where(CustomTask.date == day)).all()
            total_steps += len(custom_tasks)
            completed_count += sum(1 for t in custom_tasks if t.done)

            day_log = db.exec(select(DayLog).where(DayLog.date == day)).first()
            has_day_log = bool(day_log and day_log.content and day_log.content.strip())

            week_data.append(
                {
                    "date": day.isoformat(),
                    "day_num": day.day,
                    "is_current_month": is_current_month,
                    "total_routines": len(routines) + len(custom_tasks),
                    "total_steps": total_steps,
                    "completed_steps": completed_count,
                    "has_day_log": has_day_log,
                }
            )
        calendar_data.append(week_data)

    return {
        "calendar_data": calendar_data,
        "year": year,
        "month": month,
        "today": today.isoformat(),
    }


# 日本語: SPA ルート（カレンダー画面） / English: SPA entry route (calendar)
@app.get("/", response_class=HTMLResponse, name="index")
def index(request: Request, db: Session = Depends(get_db)):
    return template_response(request, "spa.html", {"page_id": "index"})


# 日本語: エージェント評価用カレンダー / English: Agent result calendar page
@app.get("/agent-result", response_class=HTMLResponse, name="agent_result")
def agent_result(request: Request, db: Session = Depends(get_db)):
    return template_response(request, "spa.html", {"page_id": "agent-result"})

# 日本語: エージェント結果の1日ビュー / English: Agent result day view
@app.api_route(
    "/agent-result/day/{date_str}", methods=["GET", "POST"], response_class=HTMLResponse, name="agent_day_view"
)
async def agent_day_view(request: Request, date_str: str, db: Session = Depends(get_db)):
    try:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse(url=str(request.url_for("agent_result")), status_code=303)

    if request.method == "POST":
        form = await request.form()

        if "add_custom_task" in form:
            name = form.get("custom_name")
            time = form.get("custom_time")
            if name:
                ct = CustomTask(date=date_obj, name=name, time=time)
                db.add(ct)
                db.commit()
                flash(request, "カスタムタスクを追加しました。")
            return RedirectResponse(
                url=str(request.url_for("agent_day_view", date_str=date_str)), status_code=303
            )

        if "save_log" in form:
            content = form.get("day_log_content")
            dlog = db.exec(select(DayLog).where(DayLog.date == date_obj)).first()
            if not dlog:
                dlog = DayLog(date=date_obj)
                db.add(dlog)
            dlog.content = content
            db.commit()
            flash(request, "日報を保存しました。")
            return RedirectResponse(
                url=str(request.url_for("agent_day_view", date_str=date_str)), status_code=303
            )

        if "delete_custom_task" in form:
            task_id = form.get("delete_custom_task")
            task = db.get(CustomTask, int(task_id)) if task_id else None
            if task:
                db.delete(task)
                db.commit()
                flash(request, "タスクを削除しました。")
            return RedirectResponse(
                url=str(request.url_for("agent_day_view", date_str=date_str)), status_code=303
            )

        routines = get_weekday_routines(db, date_obj.weekday())
        all_steps = []
        for r in routines:
            all_steps.extend(r.steps)

        for step in all_steps:
            done_key = f"done_{step.id}"
            memo_key = f"memo_{step.id}"
            is_done = form.get(done_key) == "on"
            memo_text = form.get(memo_key, "")

            log = db.exec(
                select(DailyLog).where(DailyLog.date == date_obj, DailyLog.step_id == step.id)
            ).first()
            if not log:
                log = DailyLog(date=date_obj, step_id=step.id)
                db.add(log)

            log.done = is_done
            log.memo = memo_text

        custom_tasks = db.exec(select(CustomTask).where(CustomTask.date == date_obj)).all()
        for task in custom_tasks:
            done_key = f"custom_done_{task.id}"
            memo_key = f"custom_memo_{task.id}"
            is_done = form.get(done_key) == "on"
            memo_text = form.get(memo_key, "")
            task.done = is_done
            task.memo = memo_text

        db.commit()
        flash(request, "進捗を保存しました。")
        return RedirectResponse(
            url=str(request.url_for("agent_day_view", date_str=date_str)), status_code=303
        )

    return template_response(request, "spa.html", {"page_id": "agent-day"})


# 日本語: 埋め込み用カレンダー画面 / English: Embedded calendar view
@app.get("/embed/calendar", response_class=HTMLResponse, name="embed_calendar")
def embed_calendar(request: Request, db: Session = Depends(get_db)):
    return template_response(request, "spa.html", {"page_id": "embed-calendar"})


# 日本語: 日次詳細データ API / English: Day detail API
@app.get("/api/day/{date_str}", name="api_day_view")
def api_day_view(date_str: str, db: Session = Depends(get_db)):
    try:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    timeline_items, completion_rate = _get_timeline_data(db, date_obj)
    day_log = db.exec(select(DayLog).where(DayLog.date == date_obj)).first()

    serialized_timeline_items = []
    for item in timeline_items:
        step = item["step"]
        if isinstance(step, dict):
            step_name = step.get("name", "")
            step_category = step.get("category", "Other")
        else:
            step_name = step.name
            step_category = getattr(step, "category", "Other")

        routine = item["routine"]
        if isinstance(routine, dict):
            routine_name = routine.get("name", "")
        else:
            routine_name = routine.name

        log = item["log"]
        if isinstance(log, dict):
            log_done = log.get("done", False)
            log_memo = log.get("memo")
        elif log:
            log_done = log.done
            log_memo = log.memo
        else:
            log_done = False
            log_memo = None

        is_done = item["real_obj"].done if item.get("real_obj") else log_done

        serialized_item = {
            "type": item["type"],
            "time": item["time"],
            "id": item["id"],
            "routine_name": routine_name,
            "step_name": step_name,
            "step_category": step_category,
            "log_done": log_done,
            "log_memo": log_memo,
            "is_done": is_done,
        }
        serialized_timeline_items.append(serialized_item)

    return {
        "date": date_obj.isoformat(),
        "weekday": date_obj.weekday(),
        "day_name": date_obj.strftime("%A"),
        "date_display": date_obj.strftime("%Y.%m.%d"),
        "timeline_items": serialized_timeline_items,
        "completion_rate": completion_rate,
        "day_log_content": day_log.content if day_log else None,
    }


# 日本語: 月間カレンダーの集計 API（重複ルート） / English: Monthly calendar summary API (duplicate route)
@app.get("/api/calendar", name="api_calendar")
def api_calendar(request: Request, db: Session = Depends(get_db)):
    today = datetime.date.today()
    year = int(request.query_params.get("year", today.year))
    month = int(request.query_params.get("month", today.month))

    if month > 12:
        month = 1
        year += 1
    elif month < 1:
        month = 12
        year -= 1

    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdatescalendar(year, month)

    calendar_data = []
    for week in month_days:
        week_data = []
        for day in week:
            is_current_month = day.month == month

            weekday = day.weekday()
            routines = get_weekday_routines(db, weekday)
            total_steps = sum(len(r.steps) for r in routines)

            logs = db.exec(select(DailyLog).where(DailyLog.date == day)).all()
            completed_count = sum(1 for l in logs if l.done)

            custom_tasks = db.exec(select(CustomTask).where(CustomTask.date == day)).all()
            total_steps += len(custom_tasks)
            completed_count += sum(1 for t in custom_tasks if t.done)

            day_log = db.exec(select(DayLog).where(DayLog.date == day)).first()
            has_day_log = bool(day_log and day_log.content and day_log.content.strip())

            week_data.append(
                {
                    "date": day.isoformat(),
                    "day_num": day.day,
                    "is_current_month": is_current_month,
                    "total_routines": len(routines) + len(custom_tasks),
                    "total_steps": total_steps,
                    "completed_steps": completed_count,
                    "has_day_log": has_day_log,
                }
            )
        calendar_data.append(week_data)

    return {
        "calendar_data": calendar_data,
        "year": year,
        "month": month,
        "today": today.isoformat(),
    }


# 日本語: 日次ビュー（表示＋フォーム更新） / English: Day view (render + form updates)
@app.api_route("/day/{date_str}", methods=["GET", "POST"], response_class=HTMLResponse, name="day_view")
async def day_view(request: Request, date_str: str, db: Session = Depends(get_db)):
    try:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse(url=str(request.url_for("index")), status_code=303)

    if request.method == "POST":
        form = await request.form()

        if "add_custom_task" in form:
            name = form.get("custom_name")
            time = form.get("custom_time")
            if name:
                ct = CustomTask(date=date_obj, name=name, time=time)
                db.add(ct)
                db.commit()
                flash(request, "カスタムタスクを追加しました。")
            return RedirectResponse(
                url=str(request.url_for("day_view", date_str=date_str)), status_code=303
            )

        if "save_log" in form:
            content = form.get("day_log_content")
            dlog = db.exec(select(DayLog).where(DayLog.date == date_obj)).first()
            if not dlog:
                dlog = DayLog(date=date_obj)
                db.add(dlog)
            dlog.content = content
            db.commit()
            flash(request, "日報を保存しました。")
            return RedirectResponse(
                url=str(request.url_for("day_view", date_str=date_str)), status_code=303
            )

        if "delete_custom_task" in form:
            task_id = form.get("delete_custom_task")
            task = db.get(CustomTask, int(task_id)) if task_id else None
            if task:
                db.delete(task)
                db.commit()
                flash(request, "タスクを削除しました。")
            return RedirectResponse(
                url=str(request.url_for("day_view", date_str=date_str)), status_code=303
            )

        routines = get_weekday_routines(db, date_obj.weekday())
        all_steps = []
        for r in routines:
            all_steps.extend(r.steps)

        for step in all_steps:
            done_key = f"done_{step.id}"
            memo_key = f"memo_{step.id}"
            is_done = form.get(done_key) == "on"
            memo_text = form.get(memo_key, "")

            log = db.exec(
                select(DailyLog).where(DailyLog.date == date_obj, DailyLog.step_id == step.id)
            ).first()
            if not log:
                log = DailyLog(date=date_obj, step_id=step.id)
                db.add(log)

            log.done = is_done
            log.memo = memo_text

        custom_tasks = db.exec(select(CustomTask).where(CustomTask.date == date_obj)).all()
        for task in custom_tasks:
            done_key = f"custom_done_{task.id}"
            memo_key = f"custom_memo_{task.id}"
            is_done = form.get(done_key) == "on"
            memo_text = form.get(memo_key, "")
            task.done = is_done
            task.memo = memo_text

        db.commit()
        flash(request, "進捗を保存しました。")
        return RedirectResponse(
            url=str(request.url_for("day_view", date_str=date_str)), status_code=303
        )

    return template_response(request, "spa.html", {"page_id": "day"})


# 日本語: 曜日別ルーチン一覧 API / English: Routines by weekday API
@app.get("/api/routines/day/{weekday}", name="api_routines_by_day")
def api_routines_by_day(weekday: int, db: Session = Depends(get_db)):
    routines = get_weekday_routines(db, weekday)
    serialized_routines = []
    for r in routines:
        steps = []
        for s in r.steps:
            steps.append({"id": s.id, "name": s.name, "time": s.time, "category": s.category})
        steps.sort(key=lambda x: x["time"])

        serialized_routines.append(
            {"id": r.id, "name": r.name, "description": r.description, "steps": steps}
        )
    return {"routines": serialized_routines}


# 日本語: ルーチン一覧 API / English: Routines list API
@app.get("/api/routines", name="api_routines")
def api_routines(db: Session = Depends(get_db)):
    routines = db.exec(select(Routine)).all()
    serialized_routines = []
    for r in routines:
        steps = []
        for s in r.steps:
            steps.append({"id": s.id, "name": s.name, "time": s.time, "category": s.category})
        serialized_routines.append(
            {"id": r.id, "name": r.name, "days": r.days, "description": r.description, "steps": steps}
        )
    return {"routines": serialized_routines}


# 日本語: ルーチン管理ページ / English: Routines management page
@app.get("/routines", response_class=HTMLResponse, name="routines_list")
def routines_list(request: Request, db: Session = Depends(get_db)):
    return template_response(request, "spa.html", {"page_id": "routines"})


# 日本語: ルーチン追加（フォーム） / English: Add routine (form submit)
@app.post("/routines/add", name="add_routine")
async def add_routine(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    name = form.get("name")
    days = ",".join(form.getlist("days"))
    desc = form.get("description")
    if name:
        r = Routine(name=name, days=days, description=desc)
        db.add(r)
        db.commit()
    return RedirectResponse(url=str(request.url_for("routines_list")), status_code=303)


# 日本語: ルーチン削除 / English: Delete routine
@app.post("/routines/{id}/delete", name="delete_routine")
def delete_routine(request: Request, id: int, db: Session = Depends(get_db)):
    r = db.get(Routine, id)
    if not r:
        raise HTTPException(status_code=404, detail="Routine not found")
    db.delete(r)
    db.commit()
    return RedirectResponse(url=str(request.url_for("routines_list")), status_code=303)


# 日本語: ステップ追加 / English: Add step to routine
@app.post("/routines/{id}/step/add", name="add_step")
async def add_step(request: Request, id: int, db: Session = Depends(get_db)):
    form = await request.form()
    r = db.get(Routine, id)
    if not r:
        raise HTTPException(status_code=404, detail="Routine not found")
    name = form.get("name")
    time = form.get("time")
    category = form.get("category")
    if name:
        s = Step(routine_id=r.id, name=name, time=time, category=category)
        db.add(s)
        db.commit()
    return RedirectResponse(url=str(request.url_for("routines_list")), status_code=303)


# 日本語: ステップ削除 / English: Delete step
@app.post("/steps/{id}/delete", name="delete_step")
def delete_step(request: Request, id: int, db: Session = Depends(get_db)):
    s = db.get(Step, id)
    if not s:
        raise HTTPException(status_code=404, detail="Step not found")
    db.delete(s)
    db.commit()
    return RedirectResponse(url=str(request.url_for("routines_list")), status_code=303)


# 日本語: モデル選択肢と現在値の取得 / English: Get available models and current selection
@app.get("/api/models", name="list_models")
def list_models():
    provider, model, base_url, _ = apply_model_selection("scheduler")
    return {
        "models": current_available_models(),
        "current": {"provider": provider, "model": model, "base_url": base_url},
    }


# 日本語: モデル設定の更新 / English: Update model settings
@app.post("/model_settings", name="update_model_settings")
async def update_model_settings(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    selection = payload.get("selection") if "selection" in payload else payload
    if isinstance(selection, dict) and "scheduler" in selection:
        selection = selection.get("scheduler")
    if selection is not None and not isinstance(selection, dict):
        raise HTTPException(status_code=400, detail="selection must be an object")

    try:
        provider, model, base_url, _ = update_override(selection if selection else None)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"モデル設定の更新に失敗しました: {exc}")
    return {"status": "ok", "applied": {"provider": provider, "model": model, "base_url": base_url}}


# 日本語: チャット履歴の取得/削除 / English: Fetch or clear chat history
@app.api_route("/api/chat/history", methods=["GET", "DELETE"], name="manage_chat_history")
async def manage_chat_history(request: Request, db: Session = Depends(get_db)):
    if request.method == "DELETE":
        try:
            db.exec(delete(ChatHistory))
            db.commit()
            return {"status": "cleared"}
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=str(e))

    history = db.exec(select(ChatHistory).order_by(ChatHistory.timestamp)).all()
    return {
        "history": [
            {"role": h.role, "content": h.content, "timestamp": h.timestamp.isoformat()}
            for h in history
        ]
    }


# 日本語: LLM 連携の中心処理 / English: Core LLM-driven chat processing
def process_chat_request(
    db: Session, message_or_history: Union[str, List[Dict[str, str]]], save_history: bool = True
) -> Dict[str, Any]:
    formatted_messages = []
    user_message = ""

    if isinstance(message_or_history, str):
        user_message = message_or_history
        formatted_messages = [{"role": "user", "content": user_message}]
    else:
        formatted_messages = message_or_history
        if formatted_messages and formatted_messages[-1].get("role") == "user":
            user_message = formatted_messages[-1].get("content", "")
        else:
            user_message = "(Context only)"

    if save_history:
        try:
            db.add(ChatHistory(role="user", content=user_message))
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"Failed to save user message: {e}")

    today = datetime.date.today()
    execution = _run_scheduler_multi_step(db, formatted_messages, today)
    final_reply = _build_final_reply(
        user_message=user_message,
        reply_text=execution.get("reply_text", ""),
        results=execution.get("results", []),
        errors=execution.get("errors", []),
    )

    if save_history:
        try:
            db.add(ChatHistory(role="assistant", content=final_reply))
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"Failed to save assistant message: {e}")

    results = execution.get("results", [])
    return {
        "reply": final_reply,
        "should_refresh": (len(results) > 0),
        "modified_ids": execution.get("modified_ids", []),
        "execution_trace": execution.get("execution_trace", []),
    }


# 日本語: チャット API（UI から呼ばれる） / English: Chat API for UI
@app.post("/api/chat", name="chat")
async def chat(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages must be a list")

    formatted_messages = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if role not in {"system", "user", "assistant"} or not isinstance(content, str):
            continue
        formatted_messages.append({"role": role, "content": content})

    if not formatted_messages or formatted_messages[-1]["role"] != "user":
        raise HTTPException(status_code=400, detail="last message must be from user")

    recent_messages = formatted_messages[-10:]

    result = process_chat_request(db, recent_messages)

    return result


# 日本語: 評価ページ / English: Evaluation page
@app.get("/evaluation", response_class=HTMLResponse, name="evaluation_page")
def evaluation_page(request: Request):
    return template_response(request, "spa.html", {"page_id": "evaluation"})


# 日本語: 評価用チャット API / English: Evaluation chat API
@app.post("/api/evaluation/chat", name="evaluation_chat")
async def evaluation_chat(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages must be a list")

    formatted_messages = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if role not in {"system", "user", "assistant"} or not isinstance(content, str):
            continue
        formatted_messages.append({"role": role, "content": content})

    if not formatted_messages or formatted_messages[-1]["role"] != "user":
        raise HTTPException(status_code=400, detail="last message must be from user")

    today = datetime.date.today()
    execution = _run_scheduler_multi_step(db, formatted_messages, today)
    reply_text = execution.get("reply_text", "")
    results = execution.get("results", [])
    errors = execution.get("errors", [])
    actions = execution.get("actions", [])

    user_message = formatted_messages[-1]["content"]
    final_reply = _build_final_reply(
        user_message=user_message,
        reply_text=reply_text,
        results=results,
        errors=errors,
    )

    return {
        "reply": final_reply,
        "raw_reply": reply_text,
        "actions": actions,
        "results": results,
        "errors": errors,
        "execution_trace": execution.get("execution_trace", []),
    }


# 日本語: 評価データの初期化 / English: Reset evaluation data
@app.post("/api/evaluation/reset", name="evaluation_reset")
def evaluation_reset(db: Session = Depends(get_db)):
    try:
        db.exec(delete(DailyLog))
        db.exec(delete(CustomTask))
        db.exec(delete(Step))
        db.exec(delete(Routine))
        db.exec(delete(DayLog))
        db.commit()
        return {"status": "ok", "message": "Scheduler data cleared."}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# 日本語: 評価用のシード投入（単日） / English: Seed evaluation data (single day)
@app.post("/api/evaluation/seed", name="evaluation_seed")
async def evaluation_seed(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    date_str = payload.get("date") or request.query_params.get("date")
    if date_str:
        target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    else:
        target_date = datetime.date.today()

    messages = _seed_evaluation_data(db, target_date, target_date)
    return {"status": "ok", "message": "; ".join(messages)}


# 日本語: 評価用のシード投入（期間） / English: Seed evaluation data (period)
@app.post("/api/evaluation/seed_period", name="evaluation_seed_period")
async def evaluation_seed_period(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    start_date_str = payload.get("start_date") or request.query_params.get("start_date")
    end_date_str = payload.get("end_date") or request.query_params.get("end_date")

    if not start_date_str or not end_date_str:
        raise HTTPException(status_code=400, detail="start_date and end_date are required")

    start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()

    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date cannot be after end_date")

    messages = _seed_evaluation_data(db, start_date, end_date)
    return {"status": "ok", "message": "; ".join(messages)}


# 日本語: 評価データを一定期間分作成 / English: Generate evaluation data over a period
def _seed_evaluation_data(db: Session, start_date: datetime.date, end_date: datetime.date):
    messages = []

    routine_name = "Daily Routine"
    daily_routine = db.exec(select(Routine).where(Routine.name == routine_name)).first()
    if not daily_routine:
        daily_routine = Routine(
            name=routine_name, days="0,1,2,3,4,5,6", description="General daily habits"
        )
        db.add(daily_routine)
        db.flush()

        steps_data = [
            ("07:00", "Wake up", "Lifestyle"),
            ("08:00", "Breakfast", "Lifestyle"),
            ("09:00", "Check Emails", "Browser"),
            ("12:00", "Lunch", "Lifestyle"),
            ("18:00", "Workout", "Lifestyle"),
            ("22:00", "Read Book", "Lifestyle"),
        ]
        for time, name, category in steps_data:
            s = Step(routine_id=daily_routine.id, name=name, time=time, category=category)
            db.add(s)
        messages.append(f"Seeded Routine '{routine_name}'")

    current_date = start_date
    while current_date <= end_date:
        db.exec(delete(DailyLog).where(DailyLog.date == current_date))
        db.exec(delete(CustomTask).where(CustomTask.date == current_date))
        db.exec(delete(DayLog).where(DayLog.date == current_date))
        messages.append(f"Cleared existing data for {current_date.isoformat()}")

        log_content = f"これは{current_date.isoformat()}の評価用日報です。今日の気分は最高です！"
        db.add(DayLog(date=current_date, content=log_content))
        messages.append(f"Seeded DayLog for {current_date.isoformat()}")

        db.add(
            CustomTask(
                date=current_date,
                name=f"ミーティング ({current_date.day}日)",
                time="10:00",
                memo="重要な議題",
            )
        )
        db.add(
            CustomTask(
                date=current_date,
                name=f"レポート作成 ({current_date.day}日)",
                time="14:00",
                memo="期限は明日",
            )
        )
        messages.append(f"Seeded Custom Tasks for {current_date.isoformat()}")

        if daily_routine:
            all_steps = db.exec(
                select(Step).where(Step.routine_id == daily_routine.id)
            ).all()
            if all_steps:
                if len(all_steps) >= 1:
                    log_entry = DailyLog(
                        date=current_date, step_id=all_steps[0].id, done=True, memo="朝の活動完了"
                    )
                    db.add(log_entry)
                    messages.append(
                        f"Marked step '{all_steps[0].name}' as done for {current_date.isoformat()}"
                    )
                if len(all_steps) >= 3:
                    log_entry = DailyLog(
                        date=current_date, step_id=all_steps[2].id, done=True, memo="メールチェック完了"
                    )
                    db.add(log_entry)
                    messages.append(
                        f"Marked step '{all_steps[2].name}' as done for {current_date.isoformat()}"
                    )

        current_date += datetime.timedelta(days=1)

    db.commit()
    return messages


# 日本語: サンプルデータ投入 / English: Seed sample data for demo
@app.post("/api/add_sample_data", name="add_sample_data")
def add_sample_data(db: Session = Depends(get_db)):
    try:
        today = datetime.date.today()
        messages = []

        days_behind = (today.weekday() - 4) % 7
        if days_behind <= 0:
            days_behind += 7
        last_friday = today - datetime.timedelta(days=days_behind)

        log = db.exec(select(DayLog).where(DayLog.date == last_friday)).first()
        if not log:
            log = DayLog(
                date=last_friday, content="先週の金曜日はとても良い天気でした。プロジェクトの進捗も順調でした。"
            )
            db.add(log)
            messages.append(f"Seeded DayLog for {last_friday}")

        routine_name = "Daily Routine"
        daily_routine = db.exec(select(Routine).where(Routine.name == routine_name)).first()
        if not daily_routine:
            daily_routine = Routine(
                name=routine_name, days="0,1,2,3,4,5,6", description="General daily habits"
            )
            db.add(daily_routine)
            db.flush()

            steps_data = [("07:00", "Wake up", "Lifestyle"), ("08:00", "Breakfast", "Lifestyle"), ("09:00", "Check Emails", "Browser")]
            for time, name, category in steps_data:
                s = Step(routine_id=daily_routine.id, name=name, time=time, category=category)
                db.add(s)
            messages.append(f"Seeded Routine '{routine_name}'")

        task_name = "Buy Milk"
        if not db.exec(
            select(CustomTask).where(CustomTask.date == today, CustomTask.name == task_name)
        ).first():
            db.add(CustomTask(date=today, name=task_name, time="18:00", memo="Low fat"))
            messages.append(f"Seeded Task '{task_name}' for Today ({today})")

        tomorrow = today + datetime.timedelta(days=1)
        tasks_tomorrow = [("13:00", "Lunch with Alice", "At the Italian place"), ("15:00", "Doctor Appointment", "Bring ID")]
        for time, name, memo in tasks_tomorrow:
            if not db.exec(
                select(CustomTask).where(CustomTask.date == tomorrow, CustomTask.name == name)
            ).first():
                db.add(CustomTask(date=tomorrow, name=name, time=time, memo=memo))
                messages.append(f"Seeded Task '{name}' for Tomorrow ({tomorrow})")

        day_after = today + datetime.timedelta(days=2)
        task_name_da = "Gym"
        if not db.exec(
            select(CustomTask).where(
                CustomTask.date == day_after, CustomTask.name == task_name_da
            )
        ).first():
            db.add(CustomTask(date=day_after, name=task_name_da, time="19:00", memo="Leg day"))
            messages.append(f"Seeded Task '{task_name_da}' for Day after Tomorrow ({day_after})")

        db.commit()

        if not messages:
            return {"status": "ok", "message": "Data already exists, nothing new seeded."}

        return {"status": "ok", "message": "; ".join(messages)}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# 日本語: 評価ログの保存 / English: Save evaluation log
@app.post("/api/evaluation/log", name="evaluation_log")
async def evaluation_log(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
    except Exception:
        data = {}
    try:
        res = EvaluationResult(
            model_name=data.get("model_name"),
            task_prompt=data.get("task_prompt"),
            agent_reply=data.get("agent_reply"),
            tool_calls=json.dumps(data.get("tool_calls", [])),
            is_success=data.get("is_success"),
            comments=data.get("comments"),
        )
        db.add(res)
        db.commit()
        return {"status": "ok"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# 日本語: 評価履歴の取得 / English: Fetch evaluation history
@app.get("/api/evaluation/history", name="evaluation_history")
def evaluation_history(db: Session = Depends(get_db)):
    results = db.exec(
        select(EvaluationResult).order_by(EvaluationResult.timestamp.desc())
    ).all()
    data = []
    for r in results:
        data.append(
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat(),
                "model_name": r.model_name,
                "task_prompt": r.task_prompt,
                "is_success": r.is_success,
            }
        )
    return {"history": data}
