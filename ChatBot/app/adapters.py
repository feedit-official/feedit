"""Django 읽기 전용 API를 챗봇 도구 계약으로 바꾸는 어댑터."""
from __future__ import annotations

import os
from urllib.parse import urlencode

import requests


class SalmalHTTPAdapter:
    def __init__(self, base: str | None = None, timeout: float = 4.0):
        self.base = (base or os.getenv("FEEDIT_BACKEND_API") or
                     "http://127.0.0.1:8000/api").rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, params: dict) -> dict:
        try:
            r = requests.get(f"{self.base}/{path}?{urlencode(params)}", timeout=self.timeout)
            r.raise_for_status()
            payload = r.json()
        except Exception as exc:  # noqa: BLE001 - 도구 실패가 대화를 죽이지 않는다
            return {"unavailable": f"살!말? 데이터를 읽지 못했습니다 ({type(exc).__name__})."}
        if payload.get("status") == "ok":
            return payload.get("data") or {}
        return {"unavailable": payload.get("reason") or "살!말? 데이터가 없습니다."}

    def card(self, card_id: int) -> dict:
        return self._get("salmal/card", {"card_id": int(card_id)})

    def search(self, term: str, limit: int = 5) -> dict:
        return self._get("salmal/search", {"term": term, "limit": limit})
