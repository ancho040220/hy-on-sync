"""2단계: HY-ON 조회용 MCP 서버 (읽기 전용, 로컬 stdio).

Claude 데스크톱이나 Claude Code에 등록하면 "이번 주 과제 뭐 있어?" 같은 질문에
Claude가 이 서버의 도구로 LMS를 직접 조회한다. 노션에 쓰는 일은 기존 노션 MCP가 맡는다.

실행: python -m hysync.mcp_server
MCP Python SDK 2.x 기준 (1.x의 FastMCP가 MCPServer로 바뀌었다).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .canvas import CanvasClient, html_to_text, split_lms_id
from .config import load_config
from .dates import KST, fmt_due

server = MCPServer(
    "hy-on",
    instructions=(
        "한양대 HY-ON(LMS)의 과제·퀴즈를 읽기 전용으로 조회한다. "
        "마감 일시는 모두 한국 시간(KST)이다. 노션에 쓰려면 노션 MCP를 사용한다."
    ),
)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
_client: tuple[CanvasClient, dict[str, str]] | None = None


def _canvas() -> tuple[CanvasClient, dict[str, str]]:
    global _client
    if _client is None:
        cfg = load_config()
        _client = (CanvasClient(cfg.hyon_base_url, cfg.hyon_token), cfg.course_aliases)
    return _client


@server.tool(annotations=_READ_ONLY)
def list_upcoming(days: int = 7) -> list[dict]:
    """앞으로 days일 안에 마감인 과제·퀴즈를 마감이 빠른 순서로 돌려준다."""
    canvas, aliases = _canvas()
    now = datetime.now(KST)
    until = now + timedelta(days=days)
    items = [i for i in canvas.fetch_items(aliases) if i.due_at and now <= i.due_at <= until]
    items.sort(key=lambda i: i.due_at)
    return [
        {
            "lms_id": i.lms_id,
            "kind": i.kind,
            "course": i.course,
            "title": i.title,
            "due": fmt_due(i.due_at),
            "due_iso": i.due_at.isoformat(),
            "url": i.url,
        }
        for i in items
    ]


@server.tool(annotations=_READ_ONLY)
def get_item(lms_id: str) -> dict:
    """list_upcoming이 돌려준 lms_id로 과제·퀴즈의 설명, 제출 형식, 배점, 링크를 가져온다."""
    canvas, _ = _canvas()
    course_id, assignment_id = split_lms_id(lms_id)
    a = canvas.assignment(course_id, assignment_id)
    return {
        "lms_id": lms_id,
        "title": a.get("name"),
        "description": html_to_text(a.get("description")),
        "submission_types": a.get("submission_types"),
        "points_possible": a.get("points_possible"),
        "unlock_at": a.get("unlock_at"),
        "due_at": a.get("due_at"),
        "url": a.get("html_url"),
    }


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
