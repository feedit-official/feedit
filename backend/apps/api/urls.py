"""프론트가 부르는 읽기 전용 API 의 주소.

`config/urls.py` 에서 `path("api/", include("apps.api.urls"))` 로 건다.
전부 GET 이고 조회만 한다 — 쓰는 길은 여기 두지 않는다.
"""

from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("health", views.health, name="health"),
    path("terms", views.terms, name="terms"),
    # 화면 검색이 쓰는 사전 전체 (용어 + 브랜드)
    path("dictionary", views.dictionary, name="dictionary"),
    # 세부 검색 네 칸(STYLE·종류·브랜드·아이템명)의 후보 — 축끼리 교집합
    path("facets", views.facets, name="facets"),
    path("trend", views.trend, name="trend"),
    path("assoc", views.assoc, name="assoc"),
    path("products", views.products, name="products"),
]
