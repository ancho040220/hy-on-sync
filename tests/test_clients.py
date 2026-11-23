"""네트워크 없이 클라이언트 변환 로직과 메시지 묶기를 검증한다."""

import json
from datetime import datetime, timedelta

import httpx
import pytest

from conftest import make_item

from hysync.canvas import CanvasClient, assignment_to_item, html_to_text, split_lms_id
from hysync.config import load_config
from hysync.dates import KST
from hysync.gcal import parse_exams
from hysync.kakao import KakaoClient
from hysync.messages import format_messages
from hysync.notion import build_properties, parse_page
from hysync.planner import Alert


# ---- Canvas ----

def test_assignment_to_item_classifies_quiz_and_converts_dates():
    a = {"id": 77, "name": " 퀴즈 3 ", "due_at": "2026-12-04T14:59:00Z", "unlock_at": None,
         "html_url": "https://lms/q/77", "submission_types": ["online_quiz"]}
    item = assignment_to_item(a, 12, "데이터베이스")
    assert item.lms_id == "quiz-12-77"
    assert item.kind == "퀴즈"
    assert item.title == "퀴즈 3"
    assert item.due_at == datetime(2026, 12, 4, 23, 59, tzinfo=KST)
    assert split_lms_id(item.lms_id) == (12, 77)


def test_assignment_without_due_uses_lock_but_grade_column_does_not():
    lab3 = {"id": 2840155, "name": "실습 과제3", "due_at": None, "unlock_at": "2026-11-15T15:00:00Z",
            "lock_at": "2026-11-22T14:59:59Z", "submission_types": ["online_upload"]}
    midterm = {"id": 2836585, "name": "중간고사", "due_at": None, "unlock_at": "2026-11-05T15:00:00Z",
               "lock_at": "2026-12-22T14:59:59Z", "submission_types": ["none"]}
    assert assignment_to_item(lab3, 214032, "데이터베이스").due_at == datetime(2026, 11, 22, 23, 59, 59, tzinfo=KST)
    assert assignment_to_item(midterm, 214032, "데이터베이스").due_at is None


def test_canvas_follows_pagination_and_aliases():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/courses":
            return httpx.Response(200, json=[{"id": 1, "name": "시스템프로그래밍(CSE4009-11)"}])
        if path == "/api/v1/courses/1/assignments" and "page=2" not in str(request.url):
            return httpx.Response(
                200,
                json=[{"id": 10, "name": "Lab 1", "due_at": None, "submission_types": ["online_upload"]}],
                headers={"Link": '<https://lms.test/api/v1/courses/1/assignments?page=2>; rel="next"'},
            )
        return httpx.Response(200, json=[{"id": 11, "name": "Lab 2", "due_at": None, "submission_types": ["online_upload"]}])

    http = httpx.Client(base_url="https://lms.test", transport=httpx.MockTransport(handler))
    items = CanvasClient("https://lms.test", "t", http=http).fetch_items({"시스템프로그래밍(CSE4009-11)": "시스템 프로그래밍"})
    assert [i.lms_id for i in items] == ["assignment-1-10", "assignment-1-11"]
    assert {i.course for i in items} == {"시스템 프로그래밍"}


def test_canvas_strips_semester_code_from_course_name():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/courses":
            return httpx.Response(200, json=[
                {"id": 1, "name": "202620HY24987_데이터베이스"},
                {"id": 2, "name": "202620HY23639_알고리즘"},
            ])
        return httpx.Response(200, json=[{"id": 10, "name": "과제 1", "due_at": None, "submission_types": ["online_upload"]}])

    http = httpx.Client(base_url="https://lms.test", transport=httpx.MockTransport(handler))
    items = CanvasClient("https://lms.test", "t", http=http).fetch_items({"알고리즘": "알고리즘 설계"})
    assert [i.course for i in items] == ["데이터베이스", "알고리즘 설계"]


def test_html_to_text():
    assert html_to_text("<p>보고서 제출&nbsp;안내</p><ul><li>PDF</li></ul>") == "보고서 제출 안내\nPDF"


# ---- Notion ----

def test_notion_properties_roundtrip(now):
    item = make_item(due=now + timedelta(days=5))
    start = item.due_at - timedelta(days=7)
    props = build_properties(item, start, {"신규"})
    assert "진행 상태" not in props  # 스크립트는 진행 상태를 건드리지 않는다
    assert props["마감 날짜"]["date"] == {"start": start.isoformat(), "end": item.due_at.isoformat()}

    # 노션이 돌려주는 모양으로 바꿔 다시 읽는다
    page = {
        "id": "p1",
        "properties": {
            "과제명": {"title": [{"plain_text": item.title}]},
            "과목": {"select": {"name": item.course}},
            "마감 날짜": {"date": props["마감 날짜"]["date"]},
            "진행 상태": {"status": {"name": "진행 중"}},
            "유형": {"select": {"name": "과제"}},
            "LMS ID": {"rich_text": [{"plain_text": item.lms_id}]},
            "링크": {"url": item.url},
            "알림 기록": {"multi_select": [{"name": "신규"}]},
        },
    }
    rec = parse_page(page)
    assert (rec.lms_id, rec.status, rec.sent) == (item.lms_id, "진행 중", {"신규"})
    assert rec.start == start and rec.end == item.due_at


def test_notion_manual_page_without_new_properties():
    rec = parse_page({"id": "p2", "properties": {
        "과제명": {"title": [{"plain_text": "자료구조론 2차 과제"}]},
        "마감 날짜": {"date": {"start": "2026-04-20", "end": None}},
    }})
    assert rec.lms_id is None and rec.sent == set()
    assert rec.end == rec.start


# ---- Google Calendar iCal ----

ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:exam1@google.com
SUMMARY:\xeb\x8d\xb0\xec\x9d\xb4\xed\x84\xb0\xeb\xb2\xa0\xec\x9d\xb4\xec\x8a\xa4 \xea\xb8\xb0\xeb\xa7\x90\xec\x8b\x9c\xed\x97\x98
DTSTART:20261215T013000Z
DTEND:20261215T033000Z
END:VEVENT
BEGIN:VEVENT
UID:exam2@google.com
SUMMARY:\xec\x8b\x9c\xec\x8a\xa4\xed\x85\x9c \xed\x94\x84\xeb\xa1\x9c\xea\xb7\xb8\xeb\x9e\x98\xeb\xb0\x8d \xec\x8b\x9c\xed\x97\x98
DTSTART;VALUE=DATE:20261216
END:VEVENT
BEGIN:VEVENT
UID:other@google.com
SUMMARY:\xeb\x8f\x99\xec\x95\x84\xeb\xa6\xac \xeb\xaa\xa8\xec\x9e\x84
DTSTART:20261210T100000Z
END:VEVENT
END:VCALENDAR
"""


def test_parse_exams_filters_by_keyword_and_handles_all_day(now):
    exams = parse_exams(ICS, "시험", now)
    assert [e.title for e in exams] == ["데이터베이스 기말시험", "시스템 프로그래밍 시험"]
    timed, all_day = exams
    assert timed.due_at == datetime(2026, 12, 15, 10, 30, tzinfo=KST) and not timed.all_day
    assert all_day.due_at == datetime(2026, 12, 16, 0, 0, tzinfo=KST) and all_day.all_day
    assert timed.lms_id == "exam-exam1@google.com"


ICS_GOSA = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:mid@google.com
SUMMARY:운영체제 중간고사
DTSTART:20261210T010000Z
END:VEVENT
BEGIN:VEVENT
UID:final@google.com
SUMMARY:데이터베이스 기말시험
DTSTART:20261215T010000Z
END:VEVENT
BEGIN:VEVENT
UID:other@google.com
SUMMARY:동아리 모임
DTSTART:20261211T010000Z
END:VEVENT
END:VCALENDAR
""".encode()


def test_parse_exams_accepts_comma_separated_keywords(now):
    exams = parse_exams(ICS_GOSA, "시험, 고사", now)
    assert [e.title for e in exams] == ["운영체제 중간고사", "데이터베이스 기말시험"]


def test_parse_exams_ignores_empty_keywords(now):
    exams = parse_exams(ICS_GOSA, "시험, ,", now)
    assert [e.title for e in exams] == ["데이터베이스 기말시험"]


@pytest.mark.parametrize("value", [None, ""])
def test_exam_keyword_defaults_to_siheom_and_gosa(monkeypatch, tmp_path, value):
    monkeypatch.chdir(tmp_path)  # 프로젝트 .env를 읽지 않게
    monkeypatch.delenv("HYSYNC_ENV_FILE", raising=False)
    for name in ("HYON_BASE_URL", "HYON_TOKEN", "NOTION_TOKEN", "NOTION_DATABASE_ID"):
        monkeypatch.setenv(name, "x")
    if value is None:
        monkeypatch.delenv("EXAM_KEYWORD", raising=False)
    else:
        monkeypatch.setenv("EXAM_KEYWORD", value)
    assert load_config().exam_keyword == "시험,고사"


# ---- Kakao ----

def test_kakao_refresh_rotates_token_and_sends():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "kauth.kakao.com":
            return httpx.Response(200, json={"access_token": "A", "refresh_token": "R2"})
        return httpx.Response(200, json={"result_code": 0})

    client = KakaoClient("key", "secret", "R1", http=httpx.Client(transport=httpx.MockTransport(handler)))
    client.send_text("[D-1] 테스트", "https://lms.test")
    assert client.new_refresh_token == "R2"
    sent = calls[1]
    assert sent.headers["Authorization"] == "Bearer A"
    body = dict(httpx.QueryParams(sent.content.decode()))
    assert json.loads(body["template_object"])["text"] == "[D-1] 테스트"


# ---- 메시지 ----

def test_messages_sorted_by_urgency_and_split_under_200_chars(now):
    alerts = [Alert("새 과제", make_item(lms_id=f"assignment-1-{i}", title=f"주간 과제 {i}번 - 보고서 제출", due=now + timedelta(days=6, hours=i))) for i in range(8)]
    alerts.append(Alert("D-1", make_item(lms_id="assignment-1-99", title="Lab 3", due=now + timedelta(hours=5))))
    messages = format_messages(alerts)
    assert len(messages) > 1
    assert all(len(m) <= 200 for m in messages)
    assert messages[0].startswith("[D-1] 시스템 프로그래밍 · Lab 3 · 12/1(화) 13:00")


# ---- Google Calendar 쓰기 ----

def _service_account():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return {"client_email": "sa@test.iam.gserviceaccount.com", "private_key": pem.decode(),
            "token_uri": "https://oauth2.googleapis.com/token"}


def _gcal_client(routes):
    """routes: (method, path 끝부분) -> Response 를 돌려주는 함수. 받은 요청은 calls에 남긴다."""
    from hysync.gcal_writer import GoogleCalendarClient

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "at", "expires_in": 3600})
        return routes(request)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    return GoogleCalendarClient("cal@group.calendar.google.com", _service_account(), http=http), calls


def test_gcal_client_gets_token_with_signed_jwt_and_lists_all_pages():
    def routes(request):
        if "pageToken" not in request.url.params:
            return httpx.Response(200, json={"nextPageToken": "p2", "items": [
                {"id": "e1", "summary": "A", "status": "confirmed",
                 "start": {"dateTime": "2026-12-01T00:00:00Z"}, "end": {"dateTime": "2026-12-01T01:00:00Z"}},
                {"id": "e2", "summary": "B", "status": "confirmed", "description": "d",
                 "start": {"date": "2026-12-02"}, "end": {"date": "2026-12-03"}},
            ]})
        return httpx.Response(200, json={"items": [{"id": "e3", "status": "cancelled"}]})

    client, calls = _gcal_client(routes)
    events = client.list_events()
    assert [e.id for e in events] == ["e1", "e2", "e3"]
    assert events[0].start == datetime(2026, 12, 1, 9, 0, tzinfo=KST)
    assert events[1].start == datetime(2026, 12, 2, 0, 0, tzinfo=KST)
    assert events[2].cancelled and events[0].description == "" and events[1].description == "d"
    token_reqs = [c for c in calls if c.url.host == "oauth2.googleapis.com"]
    assert len(token_reqs) == 1
    assert b"grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer" in token_reqs[0].content
    list_req = calls[1]
    assert list_req.headers["Authorization"] == "Bearer at" and list_req.url.params["showDeleted"] == "true"


def test_gcal_client_create_falls_back_to_put_on_409():
    from hysync.models import GcalEvent

    def routes(request):
        return httpx.Response(409, json={}) if request.method == "POST" else httpx.Response(200, json={})

    client, calls = _gcal_client(routes)
    start = datetime(2026, 12, 1, 9, 0, tzinfo=KST)
    client.create(GcalEvent("e1", "데이터베이스 · 퀴즈 1", start, start + timedelta(hours=1), "https://lms/q"))
    put = calls[-1]
    assert put.method == "PUT" and put.url.path.endswith("/events/e1")
    body = json.loads(put.content)
    assert body["status"] == "confirmed" and body["start"] == {"dateTime": start.isoformat(), "timeZone": "Asia/Seoul"}
    assert body["summary"] == "데이터베이스 · 퀴즈 1" and body["description"] == "https://lms/q"


def test_gcal_client_delete_ignores_gone_and_raises_on_403():
    from hysync.gcal_writer import GcalError

    def routes(request):
        return httpx.Response(410) if request.url.path.endswith("/gone") else httpx.Response(403, text="forbidden")

    client, _ = _gcal_client(routes)
    client.delete("gone")
    with pytest.raises(GcalError):
        client.delete("forbidden")


def test_gcal_client_marks_events_it_writes_and_reads_the_mark():
    from hysync.models import GcalEvent

    def routes(request):
        if request.method == "GET":
            return httpx.Response(200, json={"items": [
                {"id": "mine", "status": "confirmed", "start": {"date": "2026-12-01"}, "end": {"date": "2026-12-02"},
                 "extendedProperties": {"private": {"hysync": "mirror"}}},
                {"id": "theirs", "status": "confirmed", "start": {"date": "2026-12-01"}, "end": {"date": "2026-12-02"}},
            ]})
        return httpx.Response(200, json={})

    client, calls = _gcal_client(routes)
    start = datetime(2026, 12, 1, 9, 0, tzinfo=KST)
    client.create(GcalEvent("e1", "A", start, start))
    assert json.loads(calls[-1].content)["extendedProperties"] == {"private": {"hysync": "mirror"}}
    owned = {e.id: e.owned for e in client.list_events()}
    assert owned == {"mine": True, "theirs": False}


# ---- LearningX 동영상 (출석 영상 기한) ----

LX_FORM = """<html><body><form action="https://lms.test/learningx/lti/lecture_attendance/course_menu" method="post">
<input type="hidden" name="oauth_signature" value="sig"><input type="hidden" name="user_id" value="u1"></form></body></html>"""


def _lx_transport(calls, items_status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        path = request.url.path
        if path == "/api/v1/courses":
            return httpx.Response(200, json=[{"id": 1, "name": "202620HY24987_데이터베이스"}])
        if path == "/api/v1/courses/1/external_tools":
            return httpx.Response(200, json=[
                {"id": 9, "url": "https://lms.test/learningx/lti/learnstatus"},
                {"id": 138, "url": "https://lms.test/learningx/lti/lecture_attendance/course_menu"},
            ])
        if path == "/api/v1/courses/1/external_tools/sessionless_launch":
            assert request.url.params["id"] == "138"
            return httpx.Response(200, json={"url": "https://lms.test/courses/1/external_tools/sessionless_launch?verifier=v"})
        if path == "/courses/1/external_tools/sessionless_launch":
            return httpx.Response(200, html=LX_FORM)
        if path == "/learningx/lti/lecture_attendance/course_menu":
            return httpx.Response(200, html="ok", headers={"Set-Cookie": "xn_api_token=XN; Path=/"})
        if path == "/learningx/api/v1/courses/1/attendance_items":
            if items_status != 200:
                return httpx.Response(items_status, text="boom XN")
            return httpx.Response(200, json={"attendance_items": [
                {"item_id": 11, "title": "Ch6.ER모델1", "use_attendance": True, "item_content_type": "commons",
                 "unlock_at": "2026-11-23T15:00:00Z", "due_at": "2026-11-29T14:59:59Z"},
                {"item_id": 12, "title": "Ch10.빅데이터1", "use_attendance": True, "item_content_type": "commons",
                 "unlock_at": None, "due_at": "2026-12-13T14:59:59Z"},
                {"item_id": 13, "title": "11/16(월) 대면 수업", "use_attendance": True, "item_content_type": "smart_attendance",
                 "due_at": "2026-11-16T07:00:00Z"},
                {"item_id": 14, "title": "Ch6.ER모델1", "use_attendance": False, "item_content_type": "commons",
                 "due_at": None},
                {"item_id": 15, "title": "참고 영상", "use_attendance": True, "item_content_type": "commons", "due_at": None},
            ], "counts": {}})
        if path == "/learningx/api/v1/courses/1/attendance_items/summary":
            return httpx.Response(200, json={"attendance_summaries": {
                "11": {"item_id": 11, "attendance_status": "attendance"},
                "12": {"item_id": 12, "attendance_status": "none"},
                "13": {"item_id": 13, "attendance_status": "absent"},
            }})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _lx_client(calls, items_status=200):
    from hysync.learningx import LearningXClient

    transport = _lx_transport(calls, items_status)
    canvas = CanvasClient("https://lms.test", "t", http=httpx.Client(base_url="https://lms.test", transport=transport,
                                                                      headers={"Authorization": "Bearer t"}))
    return LearningXClient(canvas, "https://lms.test", http=httpx.Client(transport=transport, follow_redirects=True))


def test_learningx_fetches_attendance_videos_with_status():
    calls = []
    videos = _lx_client(calls).fetch_videos({})

    assert [(v.lms_id, v.title, v.done) for v in videos] == [
        ("video-1-11", "Ch6.ER모델1", True),
        ("video-1-12", "Ch10.빅데이터1", False),
    ]
    assert {v.kind for v in videos} == {"동영상"} and {v.course for v in videos} == {"데이터베이스"}
    assert videos[1].due_at == datetime(2026, 12, 13, 23, 59, 59, tzinfo=KST)
    assert videos[0].url == "https://lms.test/courses/1/external_tools/138"

    lx_calls = [c for c in calls if c.url.path.startswith("/learningx/api/")]
    assert lx_calls and all(c.headers["Authorization"] == "Bearer XN" for c in lx_calls)
    assert lx_calls[0].url.params["include_detail"] == "true"
    launch_and_lx = [c for c in calls if not c.url.path.startswith("/api/v1/")]
    assert all(c.headers.get("Authorization") != "Bearer t" for c in launch_and_lx)  # Canvas 토큰은 LearningX로 보내지 않는다
    assert not any("user_login" in str(c.url) for c in calls)


def test_learningx_error_does_not_leak_token():
    from hysync.learningx import LearningXError

    with pytest.raises(LearningXError) as exc:
        _lx_client([], items_status=500).fetch_videos({})
    assert "XN" not in str(exc.value) and "500" in str(exc.value)


def test_learningx_changed_response_shape_raises_instead_of_silently_misreporting():
    from hysync.learningx import LearningXError

    calls = []
    base = _lx_transport(calls)

    def handler(request):
        if request.url.path.endswith("/attendance_items/summary"):
            return httpx.Response(200, json={"renamed": {}})  # 키 이름이 바뀐 응답
        return base.handle_request(request)

    transport = httpx.MockTransport(handler)
    from hysync.learningx import LearningXClient
    canvas = CanvasClient("https://lms.test", "t", http=httpx.Client(base_url="https://lms.test", transport=transport))
    client = LearningXClient(canvas, "https://lms.test", http=httpx.Client(transport=transport, follow_redirects=True))
    with pytest.raises(LearningXError) as exc:
        client.fetch_videos({})
    assert "XN" not in str(exc.value)


# ---- 디스코드 봇 DM ----

def _discord(handler):
    from hysync.discord import DiscordClient

    calls = []

    def wrapped(request):
        calls.append(request)
        return handler(request)

    http = httpx.Client(base_url="https://discord.com/api/v10", transport=httpx.MockTransport(wrapped))
    return DiscordClient("tok", "1234", http=http), calls


def test_discord_opens_dm_once_and_sends_each_message():
    def handler(request):
        if request.url.path.endswith("/users/@me/channels"):
            return httpx.Response(200, json={"id": "c1"})
        return httpx.Response(200, json={"id": "m"})

    client, calls = _discord(handler)
    client.send_text("[D-1] 데이터베이스 · 실습 과제3 · 11/22(일) 23:59", "https://lms.test")
    client.send_text("[D-3] 알고리즘 · 과제", "https://lms.test")

    dm = [c for c in calls if c.url.path.endswith("/users/@me/channels")]
    sends = [c for c in calls if c.url.path.endswith("/channels/c1/messages")]
    assert len(dm) == 1 and json.loads(dm[0].content) == {"recipient_id": "1234"}
    assert len(sends) == 2
    body = json.loads(sends[0].content)
    assert body["content"].startswith("[D-1] 데이터베이스 · 실습 과제3") and "https://lms.test" in body["content"]
    assert body["allowed_mentions"] == {"parse": []}
    assert all(c.headers["Authorization"] == "Bot tok" for c in calls)
    assert all(c.headers["User-Agent"].startswith("DiscordBot (") for c in calls)


def test_discord_error_does_not_leak_token():
    from hysync.discord import DiscordError

    client, _ = _discord(lambda request: httpx.Response(403, json={"message": "Missing Access tok", "code": 50001}))
    with pytest.raises(DiscordError) as exc:
        client.send_text("hi", "https://lms.test")
    assert "tok" not in str(exc.value) and "403" in str(exc.value)
