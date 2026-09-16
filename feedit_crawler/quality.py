"""기존 소셜 데이터 품질 재검사와 비파괴 격리.

행을 삭제하지 않는다. 새 필터 기준에 맞지 않으면 quarantined로 표시하고,
나중에 기준이 좋아져 통과하면 다시 active로 복구한다. 플랫폼 export는 active만
내보내므로 운영 지표를 오염시키지 않으면서 원문은 되짚어 볼 수 있다.
"""
from __future__ import annotations

from . import naver, social


def _reason_naver(row: dict, facets: dict[str, str]) -> str:
    body = row.get("body") or ""
    term = (row.get("product_uid") or "")[3:] \
        if (row.get("product_uid") or "").startswith("kw:") else ""
    facet = facets.get(term, "")
    if naver._is_ad(body):
        return "광고 문구"
    if naver._is_listing(body):
        return "판매 게시물"
    if (term and naver._needs_context(term, facet)
            and not naver._context_relevant(body, term, facet)):
        return f"패션 문맥 없음 ({term})"
    return ""


def audit(store, *, apply: bool = False, sample_limit: int = 12) -> dict:
    """네이버 글과 유튜브 영상/댓글을 재검사한다."""
    social.install(store)
    facets = naver._facet_map()
    lex = social._lexicon()
    with store._lock:
        videos = [dict(r) for r in store._conn.execute(
            "SELECT * FROM yt_video ORDER BY published_at DESC")]
        texts = [dict(r) for r in store._conn.execute(
            "SELECT * FROM text_document WHERE source_code IN ('naver','youtube')")]

    bad_videos: dict[str, str] = {}
    video_samples = []
    for v in videos:
        judged = social.judge_video(v, lexicon=lex)
        if not judged["keep"]:
            bad_videos[v["video_id"]] = judged["why"]
            if len(video_samples) < sample_limit:
                video_samples.append({"id": v["video_id"], "title": v.get("title"),
                                      "channel": v.get("channel_title"),
                                      "reason": judged["why"]})

    text_state: dict[int, str] = {}
    text_samples = []
    by_source = {"naver": {"total": 0, "quarantined": 0},
                 "youtube": {"total": 0, "quarantined": 0}}
    for t in texts:
        src = t["source_code"]
        by_source[src]["total"] += 1
        reason = ""
        if src == "naver":
            reason = _reason_naver(t, facets)
        else:
            uid = t.get("product_uid") or ""
            vid = uid[3:] if uid.startswith("yt:") else ""
            if vid in bad_videos:
                reason = "비패션 영상의 댓글"
        text_state[t["id"]] = reason
        if reason:
            by_source[src]["quarantined"] += 1
            if len(text_samples) < sample_limit:
                text_samples.append({"id": t["id"], "source": src,
                                     "term": t.get("product_uid"),
                                     "body": (t.get("body") or "")[:180],
                                     "reason": reason})

    if apply:
        with store._lock:
            for v in videos:
                reason = bad_videos.get(v["video_id"], "")
                store._conn.execute(
                    "UPDATE yt_video SET quality_status=?, quality_reason=? "
                    "WHERE video_id=?",
                    ("quarantined" if reason else "active", reason or None,
                     v["video_id"]))
            for text_id, reason in text_state.items():
                store._conn.execute(
                    "UPDATE text_document SET quality_status=?, quality_reason=? "
                    "WHERE id=?",
                    ("quarantined" if reason else "active", reason or None, text_id))
            store._conn.commit()

    return {
        "ok": True, "applied": apply,
        "videos": {"total": len(videos), "quarantined": len(bad_videos)},
        "texts": by_source,
        "video_samples": video_samples, "text_samples": text_samples,
    }
