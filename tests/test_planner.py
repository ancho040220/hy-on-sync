from dataclasses import replace
from datetime import timedelta, timezone

from conftest import make_item, make_record

from hysync.models import KIND_EXAM, KIND_QUIZ, KIND_VIDEO, GcalEvent, Item, NotionRecord
from hysync.planner import desired_events, plan_gcal, plan_notion, plan_state


# ---- 노션 대상(과제·퀴즈) ----

def test_new_item_is_created_with_new_alert(now):
    item = make_item(due=now + timedelta(days=5))
    plan = plan_notion([item], [], now)
    assert len(plan.creates) == 1
    assert plan.creates[0].sent == {"신규"}
    assert plan.creates[0].start == item.due_at - timedelta(days=7)
    assert [a.tag for a in plan.alerts] == ["새 과제"]


def test_new_item_already_in_d1_records_stage_without_second_alert(now):
    item = make_item(due=now + timedelta(hours=10), kind=KIND_QUIZ, lms_id="quiz-1-11")
    plan = plan_notion([item], [], now)
    assert plan.creates[0].sent == {"신규", "D-1"}
    assert [a.tag for a in plan.alerts] == ["새 퀴즈"]


def test_entering_d3_sends_once(now):
    item = make_item(due=now + timedelta(hours=60))
    record = make_record(item, start=item.due_at - timedelta(days=7), sent={"신규"})
    plan = plan_notion([item], [record], now)
    assert [a.tag for a in plan.alerts] == ["D-3"]
    assert plan.updates[0].sent == {"신규", "D-3"}

    record.sent = {"신규", "D-3"}
    again = plan_notion([item], [record], now)
    assert again.alerts == []
    assert again.updates == []


def test_done_items_get_no_due_alerts(now):
    item = make_item(due=now + timedelta(hours=10))
    record = make_record(item, start=item.due_at - timedelta(days=7), sent={"신규"}, status="완료")
    plan = plan_notion([item], [record], now)
    assert plan.alerts == []
    assert plan.updates[0].sent == {"신규", "D-1"}  # 기록은 남겨 나중에 상태를 되돌려도 중복 없음


def test_due_change_alerts_and_resets_stages(now):
    old_due = now + timedelta(hours=20)
    item = make_item(due=now + timedelta(days=4))
    record = make_record(item, start=old_due - timedelta(days=7), sent={"신규", "D-3", "D-1"}, end=old_due)
    plan = plan_notion([item], [record], now)
    assert [(a.tag, a.old_due) for a in plan.alerts] == [("마감 변경", old_due)]
    assert plan.updates[0].sent == {"신규"}


def test_manual_record_is_linked_silently(now):
    item = make_item(due=now + timedelta(days=5))
    record = make_record(item, lms_id=None, end=None, sent=set())
    plan = plan_notion([item], [record], now)
    assert plan.creates == []
    assert plan.alerts == []
    assert plan.updates[0].record is record
    assert plan.updates[0].sent == {"신규"}


def test_exam_and_video_are_never_written_to_notion(now):
    exam = make_item(lms_id="exam-x", kind=KIND_EXAM, due=now + timedelta(days=2))
    video = make_item(lms_id="video-1-1", kind=KIND_VIDEO, due=now + timedelta(days=2))
    plan = plan_notion([exam, video], [], now)
    assert plan.creates == [] and plan.alerts == []


def test_item_without_due_is_not_created(now):
    item = make_item(due=None, title="Midterm Exam")
    plan = plan_notion([item], [], now)
    assert plan.creates == [] and plan.alerts == []


def test_item_without_due_does_not_touch_manual_record(now):
    item = make_item(due=None, title="중간고사", course="데이터베이스")
    record = make_record(item, lms_id=None, end=now + timedelta(days=10), sent=set())
    plan = plan_notion([item], [record], now)
    assert plan.creates == [] and plan.updates == [] and plan.alerts == []


def test_past_item_is_not_created(now):
    item = make_item(due=now - timedelta(hours=1))
    plan = plan_notion([item], [], now)
    assert plan.creates == [] and plan.alerts == []


def test_past_item_already_in_notion_is_still_updated(now):
    item = make_item(due=now - timedelta(days=2), title="Lab 3 (수정)")
    record = make_record(item, start=item.due_at - timedelta(days=7), sent={"신규"})
    record.title = "Lab 3"
    plan = plan_notion([item], [record], now)
    assert plan.creates == [] and plan.alerts == []
    assert len(plan.updates) == 1


def test_title_change_updates_without_alert(now):
    item = make_item(due=now + timedelta(days=10), title="Lab 3 (수정)")
    record = make_record(item, start=item.due_at - timedelta(days=7), sent={"신규"})
    record.title = "Lab 3"
    plan = plan_notion([item], [record], now)
    assert plan.alerts == []
    assert len(plan.updates) == 1


# ---- 상태 파일 대상(시험·동영상) ----

def test_video_gets_d7_d3_d1_once_each_and_no_new_alert(now):
    due = now + timedelta(days=6, hours=12)
    video = Item("video-1-5", KIND_VIDEO, "데이터베이스", "Ch10.빅데이터1", due)

    alerts, state = plan_state([video], {}, now)
    assert [a.tag for a in alerts] == ["D-7"]  # '새 동영상' 알림은 없다
    alerts, state = plan_state([video], state, now + timedelta(hours=1))
    assert alerts == []
    alerts, state = plan_state([video], state, due - timedelta(hours=60))
    assert [a.tag for a in alerts] == ["D-3"]
    alerts, state = plan_state([video], state, due - timedelta(hours=20))
    assert [a.tag for a in alerts] == ["D-1"]
    assert state["video-1-5"]["sent"] == ["D-1", "D-3", "D-7"]


def test_video_far_from_due_gets_nothing_yet(now):
    video = Item("video-1-7", KIND_VIDEO, "데이터베이스", "Ch10.빅데이터2", now + timedelta(days=10))
    alerts, state = plan_state([video], {}, now)
    assert alerts == [] and state["video-1-7"]["sent"] == []


def test_attended_video_gets_no_alerts(now):
    video = Item("video-1-5", KIND_VIDEO, "데이터베이스", "Ch6.ER모델1", now + timedelta(hours=20), done=True)
    alerts, state = plan_state([video], {}, now)
    assert alerts == []

    alerts, _ = plan_state([video], state, now + timedelta(hours=1))
    assert alerts == []


def test_new_video_already_past_due_gets_no_alert(now):
    old = Item("video-1-6", KIND_VIDEO, "데이터베이스", "Ch1.서론-1", now - timedelta(hours=2))
    alerts, _ = plan_state([old], {}, now)
    assert alerts == []


def test_exam_has_no_d7(now):
    exam = Item("exam-c", KIND_EXAM, "", "운영체제 기말고사", now + timedelta(days=5))
    alerts, _ = plan_state([exam], {}, now)
    assert alerts == []


def test_new_exam_has_no_new_alert_but_gets_stage(now):
    far = Item("exam-a", KIND_EXAM, "", "데이터베이스 기말시험", now + timedelta(days=10), all_day=True)
    near = Item("exam-b", KIND_EXAM, "", "시스템 프로그래밍 기말시험", now + timedelta(hours=30))
    alerts, state = plan_state([far, near], {}, now)
    assert [(a.tag, a.item.lms_id) for a in alerts] == [("D-3", "exam-b")]
    assert state["exam-a"]["sent"] == []
    assert state["exam-b"]["sent"] == ["D-3"]


def test_state_due_change_resets_stages(now):
    exam = Item("exam-a", KIND_EXAM, "", "기말시험", now + timedelta(hours=20))
    old = {"exam-a": {"due": (now + timedelta(days=3, hours=1)).isoformat(), "sent": ["D-3", "D-1"]}}
    alerts, state = plan_state([exam], old, now)
    assert [a.tag for a in alerts] == ["D-1"]
    assert state["exam-a"]["sent"] == ["D-1"]


# ---- 구글 캘린더 미러 ----

EID = "2d5e992f8cd081aabb00000000000001"


def _rec(now, **overrides):
    base = dict(
        page_id="2d5e992f-8cd0-81aa-bb00-000000000001", title="퀴즈 1", course="데이터베이스",
        lms_id="quiz-1-1", kind=KIND_QUIZ, start=now, end=now + timedelta(hours=2),
        url="https://lms/q", status="시작 전",
    )
    base.update(overrides)
    return NotionRecord(**base)


def test_gcal_creates_event_for_new_record(now):
    rec = _rec(now)
    plan = plan_gcal([rec], [])
    assert plan.creates == [GcalEvent(EID, "데이터베이스 · 퀴즈 1", rec.start, rec.end, "https://lms/q")]
    assert plan.updates == [] and plan.deletes == []


def test_gcal_done_record_gets_check_prefix(now):
    assert desired_events([_rec(now, status="완료")])[0].summary == "✓ 데이터베이스 · 퀴즈 1"


def test_gcal_record_without_course_uses_title_only(now):
    assert desired_events([_rec(now, course=None)])[0].summary == "퀴즈 1"


def test_gcal_unchanged_event_is_left_alone_across_timezones(now):
    rec = _rec(now, url=None)
    same = GcalEvent(EID, "데이터베이스 · 퀴즈 1", rec.start.astimezone(timezone.utc), rec.end + timedelta(seconds=30), "")
    plan = plan_gcal([rec], [same])
    assert plan.creates == [] and plan.updates == [] and plan.deletes == []


def test_gcal_changed_title_is_updated(now):
    rec = _rec(now)
    old = GcalEvent(EID, "데이터베이스 · 옛 제목", rec.start, rec.end, "https://lms/q")
    assert [e.summary for e in plan_gcal([rec], [old]).updates] == ["데이터베이스 · 퀴즈 1"]


def test_gcal_cancelled_event_is_revived_by_update(now):
    gone = replace(desired_events([_rec(now)])[0], cancelled=True)
    plan = plan_gcal([_rec(now)], [gone])
    assert plan.creates == [] and [e.id for e in plan.updates] == [EID] and not plan.updates[0].cancelled


def test_gcal_orphan_event_is_deleted_but_cancelled_orphan_is_not(now):
    orphan = GcalEvent("abc12345", "x", now, now, owned=True)
    dead = GcalEvent("abc67890", "y", now, now, cancelled=True, owned=True)
    assert plan_gcal([], [orphan, dead]).deletes == ["abc12345"]


def test_gcal_never_deletes_events_it_did_not_create(now):
    # 캘린더 ID를 잘못 넣어 개인 캘린더를 가리켜도 수업·알바 일정은 지우지 않는다
    personal = GcalEvent("1d981e67f6cc4a2cb9e8c9376bca3a18", "자료구조론", now, now)
    assert plan_gcal([], [personal]).deletes == []


def test_gcal_record_without_date_is_not_mirrored_and_its_event_is_deleted(now):
    rec = _rec(now, start=None, end=None)
    existing = GcalEvent(EID, "데이터베이스 · 퀴즈 1", now, now, owned=True)
    plan = plan_gcal([rec], [existing])
    assert plan.creates == [] and plan.deletes == [EID]


def test_state_prunes_old_entries(now):
    old_exam = Item("exam-old", KIND_EXAM, "", "중간시험", now - timedelta(days=3))
    _, state = plan_state([old_exam], {"exam-old": {"due": old_exam.due_at.isoformat(), "sent": ["D-1"]}}, now)
    assert state == {}
