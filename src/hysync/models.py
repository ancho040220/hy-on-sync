"""데이터 모델: LMS·캘린더에서 읽은 항목과 노션 과제DB의 레코드."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

KIND_ASSIGNMENT = "과제"
KIND_QUIZ = "퀴즈"
KIND_EXAM = "시험"
KIND_VIDEO = "동영상"

# 노션 과제DB에 등록하는 유형. 시험·동영상은 카카오톡 알림만 보낸다.
NOTION_KINDS = frozenset({KIND_ASSIGNMENT, KIND_QUIZ})

# 노션 '알림 기록'(다중 선택)과 상태 파일에 저장하는 값
SENT_NEW = "신규"
SENT_D7 = "D-7"  # 동영상만
SENT_D3 = "D-3"
SENT_D1 = "D-1"
DUE_STAGES = (SENT_D7, SENT_D3, SENT_D1)


@dataclass(frozen=True)
class Item:
    """LMS 과제·퀴즈·동영상 또는 구글 캘린더 시험 일정 하나."""

    lms_id: str  # 예: assignment-1234-56789, quiz-1234-56790, exam-<UID>
    kind: str
    course: str
    title: str
    due_at: datetime | None
    unlock_at: datetime | None = None
    url: str | None = None
    all_day: bool = False  # 종일 일정(시험)이면 시각 없이 날짜만 표시
    done: bool = False  # 동영상: 이미 출석 처리됨


@dataclass
class NotionRecord:
    """노션 과제DB의 페이지 하나에서 이 도구가 쓰는 속성만 뽑은 것."""

    page_id: str
    title: str
    course: str | None
    lms_id: str | None
    kind: str | None
    start: datetime | None
    end: datetime | None
    url: str | None
    status: str | None
    sent: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class GcalEvent:
    """구글 캘린더 'HY-ON 과제' 캘린더의 일정 하나 (노션 레코드를 비춘 것)."""

    id: str
    summary: str
    start: datetime
    end: datetime
    description: str = ""
    cancelled: bool = False
    owned: bool = False  # 이 스크립트가 만든 일정인지 (extendedProperties 표시)
