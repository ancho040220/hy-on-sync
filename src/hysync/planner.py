"""동기화 계획: 무엇을 만들고 고치고 어떤 알림을 보낼지 정한다.

네트워크를 전혀 쓰지 않는 순수 함수만 둔다. 그래서 테스트로 규칙을 그대로 검증할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .dates import due_stage, parse_iso, same_instant, start_date
from .models import (
    DUE_STAGES,
    KIND_EXAM,
    KIND_VIDEO,
    NOTION_KINDS,
    SENT_NEW,
    GcalEvent,
    Item,
    NotionRecord,
)

STATUS_DONE = "완료"


@dataclass(frozen=True)
class Alert:
    tag: str  # "새 과제", "D-3", "D-1", "마감 변경" ...
    item: Item
    old_due: datetime | None = None


@dataclass
class Create:
    item: Item
    start: datetime | None
    sent: set[str]


@dataclass
class Update:
    record: NotionRecord
    item: Item
    start: datetime | None
    sent: set[str]


@dataclass
class NotionPlan:
    creates: list[Create] = field(default_factory=list)
    updates: list[Update] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)


# 제출하지 않는 성적 칸(중간고사 점수 등). 날짜가 붙어 있어도 과제로 보지 않는다.
NO_SUBMISSION_TYPES = frozenset({"none", "not_graded", "on_paper"})


def effective_due(due_at: datetime | None, lock_at: datetime | None, submission_types: list[str] | None) -> datetime | None:
    """과제의 실제 마감. 마감일이 비어 있고 제출하는 과제면 제출 가능 종료일(lock_at)을 마감으로 본다.

    교수님이 마감일 없이 '이용 가능 종료일'만 넣는 경우가 있다(예: 데이터베이스 실습 과제3).
    마감일이 있으면 종료일은 무시한다 (종료일은 지각 제출 기간인 경우가 많다).
    """
    if due_at is not None:
        return due_at
    types = set(submission_types or [])
    if lock_at is not None and types and not types <= NO_SUBMISSION_TYPES:
        return lock_at
    return None


def _new_tag(item: Item) -> str:
    return f"새 {item.kind}"


def plan_notion(
    items: list[Item],
    records: list[NotionRecord],
    now: datetime,
    offset_days: int = 7,
) -> NotionPlan:
    """LMS 과제·퀴즈와 노션 레코드를 비교해 생성·갱신·알림을 정한다.

    규칙 (계획서 '데이터 설계'·'알림 설계'):
    1. LMS ID로 레코드를 찾고, 없으면 과목+과제명이 같은 수동 레코드에 연결, 그래도 없으면 새로 만든다.
       단, 마감일이 지난 항목은 새로 만들지 않고, 마감일이 없는 항목은 만들지도 연결하지도 않는다.
    2. 새 항목은 '새 과제/퀴즈' 알림. 이미 D-3·D-1 구간이면 그 단계도 보낸 것으로 기록해 중복을 막는다.
    3. 마감일이 바뀌면 날짜를 덮어쓰고 '마감 변경' 알림. D-3·D-1 기록은 지우고 현재 단계만 다시 기록한다.
    4. D-3·D-1 구간에 처음 들어가면 한 번만 알림. '완료' 상태면 보내지 않는다.
    5. 진행 상태와 메모는 건드리지 않는다.
    """
    plan = NotionPlan()
    by_id = {r.lms_id: r for r in records if r.lms_id}
    manual = {(r.course, r.title): r for r in records if not r.lms_id}

    for item in items:
        if item.kind not in NOTION_KINDS:
            continue
        start = start_date(item.unlock_at, item.due_at, offset_days)
        stage = due_stage(item.due_at, now)

        record = by_id.get(item.lms_id)
        linking = False
        if record is None:
            if item.due_at is None:
                continue  # 마감 없는 항목은 만들지도, 손으로 넣은 항목에 연결하지도 않는다
            record = manual.pop((item.course, item.title), None)
            linking = record is not None

        if record is None:
            if item.due_at < now:
                continue
            sent = {SENT_NEW} | ({stage} if stage else set())
            plan.creates.append(Create(item, start, sent))
            plan.alerts.append(Alert(_new_tag(item), item))
            continue

        sent = set(record.sent)
        done = record.status == STATUS_DONE
        due_changed = not same_instant(record.end, item.due_at)

        if linking:
            # 손으로 넣어둔 항목: 날짜는 LMS 기준으로 맞추되 알림은 보내지 않는다.
            sent.add(SENT_NEW)
            if stage:
                sent.add(stage)
        elif due_changed:
            sent -= set(DUE_STAGES)
            if stage:
                sent.add(stage)
            if not done:
                plan.alerts.append(Alert("마감 변경", item, old_due=record.end))
        elif stage and stage not in sent:
            sent.add(stage)
            if not done:
                plan.alerts.append(Alert(stage, item))

        if linking or _differs(record, item, start, sent):
            plan.updates.append(Update(record, item, start, sent))

    return plan


def _differs(record: NotionRecord, item: Item, start: datetime | None, sent: set[str]) -> bool:
    return (
        record.title != item.title
        or record.course != item.course
        or record.kind != item.kind
        or record.url != item.url
        or not same_instant(record.start, start)
        or not same_instant(record.end, item.due_at)
        or record.sent != sent
    )


# ---------------------------------------------------------------------------
# 노션에 없는 항목(시험·동영상)의 알림 기록: state/alert_log.json
#   {"<lms_id>": {"due": "<ISO>", "sent": ["신규", "D-3"]}}
# 과목명·제목은 저장하지 않는다 (저장소에 커밋되므로).
# ---------------------------------------------------------------------------

def plan_state(
    items: list[Item],
    state: dict[str, dict],
    now: datetime,
    keep_days: int = 1,
) -> tuple[list[Alert], dict[str, dict]]:
    """시험·동영상 알림을 정하고 새 상태를 돌려준다.

    - 신규 알림은 없다. 시험은 내가 직접 등록하고, 동영상은 학기 초에 한꺼번에 열리기 때문이다.
    - 시험·동영상 모두 D-7·D-3·D-1. 구간에 처음 들어가면 한 번만.
    - 동영상이 이미 출석 처리됐으면(done) 알리지 않는다. 마감이 지난 항목은 단계가 없어 알리지 않는다.
    - 마감이 바뀌면 D-7·D-3·D-1 기록을 초기화한다 (변경 알림은 과제·퀴즈만).
    - 마감이 keep_days일 넘게 지난 기록은 지운다.
    """
    alerts: list[Alert] = []
    new_state: dict[str, dict] = {}

    for item in items:
        if item.due_at is None:
            continue
        entry = state.get(item.lms_id)
        stage = due_stage(item.due_at, now, week=item.kind in (KIND_VIDEO, KIND_EXAM))

        sent: set[str] = set(entry.get("sent", [])) if entry else set()
        if entry and not same_instant(parse_iso(entry.get("due")), item.due_at):
            sent -= set(DUE_STAGES)
        if stage and stage not in sent and not item.done:
            alerts.append(Alert(stage, item))
            sent.add(stage)

        if item.due_at >= now - timedelta(days=keep_days):
            new_state[item.lms_id] = {"due": item.due_at.isoformat(), "sent": sorted(sent)}

    return alerts, new_state


# ---- 구글 캘린더 미러 ----

@dataclass
class GcalPlan:
    creates: list[GcalEvent] = field(default_factory=list)
    updates: list[GcalEvent] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)


def desired_events(records: list[NotionRecord]) -> list[GcalEvent]:
    """노션 레코드를 구글 일정 모양으로 바꾼다. 날짜가 없는 레코드는 뺀다."""
    events = []
    for r in records:
        if r.start is None:
            continue
        summary = f"{r.course} · {r.title}" if r.course else r.title
        if r.status == STATUS_DONE:
            summary = "✓ " + summary
        events.append(GcalEvent(r.page_id.replace("-", "").lower(), summary, r.start, r.end or r.start, r.url or ""))
    return events


def plan_gcal(records: list[NotionRecord], existing: list[GcalEvent]) -> GcalPlan:
    """노션 과제DB를 전용 캘린더에 그대로 비추려면 무엇을 만들고 고치고 지울지 정한다.

    지워진(cancelled) 일정은 같은 ID로 새로 만들 수 없어서 고치기로 되살린다.
    노션에 없는 일정은 지우되, 이 스크립트가 만든 일정(owned)만 지운다.
    캘린더 ID를 잘못 넣어 개인 캘린더를 가리켜도 다른 일정을 지우지 않기 위해서다.
    """
    plan = GcalPlan()
    current = {e.id: e for e in existing}
    wanted = desired_events(records)
    for want in wanted:
        have = current.get(want.id)
        if have is None:
            plan.creates.append(want)
        elif (
            have.cancelled
            or have.summary != want.summary
            or have.description != want.description
            or not same_instant(have.start, want.start)
            or not same_instant(have.end, want.end)
        ):
            plan.updates.append(want)
    wanted_ids = {w.id for w in wanted}
    plan.deletes = [e.id for e in existing if e.id not in wanted_ids and e.owned and not e.cancelled]
    return plan
