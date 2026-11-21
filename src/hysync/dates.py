"""날짜 계산: KST 변환, 시작일 역산, D-3/D-1 판단, 표시 형식."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .models import SENT_D1, SENT_D3, SENT_D7

KST = ZoneInfo("Asia/Seoul")
WEEKDAYS = "월화수목금토일"


def parse_iso(value: str | None) -> datetime | None:
    """Canvas·노션의 ISO 8601 문자열을 KST datetime으로 바꾼다. 시간대가 없으면 KST로 본다."""
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def start_date(unlock_at: datetime | None, due_at: datetime | None, offset_days: int = 7) -> datetime | None:
    """시작일 = 공개일, 공개일이 없으면 마감 offset_days일 전. 마감보다 늦을 수는 없다."""
    if due_at is None:
        return unlock_at
    candidate = unlock_at or (due_at - timedelta(days=offset_days))
    return min(candidate, due_at)


def due_stage(due_at: datetime | None, now: datetime, week: bool = False) -> str | None:
    """남은 시간이 24시간 이하면 D-1, 72시간 이하면 D-3, (week면) 7일 이하면 D-7, 그 밖이나 지났으면 None."""
    if due_at is None:
        return None
    remaining = due_at - now
    if remaining <= timedelta(0):
        return None
    if remaining <= timedelta(hours=24):
        return SENT_D1
    if remaining <= timedelta(hours=72):
        return SENT_D3
    if week and remaining <= timedelta(days=7):
        return SENT_D7
    return None


def same_instant(a: datetime | None, b: datetime | None) -> bool:
    """1분 이내 차이는 같은 시각으로 본다 (노션이 초 단위를 버리는 경우 대비)."""
    if a is None or b is None:
        return a is b
    return abs(a - b) < timedelta(minutes=1)


def fmt_due(dt: datetime | None, all_day: bool = False) -> str:
    """12/5(금) 23:59 형식. 종일 일정은 12/15(화)."""
    if dt is None:
        return "마감 없음"
    dt = dt.astimezone(KST)
    day = f"{dt.month}/{dt.day}({WEEKDAYS[dt.weekday()]})"
    return day if all_day else f"{day} {dt:%H:%M}"
