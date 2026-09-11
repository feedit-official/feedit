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
import re
import time
import traceback

from . import agent_blocks, llm, mdclean, orchestrator, verify


# ★ 예산을 꽉 채워 쓴 답변은 마지막 호출이 끝나고 값을 싸는 데 몇 ms 를 더 쓴다.
#   그 몇 ms 로 "예산 초과" 를 띄우면 정상 답변마다 경고가 붙어, 진짜 초과
#   (어느 층이 예산 밖에서 모델을 부르는 것)를 못 알아보게 된다.
OVER_GRACE_MS = 250


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


def _item_draft(trace) -> dict | None:
    """'물어보기' 카드가 그대로 받아 쓰는 상품 초안.

    ★ 답변 문장에서 상품명을 뽑지 않는다 — 모델이 지어낸 이름도 카드에 실린다.
      도구에 적힌 것만이 확인한 것이다(_terms_from 과 같은 원칙).
    ① inspect_product_link 또는 get_salmal_index 가 확인한 상품명·브랜드·가격이 있으면 그것.
    ② 없으면 search_terms 로 **실제로 찾아본 말**을 상품명 자리에 쓴다.
      링크 질문에서 모델은 링크가 무엇인지 확인한 뒤 그 이름으로 찾는다
      (orchestrator 규칙: q="아디다스 트랙탑"). 링크 주소를 그대로 남기는 것보다
      낫고, 사용자가 카드에서 고쳐 쓸 수 있다.
    """
    draft = None
    searched = ""
    for c in (trace.calls if trace else []):
        tool, res = c.get("tool"), c.get("result")
        if tool == "inspect_product_link" and isinstance(res, dict) and res.get("found"):
            draft = {"title": res.get("item_name") or "", "brand": res.get("brand") or "",
                     "price": res.get("price_krw"), "source": "상품 링크에서 확인한 값"}
        if tool == "search_terms" and not searched:
            q = str((c.get("args") or {}).get("q") or "").strip()
            if q and not q.lower().startswith(("http://", "https://")):
                searched = q[:120]
        if tool != "get_salmal_index" or not isinstance(res, dict):
            continue
        item = res.get("item_draft")
        if isinstance(item, dict) and item.get("recorded"):
            draft = {"title": item.get("name") or "", "brand": item.get("brand") or "",
                     "price": item.get("price"), "source": "챗봇이 확인한 값"}
    if draft and draft["title"]:
        return draft
    if searched:
        base = draft or {"title": "", "brand": "", "price": None}
        base["title"] = searched
        base["source"] = "챗봇이 찾아본 이름"
        return base
    return draft


def _as_of(trace) -> str | None:
    for c in (trace.calls if trace else []):
        res = c.get("result")
        if isinstance(res, dict) and res.get("as_of"):
            return str(res["as_of"])
    return None


# 대화를 이어 갈 질문. 모델이 답변 **맨 마지막 줄**에 이 표식으로 쓴다
# (orchestrator.INSTRUCTIONS 규칙 11).
_FOLLOW = re.compile(r"^[ \t]*\[다음\][ \t]*(.+?)[ \t]*$", re.M)


def _split_followup(text: str) -> tuple[str, str]:
    """대화를 이어 갈 질문을 본문에서 떼어 낸다 (2026-09-10).

    ★ 왜 떼나 — 질문이 본문에 섞여 있으면 화면에서 **리포트 카드 위**에 뜬다.
      사용자는 근거를 보기도 전에 다음 질문부터 받는다. 순서가 뒤집혀 있다.
    ★ 표식이 없으면 아무것도 하지 않는다. 끝 문장을 휴리스틱으로 떼면 멀쩡한
      결론이 잘려 나간다 — 못 찾는 편이 잘못 자르는 것보다 낫다.
    """
    if not text:
        return "", ""
    hits = list(_FOLLOW.finditer(text))
    if not hits:
        return text, ""
    last = hits[-1]
    body = (text[:last.start()] + text[last.end():]).strip()
    return body, last.group(1).strip()


def _notes(trace, rep: verify.Report, res: orchestrator.Result) -> list[dict]:
    """무엇을 못 했는지 숨기지 않는다. 화면의 '측정 불가' 와 같은 자리."""
    notes = []
    for m in (trace.missing if trace else []):
        notes.append({"code": "NO_DATA", "term": m.get("term"),
                      "message": f"{m.get('axis')} — {m.get('reason')}"})
    # ★ 검증이 무엇을 덜어냈는지는 **화면에 올리지 않는다** (2026-09-10).
    #   "P5069에서 도구 결과에 없는 숫자 5069를 제거했습니다" 처럼, 사용자가
    #   할 수 있는 일이 없는 내부 사정이 그대로 노출됐다. 덜어낸 뒤의 답변은
    #   이미 맞는 답이므로 사용자에게 필요한 정보가 아니다.
    #   숨기는 것이 아니다 — trace.verify.removed 에 그대로 남고 로그로 볼 수 있다.
    #   화면에 남기는 것은 **사용자의 판단이 달라지는 것**뿐이다
    #   (없는 축 · 웹으로 답함 · 조회를 못 끝냄).
    # ★ 웹으로만 답한 것은 **검증 실패가 아니다** — 대조할 원본이 없는 것이다.
    #   (2026-09-10) verify 는 skipped=no_tool_results 로 남기는데 여기서는
    #   "web_sourced" 를 보고 있어서, 의도한 안내 대신 "사실 확인을 끝내지
    #   못했습니다 (no_tool_results)" 라는 경고가 나갔다. 사용자에게는 웹에서
    #   찾았다는 뜻이 아니라 **답이 못 미덥다**는 뜻으로 읽힌다. 둘은 다르다.
    if rep.skipped == verify.NO_TOOL_RESULTS:
        # ★ 이 사유에는 **두 경우**가 섞여 있다 (2026-09-10).
        #   · 출처가 있으면 호스티드 웹 검색으로 답한 것이다.
        #   · 출처가 없으면 아무것도 안 보고 답한 것이다("상품 링크를 보내 주세요"
        #     같은 한 줄 답). 그런 답에 "웹에서 찾았다" 고 적으면 하지 않은 일을
        #     했다고 말하는 셈이다 — 실측에서 실제로 그렇게 나갔다.
        #   판정(검증을 건너뛴다)은 그대로 두고 **문구만** 가른다. 판정을 조이면
        #   날씨 답변의 온도가 다시 지워지던 자리로 돌아간다(10장).
        web = bool(res.sources)
        notes.append({
            "code": "WEB_SOURCED" if web else "NO_LOOKUP", "term": None,
            "message": ("FEEDiT 지표를 조회하지 않고 웹에서 찾은 내용으로 답했습니다. "
                        "측정값이 아니니 함께 확인해 주세요.") if web else
                       "FEEDiT 지표를 조회하지 않고 답했습니다. 측정값이 아닙니다."})
    elif rep.skipped:
        notes.append({"code": "VERIFY_FAILED", "term": None,
                      "message": f"사실 확인을 끝내지 못했습니다 ({rep.skipped})."})
    # 되살린 답에는 붙이지 않는다 — 모델이 조회를 마치고 쓴 답이다(2026-09-11).
    if (res.stopped in ("max_rounds", "max_calls", "time_budget")
            and not getattr(res, "recovered", False)):
        notes.append({"code": "PARTIAL", "term": None,
                      "message": "조회를 끝까지 하지 못하고 지금까지 모은 것으로 답했습니다."})
    return notes


def ask(question: str, *, store, gate, mode: str = "general",
        history: list[dict] | None = None, ctx: dict | None = None,
        salmal=None, taste=None, on_progress=None, cancel_check=None) -> dict:
    """새 경로 한 번. engine.ask() 와 같은 모양의 dict 를 돌려준다."""
    t0 = time.monotonic()
    ctx = dict(ctx or {})
    ctx.setdefault("mode", mode)
    # ★ 시간 예산은 **여기서** 정한다 (2026-09-10, 인수인계 18번).
    #   예전에는 orchestrator 루프만 예산을 봤다. 루프가 끝난 뒤에도
    #   _finish 가 한 번(20초), verify.fix 가 한 번(15초) 더 모델을 부르는데
    #   둘 다 예산 밖이었다. 그래서 예산 14초짜리 답이 25초에 나왔다.
    #   마감시각 하나를 여기서 만들어 두 층에 그대로 넘긴다 —
    #   예산이 비로소 **답변 한 번의 전체 벽시계**가 된다.
    # ★ 예산은 질문을 보고 정한다 (2026-09-11). 링크 질문은 링크가 무엇인지
    #   확인하는 바퀴가 하나 더 들어서, 같은 시계를 주면 답 쓰는 바퀴가 밀린다.
    budget = orchestrator.budget_for(question)
    deadline = t0 + budget

    res = orchestrator.run(question, store=store, gate=gate, ctx=ctx,
                           history=history, salmal=salmal, taste=taste,
                           on_progress=on_progress, deadline=deadline,
                           cancel_check=cancel_check)

    # 되묻기 — 답이 아니라 질문을 돌려준다. 실패가 아니다(설계도 원칙 3).
    if res.ask:
        opts = res.ask.get("options") or []
        msg = res.ask.get("question") or "무엇을 볼까요?"
        return {
            "ok": True, "kind": "meta", "intent": "agent.ask",
            # ★ 보기는 글머리표로 넘긴다 (2026-09-10). 예전에는 "· A\n· B" 였는데
            #   화면이 innerHTML 로 그리므로 줄바꿈이 통째로 사라져 한 줄로 붙었다.
            #   mdclean.to_html 이 <ul> 로 만들어 주면 보기가 보기로 보인다.
            "message": mdclean.to_html(
                msg + ("\n\n" + "\n".join("- " + o for o in opts) if opts else "")),
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
                                web_sourced=web_only, deadline=deadline)
    # 이어 갈 질문은 본문에서 떼어 화면이 카드 **아래**에 붙이게 한다.
    answer, follow = _split_followup(answer)

    terms = _terms_from(res.trace)
    as_of = _as_of(res.trace)
    # 블록 만들기가 실패해도 답변은 나가야 한다. 블록은 덤이다.
    # ★ 다만 **조용히** 삼키지 않는다 (2026-09-11).
    #   리포트 카드가 통째로 안 뜨는 일이 있었는데, 카탈로그가 비어서인지
    #   여기서 예외가 났는지 구분할 방법이 화면에도 콘솔에도 없었다.
    #   계측이 없으면 처방도 없다(AGENTS.md §4).
    block_error = ""
    designed = any(c.get("tool") == "compose_report"
                   for c in (res.trace.calls if res.trace else []))
    # 정상 완료된 답에서 디자인 도구를 고르지 않은 것은 모델의 명시적인 '문장만으로
    # 충분함' 판단이다. 시간·호출 상한 때문에 도구를 못 부른 경우에만 안전망 카드로
    # 조회 결과를 보존한다.
    should_build = designed or res.stopped != "done"
    try:
        blks = (agent_blocks.build(res.trace, store, gate, question=question)
                if should_build else [])
    except Exception as ex:                      # noqa: BLE001
        block_error = f"{type(ex).__name__}: {str(ex)[:120]}"
        print("! agent_blocks.build 실패 —", block_error, flush=True)
        traceback.print_exc()
        blks = []
    report_design = (None if not blks or blks[0].get("type") != "generative_report" else {
        "source": blks[0].get("source"),
        "fingerprint": blks[0].get("fingerprint"),
        "modules": len(blks[0].get("modules") or []),
    })
    ms = int((time.monotonic() - t0) * 1000)
    out = {
        "ok": True,
        "kind": "agent",
        "intent": "agent",
        "question": question,
        # server.py 가 이걸 흘려보낸다.
        # ★ 마크다운을 **여기서** HTML 로 바꾼다 (2026-09-10, mdclean.to_html).
        #   예전 경로의 한 줄 결론과 달리 새 경로 답변은 목록과 강조가 있는 여러
        #   문단이라, 그대로 보내면 팝업에 별표가 그대로 보이고 줄바꿈도 사라진다.
        #   화면 계약("서버는 안전한 HTML 만 보낸다")은 그대로다 — to_html 이
        #   이스케이프를 먼저 하고 우리가 아는 표시만 태그로 바꾼다.
        "headline": mdclean.to_html(answer),
        # 카드 아래에 붙는 이어 갈 질문. 없으면 빈 문자열.
        "followup": mdclean.to_html(follow),
        "terms": terms,
        # 물어보기(커뮤니티 카드)가 그대로 받아 쓰는 상품 초안. 없으면 None.
        "item_draft": _item_draft(res.trace),
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
        # ★ 상한에 걸렸어도 모델이 써 둔 답을 되살렸으면 부분 답변이 아니다
        #   (2026-09-11). 온전한 답 아래에 "조회를 끝까지 하지 못했다" 가 붙으면
        #   사용자는 멀쩡한 답을 의심한다.
        "partial": ((res.stopped in ("time_budget", "max_rounds", "max_calls")
                     and not getattr(res, "recovered", False))
                    or str(res.stopped or "").startswith("llm_")),
        # 진단 — 어느 도구를 몇 바퀴에 불렀나. 화면엔 안 뜨지만 로그에 남는다.
        "trace": {
            "rounds": res.rounds, "calls": res.calls, "stopped": res.stopped,
            "tools": [c["tool"] for c in (res.trace.calls if res.trace else [])],
            "verify": rep.as_dict(),
            "ms": ms,
            # 바퀴별 소요와 호스티드 도구 횟수 — 시간이 어디로 갔는지 (11장)
            "round_ms": res.round_ms,
            "hosted": res.hosted,
            # compose_report 스킬이 만든 조합의 출처·지문·모듈 수다.
            # 이름 붙은 variant 는 더 이상 없다. fingerprint 로 같은 조합에
            # 계속 쏠리는 회귀를 관찰한다.
            "report_design": report_design,
            # 카드가 안 떴을 때 어디서 비었는지 — 블록 수와 조립 실패 사유.
            "blocks": len(blks),
            "block_error": block_error,
            # ★ 예산을 지켰나. 넘었으면 그 자체가 버그다(18번) —
            #   어느 층이 예산 밖에서 모델을 부르고 있다는 뜻이다.
            "budget_ms": int(budget * 1000),
            "over_budget": ms > int(budget * 1000) + OVER_GRACE_MS,
        },
        "nlu": {"intent": "agent", "source": "orchestrator",
                "model": llm.role("orchestrator")["model"]},
    }
    return out
