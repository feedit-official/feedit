"""수집·정제된 FEEDiT L2 지표를 대화형으로 점검하는 읽기 전용 질의기."""
from __future__ import annotations

import re
import math
import json
from collections import Counter
from pathlib import Path


FACET_KO = {"style": "스타일", "item": "아이템", "material": "소재",
            "brand": "브랜드", "fit": "핏", "detail": "디테일", "tpo": "TPO"}
SOURCE_KO = {"musinsa": "무신사", "naver": "네이버", "youtube": "유튜브",
             "zigzag": "지그재그", "ably": "에이블리", "kream": "크림",
             "fruitsfamily": "후르츠패밀리", "musinsa_used": "무신사 유즈드"}
INTENT_KO = {"buy_done": "구매 완료", "restock": "재입고 대기",
             "considering": "구매 고려", "price_pain": "가격 부담",
             "disappoint": "실망", "returned": "반품"}
DOC_KIND_KO = {"naver_blog": "블로그", "naver_cafearticle": "카페 글",
               "yt_comment": "댓글", "yt_comment_reply": "답글",
               "yt_video_context": "영상 설명", "yt_transcript": "자막"}
CORE_SOURCES = ("musinsa", "zigzag", "ably", "naver", "youtube")
TEXT_SOURCES = ("naver", "youtube")


def temperature_label(value: int | float | None) -> str:
    value = float(value or 0)
    if value < 25:
        return "차가움"
    if value < 50:
        return "미지근"
    if value < 75:
        return "따뜻함"
    return "과열"


def _topic(canonical: str) -> str:
    """받침에 맞는 은/는을 붙인다."""
    text = str(canonical)
    last = ord(text[-1]) if text else 0
    has_batchim = 0xAC00 <= last <= 0xD7A3 and (last - 0xAC00) % 28 != 0
    return text + ("은" if has_batchim else "는")


def _latest(store, table: str, version: str, where: str = "1=1", args=()):
    return store._conn.execute(
        f"SELECT max(observed_on) FROM {table} WHERE metric_version=? AND {where}",
        (version, *args)).fetchone()[0]


def _top_terms(store, version: str, limit: int = 5) -> list[tuple[str, str]]:
    with store._lock:
        day = _latest(store, "metric_term_daily", version, "source_code='__all__'")
        if not day:
            return []
        rows = store._conn.execute(
            "SELECT canonical,facet FROM metric_term_daily WHERE metric_version=? "
            "AND observed_on=? AND source_code='__all__' "
            "ORDER BY temp DESC,raw_count DESC LIMIT ?", (version, day, limit)).fetchall()
    return [(r[0], r[1]) for r in rows]


def _resolve(store, lexicon, question: str, version: str) -> tuple[list[tuple[str, str]], bool]:
    hits = [(canonical, facet) for canonical, facet in lexicon.extract(question, "product")
            if lexicon.trendable.get(canonical, True)]
    hits = list(dict.fromkeys(hits))[:4]
    if hits:
        return hits, False
    # 용어 없는 일반 질문은 현재 상위 후보를 돌려준다.
    general = bool(re.search(r"요즘|지금|최근|뭐가|무엇|전체|상위|트렌드|유행", question))
    return (_top_terms(store, version, 5), True) if general else ([], False)


def _suggestions(store, version: str, question: str, limit: int = 8) -> list[dict]:
    tokens = [x for x in re.findall(r"[가-힣A-Za-z0-9]{2,}", question)
              if x not in {"알려줘", "어때", "어떻게", "트렌드", "분석", "요즘"}]
    with store._lock:
        day = _latest(store, "metric_term_daily", version, "source_code='__all__'")
        if not day:
            return []
        rows = [dict(r) for r in store._conn.execute(
            "SELECT canonical,facet,temp,raw_count FROM metric_term_daily "
            "WHERE metric_version=? AND observed_on=? AND source_code='__all__' "
            "ORDER BY temp DESC,raw_count DESC LIMIT 300", (version, day))]
    if tokens:
        matched = [r for r in rows if any(t.lower() in r["canonical"].lower() or
                                          r["canonical"].lower() in t.lower() for t in tokens)]
        if matched:
            rows = matched
    return rows[:limit]


def _term_result(store, version: str, canonical: str, facet: str) -> dict:
    key = f"{facet}:{canonical}"
    with store._lock:
        trend_day = _latest(store, "metric_term_daily", version,
                            "term_key=? AND source_code='__all__'", (key,))
        trend = None
        sources = []
        if trend_day:
            row = store._conn.execute(
                "SELECT * FROM metric_term_daily WHERE metric_version=? AND observed_on=? "
                "AND term_key=? AND source_code='__all__'", (version, trend_day, key)).fetchone()
            trend = dict(row) if row else None
            # 수집 주기가 다른 플랫폼을 종합 지표 날짜 하나에 맞추면 유튜브처럼
            # 하루 늦은 소스가 화면에서 사라진다. 각 소스의 실제 최신 스냅샷을 쓴다.
            sources = [dict(r) for r in store._conn.execute(
                "WITH latest AS (SELECT source_code,max(observed_on) observed_on "
                "FROM metric_term_daily WHERE metric_version=? AND term_key=? "
                "AND source_code<>'__all__' GROUP BY source_code) "
                "SELECT m.source_code,m.raw_count,m.pct_rank,m.temp,m.share_pct,m.observed_on,"
                "CAST(julianday(?) - julianday(m.observed_on) AS INTEGER) lag_days "
                "FROM metric_term_daily m JOIN latest l ON l.source_code=m.source_code "
                "AND l.observed_on=m.observed_on WHERE m.metric_version=? AND m.term_key=? "
                "ORDER BY m.raw_count DESC",
                (version, key, trend_day, version, key)).fetchall()]
        sentiment_day = _latest(store, "metric_term_sentiment_daily", version,
                                "term_key=?", (key,))
        sentiment = None
        if sentiment_day:
            row = store._conn.execute(
                "SELECT * FROM metric_term_sentiment_daily WHERE metric_version=? "
                "AND observed_on=? AND term_key=?", (version, sentiment_day, key)).fetchone()
            sentiment = dict(row) if row else None
        association_day = _latest(store, "metric_term_assoc_daily", version,
                                  "base_term_key=?", (key,))
        associations = []
        association_count = 0
        if association_day:
            associations = [dict(r) for r in store._conn.execute(
                "SELECT assoc_canonical,assoc_facet,co_count,lift,pmi,score_v,is_new "
                "FROM metric_term_assoc_daily WHERE metric_version=? AND observed_on=? "
                "AND base_term_key=? ORDER BY score_v DESC,co_count DESC LIMIT 8",
                (version, association_day, key)).fetchall()]
            association_count = store._conn.execute(
                "SELECT count(*) FROM metric_term_assoc_daily WHERE metric_version=? "
                "AND observed_on=? AND base_term_key=?",
                (version, association_day, key)).fetchone()[0]
        # 플랫폼별 최대 3건을 뽑아 네이버 수집량이 근거 슬롯을 독점하지 않게 한다.
        evidence = [dict(r) for r in store._conn.execute(
            "WITH candidates AS (SELECT t.id,t.source_code,t.doc_kind,"
            "substr(replace(t.body,char(10),' '),1,260) body,t.published_at,t.collected_at,"
            "row_number() OVER (PARTITION BY t.source_code ORDER BY "
            "COALESCE(t.published_at,t.collected_at) DESC,t.id DESC) rn "
            "FROM text_entity_mention m JOIN text_document t ON t.id=m.text_document_id "
            "WHERE m.term_key=? AND m.status='confirmed' "
            "AND COALESCE(t.quality_status,'active')='active' GROUP BY t.id) "
            "SELECT source_code,doc_kind,body,published_at,collected_at FROM candidates "
            "WHERE rn<=3 ORDER BY CASE source_code WHEN 'youtube' THEN 0 WHEN 'naver' THEN 1 ELSE 2 END,rn",
            (key,)).fetchall()]
        evidence_summary = [dict(r) for r in store._conn.execute(
            "SELECT t.source_code,count(DISTINCT t.id) linked_count,max(t.collected_at) last_collected_at "
            "FROM text_entity_mention m JOIN text_document t ON t.id=m.text_document_id "
            "WHERE m.term_key=? AND m.status='confirmed' "
            "AND COALESCE(t.quality_status,'active')='active' GROUP BY t.source_code "
            "ORDER BY linked_count DESC", (key,)).fetchall()]
    for row in sources:
        row["source_name"] = SOURCE_KO.get(row["source_code"], row["source_code"])
    for row in evidence:
        row["source_name"] = SOURCE_KO.get(row["source_code"], row["source_code"])
        row["doc_kind_name"] = DOC_KIND_KO.get(row["doc_kind"], row["doc_kind"])
    for row in evidence_summary:
        row["source_name"] = SOURCE_KO.get(row["source_code"], row["source_code"])
    warnings = []
    if not trend:
        warnings.append("계산된 언급량·온도 지표가 없습니다.")
    elif int(trend.get("raw_count") or 0) < 20:
        warnings.append("최신 언급 표본이 20건 미만이라 온도 변동성이 큽니다.")
    if not sentiment:
        warnings.append("대상별 구매의향 근거가 아직 없습니다.")
    elif int(sentiment.get("n_total") or 0) < 20:
        warnings.append("구매의향 표본이 20건 미만이라 중립값 쪽으로 보정됩니다.")
    if not evidence:
        warnings.append("연결된 텍스트 근거 문서가 없어 플랫폼 수집 신호만 표시합니다.")
    stale = [x["source_name"] for x in sources if int(x.get("lag_days") or 0) > 0]
    if stale:
        warnings.append("종합 지표보다 최신 스냅샷이 오래된 소스: " + ", ".join(stale))
    source_map = {x["source_code"]: x for x in sources}
    evidence_map = {x["source_code"]: x for x in evidence_summary}
    missing_sources = [SOURCE_KO[x] for x in CORE_SOURCES if x not in source_map]
    missing_text_sources = [SOURCE_KO[x] for x in TEXT_SOURCES if x not in evidence_map]
    missing_components = []
    if not trend:
        missing_components.append("언급량·온도")
    if not association_count:
        missing_components.append("연관어")
    if not sentiment or not int(sentiment.get("n_total") or 0):
        missing_components.append("긍부정·구매의향")
    if not evidence_summary:
        missing_components.append("원문 근거")
    quality = {
        "component_total": 4,
        "component_available": 4 - len(missing_components),
        "missing_components": missing_components,
        "platform_expected": len(CORE_SOURCES),
        "platform_available": sum(1 for x in CORE_SOURCES if x in source_map),
        "missing_platforms": missing_sources,
        "platform_signal_count": sum(int(source_map[x].get("raw_count") or 0)
                                     for x in CORE_SOURCES if x in source_map),
        "association_count": int(association_count),
        "sentiment_sample_count": int(sentiment.get("n_total") or 0) if sentiment else 0,
        "evidence_count": sum(int(x.get("linked_count") or 0) for x in evidence_summary),
        "text_platform_expected": len(TEXT_SOURCES),
        "text_platform_available": sum(1 for x in TEXT_SOURCES if x in evidence_map),
        "missing_text_platforms": missing_text_sources,
    }
    return {"term_key": key, "canonical": canonical, "facet": facet,
            "facet_name": FACET_KO.get(facet, facet), "trend": trend,
            "temperature_label": temperature_label(trend.get("temp") if trend else 0),
            "sources": sources, "sentiment": sentiment,
            "associations": associations, "evidence": evidence,
            "evidence_summary": evidence_summary, "data_quality": quality,
            "warnings": warnings}


def demo_targets(store, version: str, limit: int = 10) -> dict:
    """5개 핵심 플랫폼의 공통 신호와 L2 완성도를 기준으로 데모 후보를 고른다."""
    placeholders = ",".join("?" for _ in CORE_SOURCES)
    with store._lock:
        rows = [dict(r) for r in store._conn.execute(
            f"WITH latest AS (SELECT term_key,source_code,max(observed_on) day "
            f"FROM metric_term_daily WHERE metric_version=? AND source_code IN ({placeholders}) "
            "GROUP BY term_key,source_code), signals AS (SELECT m.term_key,max(m.canonical) canonical,"
            "max(m.facet) facet,count(*) platform_count,sum(m.raw_count) signal_count,"
            "min(m.raw_count) weakest_signal FROM metric_term_daily m JOIN latest l "
            "ON l.term_key=m.term_key AND l.source_code=m.source_code AND l.day=m.observed_on "
            "WHERE m.metric_version=? GROUP BY m.term_key), sentiment_days AS ("
            "SELECT term_key,max(observed_on) day FROM metric_term_sentiment_daily "
            "WHERE metric_version=? GROUP BY term_key), sentiments AS ("
            "SELECT n.term_key,n.n_total sentiment_count FROM metric_term_sentiment_daily n "
            "JOIN sentiment_days d ON d.term_key=n.term_key AND d.day=n.observed_on "
            "WHERE n.metric_version=?), association_days AS ("
            "SELECT base_term_key,max(observed_on) day FROM metric_term_assoc_daily "
            "WHERE metric_version=? GROUP BY base_term_key), associations AS ("
            "SELECT a.base_term_key term_key,count(*) association_count FROM metric_term_assoc_daily a "
            "JOIN association_days d ON d.base_term_key=a.base_term_key AND d.day=a.observed_on "
            "WHERE a.metric_version=? GROUP BY a.base_term_key) SELECT s.*,"
            "coalesce(n.sentiment_count,0) sentiment_count,"
            "coalesce(a.association_count,0) association_count FROM signals s "
            "LEFT JOIN sentiments n USING(term_key) LEFT JOIN associations a USING(term_key) "
            "WHERE s.platform_count>=2",
            (version, *CORE_SOURCES, version, version, version, version, version,
             )).fetchall()]
    for row in rows:
        volume = min(1.0, math.log1p(row["signal_count"]) / math.log1p(3000))
        balance = min(1.0, row["weakest_signal"] / 5)
        sentiment = min(1.0, row["sentiment_count"] / 30)
        association = min(1.0, row["association_count"] / 20)
        coverage = row["platform_count"] / len(CORE_SOURCES)
        row["readiness_score"] = round(40 * coverage + 20 * volume + 10 * balance +
                                         15 * sentiment + 15 * association)
        row["facet_name"] = FACET_KO.get(row["facet"], row["facet"])
    rows.sort(key=lambda x: (-x["readiness_score"], -x["sentiment_count"],
                             -x["association_count"], -x["signal_count"], x["term_key"]))
    requested = max(1, min(int(limit), 30))
    ranked = rows[:requested]
    locked_path = Path(__file__).resolve().parent.parent / "config" / "demo_targets.json"
    locked_keys = []
    try:
        locked = json.loads(locked_path.read_text(encoding="utf-8"))
        locked_keys = [f"{x['facet']}:{x['canonical']}" for x in locked.get("targets", [])]
    except (OSError, ValueError, KeyError, TypeError):
        locked = {}
    by_key = {x["term_key"]: x for x in rows}
    selected = [by_key[x] for x in locked_keys if x in by_key][:requested] or ranked
    return {"targets": selected, "recommended_targets": ranked, "core_sources": [
        {"code": x, "name": SOURCE_KO[x]} for x in CORE_SOURCES],
        "rule": "검색축별 2~3개 배분 + 플랫폼 커버리지·신호량·구매의향 표본·연관어 완성도",
        "target_version": locked.get("version") if isinstance(locked, dict) else None,
        "candidate_count": len(rows)}


def _narrative(results: list[dict], overview: bool) -> str:
    if not results:
        return "질문에서 사전에 등록된 패션 용어를 찾지 못했습니다. 아래 후보를 눌러 다시 질문해 보세요."
    parts = []
    for item in results:
        trend, sentiment = item["trend"], item["sentiment"]
        if not trend:
            parts.append(f"{_topic(item['canonical'])} 아직 계산된 트렌드 지표가 없습니다.")
            continue
        sentence = (f"{_topic(item['canonical'])} 최신 온도 {trend['temp']}점({item['temperature_label']})이고 "
                    f"언급 {int(trend['raw_count'] or 0):,}건, 모멘텀 {float(trend['momentum'] or 0):.1f}입니다.")
        if sentiment:
            sentence += (f" 구매의향은 {sentiment['index_value']}점이며 "
                         f"표본 {int(sentiment['n_total'] or 0):,}건입니다.")
        if item["associations"]:
            sentence += " 주요 연관어는 " + ", ".join(
                x["assoc_canonical"] for x in item["associations"][:3]) + "입니다."
        parts.append(sentence)
    prefix = "현재 상위 후보를 보면 " if overview else "현재 적재 데이터 기준으로 "
    return prefix + " ".join(parts)


def answer(store, lexicon, question: str, version: str) -> dict:
    question = re.sub(r"\s+", " ", str(question or "")).strip()
    if not question:
        raise ValueError("질문을 입력해 주세요.")
    if len(question) > 500:
        raise ValueError("질문은 500자 이하로 입력해 주세요.")
    terms, overview = _resolve(store, lexicon, question, version)
    results = [_term_result(store, version, canonical, facet)
               for canonical, facet in terms]
    # 사전에는 있지만 아직 지표가 전혀 없는 항목도 그대로 보여 줘 데이터 공백을 드러낸다.
    suggestions = [] if results else _suggestions(store, version, question)
    source_counts = Counter(source["source_code"] for result in results
                            for source in result["sources"])
    return {"question": question, "answer": _narrative(results, overview),
            "overview": overview, "results": results, "suggestions": suggestions,
            "metric_version": version, "matched_terms": len(results),
            "source_coverage": dict(source_counts),
            "notice": "LLM 생성문이 아니라 현재 DB 지표와 근거 문서를 조합한 읽기 전용 결과입니다."}
