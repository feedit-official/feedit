"""운영 화면 '지표 다시 계산' (ADMIN-001, 2026-09-27)."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase


class RebuildMetricsTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.staff = User.objects.create_user(username="ops", password="x", is_staff=True)
        self.normal = User.objects.create_user(username="n", password="x")
        self.c = Client()
        self.c.force_login(self.staff)

    def test_버튼이_보인다(self):
        html = self.c.get("/admin-dashboard/trend/metrics/").content.decode()
        self.assertIn("지표 다시 계산", html)
        self.assertIn('value="365"', html)

    def test_누르면_셀러리에_맡긴다(self):
        with mock.patch("apps.core.tasks.rebuild_metrics.delay") as delay:
            delay.return_value.id = "abcdef123456"
            res = self.c.post("/admin-dashboard/trend/metrics/rebuild/", {"days": "90"}, follow=True)
        delay.assert_called_once_with(90)
        self.assertIn("최근 90일 지표 다시 계산을 요청했습니다", res.content.decode())

    def test_연타는_한_번만(self):
        with mock.patch("apps.core.tasks.rebuild_metrics.delay") as delay:
            delay.return_value.id = "x"
            self.c.post("/admin-dashboard/trend/metrics/rebuild/", {"days": "35"})
            res = self.c.post("/admin-dashboard/trend/metrics/rebuild/", {"days": "35"}, follow=True)
        self.assertEqual(delay.call_count, 1)
        self.assertIn("아직 돌고 있습니다", res.content.decode())

    def test_정해진_기간만(self):
        with mock.patch("apps.core.tasks.rebuild_metrics.delay") as delay:
            res = self.c.post("/admin-dashboard/trend/metrics/rebuild/", {"days": "9999"}, follow=True)
        delay.assert_not_called()
        self.assertIn("기간이 올바르지 않습니다", res.content.decode())

    def test_브로커가_죽어도_화면은_산다(self):
        with mock.patch("apps.core.tasks.rebuild_metrics.delay", side_effect=ConnectionError("redis")):
            res = self.c.post("/admin-dashboard/trend/metrics/rebuild/", {"days": "35"}, follow=True)
        self.assertIn("작업을 보내지 못했습니다", res.content.decode())
        self.assertTrue(cache.add("dashboard:rebuild-metrics", 1, 5), "실패하면 잠금을 풀어야 다시 누를 수 있다")

    def test_GET_은_아무것도_안_한다(self):
        with mock.patch("apps.core.tasks.rebuild_metrics.delay") as delay:
            self.c.get("/admin-dashboard/trend/metrics/rebuild/")
        delay.assert_not_called()

    def test_일반_회원은_못_누른다(self):
        c = Client(); c.force_login(self.normal)
        with mock.patch("apps.core.tasks.rebuild_metrics.delay") as delay:
            c.post("/admin-dashboard/trend/metrics/rebuild/", {"days": "35"})
        delay.assert_not_called()

    def test_작업은_기간을_넘겨_계산한다(self):
        from apps.core.tasks import rebuild_metrics
        with mock.patch("analysis.text_signals.metrics.rebuild_text_metrics", return_value={"rows": 3}) as fn:
            got = rebuild_metrics(90)
        kwargs = fn.call_args.kwargs
        self.assertEqual((kwargs["until"] - kwargs["since"]).days, 90)
        self.assertEqual(got["days"], 90)
