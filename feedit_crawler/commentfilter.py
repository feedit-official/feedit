# -*- coding: utf-8 -*-
"""댓글 고르기 — 긍부정 지표에 쓸모 있는 것만 남긴다.

★ 왜 거르나
  패션 유튜브 댓글의 절반 이상은 지표에 아무 도움이 안 된다.
      "1등"  "형 오늘 잘생겼다"  "구독하고 갑니다"  "3:24 이 부분 ㅋㅋ"
  이런 걸 다 담으면 세 가지가 나빠진다.
    ① 저장 공간과 나중 분석 시간이 몇 배로 든다
    ② 긍부정 비율이 '내용 없는 칭찬'으로 부풀어 실제 여론과 멀어진다
    ③ 사람이 [데이터] 탭에서 훑어볼 때 쓸 만한 게 안 보인다

  그래서 **남길 이유가 있는 것만** 남긴다. 이유도 함께 저장해서,
  나중에 "왜 이건 버렸지?"를 되짚을 수 있게 한다.

★ 버리는 쪽을 조심한다
  거르다가 진짜 신호를 버리면 지표가 조용히 틀어진다. 그래서
  '확실히 쓸모없는 것'만 버리고, 애매하면 남기는 쪽으로 기운다.
"""
from __future__ import annotations

import re
import unicodedata

# ── 확실히 버리는 것 ──────────────────────────────────────────
_ONLY_EMOJI = re.compile(
    r"^[\s\W\d_]*$", re.UNICODE)          # 글자가 하나도 없는 것
_TIMESTAMP = re.compile(r"^\s*\d{1,2}:\d{2}(:\d{2})?\s*")   # '3:24 여기'
_JUNK = re.compile(
    r"^(1등|일등|첫|선착|출석|오늘도\s*잘\s*보|잘\s*보고\s*(가|갑니다|있)"
    r"|구독하고\s*가|구독\s*박고|알림\s*설정|좋아요\s*(누르고|박고)"
    r"|형님?\s*(사랑|최고|짱)|누나\s*(사랑|최고|짱)|언니\s*(사랑|최고|짱)"
    r"|ㅋ+|ㅎ+|ㅠ+|ㅜ+|굿|goat|goat다|👍+)[\s!?.~ㅋㅎ]*$")
_SPAM = re.compile(
    r"(카톡|텔레\s*그램|디엠\s*주세|상담\s*환영|수익\s*인증|먹튀|토토|배팅"
    r"|https?://\S*(bit\.ly|me2|link)|무료\s*체험|100%\s*환급)")

# ── 남기는 이유 ───────────────────────────────────────────────
#  구매 의향은 intent.py 가 본다. 여기서는 그 밖의 '쓸모 신호'를 본다.
_OPINION = re.compile(
    r"예쁘|이쁘|멋있|잘\s*어울|찰떡|취향|별로|촌스|안\s*어울|어색|과하"
    r"|편하|불편|따뜻|시원|더워|추워|무겁|가볍|핏이|핏은|사이즈|기장"
    r"|재질|소재|퀄리티|마감|두께|비침|늘어나|보풀|세탁")
_ASKING = re.compile(
    r"어디\s*(거|제품|브랜드)|제품\s*정보|정보\s*(좀|주세요|알려)"
    r"|무슨\s*브랜드|(?:옷|상의|하의|자켓|재킷|신발|가방|모자|제품)\s*브랜드"
    r"|(?:입고|신고|메고|쓰고|착용한?)\s*(계신|있는|한)?\s*"
    r"(옷|상의|하의|자켓|재킷|신발|가방|모자|제품)?\s*(뭐|어디)")


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFC", str(t or ""))
    t = re.sub(r"https?://\S+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def judge(text: str, *, lexicon=None, min_len: int = 6) -> dict:
    """이 댓글을 남길까. 반환: {keep, why, drop_why}

    why 는 남기는 이유(여러 개 가능):
        intent   구매 의향이 보인다 (사고싶다·질렀다·반품했다…)
        term     우리 어휘사전의 말이 나온다 (오버핏·와이드팬츠…)
        opinion  착용감·재질·핏에 대한 평가가 있다
        asking   제품을 묻고 있다 (수요 신호)
    """
    raw = str(text or "")
    t = _norm(raw)
    t = _TIMESTAMP.sub("", t)

    if not t or _ONLY_EMOJI.match(t):
        return {"keep": False, "why": [], "drop_why": "글자가 없음"}
    if _SPAM.search(t):
        return {"keep": False, "why": [], "drop_why": "스팸·광고"}
    if _JUNK.match(t):
        return {"keep": False, "why": [], "drop_why": "인사·1등 같은 빈 댓글"}

    why = []
    from .intent import classify
    got = classify(t)
    if got["labels"]:
        why.append("intent")
    if _OPINION.search(t):
        why.append("opinion")
    if _ASKING.search(t):
        why.append("asking")
    terms = []
    if lexicon is not None:
        try:
            # ★ 자유 글 기준으로 본다. 상품명 기준을 대면
            #   '바람불면' 이 코튼으로 걸려 아무 댓글이나 다 담긴다.
            terms = [c for c, _ in lexicon.extract(t, "free")]
        except Exception:
            terms = []
    # ★ 어휘 하나만으론 근거가 약하다
    #   '러닝 꾸준히 허리에 좋긴함' 도 러닝→스포티 로 한 개는 걸린다.
    #   패션 이야기라면 대개 두 개 이상 나오거나, 평가·구매 신호가 같이 붙는다.
    #   하나뿐이고 다른 신호도 없으면 우연히 스친 것으로 본다.
    if len(terms) >= 2 or (terms and why):
        why.append("term")

    if why:
        return {"keep": True, "why": why, "drop_why": "",
                "terms": terms,
                "intent": got["labels"], "score": got["score"]}

    # 아무 신호도 없지만 아주 길게 쓴 댓글은 남긴다. (40자로 뒀더니
    # 잡담이 25% 나 섞였다 — 새 유행어를 찾는 그물치고는 너무 성겼다.)
    # 사전에 아직 없는 새 유행어가 여기 숨어 있다 — 거르면 영영 못 찾는다.
    if len(t) >= 60:
        return {"keep": True, "why": ["long"], "drop_why": "",
                "intent": [], "score": None}
    if len(t) < min_len:
        return {"keep": False, "why": [], "drop_why": "너무 짧고 신호 없음"}
    return {"keep": False, "why": [], "drop_why": "지표에 쓸 신호가 없음"}
