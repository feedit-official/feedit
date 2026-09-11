import unittest

from app import salmal_index
from app.agent_blocks import salmal_blocks


class SalmalIndexTests(unittest.TestCase):
    def test_renormalizes_only_available_signals(self):
        result = salmal_index.calculate(
            term="발레코어",
            product_tags=["발레코어"],
            taste_context={"favorite_styles": ["발레코어"], "saved_terms": ["발레코어"]},
            trend={"temp": 80},
        )
        self.assertEqual(result["score"], 95)
        self.assertEqual(result["coverage"], 80)
        self.assertEqual(result["recommendation"], "살")
        self.assertEqual(result["missing"], ["price", "community"])

    def test_taste_axis_uses_favorite_style_keywords(self):
        """가입할 때 고른 스타일과 상품 이름은 어휘가 다르다.

        스타일 이름만으로 맞대면 겹치는 일이 없어 취향 축이 늘 '거리'로
        떨어졌다. 스타일의 대표 어휘로 비교하는지 본다.
        """
        ctx = {"favorite_style_profiles": [
            {"name": "스케이터", "keywords": ["카고", "오버핏", "스케이트 슈즈"]}]}
        hit = salmal_index.calculate(
            term="벌룬 카고 미디 스커트", product_tags=["카고", "미디 스커트"],
            taste_context=ctx)
        taste = [s for s in hit["signals"] if s["key"] == "taste"][0]
        self.assertEqual(taste["score"], 100)
        self.assertIn("카고", taste["why"])

        miss = salmal_index.calculate(
            term="캐시미어 머플러", product_tags=["머플러"], taste_context=ctx)
        taste = [s for s in miss["signals"] if s["key"] == "taste"][0]
        self.assertEqual(taste["score"], 25)
        self.assertIn("스케이터", taste["why"])

    def test_taste_axis_stays_silent_without_favorite_styles(self):
        result = salmal_index.calculate(term="카고 팬츠", product_tags=["카고"],
                                        taste_context={"saved_terms": ["카고"]})
        self.assertNotIn("taste", [s["key"] for s in result["signals"]])
        self.assertIn("taste", result["missing"])

    def test_community_alone_never_becomes_recommendation(self):
        result = salmal_index.calculate(community={"buy_pct": 96, "total": 1000})
        self.assertEqual(result["score"], 96)
        self.assertEqual(result["recommendation"], "보류")
        self.assertFalse(result["recommendation_allowed"])
        self.assertEqual(result["coverage"], 5)

    def test_missing_data_is_not_filled_with_neutral_number(self):
        result = salmal_index.calculate()
        self.assertIsNone(result["score"])
        self.assertEqual(result["recommendation"], "판단 자료 부족")

    def test_report_uses_existing_safe_block_types(self):
        blocks = salmal_blocks({"score": 72, "recommendation": "살", "confidence": "보통",
                                "coverage": 60, "signals": [], "missing": ["price"]})
        self.assertEqual([block["type"] for block in blocks], ["kpis", "note"])
        self.assertEqual(blocks[0]["items"][0]["v"], "72")


if __name__ == "__main__":
    unittest.main()
