from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from celery import shared_task
from django.core.management import call_command
from django.db import close_old_connections, transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.models import CrawlRun, CrawlTarget


logger = logging.getLogger(__name__)


# ============================================================
# CONFIG
# ============================================================

DISPATCH_BATCH_SIZE = 2

LIVE_MAX_RETRIES = 2
LIVE_RETRY_COUNTDOWN = (
    300,
    900,
)


def live_retry_countdown(
    retries: int,
) -> int:
    return LIVE_RETRY_COUNTDOWN[
        min(
            retries,
            len(LIVE_RETRY_COUNTDOWN) - 1,
        )
    ]


# ============================================================
# CELERY SMOKE TEST
# ============================================================


@shared_task(
    name="core.celery_smoke_test",
)
def celery_smoke_test(
    message: str = "FEEDIT DATA CRAWLER",
) -> dict[str, Any]:
    return {
        "ok": True,
        "message": message,
    }


# ============================================================
# LIVE CRAWL
# ============================================================


@shared_task(
    bind=True,
    name="core.run_live_target",
    max_retries=LIVE_MAX_RETRIES,
)
def run_live_target(
    self,
    target_id: int,
) -> dict[str, Any]:
    """
    CrawlTarget 하나 실행.

    실제 처리:
    Collection
        -> RAW
        -> STEP01
        -> STEP02

    이후 생성/갱신된 ProductSource를
    Product Agent로 비동기 전달.
    """

    close_old_connections()

    logger.info(
        "CRAWL START | target=%s task=%s",
        target_id,
        self.request.id,
    )

    try:
        # API container import 시 crawler dependency 문제를
        # 방지하기 위해 실제 실행 시점에 import.
        from collection.common.runner import (
            run_target,
        )

        result = run_target(
            target_id=target_id,
        )

        # ----------------------------------------------------
        # ProductSource IDs
        # ----------------------------------------------------

        step01_result = (
            result.get("step01_ingestion")
            if isinstance(result, dict)
            else None
        )

        product_source_ids: list[int] = []

        if isinstance(step01_result, dict):
            raw_ids = (
                step01_result.get(
                    "product_source_ids"
                )
                or []
            )

            product_source_ids = list(
                dict.fromkeys(
                    int(product_source_id)
                    for product_source_id in raw_ids
                    if product_source_id
                )
            )

        # ----------------------------------------------------
        # Product Agent
        # ----------------------------------------------------

        if product_source_ids:
            run_product_agent_after_collection.apply_async(
                args=[product_source_ids],
                queue="default",
            )

            logger.info(
                "PRODUCT AGENT QUEUED | "
                "target=%s products=%s",
                target_id,
                len(product_source_ids),
            )

        else:
            logger.info(
                "PRODUCT AGENT SKIPPED | "
                "target=%s reason=no_product_source_ids",
                target_id,
            )

        logger.info(
            "CRAWL DONE | target=%s task=%s",
            target_id,
            self.request.id,
        )

        return result

    except Exception as exc:
        retries = (
            self.request.retries
            or 0
        )

        logger.exception(
            "CRAWL FAILED | "
            "target=%s retry=%s/%s",
            target_id,
            retries,
            LIVE_MAX_RETRIES,
        )

        if retries < LIVE_MAX_RETRIES:
            raise self.retry(
                exc=exc,
                countdown=live_retry_countdown(
                    retries
                ),
            )

        raise

    finally:
        close_old_connections()


# ============================================================
# CRAWL ENQUEUE
# ============================================================


def _enqueue_live_target(
    target_id: int,
) -> None:
    """
    DB commit 이후 Crawl task enqueue.

    Broker enqueue 실패 시 next_crawl_at을 현재 시각으로
    되돌려 다음 dispatcher에서 다시 잡히게 한다.
    """

    try:
        run_live_target.apply_async(
            args=[target_id],
            queue="crawl_live",
        )

    except Exception:
        logger.exception(
            "CRAWL ENQUEUE FAILED | target=%s",
            target_id,
        )

        CrawlTarget.objects.filter(
            id=target_id,
            is_active=True,
        ).update(
            next_crawl_at=timezone.now(),
        )


# ============================================================
# LIVE TARGET DISPATCHER
# ============================================================


@shared_task(
    name="core.dispatch_due_targets",
)
def dispatch_due_targets(
    batch_size: int = DISPATCH_BATCH_SIZE,
) -> dict[str, Any]:
    """
    실행 시각이 도래한 LIVE CrawlTarget dispatch.

    중복 방지:
    - select_for_update(skip_locked=True)
    - RUNNING CrawlRun 확인
    - transaction.on_commit 이후 enqueue
    """

    close_old_connections()

    now = timezone.now()

    batch_size = max(
        1,
        int(batch_size),
    )

    dispatched = 0
    target_ids: list[int] = []
    skipped_running: list[int] = []

    try:
        with transaction.atomic():
            targets = list(
                CrawlTarget.objects
                .select_for_update(
                    skip_locked=True
                )
                .select_related("source")
                .filter(
                    is_active=True,
                    collection_mode=(
                        CrawlTarget.CollectionMode.LIVE
                    ),
                )
                .filter(
                    Q(
                        next_crawl_at__isnull=True
                    )
                    | Q(
                        next_crawl_at__lte=now
                    )
                )
                .order_by(
                    "priority",
                    "id",
                )[:batch_size]
            )

            for target in targets:
                is_running = (
                    CrawlRun.objects
                    .filter(
                        crawl_target=target,
                        status="RUNNING",
                    )
                    .exists()
                )

                if is_running:
                    skipped_running.append(
                        target.id
                    )
                    continue

                interval = (
                    target.interval_minutes
                    or target.source.crawl_interval_minutes
                    or 1440
                )

                target.next_crawl_at = (
                    now
                    + timedelta(
                        minutes=interval
                    )
                )

                target.save(
                    update_fields=[
                        "next_crawl_at",
                    ]
                )

                transaction.on_commit(
                    lambda target_id=target.id: (
                        _enqueue_live_target(
                            target_id
                        )
                    )
                )

                target_ids.append(
                    target.id
                )

                dispatched += 1

        return {
            "status": "SUCCESS",
            "dispatched": dispatched,
            "target_ids": target_ids,
            "skipped_running": skipped_running,
        }

    finally:
        close_old_connections()


# ============================================================
# PRODUCT AGENT
# ============================================================


@shared_task(
    bind=True,
    name="core.run_product_agent_after_collection",
    max_retries=2,
    soft_time_limit=60 * 20,
    time_limit=60 * 25,
)
def run_product_agent_after_collection(
    self,
    product_source_ids: list[int],
) -> dict[str, Any]:
    """
    STEP02 완료 ProductSource 대상으로 Product Agent 실행.

    완료 후 동일 ProductSource들을 STEP03 Vision으로 전달.
    """

    close_old_connections()

    ids = list(
        dict.fromkeys(
            int(product_source_id)
            for product_source_id
            in product_source_ids
            if product_source_id
        )
    )

    if not ids:
        return {
            "status": "SKIPPED",
            "reason": "NO_PRODUCT_SOURCE_IDS",
            "target_count": 0,
        }

    from pipeline.product_agents import (
        run_product_agent_fast,
    )

    success = 0
    failed = 0

    results = []
    errors = []

    logger.info(
        "PRODUCT AGENT START | targets=%s",
        len(ids),
    )

    try:
        for index, product_source_id in enumerate(
            ids,
            start=1,
        ):
            logger.info(
                "PRODUCT AGENT [%s/%s] | ps=%s",
                index,
                len(ids),
                product_source_id,
            )

            try:
                result = (
                    run_product_agent_fast(
                        product_source_id=(
                            product_source_id
                        ),
                        apply=True,
                        verbose=False,
                    )
                )

                results.append(result)
                success += 1

            except Exception as exc:
                failed += 1

                logger.exception(
                    "PRODUCT AGENT FAILED | ps=%s",
                    product_source_id,
                )

                errors.append({
                    "product_source_id":
                        product_source_id,
                    "error_type":
                        type(exc).__name__,
                    "error":
                        str(exc),
                })

            finally:
                close_old_connections()

        # ----------------------------------------------------
        # STEP03 Vision
        # ----------------------------------------------------

        run_product_vision_after_agent.apply_async(
            args=[ids],
            queue="vision",
        )

        logger.info(
            "STEP03 VISION QUEUED | targets=%s",
            len(ids),
        )

        return {
            "status": (
                "SUCCESS"
                if failed == 0
                else "PARTIAL"
            ),
            "target_count": len(ids),
            "success": success,
            "failed": failed,
            "results": results,
            "errors": errors,
            "vision_queued": True,
        }

    finally:
        close_old_connections()


# ============================================================
# STEP03 VISION
# ============================================================


@shared_task(
    bind=True,
    name="core.run_product_vision_after_agent",
    max_retries=1,
    soft_time_limit=60 * 30,
    time_limit=60 * 40,
)
def run_product_vision_after_agent(
    self,
    product_source_ids: list[int],
) -> dict[str, Any]:
    """
    STEP03 Vision Style fallback.

    ProductSource 단위 실행.

    Pipeline 내부에서:
    - STYLE 존재 -> SKIP
    - 이미지 없음 -> SKIP
    - confidence 미달 -> SKIP
    - 통과 -> HAS_STYLE 저장
    """

    close_old_connections()

    ids = list(
        dict.fromkeys(
            int(product_source_id)
            for product_source_id
            in product_source_ids
            if product_source_id
        )
    )

    if not ids:
        return {
            "status": "SKIPPED",
            "reason": "NO_PRODUCT_SOURCE_IDS",
            "target_count": 0,
        }

    from pipeline.step03_vision.pipeline import (
        ProductVisionPipeline,
    )

    logger.info(
        "STEP03 VISION START | targets=%s",
        len(ids),
    )

    # 모델을 ProductSource마다 다시 로드하지 않는다.
    pipeline = ProductVisionPipeline()

    success = 0
    skipped = 0
    failed = 0

    results = []
    errors = []

    try:
        for index, product_source_id in enumerate(
            ids,
            start=1,
        ):
            logger.info(
                "STEP03 VISION [%s/%s] | ps=%s",
                index,
                len(ids),
                product_source_id,
            )

            try:
                result = pipeline.run(
                    product_source_id,
                    save=True,
                )

                results.append(result)

                status = (
                    result.get("status")
                    if isinstance(result, dict)
                    else None
                )

                if status == "FAILED":
                    failed += 1

                    errors.append({
                        "product_source_id":
                            product_source_id,
                        "reason":
                            result.get("reason"),
                        "error_type":
                            result.get("error_type"),
                        "error":
                            result.get("error"),
                    })

                elif status == "SKIPPED":
                    skipped += 1

                else:
                    success += 1

            except Exception as exc:
                failed += 1

                logger.exception(
                    "STEP03 VISION FAILED | ps=%s",
                    product_source_id,
                )

                errors.append({
                    "product_source_id":
                        product_source_id,
                    "error_type":
                        type(exc).__name__,
                    "error":
                        str(exc),
                })

            finally:
                close_old_connections()

        logger.info(
            "STEP03 VISION DONE | "
            "targets=%s success=%s "
            "skipped=%s failed=%s",
            len(ids),
            success,
            skipped,
            failed,
        )

        return {
            "status": (
                "SUCCESS"
                if failed == 0
                else "PARTIAL"
            ),
            "target_count": len(ids),
            "success": success,
            "skipped": skipped,
            "failed": failed,
            "results": results,
            "errors": errors,
        }

    finally:
        close_old_connections()


# ============================================================
# STEP04 METRICS - DAILY
# ============================================================


@shared_task(
    bind=True,
    name="core.run_step04_metrics_daily",
    max_retries=2,
    soft_time_limit=60 * 60,
    time_limit=60 * 75,
)
def run_step04_metrics_daily(
    self,
) -> dict[str, Any]:
    """
    전날 STEP04 Metrics 생성.

    Reaction
    -> Commerce
    -> Content
    -> Source Normalize
    -> ALL Aggregate
    -> Search
    -> Final Signal
    -> Temporal
    """

    close_old_connections()

    from pipeline.step04_metrics.pipeline import (
        run_term_metric_pipeline,
    )

    metric_date = (
        timezone.localdate()
        - timedelta(days=1)
    )

    logger.info(
        "STEP04 DAILY START | date=%s",
        metric_date,
    )

    try:
        result = run_term_metric_pipeline(
            metric_date=metric_date,
            search=True,
        )

        logger.info(
            "STEP04 DAILY DONE | date=%s",
            metric_date,
        )

        return {
            "status": "SUCCESS",
            "metric_date":
                metric_date.isoformat(),
            "result": result,
        }

    except Exception as exc:
        logger.exception(
            "STEP04 DAILY FAILED | date=%s",
            metric_date,
        )

        raise self.retry(
            exc=exc,
            countdown=600,
        )

    finally:
        close_old_connections()


# ============================================================
# STEP04 METRICS - BACKFILL
# ============================================================


@shared_task(
    bind=True,
    name="core.backfill_step04_metrics",
    soft_time_limit=60 * 120,
    time_limit=60 * 150,
)
def backfill_step04_metrics(
    self,
    days: int = 28,
) -> dict[str, Any]:
    """
    STEP04 최근 N일 백필.

    MA7 / MA28 / Momentum 계산 때문에
    반드시 과거 -> 현재 순서로 실행.

    Beat 등록 금지.
    서버 초기 배포 또는 복구 시 1회 실행.
    """

    close_old_connections()

    from pipeline.step04_metrics.pipeline import (
        run_term_metric_range,
    )

    days = max(
        1,
        min(
            int(days),
            365,
        ),
    )

    end_date = (
        timezone.localdate()
        - timedelta(days=1)
    )

    start_date = (
        end_date
        - timedelta(
            days=days - 1
        )
    )

    logger.info(
        "STEP04 BACKFILL START | "
        "start=%s end=%s days=%s",
        start_date,
        end_date,
        days,
    )

    try:
        results = run_term_metric_range(
            start_date=start_date,
            end_date=end_date,
            search=True,
        )

        logger.info(
            "STEP04 BACKFILL DONE | "
            "start=%s end=%s processed=%s",
            start_date,
            end_date,
            len(results),
        )

        return {
            "status": "SUCCESS",
            "days": days,
            "start_date":
                start_date.isoformat(),
            "end_date":
                end_date.isoformat(),
            "processed_dates":
                len(results),
        }

    except Exception:
        logger.exception(
            "STEP04 BACKFILL FAILED | "
            "start=%s end=%s",
            start_date,
            end_date,
        )
        raise

    finally:
        close_old_connections()


# ============================================================
# SEARCH SIGNALS
# ============================================================


@shared_task(
    name="core.collect_search_daily",
)
def collect_search_daily() -> dict[str, Any]:
    close_old_connections()

    try:
        call_command(
            "collect_search_signals",
            mode="daily",
        )

        return {
            "status": "SUCCESS",
            "mode": "daily",
        }

    finally:
        close_old_connections()


@shared_task(
    name="core.collect_search_weekly",
)
def collect_search_weekly() -> dict[str, Any]:
    close_old_connections()

    try:
        call_command(
            "collect_search_signals",
            mode="weekly",
        )

        return {
            "status": "SUCCESS",
            "mode": "weekly",
        }

    finally:
        close_old_connections()


@shared_task(
    name="core.collect_search_volume_monthly",
)
def collect_search_volume_monthly() -> dict[str, Any]:
    close_old_connections()

    try:
        call_command(
            "collect_search_signals",
            mode="monthly",
        )

        return {
            "status": "SUCCESS",
            "mode": "monthly",
        }

    finally:
        close_old_connections()


# ============================================================
# DATA FRESHNESS
# ============================================================


@shared_task(
    name="core.check_data_freshness",
)
def check_data_freshness() -> dict[str, Any]:
    close_old_connections()

    try:
        call_command(
            "check_pipeline_freshness"
        )

        return {
            "status": "SUCCESS",
        }

    finally:
        close_old_connections()


# ============================================================
# LEGACY TEXT METRICS
# ============================================================


@shared_task(
    name="core.rebuild_metrics",
)
def rebuild_metrics(
    days: int = 35,
) -> dict[str, Any]:
    """
    기존 text_signals metrics.

    STEP04 Metrics와 별개.
    기존 운영 호환성을 위해 당장은 유지한다.
    """

    close_old_connections()

    days = max(
        1,
        min(
            int(days),
            365,
        ),
    )

    end_date = timezone.localdate()

    start_date = (
        end_date
        - timedelta(
            days=days
        )
    )

    try:
        from analysis.text_signals.metrics import (
            rebuild_text_metrics,
        )

        result = rebuild_text_metrics(
            start_date=start_date,
            end_date=end_date,
        )

        return {
            "status": "SUCCESS",
            "days": days,
            "start_date":
                start_date.isoformat(),
            "end_date":
                end_date.isoformat(),
            "result": result,
        }

    finally:
        close_old_connections()