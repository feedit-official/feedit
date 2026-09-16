"""
인기 지표 정리 — 사이트마다 다른 이름·단위를 하나로 맞춘다.

파서는 화면에 적힌 글자를 그대로 가져온다. '7,826' 같은 문자열이고,
같은 '리뷰'라는 말도 사이트마다 뜻이 다르다. 여기서 한 번 정리해야
나중에 사이트를 가로질러 비교할 수 있다.

★ 크림 카드의 세 숫자
  저장본 50장을 전부 확인했다. 자리와 이름이 한 장도 안 어긋난다.
      0번 = 관심 · 1번 = 리뷰 · 2번 = 거래
  (처음엔 가운데를 '스타일 게시물'로 잘못 알았다. 부모 요소 글자를 읽어
   '· 리뷰 3.4만' 인 것을 확인하고 바로잡았다. 추측하지 말고 열어 볼 것.)

★ 평점은 5점 만점으로 통일한다.
  무신사는 두 가지를 준다 — reviewScore 98(백점) 과 satisfactionScore 4.9(5점).
  섞이면 평균이 통째로 망가지므로 들어온 값의 크기를 보고 환산한다.
"""

from __future__ import annotations

import re

_NUM = re.compile(r"([\d,]+(?:\.\d+)?)\s*([억만천])?")

# ★ 한국 사이트는 큰 수를 줄여 쓴다. 크림 카드가 그렇다.
#   '23.4만' 을 앞 숫자만 읽으면 234,000 이 23 이 된다.
#   거래 77.6만인 에어포스가 거래 77 로 들어가고, 그 옆의 '9,985' 짜리
#   상품이 인기 1위로 올라온다. 조용히 순위를 뒤집는 종류의 버그라
#   단위를 반드시 같이 읽는다.
_UNIT = {"천": 1_000, "만": 10_000, "억": 100_000_000}


def num(v, *, decimal=False):
    """'7,826' → 7826 · '23.4만' → 234000 · '4.8' → 4.8 · '(601)' → 601"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if decimal else int(v)
    m = _NUM.search(str(v))
    if not m:
        return None
    try:
        f = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    if m.group(2):
        f *= _UNIT[m.group(2)]
    return f if decimal else int(f)


def score5(v):
    """평점을 5점 만점으로 맞춘다.

    5 이하면 그대로, 100 이하면 백점 척도로 보고 나눈다.
    '98' 을 그대로 두면 평점이 98점인 상품이 생긴다.
    """
    f = num(v, decimal=True)
    if f is None:
        return None
    if f <= 5:
        return round(f, 2)
    if f <= 100:
        return round(f / 20, 2)
    return None


def from_record(source_code: str, r: dict) -> dict:
    """파서가 뽑아 놓은 것 중 '인기'에 해당하는 값만 골라 이름을 맞춘다."""
    g = r.get
    out = {
        "rank":         num(g("rank")),
        "review_count": num(g("review_count")),
        "review_score": score5(g("review_score")),
        "wish_count":   num(g("wish_count")),
        "trade_count":  num(g("trade_count")),
        "buy_count":    num(g("buy_count")),
        "style_count":  num(g("style_count")),
        "discount":     num(g("discount")),
        "price":        num(g("price")),
        # 숫자가 아닌 것들 — 별점 분포와 대표 평가 문구
        "review_dist":    g("review_dist") or None,
        "fit_note":       (g("fit_note") or "").strip() or None,
        "thickness_note": (g("thickness_note") or "").strip() or None,
        "quality_note":   (g("quality_note") or "").strip() or None,
    }

    if source_code == "kream":
        # 관심 · 리뷰 · 거래 (저장본 50장 전수 확인)
        out["wish_count"] = out["wish_count"] or num(g("wish_text"))
        out["review_count"] = out["review_count"] or num(g("review_text"))
        out["trade_count"] = out["trade_count"] or num(g("trade_text"))

    return {k: v for k, v in out.items() if v is not None}


# ── 발매가 통화 처리 ──────────────────────────────────────────
#  크림 발매가는 '$19' 로 오기도 한다. 원화로 바꿔야 리세일 지수의
#  분모가 되는데, 사이트가 적어 준 환산값(약 26,200원)을 쓰면 안 된다.
#  그건 그 사이트 환율이다. 우리 환율로, 수집한 날짜 기준으로 바꾼다.
def retail_fields(rec: dict, fx=None, on=None) -> dict:
    """발매가를 원본 통화 그대로 + 원화 환산으로 나눠 돌려준다."""
    from .fx import parse_money

    raw = rec.get("retail_price_raw")
    krw = rec.get("retail_price")
    money = parse_money(raw) if raw else None

    if money and money[1] != "KRW":
        amount, cur = money
        if fx is None:
            # 환율기가 없으면 원본만 남긴다. 추측한 원화를 넣지 않는다.
            return {"retail_price_orig": amount, "retail_currency": cur}
        c = fx.to_krw(amount, cur, on)
        return {"retail_price": c.get("krw"),
                "retail_price_orig": amount, "retail_currency": cur,
                "retail_fx_rate": c.get("fx_rate"), "retail_fx_date": c.get("fx_date")}

    if krw is None and money:
        krw = int(money[0])
    if krw is None:
        return {}
    return {"retail_price": int(krw), "retail_price_orig": float(krw),
            "retail_currency": "KRW", "retail_fx_rate": 1.0}
