"""일반 가입·로그인과 Google 로그인 API 테스트.

Google 토큰 서버는 부르지 않는다 — exchange_code 를 가짜로 바꿔 끼운다.
실행:  python manage.py test apps.api.test_auth_google
"""

import time
from unittest import mock

from django.contrib.auth.models import User
from django.test import Client, TestCase

from apps.api import google_auth
from apps.core.models import AppUser

IDENTITY = {"sub": "1234567890", "email": "me@gmail.com", "name": "구글회원", "picture": ""}


class AuthApiTests(TestCase):
    def setUp(self):
        # CSRF 까지 실제와 같게 검사한다.
        self.c = Client(enforce_csrf_checks=True)
        self.csrf = self.c.get("/api/auth/me").json()["data"]["csrf_token"]

    def post(self, path, body):
        return self.c.post(path, body, content_type="application/json", HTTP_X_CSRFTOKEN=self.csrf)

    # ── 일반 가입·로그인 ──
    def test_signup_hashes_password_and_login_keeps_session(self):
        r = self.post("/api/auth/signup", {"username": "feedit01", "nickname": "피딧", "password": "Secret!234"})
        self.assertEqual(r.status_code, 201, r.content)
        user = User.objects.get(username="feedit01")
        self.assertNotEqual(user.password, "Secret!234")
        self.assertTrue(user.check_password("Secret!234"))
        self.assertTrue(AppUser.objects.filter(user=user).exists())

        self.csrf = r.json()["data"]["csrf_token"]
        self.post("/api/auth/logout", {})
        self.assertFalse(self.c.get("/api/auth/me").json()["data"]["authenticated"])
        self.csrf = self.c.get("/api/auth/me").json()["data"]["csrf_token"]
        self.assertEqual(self.post("/api/auth/login", {"username": "feedit01", "password": "wrong"}).status_code, 401)
        r = self.post("/api/auth/login", {"username": "feedit01", "password": "Secret!234"})
        self.assertEqual(r.status_code, 200, r.content)
        me = self.c.get("/api/auth/me").json()["data"]
        self.assertTrue(me["authenticated"])
        self.assertEqual(me["user"]["nickname"], "피딧")

    def test_post_without_csrf_is_rejected(self):
        r = self.c.post("/api/auth/login", {"username": "a", "password": "b"}, content_type="application/json")
        self.assertEqual(r.status_code, 403)

    # ── Google ──
    def test_google_not_configured(self):
        with mock.patch.dict("os.environ", {"GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": ""}):
            self.assertEqual(self.post("/api/auth/google", {"code": "x"}).status_code, 503)

    @mock.patch.dict("os.environ", {"GOOGLE_CLIENT_ID": "cid", "GOOGLE_CLIENT_SECRET": "sec"})
    def test_google_first_visit_then_signup_then_login(self):
        self.assertEqual(self.c.get("/api/auth/me").json()["data"]["google_client_id"], "cid")
        with mock.patch.object(google_auth, "exchange_code", return_value=dict(IDENTITY)):
            r = self.post("/api/auth/google", {"code": "c1"})
        data = r.json()["data"]
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(data["authenticated"])
        self.assertTrue(data["needs_signup"])
        self.assertEqual(data["google"]["email"], "me@gmail.com")
        self.assertEqual(User.objects.count(), 0, "가입 폼을 끝내기 전에는 계정을 만들지 않는다")

        r = self.post("/api/auth/google-signup", {"nickname": "구글회원", "height": 170, "weight": 60})
        self.assertEqual(r.status_code, 201, r.content)
        user = User.objects.get(email="me@gmail.com")
        self.assertFalse(user.has_usable_password(), "Google 계정은 비밀번호 로그인이 막혀 있어야 한다")
        self.assertEqual(user.feedit_profile.profile_metadata["google_sub"], "1234567890")
        self.assertEqual(user.feedit_profile.body_type, "표준")
        self.assertTrue(self.c.get("/api/auth/me").json()["data"]["authenticated"])

        # 두 번째 방문 — 가입 폼 없이 바로 로그인
        self.csrf = r.json()["data"]["csrf_token"]
        self.post("/api/auth/logout", {})
        self.csrf = self.c.get("/api/auth/me").json()["data"]["csrf_token"]
        with mock.patch.object(google_auth, "exchange_code", return_value=dict(IDENTITY)):
            r = self.post("/api/auth/google", {"code": "c2"})
        self.assertTrue(r.json()["data"]["authenticated"], r.content)
        self.assertEqual(User.objects.count(), 1)

    @mock.patch.dict("os.environ", {"GOOGLE_CLIENT_ID": "cid", "GOOGLE_CLIENT_SECRET": "sec"})
    def test_google_signup_requires_google_step(self):
        r = self.post("/api/auth/google-signup", {"nickname": "몰래가입"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(User.objects.count(), 0)

    @mock.patch.dict("os.environ", {"GOOGLE_CLIENT_ID": "cid", "GOOGLE_CLIENT_SECRET": "sec"})
    def test_same_email_password_account_is_not_hijacked(self):
        # 누군가 남의 Gmail 주소를 이메일로 넣어 아이디 가입을 해도 Google 로그인과 연결되지 않는다.
        self.post("/api/auth/signup", {"username": "attacker1", "nickname": "공격자", "password": "Secret!234", "email": "me@gmail.com"})
        self.c.logout()
        self.csrf = self.c.get("/api/auth/me").json()["data"]["csrf_token"]
        with mock.patch.object(google_auth, "exchange_code", return_value=dict(IDENTITY)):
            r = self.post("/api/auth/google", {"code": "c"})
        self.assertTrue(r.json()["data"]["needs_signup"])


class GoogleClaimTests(TestCase):
    @mock.patch.dict("os.environ", {"GOOGLE_CLIENT_ID": "cid"})
    def test_claims(self):
        good = {"aud": "cid", "iss": "https://accounts.google.com", "exp": time.time() + 60,
                "sub": "1", "email": "a@gmail.com", "email_verified": True}
        self.assertEqual(google_auth.verify_claims(good)["sub"], "1")
        for bad in ({"aud": "other"}, {"iss": "evil.com"}, {"exp": time.time() - 1}, {"email_verified": False}):
            with self.assertRaises(google_auth.GoogleAuthError):
                google_auth.verify_claims({**good, **bad})
