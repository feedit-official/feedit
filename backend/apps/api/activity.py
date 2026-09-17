"""금주의 리포트 · 활동 지표 집계 (DB 없이 도는 순수 계산부).

activity_views.py 가 DB에서 행을 읽어 dict 목록으로 넘기면, 여기서 숫자를 만든다.
DB 조회와 계산을 나눠 둔 이유는 Postgres 없이도 단위 테스트를 돌리기 위해서다.

★ 주(週) 기준
  - 한국 시간 월요일 00:00 ~ 일요일 23:59 를 한 주로 본다.
  - '지난주 대비'는 바로 앞 주(월~일) 전체와 비교한다.

★ 이벤트 한 행의 모양 (activity_views._event_rows 가 만든다)
  {"type": "SEARCH"|"VOTE"|"SAVE"|"CHAT", "at": aware datetime, "meta": dict, "style": str|None}
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
TASTE_LIMIT = 4


def week_bounds(now: datetime):
    """이번 주 월요일 00:00(KST), 다음 주 월요일 00:00, 지난주 월요일 00:00 을 돌려준다."""
    local = now.astimezone(KST)
    start = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=7), start - timedelta(days=7)


def _in(row, lo, hi):
    return lo <= row["at"] < hi


def latest_state(events, kind, key_name, on_value):
    """토글형 기록(찜·투표)의 '지금 상태'를 계산한다.

    같은 대상에 여러 번 누르면 마지막 기록만 유효하다.
    반환: {대상 키: 마지막으로 켜진 시각} — 꺼진 대상은 빠진다.
    """
    last = {}
    for row in sorted((r for r in events if r["type"] == kind), key=lambda r: r["at"]):
        key = str(row["meta"].get(key_name) or "")
        if key:
            last[key] = row
    return {k: r["at"] for k, r in last.items() if on_value(r["meta"])}


def _voted(meta):
    return meta.get("choice") in ("BUY", "PASS")


def _liked(meta):
    return bool(meta.get("liked"))


def _search_block(events, start, end, prev):
    this = [r for r in events if r["type"] == "SEARCH" and _in(r, start, end)]
    last = [r for r in events if r["type"] == "SEARCH" and _in(r, prev, start)]
    words = Counter(str(r["meta"].get("q") or "").strip() for r in this)
    words.pop("", None)
    prev_words = {str(r["meta"].get("q") or "").strip() for r in last} - {""}
    top = None
    if words:
        # 횟수가 같으면 더 최근에 검색한 말을 앞에 둔다.
        recent = {}
        for r in this:
            recent[str(r["meta"].get("q") or "").strip()] = r["at"]
        label, n = max(words.items(), key=lambda kv: (kv[1], recent.get(kv[0])))
        # 축(스타일 · 브랜드 · 아이템 · 색상 · TPO …)은 그 말을 마지막으로 검색했을 때 남은 값을 쓴다.
        facet = next((str(r["meta"].get("facet") or "") for r in reversed(this)
                      if str(r["meta"].get("q") or "").strip() == label and r["meta"].get("facet")), "")
        top = {"label": label, "count": n, "facet": facet}
    return {
        "keywords": len(words),              # 이번 주 검색한 서로 다른 키워드 수
        "count": len(this),                  # 검색 횟수
        "prev_keywords": len(prev_words),
        "delta": len(words) - len(prev_words),
        "top": top,
    }


def _vote_block(events, start, end, prev):
    def voted_in(lo, hi):
        rows = [r for r in events if r["type"] == "VOTE" and r["at"] < hi]
        state = latest_state(rows, "VOTE", "card_key", _voted)
        return sum(1 for at in state.values() if at >= lo)

    now_state = latest_state(events, "VOTE", "card_key", _voted)
    this, last = voted_in(start, end), voted_in(prev, start)
    return {"count": this, "prev": last, "delta": this - last, "total": len(now_state)}


def _saved_block(events, start, end):
    state = latest_state(events, "SAVE", "item_id", _liked)
    return {"new": sum(1 for at in state.values() if start <= at < end), "total": len(state)}


def _chat_block(sessions, start, end):
    """chat_session 의 started_at ~ updated_at 을 사용 시간으로 본다.

    질문 한 번만 하고 끝난 대화도 0분이 되지 않게 1분으로 올려 센다.
    """
    mins = []
    for s in sessions:
        if not (start <= s["updated_at"] < end):
            continue
        began = max(s["started_at"], start)
        mins.append(max(1, round((s["updated_at"] - began).total_seconds() / 60)))
    total = sum(mins)
    return {"minutes": total, "sessions": len(mins), "avg_minutes": round(total / len(mins)) if mins else 0}


def _activity_block(events, start, end):
    days, hours = [0] * 7, [0] * 24
    for r in events:
        if _in(r, start, end):
            local = r["at"].astimezone(KST)
            days[local.weekday()] += 1
            hours[local.hour] += 1
    return {"days": days, "hours": hours}


def _taste_block(events, start, end, prev):
    """내 취향 지분 — 이번 주와 지난주에 **검색한 키워드 중 스타일**의 비중을 비교한다 (방식 b).

    스냅샷 테이블 없이 user_event 만으로 계산한다.
    ★ 2026-09-17 · 투표 · 찜은 빼고 검색만 센다. 리포트의 축이 '가장 많이 검색한 키워드'이고,
      취향 지분은 그 검색 기록을 스타일 축으로만 나눠 본 것이다.
    스타일이 아닌 검색(브랜드 · 아이템 · 색상 · TPO …)은 분모에서 뺀다.
    """
    kinds = ("SEARCH",)

    def shares(lo, hi):
        c = Counter(r["style"] for r in events if r["type"] in kinds and r.get("style") and _in(r, lo, hi))
        n = sum(c.values())
        return ({k: v / n * 100 for k, v in c.items()} if n else {}), n

    cur, n_cur = shares(start, end)
    old, n_old = shares(prev, start)
    rows = []
    for label, pct in sorted(cur.items(), key=lambda kv: -kv[1])[:TASTE_LIMIT]:
        rows.append({
            "label": label,
            "share": round(pct),
            # 지난주 기록이 아예 없으면 비교하지 않는다(None) — 0에서 올랐다고 부풀리지 않는다.
            "delta": None if not n_old else round(pct - old.get(label, 0.0)),
        })
    new = [r["label"] for r in rows if n_old and r["label"] not in old]
    return {"items": rows, "signals": n_cur, "prev_signals": n_old, "new_style": new[0] if new else None}


def build_weekly_report(events, sessions, now):
    start, end, prev = week_bounds(now)
    return {
        "week": {"start": start.date().isoformat(), "end": (end - timedelta(days=1)).date().isoformat()},
        "search": _search_block(events, start, end, prev),
        "vote": _vote_block(events, start, end, prev),
        "saved": _saved_block(events, start, end),
        "chat": _chat_block(sessions, start, end),
        "activity": _activity_block(events, start, end),
        "taste": _taste_block(events, start, end, prev),
    }
