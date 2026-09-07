"""리포트 조립 — 숫자는 전부 DB 에서 온다.

★ 여기서 LLM 이 숫자를 쓰지 못하게 하는 것이 핵심이다.
  문장은 자리표시자가 있는 틀이고, 값은 서버가 도구 반환값에서 직접 꽂는다.
  LLM 은 어투만 다듬는다. 그래야 "지어낸 숫자"가 구조적으로 불가능하다.

★ 모든 답에 기준 시각이 붙는다.
  가격·재고는 볼 때마다 달라진다. 언제 기준인지 반드시 적는다 (AGENTS.md §6.2).
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from . import plans, templates
from .config import temp_band, SEARCH_FACETS
from .coverage import assess, direction

KST = timezone(timedelta(hours=9))
SOURCE_KO = {"musinsa": "무신사", "naver": "네이버", "youtube": "유튜브",
             "zigzag": "지그재그", "ably": "에이블리", "kream": "크림",
             "fruitsfamily": "후르츠패밀리", "musinsa_used": "무신사 유즈드"}
FACET_KO = {"style": "스타일", "item": "아이템", "material": "소재", "brand": "브랜드",
            "fit": "핏", "color": "컬러", "detail": "디테일", "tpo": "TPO"}
DOC_KO = {"naver_blog": "블로그", "naver_cafearticle": "카페 글", "yt_comment": "댓글",
          "yt_comment_reply": "답글", "yt_video_context": "영상 설명", "yt_transcript": "자막"}


def _has_batchim(word: str) -> bool:
    if not word:
        return False
    ch = ord(word[-1])
    return 0xAC00 <= ch <= 0xD7A3 and (ch - 0xAC00) % 28 != 0


def _josa(word: str, with_b: str, without_b: str) -> str:
    """받침에 맞는 조사. 은/는 · 과/와 · 이/가 전부 이걸 쓴다.

    돌려 보고 잡았다 — "데님와 가장 자주" 라고 나왔다. 데님은 받침이 있으니 "데님과" 다.
    """
    return with_b if _has_batchim(word) else without_b


def build_term(store, gate, hit: dict, as_of: str) -> dict:
    """term 하나에 대해 우리가 아는 전부를 모은다. 플랜 자르기는 하지 않는다."""
    key = hit["term_key"]
    latest = store.term_latest(key)
    sentiment = store.term_sentiment(key)
    assoc = store.term_assoc(key)
    cov = assess(store, key, as_of, latest, sentiment, len(assoc))

    node = {
        "canonical": hit["canonical"],
        "facet": hit["facet"],
        "facet_name": FACET_KO.get(hit["facet"], hit["facet"]),
        "via": hit.get("via"),
        "coverage": cov.as_dict(),
    }
    if not latest:
        node["available"] = False
        return node

    node["available"] = True
    node["observed_on"] = latest.get("observed_on")
    node["raw_count"] = int(latest.get("raw_count") or 0)
    node["temp"] = int(latest.get("temp") or 0)
    node["temp_band"] = temp_band(latest.get("temp"))
    node["pct_rank"] = latest.get("pct_rank")
    node["level"] = latest.get("level")
    node["momentum"] = latest.get("momentum")
    node["share_pct"] = latest.get("share_pct")

    if cov.can_direction:
        node["direction"] = direction(latest)

    srcs = store.term_sources(key)
    node["sources"] = [{"code": s["source_code"],
                        "name": SOURCE_KO.get(s["source_code"], s["source_code"]),
                        "raw_count": int(s["raw_count"] or 0),
                        "temp": int(s["temp"] or 0),
                        "observed_on": s["observed_on"]} for s in srcs]

    if cov.can_assoc:
        node["associations"] = [{"canonical": a["assoc_canonical"],
                                 "facet": a["assoc_facet"],
                                 "facet_name": FACET_KO.get(a["assoc_facet"], a["assoc_facet"]),
                                 "co_count": a["co_count"],
                                 "lift": a["lift"], "score": a["score_v"],
                                 "is_new": bool(a["is_new"])} for a in assoc]
    if cov.can_sentiment:
        # ★ 건수(pos_count·neg_count·top_*_count)도 함께 담는다.
        #   예전엔 비율(pos_pct)과 유형 이름(top_pos)만 있어 "몇 건" 을 답할 수 없었다 —
        #   '긍부정(신호 유형별 건수)' 질문엔 %가 아니라 건수가 답이다.
        node["sentiment"] = {"index": sentiment.get("index_value"),
                             "n_total": sentiment.get("n_total"),
                             "pos_pct": sentiment.get("pos_pct"),
                             "neg_pct": sentiment.get("neg_pct"),
                             "pos_count": sentiment.get("pos_count"),
                             "neg_count": sentiment.get("neg_count"),
                             "top_pos": sentiment.get("top_pos_intent"),
                             "top_pos_count": sentiment.get("top_pos_count"),
                             "top_neg": sentiment.get("top_neg_intent"),
                             "top_neg_count": sentiment.get("top_neg_count")}

    # 근거는 '원문 통짜'가 아니라 판정에 실제로 쓰인 짧은 대목이다 (store.term_evidence 주석)
    node["evidence"] = [{"source": SOURCE_KO.get(e["source_code"], e["source_code"]),
                         "kind": DOC_KO.get(e["doc_kind"], e["doc_kind"]),
                         "body": e["body"], "at": e["at"],
                         "tone": e.get("sentiment"), "origin": e.get("origin")}
                        for e in store.term_evidence(key)]
    return node


# ── 한 줄 결론 — 틀에 값을 꽂는다. 문장을 생성하지 않는다 ──────────
def headline(node: dict, intent: str) -> str:
    if not node.get("available"):
        return (f"<b>{node['canonical']}</b>{_josa(node['canonical'],'은','는')} "
                f"사전에는 있지만 아직 수집된 언급이 없습니다.")
    c, t, band = node["canonical"], node["temp"], node["temp_band"]
    n = node["raw_count"]
    j = _josa(c, "은", "는")

    if intent == "metric.direction":
        d = node.get("direction")
        if d:
            return (f"<b>{c}</b>{j} <b>{d['label']}</b>입니다. "
                    f"최근 7일 평균이 4주 평균의 {d['ratio']}배입니다.")
        return (f"<b>{c}</b>의 방향은 아직 말할 수 없습니다. "
                f"최근 28일 중 관측이 {node['coverage']['obs28']}일뿐입니다.")

    if intent == "metric.assoc" and node.get("associations"):
        top = " · ".join(a["canonical"] for a in node["associations"][:3])
        gwa = _josa(c, "과", "와")
        return f"<b>{c}</b>{gwa} 가장 자주 같이 나오는 말은 <b>{top}</b>입니다."

    if intent == "metric.sentiment":
        s = node.get("sentiment")
        if s:
            return (f"<b>{c}</b>의 구매의향 지수는 <b>{s['index']}점</b>입니다. "
                    f"표본 {s['n_total']}건 기준입니다.")
        return f"<b>{c}</b>{j} 구매의향을 판단할 문장이 아직 없습니다."

    return (f"<b>{c}</b>의 트렌드 온도는 <b>{t}점 · {band}</b>입니다. "
            f"언급 {n:,}건 기준입니다.")


def compose(store, gate, question: str, intent: str, parsed: dict,
            plan: str = plans.FREE, mode: str = "general") -> dict:
    """최종 응답. 프론트가 그대로 그릴 수 있는 모양."""
    as_of = store.latest_day()
    now = datetime.now(KST).isoformat(timespec="seconds")
    hits = parsed["search"]

    if not hits:
        return {"ok": False, "reason": "NOT_IN_LEXICON", "intent": intent,
                "question": question, "generated_at": now}

    nodes = [build_term(store, gate, h, as_of) for h in hits]
    locked_all: set = set()
    gated = []
    for n in nodes:
        g, locked = plans.apply(plan, n)
        locked_all.update(locked)
        gated.append(g)

    notes = []
    for n in nodes:
        for code, msg in (n["coverage"].get("reasons") or []):
            notes.append({"code": code, "term": n["canonical"], "message": msg})

    if intent == "metric.lifecycle":
        # ★ 수명주기는 아직 계산하지 못한다 (FEEDiT_지표계산_설계서.md 6장) —
        #   로지스틱 곡선을 맞추려면 최소 8~12주치 시계열이 필요하다.
        #   조용히 다른 지표로 대신 답하면 사용자는 그게 수명주기 답인 줄 안다.
        #   못 한다고 먼저 말하고, 지금 보이는 지표만 아래에 덧붙인다.
        notes.insert(0, {
            "code": "LIFECYCLE_PENDING", "term": nodes[0]["canonical"],
            "message": "수명주기(계절 · 착용 예측)는 아직 계산하지 못합니다.\n"
                       "최소 8~12주치 시계열이 쌓여야 예측 곡선을 맞출 수 있습니다.\n"
                       "지금 볼 수 있는 지표만 아래에 보여드립니다.",
        })

    head = headline(nodes[0], intent)
    pending = None
    if mode == "salmal":
        # ★ 살!말?지수는 아직 계산하지 못한다 (설계서 7장).
        #   수명주기 표와 가격 이력이 먼저 필요하다.
        #   조용히 일반 모드 답을 주면 사용자는 그게 '살말 판정'인 줄 안다.
        #   못 한다고 먼저 말하고, 아는 것만 덧붙인다.
        pending = {
            "code": "SALMAL_INDEX_PENDING",
            "message": "살!말?지수는 아직 계산하지 못합니다.\n"
                       "가격 이력과 수명주기 데이터가 더 쌓여야 합니다.",
        }
        head = "아직 <b>살지 말지</b>는 판단하지 못합니다. 지금 아는 것만 알려드립니다 — " + head

    rep = {
        "ok": True,
        "kind": mode,
        "intent": intent,
        "question": question,
        "as_of": {"metric": as_of, "generated_at": now},
        "metric_version": store.version,
        "headline": head,
        "terms": gated,
        "modifiers": parsed.get("modifier", []),
        "notes": notes,
        "locked": sorted(locked_all),
        "plan": plans.normalize(plan),
        "source_note": f"무신사·유튜브 등 수집 소스 통합 · {as_of} 기준",
    }
    if pending:
        rep["pending"] = pending
        rep["notes"] = [{"code": pending["code"], "term": "", "message": pending["message"]}] + rep["notes"]
    up = plans.upsell(sorted(locked_all), plan)
    if up:
        rep["upsell"] = up

    # ── 질문 유형에 맞는 구조를 고른다 ──
    #   블록 목록은 templates.py 의 레지스트리가 정한다. LLM 이 만들지 않는다.
    #   plan 으로 잘린 노드(gated)를 쓴다 — 잠긴 지표는 블록에도 안 들어간다.
    rep["blocks"] = templates.build(intent, gated, rep, as_of)
    return rep


# 등록 요청에 쓸 말을 고를 때 버리는 어절 — 질문의 껍데기다
_ASK_STOP = {"어때", "어떤가", "요즘", "지금", "알려줘", "뭐야", "무엇", "어떻게",
             "트렌드", "온도", "살까", "말까", "사도", "될까", "추천", "좀", "이거",
             "그거", "저거", "지수", "분석", "해줘", "보여줘", "궁금해", "인가요"}


def guess_surface(question: str) -> str:
    """사전에 없는 말 중 무엇을 등록 요청할 것인가.

    질문 전체를 그대로 보내면 관리자가 "코르셋코어 어때?" 를 사전에 넣게 된다.
    껍데기 어절을 걷어내고 가장 긴 것을 고른다. 틀려도 관리자가 고친다 — 비워 두는 것보다 낫다.
    """
    import re as _re
    toks = [t for t in _re.findall(r"[가-힣A-Za-z0-9]+", _nfc_q(question))
            if len(t) >= 2 and t not in _ASK_STOP]
    return max(toks, key=len) if toks else question[:40]


def _nfc_q(s: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFC", str(s or ""))


def not_in_lexicon(gate, store, question: str) -> dict:
    """사전에 없는 말. 실패로 끝내지 않는다 — 가까운 말과 등록 요청을 준다."""
    near = gate.near_candidates(question)
    fallback = not near
    if fallback:
        near = gate.popular(store)
    return {
        "ok": False,
        "reason": "NOT_IN_LEXICON",
        "message": ("사전에 없는 말입니다.\n\n"
                    "FEEDiT 는 스타일 · 소재 · 아이템 · 브랜드 네 가지로만 트렌드를 셉니다.\n"
                    "사전에 없으면 언급량을 셀 수가 없어 답을 만들 수 없습니다."),
        "near_label": "많이 찾는 키워드" if fallback else "혹시 이건가요",
        "near": near,
        "surface_guess": guess_surface(question),
        "action": {"type": "lexicon_request", "label": "등록 요청"},
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
    }
