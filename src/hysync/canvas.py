"""HY-ON(Canvas 기반) REST API 클라이언트.

HY-ON에서 개인 액세스 토큰(계정 → 설정 → 새 액세스 토큰)을 발급할 수 있다는 전제다.
발급이 막혀 있으면 계획서의 1차 대안(캘린더 피드 .ics)으로 바꾼다.
"""

from __future__ import annotations

import re
from typing import Any, Iterator

import httpx

from .dates import parse_iso
from .models import KIND_ASSIGNMENT, KIND_QUIZ, Item
from .planner import effective_due


class CanvasClient:
    def __init__(self, base_url: str, token: str, http: httpx.Client | None = None):
        self.http = http or httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=20.0,
        )

    def _get_all(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict]:
        """Link 헤더의 rel="next"를 따라가며 모든 페이지를 읽는다."""
        url: str | None = path
        while url:
            resp = self.http.get(url, params=params)
            resp.raise_for_status()
            yield from resp.json()
            url = resp.links.get("next", {}).get("url")
            params = None  # next URL에 쿼리가 이미 들어 있다

    def courses(self) -> list[dict]:
        return list(self._get_all("/api/v1/courses", {"enrollment_state": "active", "per_page": 100}))

    def assignments(self, course_id: int) -> list[dict]:
        return list(self._get_all(f"/api/v1/courses/{course_id}/assignments", {"per_page": 100}))

    def assignment(self, course_id: int, assignment_id: int) -> dict:
        resp = self.http.get(f"/api/v1/courses/{course_id}/assignments/{assignment_id}")
        resp.raise_for_status()
        return resp.json()

    def fetch_items(self, aliases: dict[str, str] | None = None) -> list[Item]:
        """수강 중인 모든 강의의 과제·퀴즈를 Item으로 바꾼다.

        Canvas의 일반 퀴즈는 과제 목록에도 submission_types=["online_quiz"]로 함께 나오므로
        과제 API 하나로 둘 다 가져온다. (성적에 안 들어가는 연습 퀴즈는 빠진다.)
        """
        aliases = aliases or {}
        items: list[Item] = []
        for course in self.courses():
            name = course_name(course, aliases)
            for a in self.assignments(course["id"]):
                items.append(assignment_to_item(a, course["id"], name))
        return items

    def fetch_videos(self, aliases: dict[str, str] | None = None) -> list[Item]:
        """출석 인정 동영상의 기한과 출석 여부 (LearningX, learningx.py 참고)."""
        from .learningx import LearningXClient  # 순환 import를 피한다

        return LearningXClient(self, str(self.http.base_url).rstrip("/")).fetch_videos(aliases or {})


def course_name(course: dict, aliases: dict[str, str]) -> str:
    """'202620HY24987_데이터베이스' → '데이터베이스'. COURSE_ALIASES가 있으면 그게 우선한다."""
    raw = course.get("name", "")
    short = re.sub(r"^\d{6}HY\d+_", "", raw)
    return aliases.get(raw) or aliases.get(short, short)


def assignment_to_item(a: dict, course_id: int, course_name: str) -> Item:
    is_quiz = "online_quiz" in (a.get("submission_types") or []) or bool(a.get("is_quiz_assignment"))
    kind = KIND_QUIZ if is_quiz else KIND_ASSIGNMENT
    prefix = "quiz" if is_quiz else "assignment"
    return Item(
        lms_id=f"{prefix}-{course_id}-{a['id']}",
        kind=kind,
        course=course_name,
        title=a.get("name", "").strip(),
        due_at=effective_due(parse_iso(a.get("due_at")), parse_iso(a.get("lock_at")), a.get("submission_types")),
        unlock_at=parse_iso(a.get("unlock_at")),
        url=a.get("html_url"),
    )


def split_lms_id(lms_id: str) -> tuple[int, int]:
    """'assignment-1234-56789' → (1234, 56789)"""
    _, course_id, item_id = lms_id.split("-", 2)
    return int(course_id), int(item_id)


def html_to_text(html: str | None, limit: int = 2000) -> str:
    """과제 설명(HTML)을 MCP 응답용 일반 텍스트로 간단히 바꾼다."""
    if not html:
        return ""
    text = re.sub(r"<(br|/p|/div|/li)\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:limit]
