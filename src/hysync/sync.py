"""1단계 진입점: LMS·구글 캘린더 → 노션 과제DB + 카카오톡 알림.

사용법:
    python -m hysync.sync --dry-run   # 아무것도 쓰지 않고 계획만 출력 (처음엔 꼭 이걸로)
    python -m hysync.sync             # 실제 실행
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx

from .canvas import CanvasClient
from .config import Config, load_config
from .dates import KST, fmt_due
from .gcal import fetch_exams
from .gcal_writer import GcalError, GoogleCalendarClient, load_service_account
from .kakao import KakaoClient, KakaoError
from .messages import format_messages
from .models import Item
from .notion import NotionStore
from .planner import GcalPlan, plan_gcal, plan_notion, plan_state
from .state import load_state, save_state

log = logging.getLogger("hysync")

# 새 리프레시 토큰을 GitHub Actions에 넘기는 임시 파일 (커밋하지 않음, .gitignore)
REFRESH_TOKEN_FILE = Path(".kakao_refresh_token")


@dataclass
class Result:
    created: int = 0
    updated: int = 0
    messages: list[str] = field(default_factory=list)
    kakao_ok: bool = True
    gcal_ok: bool = True
    gcal_changes: int = 0


def run(
    cfg: Config,
    *,
    now: datetime | None = None,
    dry_run: bool = False,
    canvas: CanvasClient | None = None,
    notion: NotionStore | None = None,
    kakao: KakaoClient | None = None,
    exams: list[Item] | None = None,
    gcal: GoogleCalendarClient | None = None,
) -> Result:
    now = now or datetime.now(KST)
    canvas = canvas or CanvasClient(cfg.hyon_base_url, cfg.hyon_token)
    notion = notion or NotionStore(cfg.notion_token, cfg.notion_database_id)
    if kakao is None and cfg.kakao_enabled:
        kakao = KakaoClient(cfg.kakao_rest_key, cfg.kakao_client_secret, cfg.kakao_refresh_token)
    mirror_on = gcal is not None or cfg.gcal_mirror_enabled

    # 1) 읽기
    items = canvas.fetch_items(cfg.course_aliases)
    videos = canvas.fetch_videos()
    if exams is None:
        exams = fetch_exams(cfg.gcal_ics_url, cfg.exam_keyword, now) if cfg.gcal_ics_url else []
    records = notion.query_all()
    state = load_state(cfg.state_path)
    log.info("LMS 과제·퀴즈 %d건, 동영상 %d건, 시험 %d건, 노션 레코드 %d건", len(items), len(videos), len(exams), len(records))

    # 2) 계획 (순수 함수)
    plan = plan_notion(items, records, now, cfg.start_offset_days)
    state_alerts, new_state = plan_state(videos + exams, state, now)
    messages = format_messages(plan.alerts + state_alerts)
    result = Result(messages=messages)

    if dry_run:
        _print_plan(plan, messages)
        if mirror_on:
            try:
                gcal = gcal or _gcal_client(cfg)
                _print_gcal_plan(plan_gcal(records, gcal.list_events()))
            except Exception as exc:  # 구글 쪽 문제는 계획 출력을 막지 않는다
                print(f"== 구글 캘린더 == 읽기 실패: {type(exc).__name__}: {exc}")
        return result

    # 3) 알림 먼저: 전송이 실패하면 알림 기록을 남기지 않아 다음 실행 때 다시 보낸다.
    if messages and kakao is not None:
        try:
            for text in messages:
                kakao.send_text(text, cfg.hyon_base_url)
        except KakaoError as exc:
            log.error("%s", exc)
            result.kakao_ok = False
    elif messages:
        log.warning("카카오 설정이 없어 알림 %d건을 보내지 않았습니다.", len(messages))
        result.kakao_ok = False

    # 4) 노션 쓰기
    for c in plan.creates:
        sent = c.sent if result.kakao_ok else set()
        notion.create(c.item, c.start, sent)
        result.created += 1
    for u in plan.updates:
        sent = u.sent if result.kakao_ok else u.record.sent
        notion.update(u.record.page_id, u.item, u.start, sent)
        result.updated += 1

    # 5) 구글 캘린더 미러: 실패해도 아래 상태 저장과 토큰 기록은 그대로 한다.
    #    (키 파일이 깨졌거나 노션 다시 읽기가 실패해도 마찬가지다)
    if mirror_on:
        try:
            gcal = gcal or _gcal_client(cfg)
            mirror = notion.query_all() if (result.created or result.updated) else records
            gplan = plan_gcal(mirror, gcal.list_events())
            steps = [(gcal.create, e) for e in gplan.creates] + [(gcal.update, e) for e in gplan.updates]
            steps += [(gcal.delete, i) for i in gplan.deletes]
            for action, arg in steps:  # 일정 하나가 실패해도 나머지는 계속한다
                try:
                    action(arg)
                    result.gcal_changes += 1
                except (GcalError, httpx.HTTPError) as exc:
                    log.error("구글 캘린더 일정 반영 실패: %s", exc)
                    result.gcal_ok = False
        except Exception as exc:
            log.error("구글 캘린더 미러 실패: %s: %s", type(exc).__name__, exc)
            result.gcal_ok = False

    # 6) 상태 파일, 새 리프레시 토큰
    if result.kakao_ok:
        save_state(cfg.state_path, new_state)
    if kakao is not None and kakao.new_refresh_token:
        REFRESH_TOKEN_FILE.write_text(kakao.new_refresh_token, encoding="utf-8")
        log.info("카카오 리프레시 토큰이 갱신되었습니다. 워크플로가 Secret을 교체합니다.")

    log.info(
        "노션 생성 %d건, 갱신 %d건, 메시지 %d개, 구글 캘린더 변경 %d건",
        result.created, result.updated, len(messages), result.gcal_changes,
    )
    return result


def _print_plan(plan, messages: list[str]) -> None:
    print("== 노션에 새로 만들 항목 ==")
    for c in plan.creates:
        print(f"  + [{c.item.kind}] {c.item.course} · {c.item.title} ({fmt_due(c.start)} ~ {fmt_due(c.item.due_at)})")
    print("== 노션에서 고칠 항목 ==")
    for u in plan.updates:
        print(f"  ~ [{u.item.kind}] {u.item.course} · {u.item.title} (알림 기록: {', '.join(sorted(u.sent)) or '없음'})")
    print("== 보낼 카카오톡 메시지 ==")
    for i, text in enumerate(messages, 1):
        print(f"--- {i} ---\n{text}")
    if not (plan.creates or plan.updates or messages):
        print("  (바뀐 것 없음)")


def _gcal_client(cfg: Config) -> GoogleCalendarClient:
    return GoogleCalendarClient(cfg.gcal_target_calendar_id, load_service_account(cfg.gcal_service_account_file))


def _print_gcal_plan(gplan: GcalPlan) -> None:
    print(f"== 구글 캘린더에 만들 일정 ({len(gplan.creates)}건) ==")
    for ev in gplan.creates:
        print(f"  + {ev.summary} ({fmt_due(ev.start)} ~ {fmt_due(ev.end)})")
    print(f"== 구글 캘린더에서 고칠 일정 ({len(gplan.updates)}건) ==")
    for ev in gplan.updates:
        print(f"  ~ {ev.summary} ({fmt_due(ev.start)} ~ {fmt_due(ev.end)})")
    print(f"== 구글 캘린더에서 지울 일정 ({len(gplan.deletes)}건) ==")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HY-ON → 노션 과제 플래너 동기화")
    parser.add_argument("--dry-run", action="store_true", help="쓰지 않고 계획만 출력")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # httpx는 요청 URL을 INFO로 찍는다. iCal 비공개 주소가 로그에 남지 않게 끈다.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    result = run(load_config(), dry_run=args.dry_run)
    # 카카오 전송·구글 캘린더 미러 실패는 실패로 끝내 GitHub Actions가 메일로 알려주게 한다
    return 0 if (result.kakao_ok and result.gcal_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
