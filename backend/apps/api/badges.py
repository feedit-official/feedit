"""컬렉션 배지 — 실제 활동 기록으로만 계산한다 (2026-09-19).

예전 화면(badges.js)은 획득일·진행도가 전부 하드코딩된 목업이었다.
여기서는 이미 쌓이는 기록으로 셀 수 있는 것만 계산하고,
기록이 없는 배지(사후 만족도 피드백 · 만족도 적중 · 공유 등)는 잠금 + '기록 없음' 으로 둔다.

  b01      스타일 입문자     즐겨입는 스타일을 1개 이상 고름 (user_taste STYLE)
  b02      첫 살말           첫 투표 (vote_ballot)
  b06~b08  살말 백전 N       투표 수 (vote_ballot)
  b12~b14  개근상 N          연속 활동일 — 투표·댓글·카드·찜·검색·챗봇 중 하나라도 한 날 (KST)
그 외는 계산 근거가 없어 잠금.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.core.models import UserEvent, UserTaste, VoteBallot, VoteCard, VoteComment

NO_RECORD = "기록 없음"


def _day(dt):
    return timezone.localtime(dt).date()


def _fmt(d):
    return d.strftime("%Y.%m.%d") if d else None


def _streak_reach(days, n):
    """정렬된 날짜들에서 연속 n일을 처음 채운 날 · 지금까지 최장 연속 · 오늘 기준 현재 연속."""
    best, run, reached, prev = 0, 0, None, None
    for d in days:
        run = run + 1 if prev and d - prev == timedelta(days=1) else 1
        prev = d
        best = max(best, run)
        if reached is None and run >= n:
            reached = d
    return reached, best


def badge_states(profile):
    """{badge_id: {"earned": bool, "date": "YYYY.MM.DD"|None, "progress": str|None}}"""
    if profile is None:
        return {}
    out = {}

    taste = (UserTaste.objects.filter(user=profile, taste_type=UserTaste.TasteType.TERM,
                                      term__term_type="STYLE")
             .order_by("created_at").values_list("created_at", flat=True).first())
    out["b01"] = {"earned": bool(taste), "date": _fmt(_day(taste)) if taste else None,
                  "progress": None if taste else "스타일 선택 전"}

    ballots = list(VoteBallot.objects.filter(user=profile).order_by("created_at")
                   .values_list("created_at", flat=True))
    out["b02"] = {"earned": bool(ballots), "date": _fmt(_day(ballots[0])) if ballots else None,
                  "progress": None if ballots else "0/1"}
    for bid, n in (("b06", 100), ("b07", 500), ("b08", 1000)):
        got = len(ballots) >= n
        out[bid] = {"earned": got, "date": _fmt(_day(ballots[n - 1])) if got else None,
                    "progress": None if got else f"{len(ballots):,}/{n:,}"}

    days = {_day(t) for t in ballots}
    days |= {_day(t) for t in UserEvent.objects.filter(user=profile).values_list("created_at", flat=True)}
    days |= {_day(t) for t in VoteComment.objects.filter(user=profile).values_list("created_at", flat=True)}
    days |= {_day(t) for t in VoteCard.objects.filter(user=profile).values_list("created_at", flat=True)}
    days = sorted(days)
    for bid, n in (("b12", 7), ("b13", 30), ("b14", 100)):
        reached, best = _streak_reach(days, n)
        out[bid] = {"earned": reached is not None, "date": _fmt(reached),
                    "progress": None if reached else f"{best}/{n}"}

    for bid in ("b03", "b04", "b05", "b09", "b10", "b11", "b15", "b16", "b17", "b18", "b19"):
        out[bid] = {"earned": False, "date": None, "progress": NO_RECORD}
    return out
