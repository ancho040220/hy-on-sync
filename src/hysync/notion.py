"""노션 과제DB 읽기·쓰기.

Notion API를 httpx로 직접 부르고 버전을 2022-06-28로 고정한다.
과제DB는 데이터 소스가 하나뿐이라 이 버전의 databases/query로 충분하고,
SDK 버전이 바뀌어도 동작이 흔들리지 않는다.
"""

from __future__ import annotations

from datetime import datetime

import httpx

from .dates import parse_iso
from .models import Item, NotionRecord

NOTION_VERSION = "2022-06-28"

# 노션 과제DB 속성 이름 (계획서 '데이터 설계' 표와 같다)
P_TITLE = "과제명"
P_COURSE = "과목"
P_DATE = "마감 날짜"
P_STATUS = "진행 상태"
P_KIND = "유형"
P_LMS_ID = "LMS ID"
P_LINK = "링크"
P_SENT = "알림 기록"

STATUS_TODO = "시작 전"


class NotionStore:
    def __init__(self, token: str, database_id: str, http: httpx.Client | None = None):
        self.database_id = database_id
        self.http = http or httpx.Client(
            base_url="https://api.notion.com",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
            timeout=20.0,
        )

    def query_all(self) -> list[NotionRecord]:
        records: list[NotionRecord] = []
        body: dict = {"page_size": 100}
        while True:
            resp = self.http.post(f"/v1/databases/{self.database_id}/query", json=body)
            resp.raise_for_status()
            data = resp.json()
            records.extend(parse_page(p) for p in data["results"])
            if not data.get("has_more"):
                return records
            body["start_cursor"] = data["next_cursor"]

    def create(self, item: Item, start: datetime | None, sent: set[str]) -> str:
        props = build_properties(item, start, sent)
        props[P_STATUS] = {"status": {"name": STATUS_TODO}}
        resp = self.http.post(
            "/v1/pages",
            json={"parent": {"database_id": self.database_id}, "properties": props},
        )
        resp.raise_for_status()
        return resp.json()["id"]

    def update(self, page_id: str, item: Item, start: datetime | None, sent: set[str]) -> None:
        resp = self.http.patch(f"/v1/pages/{page_id}", json={"properties": build_properties(item, start, sent)})
        resp.raise_for_status()


def build_properties(item: Item, start: datetime | None, sent: set[str]) -> dict:
    """스크립트가 관리하는 속성만 만든다. 진행 상태·메모는 넣지 않는다."""
    if item.due_at is None:
        date = None
    elif start is None or start == item.due_at:
        date = {"start": item.due_at.isoformat()}
    else:
        date = {"start": start.isoformat(), "end": item.due_at.isoformat()}

    props: dict = {
        P_TITLE: {"title": [{"text": {"content": item.title[:2000]}}]},
        P_DATE: {"date": date},
        P_KIND: {"select": {"name": item.kind}},
        P_LMS_ID: {"rich_text": [{"text": {"content": item.lms_id}}]},
        P_LINK: {"url": item.url},
        # 없는 선택지 이름은 노션이 자동으로 추가한다
        P_SENT: {"multi_select": [{"name": s} for s in sorted(sent)]},
    }
    if item.course:
        props[P_COURSE] = {"select": {"name": item.course[:100]}}
    return props


def _plain(rich: list[dict] | None) -> str:
    return "".join(part.get("plain_text", "") for part in (rich or []))


def parse_page(page: dict) -> NotionRecord:
    props = page.get("properties", {})

    def prop(name: str) -> dict:
        return props.get(name) or {}

    date = prop(P_DATE).get("date") or {}
    start = parse_iso(date.get("start"))
    end = parse_iso(date.get("end")) or start  # 단일 날짜면 그 날짜를 마감으로 본다
    course = (prop(P_COURSE).get("select") or {}).get("name")
    kind = (prop(P_KIND).get("select") or {}).get("name")
    status = (prop(P_STATUS).get("status") or {}).get("name")
    lms_id = _plain(prop(P_LMS_ID).get("rich_text")) or None
    sent = {o["name"] for o in prop(P_SENT).get("multi_select") or []}

    return NotionRecord(
        page_id=page["id"],
        title=_plain(prop(P_TITLE).get("title")),
        course=course,
        lms_id=lms_id,
        kind=kind,
        start=start,
        end=end,
        url=prop(P_LINK).get("url"),
        status=status,
        sent=sent,
    )
