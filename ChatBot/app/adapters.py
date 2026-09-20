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
            token = (os.getenv("FEEDIT_API_TOKEN") or "").strip()
            headers = {"X-FEEDiT-Token": token} if token else {}
            r = requests.get(f"{self.base}/{path}?{urlencode(params)}",
                             headers=headers, timeout=self.timeout)
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


# ══════════════════════════════════════════════════════════════
#  ★ 2026-09-20 가격 · 할인 · 리세일 · 수명주기 — 트렌드 분석 화면과 같은 API 를 읽는다.
#    계산 규칙을 챗봇에 따로 두지 않는다(화면과 답이 달라지는 걸 막는다).
#    무신사 · 지그재그 · 에이블리(할인) / 무신사 유즈드 · 크림(리세일)이 모두 여기로 들어온다.
# ══════════════════════════════════════════════════════════════
_SEL_KEYS = ("brand", "kind", "style", "item")


def _sel(sel: dict | None) -> dict:
    out = {}
    for k in _SEL_KEYS:
        v = (sel or {}).get(k)
        if v:
            out[k] = str(v).strip()
    return out


def _slim_list(rows, keys, limit=6):
    return [{k: r.get(k) for k in keys if k in r} for r in (rows or [])[:limit] if isinstance(r, dict)]


class MarketHTTPAdapter(SalmalHTTPAdapter):
    """/api/discount · /api/resale · /api/lifecycle — 모델에게는 숫자만 추려서 준다(시계열은 뺀다)."""

    def __init__(self, base: str | None = None, timeout: float = 8.0):
        super().__init__(base=base, timeout=timeout)

    def _market(self, path: str, params: dict) -> dict:
        data = self._get(path, params)
        if "unavailable" in data:
            data["unavailable"] = data["unavailable"].replace("살!말? 데이터", "시장 데이터")
        return data

    def discount(self, sel: dict, days: int = 30) -> dict:
        d = self._market("discount", {**_sel(sel), "days": days})
        if "unavailable" in d:
            return d
        return {
            "label": d.get("label"), "as_of": d.get("as_of"), "days": d.get("days"),
            "overall": {k: v for k, v in (d.get("overall") or {}).items() if k != "stock"},
            "cheapest": {k: (d.get("cheapest") or {}).get(k) for k in ("code", "name", "min_sale_price", "min_list_price", "min_discount")} if d.get("cheapest") else None,
            # 판매처별: 상품 수 · 평균/최대 할인율(%) · 최저 판매가 · 품절 수 · 평점
            "platforms": _slim_list(d.get("platforms"),
                                    ("code", "name", "products", "avg_discount", "max_discount",
                                     "full_price_pct", "min_sale_price", "min_list_price",
                                     "sold_out", "rating", "reviews")),
            "change_2w": d.get("change_2w"),
            "first_discount_days": d.get("first_discount_days"),
            "max_discount_period": d.get("max_discount_period"),
            "restock_count": d.get("restock_count"),
            "matched_platforms": d.get("matched_platforms"),
        }

    def resale(self, sel: dict, days: int = 30) -> dict:
        d = self._market("resale", {**_sel(sel), "days": days})
        if "unavailable" in d:
            return d
        keys = ("label", "as_of", "days", "listings", "keep_pct", "keep_change_pp", "premium",
                "premium_days", "used_price", "regular_price", "resale_index", "volume_4w",
                "volume_change_pct", "volume_basis", "spread", "basis_note")
        out = {k: d.get(k) for k in keys}
        out["sizes"] = _slim_list(d.get("sizes"), ("label", "count", "share_pct", "ratio", "price"), 5)
        for k in ("platforms", "grades", "conditions"):
            if isinstance(d.get(k), list):
                out[k] = _slim_list(d.get(k), ("label", "count", "share_pct", "ratio", "price"), 5)
        if out.get("regular_price") is None:
            out["note"] = "정가를 찾지 못한 매물이라 유지율(정가 대비 %)은 계산하지 않았습니다. 거래가만 보세요."
        return out

    def lifecycle(self, sel: dict, term: str | None = None) -> dict:
        params = _sel(sel)
        if term:
            params["term"] = term
        d = self._market("lifecycle", params)
        if "unavailable" in d:
            return d
        keys = ("label", "term", "facet", "as_of", "points", "basis", "stage", "progress",
                "peak_date", "age_weeks", "level", "momentum", "temp", "inflow_pct", "mention_28d")
        out = {k: d.get(k) for k in keys}
        wt = d.get("weekly_temp") or []
        out["weekly_temp_recent"] = wt[:6]
        return out
