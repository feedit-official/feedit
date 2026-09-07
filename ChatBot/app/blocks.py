"""응답을 '블록'으로 만든다 — 질문 유형마다 구조가 달라지게.

왜 프롬프트만으로 안 하나
  1. 화면이 깨진다. LLM 이 없는 CSS 클래스를 지어내면 버튼이 맨 글자로 나온다.
     (AGENTS.md §4.2 가 적어 둔 실제 사고다)
  2. 매번 다르게 나온다. 같은 질문에 어제와 오늘의 구조가 다르면 그건 제품이 아니다.
  3. 숫자가 샌다. 구조를 LLM 이 만들면 그 안의 값도 LLM 이 쓰게 된다.

그래서 구조는 **서버가 정한 목록에서 고른다.**
  · 어떤 블록이 있는지는 여기(blocks.py)가 정한다 — 프론트에 실제로 있는 것만.
  · 의도마다 어떤 블록을 쓸지는 templates.py 가 정한다.
  · LLM 은 애매할 때 **후보 중에서 고르는 것**만 한다. 새로 만들지 못한다.

슬롯 세 개
  full   카드 위 전체 폭 (판정 다이얼 같은 것)
  left   카드 왼쪽 (넓다 · 1.15fr)
  right  카드 오른쪽 (1fr)
"""
from __future__ import annotations

from .config import temp_band

FACET_KO = {"style": "스타일", "item": "아이템", "material": "소재", "brand": "브랜드",
            "fit": "핏", "color": "컬러", "detail": "디테일", "tpo": "TPO"}


# ── 개별 블록 ─────────────────────────────────────────
TONE_KO = {"positive": "긍정", "negative": "부정", "mixed": "엇갈림", "neutral": None}
# metric_term_sentiment_daily.top_pos_intent / top_neg_intent 원본 값 — 화면엔 한글로만 낸다.
INTENT_KO = {"buy_done": "구매완료", "considering": "구매고민", "disappoint": "실망",
             "price_pain": "가격불만", "restock": "재입고요청", "returned": "반품"}

def b_metric_rank(t: dict, as_of: str) -> dict | None:
    """지표를 행으로. 가장 기본이 되는 블록."""
    if not t.get("available"):
        return {"type": "rank", "slot": "left", "title": t["canonical"],
                "meta": (t.get("facet_name") or "") + " · " + as_of,
                "rows": [{"k": "아직 수집된 언급이 없습니다", "small": "사전에는 있습니다",
                          "v": "0건", "up": False}]}
    rows = []
    if t.get("temp") is not None:
        rows.append({"k": "트렌드 온도", "small": t.get("temp_band"),
                     "v": f"{t['temp']}점", "up": t["temp"] >= 50})
    if t.get("raw_count") is not None:
        rows.append({"k": "언급량",
                     "small": f"{len(t.get('sources') or [])}개 소스" if t.get("sources") else "",
                     "v": f"{int(t['raw_count']):,}건", "up": int(t["raw_count"]) >= 20})
    if t.get("pct_rank") is not None:
        rows.append({"k": "순위", "small": "전체 대비",
                     "v": f"상위 {100 - round(float(t['pct_rank']))}%",
                     "up": float(t["pct_rank"]) >= 50})
    return {"type": "rank", "slot": "left", "title": t["canonical"],
            "meta": (t.get("facet_name") or "") + " · " + as_of, "rows": rows}


def b_direction(t: dict) -> dict | None:
    """방향만 크게. '꺾였어?' 에는 온도보다 이게 답이다."""
    d = t.get("direction")
    if not d:
        cov = t.get("coverage") or {}
        return {"type": "note", "slot": "left",
                "text": f"최근 28일 중 관측이 {cov.get('obs28', 0)}일뿐이라 "
                        f"오르는지 내리는지 말할 수 없습니다."}
    return {"type": "kpis", "slot": "full", "items": [
        {"k": "방향", "v": d["label"], "unit": "", "note": "최근 7일 대 4주", "up": d["tone"] == "up"},
        {"k": "7일 / 4주", "v": f"{d['ratio']}", "unit": "배", "note": "1보다 크면 오르는 중",
         "up": d["ratio"] >= 1},
        {"k": "7일 평균", "v": f"{d['ma7']}", "unit": "", "note": "", "up": True},
        {"k": "4주 평균", "v": f"{d['ma28']}", "unit": "", "note": "", "up": True},
    ]}


def b_sources(t: dict, as_of: str) -> dict | None:
    src = t.get("sources") or []
    if not src:
        return None
    mx = max((s.get("raw_count") or 0) for s in src) or 1
    return {"type": "bars", "slot": "right", "title": "플랫폼별 언급량", "meta": as_of,
            "items": [{"k": s["name"], "w": round(100 * (s.get("raw_count") or 0) / mx),
                       "v": f"{int(s.get('raw_count') or 0):,}"} for s in src]}


def b_platform_temp(t: dict, as_of: str) -> dict | None:
    """플랫폼별 '온도'. 언급량 막대와 다른 질문에 답한다 —
       '어디서 많이 나오나' 가 아니라 '어디가 더 뜨거운가'."""
    src = [s for s in (t.get("sources") or []) if s.get("temp") is not None]
    if not src:
        return None
    return {"type": "table", "slot": "right", "title": "플랫폼별 온도", "meta": "0–100",
            "head": ["플랫폼", "", "온도"],
            "rows": [{"k": s["name"], "w": int(s["temp"]), "v": f"{int(s['temp'])}°",
                      "up": int(s["temp"]) >= 65} for s in src]}


def b_assoc(t: dict) -> dict | None:
    a = t.get("associations") or []
    if not a:
        return None
    return {"type": "rank", "slot": "left", "title": "같이 언급되는 말",
            "meta": f"{len(a)}개",
            "rows": [{"k": x["canonical"],
                      "small": x.get("facet_name", "") + (" · NEW" if x.get("is_new") else ""),
                      "v": f"{int(x['co_count']):,}회", "up": True} for x in a[:6]]}


def b_assoc_axis(t: dict) -> dict | None:
    """연관어를 축별로 묶어 비중을 보여 준다. 화면 연관어 파트의 '축별 비중'."""
    a = t.get("associations") or []
    if not a:
        return None
    agg: dict[str, int] = {}
    for x in a:
        agg[x.get("facet_name") or "기타"] = agg.get(x.get("facet_name") or "기타", 0) + 1
    mx = max(agg.values()) or 1
    return {"type": "bars", "slot": "right", "title": "축별 비중", "meta": "연관어 수",
            "items": [{"k": k, "w": round(100 * v / mx), "v": str(v)}
                      for k, v in sorted(agg.items(), key=lambda x: -x[1])]}


def b_sentiment(t: dict) -> dict | None:
    s = t.get("sentiment")
    if not s:
        return None
    return {"type": "kpis", "slot": "full", "items": [
        {"k": "구매의향 지수", "v": str(s.get("index")), "unit": "점",
         "note": f"표본 {s.get('n_total')}건", "up": (s.get("index") or 0) >= 50},
        {"k": "긍정 신호", "v": str(s.get("pos_pct")), "unit": "%",
         "note": s.get("top_pos") or "", "up": True},
        {"k": "부정 신호", "v": str(s.get("neg_pct")), "unit": "%",
         "note": s.get("top_neg") or "", "up": False},
    ]}


def b_sentiment_signal(t: dict) -> dict | None:
    """긍부정을 '몇 %' 가 아니라 '몇 건' 으로. 신호 유형(top_pos·top_neg)별 건수.

    metric_term_sentiment_daily 가 유형별 전체 분포는 안 주고 폴더(1위)만 준다 —
    그래서 '몇 개 유형 중 몇 건' 이 아니라 '가장 많이 나온 유형이 몇 건' 으로 답한다.
    지어낸 유형을 만들지 않는다 — top_pos_intent 가 없으면 그 줄은 아예 안 낸다.
    """
    s = t.get("sentiment")
    if not s:
        return None
    rows = []
    pos_n, neg_n = s.get("pos_count"), s.get("neg_count")
    mx = max((pos_n or 0), (neg_n or 0)) or 1
    if s.get("top_pos") and s.get("top_pos_count"):
        label = INTENT_KO.get(s["top_pos"], s["top_pos"])
        rows.append({"k": f"긍정 · {label}", "w": round(100 * s["top_pos_count"] / mx),
                     "v": f"{int(s['top_pos_count']):,}건", "up": True})
    if s.get("top_neg") and s.get("top_neg_count"):
        label = INTENT_KO.get(s["top_neg"], s["top_neg"])
        rows.append({"k": f"부정 · {label}", "w": round(100 * s["top_neg_count"] / mx),
                     "v": f"{int(s['top_neg_count']):,}건", "up": False})
    if pos_n is not None:
        rows.append({"k": "긍정 신호 전체", "w": round(100 * pos_n / mx),
                     "v": f"{int(pos_n):,}건", "up": True})
    if neg_n is not None:
        rows.append({"k": "부정 신호 전체", "w": round(100 * neg_n / mx),
                     "v": f"{int(neg_n):,}건", "up": False})
    if not rows:
        return None
    return {"type": "table", "slot": "right", "title": "긍부정 신호 건수",
            "meta": f"표본 {s.get('n_total') or 0}건",
            "head": ["신호 유형", "", "건수"], "rows": rows}


def b_evidence(t: dict) -> dict | None:
    """근거 인용.

    본문 전체가 아니라 '이 대목 때문에 그렇게 셌다' 하는 짧은 span 만 싣는다.
    긴 원문을 잘라 붙이면 말이 중간에서 끊기고, 그 term 과 무관한 문장이 딸려온다.
    """
    ev = t.get("evidence") or []
    if not ev:
        return None
    items = []
    for e in ev[:3]:
        body = str(e.get("body") or "").strip()
        if len(body) < 6:
            continue
        items.append({"src": e.get("source"), "kind": e.get("kind"),
                      "tone": TONE_KO.get(e.get("tone")), "body": body})
    if not items:
        return None
    return {"type": "quotes", "slot": "right", "title": "근거가 된 대목",
            "meta": f"{len(items)}건", "items": items}


def b_compare(nodes: list[dict], as_of: str) -> dict | None:
    """둘 이상을 나란히. '무신사 vs 29CM' 같은 질문의 답."""
    ok = [n for n in nodes if n.get("available")]
    if len(ok) < 2:
        return None
    mx = max(int(n.get("temp") or 0) for n in ok) or 1
    return {"type": "bars", "slot": "full", "title": "나란히 보기", "meta": as_of,
            "items": [{"k": n["canonical"], "w": round(100 * int(n.get("temp") or 0) / mx),
                       "v": f"{int(n.get('temp') or 0)}점"} for n in ok]}


def b_web(web: dict, t: dict) -> list[dict]:
    out = [{"type": "prose", "slot": "left", "title": t["canonical"], "meta": "웹에서 찾음",
            "text": web["answer"]}]
    if web.get("sources"):
        out.append({"type": "links", "slot": "left", "items": web["sources"][:4]})
    return out


def b_upsell(up: dict) -> dict:
    return {"type": "upsell", "slot": "right", "title": "더 볼 수 있는 것", "meta": "PRO",
            "why": up.get("why"), "unlocks": (up.get("unlocks") or [])[:4]}


def b_notes(notes: list[dict], limit: int = 3) -> list[dict]:
    return [{"type": "note", "slot": "left", "text": n["message"]} for n in (notes or [])[:limit]]
