"""
구매 의향 분류 — 설계서의 라벨 6개를 규칙으로 붙인다.

설계서가 못박아 둔 것:
  · 감성분석 모델을 붙이면 안 된다. "예뻐요"는 긍정이지만 구매 신호가 아니고,
    "비싸다"는 부정이지만 사고 싶다는 뜻일 때가 많다.
  · 1단계는 규칙 기반으로. 라벨이 6개뿐이고 표현이 정형적이라
    규칙으로 70~80%는 잡힌다. 학습 데이터가 쌓이면 그때 모델로 바꾼다.

그래서 여기는 정규식과 어휘만 쓴다. 모델 없음. 학습 없음.

★ 한 문장에 여러 라벨이 붙을 수 있다
  "살까말까 고민중... 좀 비싸네요" → 구매고민(+0.5) · 가격부담(−0.6)
  하나만 고르면 정보를 버리는 것이다. 다 붙이고 가중 평균한다.

★ 표본이 적으면 중립으로 당긴다 (수축)
  설계서의 S' = S × n/(n+100). 신규 키워드가 댓글 3건으로 지수 95를
  찍는 사고를 막는다.
"""

from __future__ import annotations

import re
import unicodedata

# ── 라벨과 가중치 (설계서 표 그대로) ──────────────────────────
LABELS = {
    "buy_done":   {"name": "구매 완료",      "w": +1.0},
    "restock":    {"name": "재입고·재고 문의", "w": +0.8},
    "considering": {"name": "구매 고민",      "w": +0.5},
    "price_pain": {"name": "가격 부담",      "w": -0.6},
    "disappoint": {"name": "실물 불만",      "w": -0.9},
    "returned":   {"name": "반품·취소",      "w": -1.0},
}

# ── 규칙 ──────────────────────────────────────────────────────
#  ※ 순서가 뜻을 바꾼다. '반품했어요'는 구매완료가 아니라 반품이다.
#    그래서 부정 라벨을 먼저 보고, 걸리면 구매완료를 빼 준다.
RULES: list[tuple[str, str]] = [
    ("returned", r"반품|환불|취소했|취소하|교환했|되팔|중고로\s*팔"),
    ("disappoint", r"실물(이|은|)\s*(별로|다르|아쉽)|사진과\s*다르|광고와\s*다르"
                   r"|생각보다\s*(별로|안좋|이상)|퀄리티\s*(별로|떨어|실망)"
                   r"|재질이\s*(별로|싸구려)|후회|비추"),
    ("price_pain", r"비싸|가격이?.{0,5}(부담|세네|세다|미쳤)|돈이?\s*아깝|가성비.{0,6}(별로|안좋|떨어|꽝)"
                   r"|세일\s*하면|할인\s*하면|쿠폰\s*(없나|주세요)|입문가|너무\s*비"),
    ("restock", r"재입고|재고\s*(있나|남았|문의)|품절|언제\s*(들어오|나와|풀려|재입고)"
                r"|사이즈.{0,8}(있나요|있나|남았|없나|재고)|어디서\s*(사|살|구매)|링크\s*(좀|주세요)"
                r"|판매처|구매처|어디\s*파"),
    ("considering", r"살까|고민(중|되|이)|担|사고\s*싶|갖고\s*싶|위시|장바구니"
                    r"|찜(했|해)|눈여겨|고민만|지를까|살지\s*말지"),
    ("buy_done", r"질렀|샀|구매했|주문했|결제했|배송\s*(왔|받|출발|중)|도착했"
                 r"|입고\s*받|잘\s*쓰고\s*있|재구매|또\s*샀|하나\s*더\s*샀"),
]
_COMPILED = [(k, re.compile(p)) for k, p in RULES]

# 이 말이 있으면 반대로 읽어야 한다.
_NEGATE = re.compile(r"안\s*(살|사|샀|비싸)|않(았|아|을)|말까|아니")


def _clean(t: str) -> str:
    t = unicodedata.normalize("NFC", str(t or ""))
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"[#@]\S+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def classify(text: str) -> dict:
    """문장 하나 → 붙은 라벨들과 점수.

    돌려주는 것: {labels: [...], score: -1~+1, matched: {라벨: 걸린 말}}
    아무것도 안 걸리면 labels 가 빈 목록이고 score 는 None 이다.
    **0 이 아니라 None 이다** — '중립'과 '판단 못 함'은 다르다.
    """
    t = _clean(text)
    if not t:
        return {"labels": [], "score": None, "matched": {}}

    hits, matched = [], {}
    for key, rx in _COMPILED:
        m = rx.search(t)
        if m:
            hits.append(key)
            matched[key] = m.group(0)

    # '반품했다'가 '샀다'로도 걸리면 반품이 이긴다. 결과가 더 중요한 사실이다.
    if "returned" in hits and "buy_done" in hits:
        hits.remove("buy_done")
        matched.pop("buy_done", None)

    if not hits:
        return {"labels": [], "score": None, "matched": {}}

    ws = [LABELS[h]["w"] for h in hits]
    score = sum(ws) / len(ws)
    return {"labels": hits, "score": round(score, 3), "matched": matched}


def aggregate(texts, shrink_n: int = 100) -> dict:
    """여러 문장 → 구매의향 지수 0~100.

    설계서 공식 그대로:
        S  = Σ(w_i × n_i) / Σ(n_i)
        S' = S × n / (n + shrink_n)        ← 표본이 적으면 중립으로
        지수 = round(50 + 50 × S')
    """
    counts = {k: 0 for k in LABELS}
    n = 0
    for t in texts:
        r = classify(t)
        if not r["labels"]:
            continue
        n += 1
        for k in r["labels"]:
            counts[k] += 1

    total = sum(counts.values())
    if not total:
        return {"index": None, "n": 0, "counts": counts,
                "message": "판단할 만한 말이 없습니다."}

    s = sum(LABELS[k]["w"] * c for k, c in counts.items()) / total
    s2 = s * n / (n + shrink_n)
    idx = round(50 + 50 * s2)

    pos = sum(c for k, c in counts.items() if LABELS[k]["w"] > 0)
    neg = total - pos
    band = ("강한 구매 신호" if idx >= 75 else
            "구매 신호 우세" if idx >= 55 else
            "팽팽한 신호" if idx >= 35 else "구매 저해 신호 우세")
    return {"index": idx, "band": band, "n": n, "signals": total,
            "counts": counts,
            "pos_pct": round(100 * pos / total, 1) if total else 0,
            "neg_pct": round(100 * neg / total, 1) if total else 0,
            "raw_score": round(s, 3), "shrunk": round(s2, 3)}
