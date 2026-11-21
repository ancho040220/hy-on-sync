"""알림 목록을 카카오톡 메시지 문자열로 묶는다."""

from __future__ import annotations

from .dates import fmt_due
from .models import SENT_D1, SENT_D3
from .planner import Alert

# 카카오톡 텍스트 템플릿의 text 길이 제한
MAX_LEN = 200

_ORDER = {"마감 변경": 0, SENT_D1: 1, SENT_D3: 2}


def format_line(alert: Alert) -> str:
    item = alert.item
    head = f"{item.course} · {item.title}" if item.course else item.title
    if alert.tag == "마감 변경":
        when = f"{fmt_due(alert.old_due, item.all_day)} → {fmt_due(item.due_at, item.all_day)}"
    else:
        when = fmt_due(item.due_at, item.all_day)
    return f"[{alert.tag}] {head} · {when}"


def format_messages(alerts: list[Alert], max_len: int = MAX_LEN) -> list[str]:
    """급한 순서(변경 → D-1 → D-3 → 신규)로 정렬해 max_len 이하 메시지 여러 개로 나눈다."""
    def key(a: Alert) -> tuple:
        due = a.item.due_at
        return (_ORDER.get(a.tag, 3), due is None, due.timestamp() if due else 0.0)

    lines = [format_line(a) for a in sorted(alerts, key=key)]
    messages: list[str] = []
    current = ""
    for line in lines:
        if len(line) > max_len:
            line = line[: max_len - 1] + "…"
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > max_len:
            messages.append(current)
            current = line
        else:
            current = candidate
    if current:
        messages.append(current)
    return messages
