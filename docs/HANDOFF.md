# 인계 노트 (2026-11-21)

claude.ai 대화에서 계획서와 구현 초안까지 만들었고, 이제 Claude Code에서 실제 서비스에 연결하는 단계다.

## 지금 상태

| 부분 | 상태 |
| --- | --- |
| 날짜 계산, 알림 규칙 (`dates.py`, `planner.py`) | 완료, 테스트로 검증 |
| Canvas·노션·카카오 클라이언트 | **실제 서비스로 확인 (2026-11-21)** |
| iCal 클라이언트 | **실제 피드로 확인 (2026-11-21):** 테스트 일정 2개를 '고사' 키워드로 읽음. '시험'은 지난 일정("쪽지시험")으로 확인 |
| `sync.py` 전체 흐름, `--dry-run` | **실제 1회 실행 (2026-11-21):** 노션 6건 생성, 카톡 3개 전송. 바로 다시 돌린 dry-run은 '바뀐 것 없음' |
| MCP 서버 (`list_upcoming`, `get_item`) | stdio 연결과 도구 호출을 가짜 HY-ON으로 확인 |
| GitHub Actions 워크플로 | `.github/workflows/sync.yml`로 옮김 (2026-11-21, 6단계). 아직 실행 안 해봄 |
| 동영상 강의 기한 (`fetch_videos`) | **구현 (2026-11-21, `learningx.py`)**. 로컬 dry-run: 출석 영상 51건 읽음, 알림은 출석 안 한 2건(빅데이터1·2)만 |

## 확인 안 된 가정

1. ~~HY-ON에서 개인 액세스 토큰을 발급할 수 있고 `/api/v1`로 접근된다.~~ **확인됨 (2026-11-21).** 도메인은 `learning.hanyang.ac.kr`이다. `lms.hanyang.ac.kr`은 `hy-mooc.hanyang.ac.kr/lmsapi`로 302 리다이렉트된다.
2. ~~일반 퀴즈는 과제 목록에 `submission_types: ["online_quiz"]`로 함께 나온다.~~ **확인됨 (2026-11-21).** 이번 학기 퀴즈 4개 모두 `online_quiz`이고, `external_tool`(새 퀴즈)은 없다. 마감 없는 성적 칸(`submission_types: ["none"]`, 예: 중간고사)도 과제 목록에 나오지만, 마감 없는 항목은 노션에 만들지 않는 규칙으로 걸러진다.
3. ~~노션 과제DB에 아래 속성 4개가 아직 없다.~~ **추가함 (2026-11-21, 노션 API로).**

   | 이름 | 종류 |
   | --- | --- |
   | 유형 | 선택 |
   | LMS ID | 텍스트 |
   | 링크 | URL |
   | 알림 기록 | 다중 선택 |

4. 과제DB ID는 `28e5992f8cd0811cb33bee82f6597713`이다 (노션 '과제 플래너' 페이지 안의 '과제DB').

## 남은 작업 순서

1. ~~환경 세팅, 테스트 확인~~ 완료
2. ~~HY-ON 접근 확인 (가정 1, 2)~~ 완료
3. ~~노션 연결, dry-run~~ 완료
4. ~~카카오톡 연결, 실제 1회 실행~~ 완료
5. ~~구글 캘린더 시험 연결~~ 완료
6. ~~GitHub 비공개 저장소, Actions 가동~~ 완료 (2026-11-21). 남은 것: `GH_PAT` Secret (12/21 전)
7. MCP 서버를 Claude Code·데스크톱에 등록 (사용자 결정: 지금은 하지 않음)
8. ~~동영상 기한 조사·구현~~ 완료 (2026-11-21, 브랜치 `feature/video-alerts` → PR)
9. README·데모 정리 → **12/13 완성**

## 2026-11-21 진행 기록 (1~5단계)

**환경**
- 로컬 `.venv`는 Python 3.11.9다. 이 PC에 3.12가 없다. `requires-python >=3.11`이라 문제는 없고, Actions는 3.12로 돈다.
- `hy-on-sync`에서 `git init`을 했다(브랜치 `main`, **커밋 없음**). 첫 커밋은 6단계에서 한다.
- WorkSpace 루트 `.gitignore`에 `hy-on-sync/`를 넣고 루트 저장소에 커밋했다(`4a777e5`).

**새로 정한 규칙** (사용자 결정, 테스트 먼저 추가. 지금 39개 통과)
- 시험 키워드: `EXAM_KEYWORD`를 쉼표로 여러 개 받는다. 기본값은 `시험,고사`다. 워크플로가 이 값을 넘기지 않으므로 Actions에서는 기본값이 쓰인다.
- 마감이 없는 LMS 항목은 노션에 만들지 않고, 손으로 넣은 항목에 연결하지도 않는다. HY-ON의 성적 칸(`Midterm Exam`, `중간고사`)이 손으로 넣은 항목의 날짜를 지우는 것을 막기 위해서다.
- 마감이 지난 항목은 새로 만들지 않는다. LMS ID로 이미 연결된 항목은 계속 갱신한다.
- 강의명 앞의 학기 코드(`202620HY24987_`)는 자동으로 뗀다. `COURSE_ALIASES`가 있으면 그게 우선한다(지금은 비어 있음).

**연결 결과**
- HY-ON: 강의 6개, 과제·퀴즈 36건. 이 중 앞으로 마감인 6건이 노션에 들어갔다. 시스템프로그래밍은 과제가 0건이다.
- 노션: 첫 실행 전에 DB를 비웠고, 지난 학기 `과목` 선택지는 사용자가 지웠다. 이번 학기 과목 선택지는 첫 실행 때 생겼다.
- 노션 학기 정리: 사용자 요청으로 마감이 지난 이번 학기 과제·퀴즈 26개를 일회용 스크립트로 '완료' 상태로 넣었다(알림 기록 '신규'). HY-ON상 미제출 2개(팀장 제출 등)도 사용자 결정으로 '완료'로 넣었다. 이후 동기화는 LMS ID로 이 항목들을 인식해 새로 만들거나 알리지 않는다(dry-run '바뀐 것 없음' 확인). 진행 상태를 쓴 것은 이 일회성 작업뿐이고, 동기화 규칙은 그대로다.
- 카카오: 테스트 메시지가 도착하는 것을 확인했다. 리프레시 토큰은 2026-11-21에 발급받아 약 2달 동안 유효하다.
- 구글 캘린더(5단계): 개인 Gmail 기본 캘린더의 비공개 iCal 주소를 쓴다. 테스트 일정 "테스트 중간고사"(12/22), "테스트기말고사"(12/23)가 읽히는 것을 확인했다. 새 일정이 피드에 반영되기까지 짧게 지연될 수 있다. **테스트 일정 2개는 사용자가 지워야 한다.** 그대로 두면 12월에 D-3·D-1 카톡이 간다.

**구글 캘린더 과제 미러 (2026-11-21 구현, 실제 연결 완료)**
- 실제 실행: 'HY-ON 과제' 캘린더에 32건 생성, 바로 다시 돌린 dry-run은 만들기·고치기·지우기 0건. 구글 캘린더 MCP로 일정(제목, ✓, 링크, 시간)을 확인했다. 서비스 계정은 전용 GCP 프로젝트 `hy-on-sync`에 있다.
- 소유 표시(`extendedProperties.private.hysync`)가 32건 모두에 남아 있는 것을 확인했다. 따라서 노션에서 지운 항목은 다음 동기화 때 구글에서도 지워진다.
- 노션 DB 항목은 노션 캘린더 앱에서만 보이고 구글 캘린더에는 써지지 않는다는 것을 확인했다. 그래서 동기화가 노션 과제DB 전체를 구글 전용 캘린더 'HY-ON 과제'에 비추도록 했다(설계: `docs/superpowers/specs/2026-11-21-gcal-mirror-design.md`, 계획: `docs/superpowers/plans/2026-11-21-gcal-mirror.md`).
- 사용자 준비(README '5. 구글 캘린더 (과제 미러)')가 끝나면 dry-run → 승인 → 실제 실행 → 재실행 dry-run '변경 0건' 순서로 확인한다.
- 6단계 Secrets에 `GCAL_TARGET_CALENDAR_ID`, `GCAL_SERVICE_ACCOUNT_JSON`(키 파일 내용 전체)을 추가한다.

**GitHub·Actions (6단계)**
- 저장소: `ancho040220/hy-on-sync` (비공개, 기본 브랜치 `main`). 첫 커밋 `ebdcc4c`만 사용자 동의로 main에 직접 push했다. 이후 작업은 브랜치로 한다. Actions 봇은 `state/alert_log.json`을 main에 커밋하므로, 로컬에서 작업하기 전에 `git pull`한다.
- Secrets는 `gh secret set -f .env`와 키 파일로 넣었다(13개). **`GH_PAT`은 아직 없다.** 카카오 리프레시 토큰이 2026-12-21쯤부터 새로 발급되므로 그 전에 이 저장소 Secrets 쓰기 권한만 준 fine-grained PAT를 넣어야 한다. 없으면 새 토큰 교체 단계가 실패한다.
- `workflow_dispatch` dry_run 실행(run 44900749282)이 성공했다: HY-ON 36건, 노션 32건, 구글 캘린더 변경 0건.

**동영상 강의 기한 조사 (8단계, 2026-11-21)**
- 영상은 모듈에 ExternalTool(`learning.hanyang.ac.kr/learningx`)로 들어 있고, Canvas 표준 API에는 날짜가 없다.
- LearningX API(`/learningx/api/v1/courses/{id}/allcomponents_db?...`)는 존재한다. 토큰 없이 부르면 `401 Unauthorized`(JSON), Canvas 개인 액세스 토큰으로 부르면 `400 Invalid request`(HTML)다. LearningX는 Canvas 토큰이 아니라 자체 토큰(외부 도구를 열 때 브라우저에 생기는 값)을 요구하는 것으로 보인다. → **개인 토큰으로는 안 되므로 구현하지 않았다.**
- **sessionless launch 확인 (같은 날):** Canvas 공식 API `GET /api/v1/courses/{id}/external_tools/sessionless_launch?id=<도구ID>`로 받은 주소를 열고 LTI 폼을 POST하면, 개인 토큰만으로 LearningX 토큰(`xn_api_token` 쿠키)이 생긴다. 과목 메뉴용 도구(예: Classmix id 19)로 열면 영상 항목을 건드리지 않는다. 그 토큰으로 `allcomponents_db`가 200으로 응답한다.
  - 그런데 `allcomponents_db`에는 Canvas 과제·퀴즈만 있고 **영상은 없다.** 영상은 '강의/출결'(도구 id 138, `/learningx/lti/lecture_attendance/...`) 쪽 데이터다. 그 목록을 주는 API 주소는 아직 모른다.
  - **영상 기한 API 찾음:** '주차학습' 도구(id 140)를 sessionless로 열어 받은 토큰으로 `GET /learningx/api/v1/courses/{id}/modules?include_detail=true`를 부르면, `module_items[]` 중 `content_type == "attendance_item"`의 `content_data`에 `title`, `week_position`, `use_attendance`, `unlock_at`, `due_at`(학습인정기간 마감), `late_at`, `lock_at`(열람 종료)이 있다. 화면 값과 일치한다(Ch1.서론-2: due 2026-09-13T14:59:59Z = 9/13 23:59). 한 과목에서 받은 토큰으로 모든 과목이 조회된다.
  - 2026-11-21 기준 앞으로 마감인 출석 영상: 데이터베이스 9개(11/22, 11/29, 12/6, 12/13 각 23:59). 나머지 과목은 0개.
  - **출석 여부도 찾음:** '출결현황' 화면(도구 id 138)이 쓰는 학생용 API 두 개.
    - `GET /learningx/api/v1/courses/{id}/attendance_items?include_detail=true` → `attendance_items[]`(item_id, title, week_position, use_attendance, item_content_type, unlock_at/due_at/late_at/lock_at). 파라미터 없이 부르면 500이 난다.
    - `GET /learningx/api/v1/courses/{id}/attendance_items/summary?only_use_attendance=true` → `attendance_summaries{item_id: {attendance_status}}`. 값은 `attendance`(출석), `none`(아직), `absent`(결석).
    - `item_content_type`이 `commons`면 영상이고, 스마트출결(대면 출석) 항목도 섞여 있으니 걸러야 한다. (`learning-activity-status/*`는 403 교수용이라 쓰지 않는다.)
    - 처음에 열었던 'Ch1.서론-1-screen'은 `attendance`(출석)으로 정상이다.
  - 주의: 첫 시험 때 영상 항목 하나('데이터베이스 · Ch1.서론-1-screen', 출결 항목 1254608)를 sessionless로 열었다(응답 500). 출결 기록에 영향이 있었는지는 확인하지 못했다. 이후에는 영상 항목을 직접 열지 않는다.
- 대안: 영상 기한을 구글 캘린더에 직접 적고 키워드로 읽기(시험과 같은 방식). 로그인 쿠키나 학교 계정 비밀번호를 쓰는 방식은 쓰지 않는다.

**남은 확인 사항**
- 이미 LMS ID로 연결된 항목의 마감이 HY-ON에서 사라지면 "마감 변경 → 마감 없음" 알림이 간다. 원래 있던 동작이라 그대로 뒀다.
- 위의 1단계 프롬프트에 적힌 "30개"는 그때 값이다.

---

## Claude Code에 줄 프롬프트

단계마다 새 대화에서 하나씩 붙여 넣는다. `[ ]` 안은 사용자가 먼저 해 둘 일이다.

### 1. 환경 세팅

```
CLAUDE.md와 docs/HANDOFF.md를 읽고 이 프로젝트의 현재 상태를 5줄로 요약해줘.
그다음 .venv 가상환경을 만들고 pip install -e ".[dev,mcp]"로 설치한 뒤 pytest를 돌려 30개가 통과하는지 확인해줘.
이번 단계에서는 코드를 고치지 마.
```

### 2. HY-ON 접근 확인

[ HY-ON 로그인 → 계정 → 설정 → 새 액세스 토큰 발급. 주소창 도메인과 토큰을 `.env`의 `HYON_BASE_URL`, `HYON_TOKEN`에 넣기 ]

```
.env에 HYON_BASE_URL과 HYON_TOKEN을 넣었어. .env 내용은 읽거나 출력하지 마.
CanvasClient로 (1) 수강 중인 강의 이름과 강의별 과제 수, (2) 과제 하나의 응답 키 목록과
unlock_at, due_at, submission_types, html_url 값을 확인하는 일회용 스크립트를 만들어 실행해줘.
결과를 보고 docs/HANDOFF.md의 '확인 안 된 가정' 1, 2번이 맞는지 판단해줘.
퀴즈 분류 같은 가정이 틀리면 고치기 전에 무엇을 어떻게 바꿀지 먼저 말해줘.
요청이 401/403/404로 실패하면 원인 후보를 알려주고 멈춰.
```

토큰 발급 메뉴가 없으면: 계획서 '리스크와 대응'의 1차 대안(캘린더 피드 .ics)으로 바꾸는 계획을 먼저 세워 달라고 한다.

### 3. 노션 연결, dry-run

[ 노션 내부 통합 생성 → `NOTION_TOKEN`. 과제DB에 통합 연결. 속성 4개 추가. `NOTION_DATABASE_ID=28e5992f8cd0811cb33bee82f6597713` ]

```
노션 설정을 .env에 넣었고 과제DB에 유형, LMS ID, 링크, 알림 기록 속성을 추가했어.
python -m hysync.sync --dry-run을 실행해서 결과를 보여줘. 아무것도 쓰면 안 돼.
노션에 이미 손으로 넣어 둔 이번 학기 항목과 과목명이 달라서 중복 생성될 것 같은 항목이 있으면
COURSE_ALIASES에 넣을 매핑을 제안해줘.
```

### 4. 카카오톡 연결, 첫 실제 실행

[ README '3. 카카오톡' 순서대로 앱 생성, 동의, 리프레시 토큰 발급 → `.env` ]

```
카카오 설정을 .env에 넣었어. 먼저 KakaoClient로 "hy-on-sync 연결 테스트" 메시지 하나만 보내서 내 카톡에 오는지 확인해줘.
온 걸 내가 확인하면, 다시 --dry-run으로 계획을 보여주고 내 승인을 받은 다음에 실제 실행(python -m hysync.sync)을 한 번 해줘.
실행 후 노션에 생긴 항목 수와 보낸 메시지 수를 알려줘.
```

### 5. 구글 캘린더 시험

[ 구글 캘린더 설정 → 캘린더 통합 → iCal 비공개 주소 → `GCAL_ICS_URL`. 테스트용으로 제목에 "시험"이 들어간 일정 하나 등록 ]

```
GCAL_ICS_URL을 넣고 테스트 시험 일정을 하나 등록했어.
fetch_exams로 시험 일정이 몇 개 읽히는지와 각 제목, 일시만 보여줘. 주소는 출력하지 마.
```

### 6. GitHub 저장소와 Actions

[ GitHub에서 비공개 저장소 생성. Secrets와 `GH_PAT`는 README 'GitHub Actions' 참고 ]

```
이 폴더를 내 비공개 GitHub 저장소 hy-on-sync로 올리고 싶어.
WorkSpace 루트도 git 저장소인데, 이 폴더를 루트 .gitignore에 넣을지 먼저 나한테 물어봐.
docs/workflows/sync.yml을 .github/workflows/sync.yml로 옮긴 다음 git init, 첫 커밋, push까지 해줘. .env가 커밋되지 않는지 꼭 확인해줘.
push 후에 내가 넣어야 할 Secrets 이름 목록을 알려주고, workflow_dispatch로 dry_run 실행하는 방법을 알려줘.
```

### 7. MCP 서버 등록

```
hysync.mcp_server를 Claude Code에 hy-on이라는 이름으로 등록해줘. HYSYNC_ENV_FILE로 이 폴더의 .env를 가리키게 해.
등록 후 list_upcoming(days=14)을 호출해서 실제 과제 목록이 나오는지 확인해줘.
Claude 데스크톱용 claude_desktop_config.json 설정도 이 PC 경로로 만들어줘.
```

### 8. 동영상 강의 기한 (선택)

[ HY-ON에서 동영상 강의 페이지를 열고 개발자 도구 Network 탭에서 기한이 담긴 요청의 URL과 응답 예시를 복사 (쿠키·토큰은 지우고) ]

```
LearningX 동영상 강의 기한을 가져오는 요청 정보를 붙여 넣을게. [붙여 넣기]
이 요청을 개인 액세스 토큰으로 호출할 수 있는지 먼저 확인하고, 가능하면 CanvasClient.fetch_videos()를 구현해줘.
lms_id는 video-<강의ID>-<항목ID> 형식으로 하고, 테스트를 먼저 추가해줘.
토큰으로 안 되면 구현하지 말고 이유와 대안만 정리해줘.
```

### 9. 마무리

```
README를 실제로 해 본 설정 과정에 맞게 고치고, 포트폴리오용으로 프로젝트 소개, 구조도 설명, 설계 결정 이유
(알림 기록을 노션에 두는 이유, 카톡을 노션 쓰기보다 먼저 보내는 이유 등)를 추가해줘.
공개 저장소로 바꿔도 되는지, 커밋 기록에 개인 정보나 비밀값이 남아 있지 않은지 점검해줘.
```
