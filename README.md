# hy-on-sync

HY-ON(한양대 LMS)의 과제와 퀴즈를 노션 과제 플래너에 자동으로 등록하고, 마감이 다가오면 카카오톡 "나에게 보내기"로 알려주는 개인 자동화 도구입니다. 2단계로 HY-ON을 조회하는 MCP 서버도 들어 있어서, Claude에게 "이번 주 과제 뭐 있어?"라고 물어볼 수 있습니다.

| 항목 | 노션 과제DB | 카카오톡 알림 | 출처 |
| --- | --- | --- | --- |
| 과제, 퀴즈 | 등록·갱신 (노션 캘린더에서 보임, 구글 캘린더 'HY-ON 과제'에 그대로 비춤) | 신규, D-3, D-1, 마감 변경 | HY-ON (Canvas API) |
| 시험 | — | D-3, D-1 | 구글 캘린더 (직접 등록, 제목에 "시험"이나 "고사") |
| 동영상 강의 | — | 신규, D-3, D-1 (출석 안 한 것만) | HY-ON LearningX (비공식 API) |

## 구조

```
src/hysync/
  planner.py     무엇을 만들고 고치고 알릴지 정하는 순수 함수 (규칙은 여기에만 있음)
  dates.py       KST 변환, 시작일 역산(공개일 없으면 마감 7일 전), D-3/D-1 판단
  canvas.py      HY-ON(Canvas) REST API
  notion.py      노션 과제DB 읽기·쓰기 (API 버전 2022-06-28 고정)
  gcal.py        구글 캘린더 비공개 iCal에서 시험 일정 읽기
  gcal_writer.py 구글 캘린더 'HY-ON 과제' 캘린더에 과제DB 비추기 (서비스 계정)
  kakao.py       카카오톡 나에게 보내기, 리프레시 토큰 갱신
  messages.py    알림을 200자 이하 메시지로 묶기
  learningx.py   LearningX 출석 영상의 기한·출석 여부 (Canvas sessionless launch로 토큰을 받음)
  state.py       시험·동영상 알림 기록 (state/alert_log.json)
  sync.py        1단계 진입점
  mcp_server.py  2단계 MCP 서버 (읽기 전용: list_upcoming, get_item)
.github/workflows/sync.yml   하루 3번(KST 08·14·21시) 실행
```

실행 순서는 **읽기 → 계획 → 카카오톡 전송 → 노션 쓰기 → 구글 캘린더 비추기 → 상태 저장**입니다. 구글 캘린더 쪽이 실패해도 상태 저장은 그대로 하고, 실행만 실패로 끝납니다. 카카오톡 전송이 실패하면 D-3·D-1 기록을 남기지 않아 다음 실행 때 다시 보냅니다. (이때 "새 과제" 알림은 다시 보내지 않습니다. 실행은 실패로 끝나 GitHub가 메일로 알려줍니다.)

## 준비

### 1. HY-ON 토큰
HY-ON에 로그인 → 계정 → 설정 → **새 액세스 토큰**. 주소창의 도메인을 `HYON_BASE_URL`에 넣습니다 (`https://learning.hanyang.ac.kr`. `lms.hanyang.ac.kr`은 Canvas API가 아닙니다). 이 메뉴가 없으면 계획서의 대안(캘린더 피드)으로 바꿔야 합니다.

### 2. 노션
1. [내 통합](https://www.notion.so/profile/integrations)에서 내부 통합을 만들고 토큰을 `NOTION_TOKEN`에 넣습니다.
2. 과제DB 페이지 → `···` → 연결 → 방금 만든 통합 추가.
3. 과제DB에 속성 4개를 추가합니다.

| 이름 | 종류 |
| --- | --- |
| 유형 | 선택 |
| LMS ID | 텍스트 |
| 링크 | URL |
| 알림 기록 | 다중 선택 |

4. 과제DB URL의 32자리 ID를 `NOTION_DATABASE_ID`에 넣습니다.

강의명 앞의 학기 코드(`202620HY24987_`)는 자동으로 뗍니다. 그래도 노션 과목 이름과 다르면 `COURSE_ALIASES`에 JSON으로 매핑합니다 (원래 강의명이나 코드를 뗀 이름 둘 다 키로 쓸 수 있습니다).
예: `{"알고리즘": "알고리즘 설계"}`

마감일이 없거나 이미 지난 과제·퀴즈는 노션에 새로 만들지 않습니다. 이미 노션에 있는 항목은 계속 갱신합니다.

### 3. 카카오톡
1. [카카오 디벨로퍼스](https://developers.kakao.com)에서 앱 생성 → REST API 키, 클라이언트 시크릿 확인.
2. 카카오 로그인 ON, 리다이렉트 URI에 `http://localhost:3000/oauth` 등록, 동의항목에서 **카카오톡 메시지 전송(talk_message)** 설정.
3. [앱] > [제품 링크 관리] > [웹 도메인]에 HY-ON 도메인 등록 (메시지 버튼 링크용).
4. 브라우저로 아래 주소에 접속해 동의하면 리다이렉트 주소의 `code=` 값을 얻습니다.
   ```
   https://kauth.kakao.com/oauth/authorize?client_id=<REST_API_키>&redirect_uri=http://localhost:3000/oauth&response_type=code&scope=talk_message
   ```
5. 그 코드로 토큰을 받고, 응답의 `refresh_token`을 `KAKAO_REFRESH_TOKEN`에 넣습니다.
   ```
   curl -X POST https://kauth.kakao.com/oauth/token \
     -d grant_type=authorization_code -d client_id=<REST_API_키> -d client_secret=<시크릿> \
     -d redirect_uri=http://localhost:3000/oauth -d code=<코드>
   ```

리프레시 토큰은 2달 동안 유효하고 만료 1달 전부터 새로 발급됩니다. 워크플로가 새 토큰을 받으면 `GH_PAT`로 Secret을 자동 교체합니다.

### 4. 구글 캘린더 (시험)
구글 캘린더 → 설정 → 내 캘린더 → 캘린더 통합 → **iCal 형식의 비공개 주소**를 `GCAL_ICS_URL`에 넣습니다. 제목에 `시험`이나 `고사`가 들어간 일정만 읽습니다 (예: "데이터베이스 기말시험", "운영체제 중간고사"). 키워드는 `EXAM_KEYWORD`에 쉼표로 구분해 바꿀 수 있습니다. 이 주소는 비밀번호처럼 다뤄야 합니다.

### 5. 구글 캘린더 (과제 미러)
노션 DB 항목은 노션 캘린더 앱에서만 보입니다. 구글 캘린더(휴대폰 캘린더 포함)에서도 보이도록, 동기화할 때마다 노션 과제DB 전체를 전용 캘린더 'HY-ON 과제'에 그대로 비춥니다. 완료한 과제는 제목 앞에 `✓`가 붙고, 노션에서 지운 항목은 이 캘린더에서도 지워집니다.

1. [구글 클라우드 콘솔](https://console.cloud.google.com)에서 프로젝트를 만들고 **Google Calendar API**를 사용 설정합니다.
2. IAM 및 관리자 → 서비스 계정 → 서비스 계정을 만들고, 키 → 새 키(JSON)를 받아 이 폴더에 `gcal-service-account.json`으로 저장합니다. (커밋되지 않습니다)
3. 구글 캘린더(개인 Gmail 계정)에서 새 캘린더 **'HY-ON 과제'**를 만들고, 설정 → 특정 사용자와 공유 → 서비스 계정 이메일(`...@...iam.gserviceaccount.com`)을 **'일정 변경'** 권한으로 추가합니다. 학교 계정은 외부 공유가 막혀 있을 수 있습니다.
4. 같은 설정 화면의 '캘린더 통합'에 있는 **캘린더 ID**(`...@group.calendar.google.com`)를 `GCAL_TARGET_CALENDAR_ID`에 넣습니다.
5. 색은 구글 캘린더에서 이 캘린더의 색을 바꾸면 됩니다. 노션 캘린더 앱에서는 같은 과제가 두 번 보이므로 이 캘린더를 숨기세요.

스크립트는 자기가 만든 일정(표시가 붙은 일정)만 고치고 지웁니다. 이 캘린더에 직접 넣은 일정은 그대로 두고, 캘린더 ID를 잘못 넣어도 다른 캘린더의 일정은 지우지 않습니다. 설정이 비어 있으면 이 단계는 건너뜁니다.

## 로컬 실행

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,mcp]"
cp .env.example .env    # 값 채우기
python -m hysync.sync --dry-run    # 처음엔 꼭 dry-run으로 계획만 확인
python -m hysync.sync
pytest
```

## GitHub Actions

1. **비공개** 저장소에 올립니다.
2. Settings → Secrets and variables → Actions에 `.env`와 같은 이름으로 Secrets를 넣습니다: `HYON_BASE_URL`, `HYON_TOKEN`, `NOTION_TOKEN`, `NOTION_DATABASE_ID`, `KAKAO_REST_KEY`, `KAKAO_CLIENT_SECRET`, `KAKAO_REFRESH_TOKEN`, `GCAL_ICS_URL`, `GCAL_TARGET_CALENDAR_ID`, 그리고 키 파일 내용 전체를 담은 `GCAL_SERVICE_ACCOUNT_JSON`.
3. `GH_PAT`: 이 저장소의 **Secrets 쓰기** 권한만 준 fine-grained PAT (카카오 토큰 자동 교체용).
4. `COURSE_ALIASES`는 Variables에 넣습니다.
5. Actions 탭 → sync → Run workflow → `dry_run` 체크로 먼저 확인합니다.

## MCP 서버 (2단계)

Claude 데스크톱 `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "hy-on": {
      "command": "C:\\경로\\hy-on-sync\\.venv\\Scripts\\python.exe",
      "args": ["-m", "hysync.mcp_server"],
      "env": { "HYSYNC_ENV_FILE": "C:\\경로\\hy-on-sync\\.env" }
    }
  }
}
```

Claude Code:

```bash
claude mcp add hy-on -e HYSYNC_ENV_FILE=/경로/hy-on-sync/.env -- /경로/.venv/bin/python -m hysync.mcp_server
```

도구는 두 개입니다. `list_upcoming(days=7)`는 앞으로 N일 안에 마감인 과제·퀴즈를, `get_item(lms_id)`는 설명·제출 형식·배점을 돌려줍니다. 둘 다 읽기 전용이고, 노션에 쓰는 일은 기존 노션 MCP가 맡습니다. MCP Python SDK 2.x(`MCPServer`) 기준입니다.

## 아직 확인하지 못한 것

- 동영상 강의: LearningX의 학생용 화면이 쓰는 비공개 API를 읽습니다(영상 목록·기한 `attendance_items`, 출석 여부 `attendance_items/summary`). 학교가 바꾸면 깨질 수 있고, 그때는 영상 알림만 멈추고 실행이 실패로 끝나 메일이 옵니다
- 새 퀴즈(New Quizzes)는 과제 목록에 `external_tool`로 나와 "과제"로 분류될 수 있습니다 (2026년 2학기에는 새 퀴즈가 없어 확인하지 못했습니다)
