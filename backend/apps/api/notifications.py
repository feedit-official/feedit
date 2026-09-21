"""알림 문구와 판정 규칙 — DB 를 건드리지 않는 순수 계산.

여기 있는 함수는 전부 값만 받아 값만 돌려준다.
DB 조회·생성은 notification_service.py 가 한다.
(금주의 리포트가 activity.py(계산) / activity_views.py(DB) 로 나뉜 것과 같은 결.)

돌리는 법:  cd backend && python -m unittest apps.api.test_notifications
"""
from __future__ import annotations

from datetime import timedelta, timezone

KST = timezone(timedelta(hours=9))

# ── 찜한 상품 가격 하락 ────────────────────────────────────────
# 몇 퍼센트부터 알릴 것인가. 1~2% 는 판매처의 일상적인 등락이라 알림이 소음이 된다.
PRICE_DROP_MIN_RATE = 0.05

# ── 살!말? 투표 결과 ──────────────────────────────────────────
# 표가 이만큼 모이면 작성자에게 한 번 알린다. 뒤에 숫자를 더 넣으면 그때마다 또 알린다.
VOTE_RESULT_MILESTONES = (10,)

# 알림 종류 — core.Notification.Kind 와 같은 값을 쓴다.
# 여기서 다시 적어 두는 이유는 이 파일이 Django 없이도 돌아야 해서다.
PRICE_DROP = "PRICE_DROP"
VOTE_RESULT = "VOTE_RESULT"
WEEKLY_REPORT = "WEEKLY_REPORT"
BADGE = "BADGE"
TERM_ADDED = "TERM_ADDED"
JOB_REVIEW = "JOB_REVIEW"
VOTE_COMMENT = "VOTE_COMMENT"

# 종류 → NotificationSetting 의 칸 이름
SETTING_FIELD = {
    PRICE_DROP: "price_drop",
    VOTE_RESULT: "vote_result",
    WEEKLY_REPORT: "weekly_report",
    BADGE: "badge",
    TERM_ADDED: "term_added",
    JOB_REVIEW: "job_review",
    VOTE_COMMENT: "vote_comment",
}


# ── 조사 ───────────────────────────────────────────────────
# "찜한 발레 플랫이" / "찜한 로퍼가" — 앞말 받침에 따라 조사가 달라진다.
# 알림 문구는 상품명·용어처럼 우리가 고르지 않은 말을 그대로 받는다.
# 숫자로 끝나는 말(뱃지 '살말 백전 100')은 읽는 소리의 받침을 본다.
_DIGIT_FINAL = {"0": True, "1": True, "2": False, "3": True, "4": False,
                "5": False, "6": True, "7": True, "8": True, "9": False}


def has_final(word):
    """마지막 글자에 받침이 있으면 True. 한글도 숫자도 아니면 받침이 있는 쪽으로 본다."""
    text = str(word or "").strip()
    if not text:
        return True
    last = text[-1]
    if "가" <= last <= "힣":
        return (ord(last) - 0xAC00) % 28 != 0
    if last.isdigit():
        return _DIGIT_FINAL[last]
    return True


def josa(word, with_final, without_final):
    """josa("로퍼", "이", "가") → "가"."""
    return with_final if has_final(word) else without_final


def kst_day(at):
    """알림 하루의 기준은 한국시간이다 (배치가 UTC 로 돌아도 같은 날로 묶인다)."""
    return at.astimezone(KST).date()


def drop_rate(base, current):
    """기준가 대비 내린 비율(0~1). 올랐거나 값이 없으면 None."""
    try:
        base = float(base)
        current = float(current)
    except (TypeError, ValueError):
        return None
    if base <= 0 or current <= 0 or current >= base:
        return None
    return (base - current) / base


def price_drops(items, min_rate=PRICE_DROP_MIN_RATE):
    """내린 상품만 골라 비율을 붙인다. 많이 내린 것이 앞에 온다.

    items: [{"item_id", "name", "base", "current"}]
    """
    out = []
    for it in items:
        rate = drop_rate(it.get("base"), it.get("current"))
        if rate is None or rate < min_rate:
            continue
        row = dict(it)
        row["rate"] = rate
        row["percent"] = int(round(rate * 100))
        out.append(row)
    out.sort(key=lambda r: r["rate"], reverse=True)
    return out


def price_digest(drops):
    """하루치를 한 건으로 묶은 (제목, 본문). 내린 것이 없으면 (None, None).

    상품마다 한 건씩 보내지 않는다 — 찜이 많은 사람은 알림창이 가격표가 된다.
    """
    if not drops:
        return None, None
    if len(drops) == 1:
        d = drops[0]
        name = d.get("name") or "찜한 상품"
        return f"찜한 {name}{josa(name, '이', '가')} {d['percent']}% 내려갔어요.", ""
    title = f"찜한 상품 {len(drops)}개가 내려갔어요."
    body = " · ".join(
        f"{d.get('name') or '이름 없는 상품'} {d['percent']}%" for d in drops[:5]
    )
    if len(drops) > 5:
        body += f"\n외 {len(drops) - 5}개"
    return title, body


def vote_milestone(total, milestones=VOTE_RESULT_MILESTONES):
    """지금 표 수가 넘어선 가장 큰 기준점. 아직이면 None."""
    reached = [m for m in milestones if total >= m]
    return max(reached) if reached else None


def vote_result_text(total, buys, card_title=""):
    """(제목, 본문). '살!'이 몇 명인지 그대로 적는다 — 결론을 대신 내지 않는다."""
    if total <= 0:
        return None, None
    title = f"{total}명 중 {buys}명이 '살!'이라고 했어요."
    return title, (card_title or "")


def badge_text(label):
    return f"뱃지 '{label}'{josa(label, '을', '를')} 달성했어요.", ""


def vote_comment_text(nickname, card_title, content, choice=None):
    """(제목, 본문). 누가 · 어느 카드에 · 살/말 중 어느 쪽으로 · 무슨 말을 했는지."""
    who = str(nickname or "누군가").strip() or "누군가"
    side = {"BUY": " '살!' 쪽에서", "PASS": " '말!' 쪽에서"}.get(choice or "", "")
    title = f"{who}님이{side} 댓글을 남겼어요."
    text = " ".join(str(content or "").split())
    if len(text) > 60:
        text = text[:59] + "…"
    card = str(card_title or "").strip()
    # ★ 2026-09-20 — 카드 제목과 댓글을 줄을 나눠 적는다 (알림 창이 \n 을 줄바꿈으로 보여 준다)
    body = "\n".join(x for x in ((f"'{card[:30]}'" if card else ""), (f"“{text}”" if text else "")) if x)
    return title, body


def job_review_text(job_label, approved, reason=""):
    """직업 인증 결과 — 승인이면 배지가 달렸다고, 반려면 사유와 다시 신청하는 길을 적는다."""
    label = str(job_label or "직업")
    if approved:
        return (f"{label} 인증이 승인됐어요.",
                f"이제 닉네임 옆에 {label} 배지가 달려요.")
    body = f"사유: {reason}\n" if reason else ""
    return (f"{label} 인증이 반려됐어요.",
            body + "회원정보 수정에서 서류를 다시 올려 신청할 수 있어요.")


def term_added_text(raw_term, canonical_name=""):
    """요청한 말과 사전에 오른 표준명이 다르면 둘 다 보여 준다."""
    body = ""
    if canonical_name and canonical_name != raw_term:
        body = (f"사전에는 '{canonical_name}'"
                f"{josa(canonical_name, '으로', '로')} 올라갔어요.")
    return f"요청한 '{raw_term}'{josa(raw_term, '이', '가')} 사전에 올라갔어요.", body


def weekly_report_text(week_start):
    """week_start: 이번 주 월요일 date."""
    return (
        "일요일이 왔어요.",
        "금주의 리포트를 확인해 보세요.",
    )
