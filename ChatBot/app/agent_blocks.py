"""L2 출력 → 화면 블록. 도구가 조회한 것만 그린다.

── 왜 필요한가 (13번 피드백) ────────────────────────────────
새 경로(orchestrator)는 지금 **문장만** 내놓는다. 화면은 그 문장을 말풍선에
흘려보내고, 그 아래 report 이벤트로 받은 blocks 를 카드로 그린다. blocks 가
비어 있으니 카드는 제목줄만 있는 빈 상자로 뜬다. 예전 경로(templates.py)는
같은 질문에 온도 막대·플랫폼 표·인용을 그렸다. 즉 **새 경로로 갈아타면 화면이
가난해진다.** 답변 품질을 올리려고 만든 경로가 화면을 후퇴시키면 갈아탈 수 없다.

── 원칙: 블록은 궤적에서 만든다, 답변 문장에서 만들지 않는다 ─
`agent_path._terms_from()` 과 같은 이유다. 답변 문장을 파싱해 블록을 만들면
모델이 지어낸 말이 그대로 막대그래프가 된다. 숫자를 검증하는 층(verify.py)을
두고서 그 옆으로 지어낸 값이 그림이 되어 새어 나가는 셈이다.

그래서 여기서는 **도구를 실제로 부른 기록(TraceLog)** 만 읽고, 값은 store 에서
다시 가져온다(report.build_term). 문장과 그림의 출처가 같아진다.

── 구조는 서버가 정한다 (blocks.py 머리말) ──────────────────
블록의 종류와 모양은 blocks.py 가 이미 정해 두었고 프론트(chat_api.js BLOCK)에
그대로 있다. 여기서 새 블록 타입을 만들지 않는다 — 프론트가 모르는 type 은
말없이 안 그려지므로, 지어내면 조용한 빈 칸이 된다.

무엇을 그릴지는 **어떤 도구를 불렀는지**가 정한다. 의도 코드로 고르지 않는다.
get_metric 이 '출처별' 을 달라고 했으면 플랫폼 막대를 그린다 — 모델이 그걸
필요하다고 판단했다는 뜻이기 때문이다.
"""
from __future__ import annotations

from typing import Any

from . import blocks as B
from . import report

MAX_TERMS = 2       # 카드 하나에 term 둘까지. 셋이면 2단 그리드가 흘러넘친다.
MAX_BLOCKS = 7


def _facet_of(term_key: str, fallback: str | None = None) -> str | None:
    if fallback:
        return fallback
    if term_key and ":" in term_key:
        return term_key.split(":", 1)[0]
    return None


def _scan(trace) -> dict[str, Any]:
    """궤적에서 '무엇을 조회했나' 만 뽑는다. 값은 여기서 쓰지 않는다."""
    got: dict[str, Any] = {"metric": {}, "facets": {}, "evidence": set(),
                           "rank": None, "web": None, "as_of": None}
    for c in (trace.calls if trace else []):
        name, args = c.get("tool"), (c.get("args") or {})
        res = c.get("result")
        if not isinstance(res, dict):
            continue
        if res.get("as_of") and not got["as_of"]:
            got["as_of"] = str(res["as_of"])

        if name == "search_terms":
            for h in (res.get("found") or []):
                if h.get("term") and h.get("facet"):
                    got["facets"][h["term"]] = h["facet"]
        elif name == "get_metric" and res.get("has_metric"):
            term = res.get("term") or args.get("term")
            if term:
                axes = set(args.get("axes") or [])
                got["metric"].setdefault(term, set()).update(axes)
        elif name == "get_evidence" and (res.get("count") or 0) > 0:
            term = res.get("term") or args.get("term")
            if term:
                got["evidence"].add(term)
        elif name == "rank_terms" and (res.get("items") or []):
            got["rank"] = res
        elif name == "web_search" and (res.get("items") or []):
            got["web"] = res
    return got


def _rank_block(res: dict, as_of: str) -> dict | None:
    """rank_terms 결과 → 순위 블록.

    ★ short_of_asked 를 meta 에 적는다. 10개를 물었는데 4개뿐이면 그 사실이
      화면에도 있어야 한다 — 문장에만 있으면 카드만 본 사람은 4개가 전부인 줄
      모르고 '나머지는 어디 갔나' 로 읽는다.
    """
    items = res.get("items") or []
    if not items:
        return None
    meta = as_of or ""
    if res.get("short_of_asked"):
        meta = (meta + " · " if meta else "") + f"찾은 것 {len(items)}개가 전부입니다"
    rows = []
    for it in items[:8]:
        temp = it.get("temp")
        rows.append({"k": it.get("term") or "",
                     "small": it.get("facet_name") or it.get("facet") or "",
                     "v": (f"{int(temp)}점" if temp is not None else "—"),
                     "up": (temp is not None and int(temp) >= 50)})
    return {"type": "rank", "slot": "full", "title": "지금 뜨는 것",
            "meta": meta, "rows": rows}


def _evidence_links(node: dict) -> dict | None:
    """근거 중 **원문으로 돌아갈 수 있는 것만** 링크로.

    없는 것은 아예 넣지 않는다. 인용 블록(b_evidence)에는 그대로 남아 있으므로
    '인용은 3건인데 링크는 2건' 이 화면에서도 그대로 보인다. 링크가 없는 근거에
    검색 결과 주소 같은 것을 붙이면 누른 사람이 우리가 인용하지 않은 글에
    도착한다 — store.evidence_link() 가 네이버에 대해 None 을 주는 이유다.
    """
    items = []
    for e in (node.get("evidence") or [])[:4]:
        url = e.get("url")
        if not url:
            continue
        title = str(e.get("body") or "").strip()
        items.append({"url": url,
                      "title": (title[:40] + "…") if len(title) > 41 else title})
    if not items:
        return None
    return {"type": "links", "slot": "right", "items": items}


def build(trace, store, gate) -> list[dict]:
    """궤적 → 블록 목록. 조회한 것이 없으면 빈 목록을 돌려준다.

    빈 목록이면 agent_path 가 report 이벤트를 보내지 않는다 — 빈 카드를
    그리느니 카드를 안 그리는 쪽이 맞다.
    """
    if trace is None or store is None:
        return []
    got = _scan(trace)
    as_of = got["as_of"] or ""
    out: list[dict] = []

    if got["rank"]:
        blk = _rank_block(got["rank"], as_of)
        if blk:
            out.append(blk)

    for term, axes in list(got["metric"].items())[:MAX_TERMS]:
        try:
            key = gate.term_key(term)
            node = report.build_term(
                store, gate,
                {"term_key": key, "canonical": term,
                 "facet": _facet_of(key, got["facets"].get(term))},
                as_of or "")
        except Exception:                       # noqa: BLE001
            # 블록은 덤이다. 여기서 터져 답변까지 못 나가면 본말전도다.
            continue
        if not node.get("available"):
            continue

        out.append(B.b_metric_rank(node, as_of or node.get("observed_on") or ""))
        if "모멘텀" in axes:
            got_dir = B.b_direction(node)
            if got_dir:
                out.append(got_dir)
        if "출처별" in axes:
            out.append(B.b_sources(node, as_of or ""))
        if "연관어" in axes:
            out.append(B.b_assoc(node))
        if term in got["evidence"]:
            out.append(B.b_evidence(node))
            out.append(_evidence_links(node))

    if got["web"]:
        src = [{"url": h.get("url"), "title": h.get("title")}
               for h in (got["web"].get("items") or [])[:4] if h.get("url")]
        if src:
            # ★ 우리 측정값이 아니라는 것을 블록 자체에 적는다.
            out.append({"type": "note", "slot": "left",
                        "text": "아래 출처는 웹에서 찾은 것으로, FEEDiT 측정값이 아닙니다."})
            out.append({"type": "links", "slot": "left", "items": src})

    for m in (trace.missing or [])[:2]:
        out.append({"type": "note", "slot": "left",
                    "text": f"{m.get('term')} — {m.get('axis')}: 아직 측정 자료가 없습니다."})

    return [b for b in out if b][:MAX_BLOCKS]
