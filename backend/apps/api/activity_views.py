"""사용자 활동 기록 API — 검색 · 살!말? 투표 · 찜 · 챗봇 사용 + 금주의 리포트.

모두 로그인 세션(Django 세션 쿠키)이 있어야 한다. 브라우저는 /api/auth/<action> 으로
부르고, 버셀 함수(frontend/api/auth/[action].js)가 쿠키·CSRF 를 그대로 중계한다.

★ 왜 살!말? 투표를 vote_ballot 이 아니라 user_event 에 적나
  vote_ballot 은 app.vote_card 의 id(FK)가 반드시 있어야 한다. 그런데 지금 살!말? 화면의
  카드는 아직 DB 카드가 아니라 프론트 목업(vote_app.js 의 VOTES)이다. 그래서
  카드 식별값(card_key)과 선택을 user_event(VOTE).metadata 에 남긴다.
  card_key 가 실제 vote_card id(숫자)이면 vote_ballot 에도 같이 반영한다.

★ 찜도 같은 이유
  user_saved_item 은 product FK 가 필요하다. 실데이터 상품 카드(id 'db-<product_source_id>')만
  user_saved_item 에 넣고, 모든 찜/해제는 user_event(SAVE) 에도 남긴다.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.core.models import (
    AppUser,
    ChatSession,
    DictionaryTerm,
    ProductSource,
    UserEvent,
    UserSavedItem,
    VoteBallot,
    VoteCard,
)

from .activity import build_weekly_report, latest_state, week_bounds

TEXT_MAX = 120
DB_ITEM_RE = re.compile(r"^db-(\d+)$")


# ── 공용 도우미 ─────────────────────────────────────────────

def _error(reason, status=400):
    return JsonResponse({"status": "error", "reason": reason, "data": None}, status=status)


def _body(request):
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _text(value, limit=TEXT_MAX):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _login_profile(request):
    """로그인하지 않았으면 None — 비로그인 사용자의 활동은 기록하지 않는다."""
    if not request.user.is_authenticated:
        return None
    profile, _ = AppUser.objects.get_or_create(
        user=request.user, defaults={"nickname": request.user.first_name or request.user.username[:12]},
    )
    return profile


def _style_term(name):
    """스타일 이름이 사전(STYLE)에 있으면 그 용어를 돌려준다."""
    name = _text(name)
    if not name:
        return None
    return DictionaryTerm.objects.filter(
        status=DictionaryTerm.Status.ACTIVE, term_type="STYLE", canonical_name=name,
    ).first()


def active_vote_count(profile):
    """지금 투표가 살아 있는 카드 수 (같은 카드를 다시 눌러 취소한 것은 뺀다)."""
    rows = _event_rows(profile, types=("VOTE",))
    return len(latest_state(rows, "VOTE", "card_key", lambda m: m.get("choice") in ("BUY", "PASS")))


def active_saved_count(profile):
    """지금 찜이 살아 있는 항목 수 (목업 상품 포함)."""
    rows = _event_rows(profile, types=("SAVE",))
    n = len(latest_state(rows, "SAVE", "item_id", lambda m: bool(m.get("liked"))))
    # 기록 API 이전에 user_saved_item 에 직접 들어간 행이 있으면 그쪽 수를 따른다.
    return max(n, UserSavedItem.objects.filter(user=profile).count())


def _event_rows(profile, types=None, since=None):
    qs = UserEvent.objects.filter(user=profile).select_related("term")
    if types:
        qs = qs.filter(event_type__in=types)
    if since is not None:
        qs = qs.filter(created_at__gte=since)
    rows = []
    for e in qs.order_by("created_at"):
        meta = e.metadata if isinstance(e.metadata, dict) else {}
        style = _text(meta.get("style")) or None
        if not style and e.term_id and e.term.term_type == "STYLE":
            style = e.term.canonical_name
        rows.append({"type": e.event_type, "at": e.created_at, "meta": meta, "style": style})
    return rows


# ── ① 검색 · 챗봇 사용 기록 ─────────────────────────────────

@require_POST
def event(request):
    """POST /api/auth/event

    {"type": "SEARCH", "q": "발레코어", "facet": "스타일", "style": "발레코어"}
    {"type": "CHAT", "conversation_id": "c_123"}
    """
    profile = _login_profile(request)
    if profile is None:
        return _error("로그인이 필요합니다.", status=401)
    data = _body(request)
    if data is None:
        return _error("요청 형식이 올바른 JSON이 아닙니다.")
    kind = _text(data.get("type")).upper()

    if kind == "SEARCH":
        q = _text(data.get("q"))
        if not q:
            return _error("검색어(q)가 비어 있습니다.")
        facet = _text(data.get("facet"), 20)
        term = DictionaryTerm.objects.filter(status=DictionaryTerm.Status.ACTIVE, canonical_name=q).first()
        style_term = _style_term(data.get("style")) or (term if term and term.term_type == "STYLE" else None)
        UserEvent.objects.create(
            user=profile, event_type=UserEvent.EventType.SEARCH, term=term,
            metadata={"q": q, "facet": facet, "style": style_term.canonical_name if style_term else ""},
        )
        return JsonResponse({"status": "ok", "data": {"recorded": "SEARCH"}})

    if kind == "CHAT":
        conv = _text(data.get("conversation_id"), 80)
        if not conv:
            return _error("conversation_id 가 비어 있습니다.")
        with transaction.atomic():
            session = (ChatSession.objects.select_for_update()
                       .filter(user=profile, context__conversation_id=conv).first())
            if session is None:
                session = ChatSession.objects.create(
                    user=profile, title=_text(data.get("title"), 300) or None,
                    context={"conversation_id": conv},
                )
            else:
                session.save(update_fields=["updated_at"])   # 최근 대화 시각만 앞으로 민다
            UserEvent.objects.create(
                user=profile, event_type=UserEvent.EventType.CHAT,
                metadata={"conversation_id": conv, "chat_session_id": session.id},
            )
        return JsonResponse({"status": "ok", "data": {"recorded": "CHAT", "chat_session_id": session.id}})

    return _error("type 은 SEARCH 또는 CHAT 이어야 합니다.")


# ── ② 살!말? 투표 ───────────────────────────────────────────

@require_POST
def vote(request):
    """POST /api/auth/vote

    {"card_key": "mock:3", "title": "스퀘어 토 로퍼", "brand": "...", "style": "", "choice": "BUY"|"PASS"|null}
    choice 가 null 이면 투표 취소.
    """
    profile = _login_profile(request)
    if profile is None:
        return _error("로그인이 필요합니다.", status=401)
    data = _body(request)
    if data is None:
        return _error("요청 형식이 올바른 JSON이 아닙니다.")
    card_key = _text(data.get("card_key"), 80)
    if not card_key:
        return _error("card_key 가 비어 있습니다.")
    choice = data.get("choice")
    choice = _text(choice).upper() if choice else None
    if choice not in (None, "BUY", "PASS"):
        return _error("choice 는 BUY · PASS · null 중 하나여야 합니다.")
    style_term = _style_term(data.get("style"))

    with transaction.atomic():
        UserEvent.objects.create(
            user=profile, event_type=UserEvent.EventType.VOTE, term=style_term,
            metadata={"card_key": card_key, "title": _text(data.get("title")),
                      "brand": _text(data.get("brand")), "choice": choice,
                      "style": style_term.canonical_name if style_term else ""},
        )
        # 실제 DB 카드면 vote_ballot 에도 반영한다.
        if card_key.isdigit() and VoteCard.objects.filter(id=int(card_key)).exists():
            if choice is None:
                VoteBallot.objects.filter(card_id=int(card_key), user=profile).delete()
            else:
                VoteBallot.objects.update_or_create(
                    card_id=int(card_key), user=profile, defaults={"choice": choice})
    return JsonResponse({"status": "ok", "data": {"card_key": card_key, "choice": choice,
                                                   "vote_count": active_vote_count(profile)}})


# ── ③ 찜 ────────────────────────────────────────────────────

@require_POST
def saved(request):
    """POST /api/auth/saved

    {"item_id": "db-17", "liked": true, "name": "...", "brand": "...", "style": "고프코어"}
    """
    profile = _login_profile(request)
    if profile is None:
        return _error("로그인이 필요합니다.", status=401)
    data = _body(request)
    if data is None:
        return _error("요청 형식이 올바른 JSON이 아닙니다.")
    item_id = _text(data.get("item_id"), 80)
    if not item_id:
        return _error("item_id 가 비어 있습니다.")
    liked = bool(data.get("liked"))
    style_term = _style_term(data.get("style"))

    with transaction.atomic():
        UserEvent.objects.create(
            user=profile, event_type=UserEvent.EventType.SAVE, term=style_term,
            metadata={"item_id": item_id, "liked": liked, "name": _text(data.get("name")),
                      "brand": _text(data.get("brand")),
                      "style": style_term.canonical_name if style_term else ""},
        )
        m = DB_ITEM_RE.match(item_id)
        product_id = None
        if m:
            product_id = (ProductSource.objects.filter(id=int(m.group(1)))
                          .values_list("product_id", flat=True).first())
        if product_id:
            if liked:
                UserSavedItem.objects.get_or_create(user=profile, product_id=product_id)
            else:
                UserSavedItem.objects.filter(user=profile, product_id=product_id).delete()
    return JsonResponse({"status": "ok", "data": {"item_id": item_id, "liked": liked,
                                                   "saved_count": active_saved_count(profile)}})


# ── ④ 금주의 리포트 ─────────────────────────────────────────

@require_GET
def weekly_report(request):
    """GET /api/auth/weekly-report — 이번 주(월~일, KST) 활동 지표."""
    profile = _login_profile(request)
    if profile is None:
        return _error("로그인이 필요합니다.", status=401)
    now = timezone.now()
    _, _, prev = week_bounds(now)
    # 투표·찜의 '현재 상태'는 과거 기록 전체가 필요하고, 나머지는 지난주부터면 된다.
    events = _event_rows(profile, types=("VOTE", "SAVE"))
    events += _event_rows(profile, types=("SEARCH", "CHAT"), since=prev)
    sessions = list(ChatSession.objects.filter(user=profile, updated_at__gte=prev)
                    .values("started_at", "updated_at"))
    report = build_weekly_report(events, sessions, now)
    # 기록 API 이전에 들어간 user_saved_item 도 총 개수에는 반영한다.
    report["saved"]["total"] = max(report["saved"]["total"], UserSavedItem.objects.filter(user=profile).count())
    report["has_activity"] = any(e["at"] >= prev for e in events) or bool(sessions)
    return JsonResponse({"status": "ok", "data": report})
