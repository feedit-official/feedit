"""선정 패션 채널에서 다음 조사 대상을 찾는 선행 트렌드 점수."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from .intent import classify
from .metrics import percentile_ranks, purchase_intent_index

WEIGHTS = {"upload": .30, "spread": .25, "view_growth": .30, "intent": .15}
# 플랫폼 검색축과 1:1로 맞춘다. 디테일/핏은 근거로는 유용하지만 후보 랭킹의
# 독립 검색축이 아니므로 여기서 별도 트렌드처럼 올리지 않는다.
FACETS = {"style", "item", "material", "brand"}


def _day(raw) -> date | None:
    try:
        return datetime.fromisoformat(str(raw or "")[:10]).date()
    except ValueError:
        return None


def build(store, lexicon, *, limit: int = 50, facet_filter: str = "all",
          gender: str = "all") -> dict:
    """Compute transparent candidates; missing history stays visible as low readiness."""
    with store._lock:
        videos = [dict(r) for r in store._conn.execute(
            "SELECT v.video_id,v.channel_id,v.title,v.description,v.published_at,"
            "COALESCE(c.gender,'미분류') gender FROM yt_video v "
            "LEFT JOIN yt_channel c ON c.channel_id=v.channel_id "
            "WHERE COALESCE(v.quality_status,'active')='active'")]
        stats = [dict(r) for r in store._conn.execute(
            "SELECT video_id,stat_date,view_count FROM yt_video_stat ORDER BY video_id,stat_date")]
        comments = [dict(r) for r in store._conn.execute(
            "SELECT substr(product_uid,4) video_id,body FROM text_document "
            "WHERE source_code='youtube' AND doc_kind IN ('yt_comment','yt_comment_reply') "
            "AND COALESCE(quality_status,'active')='active'")]
    today = date.today()
    if gender != "all":
        videos = [v for v in videos if v.get("gender") == gender]
    allowed_ids = {v["video_id"] for v in videos}
    stats = [r for r in stats if r["video_id"] in allowed_ids]
    comments = [r for r in comments if r["video_id"] in allowed_ids]
    terms_by_video, meta = {}, {}
    for video in videos:
        found = []
        for canonical, entity_facet in lexicon.extract(
                f"{video.get('title') or ''} {video.get('description') or ''}", "free"):
            if entity_facet in FACETS and lexicon.trendable.get(canonical, True):
                found.append((canonical, entity_facet))
                meta[canonical] = entity_facet
        terms_by_video[video["video_id"]] = list(dict.fromkeys(found))

    series = defaultdict(list)
    snapshot_days = set()
    for row in stats:
        observed = _day(row["stat_date"])
        if observed:
            series[row["video_id"]].append((observed, int(row.get("view_count") or 0)))
            snapshot_days.add(observed)
    growth = {}
    for video_id, points in series.items():
        if len(points) < 2:
            continue
        (d0, v0), (d1, v1) = points[-2], points[-1]
        if d1 > d0:
            growth[video_id] = max(0, v1 - v0) / (d1 - d0).days

    intent_by_video = defaultdict(Counter)
    for row in comments:
        intent_by_video[row["video_id"]].update(classify(row["body"])["labels"])

    raw = defaultdict(lambda: {"recent": 0, "prior": 0, "channels": set(),
                               "views_per_day": 0.0, "growth_videos": 0,
                               "intent": Counter(), "comment_samples": 0,
                               "videos": set(), "evidence": []})
    for video in videos:
        published = _day(video.get("published_at"))
        for canonical, _facet in terms_by_video.get(video["video_id"], []):
            item = raw[canonical]
            item["videos"].add(video["video_id"])
            if published and today - timedelta(days=30) <= published <= today:
                item["channels"].add(video.get("channel_id") or "")
                if published >= today - timedelta(days=13):
                    item["recent"] += 1
                else:
                    item["prior"] += 1
            if video["video_id"] in growth:
                item["views_per_day"] += growth[video["video_id"]]
                item["growth_videos"] += 1
            counts = intent_by_video.get(video["video_id"])
            if counts:
                item["intent"].update(counts)
                item["comment_samples"] += sum(counts.values())
            if len(item["evidence"]) < 3:
                item["evidence"].append({"video_id": video["video_id"],
                                         "title": video.get("title") or "",
                                         "published_at": video.get("published_at")})

    if facet_filter != "all":
        raw = defaultdict(raw.default_factory,
                          {k: v for k, v in raw.items() if meta.get(k) == facet_filter})
    if not raw:
        return {"as_of": today.isoformat(), "snapshot_days": len(snapshot_days),
                "rows": [], "weights": WEIGHTS, "facet": facet_filter, "gender": gender,
                "videos": len(videos)}
    upload_raw = {k: v["recent"] / 14 - v["prior"] / 16 for k, v in raw.items()}
    spread_raw = {k: len(v["channels"]) for k, v in raw.items()}
    view_raw = {k: v["views_per_day"] for k, v in raw.items()}
    intent_raw = {k: purchase_intent_index(v["intent"])["index_value"] for k, v in raw.items()}
    component = {"upload": percentile_ranks(upload_raw),
                 "spread": percentile_ranks(spread_raw),
                 "view_growth": percentile_ranks(view_raw),
                 "intent": intent_raw}
    rows = []
    for canonical, item in raw.items():
        scores = {name: component[name][canonical] for name in WEIGHTS}
        score = round(sum(WEIGHTS[name] * scores[name] for name in WEIGHTS))
        video_n = len(item["videos"])
        growth_coverage = item["growth_videos"] / video_n if video_n else 0
        readiness = round(100 * (.5 * min(len(snapshot_days) / 7, 1)
                                 + .3 * growth_coverage
                                 + .2 * min(item["comment_samples"] / 20, 1)))
        rows.append({"canonical": canonical, "facet": meta[canonical], "score": score,
                     "readiness": readiness,
                     "provisional": readiness < 60 or len(snapshot_days) < 7,
                     "recent_videos": item["recent"], "prior_videos": item["prior"],
                     "channels": len(item["channels"]), "videos": video_n,
                     "views_per_day": round(item["views_per_day"]),
                     "growth_coverage": round(100 * growth_coverage),
                     "intent_index": scores["intent"],
                     "comment_samples": item["comment_samples"],
                     "components": {k: round(v) for k, v in scores.items()},
                     "evidence": item["evidence"]})
    rows.sort(key=lambda x: (-x["score"], -x["readiness"], x["canonical"]))
    return {"as_of": today.isoformat(), "snapshot_days": len(snapshot_days),
            "weights": WEIGHTS, "facet": facet_filter, "gender": gender,
            "videos": len(videos),
            "rows": rows[:max(1, min(int(limit), 200))]}
