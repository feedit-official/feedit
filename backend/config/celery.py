from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab


os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)


app = Celery(
    "feedit"
)


app.config_from_object(
    "django.conf:settings",
    namespace="CELERY",
)


app.autodiscover_tasks()


# ============================================================
# QUEUE / ROUTING
# ============================================================

app.conf.task_default_queue = (
    "default"
)

app.conf.task_routes = {
    "core.run_live_target": {
        "queue": "crawl_live",
    },
    "core.dispatch_due_targets": {
        "queue": "crawl_live",
    },
    "core.refresh_text_signals_daily": {
        "queue": "analysis",
    },
    "core.collect_search_daily": {
        "queue": "analysis",
    },
    "core.collect_search_weekly": {
        "queue": "analysis",
    },
}


app.conf.beat_schedule = {
    "dispatch-due-crawl-targets": {
        "task": "core.dispatch_due_targets",
        "schedule": 60.0,
    },
    # ── 알림 (apps/api/tasks.py) ──
    #   시간대는 app.conf.timezone = Asia/Seoul 이다.
    #   매일 10:00 — 찜한 상품 가격 하락(하루 한 번 묶어서) · 용어 사전 등재
    "notify-daily": {
        "task": "app.notify_daily",
        "schedule": crontab(hour=10, minute=0),
    },
    #   일요일 18:00 — 주간 트렌드 리포트 (주 1회)
    "notify-weekly": {
        "task": "app.notify_weekly",
        "schedule": crontab(hour=18, minute=0, day_of_week=0),
    },
    # 매일 04:10 — 최근 YouTube 댓글 수집, 커머스 리뷰 동기화,
    # 공통 LLM 분석과 35일 지표 재계산.
    "refresh-text-signals-daily": {
        "task": "core.refresh_text_signals_daily",
        "schedule": crontab(hour=4, minute=10),
    },
    # ── 검색 신호 (2026-09-21) ──
    #   ★ 주의: 이 파일의 beat_schedule 은 config_from_object(django.conf:settings) 로
    #     읽어 온 settings.CELERY_BEAT_SCHEDULE 을 **통째로 덮어쓴다**(위 대입문).
    #     그래서 새 작업은 반드시 여기에 넣어야 한다 — settings.py 에만 넣으면 안 돈다.
    #
    #   매일 05:30 — 구글 트렌즈(추이·연관어·지역) + 데이터랩 전체 추이.
    #   텍스트 파이프라인(04:10)이 끝난 뒤에 돌려 지표 재계산과 겹치지 않게 한다.
    "collect-search-daily": {
        "task": "core.collect_search_daily",
        "schedule": crontab(hour=5, minute=30),
    },
    #   평일 06:10 — 데이터랩 성별·연령 컷을 요일별로 나눠 돈다.
    #     월 성별(m·f) · 화 10~20대 · 수 30~40대 · 목 50대+ · 금 여유(재시도)
    #   하루 최대 327회로 1,000회 한도에 여유를 남긴다.
    "collect-search-weekly": {
        "task": "core.collect_search_weekly",
        "schedule": crontab(hour=6, minute=10, day_of_week="1-5"),
    },
}

# ============================================================
# SERIALIZER
# ============================================================

# ★ 2026-09-20 — 크롤 대상 실행(1분마다)은 크롤링하는 서버에서만 돈다.
#   API 서버(EC2, compose.api.yml)는 Playwright · OCR 없이 가볍게 돌리므로
#   CELERY_CRAWL_DISPATCH=0 으로 끈다. 켜 두면 아무도 안 받는 crawl_live 큐에 작업만 쌓인다.
if os.getenv("CELERY_CRAWL_DISPATCH", "1") == "0":
    app.conf.beat_schedule.pop("dispatch-due-crawl-targets", None)

app.conf.task_serializer = (
    "json"
)

app.conf.result_serializer = (
    "json"
)

app.conf.accept_content = [
    "json",
]


# ============================================================
# TIMEZONE
# ============================================================

app.conf.timezone = (
    "Asia/Seoul"
)

app.conf.enable_utc = True


# ============================================================
# DEBUG
# ============================================================

@app.task(bind=True)
def debug_task(self):
    print(
        f"Request: {self.request!r}"
    )
