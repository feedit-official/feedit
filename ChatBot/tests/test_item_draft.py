"""'물어보기' 카드로 넘어가는 상품 초안 경로.

링크만 친 질문에서 상품명 칸에 주소가 그대로 들어가던 자리다(2026-09-11).
모델이 확인한 것을 도구 인자로 받아, 그것만 화면으로 넘어가는지 본다.
초안 때문에 도구를 한 번 더 부르지 않는다 — 바퀴가 모자라면 리포트가 사라진다.
"""
import sys
import unittest
from unittest.mock import Mock

sys.modules.setdefault("requests", Mock())

import server
from app import agent_path, tools


class _Trace:
    def __init__(self, calls):
        self.calls = calls
        self.missing = []


class ItemDraftArgTests(unittest.TestCase):
    def test_records_only_confirmed_fields(self):
        draft = tools._item_draft("벌룬 카고 미디 스커트", "허그유어스킨", "89,000원")
        self.assertEqual(draft["name"], "벌룬 카고 미디 스커트")
        self.assertEqual(draft["brand"], "허그유어스킨")
        self.assertEqual(draft["price"], 89000)

    def test_unconfirmed_fields_stay_empty(self):
        draft = tools._item_draft("카고 팬츠", None, None)
        self.assertIsNone(draft["brand"])
        self.assertIsNone(draft["price"])
        self.assertEqual(draft["recorded"], ["name"])

    def test_nothing_confirmed_is_no_draft(self):
        self.assertIsNone(tools._item_draft(None, None, None))

    def test_index_tool_takes_the_identity_in_the_same_call(self):
        spec = [s for s in tools.SPECS if s.get("name") == "get_salmal_index"][0]
        props = set(spec["parameters"]["properties"])
        self.assertEqual(props, {"term", "item_name", "brand", "price"})
        # 초안 전용 도구를 따로 두지 않는다 — 바퀴를 하나 더 쓴다.
        self.assertNotIn("record_item_identity", {s.get("name") for s in tools.SPECS})


class DraftHandoffTests(unittest.TestCase):
    def test_draft_comes_from_the_tool_not_from_the_answer(self):
        trace = _Trace([
            {"tool": "web_search", "args": {}, "result": {"answer": "허그유어스킨 스커트"}},
            {"tool": "get_salmal_index", "args": {}, "result": {
                "score": None,
                "item_draft": {"name": "벌룬 카고 미디 스커트", "brand": "허그유어스킨",
                               "price": 89000, "recorded": ["name", "brand", "price"]}}},
        ])
        draft = agent_path._item_draft(trace)
        self.assertEqual(draft["title"], "벌룬 카고 미디 스커트")
        self.assertEqual(draft["brand"], "허그유어스킨")
        self.assertEqual(draft["price"], 89000)

    def test_falls_back_to_the_name_the_bot_actually_searched(self):
        trace = _Trace([
            {"tool": "search_terms", "args": {"q": "아디다스 럭비 폴로 셔츠"}, "result": {}},
            {"tool": "get_salmal_index", "args": {}, "result": {"score": None}},
        ])
        draft = agent_path._item_draft(trace)
        self.assertEqual(draft["title"], "아디다스 럭비 폴로 셔츠")

    def test_a_link_never_becomes_the_product_name(self):
        trace = _Trace([{"tool": "search_terms",
                         "args": {"q": "https://www.musinsa.com/products/6719206"},
                         "result": {}}])
        self.assertIsNone(agent_path._item_draft(trace))

    def test_no_lookup_means_no_draft(self):
        self.assertIsNone(agent_path._item_draft(_Trace([
            {"tool": "get_metric", "args": {}, "result": {"term": "카고"}}])))

    def test_community_action_carries_the_draft(self):
        acts = server.actions_for(
            {"terms": [], "item_draft": {"title": "벌룬 카고 미디 스커트",
                                         "brand": "허그유어스킨", "price": 89000,
                                         "source": "챗봇이 확인한 값"}},
            mode="salmal")
        community = [a for a in acts if a.get("type") == "community"][0]
        self.assertEqual(community["draft"]["brand"], "허그유어스킨")
        self.assertEqual(community["draft"]["price"], 89000)

    def test_community_action_without_draft_stays_plain(self):
        acts = server.actions_for({"terms": []}, mode="salmal")
        community = [a for a in acts if a.get("type") == "community"][0]
        self.assertNotIn("draft", community)


class TasteContextTests(unittest.TestCase):
    def test_style_profiles_survive_sanitizing(self):
        out = server.clean_taste_context({
            "favorite_styles": ["스케이터"],
            "favorite_style_profiles": [{"name": "스케이터", "keywords": ["카고", "오버핏"]}],
            "user_id": "몰래 끼워 넣은 값",
        })
        self.assertEqual(out["favorite_style_profiles"],
                         [{"name": "스케이터", "keywords": ["카고", "오버핏"]}])
        self.assertNotIn("user_id", out)


if __name__ == "__main__":
    unittest.main()
