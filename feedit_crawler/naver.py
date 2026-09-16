# -*- coding: utf-8 -*-
"""네이버 수집 — 검색어 트렌드(지표 30%) + 블로그·카페 본문(긍부정).

설계서가 네이버에 **가중치 30%** 를 줬다. 커머스가 '이미 사고 있다'는
신호라면 네이버는 '찾아보고 있다'는 신호이고, 모수가 가장 크다.

★★ 데이터랩의 함정 — ratio 는 묶음 안에서의 상대값이다 ★★
  한 번에 5개까지 물어볼 수 있는데, 돌려주는 0~100 은
  **그 다섯 개 중에서** 가장 큰 값을 100 으로 놓은 값이다.
  그래서 묶음이 달라지면 같은 단어도 값이 달라진다.

      묶음 A: [오버핏, 루즈핏, 크롭]        → 오버핏 100
      묶음 B: [오버핏, 반팔, 니트]          → 오버핏 42

  이걸 모르고 그냥 쌓으면 "오버핏이 반토막 났다" 는 엉터리 지표가 나온다.
  설계서도 같은 경고를 해 뒀다.

  → 그래서 **모든 묶음에 같은 기준어(앵커)를 한 자리 넣는다.**
    앵커 대비 비율(scaled)로 바꾸면 묶음이 달라도 견줄 수 있다.
        scaled = ratio / 그 날 앵커의 ratio
    앵커가 0 인 날은 나눌 수 없으니 그 날은 scaled 를 비워 둔다.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

UTC = timezone.utc   # 파이썬 3.10 에도 있는 형태로

from .commentfilter import _norm
from .social import Naver, NotConfigured

PROBLEMS = None          # 서버가 켤 때 꽂아 준다

# 모든 묶음에 끼워 넣는 기준어. 계절을 타지 않고 늘 검색되는 말이어야 한다.
ANCHOR = "패션"
GROUP = 5                      # 데이터랩이 한 번에 받는 최대 개수

DDL = """
CREATE TABLE IF NOT EXISTS naver_trend (
  term        TEXT NOT NULL,
  observed_on TEXT NOT NULL,
  ratio       REAL,            -- 네이버가 준 값 (묶음 안 상대값 — 그대로 쓰면 안 됨)
  anchor      REAL,            -- 그 날 앵커의 값
  scaled      REAL,            -- ratio / anchor — ★ 묶음이 달라도 견줄 수 있는 값
  batch       TEXT,            -- 어느 묶음에서 나왔나 (되짚기용)
  collected_at TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (term, observed_on)
);
CREATE INDEX IF NOT EXISTS ix_ntrend ON naver_trend (observed_on DESC);
"""

# 블로그는 광고글이 많다. 이런 말이 보이면 여론이 아니라 홍보다.
_AD = (
    "협찬", "광고", "체험단", "제공받아", "원고료", "소정의", "무상으로 제공",
    "쿠팡 파트너스", "수수료를 제공", "제휴", "홍보성",
)

# 태깅 어휘와 검색 질의는 같지 않다. 상품명 안의 '여행'은 TPO로 쓸 수
# 있지만 네이버에서 '여행'만 찾으면 관광 글이 나온다. 지표의 표준 이름은
# 그대로 두고, 외부 API에 보낼 때만 패션 문맥을 입힌다.
_TPO_QUERY = {
    "출근": ["출근룩", "오피스룩"],
    "바캉스": ["바캉스룩", "휴양지룩", "리조트룩"],
    "여행": ["여행룩", "여행 코디"],
    "하객": ["하객룩", "결혼식 코디"],
    "데이트": ["데이트룩", "데이트 코디"],
    "운동": ["운동복", "운동복 코디", "짐웨어"],
}
_MATERIAL_QUERY = {
    "와플": ["와플 소재", "와플 니트", "와플 티셔츠"],
    "골지": ["골지 소재", "골지 니트", "골지 티셔츠"],
}
_FASHION_CONTEXT = re.compile(
    r"패션|코디|룩\b|룩[을은이가]|스타일|옷|의류|착용|아이템|상의|하의"
    r"|티셔츠|셔츠|니트|팬츠|바지|스커트|원피스|자켓|재킷|아우터|코트"
    r"|패딩|신발|스니커즈|가방|모자|핏",
    re.I)
_GARMENT_CONTEXT = re.compile(
    r"옷|의류|착용|상의|하의|티셔츠|셔츠|니트|스웨터|팬츠|바지|스커트"
    r"|원피스|자켓|재킷|아우터|코트|패딩|후드|가디건|셋업|드레스|핏"
    r"|양말|삭스|신발|슈즈|구두|로퍼|부츠|가방|모자|잠옷|파자마|실내복|내복",
    re.I)
_LISTING_MARKS = re.compile(
    r"상품\s*정보|판매가|구매\s*링크|주문서|택배|배송비|시세조회|N\s*페이"
    r"|결제\s*혜택|즉시할인|입금|판매합니다|가격\s*[:：-]",
    re.I)


def _facet_map(path="config/lexicon.yaml") -> dict[str, str]:
    from .lexicon import Lexicon
    return Lexicon(path).facet_of


def query_keywords(term: str, facet: str = "") -> list[str]:
    """표준 어휘 하나를 네이버에 보낼 패션 문맥 검색어로 바꾼다."""
    if term in _TPO_QUERY:
        return _TPO_QUERY[term]
    if term in _MATERIAL_QUERY:
        return _MATERIAL_QUERY[term]
    if facet == "color":
        return [f"{term} 코디", f"{term} 옷"]
    if facet == "brand":
        # 브랜드명이 자동차·음식·인물과 겹쳐도 단어별 blacklist를 늘리지 않는다.
        # 검색 질의 자체에 패션 의도를 넣고, 아래 결과 문맥 gate도 함께 통과시킨다.
        return [f"{term} 패션", f"{term} 옷"]
    return [term]


def _needs_context(term: str, facet: str) -> bool:
    return term in _TPO_QUERY or term in _MATERIAL_QUERY or facet in ("color", "brand")


def _context_relevant(body: str, term: str, facet: str) -> bool:
    if term in _MATERIAL_QUERY:
        return bool(_GARMENT_CONTEXT.search(body))
    if facet == "brand":
        # API가 검색어와 느슨하게 연결한 문서를 줄 수 있으므로 브랜드 표기와
        # 패션 문맥이 같은 제목+요약 안에 함께 있어야 한다.
        return _norm(term) in _norm(body) and bool(_FASHION_CONTEXT.search(body))
    return bool(_FASHION_CONTEXT.search(body))


def _is_listing(text: str) -> bool:
    """여론이 아니라 판매 게시물인 흔적이 두 개 이상이면 제외한다."""
    return len(_LISTING_MARKS.findall(text)) >= 2


def install(store):
    with store._lock:
        store._conn.executescript(DDL)
        store._conn.commit()


def terms_from_lexicon(path="config/lexicon.yaml", limit: int = 0,
                       store=None) -> list[str]:
    """트렌드로 볼 어휘.

    통합 사전의 브랜드 행에는 라이선스·콜라보나 동명이 업종도 들어온다.
    특정 상호를 blacklist하지 않고, 현재 커머스 상품에서 실제 brand_name으로
    관측된 브랜드만 네이버 수집 대상으로 삼는다. store가 없으면 예전 동작을
    유지해 진단·독립 사용 코드를 깨지 않는다.
    """
    from .lexicon import Lexicon
    lx = Lexicon(path)
    out = [t for t in lx.facet_of if lx.trendable.get(t, True)]
    if store is not None:
        with store._lock:
            observed = {_norm(r[0]) for r in store._conn.execute(
                "SELECT DISTINCT brand_name FROM staging_product "
                "WHERE brand_name IS NOT NULL AND trim(brand_name)<>''")}
        out = [t for t in out if lx.facet_of.get(t) != "brand" or _norm(t) in observed]
    return out[:limit] if limit else out


def _batches(terms: list[str]) -> list[list[str]]:
    """앵커 한 자리를 빼고 나눈다. 한 묶음에 실제 단어는 4개."""
    real = [t for t in terms if t != ANCHOR]
    n = GROUP - 1
    return [real[i:i + n] for i in range(0, len(real), n)]


def collect_trend(store, terms: list[str], *, days: int = 30,
                  on_event=None) -> dict:
    """검색어 트렌드를 받아 저장한다."""
    say = on_event or (lambda *_: None)
    nv = Naver()
    if not nv.ready:
        raise NotConfigured("네이버 Client ID / Secret 이 없습니다")
    install(store)
    facets = _facet_map()

    # ★ 첫 묶음이 터지면 창구부터 다시 가려낸다
    #   31번을 같은 주소로 두들기다 전부 404 로 끝난 적이 있다.
    #   검색이 붙은 문과 트렌드의 문이 다를 수 있으므로, 한 번 실패하면
    #   다른 문을 찾아보고 그 뒤로는 찾은 문으로 부른다.
    redetected = False

    end = datetime.now(UTC).date()
    start = end - timedelta(days=days)
    got = {"terms": 0, "points": 0, "batches": 0, "skipped_days": 0,
           "calls": 0, "failed": 0, "why": ""}

    for chunk in _batches(terms):
        group = [(ANCHOR, [ANCHOR])] + [
            (term, query_keywords(term, facets.get(term, ""))) for term in chunk]
        try:
            res = nv.trend(group, str(start), str(end))
            got["calls"] += 1
        except Exception as exc:
            # ★ except 로 잡은 이름은 블록이 끝나면 파이썬이 지운다.
            #   아래에서 다시 쓰려면 따로 담아 둬야 한다.
            err = exc
            # 첫 실패 때 딱 한 번 창구를 다시 찾아보고 그 묶음을 재시도한다
            if not redetected:
                redetected = True
                det = nv.detect_trend()
                say("info", {"msg": ("트렌드 창구를 다시 찾았습니다: "
                                     + (det.get("name") or det.get("error", ""))[:60])})
                if det.get("ok"):
                    try:
                        from .keystore import _store
                        _store().put("NAVER_TREND_DIALECT", det["dialect"], by="자동")
                    except Exception:
                        pass
                    try:
                        res = nv.trend(group, str(start), str(end))
                        got["calls"] += 1
                        got["batches"] += 1
                        _store_trend(store, res, chunk, got, say)
                        continue
                    except Exception as e2:
                        err = e2
            got["failed"] += 1
            # ★ 조용히 넘어가면 안 된다
            #   31번 전부 실패했는데 화면에는 '0점' 만 떠서, 왜 안 되는지
            #   알 길이 없었다. 첫 실패 이유는 결과에 담아 화면에 띄우고,
            #   기록은 [점검] 탭에 남긴다.
            if not got["why"]:
                got["why"] = str(err)[:300]
            say("warn", {"msg": f"트렌드 실패 ({', '.join(chunk)}): {err}"})
            if PROBLEMS is not None and got["failed"] == 1:
                PROBLEMS.add(title="네이버 검색어 트렌드를 못 받았습니다",
                             source_code="naver", where="수집",
                             detail=f"어휘 {len(chunk)}개: {', '.join(chunk)}",
                             raw=str(err)[:400])
            continue
        got["batches"] += 1
        _store_trend(store, res, chunk, got, say)
        say("info", {"msg": f"트렌드 {len(chunk)}개 · {','.join(chunk)[:36]}"})
    return got


def _store_trend(store, res, chunk, got, say):
    """받아 온 트렌드를 앵커 대비 값으로 바꿔 저장한다."""
    anchor_by_day = {}
    for r in res:
        if r.get("title") == ANCHOR:
            for d in r.get("data") or []:
                anchor_by_day[d["period"]] = float(d.get("ratio") or 0)

    batch_name = ",".join(chunk)
    with store._lock:
        for r in res:
            title = r.get("title")
            if title == ANCHOR:
                continue
            for d in r.get("data") or []:
                day = d["period"]
                ratio = float(d.get("ratio") or 0)
                a = anchor_by_day.get(day)
                # 앵커가 0 이면 나눌 수 없다. 값을 지어내지 않고 비워 둔다.
                scaled = round(ratio / a, 5) if a else None
                if not a:
                    got["skipped_days"] += 1
                store._conn.execute(
                    """INSERT INTO naver_trend
                       (term, observed_on, ratio, anchor, scaled, batch)
                       VALUES (?,?,?,?,?,?)
                       ON CONFLICT(term, observed_on) DO UPDATE SET
                         ratio=excluded.ratio, anchor=excluded.anchor,
                         scaled=excluded.scaled, batch=excluded.batch,
                         collected_at=datetime('now')""",
                    (title, day, ratio, a, scaled, batch_name))
                got["points"] += 1
            got["terms"] += 1
        store._conn.commit()


def _is_ad(text: str) -> bool:
    t = _norm(text)
    return any(k in t for k in _AD)


def collect_text(store, terms: list[str], *, kinds=("blog", "cafearticle"),
                 per_term: int = 30, on_event=None) -> dict:
    """블로그·카페 글을 받아 text_document 로 저장한다.

    ★ 본문이 아니라 '요약'이 온다
      네이버 검색 API 는 title 과 description(200자쯤) 만 준다.
      본문 전체를 받으려면 그 블로그를 직접 긁어야 하는데 그건
      robots 문제로 안 한다. 요약만으로도 긍부정 신호는 충분히 잡힌다.
    """
    say = on_event or (lambda *_: None)
    nv = Naver()
    if not nv.ready:
        raise NotConfigured("네이버 Client ID / Secret 이 없습니다")
    import re

    tag = re.compile(r"<[^>]+>")
    facets = _facet_map()
    got = {"seen": 0, "saved": 0, "ads": 0, "listings": 0,
           "calls": 0, "terms": 0,
           "irrelevant": 0, "failed": 0, "why": ""}

    for term in terms:
        facet = facets.get(term, "")
        query = query_keywords(term, facet)[0]
        for kind in kinds:
            try:
                j = nv.search(query, kind=kind, display=per_term, sort="date")
                got["calls"] += 1
            except Exception as e:
                got["failed"] = got.get("failed", 0) + 1
                if not got.get("why"):
                    got["why"] = str(e)[:300]
                say("warn", {"msg": f"{term}/{kind} 실패: {e}"})
                if PROBLEMS is not None and got["failed"] == 1:
                    PROBLEMS.add(title="네이버 글을 못 받았습니다",
                                 source_code="naver", where="수집",
                                 detail=f"{term} / {kind}", raw=str(e)[:400])
                continue
            items = j.get("items") or []
            got["seen"] += len(items)
            for it in items:
                # <b>강조</b> 태그가 섞여 온다. 분석 전에 걷어낸다.
                title = tag.sub("", it.get("title") or "")
                desc = tag.sub("", it.get("description") or "")
                body = f"{title}. {desc}".strip()
                if not body or len(body) < 10:
                    continue
                if _is_ad(body):
                    got["ads"] += 1
                    continue
                if _is_listing(body):
                    got["listings"] += 1
                    continue
                if (_needs_context(term, facet)
                        and not _context_relevant(body, term, facet)):
                    got["irrelevant"] += 1
                    continue
                store.put_text(
                    "naver", f"naver_{kind}", body,
                    product_uid=f"kw:{term}",
                    published_at=(it.get("postdate") or "")[:10] or None,
                    author_hash=(it.get("bloggername") or it.get("cafename") or "")[:40])
                got["saved"] += 1
        got["terms"] += 1
        shown = query if query == term else f"{term} → {query}"
        say("info", {"msg": f"'{shown}' · 누적 {got['saved']}건"})
    return got


def summary(store, days: int = 14) -> dict:
    """지금 어떤 말이 뜨고 있나. scaled 기준으로 본다."""
    install(store)
    since = (datetime.now(UTC).date() - timedelta(days=days)).isoformat()
    with store._lock:
        rows = [dict(r) for r in store._conn.execute(
            """SELECT term,
                      avg(scaled) AS avg_scaled,
                      max(observed_on) AS last_day,
                      count(*) AS n
               FROM naver_trend
               WHERE observed_on >= ? AND scaled IS NOT NULL
               GROUP BY term ORDER BY avg_scaled DESC""", (since,))]
        total = store._conn.execute("SELECT count(*) FROM naver_trend").fetchone()[0]
        texts = store._conn.execute(
            "SELECT count(*) FROM text_document WHERE source_code='naver'").fetchone()[0]
    return {"top": rows[:30], "terms": len(rows), "points": total, "texts": texts,
            "anchor": ANCHOR, "days": days}
