"""L1 오케스트레이터 — 도구를 고르고, 결과를 보고 다시 고른다.

── 이 파일이 대체하는 것 ────────────────────────────────────
`intents.py` 의 정규식 14개와 `templates.py` 의 의도→블록 고정 매핑.

예전에는 질문이 들어오면 정규식으로 의도를 **확정**하고, 그 의도에 붙은
블록 목록을 그렸다. 근거를 보기 전에 되돌릴 수 없는 결정을 하는 셈이라
세 곳에서 깨졌다:

  ① 축이 여러 개인 질문
     "살로몬 XT-6 지금 사도 돼?" 는 할인률·수명주기·리세일 셋 다인데
     하나를 고르는 순간 나머지 근거가 사라진다.
  ② 지시대명사
     "이거 어때?" 를 분류하려면 "이거" 가 뭔지 알아야 하고, 그건 분류
     이후에나 확정된다. 순서가 뒤집혀 있다.
  ③ 용어가 없는 질문
     "요즘 뭐가 핫해?" 는 사전에 걸리는 말이 없다고 범용으로 흘러갔다.
     답이 용어인 질문인데 우리 데이터를 안 보고 지어냈다.

여기서는 의도 코드를 만들지 않는다. **다음에 부를 도구**만 정하고,
결과를 받아 다시 정한다. 위 셋이 전부 이 한 가지로 풀린다.

── 일반 / 살!말? 를 가르지 않는다 ───────────────────────────
`is_salmal_question()` 정규식이 하던 일은 이제 **도구 목록의 유무**가 한다.
살말 카드에서 넘어왔으면 tools 에 get_salmal 이 있고, 아니면 없다.
모드는 라우팅 대상이 아니라 컨텍스트다(설계도 03).

── 안전장치 (설계도 08) ─────────────────────────────────────
도구를 자유롭게 부르게 두면 비용과 지연이 열려 있게 된다. 네 개를 건다:
  · 최대 바퀴 수          빈 결과를 주면 같은 것을 계속 다시 부른다
  · 같은 인자 재호출 금지  같은 인자로 두 번 부르는 건 언제나 버그다
  · 전체 시간 예산        SSE 가 시작을 못 하면 멈춘 줄 안다
  · 도구 결과 원본 보관   verify.py 가 대조할 것이 없으면 검증이 도장이 된다
"""
from __future__ import annotations

import json
import time
from typing import Any

from . import llm
from .tools import Toolbox, progress_say, specs_for

# ── 안전장치 값 ────────────────────────────────────────────
MAX_ROUNDS = 4          # 한 질문에 도구를 부를 수 있는 바퀴 수
MAX_CALLS = 10          # 바퀴를 합쳐 도구 호출 총량
TIME_BUDGET = 8.0       # 초. 넘으면 지금까지 모은 것으로 답한다
CALL_TIMEOUT = 20       # 한 번의 모델 호출 상한


INSTRUCTIONS = """너는 FEEDiT 의 패션 트렌드 분석 상담원이다.
FEEDiT 는 SNS·커머스를 수집해 용어별 트렌드 지표를 계산하는 서비스다.

## 어떻게 답을 만드나
질문을 분류하지 마라. 무엇을 더 알아야 답할 수 있는지만 판단하고 도구를 불러라.
결과를 보고 방향을 바꿔도 된다. 도구는 한 번에 여러 개를 불러도 되고,
한 바퀴로 끝나지 않아도 된다.

## 반드시 지킬 것
1. **도구가 준 값만 말한다.** 지표·숫자·용어를 기억이나 추측으로 만들지 마라.
   FEEDiT 는 측정한 것만 말하는 서비스다. 지어낸 숫자 하나가 나머지 전부의
   신뢰를 무너뜨린다.
2. **없으면 없다고 한다.** 그 축의 자료가 없으면 declare_missing 을 부르고,
   답변에서 "아직 측정 자료가 없습니다" 라고 밝혀라. 대충 메우지 마라.
3. **모르면 되묻는다.** "이거 어때?" 처럼 무엇을 묻는지 알 수 없으면
   추측하지 말고 ask_user 를 불러라. 그건 실패가 아니다.
4. **요청보다 적게 나오면 그대로 말한다.** rank_terms 가 short_of_asked=true 를
   주면 나머지를 채우지 말고 몇 개뿐인지 밝혀라.
5. **may_say 를 지킨다.** get_metric 의 may_say 에서 false 인 축은 관측이
   모자라 말할 수 없는 것이다. 그 값을 근거로 삼지 마라.
6. **링크를 지어내지 않는다.** 근거를 인용할 때 주소는 get_evidence 가 준 url
   그대로만 쓴다. url 이 비어 있으면 플랫폼과 시점만 밝히고 끝에 "(원문 링크 없음)"
   이라고 적어라. 검색 결과 주소나 그럴듯한 주소를 만들어 붙이면, 누른 사람은
   우리가 인용하지 않은 글에 도착한다. 지어낸 숫자와 같은 종류의 거짓말이다.
6. **말할_수_있는_것을 지킨다.** get_metric 이 그 조건에서 허용되는 표현을
   함께 준다. `recommend` 가 "금지" 면 **사도 된다/괜찮다 같은 권유를 하지 마라.**
   사실만 적는다. "조건부" 면 note 에 적힌 단서를 반드시 함께 쓴다.
   숫자가 전부 맞아도 결론이 틀릴 수 있고, 구매를 권하는 문장에는 책임이 따른다.
7. **숫자에는 기준선을 붙인다.** "온도 71°" 만 쓰면 높은 건지 낮은 건지 모른다.
   rank_text · delta_1w · sample_n 이 있으면 함께 적어라 —
   "온도 71°(같은 축에서 상위 12%, 지난주 78°에서 내려오는 중)".
8. **가격·재고·세일은 우리 데이터에 없다.** "살까 말까" 를 묻는 질문에는
   이것이 **유행 관점의 판단**이라는 것을 한 번은 밝혀라.

## 도구 고르는 법
- 질문이 용어를 지목했으면 → search_terms 로 정확한 표기를 얻고 get_metric
- 용어를 지목하지 않았는데 "요즘 뭐가 핫해" 류면 → rank_terms
- 판단을 묻는 질문("사도 돼?", "괜찮아?")이면 → 축을 **여러 개** 넣어라.
  온도 하나로는 답이 안 된다.
- 우리 지표로 답할 수 없는 질문이면 → web_search. 다만 그 내용이 FEEDiT
  측정값이 아니라는 것을 답변에 밝혀라.

## 답변 문체
한국어. 결론을 먼저, 근거를 뒤에. 숫자에는 기준일을 붙인다.
과장하지 않고, 확실하지 않은 것은 확실하지 않다고 쓴다."""


class Result:
    """오케스트레이터가 내놓는 것.

    answer 를 그대로 사용자에게 보내지 않는다 — verify.py 를 거친다.
    trace 가 그 검증의 원본이다.
    """

    def __init__(self) -> None:
        self.answer: str = ""
        self.trace = None            # tools.TraceLog
        self.rounds: int = 0
        self.calls: int = 0
        self.stopped: str = ""       # 왜 멈췄나 (진단용)
        self.ask: dict | None = None  # ask_user 가 걸렸으면 여기
        self.sources: list[dict] = []


def _ctx_block(question: str, ctx: dict, history: list[dict] | None) -> str:
    """모델에게 주는 상황. 질문만으로는 '이거' 를 못 푼다(설계도 L0)."""
    lines = [f"[질문] {question}"]
    if ctx.get("screen_term"):
        lines.append(f"[사용자가 보던 용어] {ctx['screen_term']}")
    if ctx.get("salmal_card_id"):
        lines.append(f"[살!말? 카드에서 넘어옴] card_id={ctx['salmal_card_id']}")
    if ctx.get("user_id"):
        lines.append("[로그인함] 취향을 근거로 쓸 수 있다")
    else:
        lines.append("[비로그인] 취향 얘기를 하지 마라")
    for t in (history or [])[-3:]:
        q, a = t.get("q"), t.get("a")
        if q:
            lines.append(f"[직전 질문] {q}")
        if a:
            lines.append(f"[직전 답변 요약] {str(a)[:160]}")
    return "\n".join(lines)


def _sig(name: str, args: dict) -> str:
    """같은 도구를 같은 인자로 부르는지 보는 지문."""
    try:
        return name + "|" + json.dumps(args, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return name + "|?"


def run(question: str, *, store, gate, ctx: dict | None = None,
        history: list[dict] | None = None, salmal=None, taste=None,
        websearch=None, on_progress=None) -> Result:
    ctx = ctx or {}
    out = Result()
    box = Toolbox(store, gate, ctx=ctx, salmal=salmal, taste=taste, websearch=websearch)
    out.trace = box.trace

    tools = specs_for(ctx)
    items: list[Any] = [{"role": "user", "content": _ctx_block(question, ctx, history)}]
    seen: set[str] = set()
    started = time.monotonic()

    for rnd in range(MAX_ROUNDS):
        out.rounds = rnd + 1
        left = TIME_BUDGET - (time.monotonic() - started)
        if left <= 0.5:
            out.stopped = "time_budget"
            break

        res = llm.respond(
            INSTRUCTIONS, items, tools=tools, raw_flag=True,
            timeout=min(CALL_TIMEOUT, max(3, int(left))),
            **llm.role("orchestrator"),
        )
        if res is None:
            # 모델에 못 닿았다. 지금까지 모은 것이 있으면 그걸로라도 답한다.
            out.stopped = f"llm_{llm.LAST_ERROR or 'unknown'}"
            break

        raw = res.get("_raw") or {}
        out.sources = res.get("_raw_sources") or out.sources
        calls = llm.tool_calls(res)

        if not calls:
            # 도구를 더 안 부른다 = 답할 준비가 됐다.
            out.answer = (res.get("text") or "").strip()
            out.stopped = "done"
            break

        # ★ 모델이 낸 출력 항목을 그대로 되돌려 넣는다.
        #   이게 없으면 모델은 자기가 뭘 불렀는지 모른 채 다음 바퀴를 돌고,
        #   같은 도구를 영원히 다시 부른다.
        items.extend(raw.get("output") or [])

        for c in calls:
            if out.calls >= MAX_CALLS:
                out.stopped = "max_calls"
                break
            sig = _sig(c["name"], c["args"])
            if sig in seen:
                # 같은 인자로 두 번은 언제나 버그다. 사실대로 알려 주면
                # 다음 바퀴에서 다른 것을 부르거나 답을 쓴다.
                items.append(llm.tool_result_item(
                    c["call_id"],
                    {"skipped": "같은 인자로 이미 불렀습니다. 결과가 위에 있습니다."}))
                continue
            seen.add(sig)
            out.calls += 1
            # ★ 부르기 **전에** 알린다. 조회가 끝난 뒤 알리면 이미 늦다.
            #   콜백이 터져도 대화는 계속돼야 한다 — 화면 장식이지 본체가 아니다.
            if on_progress:
                say = progress_say(c["name"], c["args"])
                if say:
                    try:
                        on_progress(say)
                    except Exception:                    # noqa: BLE001
                        pass
            result = box.run(c["name"], c["args"])
            items.append(llm.tool_result_item(c["call_id"], result))

        if box.trace.asked:
            # 되묻기가 걸렸다. 더 부를 이유가 없다.
            out.ask = box.trace.asked
            out.stopped = "ask_user"
            break
        if out.stopped == "max_calls":
            break
    else:
        out.stopped = "max_rounds"

    # 바퀴를 다 썼거나 시간이 다 됐는데 답이 없다 —
    # 모은 것으로 한 번만 더, 도구 없이 쓰게 한다.
    if not out.answer and not out.ask:
        out.answer = _finish(items, out)

    return out


# 안전장치가 걸렸을 때 사용자에게 보이는 말 (설계도 부록 16).
#   "안 걸리면 생기는 일" 만 정해 두고 걸렸을 때 할 말이 없으면,
#   그 순간 화면은 그냥 멈춘 것처럼 보인다.
STOP_SAY = {
    "time_budget": "여기까지 확인했습니다. 어느 쪽을 더 볼까요?",
    "max_rounds": "여기까지 확인했습니다. 어느 쪽을 더 볼까요?",
    "max_calls": "여기까지 확인했습니다. 어느 쪽을 더 볼까요?",
}


def _finish(items: list[Any], out: Result) -> str:
    """도구 없이 마무리 한 번. 여기서도 실패하면 사유를 그대로 돌려준다."""
    # ★ 예산이 다 됐을 때는 **빈손으로 끝내지 않는다**(설계도 부록 10).
    #   세 갈래 중 ②를 고른다 — 확인한 항목을 나열하고 되묻는다.
    #   부분 답변만 주면 사용자가 다음에 뭘 할지 모르고, 재시도 버튼만 주면
    #   지금까지 조회한 것이 버려진다. ②는 둘 다 피하고 다음 바퀴의 입력도 얻는다.
    partial = out.stopped in STOP_SAY
    ask = ("\n\n마지막에 **확인한 항목을 한 줄로 나열하고**, "
           "어느 쪽을 더 볼지 한 가지만 되물어라. 빈손으로 끝내지 마라."
           if partial else "")
    items = list(items) + [{
        "role": "user",
        "content": "더 조회하지 말고, 지금까지 받은 도구 결과만으로 답하라. "
                   "부족한 축은 '아직 측정 자료가 없습니다' 라고 밝혀라." + ask,
    }]
    res = llm.respond(INSTRUCTIONS, items, timeout=CALL_TIMEOUT,
                      **llm.role("orchestrator"))
    if res and res.get("text"):
        return res["text"].strip()
    # 지어내지 않는다. 왜 못 했는지만 말한다.
    if out.stopped in STOP_SAY:
        return STOP_SAY[out.stopped]
    if str(out.stopped).startswith("llm_"):
        return "지표를 불러오지 못했습니다. 다시 시도할까요?"
    return ("지금은 답을 만들지 못했습니다 "
            f"({out.stopped or 'unknown'}). 잠시 뒤 다시 물어봐 주세요.")
