"""가짜 클라이언트로 sync.run 전체 흐름을 검증한다."""

from datetime import timedelta
from pathlib import Path

from conftest import make_item, make_record

from hysync.config import Config
from hysync.gcal_writer import GcalError
from hysync.kakao import KakaoError
from hysync.models import KIND_EXAM, Item
from hysync.state import load_state
from hysync.sync import run


class FakeCanvas:
    def __init__(self, items, videos=()):
        self.items, self.videos = list(items), list(videos)

    def fetch_items(self, aliases):
        return self.items

    def fetch_videos(self):
        return self.videos


class FakeNotion:
    def __init__(self, records, after_write=None):
        self.records = records
        self.after_write = after_write  # 쓰기 뒤 다시 읽을 때 돌려줄 레코드
        self.created, self.updated = [], []
        self.queries = 0

    def query_all(self):
        self.queries += 1
        if self.queries > 1 and self.after_write is not None:
            return self.after_write
        return self.records

    def create(self, item, start, sent):
        self.created.append((item.lms_id, set(sent)))

    def update(self, page_id, item, start, sent):
        self.updated.append((page_id, set(sent)))


class FakeKakao:
    def __init__(self, fail=False):
        self.fail, self.sent, self.new_refresh_token = fail, [], None

    def send_text(self, text, link):
        if self.fail:
            raise KakaoError("boom")
        self.sent.append(text)


class FakeGcal:
    def __init__(self, existing=(), fail=False):
        self.existing, self.fail = list(existing), fail
        self.created, self.updated, self.deleted = [], [], []

    def list_events(self):
        if self.fail:
            raise GcalError("boom")
        return self.existing

    def create(self, event):
        self.created.append(event)

    def update(self, event):
        self.updated.append(event)

    def delete(self, event_id):
        self.deleted.append(event_id)


def cfg(tmp_path: Path) -> Config:
    return Config("https://lms.test", "t", "n", "db", state_path=tmp_path / "alert_log.json")


def test_run_creates_sends_and_saves_state(tmp_path, now):
    new = make_item(due=now + timedelta(days=5))
    near = make_item(lms_id="assignment-1-20", title="Lab 2", due=now + timedelta(hours=30))
    exam = Item("exam-a", KIND_EXAM, "", "데이터베이스 기말시험", now + timedelta(hours=20))
    notion = FakeNotion([make_record(near, start=near.due_at - timedelta(days=7), sent={"신규"})])
    kakao = FakeKakao()

    result = run(cfg(tmp_path), now=now, canvas=FakeCanvas([new, near]), notion=notion, kakao=kakao, exams=[exam])

    assert result.kakao_ok and result.created == 1 and result.updated == 1
    assert notion.created == [("assignment-1-10", {"신규"})]
    assert notion.updated == [("page-assignment-1-20", {"신규", "D-3"})]
    text = "\n".join(kakao.sent)
    assert "[D-1] 데이터베이스 기말시험" in text and "[D-3] 시스템 프로그래밍 · Lab 2" in text and "[새 과제]" in text
    assert load_state(tmp_path / "alert_log.json")["exam-a"]["sent"] == ["D-1"]


def test_run_does_not_record_alerts_when_kakao_fails(tmp_path, now):
    near = make_item(due=now + timedelta(hours=30))
    record = make_record(near, start=near.due_at - timedelta(days=7), sent={"신규"})
    notion = FakeNotion([record])

    result = run(cfg(tmp_path), now=now, canvas=FakeCanvas([near]), notion=notion, kakao=FakeKakao(fail=True), exams=[])

    assert not result.kakao_ok
    assert notion.updated == [("page-assignment-1-10", {"신규"})]  # D-3 기록을 남기지 않아 다음에 다시 보낸다
    assert not (tmp_path / "alert_log.json").exists()


def test_dry_run_writes_nothing(tmp_path, now, capsys):
    notion = FakeNotion([])
    kakao = FakeKakao()
    run(cfg(tmp_path), now=now, dry_run=True, canvas=FakeCanvas([make_item(due=now + timedelta(days=2))]), notion=notion, kakao=kakao, exams=[])
    out = capsys.readouterr().out
    assert "노션에 새로 만들 항목" in out and "[새 과제]" in out
    assert notion.created == [] and kakao.sent == []


# ---- 구글 캘린더 미러 ----

def test_run_mirrors_notion_to_gcal_after_writes(tmp_path, now):
    new = make_item(due=now + timedelta(days=5))
    notion = FakeNotion([], after_write=[make_record(new, start=new.due_at - timedelta(days=7))])
    gcal = FakeGcal()

    result = run(cfg(tmp_path), now=now, canvas=FakeCanvas([new]), notion=notion, kakao=FakeKakao(), exams=[], gcal=gcal)

    assert notion.queries == 2
    assert [e.summary for e in gcal.created] == ["시스템 프로그래밍 · Lab 3"]
    assert result.gcal_ok and result.gcal_changes == 1


def test_run_skips_requery_when_nothing_written(tmp_path, now):
    notion = FakeNotion([])
    run(cfg(tmp_path), now=now, canvas=FakeCanvas([]), notion=notion, kakao=FakeKakao(), exams=[], gcal=FakeGcal())
    assert notion.queries == 1


def test_gcal_failure_keeps_state_and_kakao_and_marks_failure(tmp_path, now):
    exam = Item("exam-a", KIND_EXAM, "", "데이터베이스 기말시험", now + timedelta(hours=20))
    kakao = FakeKakao()

    result = run(cfg(tmp_path), now=now, canvas=FakeCanvas([]), notion=FakeNotion([]), kakao=kakao, exams=[exam],
                 gcal=FakeGcal(fail=True))

    assert result.kakao_ok and not result.gcal_ok
    assert kakao.sent
    assert load_state(tmp_path / "alert_log.json")["exam-a"]["sent"] == ["D-1"]


def test_dry_run_prints_gcal_plan_without_writing(tmp_path, now, capsys):
    item = make_item(due=now + timedelta(days=5))
    notion = FakeNotion([make_record(item, start=item.due_at - timedelta(days=7), sent={"신규"})])
    gcal = FakeGcal()

    run(cfg(tmp_path), now=now, dry_run=True, canvas=FakeCanvas([item]), notion=notion, kakao=FakeKakao(), exams=[],
        gcal=gcal)

    out = capsys.readouterr().out
    assert "구글 캘린더에 만들 일정" in out and "시스템 프로그래밍 · Lab 3" in out
    assert gcal.created == gcal.updated == gcal.deleted == []


def test_run_without_gcal_config_skips_mirror(tmp_path, now, monkeypatch):
    monkeypatch.chdir(tmp_path)  # 프로젝트 폴더의 실제 키 파일을 보지 않게
    result = run(cfg(tmp_path), now=now, canvas=FakeCanvas([]), notion=FakeNotion([]), kakao=FakeKakao(), exams=[])
    assert result.gcal_ok and result.gcal_changes == 0


class BrokenGcal(FakeGcal):
    """GcalError가 아닌 예외(예: 잘못된 키의 KeyError)를 던진다."""

    def list_events(self):
        raise KeyError("client_email")


class FlakyGcal(FakeGcal):
    """첫 번째 만들기만 실패한다."""

    def create(self, event):
        if not self.created and not getattr(self, "failed", False):
            self.failed = True
            raise GcalError("400 bad event")
        super().create(event)


def _exam_alert_setup(now):
    return Item("exam-a", KIND_EXAM, "", "데이터베이스 기말시험", now + timedelta(hours=20))


def test_broken_key_file_does_not_block_kakao_or_state(tmp_path, now):
    key = tmp_path / "sa.json"
    key.write_text("{not json", encoding="utf-8")
    c = Config("https://lms.test", "t", "n", "db", state_path=tmp_path / "alert_log.json",
               gcal_target_calendar_id="cal@group.calendar.google.com", gcal_service_account_file=key)
    kakao = FakeKakao()

    result = run(c, now=now, canvas=FakeCanvas([]), notion=FakeNotion([]), kakao=kakao, exams=[_exam_alert_setup(now)])

    assert kakao.sent and result.kakao_ok and not result.gcal_ok
    assert load_state(tmp_path / "alert_log.json")["exam-a"]["sent"] == ["D-1"]


def test_unexpected_gcal_exception_keeps_state(tmp_path, now):
    result = run(cfg(tmp_path), now=now, canvas=FakeCanvas([]), notion=FakeNotion([]), kakao=FakeKakao(),
                 exams=[_exam_alert_setup(now)], gcal=BrokenGcal())
    assert not result.gcal_ok
    assert load_state(tmp_path / "alert_log.json")["exam-a"]["sent"] == ["D-1"]


def test_notion_requery_failure_keeps_state(tmp_path, now):
    import httpx

    class FailingRequery(FakeNotion):
        def query_all(self):
            self.queries += 1
            if self.queries > 1:
                raise httpx.ConnectTimeout("notion timeout")
            return self.records

    new = make_item(due=now + timedelta(days=5))
    result = run(cfg(tmp_path), now=now, canvas=FakeCanvas([new]), notion=FailingRequery([]), kakao=FakeKakao(),
                 exams=[_exam_alert_setup(now)], gcal=FakeGcal())
    assert result.created == 1 and not result.gcal_ok
    assert load_state(tmp_path / "alert_log.json")["exam-a"]["sent"] == ["D-1"]


def test_one_failing_event_does_not_stop_the_rest(tmp_path, now):
    a = make_item(lms_id="assignment-1-10", title="Lab 3", due=now + timedelta(days=5))
    b = make_item(lms_id="assignment-1-11", title="Lab 4", due=now + timedelta(days=6))
    records = [make_record(a, start=a.due_at - timedelta(days=7), sent={"신규"}),
               make_record(b, start=b.due_at - timedelta(days=7), sent={"신규"})]
    gcal = FlakyGcal(existing=[])

    result = run(cfg(tmp_path), now=now, canvas=FakeCanvas([a, b]), notion=FakeNotion(records), kakao=FakeKakao(),
                 exams=[], gcal=gcal)

    assert [e.summary for e in gcal.created] == ["시스템 프로그래밍 · Lab 4"]
    assert not result.gcal_ok and result.gcal_changes == 1


def test_dry_run_survives_unexpected_gcal_exception(tmp_path, now, capsys):
    run(cfg(tmp_path), now=now, dry_run=True, canvas=FakeCanvas([]), notion=FakeNotion([]), kakao=FakeKakao(),
        exams=[], gcal=BrokenGcal())
    assert "구글 캘린더" in capsys.readouterr().out
