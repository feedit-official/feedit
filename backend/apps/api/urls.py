"""/api/ 주소.

① 프론트(트렌드 분석 페이지)가 쓰는 읽기 전용 GET — views.py
② 관리자 수집 대상/이력 DRF API — crawl_views.py (SKN31-FINAL-4Team/backend 원본)
"""

from django.urls import path

from . import views
from .crawl_views import (
    CrawlRunDetailAPIView,
    CrawlRunListAPIView,
    CrawlTargetDetailAPIView,
    CrawlTargetListCreateAPIView,
)

app_name = "api"

urlpatterns = [
    # ── 프론트 읽기 전용 ──
    path("health", views.health, name="health"),
    path("terms", views.terms, name="terms"),
    path("dictionary", views.dictionary, name="dictionary"),
    path("facets", views.facets, name="facets"),
    path("trend", views.trend, name="trend"),            # 언급량·온도 / 긍부정
    path("assoc", views.assoc, name="assoc"),            # 연관어
    path("discount", views.discount, name="discount"),   # 할인률 변화
    path("resale", views.resale, name="resale"),         # 리세일 시세 지수
    path("lifecycle", views.lifecycle, name="lifecycle"),  # 수명주기
    path("products", views.products, name="products"),
    path("salmal/card", views.salmal_card, name="salmal-card"),
    path("salmal/search", views.salmal_search, name="salmal-search"),

    # ── 관리자 수집 API (DRF) ──
    path("crawl-targets/", CrawlTargetListCreateAPIView.as_view(), name="crawl-target-list-create"),
    path("crawl-targets/<int:pk>/", CrawlTargetDetailAPIView.as_view(), name="crawl-target-detail"),
    path("crawl-runs/", CrawlRunListAPIView.as_view(), name="crawl-run-list"),
    path("crawl-runs/<int:pk>/", CrawlRunDetailAPIView.as_view(), name="crawl-run-detail"),
]
