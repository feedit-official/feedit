"""
환율 — 달러로 적힌 값을 '그때 환율'로 원화로 바꾼다.

── 왜 필요한가 ──
크림 발매가가 이렇게 나온다.

    발매가 $19 (약 26,200원)

리세일 지수는 '발매가 대비 지금 얼마'다. 분모가 달러면 계산이 안 된다.
그렇다고 크림이 적어 준 '약 26,200원'을 그대로 쓰면 안 된다 —
그건 크림이 자기 환율로, 자기가 화면을 그린 시점에 계산한 값이다.
사이트마다 환율이 다르면 지수가 사이트마다 달라진다.

★ 그래서 '원본 금액 + 통화 + 우리가 쓴 환율'을 셋 다 남긴다.
  원화 값 하나만 저장하면 나중에 "이 환율이 맞나?"를 되짚을 수 없다.
  환율이 틀렸다는 걸 알아도 되돌릴 방법이 없다. 셋을 남기면 다시 계산하면 된다.

★ '크롤링 당시' 환율을 쓴다
  오늘 환율로 3년 전 발매가를 환산하면 그건 발매가가 아니다.
  수집한 날짜의 환율을 쓴다. 과거 날짜도 조회되는 API 를 골랐다.

★ 환율을 못 구했을 때 조용히 넘어가지 않는다
  마지막으로 알던 값을 쓰되 is_stale 을 붙인다. 아무 표시 없이 옛날 환율을
  쓰면 그 값이 지표에 섞여 들어가고, 나중에 왜 이상한지 알 수가 없다.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

from . import identity as _identity

UTC = timezone.utc

DDL = """
CREATE TABLE IF NOT EXISTS fx_rate (
  rate_date   TEXT NOT NULL,          -- YYYY-MM-DD (환율 기준일)
  base        TEXT NOT NULL,          -- 'USD'
  quote       TEXT NOT NULL,          -- 'KRW'
  rate        REAL NOT NULL,          -- 1 base = rate quote
  source      TEXT,                   -- 어디서 받았나
  is_stale    INTEGER DEFAULT 0,      -- 그날 환율을 못 구해 다른 날 것을 썼나
  fetched_at  TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (rate_date, base, quote)
);
"""

# 무료·무키. 유럽중앙은행 고시를 그대로 준다. 과거 날짜도 된다.
_PRIMARY = "https://api.frankfurter.app/{d}?from={b}&to={q}"
# 예비 — 첫 번째가 죽었을 때만
_BACKUP = "https://open.er-api.com/v6/latest/{b}"

# 통화 기호 → 코드. 화면 글자에서 통화를 알아내는 데 쓴다.
SYMBOL = {"$": "USD", "US$": "USD", "USD": "USD",
          "¥": "JPY", "JPY": "JPY", "€": "EUR", "EUR": "EUR",
          "₩": "KRW", "KRW": "KRW", "원": "KRW"}

_MONEY = re.compile(
    r"(?P<sym>US\$|\$|₩|€|¥)\s*(?P<num>[\d,]+(?:\.\d+)?)"
    r"|(?P<num2>[\d,]+(?:\.\d+)?)\s*(?P<sym2>USD|KRW|JPY|EUR|원)")


def parse_money(text: str) -> tuple[float, str] | None:
    """'$19' → (19.0, 'USD') · '26,200원' → (26200.0, 'KRW')"""
    m = _MONEY.search(str(text or ""))
    if not m:
        return None
    num = m.group("num") or m.group("num2")
    sym = m.group("sym") or m.group("sym2")
    try:
        return float(num.replace(",", "")), SYMBOL.get(sym, "KRW")
    except (TypeError, ValueError):
        return None


class FX:
    """환율 창고. 한 번 받은 날짜는 다시 안 묻는다."""

    def __init__(self, store, offline: bool = False, timeout: float = 6.0):
        self.store = store
        self.offline = offline          # 시험용 — 바깥에 안 나간다
        self.timeout = timeout
        with store._lock:
            store._conn.executescript(DDL)
            store._conn.commit()

    # ── 저장소 ───────────────────────────────────────────────
    def _get(self, d: str, base: str, quote: str):
        with self.store._lock:
            r = self.store._conn.execute(
                "SELECT rate, source, is_stale FROM fx_rate "
                "WHERE rate_date=? AND base=? AND quote=?", (d, base, quote)).fetchone()
        return dict(r) if r else None

    def _put(self, d, base, quote, rate, source, stale=0):
        with self.store._lock:
            self.store._conn.execute(
                "INSERT OR REPLACE INTO fx_rate "
                "(rate_date, base, quote, rate, source, is_stale, fetched_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (d, base, quote, float(rate), source, int(stale),
                 datetime.now(UTC).isoformat()))
            self.store._conn.commit()

    # ── 바깥에서 받아오기 ────────────────────────────────────
    def _fetch(self, d: str, base: str, quote: str):
        if self.offline:
            return None
        for url, pick in (
            (_PRIMARY.format(d=d, b=base, q=quote),
             lambda j: (j.get("rates") or {}).get(quote)),
            (_BACKUP.format(b=base),
             lambda j: (j.get("rates") or {}).get(quote)),
        ):
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": _identity.crawler_ua()})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    j = json.loads(r.read().decode("utf-8"))
                v = pick(j)
                if v:
                    return float(v), url.split("/")[2]
            except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
                continue
        return None

    # ── 본체 ─────────────────────────────────────────────────
    def rate(self, on: str | date | None = None,
             base: str = "USD", quote: str = "KRW") -> dict:
        """그날의 1 base 당 quote 값.

        돌려주는 것: {rate, date, source, is_stale}
        is_stale 이 True 면 그날 환율이 아니라 가장 가까운 날 것을 쓴 것이다.
        """
        if base == quote:
            return {"rate": 1.0, "date": str(on or ""), "source": "same",
                    "is_stale": False}

        d = str(on or date.today())[:10]
        got = self._get(d, base, quote)
        if got:
            return {"rate": got["rate"], "date": d, "source": got["source"],
                    "is_stale": bool(got["is_stale"])}

        fetched = self._fetch(d, base, quote)
        if fetched:
            rate, src = fetched
            self._put(d, base, quote, rate, src)
            return {"rate": rate, "date": d, "source": src, "is_stale": False}

        # 주말·공휴일은 고시가 없다. 앞뒤로 며칠 물러서 본다.
        for back in range(1, 8):
            dd = (date.fromisoformat(d) - timedelta(days=back)).isoformat()
            got = self._get(dd, base, quote)
            if not got:
                f = self._fetch(dd, base, quote)
                if f:
                    self._put(dd, base, quote, f[0], f[1])
                    got = {"rate": f[0], "source": f[1]}
            if got:
                # 그날 값이 아니라는 걸 반드시 남긴다.
                self._put(d, base, quote, got["rate"],
                          f"{got['source']}@{dd}", stale=1)
                return {"rate": got["rate"], "date": dd,
                        "source": got["source"], "is_stale": True}

        # 마지막 수단 — 우리가 아는 가장 최근 값
        with self.store._lock:
            r = self.store._conn.execute(
                "SELECT rate, source, rate_date FROM fx_rate "
                "WHERE base=? AND quote=? ORDER BY rate_date DESC LIMIT 1",
                (base, quote)).fetchone()
        if r:
            return {"rate": r["rate"], "date": r["rate_date"],
                    "source": r["source"], "is_stale": True}
        return {"rate": None, "date": d, "source": None, "is_stale": True}

    # ── 환산 ─────────────────────────────────────────────────
    def to_krw(self, amount, currency: str = "USD", on=None) -> dict:
        """달러 금액 → 원화. 쓴 환율을 같이 돌려준다.

        원화 값만 저장하면 나중에 환율이 틀렸을 때 되돌릴 수가 없다.
        원본 금액·통화·환율을 셋 다 남기는 게 이 함수의 요점이다.
        """
        if amount is None:
            return {"krw": None}
        amount = float(amount)
        if currency == "KRW":
            return {"krw": int(round(amount)), "orig": amount, "currency": "KRW",
                    "fx_rate": 1.0, "fx_date": str(on or "")[:10], "is_stale": False}
        r = self.rate(on, currency, "KRW")
        if not r["rate"]:
            # 환율을 못 구하면 원화를 만들지 않는다. 0 이나 추측값을 넣으면
            # 그게 지표에 섞여 들어가고 아무도 모른다.
            return {"krw": None, "orig": amount, "currency": currency,
                    "fx_rate": None, "fx_date": None, "is_stale": True,
                    "error": "환율을 구하지 못했습니다"}
        return {"krw": int(round(amount * r["rate"])), "orig": amount,
                "currency": currency, "fx_rate": r["rate"],
                "fx_date": r["date"], "is_stale": r["is_stale"]}

    @staticmethod
    def label(orig, currency: str, krw) -> str:
        """화면에 적을 글자. 지표는 원화지만 표기는 둘 다 보여 준다."""
        if orig is None:
            return "-"
        if currency == "KRW" or not currency:
            return f"{int(orig):,}원"
        sym = {"USD": "$", "JPY": "¥", "EUR": "€"}.get(currency, currency + " ")
        o = f"{sym}{orig:,.0f}" if float(orig).is_integer() else f"{sym}{orig:,.2f}"
        return f"{o} · {int(krw):,}원" if krw else o
