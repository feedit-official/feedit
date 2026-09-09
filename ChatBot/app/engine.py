"""질문 하나를 받아 답 하나를 돌려준다. 서비스의 입구.

Luna(LLM)는 네 자리에만 쓴다. 넷 다 **없어도 돌아간다.**
    ① 의도 분류   규칙이 못 잡을 때만        nlu.py
    ② 어투 다듬기 값을 꽂은 뒤 문장만        polish.py    숫자는 자리표시자로 봉인
    ③ 웹 검색     지식 질문                websearch.py 출처 없으면 안 올린다
    ④ 맥락 해석   정규식으로도 못 이은 후속 질문 · 잡담만   context.py
                 마지막 수단으로만 부르고, 이미 사전을 통과했던 term 밖은
                 고를 수 없게 스키마로 막는다.

LLM 이 하지 않는 것
    · 지표 해석 — 온도 86점이 무슨 뜻인지는 설계서가 원본이다.
      LLM 에게 맡기면 화면과 챗봇이 다른 말을 한다.
    · 엔티티 결정 — 4종 축 게이트는 사전이 정한다.
    · 숫자 — 값은 서버가 DB 에서 직접 꽂는다.
"""
from __future__ import annotations

from . import context, followup, history, llm, mdclean, plans, polish, report, websearch
from .lexicon_gate import LexiconGate
from .nlu import classify
from .intents import is_salmal_question, is_greeting, GENERAL_CODES, SALMAL_CODES
from .store import ReadOnlyStore


class ChatEngine:
    def __init__(self, store: ReadOnlyStore | None = None, *, use_llm: bool = True):
        self.store = store or ReadOnlyStore()
        self.gate = LexiconGate(self.store)
        self.use_llm = use_llm
        self.memory = history.Memory()

    # ── 진단 ──────────────────────────────────────────
    def llm_state(self) -> dict:
        return {"enabled": self.use_llm, "key": llm.key_hint(),
                "model": llm.MODEL, "last_error": llm.LAST_ERROR}

    # ── 본체 ──────────────────────────────────────────
    def ask(self, question: str, mode: str = "general", plan: str = plans.FREE,
            *, conversation_id: str | None = None,
            history_in: list | None = None) -> dict:
        q = " ".join(str(question or "").split())
        if not q:
            return {"ok": False, "reason": "EMPTY", "message": "질문을 입력해 주세요."}
        if len(q) > 500:
            return {"ok": False, "reason": "TOO_LONG",
                    "message": "질문은 500자 이하로 입력해 주세요."}

        # 앞 턴. 클라이언트가 보낸 것이 있으면 그쪽을 믿는다 —
        # 사용자의 세션 목록이 원본이고, 서버 메모리는 프로세스가 죽으면 사라진다.
        past = history.sanitize(history_in) if history_in else self.memory.recent(conversation_id)

        # ★ 사전 게이트를 먼저 본다. 사전 단어가 하나도 없고 이어받을 대화까지 있으면
        #   맨 아래 ④ 맥락 해석(context.py)이 마지막에 LLM 을 부를 것이다. 그 경우
        #   의도 분류(nlu)에서도 LLM 을 부르면 같은 메시지 하나에 LLM 이 두 번 불려
        #   느려지고 비용도 두 배가 된다 — 그때는 여기서 규칙만으로 조용히 넘어간다.
        #   (사전 단어가 있거나, 대화 기록이 없어 ④가 어차피 안 불릴 때는 그대로 쓴다.)
        parsed = self.gate.parse(q)
        skip_nlu_llm = not parsed["search"] and bool(past)
        nlu = classify(q, mode, use_llm=self.use_llm and not skip_nlu_llm)
        intent = nlu["intent"]

        if intent == "meta.capability":
            return self._capability(plan, nlu)
        if intent == "meta.greeting":
            return self._greeting(nlu, mode)

        carried = followup.resolve(q, parsed, nlu, past, mode)

        # ④ 규칙(정규식)으로도 못 이었다 — 잡담인지, 놓친 후속 질문인지 LLM에게 맥락을 묻는다.
        #    마지막 수단으로, 딱 한 번만 부른다. candidate_terms 는 이미 게이트를 통과했던
        #    값뿐이라 사전 밖 단어를 새로 지어낼 수 없다 (context.py 참고).
        if not parsed["search"] and not carried and self.use_llm and past:
            codes = GENERAL_CODES if mode == "general" else SALMAL_CODES
            ctx = context.resolve(q, past, codes, mode=mode)
            if ctx and ctx["kind"] == "smalltalk":
                return self._smalltalk(nlu, ctx["reply"])
            if ctx and ctx["kind"] == "followup":
                names = " · ".join(ctx["refer_terms"])
                carried = {"carried_terms": [{"canonical": c} for c in ctx["refer_terms"]],
                           "intent": ctx["intent"],
                           "why": f"앞 대화 맥락으로 '{names}' 로 읽었습니다."}

        if carried.get("carried_terms"):
            # ★ 되살릴 때도 게이트를 다시 통과시킨다. 앞 턴에 있었다는 이유만으로
            #   사전 밖의 말이 들어오면 안 된다.
            for t in carried["carried_terms"]:
                again = self.gate.parse(t["canonical"])
                if again["search"]:
                    parsed["search"].extend(again["search"])
            if not parsed["search"]:
                carried.pop("carried_terms", None)
                carried.pop("intent", None)
        if carried.get("intent"):
            intent = carried["intent"]
            nlu = dict(nlu, intent=intent, source="followup",
                       followup=carried.get("why"))

        # 사전에 걸린 말이 없으면 여기서 끝난다.
        # ★ 지식 질문이어도 검색으로 우회시키지 않는다 (설계서 3.4).
        if not parsed["search"]:
            out = report.not_in_lexicon(self.gate, self.store, q)
            out["intent"] = intent
            out["question"] = q
            out["nlu"] = nlu
            self._remember(conversation_id, q, intent, mode, [])
            return out

        if intent == "out_of_scope":
            # 사전에는 걸렸는데 모델이 패션 밖이라고 봤다. 사전을 믿는다.
            intent = "metric.level"
            nlu = dict(nlu, intent=intent, overridden="out_of_scope→사전에 걸려 metric.level 로")

        rep = report.compose(self.store, self.gate, q, intent, parsed, plan, mode)
        rep["nlu"] = nlu
        if carried.get("why"):
            # 이어받았다는 사실을 숨기지 않는다. 잘못 이어받았으면 사용자가 바로 안다.
            rep.setdefault("notes", []).insert(
                0, {"code": "FOLLOW_UP", "term": None, "message": carried["why"]})
        self._remember(conversation_id, q, intent, mode, parsed["search"])

        if mode == "general" and is_salmal_question(q):
            rep["hint"] = {
                "code": "MODE_MISMATCH",
                "message": "살지 말지는 살!말? 모드가 더 정확합니다.\n"
                           "가격 · 재고 · 수명주기까지 같이 봅니다.",
                "action": {"type": "switch_mode", "to": "salmal", "label": "살!말? 모드로"},
            }

        # ③ 지식 질문 — 웹에서 찾아 붙인다
        if intent == "knowledge.origin" and self.use_llm:
            self._attach_web(rep, parsed, q, plan, past)

        # ② 어투 다듬기 — 값이 다 꽂힌 뒤에만
        if self.use_llm:
            self._polish(rep)
        return rep

    def _remember(self, conv_id, q, intent, mode, terms):
        if conv_id:
            self.memory.add(conv_id, history.make_turn(q, intent, mode, terms))

    # ── ③ ────────────────────────────────────────────
    def _attach_web(self, rep: dict, parsed: dict, q: str, plan: str, past: list[dict]):
        head = parsed["search"][0]
        # ★ 이 term 을 이미 이전 턴에서 knowledge.origin 으로 설명한 적이 있어야만
        #   "출처는요?" 를 "뜻을 반복하지 말고 출처만" 으로 읽는다. 처음 묻는 term 인데도
        #   그렇게 읽으면 "이미 답한 내용" 이라는 전제 자체가 틀려서 답이 어색해진다.
        prior_discussed = any(
            head["canonical"] in [t.get("canonical") for t in (h.get("terms") or [])]
            and h.get("intent") == "knowledge.origin"
            for h in (past or []))
        got = websearch.ask(head["canonical"], head["facet"], q,
                            prior_discussed=prior_discussed)
        if not got:
            rep["notes"].insert(0, {"code": "WEB_UNAVAILABLE", "term": head["canonical"],
                                    "message": "웹에서 확인하지 못했습니다. 지표만 보여드립니다."})
            return
        if not got.get("answer"):
            rep["notes"].insert(0, {"code": "WEB_NO_SOURCE", "term": head["canonical"],
                                    "message": got.get("note") or "확인된 출처가 없습니다."})
            return
        rep["web"] = {"answer": got["answer"], "sources": got["sources"]}
        rep["headline"] = mdclean.first_sentence(got["answer"])
        if got.get("injection_seen"):
            # 읽어 온 글에 지시문이 있었다. 따르지 않았고, 사용자에게 알린다.
            rep["notes"].insert(0, {
                "code": "WEB_INJECTION", "term": head["canonical"],
                "message": "검색된 문서에 지시문이 섞여 있었습니다. 따르지 않았습니다."})

    # ── ② ────────────────────────────────────────────
    def _polish(self, rep: dict):
        head = rep.get("headline")
        if not head:
            return
        ctx = {"intent": rep.get("intent"), "mode": rep.get("kind"),
               "as_of": (rep.get("as_of") or {}).get("metric")}
        new, src = polish.polish(head, context=ctx)
        rep["headline"] = new
        rep["tone"] = src                    # 'llm' 이면 다듬어졌다, 'rule' 이면 원문 그대로

    # ── 인사 ──────────────────────────────────────────
    def _greeting(self, nlu: dict, mode: str = "general") -> dict:
        example = ('"이 자켓 사도 될까?", "지금 안 사면 후회할까?"' if mode == "salmal"
                   else '"카고팬츠 요즘 어때?", "고프코어 얼마나 뜨거워?"')
        return {"ok": True, "kind": "meta", "intent": "meta.greeting", "nlu": nlu,
                "message": ("안녕하세요! FEEDiT입니다.\n\n"
                            "무엇이 궁금하신가요?\n"
                            f"예) {example}")}

    # ── 잡담 (LLM 이 맥락을 보고 판단했다) ──────────────
    def _smalltalk(self, nlu: dict, reply: str) -> dict:
        return {"ok": True, "kind": "meta", "intent": "meta.smalltalk",
                "nlu": dict(nlu, intent="meta.smalltalk", source="llm_context"),
                "message": reply}

    # ── 능력 안내 ─────────────────────────────────────
    def _capability(self, plan: str, nlu: dict) -> dict:
        p = plans.normalize(plan)
        can = ["지금 얼마나 뜨거운지 (트렌드 온도 · 언급량)",
               "어떤 플랫폼에서 많이 나오는지",
               "그 말이 어떻게 시작됐는지 (웹에서 찾아 출처와 함께)"]
        if p != plans.FREE:
            can += ["오르는 중인지 내리는 중인지", "무엇과 같이 언급되는지 (연관어)",
                    "사려는 사람이 많은지 (구매의향)"]
        return {"ok": True, "kind": "meta", "intent": "meta.capability", "nlu": nlu,
                "message": ("스타일 · 소재 · 아이템 · 브랜드 네 가지 키워드로 트렌드를 답합니다.\n\n"
                            "물어볼 수 있는 것\n" + "\n".join("· " + x for x in can) +
                            "\n\n패션과 무관한 질문은 답하지 않습니다."),
                "plan": p}
