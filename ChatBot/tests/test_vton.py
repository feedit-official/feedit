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
        self.assertIn("의류 종류를 먼저 판별", sent)
        self.assertEqual(result["categories"], ["양말", "자동 분류"])


if __name__ == "__main__":
    unittest.main()
