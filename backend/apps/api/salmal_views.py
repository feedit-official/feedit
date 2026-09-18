"""실제 DB 기반 살!말? 카드 목록·댓글 API."""

from __future__ import annotations

from datetime import timedelta

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.core.models import AppUser, ProductSourceSnapshot, UserTaste, VoteBallot, VoteCard


def _ok(data):
    return JsonResponse({"status": "ok", "data": data})


def _error(reason, status=400):
    return JsonResponse({"status": "error", "reason": reason, "data": None}, status=status)


def _profile(request):
    if not request.user.is_authenticated:
        return None
    return AppUser.objects.filter(user=request.user).first()


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


def _card_payload(card, profile, tastes_by_user, taste_names_by_user):
    source = card.product_source
    product = card.product
    snapshot = None
    if source is not None:
        snapshot = (
            ProductSourceSnapshot.objects.filter(product_source=source)
            .order_by("-observed_at")
            .values("sale_price", "list_price", "rating")
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
    remaining = 0
    if card.status == VoteCard.Status.ACTIVE and card.closes_at:
        remaining = max(1, int((card.closes_at - timezone.now()).total_seconds() // 3600))
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
    return {
        "id": card.id,
        "seed_key": card.seed_key,
        "title": name,
        "description": card.description,
        "brand": brand,
        "category": category,
        "price": price,
        "image_url": card.image_url or (source.thumbnail_url if source else None),
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
        "vote_summary": summary,
        "similar_user_summary": similar,
        "taste_match_count": taste_match_count,
        "taste_match_tags": taste_match_tags,
        "my_choice": my_choice,
        "comments": comments,
    }


@require_GET
def cards(request):
    profile = _profile(request)
    tab = (request.GET.get("tab") or "latest").strip().lower()
    queryset = (
        VoteCard.objects.filter(seed_key__startswith="youtube:")
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
        "items": [_card_payload(row, profile, tastes_by_user, taste_names_by_user) for row in rows],
    })


@require_GET
def card(request, card_id):
    profile = _profile(request)
    row = (
        VoteCard.objects.filter(id=card_id, seed_key__startswith="youtube:")
        .select_related("user", "user__user", "product", "product__brand", "product__category", "product_source")
        .prefetch_related("ballots", "ballots__user", "comments", "comments__user", "comments__user__user")
        .first()
    )
    if row is None:
        return _error("카드를 찾지 못했습니다.", 404)
    tastes_by_user, taste_names_by_user = _taste_context([row], profile)
    return _ok(_card_payload(row, profile, tastes_by_user, taste_names_by_user))
