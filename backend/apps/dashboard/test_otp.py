import base64
import time

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from apps.dashboard.models import DashboardOTPDevice
from apps.dashboard.security import _totp, generate_recovery_codes


@override_settings(DASHBOARD_OTP_REQUIRED=True, DASHBOARD_SESSION_AGE=1800)
class DashboardOTPTests(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = get_user_model().objects.create_user(
            username="otp-ops",
            password="pw-otp-12345",
            is_staff=True,
        )
        self.client = Client()

    def _password_login(self, next_url=""):
        return self.client.post(
            "/admin-dashboard/login/",
            {"username": self.staff.username, "password": "pw-otp-12345", "next": next_url},
        )

    @staticmethod
    def _current_token(device):
        return _totp(device.secret, int(time.time() // 30))

    def test_rfc_6238_sha1_vector(self):
        secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
        self.assertEqual(_totp(secret, 1), "287082")

    def test_password_only_cannot_open_dashboard(self):
        response = self._password_login("/admin-dashboard/system/")
        self.assertRedirects(response, "/admin-dashboard/otp/setup/", fetch_redirect_response=False)
        response = self.client.get("/admin-dashboard/system/")
        self.assertRedirects(response, "/admin-dashboard/otp/setup/", fetch_redirect_response=False)

    def test_enrollment_shows_recovery_codes_and_unlocks_dashboard(self):
        self._password_login()
        device = DashboardOTPDevice.objects.get(user=self.staff)
        response = self.client.post(
            "/admin-dashboard/otp/setup/",
            {"token": self._current_token(device)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "복구 코드를 저장하세요")
        device.refresh_from_db()
        self.assertTrue(device.confirmed)
        self.assertEqual(len(device.recovery_code_hashes), 10)
        self.assertNotIn(response.content.decode(), device.recovery_code_hashes[0])
        self.assertNotIn(self.client.get("/admin-dashboard/").status_code, (302, 403))

    def test_enrollment_page_embeds_server_generated_qr_and_manual_key(self):
        response = self._password_login()
        self.assertRedirects(response, "/admin-dashboard/otp/setup/", fetch_redirect_response=False)
        response = self.client.get("/admin-dashboard/otp/setup/")
        device = DashboardOTPDevice.objects.get(user=self.staff)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="otp-qr"')
        self.assertContains(response, "QR이 안 읽히나요?")
        self.assertContains(response, device.secret)
        self.assertNotContains(response, "api.qrserver.com")

    def test_totp_cannot_be_replayed(self):
        self._password_login()
        device = DashboardOTPDevice.objects.get(user=self.staff)
        token = self._current_token(device)
        self.client.post("/admin-dashboard/otp/setup/", {"token": token})
        self.client.get("/admin-dashboard/logout/")
        self._password_login()
        response = self.client.post("/admin-dashboard/otp/verify/", {"token": token})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "올바르지 않습니다")

    def test_recovery_code_is_one_time(self):
        self._password_login()
        device = DashboardOTPDevice.objects.get(user=self.staff)
        self.client.post("/admin-dashboard/otp/setup/", {"token": self._current_token(device)})
        device.refresh_from_db()
        # 실제 화면에 표시되는 코드 대신 보안 모듈이 만드는 새 코드 하나를 장치에 연결한다.
        from apps.dashboard.security import _recovery_digest
        code = generate_recovery_codes()[0]
        device.recovery_code_hashes = [_recovery_digest(code)]
        device.save(update_fields=["recovery_code_hashes"])

        self.client.get("/admin-dashboard/logout/")
        self._password_login()
        response = self.client.post("/admin-dashboard/otp/verify/", {"token": code})
        self.assertRedirects(response, "/admin-dashboard/", fetch_redirect_response=False)

        self.client.get("/admin-dashboard/logout/")
        self._password_login()
        response = self.client.post("/admin-dashboard/otp/verify/", {"token": code})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "올바르지 않습니다")

    def test_external_next_is_not_followed_after_otp(self):
        self._password_login("//evil.example/x")
        device = DashboardOTPDevice.objects.get(user=self.staff)
        response = self.client.post(
            "/admin-dashboard/otp/setup/",
            {"token": self._current_token(device)},
        )
        self.assertNotContains(response, "evil.example")

    def test_five_bad_codes_are_rate_limited(self):
        self._password_login()
        device = DashboardOTPDevice.objects.get(user=self.staff)
        self.client.post("/admin-dashboard/otp/setup/", {"token": self._current_token(device)})
        self.client.get("/admin-dashboard/logout/")
        self._password_login()
        for _ in range(5):
            self.client.post("/admin-dashboard/otp/verify/", {"token": "000000"})
        response = self.client.post("/admin-dashboard/otp/verify/", {"token": "000000"})
        self.assertEqual(response.status_code, 429)


class DashboardOTPDisabledCompatibilityTests(TestCase):
    @override_settings(DASHBOARD_OTP_REQUIRED=False)
    def test_existing_staff_session_still_works_before_rollout_flag(self):
        staff = get_user_model().objects.create_user(
            username="rollout-ops", password="pw", is_staff=True,
        )
        client = Client()
        client.force_login(staff)
        self.assertNotIn(client.get("/admin-dashboard/").status_code, (302, 403))
