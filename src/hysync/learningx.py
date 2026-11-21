"""LearningX(HY-ON 동영상·출결) 출석 영상의 기한과 출석 여부를 읽는다.

LearningX는 Canvas 토큰을 받지 않는다. 그래서 Canvas 공식 API의 sessionless launch로
'출결현황' 과목 메뉴 도구를 열어 LearningX 토큰(xn_api_token 쿠키)을 받고, 그 화면이 쓰는
학생용 읽기 API 두 개를 부른다. 학교가 공개한 API가 아니므로 바뀌면 깨질 수 있다.

- 영상 항목 자체는 절대 열지 않는다 (시청·출석 기록에 영향을 줄 수 있음).
- 토큰·쿠키 값은 로그나 예외 메시지에 넣지 않는다.
"""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

import httpx

from .canvas import CanvasClient, course_name
from .dates import parse_iso
from .models import KIND_VIDEO, Item

ATTENDANCE_TOOL_PATH = "lecture_attendance/course_menu"


class LearningXError(RuntimeError):
    pass


class LearningXClient:
    def __init__(self, canvas: CanvasClient, base_url: str, http: httpx.Client | None = None):
        self.canvas = canvas
        self.base = base_url.rstrip("/")
        self.http = http or httpx.Client(timeout=30.0, follow_redirects=True)  # Canvas 토큰 없이 쿠키만 쓴다

    def fetch_videos(self, aliases: dict[str, str]) -> list[Item]:
        courses = self.canvas.courses()
        if not courses:
            return []
        tool_id, token = self._launch(courses[0]["id"])  # 토큰 하나로 모든 과목을 읽는다
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        videos: list[Item] = []
        for course in courses:
            cid = course["id"]
            items = self._get(f"/learningx/api/v1/courses/{cid}/attendance_items", {"include_detail": "true"},
                              headers, "attendance_items")
            status = self._get(f"/learningx/api/v1/courses/{cid}/attendance_items/summary",
                               {"only_use_attendance": "true"}, headers, "attendance_summaries")
            for it in items:
                if not (it.get("use_attendance") and it.get("due_at") and it.get("item_content_type") == "commons"):
                    continue  # 출석과 무관한 사본, 기한 없는 영상, 대면 스마트출결은 뺀다
                state = (status.get(str(it["item_id"])) or {}).get("attendance_status")
                videos.append(Item(
                    lms_id=f"video-{cid}-{it['item_id']}",
                    kind=KIND_VIDEO,
                    course=course_name(course, aliases),
                    title=(it.get("title") or "").strip(),
                    due_at=parse_iso(it["due_at"]),
                    unlock_at=parse_iso(it.get("unlock_at")),
                    url=f"{self.base}/courses/{cid}/external_tools/{tool_id}",
                    done=state == "attendance",
                ))
        return videos

    def _launch(self, course_id: int) -> tuple[int, str]:
        """'출결현황' 도구를 sessionless로 열어 (도구 ID, LearningX 토큰)을 돌려준다."""
        tools = list(self.canvas._get_all(f"/api/v1/courses/{course_id}/external_tools",
                                          {"include_parents": "true", "per_page": 100}))
        tool = next((t for t in tools if ATTENDANCE_TOOL_PATH in (t.get("url") or "")), None)
        if tool is None:
            raise LearningXError("출결현황(LearningX) 도구를 찾지 못했습니다.")
        resp = self.canvas.http.get(f"/api/v1/courses/{course_id}/external_tools/sessionless_launch",
                                    params={"id": tool["id"]})
        if resp.status_code != 200:
            raise LearningXError(f"sessionless launch 실패 ({resp.status_code})")
        page = self.http.get(resp.json()["url"])
        form = re.search(r'<form[^>]*action="([^"]+)"[^>]*>(.*?)</form>', page.text, re.S | re.I)
        if form is None:
            raise LearningXError("LearningX 실행 폼을 찾지 못했습니다.")
        fields = {k: unescape(v) for k, v in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form.group(2), re.I)}
        self.http.post(urljoin(str(page.url), unescape(form.group(1))), data=fields)  # 화면이 500이어도 토큰은 생긴다
        token = self.http.cookies.get("xn_api_token")
        if not token:
            raise LearningXError("LearningX 토큰(xn_api_token)을 받지 못했습니다.")
        return tool["id"], token

    def _get(self, path: str, params: dict, headers: dict, key: str):
        """응답의 key 값을 돌려준다. 응답 모양이 바뀌면 조용히 빈 값을 쓰지 않고 실패한다
        (빈 값을 쓰면 알림이 멈추거나, 이미 본 영상까지 '새 동영상'으로 알리게 된다)."""
        resp = self.http.get(f"{self.base}{path}", params=params, headers=headers)
        if resp.status_code != 200:
            raise LearningXError(f"LearningX 요청 실패 ({resp.status_code}): {path}")
        data = resp.json()
        if not isinstance(data, dict) or key not in data:
            raise LearningXError(f"LearningX 응답 형식이 바뀌었습니다 ('{key}' 없음): {path}")
        return data[key] or ({} if key == "attendance_summaries" else [])
