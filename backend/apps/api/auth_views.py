"""FEEDiT 사용자 인증·프로필 API.

Django 세션 쿠키를 사용한다. 비밀번호와 로그인 상태를 프론트 메모리나
localStorage에 저장하지 않고, 실제 사용자 데이터는 auth_user와 app 스키마에 둔다.
"""

from __future__ import annotations

import json
import math
import re
import time

from django.contrib.auth import (
    authenticate,
    login as django_login,
    logout as django_logout,
    update_session_auth_hash,
)
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import OuterRef, Q, Subquery
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from apps.core.models import (
    AppUser,
    ContentItem,
    ContentSnapshot,
    DictionaryTerm,
    ProductTerm,
    UserSavedItem,
    UserTaste,
    VoteBallot,
)

from . import google_auth


USERNAME_RE = re.compile(r"^[A-Za-z0-9]{4,16}$")
STYLE_LIMIT = 3
YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
# Google 로 인증했지만 아직 가입 폼(닉네임·체형)을 끝내지 않은 사람의 신원.
# 세션(서버 쪽)에만 두고, 이 시간 안에 가입을 마치지 않으면 다시 인증해야 한다.
GOOGLE_PENDING_KEY = "google_pending"
GOOGLE_PENDING_TTL = 10 * 60


def _json(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _error(reason, status=400, **extra):
    return JsonResponse({"status": "error", "reason": reason, "data": None, **extra}, status=status)


def _body_profile(height, weight):
    try:
        h = float(height) if height not in (None, "") else None
        w = float(weight) if weight not in (None, "") else None
    except (TypeError, ValueError):
        raise ValueError("키와 몸무게는 숫자로 입력해 주세요.")
    if h is not None and not 120 <= h <= 220:
        raise ValueError("키는 120~220cm 사이로 입력해 주세요.")
    if w is not None and not 30 <= w <= 200:
        raise ValueError("몸무게는 30~200kg 사이로 입력해 주세요.")
    if h is None or w is None:
        return h, w, None
    bmi = w / ((h / 100) ** 2)
    segment = "슬림" if bmi < 18.5 else "표준" if bmi < 23 else "스탠다드 플러스" if bmi < 25 else "볼륨"
    return h, w, segment


def _profile(user, create=False):
    if create:
        profile, _ = AppUser.objects.get_or_create(
            user=user,
            defaults={"nickname": user.first_name or user.username[:12]},
        )
        return profile
    try:
        return user.feedit_profile
    except AppUser.DoesNotExist:
        return None


def _user_payload(user, profile):
    if profile is None:
        return None
    meta = profile.profile_metadata or {}
    styles = list(
        UserTaste.objects.filter(
            user=profile,
            taste_type=UserTaste.TasteType.TERM,
            term__term_type="STYLE",
        ).values_list("term__canonical_name", flat=True)
    )
    nickname = profile.nickname or user.first_name or user.username
    return {
        "id": profile.id,
        "username": user.username,
        "email": user.email or user.username,
        "nickname": nickname,
        "initial": nickname[:1],
        "birth_date": meta.get("birth_date") or "",
        "birth_year": profile.birth_year,
        "height": meta.get("height"),
        "weight": meta.get("weight"),
        "body_type": profile.body_type,
        "bio": meta.get("bio") or "",
        "avatar": int(meta.get("avatar") or 0),
        "job": meta.get("job") or "",
        "major": meta.get("major") or "",
        "role": "admin" if user.is_staff or user.is_superuser else "user",
        "styles": styles,
        "saved_count": UserSavedItem.objects.filter(user=profile).count(),
        "vote_count": VoteBallot.objects.filter(user=profile).count(),
    }


def _auth_payload(request, user, profile):
    return {
        "status": "ok",
        "data": {
            "authenticated": True,
            "csrf_token": get_token(request),
            "google_client_id": google_auth.client_id(),
            "user": _user_payload(user, profile),
        },
    }


def _save_styles(profile, names):
    if names is None:
        return
    clean = list(dict.fromkeys(str(name).strip() for name in names if str(name).strip()))
    if len(clean) > STYLE_LIMIT:
        raise ValueError(f"즐겨입는 스타일은 {STYLE_LIMIT}개까지 저장할 수 있습니다.")
    terms = list(
        DictionaryTerm.objects.filter(
            status=DictionaryTerm.Status.ACTIVE,
            term_type="STYLE",
            canonical_name__in=clean,
        )
    )
    found = {term.canonical_name for term in terms}
    missing = [name for name in clean if name not in found]
    if missing:
        raise ValueError("사전에 없는 스타일입니다: " + ", ".join(missing))
    UserTaste.objects.filter(user=profile, taste_type=UserTaste.TasteType.TERM, term__term_type="STYLE").delete()
    UserTaste.objects.bulk_create([
        UserTaste(user=profile, taste_type=UserTaste.TasteType.TERM, term=term, source="USER")
        for term in terms
    ])


def _interest_key(value):
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _weekly_interests(profile):
    """명시한 취향과 찜 상품의 사전 태그를 추천 신호로 합친다."""
    interests = {}

    def add(label, facet, weight, source):
        key = _interest_key(label)
        if not key:
            return
        old = interests.get((facet, key))
        row = {"label": str(label).strip(), "facet": facet, "weight": weight, "source": source}
        if old is None or weight > old["weight"]:
            interests[(facet, key)] = row

    tastes = UserTaste.objects.filter(user=profile).select_related("term", "brand", "category")
    for taste in tastes:
        weight = max(1.0, float(taste.weight or 1))
        if taste.term_id:
            add(taste.term.canonical_name, str(taste.term.term_type or "").lower(), 7.0 * weight, "선택한 취향")
        elif taste.brand_id:
            add(taste.brand.name or taste.brand.english_name, "brand", 6.0 * weight, "선택한 브랜드")
        elif taste.category_id:
            add(taste.category.name, "item", 4.0 * weight, "선택한 카테고리")

    saved = list(
        UserSavedItem.objects.filter(user=profile, product__isnull=False)
        .select_related("product__brand", "product__category", "product__style__term")
        .order_by("-created_at")[:100]
    )
    product_ids = [row.product_id for row in saved]
    for row in saved:
        product = row.product
        if product.style_id:
            add(product.style.term.canonical_name, "style", 7.0, "찜한 상품")
        if product.brand_id:
            add(product.brand.name or product.brand.english_name, "brand", 6.0, "찜한 상품")
        if product.category_id:
            add(product.category.name, "item", 4.0, "찜한 상품")
    if product_ids:
        tags = ProductTerm.objects.filter(
            product_source__product_id__in=product_ids,
        ).select_related("term").distinct()
        for tag in tags:
            add(tag.term.canonical_name, str(tag.term.term_type or "").lower(), 5.0, "찜 상품 태그")
    return sorted(interests.values(), key=lambda row: row["weight"], reverse=True)[:80]


def _tag_index(tags):
    out = {}
    if not isinstance(tags, dict):
        return out
    for facet, values in tags.items():
        if facet.startswith("_") or not isinstance(values, list):
            continue
        out[str(facet).lower()] = {_interest_key(value) for value in values if _interest_key(value)}
    return out


def _metric_int(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


@require_GET
@ensure_csrf_cookie
def me(request):
    token = get_token(request)
    if not request.user.is_authenticated:
        return JsonResponse({
            "status": "ok",
            "data": {
                "authenticated": False,
                "csrf_token": token,
                # 공개 값이다. 비어 있으면 프론트가 Google 버튼을 '설정 필요'로 안내한다.
                "google_client_id": google_auth.client_id(),
                "google_pending": _google_pending_public(request),
                "user": None,
            },
        })
    profile = _profile(request.user, create=True)
    return JsonResponse(_auth_payload(request, request.user, profile))


@require_POST
def signup(request):
    data = _json(request)
    if data is None:
        return _error("요청 형식이 올바른 JSON이 아닙니다.")
    username = str(data.get("username") or "").strip()
    nickname = str(data.get("nickname") or "").strip()
    password = str(data.get("password") or "")
    if not USERNAME_RE.fullmatch(username):
        return _error("아이디는 영문·숫자 4~16자로 입력해 주세요.")
    if not 2 <= len(nickname) <= 12:
        return _error("닉네임은 2~12자로 입력해 주세요.")
    if User.objects.filter(username__iexact=username).exists():
        return _error("이미 사용 중인 아이디입니다.", status=409)
    candidate = User(username=username, first_name=nickname)
    try:
        validate_password(password, user=candidate)
        height, weight, body_type = _body_profile(data.get("height"), data.get("weight"))
    except (ValidationError, ValueError) as exc:
        messages = exc.messages if isinstance(exc, ValidationError) else [str(exc)]
        return _error(" ".join(messages))

    try:
        user, profile = _create_account(
            request,
            username=username,
            nickname=nickname,
            password=password,
            email=str(data.get("email") or "").strip(),
            data=data,
            body=(height, weight, body_type),
        )
    except ValueError as exc:
        return _error(str(exc))
    return JsonResponse(_auth_payload(request, user, profile), status=201)


def _create_account(request, *, username, nickname, password, email, data, body, extra_meta=None):
    """auth_user + app_user 를 한 트랜잭션으로 만들고 바로 로그인시킨다.

    password 가 None 이면(Google 가입) 사용할 수 없는 비밀번호로 둔다.
    비밀번호는 Django 기본 해시(PBKDF2-SHA256)로만 저장된다.
    """
    height, weight, body_type = body
    birth_date = str(data.get("birth_date") or "").strip()
    birth_year = int(birth_date[:4]) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", birth_date) else None
    with transaction.atomic():
        user = User.objects.create_user(
            username=username,
            password=password,
            first_name=nickname,
            email=email,
        )
        meta = {
            "birth_date": birth_date,
            "height": height,
            "weight": weight,
            # 직업 배지는 증빙 검토 뒤 관리자 경로에서만 기록한다.
            "job": "",
            "major": "",
            "avatar": 0,
            "bio": "",
        }
        meta.update(extra_meta or {})
        profile = AppUser.objects.create(
            user=user,
            nickname=nickname,
            birth_year=birth_year,
            body_type=body_type,
            profile_metadata=meta,
        )
        _save_styles(profile, data.get("styles"))
    # 로그인은 트랜잭션이 확정된 뒤에 — 세션 행이 롤백된 사용자를 가리키지 않게 한다.
    django_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return user, profile


@require_POST
def login(request):
    data = _json(request)
    if data is None:
        return _error("요청 형식이 올바른 JSON이 아닙니다.")
    identifier = str(data.get("username") or "").strip()
    password = str(data.get("password") or "")
    # 아이디 일치를 먼저 본다. Google 계정과 이메일이 같은 아이디 계정이 있어도
    # 엉뚱한 쪽(비밀번호 없는 Google 계정)을 집지 않게 한다.
    found = (
        User.objects.filter(username__iexact=identifier).first()
        or User.objects.filter(email__iexact=identifier).order_by("id").first()
    )
    user = authenticate(request, username=found.username if found else identifier, password=password)
    if user is None or not user.is_active:
        return _error("아이디 또는 비밀번호가 올바르지 않습니다.", status=401)
    profile = _profile(user, create=True)
    django_login(request, user)
    return JsonResponse(_auth_payload(request, user, profile))


# ── Google 로그인 ─────────────────────────────────────────────

def _google_pending(request):
    pending = request.session.get(GOOGLE_PENDING_KEY)
    if not isinstance(pending, dict):
        return None
    if float(pending.get("expires_at") or 0) < time.time():
        request.session.pop(GOOGLE_PENDING_KEY, None)
        return None
    return pending


def _google_pending_public(request):
    """가입 폼을 채우는 데 필요한 값만 내려 준다(sub 는 내려 주지 않는다)."""
    pending = _google_pending(request)
    if not pending:
        return None
    return {"email": pending["email"], "name": pending.get("name") or ""}


def _google_username(sub):
    # auth_user.username 은 150자 제한이고 sub 는 최대 255자라 앞 140자만 쓴다.
    return f"google_{sub}"[:150]


def _google_profile(sub):
    return (
        AppUser.objects.select_related("user")
        .filter(profile_metadata__google_sub=sub)
        .first()
    )


@require_POST
def google_login(request):
    """Google 팝업에서 받은 인가 코드로 로그인한다.

    - 이미 연결된 계정 → 바로 로그인 (authenticated: true)
    - 처음 온 Google 계정 → 세션에 신원만 보관하고 가입 폼으로 보낸다
      (authenticated: false, needs_signup: true)
    """
    if not google_auth.is_configured():
        return _error(
            "Google 로그인이 아직 설정되지 않았습니다. 서버 .env 의 GOOGLE_CLIENT_ID · GOOGLE_CLIENT_SECRET 을 확인해 주세요.",
            status=503,
        )
    data = _json(request)
    if data is None:
        return _error("요청 형식이 올바른 JSON이 아닙니다.")
    code = str(data.get("code") or "").strip()
    if not code or len(code) > 2048:
        return _error("Google 인가 코드가 없습니다.")
    try:
        identity = google_auth.exchange_code(code)
    except google_auth.GoogleAuthError as exc:
        return _error(exc.reason, status=exc.status)

    profile_obj = _google_profile(identity["sub"])
    if profile_obj is not None:
        user = profile_obj.user
        if not user.is_active:
            return _error("사용이 중지된 계정입니다.", status=403)
        request.session.pop(GOOGLE_PENDING_KEY, None)
        django_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return JsonResponse(_auth_payload(request, user, profile_obj))

    request.session[GOOGLE_PENDING_KEY] = {**identity, "expires_at": time.time() + GOOGLE_PENDING_TTL}
    return JsonResponse({
        "status": "ok",
        "data": {
            "authenticated": False,
            "needs_signup": True,
            "csrf_token": get_token(request),
            "google": {"email": identity["email"], "name": identity["name"]},
            "user": None,
        },
    })


@require_POST
def google_signup(request):
    """google_login 에서 보관한 신원 + 가입 폼 값으로 계정을 만든다."""
    pending = _google_pending(request)
    if pending is None:
        return _error("Google 인증 시간이 지났습니다. 'Google로 계속하기'를 다시 눌러 주세요.", status=401)
    data = _json(request)
    if data is None:
        return _error("요청 형식이 올바른 JSON이 아닙니다.")
    nickname = str(data.get("nickname") or "").strip()
    if not 2 <= len(nickname) <= 12:
        return _error("닉네임은 2~12자로 입력해 주세요.")
    try:
        body = _body_profile(data.get("height"), data.get("weight"))
    except ValueError as exc:
        return _error(str(exc))

    # 두 번 눌렀거나 다른 탭에서 먼저 가입했으면 새로 만들지 않고 로그인만 한다.
    existing = _google_profile(pending["sub"])
    if existing is not None:
        request.session.pop(GOOGLE_PENDING_KEY, None)
        django_login(request, existing.user, backend="django.contrib.auth.backends.ModelBackend")
        return JsonResponse(_auth_payload(request, existing.user, existing))

    username = _google_username(pending["sub"])
    if User.objects.filter(username=username).exists():
        return _error("이미 가입된 Google 계정입니다. 로그인해 주세요.", status=409)
    try:
        user, profile_obj = _create_account(
            request,
            username=username,
            nickname=nickname,
            password=None,  # Google 계정은 비밀번호로 로그인하지 않는다
            email=pending["email"],
            data=data,
            body=body,
            extra_meta={
                "auth_provider": "google",
                "google_sub": pending["sub"],
                "google_picture": pending.get("picture") or "",
            },
        )
    except ValueError as exc:
        return _error(str(exc))
    # django_login 이 세션 키를 새로 돌리므로, 그 뒤에 남은 보관 값을 지운다.
    request.session.pop(GOOGLE_PENDING_KEY, None)
    return JsonResponse(_auth_payload(request, user, profile_obj), status=201)


@require_POST
def logout(request):
    django_logout(request)
    return JsonResponse({
        "status": "ok",
        "data": {"authenticated": False, "csrf_token": get_token(request), "user": None},
    })


@require_POST
def profile(request):
    if not request.user.is_authenticated:
        return _error("로그인이 필요합니다.", status=401)
    data = _json(request)
    if data is None:
        return _error("요청 형식이 올바른 JSON이 아닙니다.")
    profile_obj = _profile(request.user, create=True)
    nickname = str(data.get("nickname", profile_obj.nickname or "")).strip()
    if not 2 <= len(nickname) <= 12:
        return _error("닉네임은 2~12자로 입력해 주세요.")
    try:
        height, weight, body_type = _body_profile(
            data.get("height", (profile_obj.profile_metadata or {}).get("height")),
            data.get("weight", (profile_obj.profile_metadata or {}).get("weight")),
        )
        new_password = str(data.get("password") or "")
        if new_password:
            validate_password(new_password, user=request.user)
        with transaction.atomic():
            meta = dict(profile_obj.profile_metadata or {})
            # job·major는 본인이 승인 상태를 만들 수 없도록 여기서 받지 않는다.
            for key in ("birth_date", "bio", "avatar"):
                if key in data:
                    meta[key] = data[key]
            meta.update({"height": height, "weight": weight})
            profile_obj.nickname = nickname
            profile_obj.birth_year = (
                int(str(meta.get("birth_date"))[:4])
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(meta.get("birth_date") or "")) else None
            )
            profile_obj.body_type = body_type
            profile_obj.profile_metadata = meta
            profile_obj.save()
            request.user.first_name = nickname
            if new_password:
                request.user.set_password(new_password)
            request.user.save(update_fields=["first_name", "password"] if new_password else ["first_name"])
            _save_styles(profile_obj, data.get("styles"))
            if new_password:
                update_session_auth_hash(request, request.user)
    except (ValidationError, ValueError) as exc:
        messages = exc.messages if isinstance(exc, ValidationError) else [str(exc)]
        return _error(" ".join(messages))
    return JsonResponse(_auth_payload(request, request.user, profile_obj))


@require_GET
def weekly_videos(request):
    """사용자의 사전 취향/찜 태그와 YouTube 분석 JSON을 직접 대조한다."""
    if not request.user.is_authenticated:
        return _error("로그인이 필요합니다.", status=401)
    profile_obj = _profile(request.user, create=True)
    interests = _weekly_interests(profile_obj)
    if not interests:
        return _error("선택한 스타일이나 찜한 상품이 없어 추천 기준을 만들 수 없습니다.", status=404)

    match_query = Q()
    for interest in interests:
        match_query |= Q(**{f"analysis_tags__contains": {interest["facet"]: [interest["label"]]}})
    latest = ContentSnapshot.objects.filter(content_item_id=OuterRef("pk")).order_by("-observed_at")
    contents = (
        ContentItem.objects.filter(source__code__iexact="youtube")
        .filter(match_query)
        .exclude(external_content_id="")
        .select_related("profile")
        .annotate(
            latest_view_count=Subquery(latest.values("view_count")[:1]),
            latest_like_count=Subquery(latest.values("like_count")[:1]),
            latest_comment_count=Subquery(latest.values("comment_count")[:1]),
            latest_observed_at=Subquery(latest.values("observed_at")[:1]),
        )
    )
    ranked = []
    for content in contents:
        if not YOUTUBE_ID_RE.fullmatch(content.external_content_id or ""):
            continue
        indexed = _tag_index(content.analysis_tags)
        matched = []
        relevance = 0.0
        for interest in interests:
            if interest["facet"] in indexed and _interest_key(interest["label"]) in indexed[interest["facet"]]:
                matched.append(interest)
                relevance += interest["weight"]
        if not matched:
            continue

        metadata = content.platform_metadata if isinstance(content.platform_metadata, dict) else {}
        fallback = metadata.get("latest_statistics") if isinstance(metadata.get("latest_statistics"), dict) else {}
        views = _metric_int(content.latest_view_count if content.latest_view_count is not None else fallback.get("view_count"))
        likes = _metric_int(content.latest_like_count if content.latest_like_count is not None else fallback.get("like_count"))
        comments = _metric_int(content.latest_comment_count if content.latest_comment_count is not None else fallback.get("comment_count"))
        reactions = likes + comments
        reaction_rate = reactions / max(views, 1)
        popularity = math.log10(views + 1) + 0.55 * math.log10(reactions + 1)
        score = relevance * 100 + popularity * 10 + min(reaction_rate, 0.2) * 100
        unique_matches = list(dict.fromkeys(row["label"] for row in matched))
        ranked.append((score, views, reactions, {
            "id": content.id,
            "youtube_id": content.external_content_id,
            "title": content.title or "제목 없는 영상",
            "channel": content.profile.name if content.profile_id else metadata.get("channel_title") or "",
            "url": content.content_url,
            "embed_url": f"https://www.youtube.com/embed/{content.external_content_id}",
            "thumbnail_url": content.thumbnail_url,
            "published_at": content.published_at.isoformat() if content.published_at else None,
            "matched_tags": unique_matches[:5],
            "reason": " · ".join(unique_matches[:3]),
            "metrics": {
                "views": views,
                "likes": likes,
                "comments": comments,
                "reaction_rate": round(reaction_rate * 100, 2),
                "observed_at": content.latest_observed_at.isoformat() if content.latest_observed_at else fallback.get("observed_at"),
            },
        }))

    ranked.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    items = [row[3] for row in ranked[:6]]
    if not items:
        return _error("선택한 취향과 일치하는 유튜브 분석 태그가 아직 없습니다.", status=404)
    return JsonResponse({
        "status": "ok",
        "data": {
            "items": items,
            "based_on": [
                {"label": row["label"], "facet": row["facet"], "source": row["source"]}
                for row in interests[:20]
            ],
            "ranking_rule": "취향·찜 태그 일치도를 우선하고, 동률에서는 조회수와 좋아요·댓글 반응률을 반영합니다.",
        },
    })
