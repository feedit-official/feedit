"""오케스트레이터가 부를 수 있는 도구들 — 스키마와 디스패치.

── 이 파일이 하는 일 ────────────────────────────────────────
`store.py` 의 조회 함수에 **JSON 스키마를 씌우는 얇은 층**이다.
조회 로직을 여기 새로 쓰지 않는다. store.py 는 그대로 두고, 모델이
고를 수 있는 형태로 이름과 인자만 정리한다.

── 왜 도구인가 (설계도 원칙 1·2·3) ──────────────────────────
예전 구조는 정규식으로 의도를 **확정**하고 그 의도에 맞는 블록을 그렸다.
근거를 보기 전에 되돌릴 수 없는 결정을 하는 셈이라, 축이 여러 개인 질문
("살로몬 XT-6 지금 사도 돼?" — 할인률·수명주기·리세일 셋 다)에서 깨졌다.

도구는 다르다. 0번도 3번도 부를 수 있고, 결과를 보고 방향을 바꿀 수 있다.
그래서 여기 있는 것들은 전부 **갈림길이 아니라 함수**다:

  · 사전 조회(search_terms)도 게이트가 아니라 도구다.
    못 찾았다고 대화가 끝나지 않는다 — 모델이 rank_terms 로 갈아탈 수 있다.
  · 되묻기(ask_user)도 도구다. 실패 경로가 아니라 선택 가능한 행동이다.
  · "없음"(declare_missing)도 도구다. 지어내는 대신 없다고 기록한다.

── 지어내기를 구조로 막는다 ─────────────────────────────────
체형·사이즈·후기는 우리 데이터에 없다. 그러면 **도구를 만들지 않는다.**
도구가 없으면 오케스트레이터는 그 축을 부를 수 없고, 부를 수 없으면
아래 층이 지어낼 기회도 없다. 대신 declare_missing 이 남긴 기록을
verify.py 가 "그 축 얘기는 지운다"의 근거로 쓴다.

호출 기록(TraceLog)은 반드시 원본 그대로 남긴다. 검증관이 대조할
원본이 없으면 검증이 통과 도장으로 전락한다.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable

from .config import MIN_OBS_7, MIN_OBS_14, MIN_OBS_28, THIN_SAMPLE, temp_band

# ══════════════════════════════════════════════════════════
#  스키마
# ══════════════════════════════════════════════════════════
#  Responses API 의 function tool 형식이다.
#  strict 를 켜면 목록 밖 값을 모델이 아예 못 뱉는다 — 이게 모델 크기보다
#  정확도에 더 크게 작용한다(설계도 05).

AXES = ["온도", "모멘텀", "순위", "연관어", "긍부정", "출처별", "근거"]

# ══════════════════════════════════════════════════════════
#  말해도 되는 문장 — 표현 자체를 조건에 묶는다
# ══════════════════════════════════════════════════════════
#  ★ 왜 이게 도구 응답에 들어가나 (설계도 부록 14)
#    verify.py 는 **숫자가 도구 결과에 있는지**만 본다. 그런데 사용자를
#    움직이는 문장은 "2주째 내려오는 중이고 구매 의향이 82%니 지금이
#    나쁘지 않다" 같은 **인과와 권유**다. 숫자가 전부 맞아도 이 결론은
#    틀릴 수 있고, 구매를 유도하므로 책임이 따른다.
#
#    대조로는 못 막는다. 그래서 **어떤 문장을 써도 되는지를 데이터가
#    직접 말하게** 한다. 모델이 판단 문장을 지어내기 전에, 이 조건에서
#    허용되는 표현이 무엇인지 응답에 함께 온다.
#
#  백분위 상위 = pct_rank >= 0.5

def _say_rule(pct_rank, momentum, thin: bool) -> dict:
    """이 지표 조합에서 허용되는 표현과 권유 가능 여부."""
    if thin:
        # 표본이 임계 아래면 판단 문장 자체를 막는다.
        return {"allowed": "관측만 적는다",
                "recommend": "금지",
                "note": "표본이 적어 판단 문장을 쓰지 마세요. 관측된 수치만 적으세요."}
    if pct_rank is None or momentum is None:
        return {"allowed": "관측만 적는다", "recommend": "금지",
                "note": "백분위나 모멘텀이 없어 방향을 말할 수 없습니다."}
    high = float(pct_rank) >= 0.5
    up = float(momentum) > 0
    if high and up:
        return {"allowed": "지금 올라오는 중입니다", "recommend": "가능", "note": ""}
    if high and not up:
        return {"allowed": "정점을 지나는 중입니다", "recommend": "조건부",
                "note": "권유하려면 얼마나 남았는지 기간을 함께 적으세요."}
    if not high and up:
        return {"allowed": "이제 올라오기 시작했습니다", "recommend": "조건부",
                "note": "아직 절대량이 적다는 점을 함께 적으세요."}
    return {"allowed": "내려가는 중입니다", "recommend": "금지",
            "note": "내려가는 중인 것을 권하지 마세요. 사실만 적으세요."}
FACETS = ["style", "material", "item", "brand"]


def _fn(name: str, desc: str, props: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": desc,
        "strict": True,
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": props,
            "required": required,
        },
    }


SPECS: list[dict] = [
    _fn(
        "search_terms",
        "질문에 나온 말을 사전에서 찾아 정확한 표기와 축을 돌려준다. "
        "지표를 조회하려면 이 표기가 있어야 한다. 별칭·오타도 잡는다. "
        "결과가 비어도 실패가 아니다 — 용어를 지목하지 않는 질문일 수 있다.",
        {"q": {"type": "string", "description": "사용자 질문 원문 또는 그 일부"}},
        ["q"],
    ),
    _fn(
        "rank_terms",
        "지금 온도가 높은 용어를 순서대로 돌려준다. "
        "'요즘 뭐가 핫해' '뜨는 브랜드' 처럼 답이 용어인 질문에 쓴다. "
        "질문이 용어를 지목하지 않았을 때 search_terms 대신 이것을 쓴다.",
        {
            "facet": {"type": ["string", "null"], "enum": FACETS + [None],
                      "description": "축을 좁힐 때만. 전체면 null"},
            "limit": {"type": "integer", "description": "몇 개까지. 기본 10"},
        },
        ["facet", "limit"],
    ),
    _fn(
        "get_metric",
        "한 용어의 지표를 가져온다. axes 를 여러 개 넣으면 한 번에 가져온다. "
        "판단이 필요한 질문일수록 여러 축을 함께 넣어야 한다 — "
        "'지금 사도 돼?' 는 온도만으로는 답이 안 된다.",
        {
            "term": {"type": "string", "description": "search_terms 가 준 정확한 표기"},
            "axes": {"type": "array", "items": {"type": "string", "enum": AXES},
                     "description": "필요한 축들. 여러 개 가능"},
        },
        ["term", "axes"],
    ),
    _fn(
        "get_evidence",
        "그 용어가 실제로 어떻게 언급됐는지 원문 조각을 가져온다. "
        "판단의 근거를 사람이 직접 확인할 수 있게 할 때 쓴다. "
        "각 항목은 플랫폼·시점·원문·url 을 준다. url 은 되돌아갈 수 있을 때만 채워지며, "
        "빈 항목은 링크 없이 인용하고 주소를 지어내지 않는다.",
        {"term": {"type": "string"},
         "limit": {"type": "integer", "description": "기본 3"}},
        ["term", "limit"],
    ),
    _fn(
        "get_salmal",
        "살!말? 카드 하나의 투표 현황과 상품 정보를 가져온다. "
        "사용자가 살!말? 화면에서 넘어왔을 때(컨텍스트에 salmal_card_id 가 있을 때) 쓴다.",
        {"card_id": {"type": "integer"}},
        ["card_id"],
    ),
    _fn(
        "search_salmal",
        "같은 아이템·브랜드로 올라온 다른 살!말? 고민들을 찾는다. "
        "'사람들은 뭐래?' 같은 질문에 쓴다.",
        {"term": {"type": "string"}, "limit": {"type": "integer"}},
        ["term", "limit"],
    ),
    _fn(
        "get_user_taste",
        "로그인한 사용자의 취향 가중치를 가져온다. "
        "'나한테 어울려?' '내 취향이야?' 의 유일한 근거다. "
        "비로그인이면 비어서 돌아온다 — 그때는 취향 얘기를 하지 않는다.",
        {},
        [],
    ),
    _fn(
        "web_search",
        "사전 밖 지식이나 최신 소식을 웹에서 찾는다. "
        "우리 지표로 답할 수 없는 질문에 쓴다. 출처를 함께 돌려주며, "
        "이 결과는 FEEDiT 측정값이 아니므로 답변에서 그렇게 밝혀야 한다.",
        {"q": {"type": "string"}},
        ["q"],
    ),
    _fn(
        "ask_user",
        "무엇을 볼지 되묻는다. 실패가 아니라 정상 행동이다. "
        "'이거 어때?' 처럼 정보가 질문에 없어 어떤 모델도 풀 수 없을 때 쓴다. "
        "추측해서 엉뚱한 용어로 답하지 말고 이것을 부른다.",
        {
            "question": {"type": "string", "description": "되물을 한 문장"},
            "options": {"type": "array", "items": {"type": "string"},
                        "description": "고를 수 있는 보기 2~4개. 없으면 빈 배열"},
        },
        ["question", "options"],
    ),
    _fn(
        "declare_missing",
        "그 축은 우리 데이터에 없다고 기록한다. 지어내는 대신 이것을 부른다. "
        "기록해 두면 답변에서 '아직 측정 자료가 없습니다' 로 정직하게 말할 수 있다.",
        {"term": {"type": "string"},
         "axis": {"type": "string", "description": "없는 축 이름 (예: 리세일, 체형, 사이즈)"},
         "reason": {"type": "string", "description": "왜 없는지 한 줄"}},
        ["term", "axis", "reason"],
    ),
]

NAMES = [s["name"] for s in SPECS]


# ══════════════════════════════════════════════════════════
#  지금 무엇을 하고 있는지 — 사용자의 말로
# ══════════════════════════════════════════════════════════
#  ★ 왜 필요한가 (설계도 부록 10)
#    도구 루프는 답이 완성될 때까지 화면에 아무것도 안 보낸다. 3초 무반응은
#    이미 고장난 화면이다. 같은 3.4초라도 무엇을 하고 있는지 보이면 기다림이 된다.
#
#    부수 효과가 더 크다 — 어떤 데이터를 봤는지가 답변 **전에** 드러나므로
#    대기 시간이 신뢰의 재료로 바뀐다. L3 가 뒤에서 하는 대조는 사용자가 못
#    보지만, L1 이 무엇을 불렀는지는 보여 줄 수 있다.
#
#  ⚠ 도구 이름을 그대로 쓰지 않는다. `get_metric` 이 아니라 "온도 보는 중".
FACET_SAY = {"style": "스타일", "material": "소재", "item": "아이템", "brand": "브랜드"}
AXIS_SAY = {"온도": "온도", "모멘텀": "추세", "순위": "순위", "연관어": "연관어",
            "긍부정": "반응", "출처별": "플랫폼별", "근거": "실제 언급"}


def progress_say(name: str, args: dict) -> str | None:
    """도구 호출 하나를 사람이 읽는 한 줄로. 보여 줄 게 없으면 None."""
    args = args or {}
    term = str(args.get("term") or "").strip()
    head = f"{term} " if term else ""
    if name == "search_terms":
        return "말을 사전에서 찾는 중"
    if name == "rank_terms":
        f = FACET_SAY.get(args.get("facet") or "")
        return f"지금 뜨는 {f} 세는 중" if f else "지금 뜨는 것 세는 중"
    if name == "get_metric":
        axes = [AXIS_SAY.get(a, a) for a in (args.get("axes") or [])]
        return f"{head}{' · '.join(axes[:3]) or '지표'} 보는 중"
    if name == "get_evidence":
        return f"{head}실제 언급 찾는 중"
    if name == "get_salmal":
        return "살!말? 투표 보는 중"
    if name == "search_salmal":
        return f"{head}비슷한 고민 찾는 중"
    if name == "get_user_taste":
        return "취향에 맞춰 보는 중"
    if name == "web_search":
        return "밖에서 찾아보는 중"
    # ask_user · declare_missing 은 조회가 아니다. 진행 표시를 낼 것이 없다.
    return None


# ══════════════════════════════════════════════════════════
#  실행
# ══════════════════════════════════════════════════════════

class TraceLog:
    """이번 요청에서 무엇을 불렀고 무엇이 돌아왔나.

    ★ 원본을 그대로 들고 있어야 한다.
      verify.py 가 답변의 숫자를 여기와 대조한다. 요약해서 넣으면
      대조할 것이 없어지고, 검증은 그냥 통과 도장이 된다.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.missing: list[dict] = []       # declare_missing 이 남긴 것
        self.asked: dict | None = None      # ask_user 가 남긴 것

    def add(self, name: str, args: dict, result: Any) -> None:
        self.calls.append({"tool": name, "args": args, "result": result})

    def numbers(self) -> set[str]:
        """도구 결과에 실제로 등장한 숫자들. 검증관이 쓴다."""
        seen: set[str] = set()

        def walk(v: Any) -> None:
            if isinstance(v, dict):
                for x in v.values():
                    walk(x)
            elif isinstance(v, (list, tuple)):
                for x in v:
                    walk(x)
            elif isinstance(v, bool):
                return
            elif isinstance(v, (int, float)):
                seen.add(_numstr(v))
            elif isinstance(v, str) and v.replace(".", "", 1).lstrip("-").isdigit():
                seen.add(_numstr(float(v) if "." in v else int(v)))

        walk(self.calls)
        return seen

    def terms(self) -> set[str]:
        """도구 결과에 등장한 용어·라벨. 없는 말을 지어냈는지 볼 때 쓴다."""
        out: set[str] = set()
        for c in self.calls:
            for k in ("term", "q"):
                if isinstance(c["args"].get(k), str):
                    out.add(c["args"][k])
            _collect_labels(c["result"], out)
        return out

    def as_payload(self) -> list[dict]:
        return self.calls


def _numstr(v: float | int) -> str:
    """1.0 과 1 을 같은 것으로 본다. 검증에서 헛걸림을 줄인다."""
    f = float(v)
    return str(int(f)) if f == int(f) else f"{f:.2f}".rstrip("0").rstrip(".")


def _collect_labels(v: Any, out: set[str]) -> None:
    KEYS = ("canonical", "assoc_canonical", "label", "title", "brand", "source_code")
    if isinstance(v, dict):
        for k, x in v.items():
            if k in KEYS and isinstance(x, str) and x:
                out.add(x)
            else:
                _collect_labels(x, out)
    elif isinstance(v, (list, tuple)):
        for x in v:
            _collect_labels(x, out)


class Toolbox:
    """도구 이름 → 실제 함수.

    store·gate 는 밖에서 넣는다. 이 파일이 SQLite 를 직접 열지 않는다 —
    나중에 RDS(Django ORM)로 옮길 때 store.py 만 갈아 끼우면 되도록.

    salmal·taste 는 아직 원본이 없다(RDS 쪽 표는 있으나 챗봇이 안 본다).
    없는 채로 부르면 **비어 있음**을 돌려준다. 죽지 않고, 지어내지도 않는다.
    """

    def __init__(self, store, gate, ctx: dict | None = None,
                 salmal=None, taste=None, websearch=None) -> None:
        self.store = store
        self.gate = gate
        self.ctx = ctx or {}
        self.salmal = salmal
        self.taste = taste
        self.websearch = websearch
        self.trace = TraceLog()

    # ── 디스패치 ────────────────────────────────────────
    def run(self, name: str, args: dict) -> Any:
        fn: Callable | None = getattr(self, f"t_{name}", None)
        if fn is None:
            # 모델이 없는 도구를 부르는 일은 실제로 일어난다.
            # 죽이지 말고 사실대로 알려 주면 다음 바퀴에서 고쳐 부른다.
            result = {"error": "없는 도구입니다", "available": NAMES}
        else:
            try:
                result = fn(**args)
            except TypeError as e:
                result = {"error": f"인자가 맞지 않습니다: {e}"}
            except Exception as e:                      # noqa: BLE001
                # 도구 하나가 죽어도 대화는 계속돼야 한다.
                result = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
        self.trace.add(name, args, result)
        return result

    # ── 사전 ────────────────────────────────────────────
    def t_search_terms(self, q: str) -> dict:
        parsed = self.gate.parse(q)
        hits = [{"term": h["canonical"], "facet": h["facet"], "term_key": h["term_key"]}
                for h in parsed.get("search", [])]
        out: dict[str, Any] = {"found": hits, "count": len(hits)}
        if not hits:
            # 못 찾았다고 끝이 아니다. 가까운 말과 인기어를 같이 준다 —
            # 모델이 되묻거나 rank_terms 로 갈아탈 재료가 된다.
            out["near"] = self.gate.near_candidates(q, limit=3)
            out["popular"] = self.gate.popular(self.store, limit=3)
            out["hint"] = ("용어를 지목하지 않은 질문일 수 있습니다. "
                           "'요즘 뭐가 핫해' 류면 rank_terms 를 쓰세요.")
        # 수식어(핏·색·TPO)는 검색어가 아니지만 답변 톤에 쓰인다
        out["modifiers"] = [h["canonical"] for h in parsed.get("modifier", [])]
        return out

    def t_rank_terms(self, facet: str | None = None, limit: int = 10) -> dict:
        n = max(1, min(int(limit or 10), 20))
        rows = self.store.top_terms(facet=facet or None, limit=n)
        day = self.store.latest_day()
        return {
            "as_of": day,
            "asked": n,
            "returned": len(rows),
            # ★ 요청한 수보다 적을 수 있다. 그 사실을 명시한다 —
            #   안 그러면 모델이 나머지를 채워 넣는다.
            "short_of_asked": len(rows) < n,
            "items": [{"term": r["canonical"], "facet": r["facet"],
                       "temp": r["temp"], "band": temp_band(r["temp"]),
                       "raw_count": r["raw_count"]} for r in rows],
        }

    # ── 지표 ────────────────────────────────────────────
    def t_get_metric(self, term: str, axes: list[str]) -> dict:
        key = self.gate.term_key(term)
        latest = self.store.term_latest(key)
        if not latest:
            # ★ 키 이름을 found 로 쓰지 않는다.
            #   search_terms 는 found 를 **목록**으로 준다. 같은 이름으로 여기서
            #   불리언을 주면 결과를 훑는 코드가 bool 을 순회하려다 터지고,
            #   모델도 두 도구의 found 를 같은 뜻으로 읽는다.
            #   (2026-09-09 실측: agent_path._terms_from 이 이걸로 죽었다)
            return {"term": term, "has_metric": False,
                    "reason": "이 용어는 사전에는 있지만 아직 측정된 지표가 없습니다."}

        day = latest.get("observed_on")
        n7 = self.store.obs_count(key, 7, day)
        n14 = self.store.obs_count(key, 14, day)
        n28 = self.store.obs_count(key, 28, day)
        out: dict[str, Any] = {
            "term": term, "has_metric": True, "as_of": day,
            "observations": {"n7": n7, "n14": n14, "n28": n28},
            # ★ 관측이 모자라면 그 축은 **말하면 안 된다.** config 의 실측 기준이다.
            "may_say": {"수준": n7 >= MIN_OBS_7,
                        "2주변화": n14 >= MIN_OBS_14,
                        "방향": n28 >= MIN_OBS_28},
            "thin_sample": (latest.get("raw_count") or 0) < THIN_SAMPLE,
        }
        # ★ 기준선을 같이 준다 (설계도 부록 11).
        #   "온도 71°" 만으로는 높은 건지 낮은 건지 **사용자가 모른다.**
        #   pct_rank 는 이미 term_latest 가 주고 있었는데 꺼내 쓰지 않았다.
        pct = latest.get("pct_rank")
        thin = out["thin_sample"]
        want = set(axes or [])
        if "온도" in want:
            out["온도"] = {
                "temp": latest.get("temp"),
                "band": temp_band(latest.get("temp")),
                # 71 이 무슨 뜻인지 — 같은 축에서 몇 등인가
                "percentile": pct,
                "rank_text": (None if pct is None else
                              f"같은 축에서 상위 {max(1, round((1 - float(pct)) * 100))}%"),
                # 지난주와 견주면 방향이 보인다
                "delta_1w": self._delta_1w(key, latest),
                # 표본 — 12건으로 낸 71° 와 1,240건으로 낸 71° 는 다르다
                "sample_n": latest.get("raw_count"),
                "as_of": day,
            }
        if "모멘텀" in want:
            out["모멘텀"] = ({"momentum": latest.get("momentum"),
                            "ma7": latest.get("ma7"), "ma28": latest.get("ma28")}
                           if n28 >= MIN_OBS_28 else
                           {"unavailable": f"28일 관측 {n28}건 — 방향을 말하기엔 모자랍니다."})
        if "순위" in want:
            out["순위"] = {"pct_rank": latest.get("pct_rank"), "level": latest.get("level")}
        if "출처별" in want:
            out["출처별"] = self.store.term_sources(key)
        if "연관어" in want:
            out["연관어"] = self.store.term_assoc(key, limit=8)
        if "긍부정" in want:
            s = self.store.term_sentiment(key)
            out["긍부정"] = s or {"unavailable": "감성 지표가 아직 없습니다."}
        if "근거" in want:
            out["근거"] = self.store.term_evidence(key, limit=3)

        # ★ 이 조건에서 써도 되는 문장. 모델이 판단을 지어내기 전에 준다.
        out["말할_수_있는_것"] = _say_rule(pct, latest.get("momentum"), thin)
        return out

    def _delta_1w(self, key: str, latest: dict):
        """지난주 대비 온도 변화. 관측이 없으면 None — 0 으로 채우지 않는다."""
        try:
            rows = self.store.term_series(key, days=14)
        except Exception:                                # noqa: BLE001
            return None
        now = latest.get("temp")
        if now is None or len(rows) < 2:
            return None
        # rows 는 최신순. 7일 전에 가장 가까운 것을 고른다.
        past = rows[min(7, len(rows) - 1)]
        if past.get("temp") is None:
            return None
        return round(float(now) - float(past["temp"]), 1)

    def t_get_evidence(self, term: str, limit: int = 3) -> dict:
        """근거 원문 조각. 링크는 **있는 것만** 붙인다.

        ★ 왜 url 이 None 인 채로 그냥 나가나
          store.evidence_link() 는 되돌아갈 수 있는 주소만 만든다. 네이버는
          product_uid 가 'kw:<검색어>' 라 글 자체를 가리키지 못한다(전체의 약 40%).
          여기서 "네이버 블로그 검색 결과" 같은 그럴듯한 주소를 지어 붙이면,
          누른 사람은 우리가 인용한 글이 아닌 곳에 떨어진다. 틀린 숫자와 같은 종류의
          거짓말이다. 그래서 없으면 없는 채로 내보내고, 몇 개가 확인 가능한지
          linkable 로 함께 알려 준다 — 모델이 "3건 중 2건은 원문 확인 가능" 이라고
          정직하게 쓸 수 있도록.
        """
        key = self.gate.term_key(term)
        rows = self.store.term_evidence(key, limit=max(1, min(int(limit or 3), 8)))
        items = []
        for r in rows:
            it = {"platform": r.get("platform") or r.get("source_code"),
                  "at": r.get("at"),
                  "body": r.get("body"),
                  "sentiment": r.get("sentiment"),
                  "url": r.get("url")}
            if not it["url"]:
                it["url_note"] = "원문 링크 없음"
            items.append(it)
        linkable = sum(1 for it in items if it.get("url"))
        return {"term": term, "count": len(items), "linkable": linkable,
                "items": items,
                "link_rule": "url 이 있는 항목만 링크로 쓸 수 있다. "
                             "url 이 없으면 '(원문 링크 없음)' 이라고 적고, "
                             "주소를 짐작해서 만들지 마라."}

    # ── 살!말? ──────────────────────────────────────────
    def t_get_salmal(self, card_id: int) -> dict:
        if self.salmal is None:
            return {"unavailable": "살!말? 데이터 연결이 아직 없습니다.",
                    "card_id": card_id}
        return self.salmal.card(int(card_id))

    def t_search_salmal(self, term: str, limit: int = 5) -> dict:
        if self.salmal is None:
            return {"unavailable": "살!말? 데이터 연결이 아직 없습니다.", "term": term}
        return self.salmal.search(term, limit=max(1, min(int(limit or 5), 10)))

    def t_get_user_taste(self) -> dict:
        uid = self.ctx.get("user_id")
        if not uid:
            return {"logged_in": False,
                    "note": "비로그인 상태입니다. 취향을 근거로 말하지 마세요."}
        if self.taste is None:
            return {"logged_in": True,
                    "unavailable": "취향 데이터 연결이 아직 없습니다."}
        return self.taste.of(uid)

    # ── 밖 ──────────────────────────────────────────────
    def t_web_search(self, q: str) -> dict:
        if self.websearch is None:
            return {"unavailable": "웹 검색이 꺼져 있습니다."}
        hits = self.websearch(q)
        return {"q": q, "from": "web", "not_feedit_data": True, "items": hits}

    # ── 대화 행동 ───────────────────────────────────────
    def t_ask_user(self, question: str, options: list[str]) -> dict:
        self.trace.asked = {"question": question, "options": options or []}
        return {"ok": True, "note": "되묻기를 준비했습니다. 여기서 도구 호출을 멈추세요."}

    def t_declare_missing(self, term: str, axis: str, reason: str) -> dict:
        self.trace.missing.append({"term": term, "axis": axis, "reason": reason})
        return {"ok": True, "note": f"'{axis}' 는 없는 것으로 기록했습니다. "
                                    "답변에서 그 축의 값을 말하지 마세요."}


# ══════════════════════════════════════════════════════════
#  OpenAI 가 서버 쪽에서 직접 돌려 주는 도구들
# ══════════════════════════════════════════════════════════
#  우리가 실행하지 않는다. tools 목록에 넣어 두면 모델이 알아서 부르고,
#  결과는 output 안에 web_search_call · mcp_call 같은 항목으로 되돌아온다.
#  그래서 Toolbox.run() 을 거치지 않는다 — 디스패치할 것이 없다.
#
#  ★ 왜 이걸 쓰나
#    web_search 는 우리가 만든 websearch.py 보다 최신 소식에 강하고, 무엇보다
#    출처를 붙여 준다. "오늘 날씨" 같은 사전 밖 질문에서 이게 답이 된다.
#    MCP 는 우리가 코드를 짜지 않고도 바깥 도구를 붙일 수 있는 길이다.
#
#  ⚠ MCP 는 **환경변수에 적은 서버만** 붙는다.
#    require_approval 을 "never" 로 두면 사람 확인 없이 실행된다. 챗봇에는
#    승인 UI 가 없어서 "always" 로 두면 아무것도 못 부르기 때문인데,
#    그만큼 **읽기 전용 서버만** 적어야 한다. 쓰기가 되는 서버를 여기 넣으면
#    사용자 문장 하나가 그대로 실행 명령이 된다.
#    allowed_tools 로 부를 수 있는 것을 좁혀 두는 편이 안전하다.

def _mcp_servers() -> list[dict]:
    """FEEDIT_MCP_SERVERS — JSON 배열. 없으면 MCP 를 아예 안 붙인다.

        FEEDIT_MCP_SERVERS='[{"label":"musinsa","url":"https://.../mcp",
                              "description":"무신사 상품 조회",
                              "allowed_tools":["search_product"]}]'
    """
    raw = (os.getenv("FEEDIT_MCP_SERVERS") or "").strip()
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except (TypeError, ValueError):
        # 오타 하나로 챗봇이 통째로 죽지 않게 한다. MCP 만 빠진다.
        return []
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if not isinstance(it, dict) or not it.get("url"):
            continue
        spec: dict[str, Any] = {
            "type": "mcp",
            "server_label": str(it.get("label") or "mcp"),
            "server_url": str(it["url"]),
            "server_description": str(it.get("description") or ""),
            # 승인 UI 가 없다. 대신 환경변수에 적은 것만 붙는다는 게 승인이다.
            "require_approval": str(it.get("require_approval") or "never"),
        }
        if it.get("allowed_tools"):
            spec["allowed_tools"] = list(it["allowed_tools"])
        if it.get("authorization"):
            spec["authorization"] = str(it["authorization"])
        out.append(spec)
    return out


def hosted_specs() -> list[dict]:
    """모델이 서버 쪽에서 직접 쓰는 도구들."""
    out: list[dict] = []
    if (os.getenv("FEEDIT_TOOL_WEB_SEARCH") or "1").strip() not in ("0", "false", "no"):
        out.append({"type": "web_search"})
    out.extend(_mcp_servers())
    return out


def specs_for(ctx: dict | None = None) -> list[dict]:
    """컨텍스트에 맞는 도구만 준다.

    ★ 모드로 라우팅하지 않는다(설계도 03·L1).
      살!말? 카드에서 넘어왔으면 살말 도구가 목록에 있고, 아니면 없다.
      일반/살말을 정규식으로 가르던 is_salmal_question() 이 하던 일을
      **도구 목록의 유무**가 대신한다.
    """
    ctx = ctx or {}
    drop = set()
    if not ctx.get("salmal_card_id"):
        drop.add("get_salmal")
    if not ctx.get("user_id"):
        drop.add("get_user_taste")
    hosted = hosted_specs()
    # ★ 이름이 겹치면 안 된다.
    #   우리 함수 web_search 와 내장 도구 {"type":"web_search"} 가 같은 이름이라,
    #   둘 다 넣으면 모델이 어느 쪽을 부를지 모르고 API 도 거부한다.
    #   내장 쪽이 낫다 — 출처를 붙여 주고 최신 소식에 강하다. 우리 것은
    #   내장을 껐을 때(FEEDIT_TOOL_WEB_SEARCH=0)만 남긴다.
    if any(h.get("type") == "web_search" for h in hosted):
        drop.add("web_search")
    ours = [s for s in SPECS if s["name"] not in drop]
    # 우리 함수 + OpenAI 가 직접 돌리는 것. 모델에게는 구분 없이 한 목록이다.
    return ours + hosted
