"""실제 DB 기반 살!말? 카드 목록·댓글 API."""

from __future__ import annotations

import json
import math
import re
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.core.models import (
    AppUser,
    DictionaryTerm,
    ProductSourceSnapshot,
    UserTaste,
    VoteBallot,
    VoteCard,
    VoteComment,
)

from .salmal_storage import VoteImageError, delete_vote_image, upload_vote_image, vote_image_url

VISIBLE_CARD_FILTER = Q(seed_key__startswith="youtube:") | Q(seed_key__startswith="user:")


def _ok(data, status=200):
    return JsonResponse({"status": "ok", "data": data}, status=status)


def _error(reason, status=400):
    return JsonResponse({"status": "error", "reason": reason, "data": None}, status=status)


def _profile(request):
    if not request.user.is_authenticated:
        return None
    return AppUser.objects.filter(user=request.user).first()


def _request_data(request):
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _clean_text(value, limit):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _close_expired_cards(now=None):
    """마감 시각이 지난 진행 중 카드를 종료 상태로 동기화한다."""
    now = now or timezone.now()
    return VoteCard.objects.filter(
        status=VoteCard.Status.ACTIVE,
        closes_at__isnull=False,
        closes_at__lte=now,
    ).update(status=VoteCard.Status.CLOSED)


def _comment_time(value):
    """24시간까지는 상대 시간, 그 이후에는 작성 날짜를 보여 준다."""
    local_value = timezone.localtime(value)
    elapsed = timezone.localtime(timezone.now()) - local_value
    hours = max(1, int(elapsed.total_seconds() // 3600))
    return f"{hours}시간 전" if hours < 24 else f"{local_value.month}월 {local_value.day}일"


def _vote_summary(card, ballots=None):
    ballots = list(ballots if ballots is not None else card.ballots.all())
    buy = sum(row.choice == VoteBallot.Choice.BUY for row in ballots)
    total = len(ballots)
    return {
        "total": total,
        "buy": buy,
        "pass": total - buy,
        "buy_pct": round(buy * 100 / total) if total else 50,
        "pass_pct": round((total - buy) * 100 / total) if total else 50,
    }


def _taste_context(cards, profile):
    user_ids = {ballot.user_id for card in cards for ballot in card.ballots.all()}
    if profile is not None:
        user_ids.add(profile.id)
    tastes_by_user = {}
    names_by_user = {}
    rows = UserTaste.objects.filter(
        user_id__in=user_ids, taste_type=UserTaste.TasteType.TERM
    ).values_list("user_id", "term_id", "term__canonical_name")
    for user_id, term_id, name in rows:
        tastes_by_user.setdefault(user_id, set()).add(term_id)
        names_by_user.setdefault(user_id, set()).add(name)
    return tastes_by_user, names_by_user


def _empty_similar(reason):
    """비슷한 사용자 표본이 없을 때 돌려줄 값.

    예전에는 표본이 0명이면 **전체 투표 결과를 그대로 돌려줬다**. 그러면 화면은
    "나와 비슷한 사용자들"이라 써 놓고 실제로는 전체 숫자를 보여 준다 —
    숫자를 지어내지 않는다는 원칙에 어긋난다. 그래서 비율은 None 으로 두고
    **왜 없는지**를 함께 보낸다. 화면은 이 reason 을 그대로 쓴다.
    """
    return {
        "total": 0,
        "buy": 0,
        "pass": 0,
        "buy_pct": None,
        "pass_pct": None,
        "sample_users": 0,
        "has_sample": False,
        "reason": reason,
    }


def _similar_summary(card, profile, tastes_by_user):
    """성별·체형·나이(±5년)·취향 중 둘 이상이 겹치는 투표자만 모아 비율을 낸다."""
    ballots = list(card.ballots.all())
    if profile is None:
        return _empty_similar("로그인하면 나와 비슷한 사용자들의 결과를 볼 수 있습니다.")
    style_ids = tastes_by_user.get(profile.id, set())
    # 비교할 기준이 하나도 없으면 '비슷하다'를 판정할 방법이 없다.
    if not (profile.gender or profile.body_type or profile.birth_year or style_ids):
        return _empty_similar(
            "마이페이지에서 성별·체형·출생연도나 즐겨입는 스타일을 채우면 "
            "비슷한 사용자를 찾을 수 있습니다."
        )
    candidates = []
    for ballot in ballots:
        other = ballot.user
        if getattr(other, "id", None) == profile.id:
            continue
        score = 0
        if profile.gender and other.gender == profile.gender:
            score += 1
        if profile.body_type and other.body_type == profile.body_type:
            score += 1
        if profile.birth_year and other.birth_year and abs(profile.birth_year - other.birth_year) <= 5:
            score += 1
        other_styles = tastes_by_user.get(other.id, set())
        if style_ids & other_styles:
            score += 1
        if score >= 2:
            candidates.append(ballot)
    if not candidates:
        return _empty_similar("아직 나와 비슷한 사용자가 이 카드에 투표하지 않았습니다.")
    summary = _vote_summary(card, candidates)
    summary["sample_users"] = len(candidates)
    summary["has_sample"] = True
    summary["reason"] = ""
    return summary


def _buyer_rating(snapshot):
    """판매처가 보여 주는 구매 평점 — 0~5 점 기준, 후기 수와 관측 시각을 같이."""
    if not snapshot or snapshot.get("rating") is None:
        return None
    try:
        rating = float(snapshot["rating"])
    except (TypeError, ValueError):
        return None
    if rating <= 0:
        return None
    scale = 5 if rating <= 5 else 100
    return {
        "rating": round(rating, 2),
        "scale": scale,
        "review_count": snapshot.get("review_count"),
        "observed_at": snapshot.get("observed_at"),
    }


def _activity(hours=24):
    """최근 N시간 안에 살말에 참여(투표·댓글·카드 작성)한 사람 수 — 지어낸 실시간 인원 대신."""
    since = timezone.now() - timedelta(hours=hours)
    users = set(VoteBallot.objects.filter(created_at__gte=since).values_list("user_id", flat=True))
    users |= set(VoteComment.objects.filter(created_at__gte=since, is_deleted=False)
                 .values_list("user_id", flat=True))
    users |= set(VoteCard.objects.filter(created_at__gte=since, seed_key__startswith="user:")
                 .values_list("user_id", flat=True))
    return {"hours": hours, "participants": len(users)}


def _card_payload(card, profile, tastes_by_user, taste_names_by_user):
    source = card.product_source
    product = card.product
    snapshot = None
    if source is not None:
        snapshot = (
            ProductSourceSnapshot.objects.filter(product_source=source)
            .order_by("-observed_at")
            .values("sale_price", "list_price", "rating", "review_count", "observed_at")
            .first()
        )
    ballots = list(card.ballots.all())
    summary = _vote_summary(card, ballots)
    similar = _similar_summary(card, profile, tastes_by_user)
    my_choice = None
    taste_match_count = 0
    # 몇 개가 맞았는지만이 아니라 **무엇이 맞았는지**도 보낸다.
    # 화면이 "취향 2개 일치"라고만 쓰면 사용자는 근거를 확인할 길이 없다.
    taste_match_tags = []
    if profile is not None:
        my_choice = next((row.choice for row in ballots if row.user_id == profile.id), None)
        taste_names = taste_names_by_user.get(profile.id, set())
        taste_match_tags = sorted(taste_names.intersection(card.tags or []))
        taste_match_count = len(taste_match_tags)
    metadata = card.source_metadata or {}
    price = None
    if snapshot:
        raw_price = snapshot["sale_price"] if snapshot["sale_price"] is not None else snapshot["list_price"]
        price = int(raw_price) if raw_price is not None else None
    elif metadata.get("price") is not None:
        try:
            price = int(metadata["price"])
        except (TypeError, ValueError):
            price = None
    remaining = 0
    if card.status == VoteCard.Status.ACTIVE and card.closes_at:
        remaining = max(1, math.ceil((card.closes_at - timezone.now()).total_seconds() / 3600))
    comments = []
    for comment in card.comments.filter(is_deleted=False).select_related("user", "user__user").order_by("-created_at"):
        user_meta = comment.user.profile_metadata or {}
        comments.append(
            {
                "id": comment.id,
                "name": comment.user.nickname or comment.user.user.username,
                "rank": int(user_meta.get("avatar", 0)) % 5,
                "job": user_meta.get("job") or "Basic",
                "choice": comment.choice,
                "text": comment.content,
                "time": _comment_time(comment.created_at),
                "mine": bool(profile and comment.user_id == profile.id),
                "deletable": bool(profile and (comment.user_id == profile.id
                                               or profile.user.is_superuser or profile.user.is_staff)),
            }
        )
    brand = None
    category = None
    name = card.title
    if product is not None:
        name = product.canonical_name or name
        brand = product.brand.name if product.brand_id else None
        category = product.category.name if product.category_id else None
    if source is not None:
        name = source.source_name or name
        brand = brand or (source.source_brand.name if source.source_brand_id else None)
        category = category or (
            source.source_category.source_category_name if source.source_category_id else None
        )
    brand = brand or _clean_text(metadata.get("brand"), 120) or None
    category = category or _clean_text(metadata.get("category"), 120) or None
    return {
        "id": card.id,
        "seed_key": card.seed_key,
        "title": name,
        "description": card.description,
        "brand": brand,
        "category": category,
        "price": price,
        "image_url": vote_image_url(card.image_url) or (source.thumbnail_url if source else None),
        "product_source_id": source.id if source else None,
        "product_url": source.product_url if source else None,
        "gender_target": card.gender_target,
        "style_tags": card.tags or [],
        "status": card.status,
        "closed": card.status == VoteCard.Status.CLOSED,
        "hours_remaining": remaining,
        "closes_at": card.closes_at,
        "created_at": card.created_at,
        "source": metadata,
        "author": {
            "name": card.user.nickname or card.user.user.username,
            "story": card.description or "이 상품을 살지 말지 의견이 궁금해요.",
        },
        # ★ 2026-09-19 — 화면의 '구매자 만족도'는 투표율로 만든 계산값이었다.
        #   실제 구매자 신호인 판매처 평점·후기 수(상품 스냅샷)를 보낸다. 없으면 None.
        "buyer_rating": _buyer_rating(snapshot),
        "vote_summary": summary,
        "similar_user_summary": similar,
        "taste_match_count": taste_match_count,
        "taste_match_tags": taste_match_tags,
        "my_choice": my_choice,
        "mine": bool(profile and card.user_id == profile.id),
        "deletable": bool(
            profile
            and (
                (card.user_id == profile.id and str(card.seed_key or "").startswith("user:"))
                or profile.user.is_superuser or profile.user.is_staff
            )
        ),
        "comments": comments,
    }


@require_http_methods(["GET", "POST"])
def cards(request):
    _close_expired_cards()
    if request.method == "POST":
        return _create_card(request)
    profile = _profile(request)
    tab = (request.GET.get("tab") or "latest").strip().lower()
    queryset = (
        VoteCard.objects.filter(VISIBLE_CARD_FILTER)
        .select_related(
            "user",
            "user__user",
            "product",
            "product__brand",
            "product__category",
            "product_source",
            "product_source__source_brand",
            "product_source__source_category",
        )
        .prefetch_related("ballots", "ballots__user", "comments", "comments__user", "comments__user__user")
    )
    if tab == "result":
        queryset = queryset.filter(status=VoteCard.Status.CLOSED)
    else:
        queryset = queryset.filter(status=VoteCard.Status.ACTIVE)
    rows = list(queryset)

    if tab == "taste" and profile is not None:
        tastes = set(
            UserTaste.objects.filter(user=profile, taste_type=UserTaste.TasteType.TERM)
            .values_list("term__canonical_name", flat=True)
        )
        matched = [row for row in rows if tastes.intersection(row.tags or [])]
        rows = matched
        rows.sort(key=lambda row: (-len(tastes.intersection(row.tags or [])), -row.created_at.timestamp()))
    elif tab == "popular" or tab == "result":
        rows.sort(key=lambda row: (-len(row.ballots.all()), -row.created_at.timestamp()))
    elif tab == "closing":
        # 마감임박은 진행 중인 카드를 숨기지 않고 실제 마감 시각이 가까운 순서로 보여 준다.
        # 마감 시각이 없는 예외 데이터는 목록 맨 뒤로 보낸다.
        rows.sort(
            key=lambda row: (
                row.closes_at is None,
                row.closes_at or timezone.now() + timedelta(days=36500),
                -row.created_at.timestamp(),
            )
        )
    else:
        rows.sort(key=lambda row: row.created_at, reverse=True)

    tastes_by_user, taste_names_by_user = _taste_context(rows, profile)
    return _ok({
        "tab": tab,
        "count": len(rows),
        "activity": _activity(),
        "items": [_card_payload(row, profile, tastes_by_user, taste_names_by_user) for row in rows],
    })


@require_http_methods(["GET", "DELETE"])
def card(request, card_id):
    _close_expired_cards()
    profile = _profile(request)
    row = (
        VoteCard.objects.filter(VISIBLE_CARD_FILTER, id=card_id)
        .select_related("user", "user__user", "product", "product__brand", "product__category", "product_source")
        .prefetch_related("ballots", "ballots__user", "comments", "comments__user", "comments__user__user")
        .first()
    )
    if row is None:
        return _error("카드를 찾지 못했습니다.", 404)
    if request.method == "DELETE":
        if profile is None:
            return _error("로그인이 필요합니다.", 401)
        # 운영 계정(슈퍼유저·스태프)은 어떤 카드든 지울 수 있다 — 신고 처리·시드 정리용.
        is_admin = request.user.is_superuser or request.user.is_staff
        if not is_admin and (row.user_id != profile.id or not str(row.seed_key or "").startswith("user:")):
            return _error("본인이 작성한 카드만 삭제할 수 있습니다.", 403)
        try:
            delete_vote_image(row.image_url)
        except VoteImageError as exc:
            return _error(str(exc), 502)
        deleted_id = row.id
        row.delete()
        return _ok({"id": deleted_id, "deleted": True})
    tastes_by_user, taste_names_by_user = _taste_context([row], profile)
    return _ok(_card_payload(row, profile, tastes_by_user, taste_names_by_user))


def _create_card(request):
    if not request.user.is_authenticated:
        return _error("로그인이 필요합니다.", 401)
    data = _request_data(request)
    if data is None:
        return _error("요청 형식이 올바른 JSON이 아닙니다.")

    title = _clean_text(data.get("title"), 300)
    brand = _clean_text(data.get("brand"), 120)
    description = _clean_text(data.get("description"), 1000)
    if not title:
        return _error("상품명을 입력해 주세요.")
    if not brand:
        return _error("브랜드를 입력해 주세요.")
    try:
        price = int(data.get("price"))
    except (TypeError, ValueError):
        return _error("가격은 숫자로 입력해 주세요.")
    if price < 0 or price > 1_000_000_000:
        return _error("가격은 0원 이상 10억원 이하로 입력해 주세요.")

    raw_tags = data.get("tags") or []
    if not isinstance(raw_tags, list) or len(raw_tags) > 3:
        return _error("스타일 태그는 최대 3개까지 등록할 수 있습니다.")
    tags = []
    for value in raw_tags:
        tag = _clean_text(value, 80)
        if tag and tag not in tags:
            tags.append(tag)
    valid_tags = set(
        DictionaryTerm.objects.filter(
            status=DictionaryTerm.Status.ACTIVE,
            term_type=DictionaryTerm.TermType.STYLE,
            canonical_name__in=tags,
        ).values_list("canonical_name", flat=True)
    )
    if set(tags) != valid_tags:
        return _error("지원하지 않는 스타일 태그가 포함되어 있습니다.")

    uploaded_image = None
    image_url = None
    image_data_url = str(data.get("image_data_url") or "").strip()
    if image_data_url:
        try:
            uploaded_image = upload_vote_image(image_data_url)
            image_url = uploaded_image.uri
        except VoteImageError as exc:
            return _error(str(exc), 502)
    else:
        external_image_url = _clean_text(data.get("image_url"), 2000)
        if external_image_url:
            parsed_image_url = urlsplit(external_image_url)
            if (
                parsed_image_url.scheme != "https"
                or not parsed_image_url.netloc
                or any(char in external_image_url for char in ('"', "'", "\\"))
            ):
                return _error("상품 이미지 주소는 안전한 HTTPS 주소만 사용할 수 있습니다.")
            image_url = external_image_url

    profile, _ = AppUser.objects.get_or_create(
        user=request.user,
        defaults={"nickname": request.user.first_name or request.user.username[:12]},
    )
    metadata = {"source": "USER", "brand": brand, "price": price}
    if uploaded_image is not None:
        metadata["image_s3_key"] = uploaded_image.key
    try:
        card = VoteCard.objects.create(
            user=profile,
            seed_key=f"user:{secrets.token_hex(16)}",
            gender_target=profile.gender or None,
            title=title,
            description=description or None,
            image_url=image_url,
            tags=tags,
            status=VoteCard.Status.ACTIVE,
            closes_at=timezone.now() + timedelta(hours=48),
            source_metadata=metadata,
        )
    except Exception:
        if uploaded_image is not None:
            try:
                delete_vote_image(uploaded_image.uri)
            except VoteImageError:
                pass
        raise
    tastes_by_user, taste_names_by_user = _taste_context([card], profile)
    return _ok(_card_payload(card, profile, tastes_by_user, taste_names_by_user), 201)
