"""운영 AWS RDS(PostgreSQL)를 챗봇의 기존 읽기 계약으로 바꾼다."""
from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .config import METRIC_VERSION
from .store import at_iso, platform_label


def _plain(value: Any) -> Any:
    """Postgres numeric → 파이썬 숫자.

    ★ psycopg 는 numeric 을 Decimal 로 준다 (2026-09-18). 예전 SQLite 는 float 였다.
      Decimal 은 json.dumps 가 못 읽어 리포트를 화면에 보내다 TypeError 로 죽었고,
      float 와 곱하면 그 자리에서 TypeError 가 난다. 읽는 순간 바꿔 둔다.
      정수 값은 int 로 — "82.0" 이 답변에 찍히면 verify 가 도구 결과와 대조하지 못한다.
    """
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _term(term_key: str) -> str:
    return str(term_key or "").split(":", 1)[-1]


class RDSStore:
    def __init__(self, version: str = METRIC_VERSION):
        self.version = version
        self._conn = None

    def conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(
                host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT", "5432"),
                dbname=os.getenv("DB_NAME"), user=os.getenv("DB_USER"),
                password=os.getenv("DB_PASSWORD"), row_factory=dict_row,
                autocommit=True, connect_timeout=6,
                options="-c statement_timeout=8000",
            )
        return self._conn

    def q(self, sql: str, args=()) -> list[dict[str, Any]]:
        with self.conn().cursor() as cursor:
            cursor.execute(sql, args)
            return [{k: _plain(v) for k, v in row.items()} for row in cursor.fetchall()]

    def one(self, sql: str, args=()) -> dict | None:
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def scalar(self, sql: str, args=()):
        row = self.one(sql, args)
        return next(iter(row.values())) if row else None

    def latest_day(self) -> str | None:
        value = self.scalar(
            "SELECT max(metric_date) d FROM analysis.term_metric_daily "
            "WHERE metric_version=%s AND source_id IS NULL", (self.version,)
        )
        return str(value) if value else None

    def lexicon_entries(self) -> list[dict]:
        return self.q(
            """SELECT t.canonical_name canonical,lower(t.term_type) facet,
                      coalesce(array_agg(a.alias) FILTER (WHERE a.alias IS NOT NULL),
                               ARRAY[]::varchar[]) aliases
                 FROM dictionary.dictionary_term t
                 LEFT JOIN dictionary.term_alias a ON a.term_id=t.id
                WHERE t.status='ACTIVE'
                GROUP BY t.id,t.canonical_name,t.term_type
                UNION ALL
               SELECT b.name,'brand',ARRAY[]::varchar[]
                 FROM dictionary.brand b WHERE b.status='ACTIVE' AND b.name IS NOT NULL"""
        )

    def metric_canonicals(self) -> set[str]:
        return {row["canonical"] for row in self.q(
            """SELECT DISTINCT t.canonical_name canonical
                 FROM analysis.term_metric_daily m
                 JOIN dictionary.dictionary_term t ON t.id=m.term_id
                WHERE m.metric_version=%s""", (self.version,)
        )}

    def metric_facet(self, canonical: str) -> str | None:
        return self.scalar(
            """SELECT lower(t.term_type) facet FROM analysis.term_metric_daily m
                 JOIN dictionary.dictionary_term t ON t.id=m.term_id
                WHERE m.metric_version=%s AND t.canonical_name=%s LIMIT 1""",
            (self.version, canonical),
        )

    def metric_terms_in(self, text: str, limit: int = 3) -> list[dict]:
        rows = self.q(
            """SELECT DISTINCT t.canonical_name canonical,lower(t.term_type) facet
                 FROM analysis.term_metric_daily m
                 JOIN dictionary.dictionary_term t ON t.id=m.term_id
                WHERE m.metric_version=%s""", (self.version,)
        )
        hits = [row for row in rows if row["canonical"] and row["canonical"] in str(text or "")]
        return sorted(hits, key=lambda row: -len(row["canonical"]))[:limit]

    def term_latest(self, term_key: str) -> dict | None:
        return self.one(
            """SELECT m.metric_date::text observed_on,m.raw_count,m.level,m.ma7,m.ma28,m.momentum,
                      m.trend_temperature temp,m.percentile pct_rank,
                      NULL::numeric share_pct
                 FROM analysis.term_metric_daily m
                 JOIN dictionary.dictionary_term t ON t.id=m.term_id
                WHERE m.metric_version=%s AND t.canonical_name=%s AND m.source_id IS NULL
                ORDER BY m.metric_date DESC LIMIT 1""", (self.version, _term(term_key)),
        )

    def term_series(self, term_key: str, days: int = 90) -> list[dict]:
        return self.q(
            """SELECT m.metric_date::text observed_on,m.raw_count,m.level,m.ma7,m.ma28,m.momentum,
                      m.trend_temperature temp,m.percentile pct_rank
                 FROM analysis.term_metric_daily m
                 JOIN dictionary.dictionary_term t ON t.id=m.term_id
                WHERE m.metric_version=%s AND t.canonical_name=%s AND m.source_id IS NULL
                ORDER BY m.metric_date DESC LIMIT %s""",
            (self.version, _term(term_key), max(1, min(int(days), 400))),
        )

    def obs_count(self, term_key: str, window_days: int, as_of: str) -> int:
        return int(self.scalar(
            """SELECT count(*) n FROM analysis.term_metric_daily m
                 JOIN dictionary.dictionary_term t ON t.id=m.term_id
                WHERE m.metric_version=%s AND t.canonical_name=%s AND m.source_id IS NULL
                  AND m.metric_date > %s::date-%s::int""",
            (self.version, _term(term_key), as_of, int(window_days)),
        ) or 0)

    def term_sources(self, term_key: str) -> list[dict]:
        return self.q(
            """SELECT DISTINCT ON (s.id) lower(s.code) source_code,m.raw_count,
                      m.trend_temperature temp,m.percentile pct_rank,NULL::numeric share_pct,
                      m.metric_date::text observed_on
                 FROM analysis.term_metric_daily m
                 JOIN dictionary.dictionary_term t ON t.id=m.term_id
                 JOIN collection.source s ON s.id=m.source_id
                WHERE m.metric_version=%s AND t.canonical_name=%s
                ORDER BY s.id,m.metric_date DESC""", (self.version, _term(term_key)),
        )

    def term_sentiment(self, term_key: str) -> dict | None:
        row = self.one(
            """SELECT m.purchase_intent_index index_value,
                      coalesce(m.positive_count,0)+coalesce(m.negative_count,0)+coalesce(m.neutral_count,0) n_total,
                      m.positive_count pos_count,m.negative_count neg_count,
                      m.positive_rate pos_pct,m.negative_rate neg_pct
                 FROM analysis.term_metric_daily m
                 JOIN dictionary.dictionary_term t ON t.id=m.term_id
                WHERE m.metric_version=%s AND t.canonical_name=%s AND m.source_id IS NULL
                ORDER BY m.metric_date DESC LIMIT 1""", (self.version, _term(term_key)),
        )
        return row if row and int(row.get("n_total") or 0) else None

    def term_assoc(self, term_key: str, limit: int = 8) -> list[dict]:
        return self.q(
            """SELECT target.canonical_name assoc_canonical,lower(target.term_type) assoc_facet,
                      a.cooccurrence_count co_count,a.lift,a.pmi,
                      a.association_percentile score_v,a.is_new
                 FROM analysis.term_assoc_daily a
                 JOIN dictionary.dictionary_term source ON source.id=a.source_term_id
                 JOIN dictionary.dictionary_term target ON target.id=a.target_term_id
                WHERE a.metric_version=%s AND source.canonical_name=%s
                  AND a.metric_date=(SELECT max(x.metric_date) FROM analysis.term_assoc_daily x
                                      WHERE x.source_term_id=a.source_term_id AND x.metric_version=a.metric_version)
                ORDER BY a.association_rank NULLS LAST,a.association_percentile DESC NULLS LAST
                LIMIT %s""", (self.version, _term(term_key), max(1, min(int(limit), 100))),
        )

    def term_evidence(self, term_key: str, limit: int = 3) -> list[dict]:
        from .textclean import sentence_with
        rows = self.q(
            """SELECT lower(s.code) source_code,d.document_type doc_kind,d.body,
                      tm.mention_text surface,tm.sentiment_score sentiment,
                      coalesce(ci.published_at,d.created_at) at,ci.content_url url
                 FROM analysis.text_term_mention tm
                 JOIN analysis.text_document d ON d.id=tm.document_id
                 JOIN dictionary.dictionary_term t ON t.id=tm.term_id
                 JOIN collection.source s ON s.id=d.source_id
                 LEFT JOIN content.content_item ci ON ci.id=d.content_item_id
                WHERE t.canonical_name=%s AND d.body IS NOT NULL
                ORDER BY tm.confidence DESC NULLS LAST,d.created_at DESC LIMIT 60""",
            (_term(term_key),),
        )
        out, seen = [], set()
        for row in rows:
            body = sentence_with(row.get("body") or "", row.get("surface") or _term(term_key))
            if len(body) < 10 or body in seen:
                continue
            seen.add(body)
            out.append({"source_code": row["source_code"], "doc_kind": row["doc_kind"],
                        "body": body, "at": at_iso(row.get("at")),
                        "sentiment": row.get("sentiment"), "origin": "mention",
                        "platform": platform_label(row["source_code"], row["doc_kind"]),
                        "url": row.get("url")})
            if len(out) >= limit:
                break
        return out

    def top_terms(self, facet: str | None = None, limit: int = 10,
                  facets: list[str] | None = None) -> list[dict]:
        where, args = ["m.metric_version=%s", "m.source_id IS NULL"], [self.version]
        if facet:
            where.append("lower(t.term_type)=%s"); args.append(facet.lower())
        elif facets:
            where.append("lower(t.term_type)=ANY(%s)"); args.append([x.lower() for x in facets])
        args.append(max(1, min(int(limit), 100)))
        return self.q(
            """SELECT t.canonical_name canonical,lower(t.term_type) facet,m.raw_count,
                      m.trend_temperature temp,m.percentile pct_rank
                 FROM analysis.term_metric_daily m
                 JOIN dictionary.dictionary_term t ON t.id=m.term_id
                WHERE """ + " AND ".join(where) +
            " AND m.metric_date=(SELECT max(metric_date) FROM analysis.term_metric_daily WHERE metric_version=%s)"
            " ORDER BY m.trend_temperature DESC NULLS LAST,m.raw_count DESC LIMIT %s",
            tuple(args[:-1] + [self.version, args[-1]]),
        )
