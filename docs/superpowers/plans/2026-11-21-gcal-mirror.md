# 구글 캘린더 미러 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 동기화할 때마다 노션 과제DB를 구글 캘린더의 전용 캘린더('HY-ON 과제')에 그대로 비춘다.

**Architecture:** 비교 규칙은 `planner.py`의 순수 함수 `plan_gcal`에 둔다. 구글 API 호출은 새 모듈 `gcal_writer.py`의 `GoogleCalendarClient`가 맡는다. 서비스 계정 JWT로 인증하고 `httpx`로 직접 호출한다. `sync.run`은 노션 쓰기 뒤에 미러 단계를 실행한다. 미러 오류는 그 단계 안에서 잡아서 상태 저장과 카카오 토큰 기록은 그대로 진행한다.

**Tech Stack:** Python 3.11/3.12, httpx, pyjwt[crypto](새 기본 의존성), pytest + httpx.MockTransport

**Spec:** `docs/superpowers/specs/2026-11-21-gcal-mirror-design.md`

## Global Constraints

- HTTP는 `httpx`로 직접 호출한다. 구글 클라이언트 라이브러리는 쓰지 않는다.
- 동기화 규칙은 `planner.py`에만 둔다. 규칙 테스트는 `tests/test_planner.py`에 먼저 쓴다.
- 시간대는 `Asia/Seoul`이다(`hysync.dates.KST`).
- 범위(scope)는 `https://www.googleapis.com/auth/calendar.events`, 토큰 주소는 `https://oauth2.googleapis.com/token`이다.
- 일정 ID는 노션 `page_id`에서 `-`를 빼고 소문자로 바꾼 값이다.
- 제목은 `{과목} · {과제명}`이고, 진행 상태가 `완료`면 앞에 `✓ `를 붙인다. 과목이 없으면 과제명만 쓴다.
- 설정 이름: `GCAL_TARGET_CALENDAR_ID`, `GCAL_SERVICE_ACCOUNT_FILE`(기본값 `gcal-service-account.json`). Actions Secret 이름은 `GCAL_SERVICE_ACCOUNT_JSON`이다.
- `.env`와 키 파일 내용은 읽거나 출력하지 않는다.
- **커밋하지 않는다.** hy-on-sync의 첫 커밋은 6단계에서 한다(CLAUDE.md: 커밋은 요청이 있을 때만). 각 Task 끝에는 커밋 대신 전체 `pytest`를 돌린다.

## Review Focus

1. 구글이 시각을 `Z`나 다른 오프셋으로 돌려주거나 노션과 초 단위가 다르면, 실행할 때마다 '고칠 것'이 생기면 안 된다 → Task 1에서 `same_instant`로 비교하는지 테스트한다.
2. 설명(링크)이 노션에서는 `None`이고 구글에서는 빈 문자열이거나 키가 아예 없을 때도 매번 고치면 안 된다 → Task 1과 Task 2에서 빈 문자열로 맞추는지 테스트한다.
3. 전용 캘린더에 종일 일정(`date`만 있음)이 섞여 있어도 목록 읽기가 죽으면 안 되고, 대응하는 레코드가 없고 스크립트가 만든 표시(owned)가 있으면 지운다(최종 점검에서 owned 조건 추가) → Task 2 파싱 테스트.
4. 일정이 250개를 넘어 페이지가 나뉘면 모두 읽어야 한다. 하나라도 빠지면 그 일정은 중복 생성 시도(409)를 낳는다 → Task 2 페이지 넘김 테스트.
5. 구글 인증이나 권한이 실패해도 카톡 기록, 상태 파일, 카카오 토큰 파일은 정상 처리되고 종료 코드만 1이어야 한다 → Task 3 테스트.

---

### Task 1: 비교 규칙 `plan_gcal`

**Files:**
- Modify: `src/hysync/models.py` (`GcalEvent` 추가)
- Modify: `src/hysync/planner.py` (`GcalPlan`, `desired_events`, `plan_gcal` 추가)
- Test: `tests/test_planner.py`

**Interfaces:**
- Produces:
  - `models.GcalEvent` (frozen dataclass): `id: str`, `summary: str`, `start: datetime`, `end: datetime`, `description: str = ""`, `cancelled: bool = False`
  - `planner.GcalPlan` (dataclass): `creates: list[GcalEvent]`, `updates: list[GcalEvent]`, `deletes: list[str]`(일정 ID)
  - `planner.desired_events(records: list[NotionRecord]) -> list[GcalEvent]`
  - `planner.plan_gcal(records: list[NotionRecord], existing: list[GcalEvent]) -> GcalPlan`

- [ ] **Step 1: 실패하는 테스트 쓰기** (`tests/test_planner.py`, 새 절 `# ---- 구글 캘린더 미러 ----`)

`make_record`는 `page_id="page-" + lms_id`를 쓴다. 테스트용 레코드는 `dataclasses.replace(rec, page_id="2d5e992f-8cd0-81aa-bb00-000000000001")`처럼 page_id를 바꿔서 쓴다(ID는 `2d5e992f8cd081aabb00000000000001`이 된다).

```python
def test_gcal_creates_event_for_new_record(now):
    rec = _rec(now)  # course="데이터베이스", title="퀴즈 1", start=now, end=now+2h, url="https://lms/q", status="시작 전"
    plan = plan_gcal([rec], [])
    assert plan.creates == [GcalEvent("2d5e992f8cd081aabb00000000000001", "데이터베이스 · 퀴즈 1", rec.start, rec.end, "https://lms/q")]
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
    old = GcalEvent(EID, "데이터베이스 · 옛 제목", ...)  # 시각·설명은 같게
    assert [e.summary for e in plan_gcal([_rec(now)], [old]).updates] == ["데이터베이스 · 퀴즈 1"]

def test_gcal_cancelled_event_is_revived_by_update(now):
    gone = replace(desired_events([_rec(now)])[0], cancelled=True)
    plan = plan_gcal([_rec(now)], [gone])
    assert plan.creates == [] and [e.id for e in plan.updates] == [EID] and not plan.updates[0].cancelled

def test_gcal_orphan_event_is_deleted_but_cancelled_orphan_is_not(now):
    orphan = GcalEvent("abc12345", "x", now, now)
    dead = GcalEvent("abc67890", "y", now, now, cancelled=True)
    assert plan_gcal([], [orphan, dead]).deletes == ["abc12345"]

def test_gcal_record_without_date_is_not_mirrored_and_its_event_is_deleted(now):
    rec = _rec(now, start=None, end=None)
    existing = GcalEvent(EID, "데이터베이스 · 퀴즈 1", now, now)
    plan = plan_gcal([rec], [existing])
    assert plan.creates == [] and plan.deletes == [EID]
```

`_rec(now, **overrides)`와 `EID` 상수는 테스트 파일 안에 둔다.

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_planner.py -q -k gcal`
Expected: FAIL (`ImportError: cannot import name 'plan_gcal'`)

- [ ] **Step 3: 구현**

`desired_events`: `start`가 없는 레코드는 건너뛴다. `description = record.url or ""`. 제목 규칙은 Global Constraints대로 하고, `STATUS_DONE`을 재사용한다.
`plan_gcal`: 원하는 일정을 ID로 묶고 기존 일정과 비교한다. 같은지 판단은 `summary`와 `description`이 같고, `same_instant(start)`·`same_instant(end)`이며, `cancelled`가 False인 것이다. 기존 일정이 없으면 creates, 다르면(cancelled 포함) updates(`cancelled=False`인 원하는 일정), 원하는 일정에 없고 cancelled도 아닌 기존 일정은 deletes에 넣는다(최종 점검에서 `owned`인 일정만으로 좁힘). 결과 순서는 입력 레코드 순서를 따른다.

- [ ] **Step 4: 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 39 + 8 = 47 passed

---

### Task 2: 구글 캘린더 클라이언트

**Files:**
- Create: `src/hysync/gcal_writer.py`
- Modify: `pyproject.toml` (`dependencies`에 `"pyjwt[crypto]>=2.8"` 추가 후 `.venv\Scripts\python.exe -m pip install -e ".[dev,mcp]"` 다시 실행)
- Test: `tests/test_clients.py` (새 절 `# ---- Google Calendar 쓰기 ----`)

**Interfaces:**
- Consumes: `models.GcalEvent`
- Produces:
  - `gcal_writer.GcalError(RuntimeError)`
  - `gcal_writer.GoogleCalendarClient(calendar_id: str, service_account: dict, http: httpx.Client | None = None)`
    - `list_events() -> list[GcalEvent]`
    - `create(event: GcalEvent) -> None` (409면 `update`로 넘어간다)
    - `update(event: GcalEvent) -> None` (PUT, `status: "confirmed"`로 되살린다)
    - `delete(event_id: str) -> None` (404/410은 성공으로 본다)
  - `gcal_writer.load_service_account(path: Path) -> dict` (JSON 파일 읽기)

- [ ] **Step 1: 실패하는 테스트 쓰기**

테스트용 서비스 계정은 `cryptography`로 RSA 키를 만들어 PEM으로 넣는다: `{"client_email": "sa@test.iam.gserviceaccount.com", "private_key": <PEM>, "token_uri": "https://oauth2.googleapis.com/token"}`. `MockTransport` 핸들러는 토큰 요청(POST `oauth2.googleapis.com/token`)에 `{"access_token": "at", "expires_in": 3600}`를 돌려주고, 받은 요청을 리스트에 남긴다.

```python
def test_gcal_client_gets_token_with_signed_jwt_and_lists_all_pages():
    # 1쪽: nextPageToken="p2", items=[timed(Z 시각), all-day(date만)], 2쪽: items=[cancelled]
    events = client.list_events()
    assert [e.id for e in events] == ["e1", "e2", "e3"]
    assert events[0].start == datetime(2026, 12, 1, 9, 0, tzinfo=KST)        # "2026-12-01T00:00:00Z"
    assert events[1].start == datetime(2026, 12, 2, 0, 0, tzinfo=KST)        # date "2026-12-02"
    assert events[2].cancelled and events[0].description == ""               # description 키 없음
    token_req = calls[0]
    assert token_req.url.host == "oauth2.googleapis.com"
    assert b"grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer" in token_req.content
    list_req = calls[1]
    assert list_req.headers["Authorization"] == "Bearer at" and list_req.url.params["showDeleted"] == "true"

def test_gcal_client_create_falls_back_to_put_on_409():
    # POST .../events → 409, PUT .../events/e1 → 200
    client.create(GcalEvent("e1", "데이터베이스 · 퀴즈 1", start, end, "https://lms/q"))
    put = calls[-1]
    assert put.method == "PUT" and put.url.path.endswith("/events/e1")
    body = json.loads(put.content)
    assert body["status"] == "confirmed" and body["start"] == {"dateTime": start.isoformat(), "timeZone": "Asia/Seoul"}

def test_gcal_client_delete_ignores_gone_and_raises_on_403():
    client.delete("gone")       # 410 → 예외 없음
    with pytest.raises(GcalError):
        client.delete("forbidden")  # 403
```

토큰은 클라이언트 하나당 한 번만 받는지도 확인한다(`calls` 안의 토큰 요청이 1개).

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_clients.py -q -k gcal_client`
Expected: FAIL (`ModuleNotFoundError: hysync.gcal_writer`)

- [ ] **Step 3: 구현**

- 토큰: `jwt.encode({"iss": client_email, "scope": SCOPE, "aud": TOKEN_URL, "iat": now, "exp": now + 3600}, private_key, algorithm="RS256")`를 `grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion=...`로 POST한다. 처음 API를 부를 때 한 번 받아서 재사용한다.
- 기본 주소: `https://www.googleapis.com/calendar/v3/calendars/{quote(calendar_id, safe='')}/events`.
- 목록: `showDeleted=true`, `maxResults=250`, `nextPageToken`을 따라간다. 시각은 `start.dateTime`을 `parse_iso`로 읽고, 없으면 `start.date`를 KST 자정으로 읽는다. `status == "cancelled"`면 `cancelled=True`. `description`이 없으면 `""`. cancelled 일정에는 start가 없을 수 있으니 그때는 `datetime.min.replace(tzinfo=KST)`로 둔다.
- 일정 본문: `{"id", "summary", "description", "start": {"dateTime": iso, "timeZone": "Asia/Seoul"}, "end": {...}, "status": "confirmed"}`.
- 2xx가 아니면(위의 예외 제외) `GcalError(f"구글 캘린더 요청 실패 ({status}): {text[:200]}")`. 토큰 실패도 `GcalError`. 메시지에 키나 토큰을 넣지 않는다.

- [ ] **Step 4: 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 50 passed

---

### Task 3: 설정과 `sync.run` 연결

**Files:**
- Modify: `src/hysync/config.py`
- Modify: `src/hysync/sync.py`
- Test: `tests/test_sync.py`

**Interfaces:**
- Consumes: `planner.plan_gcal`, `gcal_writer.GoogleCalendarClient`, `gcal_writer.GcalError`, `gcal_writer.load_service_account`
- Produces:
  - `Config.gcal_target_calendar_id: str = ""`, `Config.gcal_service_account_file: Path = Path("gcal-service-account.json")`, 속성 `Config.gcal_mirror_enabled -> bool`(캘린더 ID가 있고 키 파일이 존재)
  - `run(..., gcal=None)`: 테스트용 주입. None이고 `cfg.gcal_mirror_enabled`면 실제 클라이언트를 만든다.
  - `Result.gcal_ok: bool = True`, `Result.gcal_changes: int = 0`
  - `main()`은 `kakao_ok and gcal_ok`일 때만 0을 돌려준다.

- [ ] **Step 1: 실패하는 테스트 쓰기**

`FakeGcal(existing=(), fail=False)`는 `list_events`, `create`, `update`, `delete` 호출을 기록한다. `fail=True`면 `list_events`에서 `GcalError("boom")`을 던진다. `FakeNotion.query_all`은 호출 횟수를 센다.

```python
def test_run_mirrors_notion_to_gcal_after_writes(tmp_path, now):
    # 새 과제 1개 → 노션 create 후 query_all을 다시 부른다(쓴 게 있으므로). 다시 읽은 레코드 1개를 미러한다.
    assert notion.queries == 2 and [e.summary for e in gcal.created] == ["시스템 프로그래밍 · Lab 3"]
    assert result.gcal_ok and result.gcal_changes == 1

def test_run_skips_requery_when_nothing_written(tmp_path, now):
    assert notion.queries == 1

def test_gcal_failure_keeps_state_and_kakao_and_marks_failure(tmp_path, now):
    # 시험 D-1 알림이 있는 상황 + FakeGcal(fail=True)
    assert result.kakao_ok and not result.gcal_ok
    assert load_state(tmp_path / "alert_log.json")["exam-a"]["sent"] == ["D-1"]

def test_dry_run_prints_gcal_plan_without_writing(tmp_path, now, capsys):
    assert "구글 캘린더에 만들 일정" in capsys.readouterr().out
    assert gcal.created == gcal.updated == gcal.deleted == []

def test_run_without_gcal_config_skips_mirror(tmp_path, now):
    # gcal 주입 없음, cfg 기본값(키 파일 없음) → 예외 없이 gcal_ok True, gcal_changes 0
```

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tests/test_sync.py -q`
Expected: 새 테스트 FAIL (`run()`에 `gcal` 인자 없음)

- [ ] **Step 3: 구현**

- `load_config`: `GCAL_TARGET_CALENDAR_ID`(빈 문자열 기본), `GCAL_SERVICE_ACCOUNT_FILE`(비어 있으면 기본 경로).
- `run`: 노션 쓰기 뒤, 상태 저장 앞에 미러 단계를 둔다. 미러할 레코드는 created나 updated가 있으면 `notion.query_all()`을 다시 부른 값, 없으면 처음 읽은 `records`다. `gcal.list_events()` → `plan_gcal` → creates/updates/deletes 순서로 반영한다. `(GcalError, httpx.HTTPError)`를 잡아 `log.error`를 남기고 `result.gcal_ok = False`로 둔다. 상태 저장과 카카오 토큰 파일 쓰기는 그대로 이어진다.
- dry-run: 처음 읽은 `records`로 `plan_gcal`을 계산해 `_print_plan` 뒤에 출력한다. 제목은 `== 구글 캘린더에 만들 일정 ==` / `== 구글 캘린더에서 고칠 일정 ==` / `== 구글 캘린더에서 지울 일정 ==`(개수와 제목). 구글 읽기가 실패하면 그 사실만 출력한다.
- 마지막 로그에 `구글 캘린더 변경 %d건`을 덧붙인다.

- [ ] **Step 4: 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 55 passed

---

### Task 4: 문서·설정·워크플로

**Files:**
- Modify: `.env.example`: `GCAL_TARGET_CALENDAR_ID=`와 `GCAL_SERVICE_ACCOUNT_FILE=gcal-service-account.json`, 그리고 설명 주석
- Modify: `.gitignore`: `gcal-service-account.json`
- Modify: `CLAUDE.md` '정해진 것': 시험 줄은 그대로 두고, 과제·퀴즈 줄에 "노션 과제DB를 구글 캘린더 전용 캘린더 'HY-ON 과제'에 그대로 비춘다(완료는 ✓, 서비스 계정)"를 추가한다. "노션 → 노션 캘린더 → 구글 캘린더 연동은 이미 되어 있다"는 "노션 캘린더 앱에서만 보인다"로 고친다. 테스트 개수를 55로 바꾼다.
- Modify: `README.md`: 첫 표의 과제 행 설명을 고치고, 준비 절에 '5. 구글 캘린더 (과제 미러)'를 넣는다(설계서 '사용자가 할 준비' 1~6). 스크립트가 만든 표시가 있는 일정만 지운다는 것(최종 점검에서 추가)과 노션 캘린더에서 숨길 것을 적고, 구조 목록에 `gcal_writer.py`를 추가한다.
- Modify: `docs/workflows/sync.yml`: Sync 단계 앞에 키 파일을 쓰는 단계를 넣는다(셸에서 검사: `if [ -n "$GCAL_SA" ]; then printf '%s' "$GCAL_SA" > gcal-service-account.json; fi`. 최종 리뷰 반영으로 단계 `if:` 대신 셸 검사로 바꿈). Sync env에 `GCAL_TARGET_CALENDAR_ID`를 추가한다. 맨 끝에 `if: always()`로 `rm -f gcal-service-account.json`.
- Modify: `docs/HANDOFF.md`: 진행 기록에 미러 기능을 추가하고, 6단계 Secrets 목록에 `GCAL_TARGET_CALENDAR_ID`, `GCAL_SERVICE_ACCOUNT_JSON`을 넣는다.

- [ ] **Step 1: 위 파일 수정**
- [ ] **Step 2: 확인**

Run: `.venv\Scripts\python.exe -m pytest -q` → 55 passed.
Run: `git check-ignore -v gcal-service-account.json` → `.gitignore` 규칙이 출력된다.

---

### Task 5: 실제 연결 (사용자 준비 후)

- [ ] **Step 1:** 사용자가 설계서의 '사용자가 할 준비' 1~4를 끝내고 알려 준다(키 파일 위치, `.env`의 캘린더 ID).
- [ ] **Step 2:** `.venv\Scripts\python.exe -m hysync.sync --dry-run` → `구글 캘린더에 만들 일정` 32건 안팎, 고칠·지울 일정 0건. 인증 오류가 나면 멈추고 원인 후보(API 꺼짐, 공유 안 됨, 캘린더 ID 틀림)를 알린다.
- [ ] **Step 3:** 사용자 승인 후 `.venv\Scripts\python.exe -m hysync.sync` → 종료 코드 0, 로그에 `구글 캘린더 변경 32건` 안팎.
- [ ] **Step 4:** 바로 다시 `--dry-run` → 구글 쪽 변경 0건(중복 없음).
- [ ] **Step 5:** 구글 캘린더 MCP(`list_events`, 해당 캘린더 ID)로 11/22 'Weighted Activity Selection' 일정이 있는지 확인한다.
- [ ] **Step 6:** `dev-harness:audit`로 변경 범위와 테스트를 점검하고, advisor에게 완료 확인을 받는다.
