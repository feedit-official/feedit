import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.modules.setdefault("requests", Mock())

from app import vton


class VirtualFittingTests(unittest.TestCase):
    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("app.vton.requests.post")
    def test_sends_model_and_item_as_image_array(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {"data": [{"b64_json": "result"}]}

        result = vton.generate(
            image_data_url="data:image/png;base64,eA==",
            model_id="woman",
            category="상의",
        )

        files = post.call_args.kwargs["files"]
        self.assertEqual([field for field, _file in files], ["image[]", "image[]"])
        self.assertEqual(post.call_args.kwargs["data"]["model"], "gpt-image-2")
        self.assertEqual(result["image"], "data:image/png;base64,result")


if __name__ == "__main__":
    unittest.main()
