"""알림 규칙(notifications.py) 단위 테스트 — DB 없이 돈다.

돌리는 법:  cd backend && python -m unittest apps.api.test_notifications
"""
import unittest
from datetime import date, datetime, timezone as dt_timezone

from apps.api.notifications import (
    KST,
    PRICE_DROP_MIN_RATE,
    badge_text,
    drop_rate,
    has_final,
    kst_day,
    price_digest,
    price_drops,
    term_added_text,
    vote_milestone,
    vote_result_text,
    weekly_report_text,
)


def item(name, base, current):
    return {"item_id": name, "name": name, "base": base, "current": current}


class PriceDropTest(unittest.TestCase):
    def test_drop_rate(self):
        self.assertAlmostEqual(drop_rate(100000, 85000), 0.15)
        self.assertIsNone(drop_rate(100000, 100000))   # 그대로면 하락이 아니다
        self.assertIsNone(drop_rate(100000, 120000))   # 올랐다
        self.assertIsNone(drop_rate(None, 1000))
        self.assertIsNone(drop_rate(0, 1000))

    def test_small_drop_is_ignored(self):
        """1~2% 는 판매처의 일상적인 등락이라 알리지 않는다."""
        self.assertEqual(price_drops([item("A", 100000, 99000)]), [])
        self.assertEqual(len(price_drops([item("A", 100000, 100000 * (1 - PRICE_DROP_MIN_RATE))])), 1)

    def test_sorted_by_rate(self):
        drops = price_drops([item("A", 100, 90), item("B", 100, 50), item("C", 100, 80)])
        self.assertEqual([d["name"] for d in drops], ["B", "C", "A"])
        self.assertEqual([d["percent"] for d in drops], [50, 20, 10])

    def test_digest_one(self):
        title, body = price_digest(price_drops([item("발레 플랫", 100000, 85000)]))
        self.assertEqual(title, "찜한 발레 플랫이 15% 내려갔어요.")
        self.assertEqual(body, "")

    def test_digest_many_is_one_line(self):
        """상품마다 한 건씩 보내지 않는다 — 하루치를 한 줄로 묶는다."""
        drops = price_drops([item("A", 100, 80), item("B", 100, 70), item("C", 100, 60)])
        title, body = price_digest(drops)
        self.assertEqual(title, "찜한 상품 3개가 내려갔어요.")
        self.assertEqual(body, "C 40% · B 30% · A 20%")

    def test_digest_caps_at_five(self):
        drops = price_drops([item(f"P{i}", 100, 50) for i in range(8)])
        _title, body = price_digest(drops)
        self.assertTrue(body.endswith("외 3개"))

    def test_digest_empty(self):
        self.assertEqual(price_digest([]), (None, None))


class VoteResultTest(unittest.TestCase):
    def test_milestone(self):
        self.assertIsNone(vote_milestone(9))
        self.assertEqual(vote_milestone(10), 10)
        self.assertEqual(vote_milestone(31), 10)

    def test_text_counts_are_not_conclusions(self):
        title, body = vote_result_text(10, 7, "스퀘어 토 로퍼")
        self.assertEqual(title, "10명 중 7명이 '살!'이라고 했어요.")
        self.assertEqual(body, "스퀘어 토 로퍼")

    def test_no_votes(self):
        self.assertEqual(vote_result_text(0, 0), (None, None))


class OtherTextTest(unittest.TestCase):
    def test_badge(self):
        self.assertEqual(badge_text("살말 백전 100")[0], "뱃지 '살말 백전 100'을 달성했어요.")

    def test_term_added_shows_canonical_when_different(self):
        title, body = term_added_text("블로 코어", "블록코어")
        self.assertEqual(title, "요청한 '블로 코어'가 사전에 올라갔어요.")
        self.assertEqual(body, "사전에는 '블록코어'로 올라갔어요.")

    def test_term_added_same_name(self):
        self.assertEqual(term_added_text("고프코어", "고프코어")[1], "")

    def test_weekly(self):
        title, _body = weekly_report_text(date(2026, 9, 14))
        self.assertEqual(title, "이번 주 트렌드 리포트가 도착했어요.")


class JosaTest(unittest.TestCase):
    """조사 — 상품명·용어는 우리가 고른 말이 아니다."""

    def test_hangul(self):
        self.assertTrue(has_final("플랫"))
        self.assertFalse(has_final("로퍼"))

    def test_digit_reading(self):
        self.assertTrue(has_final("살말 백전 100"))    # 백 → 받침 있음
        self.assertFalse(has_final("개근상 2"))        # 이 → 받침 없음

    def test_price_digest_picks_josa(self):
        title, _ = price_digest(price_drops([item("로퍼", 100000, 80000)]))
        self.assertEqual(title, "찜한 로퍼가 20% 내려갔어요.")

    def test_badge_josa(self):
        self.assertEqual(badge_text("스타일 입문자")[0], "뱃지 '스타일 입문자'를 달성했어요.")


class DayTest(unittest.TestCase):
    def test_kst_day_groups_by_korean_date(self):
        """배치가 UTC 로 돌아도 '하루 한 번'은 한국 날짜로 묶인다."""
        at = datetime(2026, 9, 19, 16, 0, tzinfo=dt_timezone.utc)   # KST 9/20 01:00
        self.assertEqual(kst_day(at), date(2026, 9, 20))
        self.assertEqual(kst_day(datetime(2026, 9, 19, 1, 0, tzinfo=KST)), date(2026, 9, 19))


if __name__ == "__main__":
    unittest.main()
