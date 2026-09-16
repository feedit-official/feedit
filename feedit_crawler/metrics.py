"""FEEDiT L2 formulas from FEEDiT_지표계산_설계서"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from math import exp, log, log2
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import json

METRIC_VERSION = "feedit-l2-v1"
SOURCE_WEIGHTS = {"musinsa": .30, "naver": .30, "youtube": .25, "zigzag": .15}
SHADOW_VERSION = "feedit-l2-v2-shadow"
SHADOW_SOURCE_WEIGHTS = {
    "musinsa": .25, "naver": .20, "youtube": .25, "zigzag": .12,
    "ably": .08, "kream": .07, "musinsa_used": .03,
}
INTENT_WEIGHTS = {
    "buy_done": 1.0, "restock": .8, "considering": .5,
    "price_pain": -.6, "disappoint": -.9, "returned": -1.0,
}


def percentile_ranks(values: Mapping[str, float]) -> dict[str, float]:
    """Return 0..100 ranks with averaged ties; one observation receives 100."""
    if not values:
        return {}
    ordered = sorted((float(value), key) for key, value in values.items())
    if len(ordered) == 1:
        return {ordered[0][1]: 100.0}
    result: dict[str, float] = {}
    i = 0
    while i < len(ordered):
        j = i + 1
        while j < len(ordered) and ordered[j][0] == ordered[i][0]:
            j += 1
        rank = 100.0 * ((i + j - 1) / 2) / (len(ordered) - 1)
        for _, key in ordered[i:j]:
            result[key] = rank
        i = j
    return result


def log_compress(raw_count: int | float) -> float:
    return log(1.0 + max(0.0, float(raw_count)))


def weighted_level(source_percentiles: Mapping[str, float],
                   weights: Mapping[str, float] = SOURCE_WEIGHTS) -> float:
    """Missing sources are zero; renormalizing would change the designed scale."""
    value = sum(float(weights.get(source, 0)) * float(percentile)
                for source, percentile in source_percentiles.items())
    return max(0.0, min(100.0, value))


def momentum(ma7: float, ma28: float) -> float:
    if ma28 <= 0:
        return 50.0 if ma7 <= 0 else 100.0
    return 100.0 / (1.0 + exp(-6.0 * (float(ma7) / float(ma28) - 1.0)))


def trend_temperature(level: float, momentum_value: float) -> int:
    return max(0, min(100, round(.6 * level + .4 * momentum_value)))


def association(n_documents: int, base_documents: int, assoc_documents: int,
                co_documents: int) -> tuple[float, float]:
    """Return lift and base-2 PMI from distinct-document counts."""
    if min(n_documents, base_documents, assoc_documents, co_documents) <= 0:
        return 0.0, 0.0
    lift = (co_documents / base_documents) / (assoc_documents / n_documents)
    return lift, log2(lift)


def association_is_candidate(co_count: int, lift: float) -> bool:
    return co_count >= 20 and lift >= 1.3


def purchase_intent_index(counts: Mapping[str, int], shrinkage: int = 100) -> dict:
    """Designed purchase intent, intentionally distinct from generic sentiment."""
    known = {key: max(0, int(counts.get(key, 0))) for key in INTENT_WEIGHTS}
    total = sum(known.values())
    weighted_sum = sum(INTENT_WEIGHTS[key] * count for key, count in known.items())
    raw_score = weighted_sum / total if total else 0.0
    shrunk = raw_score * total / (total + shrinkage) if total else 0.0
    positive = sum(known[key] for key in ("buy_done", "restock", "considering"))
    negative = total - positive
    return {
        "n_total": total, "weighted_sum": weighted_sum,
        "index_value": max(0, min(100, round(50 + 50 * shrunk))),
        "pos_count": positive, "neg_count": negative,
        "pos_pct": 100.0 * positive / total if total else 0.0,
        "neg_pct": 100.0 * negative / total if total else 0.0,
    }


def moving_average(values: Iterable[float], window: int) -> float:
    tail = list(values)[-window:]
    return sum(tail) / len(tail) if tail else 0.0


def _day(value: str | None) -> date | None:
    raw = str(value or "").strip()[:10]
    try:
        if len(raw) == 8 and raw.isdigit():
            return datetime.strptime(raw, "%Y%m%d").date()
        return date.fromisoformat(raw)
    except ValueError:
        return None


class MetricAggregator:
    """Build versioned L2 snapshots from confirmed entity mentions only."""

    def __init__(self, store, version: str = METRIC_VERSION, *, lexicon=None,
                 weights: Mapping[str, float] | None = None):
        self.store = store
        self.version = version
        self.lexicon = lexicon
        self.weights = dict(weights or (SHADOW_SOURCE_WEIGHTS
                            if version == SHADOW_VERSION else SOURCE_WEIGHTS))

    def rebuild(self) -> dict[str, int]:
        from .entity_linker import RULE_MODEL, RULE_VERSION
        from .llm_analysis import MODEL, PROMPT_VERSION
        with self.store._lock:
            rows = [dict(r) for r in self.store._conn.execute(
                "SELECT m.text_document_id,m.term_key,m.canonical,m.facet,m.mention_role,"
                "t.source_code,t.body,t.published_at,t.collected_at "
                "FROM text_entity_mention m JOIN text_document t ON t.id=m.text_document_id "
                "WHERE m.status='confirmed' AND COALESCE(t.quality_status,'active')='active' "
                "AND (m.model<>? OR m.prompt_version=?)", (RULE_MODEL, RULE_VERSION))]
            llm_rows = [dict(r) for r in self.store._conn.execute(
                "SELECT text_document_id,purchase_intents FROM text_llm_analysis "
                "WHERE prompt_version LIKE 'feedit-text-v2%' ORDER BY analyzed_at")]
            opinion_rows = [dict(r) for r in self.store._conn.execute(
                "SELECT * FROM text_entity_opinion WHERE model=? AND prompt_version=? "
                "AND confidence>=.8 ORDER BY analyzed_at", (MODEL, PROMPT_VERSION))]
        llm_intents = {}
        for row in llm_rows:
            try:
                labels = json.loads(row["purchase_intents"] or "[]")
            except (TypeError, ValueError):
                labels = []
            llm_intents[row["text_document_id"]] = [x for x in labels if x in INTENT_WEIGHTS]
        opinions = defaultdict(dict)
        for row in opinion_rows:
            try:
                labels = json.loads(row.get("purchase_intents") or "[]")
            except (TypeError, ValueError):
                labels = []
            opinions[row["text_document_id"]][row["term_key"]] = [
                x for x in labels if x in INTENT_WEIGHTS]
        docs: dict[int, dict] = {}
        for row in rows:
            observed = _day(row.get("published_at")) or _day(row.get("collected_at"))
            if not observed:
                continue
            doc = docs.setdefault(row["text_document_id"], {
                "day": observed, "source": row["source_code"], "body": row["body"],
                "terms": {}, "targets": set(),
                "llm_intents": llm_intents.get(row["text_document_id"]),
                "opinions": opinions.get(row["text_document_id"], {}),
            })
            key = row["term_key"]
            doc["terms"][key] = (row["canonical"], row["facet"])
            if row["mention_role"] == "target":
                doc["targets"].add(key)
        if self.lexicon is not None and self.version == SHADOW_VERSION:
            docs.update(self._market_documents())
        daily = self._daily(docs)
        assoc = self._associations(docs)
        sentiment = self._sentiment(docs)
        with self.store.tx() as c:
            for table in ("metric_term_daily", "metric_term_assoc_daily",
                          "metric_term_sentiment_daily"):
                c.execute(f"DELETE FROM {table} WHERE metric_version=?", (self.version,))
            c.executemany("INSERT INTO metric_term_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", daily)
            c.executemany("INSERT INTO metric_term_assoc_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", assoc)
            c.executemany("INSERT INTO metric_term_sentiment_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", sentiment)
        return {"documents": len(docs), "daily": len(daily),
                "associations": len(assoc), "sentiments": len(sentiment)}

    def _market_documents(self) -> dict[str, dict]:
        """Product-market activity as source-normalized trend observations.

        Cumulative counters only contribute their non-negative delta after the
        first snapshot. The first observation is a product-presence signal, not
        a claim that all historical purchases happened that day.
        """
        with self.store._lock:
            rows = [dict(r) for r in self.store._conn.execute(
                "SELECT s.*,p.name,p.brand_name,p.category_path,p.site_tags FROM product_stat s "
                "JOIN staging_product p ON p.source_code=s.source_code "
                "AND p.source_uid=s.source_uid WHERE s.source_code IN "
                "('musinsa','zigzag','ably','kream','musinsa_used') "
                "ORDER BY s.source_code,s.source_uid,s.stat_date")]
        previous = {}
        output = {}
        for row in rows:
            tags = row.get("site_tags") or "[]"
            try:
                tags = json.loads(tags) if isinstance(tags, str) else tags
            except (TypeError, ValueError):
                tags = []
            hits = self.lexicon.tag(name=row.get("name") or "", tags=tags or (),
                                    category=row.get("category_path") or "")["hits"]
            # 상품명 부분문자열 브랜드는 금지한다. 별도 brand_name 정확 일치만 허용한다.
            terms = {f"{h['facet']}:{h['term']}": (h["term"], h["facet"])
                     for h in hits if h.get("trendable", True) and h["facet"] != "brand"}
            brand = self.lexicon.exact(row.get("brand_name") or "", "brand")
            if brand:
                terms[f"brand:{brand[0]}"] = brand
            if not terms:
                continue
            key = (row["source_code"], row["source_uid"])
            old = previous.get(key)
            signal = 1.0
            if old:
                if row["source_code"] == "ably":
                    signal += log_compress(max(0, (row.get("buy_count") or 0) -
                                                   (old.get("buy_count") or 0)))
                elif row["source_code"] == "kream":
                    signal += log_compress(max(0, (row.get("trade_count") or 0) -
                                                   (old.get("trade_count") or 0)))
                    signal += .25 * log_compress(max(0, (row.get("wish_count") or 0) -
                                                         (old.get("wish_count") or 0)))
                elif row["source_code"] == "zigzag":
                    signal += .5 * log_compress(max(0, (row.get("review_count") or 0) -
                                                        (old.get("review_count") or 0)))
            previous[key] = row
            observed = _day(row.get("stat_date"))
            if not observed:
                continue
            output[f"market:{row['source_code']}:{row['source_uid']}:{row['stat_date']}"] = {
                "day": observed, "source": row["source_code"], "body": "",
                "terms": terms, "targets": set(), "llm_intents": None,
                "opinions": {},
                "signal": signal, "association": False,
            }
        return output

    def _daily(self, docs: dict[int, dict]) -> list[tuple]:
        counts, source_totals, terms = Counter(), Counter(), {}
        for doc in docs.values():
            unique = doc["terms"]
            signal = float(doc.get("signal", 1.0))
            source_totals[(doc["day"], doc["source"])] += signal
            for key, meta in unique.items():
                terms[key] = meta
                counts[(doc["day"], doc["source"], key)] += signal
        if not counts:
            return []
        days = sorted({x[0] for x in counts})
        sources = sorted({x[1] for x in counts})
        pct = {}
        for day in days:
            for source in sources:
                raw = {key: log_compress(counts[(day, source, key)])
                       for key in terms if counts[(day, source, key)]}
                for key, value in percentile_ranks(raw).items():
                    pct[(day, source, key)] = value
        # 이동평균에서는 관측이 없는 날을 0으로 취급하되, 모든 날짜×모든 용어의
        # 데카르트 곱을 만들거나 DB에 0행을 적재하지 않는다. 장기간 수집 시 이 곱은
        # 실제 신호보다 수백 배 큰 파생 테이블을 만들 수 있다.
        active_day_terms = {(day, key) for day, _source, key in counts}
        levels = {(day, key): weighted_level(
                    {s: pct.get((day, s, key), 0) for s in sources}, self.weights)
                  for day, key in active_day_terms}
        output = []
        for day in days:
            for key, (canonical, facet) in terms.items():
                total_raw = sum(counts[(day, source, key)] for source in sources)
                if total_raw <= 0:
                    continue
                history = [levels.get((day - timedelta(days=n), key), 0)
                           for n in range(27, -1, -1)]
                ma7, ma28 = moving_average(history, 7), moving_average(history, 28)
                mom = momentum(ma7, ma28)
                output.append((key, canonical, facet, "__all__", day.isoformat(), round(total_raw),
                               log_compress(total_raw), None, levels[(day, key)], ma7, ma28,
                               mom, trend_temperature(levels[(day, key)], mom), None, self.version))
                for source in sources:
                    raw = counts[(day, source, key)]
                    if not raw:
                        continue
                    share = 100 * raw / source_totals[(day, source)]
                    output.append((key, canonical, facet, source, day.isoformat(), round(raw),
                                   log_compress(raw), pct[(day, source, key)],
                                   pct[(day, source, key)], None, None, None,
                                   round(pct[(day, source, key)]), share, self.version))
        return output

    def _associations(self, docs: dict[int, dict]) -> list[tuple]:
        if not docs:
            return []
        output = []
        days = sorted({doc["day"] for doc in docs.values()})
        for day in days:
            current = [d for d in docs.values() if d.get("association", True)
                       and day - timedelta(days=6) <= d["day"] <= day]
            previous = [d for d in docs.values() if d.get("association", True)
                        and day - timedelta(days=34) <= d["day"] < day - timedelta(days=6)]
            n = len(current)
            singles, pairs, prior_pairs, terms = Counter(), Counter(), Counter(), {}
            for doc in current:
                keys = sorted(doc["terms"])
                terms.update(doc["terms"])
                singles.update(keys)
                for base in keys:
                    pairs.update((base, other) for other in keys if other != base)
            for doc in previous:
                keys = sorted(doc["terms"])
                for base in keys:
                    prior_pairs.update((base, other) for other in keys if other != base)
            candidates = defaultdict(list)
            for (base, other), co in pairs.items():
                lift, pmi = association(n, singles[base], singles[other], co)
                if association_is_candidate(co, lift):
                    candidates[(base, terms[other][1])].append((other, co, lift, pmi))
            for (base, facet), values in candidates.items():
                ranks = percentile_ranks({other: pmi for other, _, _, pmi in values})
                ordered = sorted(values, key=lambda x: (-ranks[x[0]], -x[1], x[0]))
                for rank, (other, co, lift, pmi) in enumerate(ordered, 1):
                    output.append((base, *terms[base], other, *terms[other], day.isoformat(),
                                   co, lift, pmi, round(ranks[other]), rank,
                                   int(prior_pairs[(base, other)] < 5), self.version))
        return output

    def _sentiment(self, docs: dict[int, dict]) -> list[tuple]:
        from .intent import classify
        grouped = defaultdict(Counter)
        terms = {}
        for doc in docs.values():
            if doc.get("opinions"):
                for key, labels in doc["opinions"].items():
                    if key in doc["terms"]:
                        terms[key] = doc["terms"][key]
                        grouped[(doc["day"], key)].update(labels)
                continue
            # 한 문서가 여러 대상을 말하면 어느 대상의 구매의도인지 알 수 없다.
            # 억지 배분하지 않고 제외하며, 단일 target만 안전하게 집계한다.
            if len(doc["targets"]) != 1:
                continue
            labels = (doc["llm_intents"] if doc["llm_intents"] is not None
                      else classify(doc["body"])["labels"])
            for key in doc["targets"]:
                terms[key] = doc["terms"][key]
                grouped[(doc["day"], key)].update(labels)
        output = []
        pos_keys = ("buy_done", "restock", "considering")
        neg_keys = ("price_pain", "disappoint", "returned")
        for (day, key), counts in grouped.items():
            got = purchase_intent_index(counts)
            if not got["n_total"]:
                continue
            top_pos = max(pos_keys, key=lambda x: counts[x])
            top_neg = max(neg_keys, key=lambda x: counts[x])
            canonical, facet = terms[key]
            output.append((key, canonical, facet, day.isoformat(), got["n_total"],
                           got["weighted_sum"], got["pos_count"], got["neg_count"],
                           got["index_value"], got["pos_pct"], got["neg_pct"],
                           top_pos if counts[top_pos] else None, counts[top_pos] or None,
                           top_neg if counts[top_neg] else None, counts[top_neg] or None,
                           self.version))
        return output
