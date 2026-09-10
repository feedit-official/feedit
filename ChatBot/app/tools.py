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

from . import season as season_ref     # 인자 이름(season)과 겹치지 않게
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
# similar_terms 가 훑어볼 후보 수. 후보마다 연관어를 한 번씩 읽으므로
# 이 값이 곧 SQLite 조회 횟수다. 로컬이라 40이면 수십 ms 다.
CAND_MAX = 40
# similar_terms 가 기준(base)을 고르는 순서. 낮을수록 먼저다.
#   ★ 왜 아이템이 먼저인가 (2026-09-10 실측)
#     "…레이어드 와이드팬츠" 링크에 모델이 **레이어드**(스타일)를 기준으로 넘겼고,
#     "레이어드와 비슷한 것: 스트릿웨어 · 캐주얼 · Y2K" 가 나왔다. 팬츠를 물었는데
#     스타일 목록이 나온 것이다. 어느 축을 기준으로 삼느냐가 답의 종류를 바꾼다.
BASE_ORDER = {"item": 0, "material": 1, "style": 2, "tpo": 3, "fit": 4, "color": 5, "brand": 6}
# 이름 계열을 볼 때 훑는 같은 축 용어 수. item 축이 111개라 200이면 전부 덮는다.
FAMILY_POOL = 200
MIN_SUFFIX = 2          # 공통 꼬리가 이만큼이면 같은 계열로 본다


def _family(base: str, other: str) -> int:
    """이름이 같은 계열인가. 0 이면 아니고, 클수록 강하다.

    ★ 왜 이름을 보나 (2026-09-10)
      "비슷한 것" 의 근거는 연관어 프로필 겹침(2차 연관)이 제일 좋은데,
      실측에서 연관어 표가 얇았다 — 1054행, 'item:팬츠' 는 0개.
      지표에도 사전에도 상의/하의 같은 하위 분류가 **없다**
      (사전이 들고 있는 것: version · surfaces · facet_of · trendable · 차단어).
      그래서 남은 근거가 이름이다. 한국어 패션 용어는 복합어의 **뒤쪽이 범주**인
      경우가 많다 — 와이드팬츠 · 조거팬츠 · 카고팬츠 는 전부 '팬츠' 로 끝난다.
    ★ 완벽하지 않다. '자켓/재킷' 처럼 표기가 갈리면 못 잡고, '블레이저' 는 놓친다.
      **놓치는 것은 괜찮고 틀리게 묶는 것이 문제**라, 기준을 느슨하게 잡지 않는다.
    """
    a = "".join(str(base or "").split())
    b = "".join(str(other or "").split())
    if not a or not b or a == b:
        return 0
    if a in b or b in a:                      # 팬츠 ⊂ 와이드팬츠
        return max(len(a), len(b))
    n = 0
    while n < min(len(a), len(b)) and a[-1 - n] == b[-1 - n]:
        n += 1
    return n if n >= MIN_SUFFIX else 0

# ★ 축을 지목하지 않은 순위("요즘 뭐가 핫해")에서 볼 축.
#   브랜드를 뺀다 — lexicon.yaml 이 브랜드·제품명을 사전에서 뺀 것과 같은 이유다
#   ("사전에 넣으면 트렌드 지표가 특정 브랜드 홍보판이 됩니다").
#   색·핏·TPO 도 뺀다. '블랙' 이 늘 상위에 있는 것은 트렌드가 아니라 상수다.
#   브랜드 순위가 필요하면 facet="brand" 로 명시해서 부르면 그대로 나온다.
TREND_FACETS = ["style", "material", "item"]


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
        "결과가 비어도 실패가 아니다 — 용어를 지목하지 않는 질문일 수 있다. "
        "★ 후보가 여럿이면 alts 에 **한 번에 모두** 넣어라. 한 번에 다 찾아 준다. "
        "나눠서 여러 번 부르면 그만큼 바퀴를 쓰고 답 쓸 시간이 없어진다.",
        {"q": {"type": "string", "description": "사용자 질문 원문 또는 그 일부"},
         "alts": {"type": "array", "items": {"type": "string"},
                  "description": "함께 찾아 볼 후보들. 상품명이면 브랜드·아이템·소재로 "
                                 "나눈 말 (예: [\"아디다스\", \"트랙탑\"]). 없으면 빈 배열"}},
        ["q", "alts"],
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
        "season_fit",
        "이 옷을 지금 기온·계절에 입을 만한지 본다. "
        "'지금 가을인데 입을 만해?' '이거 지금 입어도 돼?' 같은 질문에 쓴다. "
        "★ 우리 측정값이 아니라 **일반적인 착용 기준**이다 — 답변에서 그렇게 밝혀야 한다. "
        "temp_c 는 web_search 로 알아낸 현재 기온을 넣는다. 모르면 null 로 두면 "
        "계절 평균으로 대신 잡고, 무엇으로 잡았는지 함께 돌려준다.",
        {"terms": {"type": "array", "items": {"type": "string"},
                   "description": "볼 아이템·소재 이름들. 한 번에 여러 개 (예: [\"트랙탑\", \"폴리에스터\"])"},
         "temp_c": {"type": ["number", "null"], "description": "지금 기온(°C). 모르면 null"},
         "season": {"type": ["string", "null"], "description": "봄·여름·가을·겨울. 모르면 null"}},
        ["terms", "temp_c", "season"],
    ),
    _fn(
        "similar_terms",
        "비슷한 것을 우리 지표에서 찾는다. '비슷한 거 추천해줘' 에 쓴다. "
        "★ 후보를 아는 대로 terms 에 **모두** 넣어라 — 도구가 그중 기준을 고른다. "
        "상품 추천이면 **아이템 축 용어(팬츠·티셔츠 …)를 반드시 함께** 넣어라. "
        "스타일 용어(레이어드·스트릿웨어)만 주면 '성격이 비슷한 스타일' 을 찾게 되어 "
        "상품 추천과 다른 답이 나온다. "
        "★ 상품이 아니라 **용어** 단위다. 우리 데이터에 상품 사진은 없다.",
        {"terms": {"type": "array", "items": {"type": "string"},
                   "description": "기준 후보들 (예: [\"팬츠\", \"조거팬츠\", \"레이어드\"]). "
                                  "아이템 축을 우선 고른다"},
         "limit": {"type": "integer", "description": "몇 개까지. 기본 6"}},
        ["terms", "limit"],
    ),
    _fn(
        "compose_report",
        "조회가 끝난 뒤 이번 답에 필요한 결과만 골라 화면을 직접 구성하는 UI 스킬이다. "
        "완성 템플릿을 고르는 도구가 아니다. 데이터 모듈의 표현 방식과 12열 폭, "
        "강조도를 조합해 매 요청마다 새 캔버스를 만든다. 데이터가 있는 답에서는 최종 "
        "문장을 쓰기 직전에 정확히 한 번 부른다. kind 는 이미 호출한 도구 결과에 있는 "
        "것만 쓴다: rank_terms=ranking, 둘 이상 get_metric=comparison, get_metric=metric, "
        "모멘텀=direction, 출처별=sources, 연관어=associations, 긍부정=sentiment, "
        "similar_terms=recommendations, get_user_taste=taste, season_fit=context, "
        "get_evidence=evidence/links, declare_missing=missing. term 은 특정 용어 모듈이면 "
        "그 정확한 표기를 쓰고 공통 모듈이면 null. HTML·CSS나 수치·상품을 인자에 쓰지 마라.",
        {
            "title": {"type": "string", "description": "짧은 리포트 제목. 수치를 넣지 않는다"},
            "accent": {"type": "string", "enum": ["coral", "ink", "violet", "blue", "lime"]},
            "surface": {"type": "string", "enum": ["paper", "soft", "contrast", "glass"]},
            "density": {"type": "string", "enum": ["airy", "balanced", "compact"]},
            "modules": {
                "type": "array", "maxItems": 9,
                "items": {
                    "type": "object", "additionalProperties": False,
                    "properties": {
                        "kind": {"type": "string", "enum": [
                            "ranking", "comparison", "metric", "direction", "sources",
                            "associations", "sentiment", "recommendations", "taste",
                            "context", "evidence", "links", "missing"]},
                        "term": {"type": ["string", "null"],
                                 "description": "특정 용어 모듈이면 정확한 용어, 공통이면 null"},
                        "presentation": {"type": "string", "enum": [
                            "hero", "card", "chart", "list", "editorial", "compact"]},
                        "span": {"type": "integer", "minimum": 4, "maximum": 12,
                                 "description": "12열 캔버스에서 차지할 열 수"},
                        "emphasis": {"type": "string", "enum": ["strong", "normal", "quiet"]},
                    },
                    "required": ["kind", "term", "presentation", "span", "emphasis"],
                },
            },
        },
        ["title", "accent", "surface", "density", "modules"],
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
        "그 축들은 우리 데이터에 없다고 기록한다. 지어내는 대신 이것을 부른다. "
        "기록해 두면 답변에서 '아직 측정 자료가 없습니다' 로 정직하게 말할 수 있다. "
        "★ 없는 축이 여럿이면 axes 에 한 번에 모두 넣어라. 축마다 따로 부르지 않는다.",
        {"term": {"type": "string"},
         "axes": {"type": "array", "items": {"type": "string"},
                  "description": "없는 축 이름들 (예: [\"리세일\", \"체형\", \"사이즈\"]). "
                                 "하나뿐이어도 배열로 넣는다"},
         "reason": {"type": "string",
                    "description": "왜 없는지 한 줄. 축들에 공통으로 붙는다"}},
        ["term", "axes", "reason"],
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


def _axis_list(axes: Any, axis: Any = None) -> list[str]:
    """declare_missing 의 축 인자를 목록으로 고른다.

    ★ 표준은 axes(배열)다 (2026-09-10, 인수인계 17번).
      예전 스펙은 axis 를 **하나씩** 받아서, 없는 축마다 한 번씩 불렸다.
      그 반복이 orchestrator.MAX_PER_TOOL 에 걸리면 뒤쪽 축은 기록되지
      않은 채 조용히 사라진다 — 상한은 그 증상을 막은 것이지 원인을
      고친 것이 아니었다.
    ★ 그래도 axis(문자열)를 받는다. strict 스키마를 켜도 모델이 옛 모양으로
      부르는 일이 있고, 그때 죽는 것보다 받아 주는 편이 낫다.
    """
    raw: list[Any] = []
    if isinstance(axes, str):
        raw.append(axes)
    elif isinstance(axes, (list, tuple)):
        raw.extend(axes)
    if axis:
        raw.append(axis)
    out: list[str] = []
    for a in raw:
        s = str(a or "").strip()
        if s and s not in out:          # 같은 축을 두 번 적어도 한 줄로 남는다
            out.append(s)
    return out


def progress_say(name: str, args: dict) -> str | None:
    """도구 호출 하나를 사람이 읽는 한 줄로. 보여 줄 게 없으면 None."""
    args = args or {}
    term = str(args.get("term") or "").strip()
    head = f"{term} " if term else ""
    if name == "search_terms":
        # ★ 같은 문구가 반복되면 화면이 멈춘 것처럼 보인다. 찾는 말을 넣는다.
        q = " ".join(str(args.get("q") or "").split())
        if q.startswith("http"):
            # 주소를 그대로 보여 주면 화면이 한 줄을 다 먹는다. 후보 쪽을 보여 준다.
            alt = [str(a).strip() for a in (args.get("alts") or []) if str(a).strip()]
            return f"'{alt[0]}' 찾아보는 중" if alt else "보내신 링크를 살펴보는 중"
        if not q:
            return "말을 사전에서 찾는 중"
        return f"'{q[:12]}…' 찾아보는 중" if len(q) > 12 else f"'{q}' 찾아보는 중"
    if name == "rank_terms":
        f = FACET_SAY.get(args.get("facet") or "")
        return f"지금 뜨는 {f} 세는 중" if f else "지금 뜨는 것 세는 중"
    if name == "get_metric":
        axes = [AXIS_SAY.get(a, a) for a in (args.get("axes") or [])]
        return f"{head}{' · '.join(axes[:3]) or '지표'} 보는 중"
    if name == "get_evidence":
        return f"{head}실제 언급 찾는 중"
    if name == "declare_missing":
        ax = _axis_list(args.get("axes"), args.get("axis"))
        if not ax:
            return "없는 항목을 기록하는 중"
        head = " · ".join(ax[:3]) + ("…" if len(ax) > 3 else "")
        return f"{head} 은(는) 측정 자료가 없다고 기록하는 중"
    if name == "season_fit":
        ts = [str(t).strip() for t in (args.get("terms") or []) if str(t).strip()]
        return f"{ts[0]} 지금 입기 좋은지 보는 중" if ts else "지금 입기 좋은지 보는 중"
    if name == "similar_terms":
        cand = [str(t).strip() for t in (args.get("terms") or []) if str(t).strip()]
        first = cand[0] if cand else term
        return f"{first} 비슷한 것 찾는 중" if first else "비슷한 것 찾는 중"
    if name == "get_salmal":
        return "살!말? 투표 보는 중"
    if name == "search_salmal":
        return f"{head}비슷한 고민 찾는 중"
    if name == "get_user_taste":
        return "취향에 맞춰 보는 중"
    if name == "compose_report":
        return "결과에 맞는 화면을 구성하는 중"
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

        # compose_report 의 span·제목은 화면 배치값이지 조회 사실이 아니다.
        # 검증 숫자에 섞이면 모델이 만든 숫자가 도구 근거인 것처럼 통과한다.
        walk([c for c in self.calls if c.get("tool") != "compose_report"])
        return seen

    def terms(self) -> set[str]:
        """도구 결과에 등장한 용어·라벨. 없는 말을 지어냈는지 볼 때 쓴다."""
        out: set[str] = set()
        for c in self.calls:
            if c.get("tool") == "compose_report":
                continue
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
    def _key(self, term: str) -> str:
        """term_key 를 만든다. 사전에 없으면 지표 표의 축을 쓴다.

        gate.term_key() 는 lex.facet_of 만 보므로 브랜드는 "None:살로몬" 이 된다.
        """
        f = self.gate.facet_of(term)
        if not f:
            f = self.store.metric_facet(term)
        return f"{f}:{term}"

    def _look_up(self, text: str) -> tuple[list[dict], str]:
        """말 하나를 사전 → 지표 순으로 찾는다. (hits, 어디서 찾았나)"""
        parsed = self.gate.parse(text)
        hits = [{"term": h["canonical"], "facet": h["facet"], "term_key": h["term_key"]}
                for h in parsed.get("search", [])]
        if hits:
            return hits, "lexicon"
        # ★ 사전에 없어도 **지표에는 있을 수 있다.** (2026-09-09)
        #   실측: "살로몬" 은 지표 표에 8행 있는데 사전에 없어 못 찾았고,
        #   챗봇은 "측정 자료가 없습니다" 라고 답했다. 틀린 답이다.
        direct = self.store.metric_terms_in(text, limit=3)
        if direct:
            return ([{"term": r["canonical"], "facet": r["facet"],
                      "term_key": f'{r["facet"]}:{r["canonical"]}'} for r in direct],
                    "metric")
        return [], ""

    def t_search_terms(self, q: str, alts: Any = None) -> dict:
        """q 와 alts 를 **한 번에** 찾는다 (2026-09-10).

        ★ 왜 alts 인가 — 실측(무신사 상품 링크): 모델이 링크 → "아디다스 트랙탑"
          → "트랙탑" 순으로 search_terms 를 **세 번** 불렀다. 한 번 부를 때마다
          모델 왕복이 한 바퀴라, 세 바퀴(15초)를 조회에만 쓰고 답을 못 썼다.
          17번의 declare_missing 과 같은 낭비다 — **스펙이 하나씩만 받으면
          모델은 하나씩 부른다.** 그래서 여기도 한 번에 받는다.
        ★ 후보를 순회하되 **첫 성공에서 멈추지 않는다.** 브랜드와 아이템이 둘 다
          잡혀야 '나란히 보기' 가 붙는다.
        """
        tried = [str(q or "").strip()]
        for a in (alts if isinstance(alts, (list, tuple)) else []):
            t = str(a or "").strip()
            if t and t not in tried:
                tried.append(t)

        hits: list[dict] = []
        seen: set[str] = set()
        sources: set[str] = set()
        for cand in tried:
            if not cand:
                continue
            got, where = self._look_up(cand)
            if where:
                sources.add(where)
            for h in got:
                if h["term"] in seen:
                    continue
                seen.add(h["term"])
                hits.append(dict(h, **({"from": cand} if cand != tried[0] else {})))

        parsed = self.gate.parse(tried[0] if tried else "")
        out: dict[str, Any] = {"found": hits, "count": len(hits), "tried": tried}
        if hits and "metric" in sources:
            out["source"] = "metric"          # 사전이 아니라 지표에서 직접 찾았다
            out["note"] = ("사전에는 없지만 지표에 이름이 있는 용어가 있습니다"
                           "(브랜드 등). 그대로 get_metric 에 넘기면 됩니다.")
        if hits and len(tried) > 1:
            out["substituted"] = True
            첫말 = tried[0] if len(tried[0]) <= 40 else tried[0][:39] + "…"
            out["substituted_note"] = (
                f"'{첫말}' 로는 못 찾아 다른 후보로 찾았습니다. "
                "답변에 **무엇 대신 무엇을 봤는지 반드시 밝히십시오.**")
        if not hits:
            # 못 찾았다고 끝이 아니다. 가까운 말과 인기어를 같이 준다 —
            # 모델이 되묻거나 rank_terms 로 갈아탈 재료가 된다.
            out["near"] = self.gate.near_candidates(q, limit=3)
            out["popular"] = self.gate.popular(self.store, limit=3)
            out["hint"] = ("용어를 지목하지 않은 질문일 수 있습니다. "
                           "'요즘 뭐가 핫해' 류면 rank_terms 를 쓰세요.")
            # ★ 표기만 바꿔 다시 부르는 것을 막는다 (2026-09-09 실측:
            #   "살로몬 XT-6" → "XT-6" → "살로몬" 으로 3~4연속 호출).
            out["retry"] = "금지"
            out["retry_note"] = (
                "같은 대상을 표기만 바꿔(띄어쓰기·모델명 분리·영문) 다시 부르지 마십시오. "
                "사전에도 지표에도 없는 말은 표기를 바꿔도 없습니다. "
                "구성 요소로 나눠 볼 생각이면 **이 도구를 다시 부르지 말고 alts 에 "
                "한 번에 넣으십시오** (예: alts=[\"아디다스\", \"트랙탑\"]). "
                "한 번 더 부를 때마다 바퀴를 하나 쓰고, 그만큼 답 쓸 시간이 줄어듭니다. "
                "그래도 없으면 declare_missing 으로 기록하고 답을 쓰십시오.")
        # 수식어(핏·색·TPO)는 검색어가 아니지만 답변 톤에 쓰인다
        out["modifiers"] = [h["canonical"] for h in parsed.get("modifier", [])]
        return out

    def t_rank_terms(self, facet: str | None = None, limit: int = 10) -> dict:
        n = max(1, min(int(limit or 10), 20))
        rows = self.store.top_terms(facet=facet or None, limit=n,
                                    facets=None if facet else TREND_FACETS)
        day = self.store.latest_day()
        return {
            "as_of": day,
            "asked": n,
            "returned": len(rows),
            # 어떤 축을 보고 센 순위인지 밝힌다. 모델이 답에 적을 수 있어야 한다.
            "facets_seen": [facet] if facet else TREND_FACETS,
            "facets_note": (None if facet else
                            "브랜드·색·핏 축은 전체 순위에서 제외했습니다. "
                            "브랜드 순위를 원하면 facet=\"brand\" 로 다시 부르십시오."),
            # ★ 요청한 수보다 적을 수 있다. 그 사실을 명시한다 —
            #   안 그러면 모델이 나머지를 채워 넣는다.
            "short_of_asked": len(rows) < n,
            "items": [{"term": r["canonical"], "facet": r["facet"],
                       "temp": r["temp"], "band": temp_band(r["temp"]),
                       "raw_count": r["raw_count"]} for r in rows],
        }

    # ── 지표 ────────────────────────────────────────────
    def t_get_metric(self, term: str, axes: list[str]) -> dict:
        key = self._key(term)
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
                # 지난주와 견주면 방향이 보인다.
                #   ★ 2주 관측이 모자라면 주지 않는다 — may_say["2주변화"] 와 같은 기준.
                #     안 그러면 표본 16건짜리 용어가 "지난주보다 31° 하락" 이라고 나간다.
                "delta_1w": (self._delta_1w(key, latest)
                             if n14 >= MIN_OBS_14 else None),
                # 지난주 온도 자체. 모델이 빼기를 하지 않아도 되게 한다.
                "temp_1w_ago": ((self._week_ago(key, latest) or (None, None))[0]
                                if n14 >= MIN_OBS_14 else None),
                "delta_1w_note": (None if n14 >= MIN_OBS_14 else
                                  f"14일 관측 {n14}건 — 지난주 대비 변화를 말하기엔 모자랍니다."),
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
            # ★ 2026-09-09 — 표본 문턱을 여기서 건다.
            #   실측: material:니트 의 감성은 n_total=1, pos_pct=100.0 이었다.
            #   그대로 내보내면 모델이 "긍정 100%" 라고 쓴다. 댓글 한 건이다.
            #   may_say 를 만들어 두고 이 축만 문턱이 없었다.
            s = self.store.term_sentiment(key)
            n_s = int((s or {}).get("n_total") or 0)
            if not s:
                out["긍부정"] = {"unavailable": "감성 지표가 아직 없습니다."}
            elif n_s < MIN_OBS_7:
                out["긍부정"] = {
                    "unavailable": f"감성 표본 {n_s}건 — 비율을 말하기엔 모자랍니다.",
                    "n_total": n_s}
            else:
                s = dict(s)
                if n_s < THIN_SAMPLE:
                    s["thin_sample"] = True
                    s["note"] = f"표본 {n_s}건 — 비율을 적을 때 표본 수를 반드시 함께 적으세요."
                out["긍부정"] = s
        if "근거" in want:
            out["근거"] = self.store.term_evidence(key, limit=3)

        # ★ 이 조건에서 써도 되는 문장. 모델이 판단을 지어내기 전에 준다.
        out["말할_수_있는_것"] = _say_rule(pct, latest.get("momentum"), thin)
        return out

    def _delta_1w(self, key: str, latest: dict):
        """지난주 대비 온도 변화. 관측이 없으면 None — 0 으로 채우지 않는다."""
        d = self._week_ago(key, latest)
        return None if d is None else d[1]

    def _week_ago(self, key: str, latest: dict):
        """(지난주 온도, 변화량). 둘 다 **도구가 계산해서** 준다.

        ★ 왜 지난주 값을 따로 주나 (2026-09-09 실측)
          delta_1w 만 주면 모델이 "지난주 87도에서 31도 하락" 이라고 쓴다 —
          87 은 56+31 을 스스로 계산한 값이다. 계산이 맞아도 도구가 확인해
          준 값이 아니라 검증관이 지웠다("87도에서 " 삭제).
          그런데 사용자에게는 "지난주 87°에서 31° 하락" 이 "31° 하락" 보다
          훨씬 유용하다(설계도 부록 11 — 기준선).
          검증을 푸는 대신 **도구가 그 값을 직접 준다.** 값은 도구에서만
          나온다는 원칙을 지키면서 답변이 친절해진다.
        """
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
        prev = round(float(past["temp"]), 1)
        return prev, round(float(now) - prev, 1)

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
        key = self._key(term)
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

    # ── 출력 디자인 스킬 ─────────────────────────────────
    def t_compose_report(self, title: str, accent: str, surface: str,
                         density: str, modules: Any) -> dict:
        """모델의 UI 결정을 기록한다. 데이터는 여기서 만들지 않는다.

        실제 모듈 존재 여부는 agent_blocks → report_skill 이 궤적과 다시 맞춘다.
        이 도구는 안전한 디자인 어휘만 남기므로 HTML/CSS 주입 경로가 없다.
        """
        allowed = {
            "kinds": {"ranking", "comparison", "metric", "direction", "sources",
                      "associations", "sentiment", "recommendations", "taste", "context",
                      "evidence", "links", "missing"},
            "presentations": {"hero", "card", "chart", "list", "editorial", "compact"},
            "emphasis": {"strong", "normal", "quiet"},
            "accents": {"coral", "ink", "violet", "blue", "lime"},
            "surfaces": {"paper", "soft", "contrast", "glass"},
            "densities": {"airy", "balanced", "compact"},
        }
        clean = []
        for raw in (modules if isinstance(modules, list) else [])[:9]:
            if not isinstance(raw, dict) or raw.get("kind") not in allowed["kinds"]:
                continue
            try:
                span = max(4, min(12, int(raw.get("span") or 6)))
            except (TypeError, ValueError):
                span = 6
            clean.append({
                "kind": raw["kind"],
                "term": (str(raw["term"]).strip() if raw.get("term") is not None else None),
                "presentation": (raw.get("presentation") if raw.get("presentation") in
                                 allowed["presentations"] else "card"),
                "span": span,
                "emphasis": (raw.get("emphasis") if raw.get("emphasis") in
                             allowed["emphasis"] else "normal"),
            })
        spec = {
            "title": str(title or "FEEDiT SIGNAL").strip()[:48],
            "accent": accent if accent in allowed["accents"] else "coral",
            "surface": surface if surface in allowed["surfaces"] else "paper",
            "density": density if density in allowed["densities"] else "balanced",
            "modules": clean,
        }
        return {"ok": True, "skill": "generative-report-v1", "spec": spec,
                "note": "실제 조회 결과와 일치하는 모듈만 화면에 결합됩니다."}

    # ── 밖 ──────────────────────────────────────────────
    def t_web_search(self, q: str) -> dict:
        if self.websearch is None:
            return {"unavailable": "웹 검색이 꺼져 있습니다."}
        hits = self.websearch(q)
        return {"q": q, "from": "web", "not_feedit_data": True, "items": hits}

    # ── 계절·비슷한 것 ──────────────────────────────────
    def t_season_fit(self, terms: Any = None, temp_c: Any = None,
                     season: Any = None) -> dict:
        """지금 기온에 입을 만한가. **일반 기준**이지 우리 측정값이 아니다.

        ★ 판단을 모델에게 맡기지 않고 표에서 읽는다(app/season.py 머리말).
          모델이 그때그때 판단하면 대조할 원본이 없어 지어낸 숫자와 같은 자리에 선다.
        ★ 표에 없는 말은 unknown 으로 돌려준다. 비슷해 보인다고 끼워 맞추지 않는다.
        """
        names = _axis_list(terms)
        if not names:
            return {"error": "terms 가 비어 있습니다. 볼 아이템·소재 이름을 배열로 넣으십시오."}
        try:
            t = float(temp_c) if temp_c is not None else None
        except (TypeError, ValueError):
            t = None
        basis = f"{t:g}°C 기준" if t is not None else ""
        if t is None:
            t, basis = season_ref.temp_for_season(season)
        if t is None:
            return {"unavailable": "기온도 계절도 받지 못했습니다.",
                    "hint": "web_search 로 현재 기온을 확인해 temp_c 에 넣거나, "
                            "season 에 '가을' 처럼 계절을 넣어 다시 부르십시오."}
        fits, unknown = [], []
        for n in names:
            r = season_ref.fit(n, t)
            (fits.append(r) if r else unknown.append(n))
        return {
            "temp_c": t, "basis": basis, "items": fits, "unknown": unknown,
            # ★ 이 두 줄이 이 도구의 핵심이다. 빼지 마라.
            "not_feedit_data": True,
            "note": ("일반적인 착용 기준이며 FEEDiT 측정값이 아닙니다. "
                     "답변에서 그렇게 밝히십시오. "
                     + ("표에 없는 말(" + ", ".join(unknown) + ")은 판단하지 마십시오."
                        if unknown else "")),
        }

    def _pick_base(self, names: list[str]) -> tuple[str, str | None, list[dict]]:
        """후보 중 기준을 고른다. 아이템 축이 먼저다(BASE_ORDER).

        고른 이유와 함께 돌려준다 — 모델이 답변에 "무엇을 기준으로 봤는지" 를
        적을 수 있어야 한다.
        """
        seen: list[dict] = []
        for nm in names:
            key = self._key(nm)
            f = key.split(":", 1)[0] if ":" in key else None
            if f in ("", "None"):
                f = None
            seen.append({"term": nm, "facet": f})
        ranked = sorted(seen, key=lambda x: BASE_ORDER.get(x["facet"] or "", 9))
        best = ranked[0] if ranked else {"term": "", "facet": None}
        return best["term"], best["facet"], seen

    def t_similar_terms(self, terms: Any = None, term: str = "",
                        limit: int = 6) -> dict:
        """비슷한 것 = **연관어 프로필이 겹치는 것** (2026-09-10 다시 씀).

        ★ 처음에는 연관어를 그대로 "비슷한 것" 으로 내보냈다. 틀렸다.
          연관어는 **함께 언급된** 말이라 대부분 코디(보완재)다.
          실측: 반팔 티셔츠 링크에 "비슷한 것" 으로 팬츠·자켓이 나왔다.
          같이 입는 것이지 대신 입는 것이 아니다.

        ★ 대체재는 지표로 구할 수 있다. **같은 자리에 놓이는 말은 같은 것들과
          함께 언급된다.** 티셔츠와 맨투맨은 둘 다 팬츠·데님과 함께 나오고,
          팬츠는 그 둘과 함께 나오지만 팬츠의 연관어는 상의들이다.
          그래서 base 의 연관어 집합과 후보의 연관어 집합이 얼마나 겹치는지
          (자카드)로 고른다 — 1차 연관이 아니라 **2차 연관**이다.
          분류표를 새로 만들지 않고 우리 지표만으로 푸는 방법이다.

        ★ 두 목록을 **나눠서** 돌려준다.
            items — 비슷한 것 (대신 입을 만한 것)
            pairs — 함께 언급된 것 (같이 입는 것). 섞으면 이번 같은 답이 나온다.

        ★ 연관어 자료가 얇으면 같은 축 상위로 대신하되 **그렇게 밝힌다**(method).
        """
        names = _axis_list(terms, term)
        if not names:
            return {"error": "terms 가 비어 있습니다. 기준 후보를 배열로 넣으십시오."}
        n = max(1, min(int(limit or 6), 10))
        term, facet, considered = self._pick_base(names)
        key = self._key(term)

        base_rows = self.store.term_assoc(key, limit=30)
        base_set = {r.get("assoc_canonical") for r in base_rows if r.get("assoc_canonical")}
        pairs = [{"term": r.get("assoc_canonical"), "facet": r.get("assoc_facet"),
                  "co_count": r.get("co_count")}
                 for r in base_rows[:6] if r.get("assoc_canonical")]

        cands = self.store.top_terms(facet=facet, limit=CAND_MAX) if facet else []
        scored: list[dict] = []
        for r in cands:
            name = r.get("canonical")
            if not name or name == term:
                continue
            if not base_set:
                break                       # 겹칠 원본이 없다. 아래 폴백으로 간다.
            other = self.store.term_assoc(f'{r.get("facet")}:{name}', limit=30)
            other_set = {x.get("assoc_canonical") for x in other if x.get("assoc_canonical")}
            if not other_set:
                continue
            shared = base_set & other_set
            if not shared:
                continue
            score = len(shared) / len(base_set | other_set)
            scored.append({
                "term": name, "facet": r.get("facet"), "temp": r.get("temp"),
                "band": temp_band(r.get("temp")), "score": round(score, 3),
                "shared": sorted(shared)[:3],
                "why": "같은 말들과 함께 언급됨",
            })

        scored.sort(key=lambda x: (x["score"], x.get("temp") or 0), reverse=True)
        items = scored[:n]
        method = "연관어 프로필이 겹치는 정도(2차 연관)로 골랐습니다"

        # ★ 연관어가 얇으면 **이름 계열**로 채운다. 지표에도 사전에도 하위 분류가
        #   없으니 남은 근거가 이름이다(_family 머리말). 근거가 다르므로 why 도 다르다.
        if len(items) < n and facet:
            있음 = {i["term"] for i in items}
            가족 = []
            for r in self.store.top_terms(facet=facet, limit=FAMILY_POOL):
                nm = r.get("canonical")
                if not nm or nm == term or nm in 있음:
                    continue
                w = _family(term, nm)
                if w:
                    가족.append({"term": nm, "facet": r.get("facet"), "temp": r.get("temp"),
                                 "band": temp_band(r.get("temp")), "kin": w,
                                 "why": "이름이 같은 계열"})
            가족.sort(key=lambda x: (x["kin"], x.get("temp") or 0), reverse=True)
            items = items + 가족[: n - len(items)]
            if 가족:
                method = ("연관어 프로필 겹침과 **이름 계열**로 골랐습니다"
                          if scored else "**이름 계열**로 골랐습니다 (연관어 자료가 없습니다)")

        axis = FACET_SAY.get(facet or "", facet or "같은")
        alts: list[dict] = []
        if not items:
            # ★ 연관어가 없으면 **비슷한 것을 못 찾은 것이다.** (2026-09-10 실측:
            #   연관어 표 1054행 중 'item:팬츠' 는 0개, 'item:티셔츠' 는 3개다.)
            #   예전에는 축 상위를 items 에 담아 돌려줬는데, 이름이 같으니 모델이
            #   그대로 "비슷한 것" 으로 소개했다 — 팬츠 옆에 자켓·백팩이 섰다.
            #   말로 "이건 비슷한 게 아니다" 라고 덧붙이는 대신 **자리를 나눈다.**
            #   items 는 비우고 alternatives 에 담는다. 섞일 수 없는 모양으로 준다.
            for r in cands:
                name = r.get("canonical")
                if not name or name == term:
                    continue
                alts.append({"term": name, "facet": r.get("facet"), "temp": r.get("temp"),
                             "band": temp_band(r.get("temp")),
                             "why": f"{axis} 축에서 지금 높은 것"})
                if len(alts) >= n:
                    break
            # ★ 축 이름을 분명히 적는다. "같은 축" 이라고만 주면 모델이 "팬츠 축에서"
            #   로 옮겨 적는다 — 실제로 그렇게 나갔다. 우리 지표의 축은
            #   style · material · item · brand 넷뿐이고, item 안에 상의·하의·가방이
            #   전부 들어 있다. 그래서 팬츠의 '같은 축' 에 자켓·백팩이 함께 나온다.
            method = (f"'{term}' 의 연관어 자료가 없어 **비슷한 것을 찾지 못했습니다.** "
                      f"먼저 그렇게 말하십시오. alternatives 는 다른 질문의 답입니다 — "
                      f"{axis} 축에서 지금 온도가 높은 용어이고 이 축에는 다른 종류도 "
                      "섞여 있습니다. '비슷한 것' 으로 소개하지 마십시오.")

        out: dict[str, Any] = {
            "term": term, "facet": facet, "as_of": self.store.latest_day(),
            "base_note": f"'{term}' 기준. 무엇을 기준으로 봤는지 답변에 밝히십시오.",
            "method": method, "count": len(items), "items": items,
            # 비슷한 것을 못 찾았을 때만 채워진다. items 와 **다른 것**이다.
            "alternatives": alts,
            # ★ 이건 비슷한 것이 아니다. 이름과 설명을 분명히 해서 넘긴다.
            # 함께 언급된 말 = 같이 입는 것. 비슷한 것이 아니다.
            "paired_with": pairs[:4],
            "note": ("용어 단위입니다. 상품 목록·사진 없음. paired_with 를 '비슷한 것' 으로 "
                     "말하지 마십시오." if items else
                     "비슷한 것을 찾지 못했습니다. 그 사실을 먼저 말하십시오."),
        }
        if facet not in ("item", "material"):
            # ★ 스타일·브랜드 축을 기준으로 삼으면 '비슷한 상품' 이 아니라
            #   '성격이 비슷한 스타일' 이 나온다. 다른 질문의 답이다.
            out["caution"] = (
                f"'{term}' 은 아이템·소재 축이 아닙니다. 비슷한 상품이 아니라 "
                "성격이 비슷한 스타일입니다. 그렇게 밝히십시오.")
        return out

    # ── 대화 행동 ───────────────────────────────────────
    def t_ask_user(self, question: str, options: list[str]) -> dict:
        self.trace.asked = {"question": question, "options": options or []}
        return {"ok": True, "note": "되묻기를 준비했습니다. 여기서 도구 호출을 멈추세요."}

    def t_declare_missing(self, term: str = "", reason: str = "",
                          axes: Any = None, axis: Any = None) -> dict:
        """없는 축들을 **한 번에** 기록한다 (인수인계 17번).

        ★ 기록 모양은 예전 그대로 축 하나당 한 줄이다.
          trace.missing 을 읽는 곳이 셋(verify.check · agent_path._notes ·
          agent_blocks)이라, 저장 모양까지 바꾸면 파급이 셋으로 퍼진다.
          바뀐 것은 **부르는 모양**뿐이다.
        """
        names = _axis_list(axes, axis)
        if not names:
            return {"error": "axes 가 비어 있습니다. 없는 축 이름을 배열로 넣으십시오."}
        already = {(m.get("term"), m.get("axis")) for m in self.trace.missing}
        added = []
        for a in names:
            if (term, a) in already:
                continue
            self.trace.missing.append({"term": term, "axis": a, "reason": reason})
            added.append(a)
        joined = " · ".join(names)
        return {"ok": True, "axes": names, "recorded": added, "count": len(names),
                "note": f"'{joined}' 는 없는 것으로 기록했습니다. "
                        "답변에서 그 축의 값을 말하지 마세요. "
                        "없는 축이 더 있어도 이 도구를 다시 부르지 말고, "
                        "지금 한 번에 넣었어야 합니다."}


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
    if ctx.get("no_ask"):
        # 되묻기 예산 소진 (orchestrator.ASK_BUDGET). 목록에 없으면 못 부른다 —
        # 프롬프트로 부탁하는 것과 달리 이건 지켜진다.
        drop.add("ask_user")
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
