"""L1~L4 를 한 줄로 잇는다 — 오케스트레이터 답변을 화면이 아는 모양으로.

── 왜 별도 파일인가 ─────────────────────────────────────────
`engine.py` 의 기존 경로(정규식 의도 분류 → 고정 템플릿)를 지우지 않는다.
스위치 하나로 두 경로가 나란히 서고, 껐다 켰다 하며 비교할 수 있어야 한다.

    FEEDIT_CHAT_ORCHESTRATOR=1   새 경로 (도구 루프)
    (없거나 0)                    지금까지의 경로

지금 돌고 있는 챗봇을 세우지 않고 갈아 끼우기 위한 것이다. 새 경로가
어느 질문에서 더 나은지 실제로 재 본 뒤에 기본값을 바꾸면 된다.

── 화면 계약 ────────────────────────────────────────────────
server.py 가 기대하는 모양은 이미 정해져 있다:
    kind == "meta"  → message 를 흘려보내고 끝
    그 외           → headline 을 흘려보내고 report 이벤트로 rep 전체를 보냄
                      actions_for(rep) 가 terms[0] 의 facet·available 을 본다
그래서 여기서도 headline·terms 를 채운다. 화면은 고칠 것이 없다.
"""
from __future__ import annotations

import os
import time

from . import agent_blocks, llm, orchestrator, verify


def enabled() -> bool:
    return (os.getenv("FEEDIT_CHAT_ORCHESTRATOR") or "").strip().lower() in ("1", "true", "yes")


def _terms_from(trace) -> list[dict]:
    """actions_for() 가 쓸 용어 목록. 도구가 실제로 조회한 것만 넣는다.

    ★ 답변 본문에서 뽑지 않는다.
      본문에서 뽑으면 모델이 지어낸 말도 '지표로 보기' 버튼이 되어,
      눌렀을 때 빈 화면이 뜬다. 조회한 것만이 화면에 있는 것이다.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for c in (trace.calls if trace else []):
        res = c.get("result") or {}
        if not isinstance(res, dict):
            continue
        # search_terms 가 찾아 준 것.
        #   ★ 타입을 확인한다. 도구가 늘어나면 같은 키에 다른 모양이 또 들어온다.
        for h in (res.get("found") if isinstance(res.get("found"), list) else []):
            name = h.get("term")
            if name and name not in seen:
                seen.add(name)
                out.append({"canonical": name, "facet": h.get("facet"),
                            "available": False})
        # rank_terms 가 준 것 — 지표가 있으니 available
        for it in (res.get("items") if isinstance(res.get("items"), list) else []):
            name = it.get("term")
            if name and name not in seen:
                seen.add(name)
                out.append({"canonical": name, "facet": it.get("facet"),
                            "available": True})
        # get_metric 이 실제로 값을 찾은 것 → available 을 올린다
        if c.get("tool") == "get_metric" and res.get("has_metric"):
            name = res.get("term")
            for t in out:
                if t["canonical"] == name:
                    t["available"] = True
                    break
            else:
                if name:
                    seen.add(name)
                    out.append({"canonical": name, "facet": None, "available": True})
    return out[:5]


def _as_of(trace) -> str | None:
    for c in (trace.calls if trace else []):
        res = c.get("result")
        if isinstance(res, dict) and res.get("as_of"):
            return str(res["as_of"])
    return None


def _notes(trace, rep: verify.Report, res: orchestrator.Result) -> list[dict]:
    """무엇을 못 했는지 숨기지 않는다. 화면의 '측정 불가' 와 같은 자리."""
    notes = []
    for m in (trace.missing if trace else []):
        notes.append({"code": "NO_DATA", "term": m.get("term"),
                      "message": f"{m.get('axis')} — {m.get('reason')}"})
    if rep.changed and rep.removed:
        notes.append({"code": "VERIFIED",
                      "term": None,
                      "message": "측정 자료에 없는 내용을 덜어냈습니다: "
                                 + ", ".join(rep.removed[:3])})
    if rep.skipped:
        notes.append({"code": "VERIFY_FAILED", "term": None,
                      "message": f"사실 확인을 끝내지 못했습니다 ({rep.skipped})."})
    if rep.skipped == "web_sourced":
        notes.append({"code": "WEB_SOURCED", "term": None,
                      "message": "FEEDiT 지표를 조회하지 않고 답했습니다. "
                                 "측정값이 아니니 함께 확인해 주세요."})
    if res.stopped in ("max_rounds", "max_calls", "time_budget"):
        notes.append({"code": "PARTIAL", "term": None,
                      "message": "조회를 끝까지 하지 못하고 지금까지 모은 것으로 답했습니다."})
    return notes


def ask(question: str, *, store, gate, mode: str = "general",
        history: list[dict] | None = None, ctx: dict | None = None,
        salmal=None, taste=None, on_progress=None) -> dict:
    """새 경로 한 번. engine.ask() 와 같은 모양의 dict 를 돌려준다."""
    t0 = time.monotonic()
    ctx = dict(ctx or {})
    ctx.setdefault("mode", mode)

    res = orchestrator.run(question, store=store, gate=gate, ctx=ctx,
                           history=history, salmal=salmal, taste=taste,
                           on_progress=on_progress)

    # 되묻기 — 답이 아니라 질문을 돌려준다. 실패가 아니다(설계도 원칙 3).
    if res.ask:
        opts = res.ask.get("options") or []
        msg = res.ask.get("question") or "무엇을 볼까요?"
        return {
            "ok": True, "kind": "meta", "intent": "agent.ask",
            "message": msg + ("\n\n· " + "\n· ".join(opts) if opts else ""),
            "question": question,
            "actions": [{"label": o, "type": "ask", "text": o} for o in opts[:4]],
            "trace": {"rounds": res.rounds, "calls": res.calls, "stopped": res.stopped},
        }

    # ★ 우리 도구를 **하나도** 안 불렀으면 대조할 원본이 없다.
    #   known 이 빈 집합이라 답변의 모든 숫자가 "지어낸 것" 으로 잡히고,
    #   fix() 가 그걸 전부 지운다. 검증이 아니라 자동 삭제다.
    #   실측(2026-09-09) — "오늘 날씨 어때?" 가 호스티드 web_search 로 답했는데
    #   16·18·21 이 모두 삭제되어 "약 °C · ~°C · 낮 °C" 가 되어 나갔다.
    #   (처음엔 res.sources 로 판정했는데, 호스티드 검색은 annotation 을
    #    안 남길 때가 있어 sources 가 비어 이 가드가 통째로 무력해졌다.)
    web_only = not (res.trace.calls if res.trace else [])
    answer, rep = verify.verify(res.answer, res.trace, question,
                                web_sourced=web_only)

    terms = _terms_from(res.trace)
    as_of = _as_of(res.trace)
    # 블록 만들기가 실패해도 답변은 나가야 한다. 블록은 덤이다.
    try:
        blks = agent_blocks.build(res.trace, store, gate)
    except Exception:                            # noqa: BLE001
        blks = []
    out = {
        "ok": True,
        "kind": "agent",
        "intent": "agent",
        "question": question,
        # server.py 가 이걸 흘려보낸다
        "headline": answer,
        "terms": terms,
        # ★ 화면 계약: chat_api.reportHTML 은 as_of 를 **객체**로 읽는다
        #   (rep.as_of && rep.as_of.metric). 문자열을 주면 .metric 이 undefined 라
        #   카드 제목줄의 기준일이 조용히 사라진다. 예전 경로(engine.py:205)도
        #   같은 모양을 쓴다.
        "as_of": {"metric": as_of} if as_of else {},
        # ★ 블록은 답변 문장이 아니라 궤적에서 만든다(agent_blocks 머리말).
        "blocks": blks,
        "notes": _notes(res.trace, rep, res),
        "sources": res.sources or [],
        # 예산이 다 돼 되묻는 것으로 끝났나. 화면이 "더 볼까요" 버튼을 붙일 수 있다.
        #   ★ llm_* (모델 호출 실패·타임아웃) 도 부분 답변이다. 예전에는 빠져
        #     있어서, 중간에 끊긴 답이 완전한 답인 척 화면에 떴다.
        #     (2026-09-09 실측: stopped=llm_NET_ReadTimeout 인데 partial=False)
        "partial": (res.stopped in ("time_budget", "max_rounds", "max_calls")
                    or str(res.stopped or "").startswith("llm_")),
        # 진단 — 어느 도구를 몇 바퀴에 불렀나. 화면엔 안 뜨지만 로그에 남는다.
        "trace": {
            "rounds": res.rounds, "calls": res.calls, "stopped": res.stopped,
            "tools": [c["tool"] for c in (res.trace.calls if res.trace else [])],
            "verify": rep.as_dict(),
            "ms": int((time.monotonic() - t0) * 1000),
        },
        "nlu": {"intent": "agent", "source": "orchestrator",
                "model": llm.role("orchestrator")["model"]},
    }
    return out
