# hy-on-sync

HY-ON(한양대 Canvas LMS)의 과제·퀴즈를 노션 과제DB에 자동으로 등록하고, 마감이 다가오면 카카오톡 "나에게 보내기"로 알려 주는 개인 자동화 도구입니다. 노션 과제DB는 구글 캘린더에도 그대로 비춰서 휴대폰 캘린더에서 볼 수 있고, 시험과 동영상 강의 출석 기한도 카톡으로 챙겨 줍니다. GitHub Actions로 하루 3번(KST 08·14·21시) 돕니다.

## 무엇을 하나

| 항목 | 어디서 읽나 | 노션 과제DB | 구글 캘린더 'HY-ON 과제' | 카카오톡 |
| --- | --- | --- | --- | --- |
| 과제·퀴즈 | HY-ON (Canvas API) | 등록·갱신 | 노션 DB를 그대로 비춤 (완료는 `✓`) | 신규, D-3, D-1, 마감 변경 |
| 시험 | 구글 캘린더 (직접 등록한 일정, 비공개 iCal) | — | — | D-3, D-1 |
| 동영상 강의 | HY-ON LearningX (출석 영상) | — | — | 신규, D-3, D-1 (출석 안 한 것만) |

## 알림·동기화 규칙

규칙은 모두 `src/hysync/planner.py`에 있고 `tests/test_planner.py`로 검증합니다.

- **시작일:** 공개일(`unlock_at`), 없으면 마감 7일 전(`START_OFFSET_DAYS`). 노션의 '마감 날짜'에 시작일~마감 범위로 넣습니다.
- **알림 시점:** D-3는 마감 72시간 이하, D-1은 24시간 이하로 처음 들어갈 때 한 번씩. 마감이 바뀌면(과제·퀴즈만) '마감 변경'을 보내고 D-3·D-1 기록을 다시 시작합니다.
- **과제·퀴즈**
  - 마감이 없거나 이미 지난 항목은 노션에 새로 만들지 않습니다. LMS ID로 이미 연결된 항목은 계속 갱신합니다.
  - 노션에서 진행 상태가 '완료'면 D-3·D-1을 보내지 않습니다.
  - 노션에 손으로 넣어 둔 항목은 과목+과제명이 같으면 새로 만들지 않고 연결합니다(마감 없는 항목은 연결하지 않음).
  - 강의명 앞의 학기 코드(`202620HY24987_`)는 자동으로 뗍니다.
  - 스크립트는 노션의 '진행 상태'와 '메모'를 건드리지 않습니다.
- **시험:** 구글 캘린더 일정 중 제목에 `시험`이나 `고사`가 들어간 것(`EXAM_KEYWORD`, 쉼표로 구분). 직접 등록한 일정이라 신규 알림은 없습니다.
- **동영상:** 출석 인정 영상 중 이미 출석했거나, 처음 봤을 때 이미 마감이 지난 영상은 알리지 않습니다.
- **구글 캘린더 미러:** 노션 과제DB 전체(지난 과제 포함)를 비추고, 노션에서 지운 항목은 지웁니다. 스크립트가 만든 일정만 고치고 지우므로, 이 캘린더에 직접 넣은 일정이나 다른 캘린더는 건드리지 않습니다.

## 동작 흐름

```
HY-ON (Canvas API) ─────────────┐
HY-ON LearningX (출석 영상) ────┤
구글 캘린더 iCal (시험) ────────┼─▶ sync.py ─▶ planner.py (순수 함수: 무엇을 만들고 고치고 알릴지)
노션 과제DB (현재 상태) ────────┘                     │
                                                      ├─▶ ① 카카오톡 나에게 보내기
                                                      ├─▶ ② 노션 과제DB 쓰기
                                                      ├─▶ ③ 구글 캘린더 'HY-ON 과제' 비추기
                                                      └─▶ ④ state/alert_log.json (시험·동영상 알림 기록)
```

카톡을 노션 쓰기보다 먼저 보내고, 실패했을 때 무엇을 남길지 정해 두었습니다. 어느 쪽이 실패해도 실행은 실패(종료 코드 1)로 끝나 GitHub가 메일로 알려 줍니다.

| 실패한 곳 | 결과 |
| --- | --- |
| 카카오톡 전송 | D-3·D-1 기록을 남기지 않아 다음 실행 때 다시 보냅니다('새 과제'는 다시 보내지 않음) |
| 구글 캘린더 미러 | 카톡·노션·상태 저장은 그대로 합니다. 다음 실행에서 처음부터 다시 비교해 저절로 복구됩니다 |
| LearningX(동영상) | 영상 알림만 건너뛰고 나머지는 그대로 돕니다. 기존 영상 알림 기록은 유지합니다 |

## 구조

```
src/hysync/
  sync.py        진입점 (python -m hysync.sync [--dry-run])
  planner.py     알림·동기화 규칙 (순수 함수, 규칙은 여기에만)
  dates.py       KST 변환, 시작일 역산, D-3/D-1 판단
  canvas.py      HY-ON(Canvas) REST API
  learningx.py   LearningX 출석 영상의 기한·출석 여부 (Canvas sessionless launch로 토큰을 받음)
  notion.py      노션 과제DB 읽기·쓰기 (API 버전 2022-06-28 고정)
  gcal.py        구글 캘린더 비공개 iCal에서 시험 읽기
  gcal_writer.py 구글 캘린더 'HY-ON 과제'에 노션 과제DB 비추기 (서비스 계정)
  kakao.py       카카오톡 나에게 보내기, 리프레시 토큰 갱신
  messages.py    알림을 200자 이하 메시지로 묶기
  state.py       시험·동영상 알림 기록 (state/alert_log.json, 과목명·제목은 저장하지 않음)
  config.py      .env / 환경 변수
  mcp_server.py  (선택) HY-ON 조회용 MCP 서버
.github/workflows/sync.yml   GitHub Actions (하루 3번 + 수동 실행)
```

## 처음 설정하기

아래 순서대로 하면 됩니다. 값은 모두 `.env`에 넣고(`.env.example` 참고), `.env`와 키 파일은 커밋되지 않습니다.

### 1. 로컬 설치 (Windows PowerShell)

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev,mcp]"
Copy-Item .env.example .env
.venv\Scripts\python.exe -m pytest
```

Python 3.11 이상이면 됩니다(Actions는 3.12).

### 2. HY-ON 토큰

1. HY-ON 로그인 → 계정 → 설정 → **새 액세스 토큰**을 발급합니다.
2. `HYON_BASE_URL=https://learning.hanyang.ac.kr`, `HYON_TOKEN=발급한 토큰`. `lms.hanyang.ac.kr`은 Canvas API가 아니라 다른 곳으로 리다이렉트되니 쓰지 않습니다.

### 3. 노션 과제DB

1. [노션 통합](https://www.notion.so/profile/integrations)에서 **내부 통합**을 만들고(기능: 콘텐츠 읽기·업데이트·입력), 시크릿을 `NOTION_TOKEN`에 넣습니다.
2. 과제DB에 통합을 연결합니다. 과제DB `···` → 연결, 또는 통합 설정의 '액세스' 탭에서 과제DB를 고릅니다.
3. 과제DB URL의 32자리 ID를 `NOTION_DATABASE_ID`에 넣습니다.
4. 과제DB에 아래 속성이 있어야 합니다. 이름은 띄어쓰기까지 같아야 합니다.

| 이름 | 종류 | 비고 |
| --- | --- | --- |
| 과제명 | 제목 | |
| 과목 | 선택 | 없는 선택지는 자동으로 생깁니다 |
| 마감 날짜 | 날짜 | 시작일~마감 범위 |
| 진행 상태 | 상태 | 선택지 `시작 전` / `진행 중` / `완료` |
| 메모 | 텍스트 | 스크립트가 건드리지 않음 |
| 유형 | 선택 | 과제 / 퀴즈 |
| LMS ID | 텍스트 | 연결 키 |
| 링크 | URL | HY-ON 과제 주소 |
| 알림 기록 | 다중 선택 | 보낸 알림(신규, D-3, D-1) |

강의명(학기 코드를 뗀 이름)이 노션 '과목' 이름과 다르면 `COURSE_ALIASES`에 JSON으로 매핑합니다. 예: `{"알고리즘": "알고리즘 설계"}`

### 4. 카카오톡 나에게 보내기

1. [카카오 디벨로퍼스](https://developers.kakao.com) → 내 애플리케이션 → 애플리케이션 추가.
2. **[앱] > [플랫폼 키] > [REST API 키]**
   - REST API 키 → `KAKAO_REST_KEY`
   - '카카오 로그인 리다이렉트 URI'에 `http://localhost:3000/oauth`를 등록합니다.
   - '클라이언트 시크릿'의 코드 → `KAKAO_CLIENT_SECRET` (기본으로 켜져 있습니다. 켜져 있는데 비워 두면 토큰 갱신이 실패합니다)
3. **[카카오 로그인] > [사용 설정]**을 ON으로, **[카카오 로그인] > [동의항목]**에서 '카카오톡 메시지 전송'을 선택 동의로 설정합니다.
4. **[앱] > [제품 링크 관리] > [웹 도메인]**에 `https://learning.hanyang.ac.kr`을 등록합니다(메시지의 'HY-ON 열기' 버튼용).
5. 브라우저로 아래 주소에 접속해 동의합니다. '사이트에 연결할 수 없음'이 떠도 정상이고, 주소창의 `code=` 뒤 값을 복사합니다(한 번만 쓸 수 있고 몇 분 안에 만료).
   ```
   https://kauth.kakao.com/oauth/authorize?client_id=<REST_API_키>&redirect_uri=http://localhost:3000/oauth&response_type=code&scope=talk_message
   ```
6. 코드를 리프레시 토큰으로 바꾸고, 결과의 `refresh_token`을 `KAKAO_REFRESH_TOKEN`에 넣습니다.
   ```powershell
   Invoke-RestMethod -Method Post -Uri https://kauth.kakao.com/oauth/token -Body @{grant_type='authorization_code'; client_id='<REST_API_키>'; client_secret='<시크릿>'; redirect_uri='http://localhost:3000/oauth'; code='<코드>'}
   ```

리프레시 토큰은 2달 동안 유효하고 만료 1달 전부터 새로 발급됩니다. Actions가 새 토큰을 받으면 `GH_PAT`로 Secret을 자동 교체합니다(7단계).

### 5. 구글 캘린더: 시험 읽기

1. 시험 일정을 넣는 구글 캘린더(개인 Gmail 권장) → 설정 → 캘린더 통합 → **iCal 형식의 비공개 주소**를 `GCAL_ICS_URL`에 넣습니다. 이 주소는 비밀번호처럼 다뤄야 합니다.
2. 시험 일정 제목에 `시험`이나 `고사`를 넣습니다(예: "데이터베이스 기말고사"). 새 일정이 iCal 피드에 반영되기까지 조금 걸릴 수 있습니다.

### 6. 구글 캘린더: 과제 미러

노션 DB 항목은 노션 캘린더 앱에서만 보이고 구글 캘린더에는 써지지 않습니다. 그래서 스크립트가 노션 과제DB를 전용 캘린더에 직접 씁니다.

1. [구글 클라우드 콘솔](https://console.cloud.google.com)에서 프로젝트를 만들고(예: `hy-on-sync`) **Google Calendar API**를 사용 설정합니다.
2. Credentials → Create credentials → **Service account**(역할은 지정하지 않음) → Keys → Add key → JSON. 받은 파일을 이 폴더에 `gcal-service-account.json`으로 둡니다.
3. 구글 캘린더(개인 Gmail)에서 새 캘린더 **'HY-ON 과제'**를 만들고, 설정 및 공유 → 특정 사용자와 공유 → 서비스 계정 이메일을 **'일정 변경'** 권한으로 추가합니다. 학교 계정은 외부 공유가 막혀 있을 수 있습니다.
4. 같은 화면의 캘린더 통합 → **캘린더 ID**(`...@group.calendar.google.com`)를 `GCAL_TARGET_CALENDAR_ID`에 넣습니다.
5. 색은 구글 캘린더에서 이 캘린더 색을 바꾸면 됩니다. 노션 캘린더 앱에서는 같은 과제가 두 번 보이므로 이 캘린더를 숨깁니다.

`GCAL_TARGET_CALENDAR_ID`나 키 파일이 없으면 미러는 건너뜁니다.

### 7. 확인하고 첫 실행

```powershell
.venv\Scripts\python.exe -m hysync.sync --dry-run   # 아무것도 쓰지 않고 계획만 출력
.venv\Scripts\python.exe -m hysync.sync             # 실제 실행
```

dry-run은 노션에 만들 항목, 고칠 항목, 보낼 카톡, 구글 캘린더 변경을 보여 줍니다. 계획이 맞는지 확인한 뒤 실제로 실행하고, 바로 한 번 더 dry-run을 돌려 '바뀐 것 없음'이 나오면 중복이 없는 것입니다.

### 8. GitHub Actions

1. **비공개** 저장소에 올립니다. `.env`, `gcal-service-account.json`, `.kakao_refresh_token`은 `.gitignore`에 있습니다.
2. Secrets를 넣습니다. `gh`를 쓰면 값을 화면에 띄우지 않고 파일에서 바로 넣을 수 있습니다.
   ```powershell
   gh secret set -f .env --repo <owner>/hy-on-sync
   Get-Content gcal-service-account.json -Raw | gh secret set GCAL_SERVICE_ACCOUNT_JSON --repo <owner>/hy-on-sync
   ```
   필요한 Secrets: `HYON_BASE_URL`, `HYON_TOKEN`, `NOTION_TOKEN`, `NOTION_DATABASE_ID`, `KAKAO_REST_KEY`, `KAKAO_CLIENT_SECRET`, `KAKAO_REFRESH_TOKEN`, `GCAL_ICS_URL`, `GCAL_TARGET_CALENDAR_ID`, `GCAL_SERVICE_ACCOUNT_JSON`. `COURSE_ALIASES`를 쓰면 Variables에 넣습니다. `EXAM_KEYWORD`와 `START_OFFSET_DAYS`는 워크플로가 넘기지 않으므로 Actions에서는 기본값(`시험,고사`, 7일)으로 돕니다.
3. `GH_PAT`: 이 저장소의 **Secrets 읽기·쓰기** 권한만 준 fine-grained PAT. 카카오 리프레시 토큰 자동 교체용이며, 토큰을 발급하고 한 달 안에 넣어야 합니다.
   ```powershell
   gh secret set GH_PAT --repo <owner>/hy-on-sync
   ```
4. Actions 탭 → sync → Run workflow에서 `dry_run`을 체크해 먼저 확인합니다(또는 `gh workflow run sync -f dry_run=true`).

## 운영 메모

- **실패 메일이 오면** Actions 로그의 `ERROR` 줄을 봅니다. 어느 부분이 실패해도 나머지는 위 표대로 동작합니다.
- **Actions 봇이 `state/alert_log.json`을 main에 커밋**합니다. 로컬에서 작업하기 전에 `git pull`을 하고, 변경은 브랜치 → PR로 올립니다.
- **새 학기**에는 강의명 학기 코드가 자동으로 떨어지고, 노션에 새 '과목' 선택지가 생깁니다. 지난 학기 노션 항목은 그대로 남습니다.

## (선택) MCP 서버

Claude에서 "이번 주 과제 뭐 있어?"처럼 HY-ON을 바로 조회하는 읽기 전용 MCP 서버입니다. 도구는 `list_upcoming(days=7)`(앞으로 N일 안에 마감인 과제·퀴즈)과 `get_item(lms_id)`(설명·제출 형식·배점) 두 개입니다. MCP Python SDK 2.x(`MCPServer`) 기준이며, 지금은 등록해서 쓰고 있지 않습니다.

```powershell
claude mcp add hy-on -e HYSYNC_ENV_FILE=C:\경로\hy-on-sync\.env -- C:\경로\hy-on-sync\.venv\Scripts\python.exe -m hysync.mcp_server
```

## 한계와 주의

- **LearningX는 비공식 API입니다.** 학생용 '출결현황' 화면이 쓰는 주소(`attendance_items`, `attendance_items/summary`)를, Canvas 공식 기능인 sessionless launch로 받은 토큰으로 읽습니다. 영상 항목은 열지 않습니다. 학교가 바꾸면 영상 알림만 멈추고 실패 메일이 옵니다.
- **새 퀴즈(New Quizzes)**는 과제 목록에 `external_tool`로 나와 '과제'로 분류될 수 있습니다. 2026년 2학기에는 새 퀴즈가 없어 확인하지 못했습니다.
- **과목 캘린더 피드(.ics)는 쓰지 않습니다.** 과목 전체 주소라 다른 분반이나 특정 학생에게만 배정된 과제가 섞여 있습니다. 동기화는 내 계정이 볼 수 있는 과제만 읽습니다.
- 비밀값(`.env`, 서비스 계정 키, iCal 비공개 주소, 토큰)은 커밋하거나 채팅·이슈에 붙여 넣지 않습니다.

## 개발

- 테스트: `.venv\Scripts\python.exe -m pytest` (68개, 모두 가짜 응답 기반)
- 규칙을 바꿀 때는 `tests/test_planner.py`에 테스트부터 추가하고 `planner.py`만 고칩니다.
- 외부 서비스에 처음 연결할 때는 `--dry-run`으로 먼저 확인합니다.
- 계획서: `docs/PLAN.md`, 진행 상황·다음 할 일: `docs/HANDOFF.md`, 구글 캘린더 미러 설계: `docs/superpowers/specs/2026-11-21-gcal-mirror-design.md`
