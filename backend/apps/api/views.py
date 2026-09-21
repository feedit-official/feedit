"""프론트(트렌드 분석 페이지)가 부르는 읽기 전용 API.

── 구조 ────────────────────────────────────────────────────
    브라우저 ─▶ (Vercel 함수 또는 vite 프록시) ─▶ 이 API ─▶ AWS RDS

스키마는 SKN31-FINAL-4Team/backend 의 모델(apps/core/models)이 원본이다.
이 파일은 그 표를 **읽기만** 한다.

── 원칙 ────────────────────────────────────────────────────
① 쓰지 않는다. 전부 GET.
② 지표(온도·모멘텀·구매의향 지수·연관도)는 적재된 값을 그대로 쓴다.
   여기서 하는 계산은 "읽은 값끼리의 집계"(평균·중앙값·기간 비교)뿐이다.
   수명주기 단계처럼 저장된 칸이 없는 판정은 규칙을 응답(`rule`)에 함께 적는다.
③ 값이 없으면 지어내지 않는다. `status:"empty"` 와 사유를 돌려주고,
   칸 단위로 없는 값은 null 로 둔다. 화면은 그 자리를 '측정 불가'로 그린다.

── 탭 ↔ 주소 ───────────────────────────────────────────────
    언급량·온도   /api/trend?term=
    연관어        /api/assoc?term=
    긍부정        /api/trend?term=      (같은 표의 반응·의도 칸)
    할인률 변화   /api/discount?style=&kind=&brand=&item=&term=
    리세일 시세   /api/resale?…          (같은 조건)
    수명주기      /api/lifecycle?…       (같은 조건)
"""

from __future__ import annotations

import math
import os
import statistics
from collections import defaultdict
from datetime import timedelta

from django.db import connection
from django.db.models import Case, Count, Exists, F, FloatField, Max, Min, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Cast, Coalesce, Ln
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET

from .notifications import josa
from apps.core.models import (
    Brand,
    BrandSource,
    ContentItem,
    DictionaryTerm,
    Product,
    ProductSource,
    ProductSourceSnapshot,
    ProductTerm,
    ResaleSnapshot,
    TermAlias,
    TermAssocDaily,
    TermMetricDaily,
    TextDocument,
    TextTermMention,
    VoteBallot,
    VoteCard,
)

MAX_LIMIT = 500

# ★ 팀이 정한 핵심 스타일 10종 (2026-09-16).
#   세부 검색 STYLE 칸에는 이 10개만, 이 순서를 기준으로 보여 준다.
#   상품 태그가 0건이어도 칸에서 빼지 않고 0 으로 둔다 — 핵심인데 안 보이면
#   "적재가 안 됐다" 는 사실이 가려진다.
#   바꿔야 하면 코드 대신 .env 의 FEEDIT_CORE_STYLES=고프코어,블록코어,… 로 덮는다.
DEFAULT_CORE_STYLES = (
    "고프코어", "블록코어", "바이크코어", "놈코어", "애슬레저",
    "클래식", "아메카지", "그런지", "페미닌", "스트릿웨어",
)


def _core_styles():
    env = [x.strip() for x in (os.getenv("FEEDIT_CORE_STYLES") or "").split(",") if x.strip()]
    return tuple(env) if env else DEFAULT_CORE_STYLES

# 우리 term_type ↔ 화면이 쓰는 축 이름
FACET_KO = {
    "BRAND": "브랜드", "STYLE": "스타일", "ITEM": "아이템", "MATERIAL": "소재",
    "DETAIL": "디테일", "COLOR": "색", "TPO": "TPO", "PERSON": "인물",
}


# ══════════════════════════════════════════════════════════════
#  공용 도우미
# ══════════════════════════════════════════════════════════════

def _ok(data, **extra):
    return JsonResponse({"status": "ok", **extra, "data": data})


def _empty(reason, **extra):
    return JsonResponse({"status": "empty", "reason": reason, **extra, "data": None})


def _num(v, nd=None):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, nd) if nd is not None else f


def _pct(v):
    """할인율 — 0~1 로 들어온 값은 % 로 바꾼다."""
    v = _num(v)
    if v is None:
        return None
    return round(v * 100 if 0 < v <= 1 else v, 1)


def _retail_discount_pct(row):
    """일반 판매 스냅샷은 정가·판매가를 우선한다. 1%를 100%로 오해하지 않는다."""
    list_price = _num(row.get("list_price"))
    sale_price = _num(row.get("sale_price"))
    if list_price is not None and list_price > 0 and sale_price is not None:
        if sale_price < 0 or sale_price > list_price:
            return None
        return round((list_price - sale_price) / list_price * 100, 1)
    raw = _num(row.get("discount_rate"))
    return round(raw, 1) if raw is not None and 0 <= raw <= 100 else None


def _int(request, name, default, lo, hi):
    try:
        return max(lo, min(hi, int(request.GET.get(name, default))))
    except (TypeError, ValueError):
        return default


def _norm(s):
    return "".join(str(s or "").split()).lower()


def _median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _pick_measured(qs):
    """같은 이름이 여러 축에 있을 때(예: '니트' ITEM · MATERIAL) 지표가 가장 많은 쪽.
    예전에는 순서 없는 .first() 라 지표가 적은 쪽이 잡히기도 했다(2026-09-19)."""
    return qs.annotate(_n=Count("daily_metrics")).order_by("-_n", "id").first()


def _resolve_term(name):
    """화면에서 온 말 → DictionaryTerm. 표준명 › 정규화명 › 별칭 › 브랜드명 순."""
    name = (name or "").strip()
    if not name:
        return None
    base = DictionaryTerm.objects.exclude(status="INACTIVE")
    t = _pick_measured(base.filter(canonical_name=name))
    if t:
        return t
    n = _norm(name)
    t = _pick_measured(base.filter(normalized_name=n))
    if t:
        return t
    alias = (
        TermAlias.objects.filter(Q(alias=name) | Q(normalized_alias=n))
        .values_list("term_id", flat=True).first()
    )
    if alias:
        return base.filter(id=alias).first()
    return base.filter(
        Q(brand__name=name) | Q(brand__english_name__iexact=name), term_type="BRAND"
    ).first()


def _resolve_brand(name):
    """표준명·영문명·플랫폼 표기 중 하나로 활성 브랜드를 찾는다."""
    name = (name or "").strip()
    if not name:
        return None
    brand = Brand.objects.filter(status="ACTIVE").filter(
        Q(name=name) | Q(english_name__iexact=name)
    ).first()
    if brand:
        return brand
    brand_id = (
        BrandSource.objects.filter(brand__status="ACTIVE")
        .filter(Q(name=name) | Q(english_name__iexact=name))
        .values_list("brand_id", flat=True)
        .first()
    )
    return Brand.objects.filter(id=brand_id).first() if brand_id else None


def _brand_variants(brand):
    """댓글에서 브랜드를 찾을 때 쓸 검수된 표기. 너무 짧은 표기는 오탐을 막는다."""
    raw = [brand.name, brand.english_name]
    raw.extend(
        value
        for pair in BrandSource.objects.filter(brand=brand).values_list("name", "english_name")
        for value in pair
    )
    variants, seen = [], set()
    for value in raw:
        value = str(value or "").strip()
        key = _norm(value)
        if not key or key in seen or (value.isascii() and len(key) < 3) or (not value.isascii() and len(key) < 2):
            continue
        seen.add(key)
        variants.append(value)
    return variants[:40]


def _contains_any(field, values):
    query = Q()
    for value in values:
        query |= Q(**{f"{field}__icontains": value})
    return query


def _published_date(metadata):
    raw = metadata.get("published_at") if isinstance(metadata, dict) else None
    parsed = parse_datetime(str(raw)) if raw else None
    return parsed.date() if parsed else None


def _direct_sentiment_series(rows, days):
    """mention 행을 댓글 단위로 합친 뒤, 실제 게시일 기준 일별 반응으로 만든다."""
    documents = {}
    for row in rows:
        day = _published_date(row.get("document__analysis_metadata"))
        score = _num(row.get("sentiment_score"))
        if day is None or score is None:
            continue
        doc = documents.setdefault(
            row["document_id"], {"date": day, "scores": [], "intent": row.get("intent_code")}
        )
        doc["scores"].append(score)
        if not doc["intent"] and row.get("intent_code"):
            doc["intent"] = row["intent_code"]

    if not documents:
        return [], None, 0

    last_date = max(doc["date"] for doc in documents.values())
    since = last_date - timedelta(days=days - 1)
    daily = defaultdict(lambda: defaultdict(int))
    intent_fields = {
        "QUESTION": "question_n", "PURCHASE": "purchase_n", "EXPERIENCE": "experience_n",
        "PRAISE": "praise_n", "CRITIQUE": "critique_n", "CHITCHAT": "chitchat_n",
    }
    included = 0
    for doc in documents.values():
        if doc["date"] < since:
            continue
        included += 1
        bucket = daily[doc["date"]]
        score = sum(doc["scores"]) / len(doc["scores"])
        polarity = "pos_n" if score > 0.5 else "neg_n" if score < 0.5 else "neu_n"
        bucket[polarity] += 1
        intent_field = intent_fields.get(str(doc["intent"] or "").upper())
        if intent_field:
            bucket[intent_field] += 1

    series = []
    count_fields = (
        "pos_n", "neu_n", "neg_n", "question_n", "purchase_n", "experience_n",
        "praise_n", "critique_n", "chitchat_n",
    )
    for day in sorted(daily):
        bucket = daily[day]
        point = {"date": day.isoformat(), **{field: bucket[field] for field in count_fields}}
        total = point["pos_n"] + point["neu_n"] + point["neg_n"]
        point.update({
            "mention": total,
            "document": total,
            "pos_rate": round(point["pos_n"] / total * 100, 4) if total else None,
            "neu_rate": round(point["neu_n"] / total * 100, 4) if total else None,
            "neg_rate": round(point["neg_n"] / total * 100, 4) if total else None,
            "sentiment": round((point["pos_n"] - point["neg_n"]) / total, 5) if total else None,
            "intent": None,
        })
        series.append(point)
    return series, last_date, included


# ── 장기 이력 (2026-09-19) ─────────────────────────────────────
#  RDS 의 YouTube 댓글·설명란을 '쓰인 날'로 되돌려 다시 계산한 일별 지표.
#  (backend/apps/core/management/commands/rebuild_term_history.py)
#  플랫폼 합산 버전(feedit-l2-v2)은 하루치뿐이라 수명주기(28일 이상)를 못 낸다.
#  그래서 '수명주기 · 추이' 에서만 이 버전을 읽는다. 플랫폼별 온도·새 용어는 기존 버전 그대로.
#  ★ 기본 버전 고르기(_metric_version)에서는 빼야 한다 — 적재 시각이 더 늦어
#    '가장 최근 버전'으로 잡히면 합산 행이 없는 버전이 기본이 되어 화면 전체가 빈다.
HISTORY_VERSION = (os.getenv("FEEDIT_HISTORY_METRIC_VERSION") or "feedit-yt-history-v1").strip()
HISTORY_SOURCE = "YOUTUBE"
HISTORY_MIN_POINTS = 28
HISTORY_BASIS = {
    "source": HISTORY_SOURCE,
    "metric_version": HISTORY_VERSION,
    "note": "YouTube 댓글·영상 설명의 작성일 기준 재계산 이력입니다. 다른 플랫폼은 포함되지 않습니다.",
}


def _history_series(term, days):
    """장기 이력(YouTube) — 마지막 적재일 기준으로 days 만큼."""
    qs = TermMetricDaily.objects.filter(
        term=term, metric_version=HISTORY_VERSION, source__code__iexact=HISTORY_SOURCE)
    last = qs.aggregate(d=Max("metric_date"))["d"]
    if not last:
        return []
    return list(qs.filter(metric_date__gt=last - timedelta(days=days))
                .order_by("metric_date").values(*METRIC_VALUES))


def _metric_version(term_id=None):
    """여러 지표 버전이 섞여 있을 수 있다 — 환경변수 › 가장 최근 적재 버전.
    장기 이력 버전(HISTORY_VERSION)은 합산 행이 없으므로 기본 버전 후보에서 뺀다."""
    env = (os.getenv("FEEDIT_METRIC_VERSION") or "").strip()
    qs = TermMetricDaily.objects.exclude(metric_version=HISTORY_VERSION)
    if term_id:
        qs = qs.filter(term_id=term_id)
    if env and qs.filter(metric_version=env).exists():
        return env
    row = qs.order_by("-metric_date", "-updated_at").values("metric_version").first()
    return row["metric_version"] if row else None


def _term_missing_reason(name, days=None):
    as_brand = Brand.objects.filter(Q(name=name) | Q(english_name__iexact=name)).exists()
    if as_brand:
        return (f"‘{name}’ 은 브랜드 사전에는 있지만 지표 대상 용어(dictionary_term)로 "
                "연결돼 있지 않아 지표가 없습니다.")
    return f"‘{name}’ 을 사전에서 찾지 못했습니다."


# ══════════════════════════════════════════════════════════════
#  health · dictionary · terms
# ══════════════════════════════════════════════════════════════

def _column_mismatch():
    """모델에는 있는데 실제 DB 표에는 없는 칸 — 스키마 어긋남을 먼저 알린다."""
    out = {}
    models = (DictionaryTerm, TermMetricDaily, TermAssocDaily, Product,
              ProductSource, ProductSourceSnapshot, ResaleSnapshot)
    with connection.cursor() as c:
        for model in models:
            raw = model._meta.db_table.replace('"', "")
            schema, _, tbl = raw.rpartition(".")
            try:
                c.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = %s", [schema or "public", tbl])
                have = {r[0] for r in c.fetchall()}
            except Exception as exc:  # noqa: BLE001
                out[raw] = {"missing": ["(표를 못 읽음)"], "error": str(exc)[:120]}
                continue
            if not have:
                out[raw] = {"missing": ["(표 자체가 없음)"]}
                continue
            gap = sorted({f.column for f in model._meta.concrete_fields} - have)
            if gap:
                out[raw] = {"missing": gap}
    return out


@require_GET
def health(request):
    """붙었는지, 표마다 몇 행인지, 모델과 어긋나지 않는지."""
    mismatch = _column_mismatch()
    counts = {}
    for label, model in (
        ("dictionary.dictionary_term", DictionaryTerm),
        ("commerce.product_source", ProductSource),
        ("snapshot.product_source_snapshot", ProductSourceSnapshot),
        ("snapshot.resale_snapshot", ResaleSnapshot),
        ("analysis.term_metric_daily", TermMetricDaily),
        ("analysis.term_assoc_daily", TermAssocDaily),
    ):
        try:
            counts[label] = model.objects.count()
        except Exception as exc:  # noqa: BLE001
            counts[label] = f"error: {str(exc)[:80]}"
    latest = None
    try:
        latest = TermMetricDaily.objects.aggregate(d=Max("metric_date"))["d"]
    except Exception:  # noqa: BLE001
        pass
    # 지표 표가 어떤 모양으로 적재돼 있는지 — 합산 행(source 없음)·버전·용어당 날짜 수
    metric_shape = None
    try:
        tm = TermMetricDaily.objects
        per_term = (tm.values("term_id").annotate(n=Count("metric_date", distinct=True))
                    .order_by("-n"))
        metric_shape = {
            "rows_all_sources": tm.filter(source__isnull=True).count(),
            "rows_by_source": {(r["source__code"] or "ALL"): r["n"] for r in
                               tm.values("source__code").annotate(n=Count("id"))},
            "versions": {r["metric_version"]: r["n"] for r in
                         tm.values("metric_version").annotate(n=Count("id"))},
            "terms": per_term.count(),
            "max_days_per_term": per_term[0]["n"] if per_term else 0,
            "dates": list(tm.values_list("metric_date", flat=True).distinct().order_by("metric_date")[:40]),
            "filled": {
                "trend_temperature": tm.filter(trend_temperature__isnull=False).count(),
                "level": tm.filter(level__isnull=False).count(),
                "momentum": tm.filter(momentum__isnull=False).count(),
                "purchase_intent_index": tm.filter(purchase_intent_index__isnull=False).count(),
                "positive_rate": tm.filter(positive_rate__isnull=False).count(),
            },
            "sample_terms": list(per_term.values_list("term__canonical_name", "term__term_type", "n")[:10]),
        }
    except Exception as exc:  # noqa: BLE001
        metric_shape = {"error": str(exc)[:200]}

    # 핵심 스타일 10종이 사전·스타일 표·상품 태그에 실제로 있는지
    core_styles = []
    try:
        from apps.core.models import Style
        for name in _core_styles():
            term = DictionaryTerm.objects.filter(term_type="STYLE", canonical_name=name).first()
            style = Style.objects.filter(term=term).first() if term else None
            core_styles.append({
                "style": name,
                "in_dictionary": term is not None,
                "is_core_flag": (style.is_core if style else None),
                "tagged_products": (ProductTerm.objects.filter(term=term)
                                    .values("product_source_id").distinct().count() if term else 0),
            })
    except Exception as exc:  # noqa: BLE001
        core_styles = [{"error": str(exc)[:200]}]

    bits = []
    if mismatch:
        bits.append("★ 모델과 실제 DB 가 어긋납니다: " + " / ".join(
            f"{k}: {', '.join(v.get('missing') or [])}" for k, v in mismatch.items()))
    bits.append(f"트렌드 지표 {counts.get('analysis.term_metric_daily')}행 (최신 {latest}).")
    return JsonResponse({
        "ok": True,
        "checked_at": timezone.now().isoformat(),
        "tables": counts,
        "latest_metric_date": latest,
        "metric_version": _metric_version(),
        "column_mismatch": mismatch or None,
        "core_styles": core_styles,
        "metric_shape": metric_shape,
        "verdict": " ".join(bits),
    })


HOT_MIN_ACTIVE_28 = 7   # 최근 28일 중 언급된 날이 이보다 적으면 순위에서 뺀다 (하루 튄 용어 방지)
HOT_RULE = ("최근 7일 평균(ma7)이 28일 평균(ma28)보다 얼마나 높은지(%)로 줄 세웁니다. "
            f"최근 28일 중 {HOT_MIN_ACTIVE_28}일 이상 언급된 용어만 올립니다.")


def _hot_terms(request):
    """GET /api/trend?rank=hot — 홈 HOT TREND TOP 10.

    장기 이력(YouTube) 버전의 마지막 적재일 기준. 지표는 다시 계산하지 않고
    적재된 ma7·ma28 을 그대로 읽어 변화율만 낸다.
    """
    limit = _int(request, "limit", 10, 1, 30)
    hist = TermMetricDaily.objects.filter(
        metric_version=HISTORY_VERSION, source__code__iexact=HISTORY_SOURCE)
    as_of = hist.aggregate(d=Max("metric_date"))["d"]
    if not as_of:
        return _empty("순위를 낼 지표가 아직 없습니다.")
    active = dict(
        hist.filter(metric_date__gt=as_of - timedelta(days=28))
        .values("term_id").annotate(n=Count("id")).values_list("term_id", "n"))
    latest = (
        hist.filter(metric_date__gt=as_of - timedelta(days=3),
                    term_id__in=[k for k, v in active.items() if v >= HOT_MIN_ACTIVE_28])
        .exclude(term__status="INACTIVE")
        .order_by("term_id", "-metric_date").distinct("term_id")
        .values("term_id", "term__canonical_name", "term__term_type", "metric_date",
                "ma7", "ma28", "trend_temperature")
    )
    rows = []
    for r in latest:
        ma7, ma28 = _num(r["ma7"]), _num(r["ma28"])
        if not ma28:
            continue
        rows.append({
            "term": r["term__canonical_name"], "facet": r["term__term_type"],
            "change_pct": round((ma7 / ma28 - 1) * 100),
            "temp": _num(r["trend_temperature"]),
            "active_days_28": active.get(r["term_id"], 0),
            "date": r["metric_date"].isoformat(),
        })
    rising = sorted((x for x in rows if x["change_pct"] > 0), key=lambda x: -x["change_pct"])
    falling = sorted((x for x in rows if x["change_pct"] < 0), key=lambda x: x["change_pct"])
    return _ok({
        "as_of": as_of.isoformat(),
        "basis": HISTORY_BASIS,
        "rule": HOT_RULE,
        "rising": rising[:limit],
        "falling": falling[:limit],
    })


@require_GET
def terms(request):
    """지표가 실제로 있는 용어 목록 — 화면의 검색 후보. ?rank=hot 이면 HOT 순위."""
    if (request.GET.get("rank") or "").strip() == "hot":
        return _hot_terms(request)
    ver = _metric_version()
    qs = (
        TermMetricDaily.objects.filter(source__isnull=True, metric_version=ver)
        .values("term__canonical_name", "term__term_type")
        .annotate(points=Count("id"), last_date=Max("metric_date"))
        # 적재 초기에는 용어당 하루치뿐일 수 있다 — 하루라도 있으면 목록에 올린다.
        .filter(points__gte=1)
        .order_by("-points", "term__canonical_name")[: _int(request, "limit", 300, 1, MAX_LIMIT)]
    )
    rows = list(qs)
    if not rows:
        return _empty("지표가 있는 용어가 아직 없습니다. analysis.term_metric_daily 적재를 확인하세요.")
    return _ok([
        {"term": r["term__canonical_name"], "facet": r["term__term_type"],
         "points": r["points"], "last_date": r["last_date"]}
        for r in rows
    ])


@require_GET
def dictionary(request):
    """GET /api/dictionary — 화면 검색이 쓸 사전 전체 (용어 + 브랜드)."""
    limit = _int(request, "limit", 6000, 1, 12000)
    rows, seen = [], set()
    for r in DictionaryTerm.objects.filter(status="ACTIVE").values(
            "canonical_name", "term_type", "english_name")[:limit]:
        key = (r["canonical_name"], r["term_type"])
        if not r["canonical_name"] or key in seen:
            continue
        seen.add(key)
        rows.append({"label": r["canonical_name"],
                     "facet": FACET_KO.get(r["term_type"], r["term_type"]),
                     "kind": "brand" if r["term_type"] == "BRAND" else "term",
                     "en": r["english_name"] or ""})
    # 용어로 아직 연결 안 된 브랜드도 검색은 되게 한다.
    for r in Brand.objects.filter(status="ACTIVE").values("name", "english_name")[:limit]:
        if r["name"] and (r["name"], "BRAND") not in seen:
            seen.add((r["name"], "BRAND"))
            rows.append({"label": r["name"], "facet": "브랜드", "kind": "brand",
                         "en": r["english_name"] or ""})
    if not rows:
        return _empty("사전이 비어 있습니다. dictionary_term·brand 적재를 확인하세요.")
    by_facet = defaultdict(int)
    for r in rows:
        by_facet[r["facet"]] += 1
    return _ok(rows, counts=dict(by_facet), total=len(rows))


# ══════════════════════════════════════════════════════════════
#  언급량·온도 / 긍부정  — analysis.term_metric_daily
# ══════════════════════════════════════════════════════════════

METRIC_VALUES = (
    "metric_date", "raw_count", "mention_count", "document_count", "content_count",
    "creator_count", "log_count", "percentile", "level", "ma7", "ma28", "momentum",
    "trend_temperature", "sentiment_avg",
    "positive_count", "neutral_count", "negative_count",
    "question_count", "purchase_count", "experience_count", "praise_count",
    "critique_count", "chitchat_count",
    "positive_rate", "neutral_rate", "negative_rate",
    "question_rate", "purchase_rate", "experience_rate", "praise_rate", "critique_rate",
    "purchase_intent_index", "metrics",
)


def _metric_point(r, share=None):
    """DB 한 행 → 화면이 쓰는 이름. (예전 화면이 쓰던 temp·mention 이름을 유지)"""
    return {
        "date": r["metric_date"].isoformat(),
        "mention": r["mention_count"],
        "document": r["document_count"],
        "content": r["content_count"],
        "creator": r["creator_count"],
        "raw": _num(r["raw_count"]),
        "log": _num(r["log_count"]),
        "pct_rank": _num(r["percentile"]),
        "level": _num(r["level"]),
        "ma7": _num(r["ma7"]),
        "ma28": _num(r["ma28"]),
        "momentum": _num(r["momentum"]),
        "temp": _num(r["trend_temperature"]),
        "sentiment": _num(r["sentiment_avg"]),
        "share_pct": share,
        # 긍부정
        "pos_n": r["positive_count"], "neu_n": r["neutral_count"], "neg_n": r["negative_count"],
        "pos_rate": _num(r["positive_rate"]), "neu_rate": _num(r["neutral_rate"]),
        "neg_rate": _num(r["negative_rate"]),
        # 의도
        "question_n": r["question_count"], "purchase_n": r["purchase_count"],
        "experience_n": r["experience_count"], "praise_n": r["praise_count"],
        "critique_n": r["critique_count"], "chitchat_n": r["chitchat_count"],
        "intent": _num(r["purchase_intent_index"]),
    }


def _term_series(term, days, source=None, version=None):
    """용어 하나의 일별 지표. source=None 이면 전체 합산 행."""
    since = timezone.localdate() - timedelta(days=days)
    version = version or _metric_version(term.id)
    qs = TermMetricDaily.objects.filter(term=term, metric_version=version)
    # 최신 적재일이 오늘보다 한참 전일 수 있다 → 기준을 '마지막 적재일'로 잡는다.
    last = qs.filter(source__isnull=True).aggregate(d=Max("metric_date"))["d"]
    if last:
        since = min(since, last - timedelta(days=days))
    qs = qs.filter(metric_date__gte=since)
    qs = qs.filter(source__code=source) if source else qs.filter(source__isnull=True)
    return list(qs.order_by("metric_date").values(*METRIC_VALUES)), version


@require_GET
def trend(request):
    """GET /api/trend?term=발레코어&days=120&source=musinsa

    반환: series(일별), platforms(플랫폼별 최신 온도), new_terms(최근 새로 잡힌 용어)
    """
    name = (request.GET.get("term") or "").strip()
    if not name:
        return terms(request)
    days = _int(request, "days", 120, 7, 730)
    source = (request.GET.get("source") or "").strip() or None

    term = _resolve_term(name)
    if term is None:
        return _empty(_term_missing_reason(name), term=name, known=False)

    rows, version = _term_series(term, days, source)
    if not rows:
        return _empty(
            f"‘{term.canonical_name}’ 은 사전에 있지만 측정된 지표가 아직 없습니다.",
            term=term.canonical_name, known=True)

    # 점유율 — 같은 날 전체(합산 행) 언급량 중 이 용어의 몫
    dates = [r["metric_date"] for r in rows]
    totals = dict(
        TermMetricDaily.objects.filter(
            source__isnull=True, metric_version=version,
            metric_date__gte=dates[0], metric_date__lte=dates[-1])
        .values_list("metric_date").annotate(t=Sum("mention_count"))
    )
    series = []
    for r in rows:
        tot = totals.get(r["metric_date"]) or 0
        share = round(r["mention_count"] / tot * 100, 2) if tot else None
        series.append(_metric_point(r, share))

    last_date = rows[-1]["metric_date"]

    # 추이 — 합산 이력이 28일보다 짧으면 장기 이력(YouTube)으로 그린다.
    # 플랫폼별 온도 · 새 용어는 아래에서 그대로 기존 버전(version)을 쓴다.
    series_basis = None
    if source is None and len(rows) < HISTORY_MIN_POINTS:
        hist = _history_series(term, days)
        if len(hist) > len(rows):
            series = [_metric_point(r, (r.get("metrics") or {}).get("share_pct")) for r in hist]
            series_basis = HISTORY_BASIS

    # 플랫폼별 최신 온도
    plat_rows = (
        TermMetricDaily.objects.filter(term=term, metric_version=version,
                                       source__isnull=False,
                                       metric_date__gte=last_date - timedelta(days=14))
        .order_by("source_id", "-metric_date")
        .values("source__code", "source__name", "metric_date", "trend_temperature",
                "level", "mention_count")
    )
    platforms, seen = [], set()
    for p in plat_rows:
        if p["source__code"] in seen:
            continue
        seen.add(p["source__code"])
        platforms.append({"code": p["source__code"], "name": p["source__name"],
                          "date": p["metric_date"].isoformat(),
                          "temp": _num(p["trend_temperature"]), "level": _num(p["level"]),
                          "mention": p["mention_count"]})
    platforms.sort(key=lambda x: (x["temp"] is None, -(x["temp"] or 0)))

    # 최근 7일 안에 처음 잡힌 용어 (같은 축) — 온도 높은 순
    first_seen = (
        TermMetricDaily.objects.filter(source__isnull=True, metric_version=version,
                                       term__term_type=term.term_type)
        .values("term_id").annotate(first=Min("metric_date"))
        .filter(first__gte=last_date - timedelta(days=7))
    )
    new_ids = [x["term_id"] for x in first_seen[:200]]
    new_terms = list(
        TermMetricDaily.objects.filter(term_id__in=new_ids, source__isnull=True,
                                       metric_version=version, metric_date=last_date)
        .order_by("-trend_temperature")
        .values("term__canonical_name", "trend_temperature")[:5]
    )

    last = series[-1]
    missing = [f for f in ("temp", "momentum", "level", "intent") if last.get(f) is None]
    extra = {}
    if missing:
        extra["unavailable"] = {
            "fields": missing,
            "reason": f"최신 행에 비어 있는 값이 있습니다 ({'·'.join(missing)}).",
        }
    return _ok(
        {
            "term": term.canonical_name,
            "facet": term.term_type,
            "source": source,
            "days": days,
            "points": len(series),
            "as_of": last_date.isoformat(),
            "metric_version": version,
            "series": series,
            "series_as_of": series[-1]["date"] if series else None,
            "series_basis": series_basis,
            "platforms": platforms,
            "new_terms": [{"term": x["term__canonical_name"],
                           "temp": _num(x["trend_temperature"])} for x in new_terms],
        },
        **extra,
    )


def _sentiment_evidence(term, is_brand=False, variants=None):
    """긍부정 신호 유형별 근거 문장 추출"""
    evidence = defaultdict(list)
    intents = ["QUESTION", "PURCHASE", "EXPERIENCE", "PRAISE", "CRITIQUE", "CHITCHAT"]

    if is_brand:
        docs = TextDocument.objects.filter(
            document_type=TextDocument.DocumentType.COMMENT
        ).filter(_contains_any("body", variants)).values_list("id", flat=True)[:2000]
        qs = TextTermMention.objects.filter(
            document_id__in=docs, intent_code__in=intents
        ).exclude(mention_text__isnull=True).filter(_contains_any("mention_text", variants))
    else:
        qs = TextTermMention.objects.filter(
            term=term, document__document_type=TextDocument.DocumentType.COMMENT,
            intent_code__in=intents
        ).exclude(mention_text__isnull=True)

    rows = (
        qs.order_by("-created_at")
        .values("intent_code", "mention_text", "document__source__name", "document__document_type")[:1000]
    )

    for row in rows:
        intent = str(row["intent_code"]).upper()
        if not intent or intent == "NONE":
            continue
        bucket = evidence[intent]
        if len(bucket) < 2:
            bucket.append({
                "tag": row["document__source__name"] or row["document__document_type"],
                "text": row["mention_text"][:160],
            })
    return evidence


@require_GET
def sentiment(request):
    """GET /api/sentiment?term=셔츠&days=400&subject=term|brand.

    사전 용어는 TextTermMention의 해당 term 분석을 직접 집계한다.
    브랜드는 아직 DictionaryTerm(BRAND)이 없으므로 브랜드 표기가 실제 포함된
    mention 문맥만 모아 '브랜드 언급 문맥 반응'으로 제공한다.
    """
    name = (request.GET.get("term") or "").strip()
    if not name:
        return _empty("term 을 지정해 주세요. 예: /api/sentiment?term=셔츠")
    days = _int(request, "days", 400, 7, 730)
    requested_kind = (request.GET.get("subject") or request.GET.get("kind") or "").strip().lower()
    term = None if requested_kind == "brand" else _resolve_term(name)

    method = "TERM_MENTION"
    facet = None
    canonical = name
    if term is not None:
        canonical = term.canonical_name
        facet = term.term_type
        mention_rows = list(
            TextTermMention.objects.filter(
                term=term,
                document__document_type=TextDocument.DocumentType.COMMENT,
                sentiment_score__isnull=False,
            ).values(
                "document_id", "document__analysis_metadata", "sentiment_score", "intent_code"
            )
        )
        matched_comments = len({row["document_id"] for row in mention_rows})
    else:
        brand = _resolve_brand(name)
        if brand is None:
            return _empty(
                f"‘{name}’ 을 활성 사전이나 브랜드 표에서 찾지 못했습니다.",
                term=name, known=False,
            )
        canonical = brand.name or brand.english_name or name
        facet = "BRAND"
        method = "BRAND_CONTEXT"
        variants = _brand_variants(brand)
        if not variants:
            return _empty(
                f"‘{canonical}’ 은 브랜드이지만 댓글에서 안전하게 찾을 수 있는 표기가 없습니다.",
                term=canonical, known=True,
            )
        documents = list(
            TextDocument.objects.filter(document_type=TextDocument.DocumentType.COMMENT)
            .filter(_contains_any("body", variants))
            .values("id", "analysis_metadata")
        )
        matched_comments = len(documents)
        doc_meta = {row["id"]: row["analysis_metadata"] for row in documents}
        mention_rows = list(
            TextTermMention.objects.filter(
                document_id__in=doc_meta,
                sentiment_score__isnull=False,
            )
            .exclude(mention_text__isnull=True)
            .filter(_contains_any("mention_text", variants))
            .values("document_id", "sentiment_score", "intent_code")
        )
        for row in mention_rows:
            row["document__analysis_metadata"] = doc_meta.get(row["document_id"], {})

    series, last_date, classified_comments = _direct_sentiment_series(mention_rows, days)
    if not series:
        detail = (
            "브랜드가 언급된 댓글은 있지만 해당 문맥에 연결된 긍부정 분석행이 없습니다."
            if method == "BRAND_CONTEXT" and matched_comments
            else "댓글에서 이 용어와 연결된 긍부정 분석행이 없습니다."
        )
        return _empty(detail, term=canonical, facet=facet, known=True)

    evidence = _sentiment_evidence(term, is_brand=(method == "BRAND_CONTEXT"), variants=variants if method == "BRAND_CONTEXT" else None)

    return _ok({
        "term": canonical,
        "facet": facet,
        "days": days,
        "points": len(series),
        "as_of": last_date.isoformat(),
        "metric_version": "direct-text-mention-v1",
        "method": method,
        "scope_label": "브랜드 언급 문맥" if method == "BRAND_CONTEXT" else "용어 직접 언급",
        "matched_comments": matched_comments,
        "classified_comments": classified_comments,
        "series": series,
        "evidence": dict(evidence),
    })


# ══════════════════════════════════════════════════════════════
#  연관어 — analysis.term_assoc_daily
# ══════════════════════════════════════════════════════════════

def _analysis_tag_term_map():
    """콘텐츠 JSON 태그의 표기 → 공통 DictionaryTerm ID.

    새 분석이나 외부 호출은 하지 않는다. 표준명·정규화명·검수된 별칭만 연결한다.
    같은 표기가 여러 활성 용어에 걸리면 먼저 확정된 표준 용어 하나만 사용한다.
    """
    terms = list(
        DictionaryTerm.objects.exclude(status="INACTIVE")
        .values("id", "canonical_name", "normalized_name", "term_type")
    )
    by_id = {row["id"]: row for row in terms}
    by_name = {}
    for row in terms:
        for value in (row["canonical_name"], row["normalized_name"]):
            key = _norm(value)
            if key:
                by_name.setdefault(key, row["id"])
    for alias in TermAlias.objects.filter(term_id__in=by_id).values(
        "term_id", "alias", "normalized_alias"
    ):
        for value in (alias["alias"], alias["normalized_alias"]):
            key = _norm(value)
            if key:
                by_name.setdefault(key, alias["term_id"])
    return by_name, by_id


def _tag_values(value):
    """analysis_tags의 현재/과거 JSON 모양에서 문자열 태그만 꺼낸다."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _tag_values(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if not str(key).startswith("_"):
                yield from _tag_values(item)


def _assoc_evidence(source_term, target_ids):
    """실제 같은 문서 안에서 찾은 대상 용어 문맥만 근거로 돌려준다."""
    evidence = defaultdict(list)
    if not target_ids:
        return evidence
    doc_ids = TextTermMention.objects.filter(term=source_term).values("document_id")
    rows = (
        TextTermMention.objects.filter(term_id__in=target_ids, document_id__in=doc_ids)
        .exclude(mention_text__isnull=True).exclude(mention_text="")
        .order_by("-created_at")
        .values("term_id", "mention_text", "document__document_type", "document__source__name")[:1500]
    )
    for row in rows:
        bucket = evidence[row["term_id"]]
        if len(bucket) < 2:
            bucket.append({
                "tag": row["document__source__name"] or row["document__document_type"],
                "text": row["mention_text"][:160],
            })
    return evidence


def _direct_assoc(term, limit):
    """적재 지표 없이 기존 DB의 공통 키만으로 연관 용어를 찾는다.

    - 문서: 같은 TextDocument의 TextTermMention
    - 상품: 같은 ProductSource의 ProductTerm (표준 상품 style도 기준 용어로 인정)
    - 콘텐츠: 같은 ContentItem.analysis_tags JSON

    서로 단위가 다른 세 개의 수를 새 지표처럼 합성하지 않는다. 화면 호환용
    cooccurrence는 '공통 레코드 수 합계'이고, 원천별 수를 sources에 함께 공개한다.
    """
    stats = defaultdict(lambda: {"documents": 0, "products": 0, "contents": 0})

    source_docs = TextTermMention.objects.filter(term=term).values("document_id")
    for row in (
        TextTermMention.objects.filter(document_id__in=source_docs)
        .exclude(term=term)
        .values("term_id")
        .annotate(n=Count("document_id", distinct=True))
    ):
        stats[row["term_id"]]["documents"] = row["n"]

    source_products = (
        ProductSource.objects.filter(product_terms__term=term)
        .values("id")
        .distinct()
    )
    for row in (
        ProductTerm.objects.filter(product_source_id__in=source_products)
        .exclude(term=term)
        .values("term_id")
        .annotate(n=Count("product_source_id", distinct=True))
    ):
        stats[row["term_id"]]["products"] = row["n"]

    by_name, term_rows = _analysis_tag_term_map()
    source_id = term.id
    content_matches = 0
    for row in ContentItem.objects.exclude(analysis_tags={}).values("analysis_tags").iterator(chunk_size=500):
        ids = {
            by_name[key]
            for raw in _tag_values(row["analysis_tags"])
            if (key := _norm(raw)) in by_name
        }
        if source_id not in ids:
            continue
        content_matches += 1
        for target_id in ids - {source_id}:
            stats[target_id]["contents"] += 1

    ranked = []
    for target_id, sources in stats.items():
        total = sum(sources.values())
        if total:
            ranked.append((target_id, total, sum(1 for value in sources.values() if value), sources))
    ranked.sort(key=lambda row: (-row[1], -row[2], term_rows.get(row[0], {}).get("canonical_name", "")))
    ranked = ranked[:limit]
    evidence = _assoc_evidence(term, [row[0] for row in ranked])

    items = []
    for rank, (target_id, total, _, sources) in enumerate(ranked, 1):
        target = term_rows.get(target_id)
        if not target:
            continue
        items.append({
            "term": target["canonical_name"],
            "facet": target["term_type"],
            "facet_ko": FACET_KO.get(target["term_type"], target["term_type"]),
            "cooccurrence": total,
            "lift": None,
            "pmi": None,
            "percentile": None,
            "rank": rank,
            "change": None,
            "sources": sources,
            "evidence": evidence.get(target_id, []),
        })
    return {
        "term": term.canonical_name,
        "as_of": timezone.localdate().isoformat(),
        "previous": None,
        "metric_version": None,
        "method": "DIRECT_SHARED_KEYS",
        "scope_label": "기존 DB 공통 키 직접 연결",
        "items": items,
        "history": [],
        "source_records": {
            "documents": TextTermMention.objects.filter(term=term).values("document_id").distinct().count(),
            "products": source_products.count(),
            "contents": content_matches,
        },
    }

@require_GET
def assoc(request):
    """GET /api/assoc?term=발레코어&limit=60&days=90

    items   최신 기준일의 연관어 (lift·PMI·백분위·순위·신규 여부·순위 변화·근거 문장)
    history 기준일별 연관어 수와 동시언급 문서 합 — 추이 차트
    """
    name = (request.GET.get("term") or "").strip()
    if not name:
        return _empty("term 을 지정해 주세요. 예: /api/assoc?term=발레코어")
    term = _resolve_term(name)
    if term is None:
        return _empty(_term_missing_reason(name), term=name)
    limit = _int(request, "limit", 60, 5, 200)
    days = _int(request, "days", 120, 7, 730)

    base = TermAssocDaily.objects.filter(source_term=term)
    ver_row = base.order_by("-metric_date").values("metric_version").first()
    if ver_row is None:
        direct = _direct_assoc(term, limit)
        if direct["items"]:
            return _ok(direct)
        total = TermAssocDaily.objects.count()
        return _empty(
            f"‘{term.canonical_name}’ 과 공통 문서·상품·콘텐츠 태그를 가진 연관 용어가 없습니다.",
            term=term.canonical_name, total_rows=total,
            source_records=direct["source_records"])
    base = base.filter(metric_version=ver_row["metric_version"])
    dates = list(base.values_list("metric_date", flat=True).distinct().order_by("-metric_date")[:2])
    latest = dates[0]
    prev = dates[1] if len(dates) > 1 else None

    sort_method = request.GET.get("sort", "pmi")
    order_clause = ["-cooccurrence_count", "-pmi"] if sort_method == "cooc" else [Coalesce("association_rank", 999999), "-pmi", "-cooccurrence_count"]

    rows = list(
        base.filter(metric_date=latest)
        .order_by(*order_clause)
        .values("target_term_id", "target_term__canonical_name", "target_term__term_type",
                "cooccurrence_count", "lift", "pmi", "association_percentile",
                "association_rank", "is_new")[:limit]
    )
    prev_rank = {}
    if prev:
        prev_rank = dict(base.filter(metric_date=prev).values_list("target_term_id",
                                                                     "association_rank"))

    target_ids = [r["target_term_id"] for r in rows]
    evidence = _assoc_evidence(term, target_ids)

    items = []
    for r in rows:
        rank, before = r["association_rank"], prev_rank.get(r["target_term_id"])
        if r["is_new"] or (prev and r["target_term_id"] not in prev_rank):
            change = "new"
        elif rank is not None and before is not None:
            change = before - rank          # 양수 = 순위 상승
        else:
            change = None
        items.append({
            "term": r["target_term__canonical_name"],
            "facet": r["target_term__term_type"],
            "facet_ko": FACET_KO.get(r["target_term__term_type"], r["target_term__term_type"]),
            "cooccurrence": r["cooccurrence_count"],
            "lift": _num(r["lift"], 4),
            "pmi": _num(r["pmi"], 4),
            "percentile": _num(r["association_percentile"], 2),
            "rank": rank,
            "change": change,
            "evidence": evidence.get(r["target_term_id"], []),
        })

    hist = (
        base.filter(metric_date__gte=latest - timedelta(days=days))
        .values("metric_date")
        .annotate(count=Count("id"), cooc=Sum("cooccurrence_count"))
        .order_by("metric_date")
    )
    history = [{"date": h["metric_date"].isoformat(), "count": h["count"], "cooc": h["cooc"]}
               for h in hist]

    return _ok({
        "term": term.canonical_name,
        "as_of": latest.isoformat(),
        "previous": prev.isoformat() if prev else None,
        "metric_version": ver_row["metric_version"],
        "items": items,
        "history": history,
    })


# ══════════════════════════════════════════════════════════════
#  세부 검색 조건 → 상품(플랫폼 상품) 집합
# ══════════════════════════════════════════════════════════════
#  네 칸(스타일·종류·브랜드·아이템명)은 서로 독립된 필터이고, 겹치면 교집합이다.
#  스냅샷(가격·리셀)은 commerce.product_source 에 붙으므로 그 단위로 센다.
#  (표준 상품 product 가 아직 연결 안 된 UNMAPPED 행도 빠지지 않게)

FACET_PARAMS = ("style", "kind", "brand", "item")
MIN_PRODUCTS_FOR_FACETS = 20

BRAND_EXPR = Coalesce("product__brand__name", "source_brand__brand__name", "source_brand__name")
ITEM_EXPR = Coalesce("product__canonical_name", "source_name")
CATEGORY_EXPR = Coalesce("product__category__name", "source_category__category__name", "source_category__source_category_name")

def _list(request, name):
    out, seen = [], set()
    for v in request.GET.getlist(name):
        v = (v or "").strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _selection(request):
    return {k: _list(request, k) for k in FACET_PARAMS}


def _apply(qs, sel, skip=None):
    """고른 조건을 ProductSource 목록에 건다. `skip` 축은 뺀다(자기 축 제외)."""
    if skip != "style" and sel["style"]:
        # ★ 2026-09-21 — 스타일은 상품마다 여러 개 달린다. 연결 표(product_term)만 본다.
        #   예전 단일 FK(product.style) 갈래는 칸 자체가 없어져 떼어냈다.
        qs = qs.filter(
            id__in=ProductTerm.objects.filter(term__term_type="STYLE",
                                              term__canonical_name__in=sel["style"])
            .values("product_source_id"))
    if skip != "kind" and sel["kind"]:
        qs = qs.filter(
            Q(id__in=ProductTerm.objects.filter(term__term_type="ITEM",
                                                term__canonical_name__in=sel["kind"])
              .values("product_source_id"))
            | Q(product__category__name__in=sel["kind"])
            | Q(source_category__category__name__in=sel["kind"]))
    if skip != "brand" and sel["brand"]:
        qs = qs.filter(Q(product__brand__name__in=sel["brand"])
                       | Q(product__brand__english_name__in=sel["brand"])
                       | Q(source_brand__brand__name__in=sel["brand"])
                       | Q(source_brand__name__in=sel["brand"]))
    if skip != "item" and sel["item"]:
        qs = qs.filter(Q(product__canonical_name__in=sel["item"]) | Q(source_name__in=sel["item"]))
    return qs


def _selected_sources(sel, market=None):
    qs = _apply(ProductSource.objects.all(), sel)
    if market:
        qs = qs.filter(market_type=market)
    return qs


def _selection_term(sel, preferred=""):
    """검색 조건에서 실제 지표가 있는 대표 용어를 고른다.

    카테고리·상품명은 commerce 쪽 값이라 같은 이름의 사전 용어가 없을 수 있다.
    그때 선택 상품에 붙은 태그 중 지표 이력이 가장 많은 용어로 내려가면,
    검색 조건은 유지하면서도 빈 수명주기를 잘못 보여 주지 않는다.
    """
    candidates = [preferred]
    for key in ("item", "kind", "style", "brand"):
        candidates.extend(sel.get(key) or [])
    seen = set()
    for name in candidates:
        key = _norm(name)
        if not key or key in seen:
            continue
        seen.add(key)
        term = _resolve_term(name)
        if term:
            return term
    if not any(sel.values()):
        return None
    source_ids = _selected_sources(sel).values("id")
    return _pick_measured(
        DictionaryTerm.objects.exclude(status="INACTIVE")
        .filter(product_terms__product_source_id__in=source_ids)
        .distinct()
    )


def _selection_label(sel):
    b, i = (sel["brand"] or [None])[0], (sel["item"] or [None])[0]
    if b and i:
        return f"{b} {i}"
    for k in ("item", "brand", "kind", "style"):
        if sel[k]:
            return sel[k][0]
    return ""


def _count_rows(qs, expr, keep, limit):
    agg = (qs.annotate(_label=expr).exclude(_label__isnull=True).exclude(_label="")
           .values("_label").annotate(n=Count("id", distinct=True)).order_by("-n", "_label"))
    out = [{"label": r["_label"], "count": r["n"]} for r in agg[:limit]]
    have = {o["label"] for o in out}
    out += [{"label": k, "count": 0, "picked_only": True} for k in keep if k not in have]
    return out


def _core_style_rows(qs, keep):
    """STYLE 칸 — 핵심 스타일만, 0건도 0 으로 남긴다. 많이 걸린 순, 같으면 핵심 목록 순."""
    core = _core_styles()
    counts = dict(
        ProductTerm.objects.filter(term__term_type="STYLE", term__canonical_name__in=core,
                                   product_source_id__in=qs.values("id"))
        .values_list("term__canonical_name")
        .annotate(n=Count("product_source_id", distinct=True))
    )
    out = [{"label": name, "count": counts.get(name, 0), "core": True} for name in core]
    out.sort(key=lambda o: (-o["count"], core.index(o["label"])))
    # 다른 경로(검색창 등)로 이미 걸린 비핵심 스타일은 칩을 뗄 수 있게 남긴다.
    out += [{"label": k, "count": 0, "picked_only": True} for k in keep if k not in core]
    return out


def _term_rows(qs, term_type, keep, limit):
    agg = (ProductTerm.objects.filter(term__term_type=term_type, product_source_id__in=qs.values("id"))
           .values("term__canonical_name")
           .annotate(n=Count("product_source_id", distinct=True))
           .order_by("-n", "term__canonical_name"))
    out = [{"label": r["term__canonical_name"], "count": r["n"]} for r in agg[:limit]
           if r["term__canonical_name"]]
    have = {o["label"] for o in out}
    out += [{"label": k, "count": 0, "picked_only": True} for k in keep if k not in have]
    return out


def _item_with_thumb_rows(qs, expr, keep, limit):
    out = _count_rows(qs, expr, keep, limit)
    labels = [o["label"] for o in out if not o.get("picked_only")]

    thumb_map = {}
    if labels:
        from apps.core.models import ProductSource

        # 1. Check ProductSource by product__canonical_name (fast join)
        prod_thumbs = ProductSource.objects.filter(product__canonical_name__in=labels)\
            .exclude(thumbnail_url__isnull=True).exclude(thumbnail_url="")\
            .values_list("product__canonical_name", "thumbnail_url")
        for k, v in prod_thumbs:
            if k not in thumb_map:
                thumb_map[k] = v

        # 2. For remaining labels, check ProductSource by source_name (fast index)
        missing_labels = [L for L in labels if L not in thumb_map]
        if missing_labels:
            ps_thumbs = ProductSource.objects.filter(source_name__in=missing_labels)\
                .exclude(thumbnail_url__isnull=True).exclude(thumbnail_url="")\
                .values_list("source_name", "thumbnail_url")
            for k, v in ps_thumbs:
                if k not in thumb_map:
                    thumb_map[k] = v

    for o in out:
        o["thumb"] = thumb_map.get(o["label"])

    return out


def _discount_product_rows(qs, query, limit, offset=0):
    """할인률 후보는 이름 집계가 아니라 실제 일반 판매 상품 ID 단위로 돌려준다."""
    qs = qs.filter(Exists(ProductSourceSnapshot.objects.filter(product_source_id=OuterRef("pk"))))
    if query:
        qs = qs.filter(Q(source_name__icontains=query)
                       | Q(product__canonical_name__icontains=query))
    rows = (qs.annotate(_label=ITEM_EXPR, _brand=BRAND_EXPR)
            .values("id", "_label", "_brand", "thumbnail_url", "source__name")
            .distinct().order_by("-id")[offset:offset + limit])
    return [{"id": row["id"], "label": row["_label"] or "상품명 없음",
             "brand": row["_brand"] or "", "source": row["source__name"],
             "thumb": row["thumbnail_url"]} for row in rows]


@require_GET
def facets(request):
    """GET /api/facets?style=스트릿&brand=스투시&limit=200 — 세부 검색 네 칸의 후보."""
    limit = _int(request, "limit", 200, 1, 1000)
    sel = _selection(request)
    base = ProductSource.objects.filter(status="ACTIVE")
    n_products = base.count()

    if n_products < MIN_PRODUCTS_FOR_FACETS:
        def dict_terms(kind):
            return [{"label": r, "count": None} for r in
                    DictionaryTerm.objects.filter(status="ACTIVE", term_type=kind)
                    .values_list("canonical_name", flat=True)[:limit] if r]
        data = {
            "style": [{"label": name, "count": None, "core": True} for name in _core_styles()],
            "kind": dict_terms("ITEM"),
            "brand": [{"label": r, "count": None} for r in
                      Brand.objects.filter(status="ACTIVE").values_list("name", flat=True)[:limit] if r],
            "item": [],
        }
        if not any(data.values()):
            return _empty("상품도 사전도 비어 있습니다.", narrowed=False, products=n_products)
        return _ok(data, matched=0, narrowed=False, products=n_products,
                   note=(f"commerce.product_source 가 {n_products}개뿐이라 축끼리 좁히지 못했습니다 "
                         "— 사전 목록을 그대로 보냅니다."))

    matched = _apply(base, sel).count()
    data = {
        "style": _core_style_rows(_apply(base, sel, "style"), sel["style"]),
        "kind": _term_rows(_apply(base, sel, "kind"), "ITEM", sel["kind"], limit),
        "brand": _count_rows(_apply(base, sel, "brand"), BRAND_EXPR, sel["brand"], limit),
        "item": _count_rows(_apply(base, sel, "item"), ITEM_EXPR, sel["item"], limit),
    }
    if not any(len(v) for v in data.values()):
        return _empty("고른 조건에 맞는 상품이 없습니다. 조건을 하나 빼고 다시 보세요.",
                      matched=0, narrowed=True)
    return _ok(data, matched=matched, narrowed=True, selected=sel, products=n_products)


@require_GET
def discount_facets(request):
    """GET /api/discount/facets?style=스트릿&brand=스투시&limit=200"""
    limit = _int(request, "limit", 200, 1, 1000)
    item_limit = _int(request, "item_limit", min(limit, 24), 1, 50)
    item_offset = _int(request, "item_offset", 0, 0, 10000)
    sel = _selection(request)
    query = (request.GET.get("q") or "").strip()
    base = ProductSource.objects.filter(market_type="RETAIL", status="ACTIVE")
    def item_page():
        # 한 건을 더 읽어 다음 페이지 유무만 확인한다. 3천 건을 세거나 URL을 보내지 않는다.
        rows = _discount_product_rows(_apply(base, sel, "item"), query,
                                      item_limit + 1, item_offset)
        return rows[:item_limit], len(rows) > item_limit

    # 입력 중에는 상품명 후보만 바뀐다. 네 축의 집계를 매 글자마다 다시 하지 않는다.
    if request.GET.get("items_only") == "1":
        rows, has_more = item_page()
        return _ok({"item": rows}, items_only=True, item_has_more=has_more,
                   item_offset=item_offset)
    n_products = base.count()

    if n_products == 0:
        return _empty("상품 데이터가 비어 있습니다.", narrowed=False, products=n_products)

    matched = _apply(base, sel).count()
    rows, has_more = item_page()
    data = {
        "style": _core_style_rows(_apply(base, sel, "style"), sel["style"]),
        "brand": _count_rows(_apply(base, sel, "brand"), BRAND_EXPR, sel["brand"], limit),
        "kind": _count_rows(_apply(base, sel, "kind"), CATEGORY_EXPR, sel["kind"], limit),
        "item": rows,
    }
    if not any(len(v) for v in data.values()):
        return _empty("고른 조건에 맞는 상품이 없습니다. 조건을 하나 빼고 다시 보세요.",
                      matched=0, narrowed=True)
    return _ok(data, matched=matched, narrowed=True, selected=sel, products=n_products,
               item_has_more=has_more, item_offset=item_offset)


def _temp_block(term_name, days):
    """선택 대상의 대표 용어 온도 — 할인률·리세일·수명주기 탭이 함께 쓴다."""
    term = _resolve_term(term_name) if term_name else None
    if term is None:
        return {"term": term_name or None, "status": "empty",
                "reason": (_term_missing_reason(term_name) if term_name else "대표 용어가 없습니다."),
                "series": []}
    rows, _ = _term_series(term, days)
    if not rows:
        return {"term": term.canonical_name, "status": "empty",
                "reason": f"‘{term.canonical_name}’ 의 트렌드 지표가 아직 없습니다.", "series": []}
    series = [_metric_point(r) for r in rows]
    return {"term": term.canonical_name, "facet": term.term_type, "status": "ok",
            "as_of": series[-1]["date"], "latest": series[-1], "series": series}


def _no_selection():
    return _empty("세부 검색에서 스타일·종류·브랜드·아이템명 중 하나 이상을 골라 주세요.")


# ══════════════════════════════════════════════════════════════
#  할인률 변화 — snapshot.product_source_snapshot
# ══════════════════════════════════════════════════════════════

@require_GET
def discount(request):
    """GET /api/discount?source_id=17&days=90 — 한 일반 판매 상품의 가격 기록."""
    sel = _selection(request)
    source_id = _int(request, "source_id", 0, 0, 2_147_483_647)
    source = None
    if source_id:
        source = (ProductSource.objects.filter(id=source_id, market_type="RETAIL", status="ACTIVE")
                  .select_related("source", "product", "product__brand", "source_brand").first())
        if source is None:
            return _empty("선택한 일반 판매 상품을 찾을 수 없습니다.", source_id=source_id)
    if source is None and not any(sel.values()):
        return _no_selection()
    days = _int(request, "days", 90, 14, 365)
    label = (source.source_name or source.product.canonical_name) if source else _selection_label(sel)
    term_name = (request.GET.get("term") or "").strip() or ("" if source else label)

    sources = _selected_sources(sel).filter(market_type="RETAIL") if source is None else None
    ps_ids = [source.id] if source else list(sources.values_list("id", flat=True)[:5000])
    if not ps_ids:
        return _empty(f"‘{label}’ 조건에 맞는 판매 상품이 없습니다.", label=label)

    snaps = ProductSourceSnapshot.objects.filter(product_source_id__in=ps_ids)
    last_obs = snaps.aggregate(d=Max("observed_at"))["d"]
    if last_obs is None:
        return _empty(f"‘{label}’ 상품 {len(ps_ids)}개에 가격 스냅샷이 아직 없습니다.",
                      label=label, products=len(ps_ids))
    since = last_obs - timedelta(days=days)

    rows = list(
        snaps.filter(observed_at__gte=since)
        .order_by("product_source_id", "observed_at")
        .values("product_source_id", "product_source__source__code",
                "product_source__source__name", "observed_at", "list_price", "sale_price",
                "discount_rate", "stock_status", "rating", "review_count", "like_count",
                "sales_count")[:60000]
    )

    # 상품별 최신 스냅샷 + 재입고(품절 → 판매 전환) 횟수
    latest, restock, prev_stock = {}, 0, {}
    first_disc = None
    max_disc = None
    for r in rows:
        pid = r["product_source_id"]
        d = _retail_discount_pct(r)
        r["_d"] = d
        st = (r["stock_status"] or "").upper()
        if prev_stock.get(pid) in ("SOLD_OUT", "OUT_OF_STOCK") and st and st not in ("SOLD_OUT", "OUT_OF_STOCK"):
            restock += 1
        if st:
            prev_stock[pid] = st
        if d and d > 0:
            first_disc = r["observed_at"] if first_disc is None else min(first_disc, r["observed_at"])
            max_disc = d if max_disc is None else max(max_disc, d)
        latest[pid] = r

    def plat_summary(items):
        ds = [x["_d"] for x in items if x["_d"] is not None]
        priced = [x for x in items if x["sale_price"] is not None]
        cheapest = min(priced, key=lambda x: x["sale_price"]) if priced else None
        sold = [x for x in items if (x["stock_status"] or "").upper() in ("SOLD_OUT", "OUT_OF_STOCK")]
        return {
            "products": len(items),
            "avg_discount": round(_mean(ds), 1) if ds else None,
            "max_discount": max(ds) if ds else None,
            "full_price_pct": round(sum(1 for x in ds if x <= 0) / len(ds) * 100, 1) if ds else None,
            "min_sale_price": _num(cheapest["sale_price"]) if cheapest else None,
            "min_list_price": _num(cheapest["list_price"]) if cheapest else None,
            "min_discount": cheapest["_d"] if cheapest else None,
            "sold_out": len(sold),
            "rating": round(_mean([_num(x["rating"]) for x in items]), 2)
            if any(x["rating"] is not None for x in items) else None,
            "reviews": sum(x["review_count"] or 0 for x in items),
            "likes": sum(x["like_count"] or 0 for x in items),
            "stock": dict(sorted(
                {k: sum(1 for x in items if (x["stock_status"] or "미상") == k)
                 for k in {(x["stock_status"] or "미상") for x in items}}.items(),
                key=lambda kv: -kv[1])),
        }

    by_plat = defaultdict(list)
    for r in latest.values():
        by_plat[(r["product_source__source__code"], r["product_source__source__name"])].append(r)
    platforms = []
    for (code, pname), items in by_plat.items():
        platforms.append({"code": code, "name": pname, **plat_summary(items)})
    platforms.sort(key=lambda p: (p["min_sale_price"] is None, p["min_sale_price"] or 0))

    # 일별 할인율 — 단일 상품은 하루 중 마지막 관측값, 조건 검색은 평균.
    daily = defaultdict(list)
    daily_plat = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["_d"] is None:
            continue
        day = timezone.localtime(r["observed_at"]).date().isoformat()
        if source:
            daily[day] = [r["_d"]]
            daily_plat[r["product_source__source__code"]][day] = [r["_d"]]
        else:
            daily[day].append(r["_d"])
            daily_plat[r["product_source__source__code"]][day].append(r["_d"])
    series = [{"date": d, "discount": round(_mean(v), 2)} for d, v in sorted(daily.items())]
    plat_series = {c: [{"date": d, "discount": round(_mean(v), 2)} for d, v in sorted(m.items())]
                   for c, m in daily_plat.items()}

    # 최근 2주 변화(%p)
    change_2w = None
    if series:
        last_day = series[-1]["date"]
        cut = (timezone.datetime.fromisoformat(last_day) - timedelta(days=14)).date().isoformat()
        before = [s for s in series if s["date"] <= cut]
        if before:
            change_2w = round(series[-1]["discount"] - before[-1]["discount"], 1)

    overall = plat_summary(list(latest.values()))
    cheapest = platforms[0] if platforms and platforms[0]["min_sale_price"] is not None else None
    product = None
    price_series = []
    matched_platforms = []
    if source:
        current = latest[source.id]
        # 하루에 여러 번 수집했다면 그날의 마지막 유효 판매가만 그린다.
        # 가격이 없는 날을 0원이나 직전 가격으로 채우지 않는다.
        price_by_day = {}
        for row in rows:
            sale = _num(row["sale_price"])
            if sale is None or sale <= 0:
                continue
            regular = _num(row["list_price"])
            day = timezone.localtime(row["observed_at"]).date().isoformat()
            price_by_day[day] = {
                "date": day, "sale_price": sale,
                "list_price": regular if regular is not None and regular > 0 else None,
            }
        price_series = [price_by_day[day] for day in sorted(price_by_day)]
        minimum = min(price_series, key=lambda point: point["sale_price"]) if price_series else None
        maximum = max(price_series, key=lambda point: point["sale_price"]) if price_series else None
        brand = (source.product.brand.name if source.product_id and source.product.brand_id
                 else source.source_brand.name if source.source_brand_id else "")
        # 표준 상품(product_id)이 같다고 확인된 일반 판매 상품만 가격 비교에 넣는다.
        # 현재 DB에 매칭이 한 판매처뿐이면 다른 상품을 이름으로 추측해 끼워 넣지 않는다.
        peers = ([source] if not source.product_id or source.mapping_status != "MAPPED" else
                 list(ProductSource.objects.filter(
                     product_id=source.product_id, mapping_status="MAPPED",
                     market_type="RETAIL", status="ACTIVE",
                 ).select_related("source").order_by("id")[:50]))
        if not any(peer.id == source.id for peer in peers):
            peers = peers[:49] + [source]
        peer_snapshots = {}
        for snap in (ProductSourceSnapshot.objects.filter(product_source_id__in=[peer.id for peer in peers])
                     .order_by("product_source_id", "-observed_at", "-id")
                     .distinct("product_source_id")
                     .values("product_source_id", "list_price", "sale_price", "discount_rate", "observed_at")):
            peer_snapshots[snap["product_source_id"]] = snap
        by_platform = {}
        for peer in peers:
            snap = peer_snapshots.get(peer.id)
            if not snap:
                continue
            sale = _num(snap["sale_price"])
            if sale is None or sale <= 0:
                continue
            candidate = {
                "source_id": peer.id, "name": peer.source.name,
                "sale_price": sale, "list_price": _num(snap["list_price"]),
                "discount_rate": _retail_discount_pct(snap),
                "observed_at": snap["observed_at"],
            }
            previous = by_platform.get(peer.source_id)
            if previous is None or sale < previous["sale_price"]:
                by_platform[peer.source_id] = candidate
        matched_platforms = sorted(by_platform.values(), key=lambda item: item["sale_price"])
        product = {
            "id": source.id, "name": label, "brand": brand,
            "source": source.source.name, "image": source.thumbnail_url,
            "list_price": _num(current["list_price"]),
            "sale_price": _num(current["sale_price"]),
            "discount_rate": current["_d"],
            "observed_at": current["observed_at"],
            "history_min_price": minimum["sale_price"] if minimum else None,
            "history_min_at": minimum["date"] if minimum else None,
            "history_max_price": maximum["sale_price"] if maximum else None,
            "history_max_at": maximum["date"] if maximum else None,
            "observed_days": len(price_series),
        }
    return _ok({
        "label": label,
        "selected": sel,
        "as_of": timezone.localtime(last_obs).isoformat(),
        "days": days,
        "overall": overall,
        "cheapest": cheapest,
        "platforms": platforms,
        "change_2w": change_2w,
        "first_discount_at": timezone.localtime(first_disc).date().isoformat() if first_disc else None,
        "first_discount_days": (timezone.localtime(last_obs).date()
                                - timezone.localtime(first_disc).date()).days if first_disc else None,
        "max_discount_period": max_disc,
        "restock_count": restock,
        "series": series,
        "platform_series": plat_series,
        "temperature": _temp_block(term_name, days),
        "product": product,
        "price_series": price_series,
        "matched_platforms": matched_platforms,
    })


# ══════════════════════════════════════════════════════════════
#  리세일 시세 — snapshot.resale_snapshot
# ══════════════════════════════════════════════════════════════

RESALE_STYLE_MIN = 30        # 스타일로 고른 매물이 이보다 적으면 대표 브랜드로 넓힌다
STYLE_PROXY_BRANDS = 6       # 대표 브랜드 수


def _style_proxy_brands(styles, limit=STYLE_PROXY_BRANDS):
    """그 스타일에 **몰려 있는** 브랜드 — 스타일 태그 상품 수만 보면 나이키·무신사 스탠다드처럼
    상품이 많은 범용 브랜드가 모든 스타일의 대표가 된다(2026-09-20 실측: 고프코어 대표에 무신사 스탠다드).
    그래서 '그 브랜드 태그 상품 중 이 스타일 비율'(집중도) × √(이 스타일 상품 수)로 고른다. 최소 3개."""
    key = "product_source__source_brand__brand__name"
    base = ProductTerm.objects.filter(term__term_type="STYLE", product_source__market_type="RETAIL",
                                      product_source__source_brand__brand__isnull=False)
    in_style = dict(base.filter(term__canonical_name__in=styles).values_list(key)
                    .annotate(n=Count("product_source_id", distinct=True)))
    in_style = {b: n for b, n in in_style.items() if b and n >= 3}
    if not in_style:
        return []
    total = dict(base.filter(**{f"{key}__in": list(in_style)}).values_list(key)
                 .annotate(n=Count("product_source_id", distinct=True)))
    score = {b: (n / max(1, total.get(b, n))) * math.sqrt(n) for b, n in in_style.items()}
    return [b for b, _ in sorted(score.items(), key=lambda kv: -kv[1])[:limit]]


def _resale_price(r):
    for k in ("last_trade_price", "median_price", "avg_price", "min_price", "lowest_ask"):
        v = _num(r.get(k))
        if v:
            return v
    return None


@require_GET
def resale(request):
    """GET /api/resale?brand=살로몬&kind=스니커즈&term=살로몬&days=90

    가치 유지율 = 중고 거래가 ÷ 정가. 적재된 resale_price_ratio 가 있으면 그것을,
    없으면 market_metrics.regular_price(없으면 같은 표준상품의 최신 정가)로 나눈다.
    """
    sel = _selection(request)
    if not any(sel.values()):
        return _no_selection()
    days = _int(request, "days", 90, 14, 365)
    label = _selection_label(sel)
    term_name = (request.GET.get("term") or "").strip() or label
    metric_term = _selection_term(sel, term_name)

    # 리셀 매물에는 스타일·종류 태그가 안 붙어 있는 경우가 많다 →
    # 조건에 걸린 상품과 같은 표준 상품(product)으로 묶인 매물까지 함께 본다.
    matched = _selected_sources(sel)
    sources = ProductSource.objects.filter(
        Q(id__in=matched.values("id"))
        | Q(product_id__in=matched.exclude(product_id__isnull=True).values("product_id")))
    resale_src = sources.filter(Q(market_type="RESALE") | Q(resale_snapshots__isnull=False)).distinct()
    ps = list(resale_src.values("id", "product_id", "source__code", "source__name")[:5000])
    basis_note = None
    # ★ 2026-09-20 — 크림 · 무신사 유즈드 매물에는 스타일 태그가 거의 없다(크림 0 · 유즈드 5건).
    #   스타일로 고르면 매물이 몇 건뿐이라, 그 스타일로 태그된 일반 판매 상품의 **대표 브랜드**
    #   매물로 넓혀 본다. 대표 브랜드와 기준을 응답에 적어 화면·챗봇이 밝힐 수 있게 한다.
    if sel.get("style") and len(ps) < RESALE_STYLE_MIN:
        brands = _style_proxy_brands(sel["style"])
        if brands:
            proxy_sel = {**sel, "style": [], "brand": brands}
            proxy = ProductSource.objects.filter(
                Q(id__in=_selected_sources(proxy_sel).values("id")), Q(market_type="RESALE"))
            extra = list(proxy.values("id", "product_id", "source__code", "source__name")[:5000])
            have = {p["id"] for p in ps}
            ps += [p for p in extra if p["id"] not in have]
            basis_note = (f"‘{label}’ 태그가 붙은 중고·리셀 매물이 적어, 이 스타일의 대표 브랜드 "
                          f"({', '.join(brands)}) 매물로 넓혀 계산했습니다.")
    if not ps:
        return _empty(f"‘{label}’ 조건에 맞는 리셀·중고 매물이 없습니다.", label=label)
    ps_by_id = {p["id"]: p for p in ps}

    snaps = ResaleSnapshot.objects.filter(product_source_id__in=list(ps_by_id))
    last_obs = snaps.aggregate(d=Max("observed_at"))["d"]
    if last_obs is None:
        return _empty(f"‘{label}’ 매물 {len(ps)}개에 시세 스냅샷이 아직 없습니다.", label=label)
    since = last_obs - timedelta(days=max(days, 56))

    # 정가 후보 — 같은 표준상품의 일반 판매 최신 정가
    product_ids = {p["product_id"] for p in ps if p["product_id"]}
    retail_price = {}
    if product_ids:
        for r in (ProductSourceSnapshot.objects
                  .filter(product_source__product_id__in=product_ids, list_price__isnull=False)
                  .exclude(product_source__market_type="RESALE")
                  .order_by("product_source__product_id", "-observed_at")
                  .values("product_source__product_id", "list_price")):
            retail_price.setdefault(r["product_source__product_id"], _num(r["list_price"]))

    rows = list(snaps.filter(observed_at__gte=since).order_by("observed_at").values(
        "product_source_id", "observed_at", "listing_count", "available_count", "min_price",
        "max_price", "avg_price", "median_price", "sold_count", "lowest_ask", "highest_bid",
        "last_trade_price", "trade_volume", "resale_price_ratio", "resale_index",
        "market_metrics")[:60000])

    recs = []
    for r in rows:
        mm = r["market_metrics"] or {}
        price = _resale_price(r)
        regular = _num(mm.get("regular_price")) or retail_price.get(ps_by_id[r["product_source_id"]]["product_id"])
        ratio = _num(r["resale_price_ratio"])
        if ratio is None and price and regular:
            ratio = price / regular
        recs.append({
            "pid": r["product_source_id"],
            "day": timezone.localtime(r["observed_at"]).date(),
            "price": price, "regular": regular, "ratio": ratio,
            "index": _num(r["resale_index"]),
            "ask": _num(r["lowest_ask"]), "bid": _num(r["highest_bid"]),
            "trade": _num(r["last_trade_price"]),
            "volume": r["trade_volume"] if r["trade_volume"] is not None else r["sold_count"],
            "listings": r["listing_count"],
            "size": mm.get("size"), "grade": mm.get("condition_grade") or mm.get("condition_grade_raw"),
            "sold_out": mm.get("is_sold_out"),
            "platform": ps_by_id[r["product_source_id"]]["source__name"],
        })

    last_day = timezone.localtime(last_obs).date()
    win = [x for x in recs if x["day"] > last_day - timedelta(days=days)]
    wk = [x for x in recs if x["day"] > last_day - timedelta(days=7)]
    prev_wk = [x for x in recs if last_day - timedelta(days=14) < x["day"] <= last_day - timedelta(days=7)]
    m4 = [x for x in recs if x["day"] > last_day - timedelta(days=28)]
    p4 = [x for x in recs if last_day - timedelta(days=56) < x["day"] <= last_day - timedelta(days=28)]

    ratio_now = _median([x["ratio"] for x in (wk or win)])
    ratio_prev = _median([x["ratio"] for x in prev_wk])

    def vol(xs):
        v = [x["volume"] for x in xs if x["volume"] is not None]
        return sum(v) if v else None

    # 거래량이 적재되지 않으면 관측된 매물 수로 대신한다 — 어느 쪽인지 밝힌다.
    vol_now, vol_prev = vol(m4), vol(p4)
    vol_basis = "trade_volume/sold_count"
    if vol_now is None:
        vol_now, vol_prev, vol_basis = len({(x["pid"], x["day"]) for x in m4}), \
            len({(x["pid"], x["day"]) for x in p4}), "observed_listings"

    # 일별 중앙 유지율 → 프리미엄(≥1.0) 연속 일수
    by_day = defaultdict(list)
    for x in win:
        if x["ratio"] is not None:
            by_day[x["day"]].append(x["ratio"])
    series = [{"date": d.isoformat(), "ratio": round(_median(v), 4),
               "keep_pct": round(_median(v) * 100, 1)} for d, v in sorted(by_day.items())]
    prem_days = 0
    for s in reversed(series):
        if s["ratio"] >= 1:
            prem_days += 1
        else:
            break

    def group(key):
        g = defaultdict(list)
        for x in win:
            if x[key]:
                g[str(x[key])].append(x)
        total = sum(len(v) for v in g.values()) or 1
        out = [{"label": k, "count": len(v), "share_pct": round(len(v) / total * 100, 1),
                "ratio": _num(_median([y["ratio"] for y in v]), 3),
                "price": _num(_median([y["price"] for y in v]), 0)} for k, v in g.items()]
        return sorted(out, key=lambda o: -o["count"])[:12]

    asks = [x["ask"] for x in win if x["ask"]]
    trades = [x["trade"] or x["bid"] for x in win if (x["trade"] or x["bid"])]
    spread = None
    if asks and trades:
        a, t = _median(asks), _median(trades)
        spread = {"ask": round(a), "trade": round(t), "gap_pct": round((a - t) / t * 100, 1) if t else None}

    return _ok({
        "label": label,
        "selected": sel,
        "as_of": timezone.localtime(last_obs).isoformat(),
        "days": days,
        "listings": len({x["pid"] for x in win}),
        "keep_pct": round(ratio_now * 100, 1) if ratio_now is not None else None,
        "keep_change_pp": round((ratio_now - ratio_prev) * 100, 1)
        if ratio_now is not None and ratio_prev is not None else None,
        "premium": (ratio_now or 0) >= 1,
        "premium_days": prem_days,
        "used_price": _num(_median([x["price"] for x in (wk or win)]), 0),
        "regular_price": _num(_median([x["regular"] for x in (wk or win)]), 0),
        "resale_index": _num(_median([x["index"] for x in (wk or win)]), 3),
        "volume_4w": vol_now,
        "volume_change_pct": round((vol_now - vol_prev) / vol_prev * 100, 1) if vol_prev else None,
        "volume_basis": vol_basis,
        "sizes": group("size"),
        "grades": group("grade"),
        "platforms": group("platform"),
        "spread": spread,
        "basis_note": basis_note,
        "series": series,
        "temperature": _temp_block(metric_term.canonical_name if metric_term else term_name, days),
    })


# ══════════════════════════════════════════════════════════════
#  수명주기 — term_metric_daily 의 level·momentum 으로 판정
# ══════════════════════════════════════════════════════════════

LIFECYCLE_RULE = (
    "28일 이동평균(ma28)의 관측 기간 최고점 대비 현재 위치와 모멘텀(50=보합)으로 판정합니다. "
    "모멘텀 ≥ 55: 최근 7일 수준(ma7) < 35 이면 태동, 아니면 확산 / "
    "45 ≤ 모멘텀 < 55 이고 ma28 이 최고점의 85% 이상이면 정점 / "
    "그 밖(모멘텀 < 45 등)은 최고점을 지났으면 쇠퇴, 최고점 자체가 낮으면(ma7 최고 < 35) 태동. "
    "관측 28일 미만이면 판단을 보류합니다."
)


def _smooth_level(p):
    """판정에 쓰는 수준 — 하루치 level 은 드문 용어에서 0↔100 으로 튄다(2026-09-19).
    ma7 이 있으면 ma7, 없으면 level."""
    v = p.get("ma7")
    return v if v is not None else p.get("level")


def _lifecycle_stage(series):
    pts = [p for p in series if p.get("level") is not None or p.get("ma28") is not None]
    if len(pts) < 28:
        return None, None, None
    last = pts[-1]
    lvl = _smooth_level(last) or 0
    mom = last.get("momentum")
    ma = [p.get("ma28") for p in pts if p.get("ma28") is not None]
    peak = max(ma) if ma else None
    now = ma[-1] if ma else None
    ratio = (now / peak) if (peak and now is not None) else None
    peak_i = max(range(len(pts)), key=lambda i: pts[i].get("ma28") or -1)
    after_peak = peak_i < len(pts) - 1 and ratio is not None and ratio < 0.999
    max_level = max((_smooth_level(p) or 0) for p in pts)

    if mom is None:
        stage = None
    elif mom >= 55:
        stage = "태동" if lvl < 35 else "확산"
    elif mom >= 45 and ratio is not None and ratio >= 0.85:
        stage = "정점"
    elif max_level < 35:
        stage = "태동"
    else:
        stage = "쇠퇴"

    # 유행 진행도(0~100): 최고점 전에는 0~50, 지난 뒤에는 50~100
    progress = None
    if ratio is not None:
        progress = round(ratio * 50) if (not after_peak or stage in ("태동", "확산")) \
            else round(50 + (1 - ratio) * 50)
    return stage, progress, pts[peak_i]["date"]


@require_GET
def lifecycle(request):
    """GET /api/lifecycle?style=고프코어&term=고프코어"""
    sel = _selection(request)
    label = _selection_label(sel)
    term_name = (request.GET.get("term") or "").strip() or label
    if not term_name:
        return _no_selection()
    term = _selection_term(sel, term_name)
    if term is None:
        return _empty(_term_missing_reason(term_name), label=label or term_name)
    rows, _ = _term_series(term, 365)
    basis = None
    if len(rows) < HISTORY_MIN_POINTS:
        hist = _history_series(term, 365)
        if len(hist) > len(rows):
            rows, basis = hist, HISTORY_BASIS
    if not rows:
        return _empty(f"‘{term.canonical_name}’ 의 트렌드 지표가 아직 없습니다.", label=label)
    series = [_metric_point(r) for r in rows]
    stage, progress, peak_date = _lifecycle_stage(series)

    last = series[-1]
    last_day = rows[-1]["metric_date"]

    def sum_mention(a, b):
        return sum(p["mention"] or 0 for p in series
                   if last_day - timedelta(days=a) < timezone.datetime.fromisoformat(p["date"]).date()
                   <= last_day - timedelta(days=b))

    m_now, m_prev = sum_mention(28, 0), sum_mention(56, 28)
    first_active = next((p["date"] for p in series if (p.get("level") or 0) >= 20), series[0]["date"])
    age_weeks = (last_day - timezone.datetime.fromisoformat(first_active).date()).days // 7

    # 주별 온도 (최근 12주)
    weekly = defaultdict(list)
    for p in series:
        d = timezone.datetime.fromisoformat(p["date"]).date()
        if d > last_day - timedelta(weeks=12) and p["temp"] is not None:
            weekly[(last_day - d).days // 7].append(p["temp"])
    weekly_temp = [{"weeks_ago": k, "temp": round(_mean(v), 1)} for k, v in sorted(weekly.items())]

    # 판매 신호 — 선택 조건 상품의 일별 판매수 증가분 합
    sales = []
    if any(sel.values()):
        ps_ids = list(_selected_sources(sel).values_list("id", flat=True)[:3000])
        if ps_ids:
            prev, daily = {}, defaultdict(int)
            for r in (ProductSourceSnapshot.objects
                      .filter(product_source_id__in=ps_ids, sales_count__isnull=False,
                              observed_at__date__gte=last_day - timedelta(days=365))
                      .order_by("product_source_id", "observed_at")
                      .values("product_source_id", "observed_at", "sales_count")[:80000]):
                pid, v = r["product_source_id"], r["sales_count"]
                if pid in prev and v >= prev[pid]:
                    daily[timezone.localtime(r["observed_at"]).date().isoformat()] += v - prev[pid]
                prev[pid] = v
            sales = [{"date": d, "sales": v} for d, v in sorted(daily.items())]

    return _ok({
        "label": label or term.canonical_name,
        "term": term.canonical_name,
        "facet": term.term_type,
        "as_of": last["date"],
        "points": len(series),
        "basis": basis,
        "stage": stage,
        "progress": progress,
        "peak_date": peak_date,
        "age_weeks": age_weeks,
        "level": last["level"],
        "momentum": last["momentum"],
        "temp": last["temp"],
        "inflow_pct": round((m_now - m_prev) / m_prev * 100, 1) if m_prev else None,
        "mention_28d": m_now,
        "weekly_temp": weekly_temp,
        "series": series,
        "sales_series": sales,
        "rule": LIFECYCLE_RULE,
    })


# ══════════════════════════════════════════════════════════════
#  상품 · 살!말? (챗봇이 쓰는 창구 — 새 스키마에 맞춤)
# ══════════════════════════════════════════════════════════════

@require_GET
def products(request):
    """GET /api/products?style=고프코어&limit=16&offset=0 — 태그된 상품 목록.

    스타일은 자동 태깅 결과(`commerce.product_term` · term_type='STYLE')로 고른다.
    한 상품에 스타일이 여러 개 달릴 수 있어, 그중 하나라도 맞으면 포함한다.
    화면에서 쓸 수 있게 원본 상품 이미지와 최신 가격도 같이 돌려준다.
    """
    kw = (request.GET.get("q") or "").strip()
    brand = (request.GET.get("brand") or "").strip()
    limit = _int(request, "limit", 40, 1, 200)
    offset = _int(request, "offset", 0, 0, 1_000_000)
    sel = _selection(request)
    # brand 는 기존 API 의 영문 대소문자 무시 동작을 유지하려고 아래에서 따로 건다.
    product_sel = {**sel, "brand": []}
    qs = _selected_sources(product_sel).filter(status="ACTIVE").distinct()
    if kw:
        qs = qs.filter(Q(source_name__icontains=kw) | Q(product__canonical_name__icontains=kw))
    if brand:
        qs = qs.filter(Q(product__brand__name=brand) | Q(product__brand__english_name__iexact=brand)
                       | Q(source_brand__name=brand) | Q(source_brand__brand__name=brand))
    # 정렬 — 값은 모두 최신 스냅샷 한 줄에서 온다. 값이 없는 상품은 어느 정렬이든 맨 뒤.
    # recommend(FEEDiT 추천순): 리뷰·좋아요·판매량(로그) + 평점 + 할인율 + 이미지·가격 보유 가산점.
    # 계산식은 api/products.js(Node) 와 같게 유지한다.
    sort = (request.GET.get("sort") or "latest").strip()
    snap = ProductSourceSnapshot.objects.filter(product_source_id=OuterRef("pk")).order_by("-observed_at")

    def last(field):
        return Cast(Subquery(snap.values(field)[:1]), FloatField())

    zero = Value(0.0, output_field=FloatField())
    extra = {"_price": Cast(Subquery(snap.annotate(_p=Coalesce("sale_price", "list_price")).values("_p")[:1]),
                            FloatField())}
    tail = ("-last_seen_at", "-id")
    simple = {"reviews": "review_count", "rating": "rating", "likes": "like_count", "sales": "sales_count"}
    if sort == "price_desc":
        ordering = (F("_price").desc(nulls_last=True), "-id")
    elif sort == "price_asc":
        ordering = (F("_price").asc(nulls_last=True), "-id")
    elif sort in simple:
        extra["_key"] = last(simple[sort])
        ordering = (F("_key").desc(nulls_last=True),) + (
            (F("_rv").desc(nulls_last=True),) if sort == "rating" else ()) + tail
        if sort == "rating":
            extra["_rv"] = last("review_count")
    elif sort in ("discount", "recommend"):
        extra["_dc_raw"] = last("discount_rate")
        disc = Case(When(_dc_raw__lte=1, then=F("_dc_raw") * 100), default=F("_dc_raw"), output_field=FloatField())
        if sort == "discount":
            extra["_key"] = disc
            ordering = (F("_key").desc(nulls_last=True),) + tail
        else:
            extra.update({"_rv": last("review_count"), "_lk": last("like_count"),
                          "_sl": last("sales_count"), "_rt": last("rating")})
            extra["_key"] = (
                Coalesce(Ln(F("_rv") + 1.0), zero) * 1.0
                + Coalesce(Ln(F("_lk") + 1.0), zero) * 0.8
                + Coalesce(Ln(F("_sl") + 1.0), zero) * 0.8
                + Coalesce(F("_rt"), zero) * 0.6
                + Coalesce(disc, zero) * 0.03
                + Case(When(thumbnail_url__isnull=False, then=Value(0.5)), default=zero, output_field=FloatField())
                + Case(When(_price__isnull=False, then=Value(0.5)), default=zero, output_field=FloatField())
            )
            ordering = (F("_key").desc(),) + tail
    else:
        ordering = tail
    sort_fields = [k for k in extra]
    rows = list(qs.annotate(
        **extra,
        _brand=BRAND_EXPR,
        _name=ITEM_EXPR,
        _category=Coalesce(
            "product__category__name",
            "source_category__category__name",
            "source_category__source_category_name",
        ),
    ).values(
        "id", "product_id", "_name", "_brand", "_category", "source__code",
        "product_url", "thumbnail_url", "market_type", *sort_fields,
    ).order_by(*ordering)[offset:offset + limit + 1])
    if not rows:
        label = kw or brand or (sel["style"] or [None])[0]
        return _empty(f"조건에 맞는 상품이 없습니다 (검색어 ‘{label}’)."
                      if label else "commerce.product_source 가 비어 있습니다.")
    has_more = len(rows) > limit
    rows = rows[:limit]
    total = qs.count()   # '더 보기' 버튼이 "24 / 312" 를 보여 주려면 전체 개수가 필요하다
    snaps = {}
    for s in (ProductSourceSnapshot.objects.filter(product_source_id__in=[r["id"] for r in rows])
              .order_by("product_source_id", "-observed_at")
              .values("product_source_id", "list_price", "sale_price", "discount_rate",
                      "stock_status", "observed_at")):
        snaps.setdefault(s["product_source_id"], s)
    items = []
    for r in rows:
        s = snaps.get(r["id"])
        items.append({
            "id": r["product_id"] or r["id"], "product_source_id": r["id"],
            "name": r["_name"], "brand": r["_brand"], "source": r["source__code"],
            "url": r["product_url"], "image": r["thumbnail_url"],
            "category": r["_category"], "market": r["market_type"],
            "price": {
                "list": _num(s["list_price"]) if s else None,
                "sale": _num(s["sale_price"]) if s else None,
                "discount": _pct(s["discount_rate"]) if s else None,
                "stock": s["stock_status"] if s else None,
                "as_of": s["observed_at"] if s else None,
                "unavailable": None if s else "이 상품은 아직 가격 스냅샷이 없습니다.",
            },
        })
    return _ok({
        "count": len(items),
        "items": items,
        "offset": offset,
        "next_offset": offset + len(items),
        "has_more": has_more,
        "total": total,
        "style": sel["style"],
    })


@require_GET
def price_history(request):
    """GET /api/price-history?ids=17,18,19 — 찜한 상품들의 가격 기록 요약.

    트렌드 분석 › 찜한 키워드 화면이 '최저가'를 실값으로 그리려고 부른다.
    ids 는 commerce.product_source.id (스타일 페이지 상품 카드의 product_source_id).
    가격은 판매가, 없으면 정가를 쓴다. 스냅샷이 없는 상품은 결과에서 빠진다 —
    0원이나 추정값으로 채우지 않는다.
    """
    raw = (request.GET.get("ids") or "").replace(" ", "")
    ids = []
    for x in raw.split(","):
        if x.isdigit() and int(x) not in ids:
            ids.append(int(x))
    ids = ids[:100]
    if not ids:
        return _empty("ids 가 비어 있습니다 (예: ?ids=17,18).")

    out = {}
    rows = (ProductSourceSnapshot.objects.filter(product_source_id__in=ids)
            .order_by("product_source_id", "observed_at")
            .values("product_source_id", "list_price", "sale_price", "observed_at"))
    for r in rows:
        price = _num(r["sale_price"]) if r["sale_price"] is not None else _num(r["list_price"])
        if price is None:
            continue
        d = out.setdefault(str(r["product_source_id"]), {
            "points": 0, "min": price, "max": price, "min_at": r["observed_at"],
            "first_at": r["observed_at"], "current": price, "current_at": r["observed_at"],
            "previous": None, "list": None,
        })
        d["points"] += 1
        if price < d["min"]:
            d["min"], d["min_at"] = price, r["observed_at"]
        d["max"] = max(d["max"], price)
        if d["points"] > 1:
            d["previous"] = d["current"]
        d["current"], d["current_at"] = price, r["observed_at"]
        d["list"] = _num(r["list_price"])
    if not out:
        return _empty("요청한 상품들에 가격 스냅샷이 아직 없습니다.", ids=ids)
    return _ok({"count": len(out), "items": out})


def _salmal_card_payload(card):
    product = card.product
    ballots = VoteBallot.objects.filter(card_id=card.id)
    total = ballots.count()
    buys = ballots.filter(choice=VoteBallot.Choice.BUY).count()
    tags = [str(x).strip() for x in (card.tags or []) if str(x).strip()]
    product_tags, price = [], None
    if product is not None:
        product_tags = list(ProductTerm.objects.filter(product_source__product_id=product.id)
                            .values_list("term__canonical_name", flat=True).distinct()[:20])
        latest = (ProductSourceSnapshot.objects.filter(product_source__product_id=product.id)
                  .order_by("-observed_at")
                  .values("list_price", "sale_price", "discount_rate", "stock_status", "observed_at")
                  .first())
        if latest:
            price = {"list_price": _num(latest["list_price"]), "sale_price": _num(latest["sale_price"]),
                     "discount_rate": _pct(latest["discount_rate"]),
                     "stock_status": latest["stock_status"], "observed_at": latest["observed_at"]}
    return {
        "card": {"id": card.id, "title": card.title, "description": card.description,
                 "image_url": card.image_url, "tags": tags, "status": card.status,
                 "created_at": card.created_at},
        "product": (None if product is None else {
            "id": product.id, "name": product.canonical_name,
            "brand": product.brand.name if product.brand_id else None,
            "category": product.category.name if product.category_id else None,
            "tags": list(dict.fromkeys([*tags, *product_tags])),
        }),
        "vote_summary": {"total": total, "buy": buys, "pass": total - buys,
                         "buy_pct": (round(buys / total * 100, 1) if total else None),
                         "closed": card.status == VoteCard.Status.CLOSED},
        "price_snapshot": price,
        "as_of": timezone.now().isoformat(),
    }


@require_GET
def salmal_card(request):
    card_id = _int(request, "card_id", 0, 0, 2_147_483_647)
    if not card_id:
        return _empty("card_id를 지정해 주세요.")
    card = VoteCard.objects.filter(id=card_id).select_related(
        "product", "product__brand", "product__category").first()
    if card is None:
        return _empty("해당 살!말? 카드를 찾지 못했습니다.", card_id=card_id)
    return _ok(_salmal_card_payload(card))


@require_GET
def salmal_search(request):
    term = (request.GET.get("term") or "").strip()
    if not term:
        return _empty("term을 지정해 주세요.")
    limit = _int(request, "limit", 5, 1, 10)
    cards = (VoteCard.objects.filter(Q(title__icontains=term)
                                     | Q(product__canonical_name__icontains=term)
                                     | Q(product__brand__name__icontains=term))
             .select_related("product", "product__brand", "product__category")
             .order_by("-created_at")[:limit])
    rows = [_salmal_card_payload(c) for c in cards]
    if not rows:
        return _empty(f"‘{term}’{josa(term, '과', '와')} 연결된 살!말? 카드가 없습니다.", term=term)
    return _ok({"term": term, "items": rows, "count": len(rows)})
