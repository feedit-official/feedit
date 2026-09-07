"""크롤러 SQLite 읽기 전용 어댑터.

★ 크롤러의 store.py 를 import 하지 않는다.
  `store._conn` · `store._lock` 은 비공개고, 쓰기 경로가 같이 딸려 온다.
  이 서비스는 **읽기만** 한다. 그래서 자기 것을 따로 갖는다.

★ 지표를 계산하지 않는다.
  온도·모멘텀·연관어는 crawler/metrics.py 가 원본이다.
  여기서 다시 계산하면 화면과 챗봇이 다른 숫자를 말한다 (AGENTS.md §6.1).
  여기서 하는 계산은 '읽은 값을 설명하기 위한 파생'뿐이다 — 예: ma7/ma28 배수.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from .config import DB_PATH, METRIC_VERSION


class ReadOnlyStore:
    def __init__(self, path=None, version: str = METRIC_VERSION):
        self.path = str(path or DB_PATH)
        self.version = version
        self._conn: sqlite3.Connection | None = None

    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            # mode=ro — 실수로도 쓸 수 없게 한다
            self._conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True,
                                         check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def q(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn().execute(sql, args)]

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        r = self.conn().execute(sql, args).fetchone()
        return dict(r) if r else None

    def scalar(self, sql: str, args: tuple = ()):
        r = self.conn().execute(sql, args).fetchone()
        return r[0] if r else None

    # ── 기준일 ────────────────────────────────────────────
    def latest_day(self) -> str | None:
        """종합 지표의 최신 관측일. 모든 답변의 '기준 시각'이 여기서 나온다."""
        return self.scalar(
            "SELECT max(observed_on) FROM metric_term_daily "
            "WHERE metric_version=? AND source_code='__all__'", (self.version,))

    # ── 지표에 실제로 적재된 canonical ────────────────────
    def metric_canonicals(self) -> set[str]:
        """접힘 되돌리기(설계서 3.3 4단)의 근거.

        사전이 '코트' 를 '아우터' 로 접는데 지표에는 '코트' 가 따로 있다.
        사용자가 쓴 말이 여기 있으면 접지 않는다.
        """
        return {r["canonical"] for r in self.q(
            "SELECT DISTINCT canonical FROM metric_term_daily WHERE metric_version=?",
            (self.version,))}

    # ── term 하나의 최신 지표 ─────────────────────────────
    def term_latest(self, term_key: str) -> dict | None:
        day = self.scalar(
            "SELECT max(observed_on) FROM metric_term_daily WHERE metric_version=? "
            "AND term_key=? AND source_code='__all__'", (self.version, term_key))
        if not day:
            return None
        return self.one(
            "SELECT * FROM metric_term_daily WHERE metric_version=? AND term_key=? "
            "AND source_code='__all__' AND observed_on=?", (self.version, term_key, day))

    def term_series(self, term_key: str, days: int = 90) -> list[dict]:
        return self.q(
            "SELECT observed_on,raw_count,level,ma7,ma28,momentum,temp,pct_rank "
            "FROM metric_term_daily WHERE metric_version=? AND term_key=? "
            "AND source_code='__all__' ORDER BY observed_on DESC LIMIT ?",
            (self.version, term_key, days))

    def obs_count(self, term_key: str, window_days: int, as_of: str) -> int:
        """as_of 기준 최근 window_days 창 안의 관측일 수."""
        return self.scalar(
            "SELECT count(*) FROM metric_term_daily WHERE metric_version=? "
            "AND term_key=? AND source_code='__all__' "
            f"AND observed_on > date(?, '-{int(window_days)} day')",
            (self.version, term_key, as_of)) or 0

    def term_sources(self, term_key: str) -> list[dict]:
        """소스별 최신 스냅샷.

        수집 주기가 달라 유튜브처럼 하루 늦은 소스가 있다.
        종합 지표 날짜 하나로 맞추면 그런 소스가 화면에서 사라진다 — 각자 최신을 쓴다.
        (crawler/trend_chat.py 가 쓰는 방식과 같다)
        """
        return self.q(
            "WITH latest AS (SELECT source_code, max(observed_on) observed_on "
            " FROM metric_term_daily WHERE metric_version=? AND term_key=? "
            " AND source_code<>'__all__' GROUP BY source_code) "
            "SELECT m.source_code, m.raw_count, m.temp, m.pct_rank, m.share_pct, m.observed_on "
            "FROM metric_term_daily m JOIN latest l "
            "  ON l.source_code=m.source_code AND l.observed_on=m.observed_on "
            "WHERE m.metric_version=? AND m.term_key=? ORDER BY m.raw_count DESC",
            (self.version, term_key, self.version, term_key))

    def term_sentiment(self, term_key: str) -> dict | None:
        day = self.scalar(
            "SELECT max(observed_on) FROM metric_term_sentiment_daily "
            "WHERE metric_version=? AND term_key=?", (self.version, term_key))
        if not day:
            return None
        return self.one(
            "SELECT * FROM metric_term_sentiment_daily WHERE metric_version=? "
            "AND term_key=? AND observed_on=?", (self.version, term_key, day))

    def term_assoc(self, term_key: str, limit: int = 8) -> list[dict]:
        day = self.scalar(
            "SELECT max(observed_on) FROM metric_term_assoc_daily "
            "WHERE metric_version=? AND base_term_key=?", (self.version, term_key))
        if not day:
            return []
        return self.q(
            "SELECT assoc_canonical, assoc_facet, co_count, lift, pmi, score_v, is_new "
            "FROM metric_term_assoc_daily WHERE metric_version=? AND base_term_key=? "
            "AND observed_on=? ORDER BY score_v DESC, co_count DESC LIMIT ?",
            (self.version, term_key, day, limit))

    def term_evidence(self, term_key: str, limit: int = 3) -> list[dict]:
        """근거 스니펫.

        ★ 본문(text_document.body)을 240자로 자르던 방식을 버렸다.
          그 방식은 (1) 말 중간에서 잘리고 (2) 그 말과 상관없는 문장이 딸려오고
          (3) `&lt;아디다스&gt;` 같은 수집 찌꺼기를 그대로 화면에 올렸다.

        1순위 — text_entity_opinion.evidence.
          긍부정 분석이 '이 대목 때문에 이렇게 판정했다' 고 남긴 짧은 span 이다.
          즉 언급량·긍부정에 실제로 영향을 준 문장이고, 이미 그 term 범위로 좁혀져 있다.
          현재 137개 term / 633행에만 있다.
        2순위 — 그게 없는 term 은 본문에서 그 말이 든 문장 하나만 뽑는다.

        어느 쪽이든 textclean 을 통과시켜 엔티티·태그·링크를 씻는다.
        플랫폼별로 하나씩 돌아가며 담아 네이버가 슬롯을 독점하지 않게 한다.
        """
        import json as _json

        from .textclean import sentence_with, snippet

        rows = self.q(
            "SELECT o.evidence, o.sentiment, o.confidence, o.canonical, "
            "  d.source_code, d.doc_kind, COALESCE(d.published_at, d.collected_at) at "
            "FROM text_entity_opinion o JOIN text_document d ON d.id=o.text_document_id "
            "WHERE o.term_key=? AND COALESCE(d.quality_status,'active')='active' "
            "  AND o.evidence IS NOT NULL AND o.evidence NOT IN ('', '[]') "
            "ORDER BY o.confidence DESC, at DESC LIMIT 40", (term_key,))

        out: list[dict] = []
        seen: set[str] = set()
        for r in rows:
            try:
                spans = _json.loads(r["evidence"])
            except Exception:
                spans = [r["evidence"]]
            if not isinstance(spans, list):
                spans = [spans]
            for sp in spans:
                body = snippet(sp)
                if len(body) < 6 or body in seen:
                    continue
                seen.add(body)
                out.append({"source_code": r["source_code"], "doc_kind": r["doc_kind"],
                            "body": body, "at": r["at"], "sentiment": r["sentiment"],
                            "origin": "opinion"})
                break            # 문서 하나당 한 마디만 — 같은 글이 화면을 채우지 않게
        if out:
            return self._spread(out, limit)

        # 2순위 — opinion 이 없는 term.
        # ★ 그 말이 실제로 든 문장만 쓴다. 없으면 아무것도 내지 않는다.
        #   'material:다운' 이 '아름다운' 에 걸린 것 같은 사전 오탐을 근거랍시고
        #   올리면, 틀린 숫자보다 더 나쁘다.
        raw = self.q(
            "SELECT t.source_code, t.doc_kind, t.body, m.surface, "
            "  COALESCE(t.published_at, t.collected_at) at "
            "FROM text_entity_mention m JOIN text_document t ON t.id=m.text_document_id "
            "WHERE m.term_key=? AND m.status='confirmed' "
            "  AND COALESCE(t.quality_status,'active')='active' "
            "GROUP BY t.id ORDER BY at DESC LIMIT 60", (term_key,))
        for r in raw:
            surface = (r["surface"] or "").strip()
            if len(surface) < 2:
                continue
            body = sentence_with(r["body"], surface)
            if len(body) < 10 or surface not in body or body in seen:
                continue
            seen.add(body)
            out.append({"source_code": r["source_code"], "doc_kind": r["doc_kind"],
                        "body": body, "at": r["at"], "sentiment": None,
                        "origin": "body"})
        return self._spread(out, limit)

    @staticmethod
    def _spread(rows: list[dict], limit: int) -> list[dict]:
        """플랫폼을 번갈아 담는다. 수집량이 많은 곳이 근거를 독점하면 편향으로 읽힌다."""
        buckets: dict[str, list[dict]] = {}
        for r in rows:
            buckets.setdefault(r["source_code"], []).append(r)
        out: list[dict] = []
        while len(out) < limit and any(buckets.values()):
            for k in list(buckets):
                if buckets[k]:
                    out.append(buckets[k].pop(0))
                    if len(out) >= limit:
                        break
        return out

    def top_terms(self, facet: str | None = None, limit: int = 10) -> list[dict]:
        day = self.latest_day()
        if not day:
            return []
        if facet:
            return self.q(
                "SELECT canonical,facet,raw_count,temp,pct_rank FROM metric_term_daily "
                "WHERE metric_version=? AND observed_on=? AND source_code='__all__' AND facet=? "
                "ORDER BY temp DESC, raw_count DESC LIMIT ?", (self.version, day, facet, limit))
        return self.q(
            "SELECT canonical,facet,raw_count,temp,pct_rank FROM metric_term_daily "
            "WHERE metric_version=? AND observed_on=? AND source_code='__all__' "
            "ORDER BY temp DESC, raw_count DESC LIMIT ?", (self.version, day, limit))
