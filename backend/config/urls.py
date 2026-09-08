from django.contrib import admin
from django.urls import include, path

from apps.core.views.normalization import (
    normalization_dashboard,
    normalize_brands,
)


urlpatterns = [
    # 프론트(Vercel)가 부르는 읽기 전용 API.
    #   RDS 는 사설이라 프론트가 직접 못 붙는다. RDS 를 인터넷에 여는 대신
    #   이미 RDS 에 닿는 이 Django 가 창구를 내주고 프론트는 그걸 부른다.
    path(
        "api/",
        include("apps.api.urls"),
    ),

    path(
        "admin/normalization/",
        normalization_dashboard,
        name="normalization_dashboard",
    ),

    path(
        "admin/normalization/<int:run_id>/brands/",
        normalize_brands,
        name="normalize_brands",
    ),

    path(
        "admin/",
        admin.site.urls,
    ),
]