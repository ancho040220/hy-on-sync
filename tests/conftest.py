from datetime import datetime

import pytest

from hysync.dates import KST
from hysync.models import KIND_ASSIGNMENT, Item, NotionRecord


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 12, 1, 8, 0, tzinfo=KST)  # 화요일 08:00 실행


def make_item(lms_id="assignment-1-10", due=None, unlock=None, kind=KIND_ASSIGNMENT, title="Lab 3", course="시스템 프로그래밍"):
    return Item(lms_id=lms_id, kind=kind, course=course, title=title, due_at=due, unlock_at=unlock, url=f"https://lms.example/{lms_id}")


def make_record(item: Item, *, start=None, sent=None, status="시작 전", lms_id="same", end="same"):
    return NotionRecord(
        page_id="page-" + item.lms_id,
        title=item.title,
        course=item.course,
        lms_id=item.lms_id if lms_id == "same" else lms_id,
        kind=item.kind,
        start=start,
        end=item.due_at if end == "same" else end,
        url=item.url,
        status=status,
        sent=set(sent or []),
    )
