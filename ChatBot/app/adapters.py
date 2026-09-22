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
# 상품 조회 한 칸의 상한(초). 병렬로 불러도 가장 느린 칸이 한 바퀴를 정한다.
PRODUCTS_TIMEOUT = 4.0


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
        # ★ 상품 조회만 시계를 짧게 쓴다 (2026-09-22). 코디는 칸마다 한 번씩 부르므로
        #   한 칸의 지연이 그대로 한 바퀴의 지연이 된다.
        keep = self.timeout
        if path == "products":
            self.timeout = min(self.timeout, PRODUCTS_TIMEOUT)
        try:
            data = self._get(path, params)
        finally:
            self.timeout = keep
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

    # ── 상품 목록 (2026-09-22) ────────────────────────────────
    #   ★ 화면이 쓰는 /api/products 를 그대로 읽는다. 스타일은 자동 태깅 결과
    #     (commerce.product_term · term_type='STYLE')로 걸리고, 사진(thumbnail_url)과
    #     최신 가격이 함께 온다 — 코디를 짤 재료가 이 한 곳에 다 있다.
    #   ★ timeout 이 짧다. 코디는 칸마다 한 번씩 물어서(fit.propose 가 병렬로 부른다)
    #     한 칸이 오래 끌면 답 쓸 시간을 먹는다. 못 받으면 그 칸은 비는 게 낫다.
    def products(self, sel: dict, limit: int = 3, sort: str = "recommend") -> list[dict]:
        data = self._market("products", {**_sel(sel), "sort": sort, "limit": limit})
        if "unavailable" in data:
            return []
        rows = _slim_list(data.get("items"),
                          ("name", "brand", "image", "url", "product_source_id", "category"),
                          limit)
        # 가격은 중첩 객체라 _slim_list 가 통째로 옮긴다 — 판매가 하나만 남긴다.
        for row, src in zip(rows, (data.get("items") or [])):
            price = (src or {}).get("price") or {}
            row["price"] = price.get("sale") or price.get("list")
        return rows

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
