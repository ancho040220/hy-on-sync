"""카카오톡 '나에게 보내기'.

- REST API 액세스 토큰은 6시간, 리프레시 토큰은 2달 동안 유효하다.
- 실행할 때마다 리프레시 토큰으로 액세스 토큰을 새로 받는다.
- 리프레시 토큰은 만료 1달 전부터 새로 발급된다. 새 값이 오면 new_refresh_token에 담고,
  sync.py가 파일로 남기면 GitHub Actions가 Secret을 갱신한다.
"""

from __future__ import annotations

import json

import httpx

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


class KakaoError(RuntimeError):
    pass


class KakaoClient:
    def __init__(self, rest_key: str, client_secret: str, refresh_token: str, http: httpx.Client | None = None):
        self.rest_key = rest_key
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.http = http or httpx.Client(timeout=15.0)
        self.access_token: str | None = None
        self.new_refresh_token: str | None = None

    def refresh(self) -> None:
        data = {
            "grant_type": "refresh_token",
            "client_id": self.rest_key,
            "refresh_token": self.refresh_token,
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret
        resp = self.http.post(TOKEN_URL, data=data)
        if resp.status_code != 200:
            raise KakaoError(f"토큰 갱신 실패 ({resp.status_code}). 리프레시 토큰이 만료됐다면 다시 로그인하세요.")
        body = resp.json()
        self.access_token = body["access_token"]
        if body.get("refresh_token"):
            self.new_refresh_token = body["refresh_token"]

    def send_text(self, text: str, link_url: str) -> None:
        if self.access_token is None:
            self.refresh()
        template = {
            "object_type": "text",
            "text": text,
            # 링크 도메인은 카카오 디벨로퍼스 [앱] > [제품 링크 관리] > [웹 도메인]에 등록돼 있어야 한다
            "link": {"web_url": link_url, "mobile_web_url": link_url},
            "button_title": "HY-ON 열기",
        }
        resp = self.http.post(
            SEND_URL,
            headers={"Authorization": f"Bearer {self.access_token}"},
            data={"template_object": json.dumps(template, ensure_ascii=False)},
        )
        if resp.status_code != 200 or resp.json().get("result_code") != 0:
            raise KakaoError(f"메시지 전송 실패 ({resp.status_code}): {resp.text[:200]}")
