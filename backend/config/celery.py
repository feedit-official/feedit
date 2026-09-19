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
    #   월요일 09:00 — 주간 트렌드 리포트 (주 1회)
    "notify-weekly": {
        "task": "app.notify_weekly",
        "schedule": crontab(hour=9, minute=0, day_of_week=1),
    },
}

# ============================================================
# SERIALIZER
# ============================================================

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