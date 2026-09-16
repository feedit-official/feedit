"""
수집 커버리지 — "우리 지표를 만들려면 뭐가 필요한데, 지금 뭐가 들어와 있나".

데이터 탭은 '한 상품이 어떻게 생겼나'를 보여 준다. 그런데 크롤러를 돌리는
사람이 정작 알고 싶은 건 다른 것이다 — **플랫폼 기능 하나를 만들려면
어떤 값이 필요하고, 그게 사이트별로 채워지고 있느냐**.

지금까지는 이걸 알 방법이 없었다. 후기 수가 몇 주 동안 통째로 버려지고
있었는데도 아무도 몰랐던 이유가 그거다. 화면이 '상품 1,304건'이라고만
말해 주니 건수는 늘고 있고 아무 문제 없어 보였다.

그래서 여기서는 건수 대신 **기능 단위**로 본다.
  "리세일 지수를 만들려면 체결가와 발매가가 필요하다 → 크림 92% / 무신사 유즈드 일부"
이렇게 보여야 무엇을 다음에 고쳐야 할지가 바로 보인다.
"""

from __future__ import annotations

# ── 값 하나하나가 어디 있는지 ──────────────────────────────────
#  (라벨, 표, 조건). 조건은 staging_product 를 p 로 놓고 쓴다.
FIELDS: dict[str, tuple[str, str, str]] = {
    "name":         ("상품명",     "product", "p.name IS NOT NULL AND trim(p.name)<>''"),
    "brand":        ("브랜드",     "product", "p.brand_name IS NOT NULL AND trim(p.brand_name)<>''"),
    "image":        ("사진",       "product", "p.image_url IS NOT NULL AND trim(p.image_url)<>''"),
    "category":     ("카테고리",   "product", "p.category_path IS NOT NULL AND trim(p.category_path)<>''"),
    "model_code":   ("모델번호",   "product", "p.model_code IS NOT NULL AND trim(p.model_code)<>''"),
    "retail_price": ("발매가·정가", "product", "p.retail_price IS NOT NULL"),
    "size_names":   ("사이즈 목록", "product", "p.size_names IS NOT NULL AND p.size_names NOT IN ('','[]')"),
    "measurements": ("실측 치수",  "product", "p.measurements IS NOT NULL AND p.measurements NOT IN ('','[]')"),

    "price_now":    ("현재가",     "listing", "1=1"),
    "settled":      ("체결가",     "listing", "listing_type='settled'"),

    "rank":         ("랭킹 순위",  "stat", "rank IS NOT NULL"),
    "review_count": ("후기 수",    "stat", "review_count IS NOT NULL"),
    "review_score": ("평점",       "stat", "review_score IS NOT NULL"),
    "review_dist":  ("별점 분포",  "stat", "review_dist IS NOT NULL"),
    "wish_count":   ("관심 수",    "stat", "wish_count IS NOT NULL"),
    "trade_count":  ("거래 수",    "stat", "trade_count IS NOT NULL"),
    "buy_count":    ("구매 수",    "stat", "buy_count IS NOT NULL"),
    "fit_note":     ("착용감 평가", "stat", "fit_note IS NOT NULL"),

    "text_body":    ("후기 본문",  "text", "1=1"),
}

# ── 플랫폼 기능마다 뭐가 필요한가 ─────────────────────────────
#  '어디서 받을 수 있나'는 사실이다. 추측으로 적지 않는다.
#  없는 곳은 없다고 적어야 "왜 0%지?" 하고 헤매지 않는다.
FEATURES = [
    {
        "key": "identity", "name": "상품 기본 정보",
        "why": "무엇이든 하려면 먼저 이게 있어야 한다",
        "need": ["name", "brand", "image", "price_now"],
        "from": {"kream": 1, "musinsa": 1, "zigzag": 1, "musinsa_used": 1,
                 "ably": 0.5},
        "note": "에이블리만 0.5 인 건 사진 때문이다. 카드에 <img> 태그가 아예 "
                "없고 나중에 붙는 구조라 못 잡는다. 나머지는 다 들어온다.",
    },
    {
        "key": "matching", "name": "플랫폼 간 상품 매칭",
        "why": "무신사의 그 옷이 크림에서 얼마인지 이으려면 모델번호가 열쇠다",
        "need": ["model_code"],
        "from": {"kream": 1, "musinsa": 0.5, "musinsa_used": 0.5,
                 "zigzag": 0, "ably": 0},
        "note": "무신사 목록에는 모델번호 칸이 없다. 상품명 꼬리에 붙은 것만 "
                "주워서 15% 정도다 (API 가 나오면 100% 가 된다). "
                "지그재그·에이블리는 자체 제작(MADE) 비중이 커서 모델번호가 없다. "
                "이쪽은 상품명·브랜드로 묶는 수밖에 없다.",
    },
    {
        "key": "resale", "name": "리세일 지수 (프리미엄율)",
        "why": "발매가 대비 지금 얼마에 팔리나 — EDIT 의 핵심 숫자",
        "need": ["settled", "retail_price"],
        "from": {"kream": 1, "musinsa_used": 0.5,
                 "musinsa": 0, "zigzag": 0, "ably": 0},
        "note": "리세일 플랫폼에만 있는 값이다. 커머스 3사는 정가 판매라 "
                "체결가라는 개념 자체가 없다 — 0% 가 정상이다.",
    },
    {
        "key": "popularity", "name": "인기·수요 지표",
        "why": "무엇이 지금 뜨는지 가리는 신호",
        "need": ["rank", "review_count", "wish_count", "trade_count", "buy_count"],
        "any": True,          # 하나만 있어도 쓸 수 있다
        "from": {"kream": 1, "musinsa": 1, "zigzag": 1, "ably": 1, "musinsa_used": 0.5},
    },
    {
        "key": "sentiment", "name": "긍부정·연관어 (EDIT 어휘)",
        "why": "'오버핏' 같은 말이 언제 얼마나 오르내리는지 — 트렌드의 원천",
        "need": ["text_body"],
        "from": {"kream": 0.5, "musinsa": 0.5, "zigzag": 0.5, "ably": 0,
                 "musinsa_used": 0},
        "note": "★ 지금 한 건도 없다. 후기 '개수'는 받고 있지만 '본문'은 안 받는다. "
                "본문은 상세 페이지 안에서도 따로 더 불러오는 구조라 "
                "지금 방식으로는 못 닿는다. 별도 작업이 필요하다.",
    },
    {
        "key": "fit", "name": "사이즈·핏 추천",
        "why": "표기 사이즈가 제각각인 옷을 실제 치수로 비교",
        "need": ["size_names", "measurements", "fit_note"],
        "any": True,
        "from": {"musinsa_used": 0.5, "kream": 1, "musinsa": 0.5,
                 "zigzag": 0.5, "ably": 0},
        "note": "에이블리 실측은 robots.txt 가 막은 경로다. 안 간다.",
    },
    {
        "key": "pricetrend", "name": "가격 추이",
        "why": "할인 폭이 커지는지 — 재고 소진과 인기 하락의 신호",
        "need": ["price_now"],
        "from": {"kream": 1, "musinsa": 1, "zigzag": 1, "ably": 1, "musinsa_used": 1},
        "note": "값은 매번 들어온다. 다만 '추이'가 되려면 같은 상품을 "
                "여러 날 반복해서 봐야 한다 — 자동 주기가 그 일을 한다.",
    },
    {
        "key": "taxonomy", "name": "카테고리 분류",
        "why": "'여성 상의' 안에서 무엇이 뜨는지 좁혀 보려면 필요",
        "need": ["category"],
        "from": {"kream": 1, "musinsa": 0.5, "musinsa_used": 1,
                 "zigzag": 0.5, "ably": 0.5},
        "note": "커머스 3사는 목록에 카테고리가 안 적힌다. 대신 우리가 "
                "'여성 상의' 페이지를 골라 들어가므로 그 라벨을 붙이면 된다.",
    },
]

STATUS = {1: ("가능", "ok"), 0.5: ("일부", "warn"), 0: ("불가", "na")}


def _pct(store, source_code: str, field: str) -> float | None:
    """이 사이트에서 이 값이 몇 %나 채워졌나. 분모는 늘 상품 수."""
    label, table, cond = FIELDS[field]
    with store._lock:
        total = store._conn.execute(
            "SELECT count(*) FROM staging_product WHERE source_code=?",
            (source_code,)).fetchone()[0]
        if not total:
            return None
        try:
            if table == "product":
                n = store._conn.execute(
                    f"SELECT count(*) FROM staging_product p "
                    f"WHERE p.source_code=? AND ({cond})", (source_code,)).fetchone()[0]
            elif table == "listing":
                # 리세일 행 uid 는 '<상품>:list' 꼴이라 콜론 앞을 잘라 묶는다
                n = store._conn.execute(
                    f"""SELECT count(DISTINCT CASE WHEN instr(source_uid,':')>0
                            THEN substr(source_uid,1,instr(source_uid,':')-1)
                            ELSE source_uid END)
                        FROM resale_listing WHERE source_code=? AND ({cond})""",
                    (source_code,)).fetchone()[0]
            elif table == "stat":
                n = store._conn.execute(
                    f"SELECT count(DISTINCT source_uid) FROM product_stat "
                    f"WHERE source_code=? AND ({cond})", (source_code,)).fetchone()[0]
            else:   # text
                n = store._conn.execute(
                    f"SELECT count(DISTINCT product_uid) FROM text_document "
                    f"WHERE source_code=? AND ({cond})", (source_code,)).fetchone()[0]
        except Exception:
            return None
    return round(n / total, 4)


def report(store, sources: list[str] | None = None) -> dict:
    """기능 × 사이트 표를 만든다."""
    with store._lock:
        have = [r[0] for r in store._conn.execute(
            "SELECT source_code, count(*) c FROM staging_product "
            "GROUP BY source_code HAVING c > 0 ORDER BY c DESC")]
    codes = [c for c in (sources or have) if not c.startswith("test")]

    counts = {}
    with store._lock:
        for c in codes:
            counts[c] = store._conn.execute(
                "SELECT count(*) FROM staging_product WHERE source_code=?",
                (c,)).fetchone()[0]

    out = []
    for feat in FEATURES:
        cells = []
        for c in codes:
            possible = feat["from"].get(c, 0)
            pcts = {f: _pct(store, c, f) for f in feat["need"]}
            vals = [v for v in pcts.values() if v is not None]
            if not vals:
                got = None
            elif feat.get("any"):
                got = max(vals)         # 하나만 있어도 되는 기능
            else:
                got = min(vals)         # 전부 있어야 하는 기능
            # 받을 수 있는데 안 받고 있으면 그게 고칠 거리다
            gap = bool(possible and got is not None and got < 0.5 * possible)
            cells.append({
                "source": c, "possible": possible,
                "status": STATUS[possible][1], "label": STATUS[possible][0],
                "got": got, "gap": gap,
                "detail": {FIELDS[f][0]: pcts[f] for f in feat["need"]},
            })
        out.append({**{k: v for k, v in feat.items() if k != "from"},
                    "needs": [FIELDS[f][0] for f in feat["need"]],
                    "cells": cells})
    return {"sources": codes, "counts": counts, "features": out}
