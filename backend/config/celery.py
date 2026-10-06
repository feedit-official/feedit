from __future__ import annotations

import os

from celery import Celery


os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

app = Celery("feedit")

app.config_from_object(
    "django.conf:settings",
    namespace="CELERY",
)

app.autodiscover_tasks()


# ============================================================
# QUEUES / ROUTING
# ============================================================

app.conf.task_default_queue = "default"

app.conf.task_routes = {
    # --------------------------------------------------------
    # CRAWL
    # --------------------------------------------------------
    "core.dispatch_due_targets": {
        "queue": "crawl_live",
    },
    "core.run_live_target": {
        "queue": "crawl_live",
    },

    # --------------------------------------------------------
    # PRODUCT AGENT
    # --------------------------------------------------------
    "core.run_product_agent_after_collection": {
        "queue": "default",
    },

    # --------------------------------------------------------
    # STEP03 VISION
    # --------------------------------------------------------
    "core.run_product_vision_after_agent": {
        "queue": "vision",
    },

    # --------------------------------------------------------
    # ANALYSIS / SEARCH
    # --------------------------------------------------------
    "core.refresh_text_signals_daily": {
        "queue": "analysis",
    },
    "core.collect_search_daily": {
        "queue": "analysis",
    },
    "core.collect_search_weekly": {
        "queue": "analysis",
    },
    "core.collect_search_volume_monthly": {
        "queue": "analysis",
    },

    # 기존 legacy metrics
    # 현재 STEP04와 별개이므로 당장 삭제하지 않는다.
    "core.rebuild_metrics": {
        "queue": "analysis",
    },

    # --------------------------------------------------------
    # STEP04 METRICS
    # --------------------------------------------------------
    "core.run_step04_metrics_daily": {
        "queue": "analysis",
    },
    "core.backfill_step04_metrics": {
        "queue": "analysis",
    },

    # --------------------------------------------------------
    # OPS
    # --------------------------------------------------------
    "core.check_data_freshness": {
        "queue": "analysis",
    },
}


# ============================================================
# CRAWL DISPATCH SWITCH
# ============================================================

# CELERY_BEAT_SCHEDULE의 single source of truth는 settings.py.
#
# 크롤하지 않는 서버에서는:
#
# CELERY_CRAWL_DISPATCH=0
#
# 으로 dispatcher만 제거한다.

if os.getenv(
    "CELERY_CRAWL_DISPATCH",
    "1",
) == "0":
    schedule = dict(
        app.conf.beat_schedule or {}
    )

    schedule.pop(
        "dispatch-due-crawl-targets",
        None,
    )

    app.conf.beat_schedule = schedule


# ============================================================
# DEBUG
# ============================================================


@app.task(bind=True)
def debug_task(self):
    print(
        f"Request: {self.request!r}"
    )