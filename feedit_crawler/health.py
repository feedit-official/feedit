"""
건강 점검 — 자동으로 돌기 시작하면 '조용히 틀리는 것'이 가장 무섭다.

크롤러가 멈추면 금방 안다. 문제는 **멈추지 않고 틀리는 경우**다.
사이트가 화면 구조를 바꾸면 셀렉터가 빗나가는데, 에러는 안 난다.
수집 건수도 그대로다. 다만 가격 칸이 전부 비어서 들어올 뿐이다.
크림에서 실제로 그랬다 — 20건이 '성공'으로 찍혔지만 값은 상품명뿐이었다.

그래서 건수가 아니라 **칸이 채워지는 비율**을 매번 기록하고,
지난번과 비교해 뚝 떨어지면 경고한다. 이게 이 파일의 존재 이유다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

UTC = timezone.utc

DDL = """
CREATE TABLE IF NOT EXISTS run_quality (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  source_code  TEXT NOT NULL,
  run_id       INTEGER,
  checked_at   TEXT NOT NULL,
  products     INTEGER DEFAULT 0,   -- 이번에 본 상품 수
  fill         TEXT,                -- json: {칸이름: 채워진 비율 0~1}
  errors       INTEGER DEFAULT 0,
  blocked      INTEGER DEFAULT 0,
  note         TEXT
);
CREATE INDEX IF NOT EXISTS ix_rq ON run_quality (source_code, id DESC);
"""

# 이 칸들이 비면 지표를 못 만든다. 사이트마다 기대치가 달라서 따로 둔다.
WATCH = {
    "kream":        ["name", "brand_name", "model_code", "image_url"],
    "fruitsfamily": ["name", "brand_name", "image_url"],
    "musinsa_used": ["name", "brand_name", "image_url"],
    "musinsa":      ["name", "brand_name", "retail_price", "image_url"],
    # 무신사 목록에는 모델번호가 없다(상세에만 있음). 지표에 넣으면 늘 0% 로
    # 경고가 뜨므로 감시 항목에서 뺀다 — 거짓 경보를 만들지 않는 게 중요하다.
    # 지그재그 목록에는 카테고리가 안 나온다(상세에만 있음). 감시에서 뺀다.
    "zigzag":       ["name", "brand_name", "image_url"],
    # 에이블리 카드에는 <img> 가 아예 없다. 이미지가 나중에 붙는 구조라
    # 수확 시점에는 못 잡는다. 감시에 두면 매번 0% 로 거짓 경보가 난다.
    "ably":         ["name", "brand_name"],
}
DEFAULT_WATCH = ["name", "brand_name", "image_url"]

# 인기 지표 — 사이트가 실제로 주는 것만 적는다.
# 안 주는 값을 적으면 늘 0% 라 경고가 무뎌진다.
STAT_WATCH = {
    "kream":   ["wish_count", "review_count", "trade_count"],
    "musinsa": ["rank"],          # 후기는 상세에만 있다. 목록만 돌면 안 들어온다.
    "zigzag":  ["review_count", "review_score"],
    "ably":    ["buy_count"],
    "musinsa_used": ["price"],
}

# 얼마나 떨어지면 경고할지
DROP_WARN = 0.30      # 30%p 이상 떨어지면 주의
DROP_BAD = 0.55       # 55%p 이상이면 심각
VOLUME_WARN = 0.5     # 수집량이 지난번의 절반 아래면 주의


def install(conn):
    conn.executescript(DDL)


def snapshot(store, source_code: str, run_id: int | None = None,
             errors: int = 0, blocked: bool = False, note: str = "") -> dict:
    """지금 이 사이트 데이터가 얼마나 채워져 있는지 재서 남긴다."""
    cols = WATCH.get(source_code, DEFAULT_WATCH)
    with store._lock:
        total = store._conn.execute(
            "SELECT count(*) FROM staging_product WHERE source_code=?",
            (source_code,)).fetchone()[0]
        fill = {}
        for c in cols:
            try:
                n = store._conn.execute(
                    f"SELECT count(*) FROM staging_product "
                    f"WHERE source_code=? AND {c} IS NOT NULL AND trim({c})<>''",
                    (source_code,)).fetchone()[0]
            except Exception:
                continue
            fill[c] = round(n / total, 4) if total else 0.0
        # ★ 인기 지표도 같이 본다. 예전엔 이걸 안 봐서, 파서가 후기 수를
        #   뽑고도 저장이 안 되고 있다는 걸 몇 주 동안 아무도 몰랐다.
        #   '수집은 되는데 조용히 사라지는 값'이야말로 이 파일이 잡아야 할 것이다.
        for c in STAT_WATCH.get(source_code, []):
            try:
                n_ = store._conn.execute(
                    f"""SELECT count(DISTINCT source_uid) FROM product_stat
                        WHERE source_code=? AND {c} IS NOT NULL""",
                    (source_code,)).fetchone()[0]
            except Exception:
                continue
            fill[c] = round(n_ / total, 4) if total else 0.0

        # 가격은 다른 표에 있다
        # 가격 종류를 안 가린다 — 리세일은 ask/settled, 커머스는 retail 이다.
        # 한쪽만 세면 나머지 사이트가 늘 '가격 없음' 으로 찍힌다.
        priced = store._conn.execute(
            """SELECT count(DISTINCT CASE WHEN instr(source_uid,':')>0
                        THEN substr(source_uid,1,instr(source_uid,':')-1)
                        ELSE source_uid END)
               FROM resale_listing WHERE source_code=?""", (source_code,)).fetchone()[0]
        fill["price"] = round(priced / total, 4) if total else 0.0

        store._conn.execute(
            """INSERT INTO run_quality
               (source_code, run_id, checked_at, products, fill, errors, blocked, note)
               VALUES (?,?,?,?,?,?,?,?)""",
            (source_code, run_id, datetime.now(UTC).isoformat(), total,
             json.dumps(fill, ensure_ascii=False), errors, int(blocked), note))
        store._conn.commit()
    return {"products": total, "fill": fill}


def _rows(store, source_code: str, limit: int = 8) -> list[dict]:
    with store._lock:
        rs = store._conn.execute(
            "SELECT * FROM run_quality WHERE source_code=? ORDER BY id DESC LIMIT ?",
            (source_code, limit)).fetchall()
    out = []
    for r in rs:
        d = dict(r)
        try:
            d["fill"] = json.loads(d["fill"] or "{}")
        except Exception:
            d["fill"] = {}
        out.append(d)
    return out


def check(store, source_code: str, expect_hours: float | None = None) -> dict:
    """지난번과 비교해 이상한 데가 있는지 본다.

    돌려주는 level: ok / warn / bad / unknown
    """
    hist = _rows(store, source_code)
    if not hist:
        return {"level": "unknown", "issues": [],
                "message": "아직 점검 기록이 없습니다.", "history": []}

    now, alerts = hist[0], []

    # ① 차단
    if now.get("blocked"):
        alerts.append(("bad", "차단이 감지돼 멈췄습니다. 간격을 늘리고 하루 쉬어 보세요."))

    # ② 마지막 수집이 너무 오래됨
    if expect_hours:
        try:
            last = datetime.fromisoformat(str(now["checked_at"]).replace(" ", "T"))
            # SQLite 가 넣은 값은 시간대가 없다. 그대로 빼면 TypeError 가 나는데
            # 예전엔 그게 조용히 삼켜져서 '안 돌고 있음' 경고가 안 떴다.
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            gap = (datetime.now(UTC) - last).total_seconds() / 3600
            if gap > expect_hours * 2:
                alerts.append(("bad", f"{gap:.0f}시간째 안 돌았습니다 "
                                      f"(예정 주기 {expect_hours:.0f}시간)."))
            elif gap > expect_hours * 1.5:
                alerts.append(("warn", f"{gap:.0f}시간째 안 돌았습니다."))
        except Exception:
            pass

    # ③ ★ 칸 채움률 급락 — 셀렉터가 빗나갔다는 가장 확실한 신호
    if len(hist) >= 2:
        prev = hist[1]
        for k, v in (now["fill"] or {}).items():
            p = (prev["fill"] or {}).get(k)
            if p is None or p < 0.2:      # 원래도 안 채워지던 칸은 넘어간다
                continue
            drop = p - v
            if drop >= DROP_BAD:
                alerts.append(("bad", f"'{k}' 가 {p*100:.0f}% → {v*100:.0f}% 로 무너졌습니다. "
                                      f"화면 구조가 바뀌었을 가능성이 큽니다."))
            elif drop >= DROP_WARN:
                alerts.append(("warn", f"'{k}' 채움률이 {p*100:.0f}% → {v*100:.0f}% 로 떨어졌습니다."))

        # ④ 수집량 급감
        if prev["products"] >= 20 and now["products"] < prev["products"] * VOLUME_WARN:
            alerts.append(("warn", f"상품 수가 {prev['products']} → {now['products']} 로 줄었습니다."))

    # ⑤ 지금 당장 비어 있는 핵심 칸
    for k, v in (now["fill"] or {}).items():
        if v < 0.15:
            alerts.append(("warn", f"'{k}' 가 거의 비어 있습니다 ({v*100:.0f}%). "
                                   f"설정에서 이 칸을 확인하세요."))

    level = "bad" if any(a[0] == "bad" for a in alerts) else \
            "warn" if alerts else "ok"
    msg = {"ok": "정상입니다.", "warn": "확인이 필요합니다.",
           "bad": "문제가 있습니다."}[level]
    return {
        "level": level,
        "issues": [{"level": a, "text": b} for a, b in alerts],
        "message": msg,
        "products": now["products"],
        "fill": now["fill"],
        "checked_at": now["checked_at"],
        "history": [{"at": h["checked_at"], "products": h["products"],
                     "fill": h["fill"]} for h in hist],
    }


def check_all(store, schedules: dict[str, float] | None = None) -> dict:
    out = {}
    with store._lock:
        codes = [r[0] for r in store._conn.execute(
            "SELECT DISTINCT source_code FROM run_quality")]
    for c in codes:
        out[c] = check(store, c, (schedules or {}).get(c))
    return out
