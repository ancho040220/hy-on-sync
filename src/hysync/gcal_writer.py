"""구글 캘린더 'HY-ON 과제' 전용 캘린더에 일정을 쓴다 (서비스 계정).

준비: 구글 클라우드에서 서비스 계정 키(JSON)를 만들고, 전용 캘린더를 서비스 계정 이메일에
'일정 변경' 권한으로 공유한다. 키 파일은 비밀값이므로 커밋하지 않는다.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, time as dtime
from pathlib import Path
from urllib.parse import quote

import httpx
import jwt

from .dates import KST, parse_iso
from .models import GcalEvent

SCOPE = "https://www.googleapis.com/auth/calendar.events"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3/calendars"
MARK_KEY, MARK_VALUE = "hysync", "mirror"


class GcalError(RuntimeError):
    pass


def load_service_account(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class GoogleCalendarClient:
    def __init__(self, calendar_id: str, service_account: dict, http: httpx.Client | None = None):
        self.base = f"{API}/{quote(calendar_id, safe='')}/events"
        self.sa = service_account
        self.http = http or httpx.Client(timeout=20.0)
        self._access_token: str | None = None

    def _headers(self) -> dict[str, str]:
        if self._access_token is None:
            now = int(time.time())
            claims = {"iss": self.sa["client_email"], "scope": SCOPE, "aud": TOKEN_URL, "iat": now, "exp": now + 3600}
            assertion = jwt.encode(claims, self.sa["private_key"], algorithm="RS256")
            resp = self.http.post(
                TOKEN_URL,
                data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
            )
            if resp.status_code != 200:
                raise GcalError(f"구글 인증 실패 ({resp.status_code}). 서비스 계정 키와 Calendar API 사용 설정을 확인하세요.")
            self._access_token = resp.json()["access_token"]
        return {"Authorization": f"Bearer {self._access_token}"}

    def _check(self, resp: httpx.Response, ok: tuple[int, ...] = ()) -> None:
        if not (200 <= resp.status_code < 300 or resp.status_code in ok):
            raise GcalError(f"구글 캘린더 요청 실패 ({resp.status_code}): {resp.text[:200]}")

    def list_events(self) -> list[GcalEvent]:
        events: list[GcalEvent] = []
        params: dict[str, str] = {"showDeleted": "true", "maxResults": "250"}
        while True:
            resp = self.http.get(self.base, params=params, headers=self._headers())
            self._check(resp)
            data = resp.json()
            events.extend(_parse_event(e) for e in data.get("items", []))
            token = data.get("nextPageToken")
            if not token:
                return events
            params = {**params, "pageToken": token}

    def create(self, event: GcalEvent) -> None:
        resp = self.http.post(self.base, json=_body(event), headers=self._headers())
        if resp.status_code == 409:  # 지워진 일정이 같은 ID를 잡고 있다 → 고치면서 되살린다
            self.update(event)
            return
        self._check(resp)

    def update(self, event: GcalEvent) -> None:
        resp = self.http.put(f"{self.base}/{event.id}", json=_body(event), headers=self._headers())
        self._check(resp)

    def delete(self, event_id: str) -> None:
        resp = self.http.delete(f"{self.base}/{event_id}", headers=self._headers())
        self._check(resp, ok=(404, 410))


def _body(event: GcalEvent) -> dict:
    return {
        "id": event.id,
        "summary": event.summary,
        "description": event.description,
        "start": {"dateTime": event.start.isoformat(), "timeZone": "Asia/Seoul"},
        "end": {"dateTime": event.end.isoformat(), "timeZone": "Asia/Seoul"},
        "status": "confirmed",
        # 이 표시가 있는 일정만 지운다 (plan_gcal 참고)
        "extendedProperties": {"private": {MARK_KEY: MARK_VALUE}},
    }


def _when(part: dict | None) -> datetime:
    part = part or {}
    if part.get("dateTime"):
        return parse_iso(part["dateTime"])
    if part.get("date"):
        return datetime.combine(datetime.fromisoformat(part["date"]).date(), dtime(0, 0), tzinfo=KST)
    return datetime.min.replace(tzinfo=KST)  # 지워진 일정은 시각이 없을 수 있다


def _parse_event(e: dict) -> GcalEvent:
    return GcalEvent(
        id=e["id"],
        summary=e.get("summary", ""),
        start=_when(e.get("start")),
        end=_when(e.get("end")),
        description=e.get("description", ""),
        cancelled=e.get("status") == "cancelled",
        owned=((e.get("extendedProperties") or {}).get("private") or {}).get(MARK_KEY) == MARK_VALUE,
    )
