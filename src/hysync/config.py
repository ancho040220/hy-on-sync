"""환경 변수 설정. 로컬에서는 프로젝트 루트의 .env를, GitHub Actions에서는 Secrets를 쓴다."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def load_dotenv(path: Path | None = None) -> None:
    """KEY=VALUE 형식의 .env를 읽어 아직 없는 환경 변수만 채운다.

    기본은 현재 폴더의 .env. MCP 서버처럼 실행 폴더가 다를 때는 HYSYNC_ENV_FILE로 경로를 준다.
    """
    path = path or Path(os.environ.get("HYSYNC_ENV_FILE", ".env"))
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Config:
    hyon_base_url: str
    hyon_token: str
    notion_token: str
    notion_database_id: str
    kakao_rest_key: str = ""
    kakao_client_secret: str = ""
    kakao_refresh_token: str = ""
    gcal_ics_url: str = ""
    exam_keyword: str = "시험,고사"
    start_offset_days: int = 7
    # Canvas 강의명 → 노션 '과목' 선택지 이름. 예: {"시스템프로그래밍(CSE4009-11)": "시스템 프로그래밍"}
    course_aliases: dict[str, str] = field(default_factory=dict)
    state_path: Path = Path("state/alert_log.json")
    # 노션 과제DB를 비출 구글 캘린더 전용 캘린더와 서비스 계정 키 파일
    gcal_target_calendar_id: str = ""
    gcal_service_account_file: Path = Path("gcal-service-account.json")

    @property
    def kakao_enabled(self) -> bool:
        return bool(self.kakao_rest_key and self.kakao_refresh_token)

    @property
    def gcal_mirror_enabled(self) -> bool:
        return bool(self.gcal_target_calendar_id) and self.gcal_service_account_file.exists()


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"환경 변수 {name}가 비어 있습니다. .env.example을 참고하세요.")
    return value


def load_config() -> Config:
    load_dotenv()
    return Config(
        hyon_base_url=_require("HYON_BASE_URL").rstrip("/"),
        hyon_token=_require("HYON_TOKEN"),
        notion_token=_require("NOTION_TOKEN"),
        notion_database_id=_require("NOTION_DATABASE_ID"),
        kakao_rest_key=os.environ.get("KAKAO_REST_KEY", ""),
        kakao_client_secret=os.environ.get("KAKAO_CLIENT_SECRET", ""),
        kakao_refresh_token=os.environ.get("KAKAO_REFRESH_TOKEN", ""),
        gcal_ics_url=os.environ.get("GCAL_ICS_URL", ""),
        exam_keyword=os.environ.get("EXAM_KEYWORD") or "시험,고사",
        start_offset_days=int(os.environ.get("START_OFFSET_DAYS", "7")),
        course_aliases=json.loads(os.environ.get("COURSE_ALIASES", "{}") or "{}"),
        gcal_target_calendar_id=os.environ.get("GCAL_TARGET_CALENDAR_ID", "").strip(),
        gcal_service_account_file=Path(os.environ.get("GCAL_SERVICE_ACCOUNT_FILE") or "gcal-service-account.json"),
    )
