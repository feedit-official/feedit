import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.modules.setdefault("requests", Mock())

from app import vton


class VirtualFittingTests(unittest.TestCase):
    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("app.vton.requests.post")
    def test_sends_model_and_all_items_as_image_array(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {"data": [{"b64_json": "result"}]}

        result = vton.generate(
            model_id="woman",
            items=[
                {"image": "data:image/png;base64,eA==", "category": "상의"},
                {"image": "data:image/png;base64,eQ==", "category": "하의"},
            ],
        )

        files = post.call_args.kwargs["files"]
        self.assertEqual([field for field, _file in files],
                         ["image[]", "image[]", "image[]"])
        self.assertEqual(post.call_args.kwargs["data"]["model"],
                         "gpt-image-2.5-sunburst")
        self.assertEqual(result["image"], "data:image/png;base64,result")
        self.assertEqual(result["item_count"], 2)
        self.assertEqual(result["categories"], ["상의", "하의"])

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("app.vton.requests.post")
    def test_keeps_legacy_single_item_contract(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {"data": [{"b64_json": "result"}]}

        result = vton.generate(
            image_data_url="data:image/png;base64,eA==",
            model_id="man",
            category="아우터",
        )

        self.assertEqual(result["categories"], ["아우터"])

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("app.vton.requests.post")
    def test_supports_socks_and_auto_classification_prompt(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {"data": [{"b64_json": "result"}]}

        result = vton.generate(model_id="woman", items=[
            {"image": "data:image/png;base64,eA==", "category": "양말"},
            {"image": "data:image/png;base64,eQ==", "category": "자동 분류"},
        ])

        sent = post.call_args.kwargs["data"]["prompt"]
        self.assertIn("양말", sent)
        # 모자·벨트·안경이 칸에 들어오면서 "의류" 라고 못 박지 않는다 (2026-09-14)
        self.assertIn("종류를 먼저 판별", sent)
        self.assertEqual(result["categories"], ["양말", "자동 분류"])

    # ── 2026-09-14 추가 칸 · 착장 옵션 ─────────────────────────
    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("app.vton.requests.post")
    def test_accessory_slots_carry_their_own_wear_guide(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {"data": [{"b64_json": "result"}]}

        result = vton.generate(model_id="woman", items=[
            {"image": "data:image/png;base64,eA==", "category": "모자"},
            {"image": "data:image/png;base64,eQ==", "category": "벨트"},
            {"image": "data:image/png;base64,eg==", "category": "안경"},
        ])

        sent = post.call_args.kwargs["data"]["prompt"]
        self.assertIn(vton.WEAR_GUIDE["모자"], sent)
        self.assertIn(vton.WEAR_GUIDE["벨트"], sent)
        self.assertIn(vton.WEAR_GUIDE["안경"], sent)
        self.assertEqual(result["categories"], ["모자", "벨트", "안경"])

    def test_options_off_keeps_the_old_prompt(self):
        """전부 꺼진 상태가 기존 동작이다 — 켜지 않은 연출이 새면 안 된다."""
        base = vton.prompt(["상의"])
        self.assertEqual(base, vton.prompt(["상의"], {}))
        self.assertEqual(base, vton.prompt(["상의"], {k: False for k in vton.OPTION_LINES}))

    def test_option_lines_are_added_and_conflicts_dropped(self):
        got = vton.prompt(["아우터"], {"outer_layered": True, "outer_open": True,
                                       "top_open": True, "top_closed": True})
        self.assertIn(vton.OPTION_LINES["outer_layered"], got)
        self.assertIn(vton.OPTION_LINES["outer_open"], got)
        # 열기·닫기를 둘 다 켜 보내면 어느 쪽도 쓰지 않는다 (모순된 지시를 막는다)
        self.assertNotIn(vton.OPTION_LINES["top_open"], got)
        self.assertNotIn(vton.OPTION_LINES["top_closed"], got)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("app.vton.requests.post")
    def test_generate_reports_the_options_it_used(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {"data": [{"b64_json": "result"}]}

        result = vton.generate(
            model_id="woman",
            items=[{"image": "data:image/png;base64,eA==", "category": "아우터"}],
            options={"outer_layered": True, "top_closed": True},
        )

        self.assertEqual(result["options"], ["outer_layered", "top_closed"])


if __name__ == "__main__":
    unittest.main()
