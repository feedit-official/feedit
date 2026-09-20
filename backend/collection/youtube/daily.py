from __future__ import annotations

import os
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.core.models import ContentItem, ContentProfile, CrawlRun, Source
from apps.core.services import create_raw_document, mark_crawl_run_failed, mark_crawl_run_success
from apps.core.services.content import (
    upsert_youtube_comments,
    upsert_youtube_content_items,
    upsert_youtube_content_profile,
)

from .pipeline import YoutubePipeline


def collect_daily_youtube_comments(
    *,
    video_limit: int | None = None,
    comment_limit: int | None = None,
    lookback_days: int | None = None,
) -> dict:
    """최근 YouTube 영상 댓글을 수집해 S3 원본과 TextDocument를 함께 갱신한다."""

    video_limit = video_limit or int(os.getenv("FEEDIT_YOUTUBE_DAILY_VIDEO_LIMIT", "100"))
    comment_limit = comment_limit or int(os.getenv("FEEDIT_YOUTUBE_COMMENT_LIMIT", "100"))
    lookback_days = lookback_days or int(os.getenv("FEEDIT_YOUTUBE_COMMENT_LOOKBACK_DAYS", "180"))
    channel_limit = int(os.getenv("FEEDIT_YOUTUBE_DAILY_CHANNEL_LIMIT", "50"))
    videos_per_channel = int(os.getenv("FEEDIT_YOUTUBE_DAILY_VIDEOS_PER_CHANNEL", "10"))
    source = Source.objects.get(code__iexact="YOUTUBE")
    run = CrawlRun.objects.create(
        source=source,
        run_type=CrawlRun.RunType.LIVE,
        target="daily-youtube-comments",
        params={
            "video_limit": video_limit,
            "comment_limit": comment_limit,
            "lookback_days": lookback_days,
            "channel_limit": channel_limit,
            "videos_per_channel": videos_per_channel,
        },
        status=CrawlRun.Status.RUNNING,
        started_at=timezone.now(),
    )
    discovered = comment_discovered = created = updated = failed = disabled = 0
    channels_refreshed = videos_refreshed = 0
    errors = []
    try:
        if not settings.YOUTUBE_API_KEY:
            raise ValueError("YOUTUBE_API_KEY가 없습니다.")
        if not settings.AWS_STORAGE_BUCKET_NAME:
            raise ValueError("AWS_STORAGE_BUCKET_NAME이 없습니다.")
        pipeline = YoutubePipeline(
            bucket=settings.AWS_STORAGE_BUCKET_NAME,
            region_name=settings.AWS_REGION,
        )

        # ContentProfile을 기준으로 최신 영상부터 갱신한다. CrawlTarget의 활성화
        # 여부와 분리해 두어, 운영자가 개별 타깃을 잠시 꺼도 일일 분석 원천은
        # 기존에 등록된 채널을 계속 따라간다.
        profiles = list(
            ContentProfile.objects.filter(
                source=source,
                status="ACTIVE",
            ).order_by("id")[:channel_limit]
        )
        for profile in profiles:
            try:
                result = pipeline.run_target(
                    target_type="CREATOR",
                    target_url=profile.profile_url,
                    params={
                        "channel_id": profile.external_profile_id,
                        "collect_videos": True,
                        "video_limit": videos_per_channel,
                    },
                )
                create_raw_document(
                    crawl_run=run,
                    document_type=result["entity_type"],
                    external_id=result["source_entity_id"],
                    source_url=result.get("source_url"),
                    s3_bucket=result["s3"]["bucket"],
                    s3_key=result["s3"]["key"],
                    http_status=result.get("http_status"),
                    content_type=result.get("content_type"),
                    collected_at=result.get("collected_at"),
                )
                platform_data = result.get("platform_data") or {}
                discovered += int(result.get("discovered_count") or 0)
                refreshed_profile = upsert_youtube_content_profile(
                    source=source,
                    data=platform_data.get("profile") or {},
                )
                videos = platform_data.get("videos") or []
                if videos:
                    ingested_videos = upsert_youtube_content_items(
                        source=source,
                        videos=videos,
                        profile=refreshed_profile,
                        observed_at=platform_data.get("collected_at"),
                    )
                    videos_refreshed += int(ingested_videos.get("success_count") or 0)
                    failed += int(ingested_videos.get("failure_count") or 0)
                channels_refreshed += 1
            except Exception as exc:
                failed += 1
                errors.append({
                    "channel_id": profile.external_profile_id,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:300],
                })

        since = timezone.now() - timedelta(days=lookback_days)
        items = list(
            ContentItem.objects.filter(
                source=source,
                published_at__gte=since,
            ).order_by("-published_at", "-id")[:video_limit]
        )
        for item in items:
            try:
                result = pipeline.run_target(
                    target_type="VIDEO",
                    target_url=item.content_url,
                    params={
                        "video_id": item.external_content_id,
                        "comment_limit": comment_limit,
                        "comment_order": "time",
                    },
                )
                create_raw_document(
                    crawl_run=run,
                    document_type=result["entity_type"],
                    external_id=result["source_entity_id"],
                    source_url=result.get("source_url"),
                    s3_bucket=result["s3"]["bucket"],
                    s3_key=result["s3"]["key"],
                    http_status=result.get("http_status"),
                    content_type=result.get("content_type"),
                    collected_at=result.get("collected_at"),
                )
                platform_data = result.get("platform_data") or {}
                ingested = upsert_youtube_comments(
                    source=source,
                    content_item=item,
                    comments=platform_data.get("comments") or [],
                )
                discovered += int(result.get("discovered_count") or 0)
                comment_discovered += int(result.get("discovered_count") or 0)
                created += int(ingested.get("created") or 0)
                updated += int(ingested.get("updated") or 0)
                failed += int(ingested.get("failed") or 0)
                disabled += int(bool(platform_data.get("disabled")))
            except Exception as exc:  # 한 영상 실패가 전체 일일 수집을 막지 않는다.
                failed += 1
                errors.append({
                    "video_id": item.external_content_id,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:300],
                })
        mark_crawl_run_success(
            run,
            discovered_count=discovered,
            success_count=channels_refreshed + videos_refreshed + created + updated,
            failure_count=failed,
        )
    except Exception as exc:
        mark_crawl_run_failed(run, error=exc, error_code=type(exc).__name__)
        raise
    return {
        "crawl_run_id": run.id,
        "channels_refreshed": channels_refreshed,
        "videos_refreshed": videos_refreshed,
        "videos": len(items),
        "entities_discovered": discovered,
        "comments_discovered": comment_discovered,
        "created": created,
        "updated": updated,
        "failed": failed,
        "comments_disabled_videos": disabled,
        "errors": errors[:20],
    }
