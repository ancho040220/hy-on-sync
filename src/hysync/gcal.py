"""구글 캘린더 비공개 iCal 주소에서 시험 일정을 읽는다.

구글 캘린더 → 설정 → (내 캘린더) → 캘린더 통합 → 'iCal 형식의 비공개 주소'.
이 주소만 있으면 OAuth 없이 읽기 전용으로 접근할 수 있으므로 반드시 Secret으로 보관한다.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import httpx
from icalendar import Calendar

from .dates import KST
from .models import KIND_EXAM, Item


def fetch_exams(ics_url: str, keyword: str, now: datetime, http: httpx.Client | None = None) -> list[Item]:
    client = http or httpx.Client(timeout=20.0, follow_redirects=True)
    resp = client.get(ics_url)
    resp.raise_for_status()
    return parse_exams(resp.content, keyword, now)


def parse_exams(ics: bytes, keyword: str, now: datetime, horizon_days: int = 120) -> list[Item]:
    """제목에 keyword(쉼표로 여러 개) 중 하나가 들어간 일정 중 어제 이후 ~ horizon_days일 안의 것만 고른다."""
    keywords = [k.strip() for k in keyword.split(",") if k.strip()]
    cal = Calendar.from_ical(ics)
    lo, hi = now - timedelta(days=1), now + timedelta(days=horizon_days)
    exams: list[Item] = []
    for event in cal.walk("VEVENT"):
        summary = str(event.get("SUMMARY", "")).strip()
        if not any(k in summary for k in keywords) or "RRULE" in event:
            continue
        raw = event.decoded("DTSTART")
        all_day = not isinstance(raw, datetime) and isinstance(raw, date)
        if all_day:
            start = datetime.combine(raw, time(0, 0), tzinfo=KST)
        else:
            start = raw if raw.tzinfo else raw.replace(tzinfo=KST)
            start = start.astimezone(KST)
        if not (lo <= start <= hi):
            continue
        exams.append(
            Item(
                lms_id=f"exam-{event.get('UID')}",
                kind=KIND_EXAM,
                course="",
                title=summary,
                due_at=start,
                all_day=all_day,
            )
        )
    return exams
