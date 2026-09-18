"""로그인 취향 · 입혀보기 버튼 (2026-09-18).

실측 — 로그인해서 가입 스타일 3개가 DB 에 있는데도 챗봇이 "비로그인 상태의 취향 신호"
라며 취향을 못 썼다. 화면이 user_id 를 안 보냈고, 챗봇의 취향 어댑터도 비어 있었다.
그리고 링크로 옷을 보내 살까 말까를 물어도 입혀보기 버튼이 한 번도 안 떴다.
"""
import sys
from unittest.mock import Mock

sys.modules.setdefault("requests", Mock())

import server
from app.tools import Toolbox, specs_for

TASTE = {"favorite_styles": ["아메카지", "스트릿웨어", "고프코어"],
         "favorite_style_profiles": [{"name": "고프코어", "keywords": ["gorpcore"]}],
         "searched_terms": ["재킷"], "saved_terms": ["아크테릭스"]}


def box(ctx):
    return Toolbox(Mock(), Mock(), ctx=ctx)


def test_logged_in_user_gets_taste_from_profile():
    got = box({"user_id": "31", "taste_context": TASTE}).t_get_user_taste()
    assert got["logged_in"] is True and got["source"] == "profile"
    assert got["favorite_styles"] == TASTE["favorite_styles"]
    assert got["items"][0] == {"name": "아메카지", "why": "즐겨입는 스타일"}


def test_logged_in_without_any_taste_says_why():
    got = box({"user_id": "31", "taste_context": {}}).t_get_user_taste()
    assert got["logged_in"] is True and "unavailable" in got


def test_anonymous_stays_anonymous():
    assert box({}).t_get_user_taste()["logged_in"] is False
    names = [s.get("name") for s in specs_for({})]
    assert "get_user_taste" not in names
    assert "get_user_taste" in [s.get("name") for s in specs_for({"user_id": "31"})]


def labels(rep, mode):
    return [a["label"] for a in server.actions_for(rep, mode=mode)]


def test_tryon_offered_for_linked_product_in_salmal():
    rep = {"question": "https://www.musinsa.com/products/4652858 이 옷 살까말까?", "intent": "agent",
           "item_draft": {"title": "무신사 스탠다드 재킷", "source": "상품 링크에서 확인한 값"}}
    assert "입혀보기" in labels(rep, "salmal")


def test_tryon_offered_when_asked_in_any_mode():
    assert "입혀보기" in labels({"question": "이거 나한테 입혀 줘", "intent": "agent"}, "general")


def test_tryon_offered_for_photo_in_salmal():
    rep = {"question": "이거 어때?", "intent": "agent", "visual_context": {"item": "재킷"}}
    assert "입혀보기" in labels(rep, "salmal")


def test_no_tryon_for_plain_trend_question():
    assert "입혀보기" not in labels({"question": "고프코어 요즘 어때?", "intent": "agent"}, "general")
    assert "입혀보기" not in labels({"question": "고프코어 살까?", "intent": "agent"}, "salmal")
