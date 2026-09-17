"""/api/ 주소.

① 프론트(트렌드 분석 페이지)가 쓰는 읽기 전용 GET — views.py
② 관리자 수집 대상/이력 DRF API — crawl_views.py (SKN31-FINAL-4Team/backend 원본)
"""

from django.urls import path

from . import activity_views, auth_views, views
from .crawl_views import (
    CrawlRunDetailAPIView,
    CrawlRunListAPIView,
    CrawlTargetDetailAPIView,
    CrawlTargetListCreateAPIView,
)

app_name = "api"

urlpatterns = [
    # ── 사용자 세션·프로필 ──
    path("auth/me", auth_views.me, name="auth-me"),
    path("auth/signup", auth_views.signup, name="auth-signup"),
    path("auth/login", auth_views.login, name="auth-login"),
    path("auth/google", auth_views.google_login, name="auth-google"),
    path("auth/google-signup", auth_views.google_signup, name="auth-google-signup"),
    path("auth/logout", auth_views.logout, name="auth-logout"),
    path("auth/profile", auth_views.profile, name="auth-profile"),
    path("auth/weekly-videos", auth_views.weekly_videos, name="auth-weekly-videos"),
    # ── 사용자 활동 기록 · 금주의 리포트 (activity_views.py) ──
    path("auth/event", activity_views.event, name="auth-event"),                    # 검색 · 챗봇 사용
    path("auth/vote", activity_views.vote, name="auth-vote"),                       # 살!말? 투표
    path("auth/saved", activity_views.saved, name="auth-saved"),                    # 찜 / 찜 해제
    path("auth/weekly-report", activity_views.weekly_report, name="auth-weekly-report"),

    # ── 프론트 읽기 전용 ──
    path("health", views.health, name="health"),
    path("terms", views.terms, name="terms"),
    path("dictionary", views.dictionary, name="dictionary"),
    path("facets", views.facets, name="facets"),
    path("trend", views.trend, name="trend"),            # 언급량·온도 / 긍부정
    path("sentiment", views.sentiment, name="sentiment"),  # 댓글 원문 기반 긍부정
    path("assoc", views.assoc, name="assoc"),            # 연관어
    path("discount", views.discount, name="discount"),   # 할인률 변화
    path("resale", views.resale, name="resale"),         # 리세일 시세 지수
    path("lifecycle", views.lifecycle, name="lifecycle"),  # 수명주기
    path("products", views.products, name="products"),
    path("price-history", views.price_history, name="price-history"),  # 찜한 상품 가격 기록
    path("salmal/card", views.salmal_card, name="salmal-card"),
    path("salmal/search", views.salmal_search, name="salmal-search"),

    # ── 관리자 수집 API (DRF) ──
    path("crawl-targets/", CrawlTargetListCreateAPIView.as_view(), name="crawl-target-list-create"),
    path("crawl-targets/<int:pk>/", CrawlTargetDetailAPIView.as_view(), name="crawl-target-detail"),
    path("crawl-runs/", CrawlRunListAPIView.as_view(), name="crawl-run-list"),
    path("crawl-runs/<int:pk>/", CrawlRunDetailAPIView.as_view(), name="crawl-run-detail"),
]
