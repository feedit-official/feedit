"""대화 기억 — 바로 앞 몇 턴만.

왜 필요한가
  "발레코어는 지금 유행이야?" 다음에 "그러면 고프코어는?" 이 오면
  사람은 같은 질문을 다른 말에 대해 다시 묻는 것으로 읽는다.
  앞 턴이 없으면 규칙도 LLM 도 "고프코어가 뭐냐" 로 읽는다. 실제로 그렇게 답했다.

무엇을 기억하나 — 세 가지뿐이다.
  · 무엇을 물었나 (intent)
  · 무엇에 대해 물었나 (사전에 걸린 term)
  · 원문 (사용자에게 "앞 질문을 이어받았다" 고 보여 주려고)
답변 본문은 기억하지 않는다. 다음 답을 만들 때 쓰이지 않는데 들고 있으면
언젠가 그걸 근거 삼아 말하게 된다.

수명
  대화당 8턴, 2시간, 전체 500대화. 개발 서버는 프로세스 메모리다.
  ★ 여기가 진실의 원본이 되면 안 된다. 서버가 죽으면 사라지는 것이 맞다.
    클라이언트도 최근 턴을 같이 보내므로(engine.ask(history=…)) 그때는 그쪽을 쓴다.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque

MAX_TURNS = 8
TTL_SEC = 2 * 60 * 60
MAX_CONV = 500


def make_turn(question: str, intent: str, mode: str, terms: list[dict]) -> dict:
    return {
        "q": " ".join(str(question or "").split())[:200],
        "intent": intent,
        "mode": mode,
        "terms": [{"canonical": t.get("canonical"), "facet": t.get("facet"),
                   "term_key": t.get("term_key")} for t in (terms or [])][:4],
        "at": time.time(),
    }


class Memory:
    def __init__(self, max_turns: int = MAX_TURNS, ttl: int = TTL_SEC,
                 max_conv: int = MAX_CONV):
        self.max_turns, self.ttl, self.max_conv = max_turns, ttl, max_conv
        self._c: OrderedDict[str, deque] = OrderedDict()
        self._lock = threading.Lock()

    def recent(self, conv_id: str | None) -> list[dict]:
        if not conv_id:
            return []
        with self._lock:
            d = self._c.get(conv_id)
            if not d:
                return []
            self._c.move_to_end(conv_id)
            now = time.time()
            return [t for t in d if now - t["at"] <= self.ttl]

    def add(self, conv_id: str | None, turn: dict) -> None:
        if not conv_id:
            return
        with self._lock:
            d = self._c.get(conv_id)
            if d is None:
                d = self._c[conv_id] = deque(maxlen=self.max_turns)
            d.append(turn)
            self._c.move_to_end(conv_id)
            while len(self._c) > self.max_conv:
                self._c.popitem(last=False)

    def forget(self, conv_id: str | None) -> None:
        with self._lock:
            self._c.pop(conv_id, None)


def sanitize(raw) -> list[dict]:
    """클라이언트가 보낸 history 를 걸러 받는다.

    ★ 밖에서 온 값이다. intent 를 그대로 믿으면 사용자가 게이트를 우회할 수 있다.
      term 도 canonical 문자열만 받고, 실제로 지표에 있는지는 부르는 쪽이 확인한다.
    """
    out = []
    if not isinstance(raw, list):
        return out
    for t in raw[-MAX_TURNS:]:
        if not isinstance(t, dict):
            continue
        q = " ".join(str(t.get("q") or t.get("question") or "").split())[:200]
        if not q:
            continue
        terms = []
        for x in (t.get("terms") or [])[:4]:
            if isinstance(x, dict) and x.get("canonical"):
                terms.append({"canonical": str(x["canonical"])[:40],
                              "facet": str(x.get("facet") or "")[:16] or None,
                              "term_key": str(x.get("term_key") or "")[:60] or None})
            elif isinstance(x, str):
                terms.append({"canonical": x[:40], "facet": None, "term_key": None})
        out.append({"q": q, "intent": str(t.get("intent") or "")[:32] or None,
                    "mode": "salmal" if t.get("mode") == "salmal" else "general",
                    "terms": terms, "at": time.time()})
    return out
