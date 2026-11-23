"""디스코드 봇이 나에게 DM으로 알림을 보낸다 (휴대폰 푸시 알림이 울린다).

카톡 '나에게 보내기'는 메모용이라 알림이 울리지 않아서 바꿨다.
준비: 디스코드 개발자 포털에서 봇을 만들어 토큰을 받고, 내 서버에 봇을 초대하고(봇과 같은 서버에 있어야 DM이 됨),
개발자 모드로 내 사용자 ID를 복사한다. 토큰은 비밀값이므로 로그·예외 메시지에 넣지 않는다.
"""

from __future__ import annotations

import httpx

API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com/ancho040220/hy-on-sync, 0.1)"  # 디스코드 REST API가 요구하는 형식


class DiscordError(RuntimeError):
    pass


class DiscordClient:
    max_len = 1900  # 디스코드 메시지 한도 2000자에서 링크 줄 자리를 뺀 값
    new_refresh_token = None  # 카카오와 같은 자리 (디스코드는 토큰 갱신이 없다)

    def __init__(self, bot_token: str, user_id: str, http: httpx.Client | None = None):
        self.user_id = user_id
        self.http = http or httpx.Client(base_url=API, timeout=15.0)
        self.headers = {"Authorization": f"Bot {bot_token}", "User-Agent": USER_AGENT}
        self._channel_id: str | None = None

    def _post(self, path: str, body: dict) -> dict:
        resp = self.http.post(path, json=body, headers=self.headers)
        if resp.status_code not in (200, 201):
            raise DiscordError(f"디스코드 요청 실패 ({resp.status_code}): {path.split('/')[1]}")
        return resp.json()

    def send_text(self, text: str, link_url: str) -> None:
        if self._channel_id is None:  # 실행당 한 번만 DM 채널을 연다
            self._channel_id = self._post("/users/@me/channels", {"recipient_id": self.user_id})["id"]
        self._post(
            f"/channels/{self._channel_id}/messages",
            {"content": f"{text}\n<{link_url}>", "allowed_mentions": {"parse": []}},
        )
