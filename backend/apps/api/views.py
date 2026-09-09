"""프론트가 부르는 읽기 전용 API.

── 왜 이게 필요한가 ─────────────────────────────────────────
프론트(Vercel)는 RDS 에 직접 못 붙는다. RDS 는 사설이고 SSM 굴로만 열린다.
그래서 **RDS 를 인터넷에 여는 대신** 이미 RDS 에 닿는 이 Django 가
읽기 전용 창구를 내주고, 프론트는 그걸 부른다.

    브라우저 ─▶ Vercel 함수 ─▶ 이 API ─▶ RDS

── 지키는 것 ────────────────────────────────────────────────
① **쓰지 않는다.** 전부 GET 이고 조회만 한다.
② **지표를 계산하지 않는다.** 온도·모멘텀의 정의는
   `FEEDiT_지표계산_설계서.md` 가 원본이고 계산은 수집·정제 쪽이 한다.
   여기서 다시 계산하면 화면과 챗봇이 다른 숫자를 말하게 된다.
③ **없는 값을 지어내지 않는다.** 값이 없으면 `status:"empty"` 와
   **왜 없는지**를 함께 돌려준다. 화면은 그 자리를 '측정 불가'로 그린다.

   ok    값이 있다
   empty 붙었는데 값이 없다   ← 기다릴 일
   (연결 실패는 프론트 쪽 Vercel 함수가 error 로 가른다)
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Max
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.core.models import (
    Brand,
    DictionaryTerm,
    Product,
    ProductTerm,
    TermAssocDaily,
    TermMetricDaily,
)

# 설계서 §1 의 값들. RDS 에 아직 안 들어왔으면 None 으로 나가고,
# 화면은 그 자리를 '측정 불가'로 그린다.
METRIC_FIELDS = ("temp", "momentum", "ma7", "ma28", "level", "pct_rank")

MAX_LIMIT = 500


def _ok(data, **extra):
    return JsonResponse({"status": "ok", **extra, "data": data})


def _empty(reason, **extra):
    return JsonResponse({"status": "empty", "reason": reason, **extra, "data": None})


def _num(v):
    return None if v is None else float(v)


def _int(request, name, default, lo, hi):
    try:
        return max(lo, min(hi, int(request.GET.get(name, default))))
    except (TypeError, ValueError):
        return default


def _column_mismatch():
    """모델에는 있는데 실제 DB 표에는 없는 칸을 찾는다.

    ★ 왜 이걸 보나
      2026-09-07 에 `/api/trend` 가 통째로 500 이 났다:
          column dictionary_term.normalized_name does not exist
      모델·마이그레이션에는 있는데 실제 표에 없었다. Django 는
      "No migrations to apply" 라고 하므로 **아무도 모른 채 지나간다.**
      이런 어긋남은 쿼리를 날려 봐야 터지는데, 그때는 이미 화면이 깨진 뒤다.
      여기서 먼저 알려 준다.

    ★ 2026-09-09 — 이 진단 자체가 거짓 경보를 내고 있었다.
      우리 표 이름은 스키마까지 붙은 `"dictionary"."dictionary_term"` 이다.
      따옴표만 지우면 `dictionary.dictionary_term` 이라는 **한 덩어리 문자열**이
      되고, Django 는 그걸 통째로 한 이름으로 인용해 물어본다:
          SELECT * FROM "dictionary.dictionary_term" LIMIT 1
          → relation "dictionary.dictionary_term" does not exist
      표는 멀쩡히 있는데(같은 응답의 tables 가 407행을 세고 있었다)
      "★ 모델과 실제 DB 가 어긋납니다" 가 떴다. 없는 문제를 쫓게 만든다.
      그래서 스키마와 표 이름을 갈라서 information_schema 에 직접 묻는다.
    """
    from django.db import connection

    out = {}
    with connection.cursor() as c:
        for model in (DictionaryTerm, TermMetricDaily, TermAssocDaily, Product):
            raw = model._meta.db_table.replace('"', "")
            schema, _, tbl = raw.rpartition(".")
            try:
                if schema:
                    c.execute(
                        """SELECT column_name FROM information_schema.columns
                             WHERE table_schema = %s AND table_name = %s""",
                        [schema, tbl],
                    )
                    have = {r[0] for r in c.fetchall()}
                else:
                    # 스키마가 없는 표는 예전 방식 그대로 (SQLite 에서도 돈다)
                    have = {
                        d.name
                        for d in connection.introspection.get_table_description(c, raw)
                    }
            except Exception as exc:      # noqa: BLE001 - 진단이 실패해도 health 는 떠야 한다
                out[raw] = {"missing": ["(표를 못 읽음)"], "error": str(exc)[:120]}
                continue
            table = raw
            if not have:
                out[table] = {"missing": ["(표 자체가 없음)"]}
                continue
            gap = sorted({f.column for f in model._meta.concrete_fields} - have)
            if gap:
                out[table] = {"missing": gap}
    return out


@require_GET
def health(request):
    """붙었는지, 어느 표에 몇 행이 있는지, 모델과 어긋나지 않는지.

    배포한 뒤 이 주소를 열면 추측 없이 실상이 보인다.
    """
    counts = {
        "dictionary.dictionary_term": DictionaryTerm.objects.count(),
        "commerce.product": Product.objects.count(),
        "analysis.term_metric_daily": TermMetricDaily.objects.count(),
        "analysis.term_assoc_daily": TermAssocDaily.objects.count(),
    }
    latest = TermMetricDaily.objects.aggregate(d=Max("metric_date"))["d"]

    bits = []
    if not counts["analysis.term_metric_daily"]:
        bits.append(
            "트렌드 지표가 0행입니다. 수집·정제 쪽에서 analysis.term_metric_daily "
            "적재가 아직 안 돌았습니다."
        )
    else:
        bits.append(f"트렌드 지표 {counts['analysis.term_metric_daily']:,}행 (최신 {latest}).")

    # 온도가 실제로 채워졌는지 — 행은 있는데 온도만 비는 경우를 잡는다.
    if counts["analysis.term_metric_daily"]:
        filled = TermMetricDaily.objects.filter(temp__isnull=False).count()
        bits.append(
            f"그중 온도가 채워진 행 {filled:,}건."
            if filled
            else "다만 temp 가 전부 비어 있습니다 — 적재 때 온도를 안 넣고 있습니다."
        )

    mismatch = _column_mismatch()
    if mismatch:
        bits.insert(
            0,
            "★ 모델과 실제 DB 가 어긋납니다 — "
            + " / ".join(
                f"{tbl}: {', '.join(v.get('missing') or [v.get('error', '?')])}"
                for tbl, v in mismatch.items()
            )
            + ". 이 상태로 조회하면 쓰지도 않는 칸 때문에 500 이 납니다. "
            "migrate 를 다시 돌리거나, DB 를 손으로 고쳤다면 모델과 맞춰 주세요.",
        )

    return JsonResponse(
        {
            "ok": True,
            "checked_at": timezone.now().isoformat(),
            "tables": counts,
            "latest_metric_date": latest,
            "column_mismatch": mismatch or None,
            "verdict": " ".join(bits),
        }
    )


@require_GET
def terms(request):
    """지표가 실제로 있는 용어 목록 — 화면의 검색 후보."""
    qs = (
        TermMetricDaily.objects.filter(source__isnull=True)  # 전체 합산 행만
        .values("term__canonical_name", "term__term_type")
        .annotate(points=Count("id"), last_date=Max("metric_date"))
        .filter(points__gte=3)
        .order_by("-points")[: _int(request, "limit", 300, 1, MAX_LIMIT)]
    )
    rows = list(qs)
    if not rows:
        return _empty(
            "지표가 있는 용어가 아직 없습니다. "
            "analysis.term_metric_daily 적재가 돌면 여기에 나타납니다."
        )
    return _ok(
        [
            {
                "term": r["term__canonical_name"],
                "facet": r["term__term_type"],
                "points": r["points"],
                "last_date": r["last_date"],
            }
            for r in rows
        ]
    )


# 우리 term_type ↔ 화면이 쓰는 축 이름
FACET_KO = {
    "BRAND": "브랜드", "STYLE": "스타일", "ITEM": "아이템",
    "MATERIAL": "소재", "DETAIL": "디테일", "COLOR": "색", "TPO": "TPO",
}


@require_GET
def dictionary(request):
    """GET /api/dictionary — 화면 검색이 쓸 사전 전체.

    ★ 왜 필요한가
      프론트는 지금 자기 파일에 박아 둔 146개로만 검색한다. 그래서
      **RDS 사전에 있는 말도 "찾지 못했습니다"** 가 된다.
      실제로 스투시·키르시·엄브로가 그랬다.

    ★ 브랜드는 다른 표에 산다
      `dictionary_term` 에는 스타일·아이템·소재·색·디테일·TPO 가 들어 있고,
      **브랜드는 `dictionary.brand` 에 따로 있다**(2026-09-08 기준 term 395 · brand 2,775).
      화면에서는 둘 다 '검색해서 지표를 볼 대상' 이므로 여기서 합쳐 준다.
      어디서 왔는지는 `kind` 로 남겨, 나중에 지표가 없을 때 이유를 정확히 말할 수 있게 한다.
    """
    limit = _int(request, "limit", 4000, 1, 8000)

    rows = [
        {
            "label": r["canonical_name"],
            "facet": FACET_KO.get(r["term_type"], r["term_type"]),
            "kind": "term",
            "en": r["english_name"] or "",
        }
        for r in DictionaryTerm.objects.filter(status="ACTIVE").values(
            "canonical_name", "term_type", "english_name"
        )[:limit]
    ]
    # ★ Brand 는 `name` 을 쓴다. `canonical_name` 이 아니다 —
    #   마이그레이션 0014 가 그 칸을 지웠다. 이름이 표마다 다르다.
    rows += [
        {"label": r["name"], "facet": "브랜드", "kind": "brand",
         "en": r["english_name"] or ""}
        for r in Brand.objects.filter(status="ACTIVE").values("name", "english_name")[:limit]
        if r["name"]
    ]

    if not rows:
        return _empty("사전이 비어 있습니다. dictionary_term·brand 적재를 확인하세요.")

    by_facet = {}
    for r in rows:
        by_facet[r["facet"]] = by_facet.get(r["facet"], 0) + 1
    return _ok(rows, counts=by_facet, total=len(rows))


@require_GET
def trend(request):
    """GET /api/trend?term=발레코어&days=90&source=musinsa

    source 를 주면 그 플랫폼만, 안 주면 전 플랫폼 합산.
    """
    name = (request.GET.get("term") or "").strip()
    if not name:
        return terms(request)

    days = _int(request, "days", 90, 7, 400)
    source = (request.GET.get("source") or "").strip()
    since = timezone.localdate() - timedelta(days=days)

    qs = TermMetricDaily.objects.filter(
        term__canonical_name=name, metric_date__gte=since
    )
    qs = qs.filter(source__code=source) if source else qs.filter(source__isnull=True)
    # ★ select_related 를 쓰지 않는다.
    #   그러면 DictionaryTerm 의 **모든 칸**을 SELECT 하는데, 실제 DB 에
    #   모델에만 있는 칸(예: normalized_name)이 없으면 통째로 500 이 난다.
    #   2026-09-07 실제로 그랬다:
    #     ProgrammingError: column dictionary_term.normalized_name does not exist
    #   쓰지도 않는 칸 때문에 API 가 죽으면 안 된다. 필요한 것만 집어 온다.
    rows = list(
        qs.order_by("metric_date").values(
            "metric_date", "mention_count", "document_count", "source_count",
            "sentiment_avg", "growth_rate", "trend_score", "metrics",
            "metric_version", "temp", "momentum", "ma7", "ma28", "level", "pct_rank",
            "term__canonical_name", "term__term_type",
        )
    )

    if not rows:
        # ★ '사전에 없다' 를 함부로 말하지 않는다.
        #   브랜드는 dictionary_term 이 아니라 brand 표에 산다. 거기만 보고
        #   "사전에서 찾지 못했습니다" 라고 하면 거짓말이 된다 —
        #   실제로 스투시가 그랬다(브랜드 표에는 있다).
        as_term = DictionaryTerm.objects.filter(canonical_name=name).exists()
        as_brand = Brand.objects.filter(name=name).exists()
        if as_term:
            reason = f"‘{name}’ 은 사전에 있지만 최근 {days}일 안에 측정된 지표가 없습니다."
        elif as_brand:
            reason = (
                f"‘{name}’ 은 브랜드 사전에는 있지만, 아직 지표 대상 용어로 "
                f"등록돼 있지 않습니다. 브랜드를 dictionary_term 에도 넣어야 "
                f"온도를 잴 수 있습니다."
            )
        else:
            reason = f"‘{name}’ 을 사전에서 찾지 못했습니다."
        return _empty(reason, term=name, known=as_term or as_brand,
                      found_in=("term" if as_term else "brand" if as_brand else None))

    series = [
        {
            "date": r["metric_date"],
            "mention": r["mention_count"],
            "document": r["document_count"],
            "source": r["source_count"],
            "sentiment": _num(r["sentiment_avg"]),
            "growth": _num(r["growth_rate"]),
            "score": _num(r["trend_score"]),
            **{f: _num(r.get(f)) for f in METRIC_FIELDS},
            # 크롤러가 metrics JSON 에 담아 보낸 값도 꺼내 준다.
            **{k: _num(v) for k, v in (r.get("metrics") or {}).items()
               if k in ("share_pct", "raw_count", "log_value")},
        }
        for r in rows
    ]

    # 아직 안 들어온 값이 있으면 숨기지 않고 알려 준다.
    last = series[-1]
    missing = [f for f in METRIC_FIELDS if last.get(f) is None]
    extra = {}
    if missing:
        extra["unavailable"] = {
            "fields": missing,
            "reason": (
                f"이 값들이 아직 비어 있습니다 ({'·'.join(missing)}). "
                "적재할 때 크롤러가 계산해 둔 값을 그대로 넣어야 채워집니다."
            ),
        }

    return _ok(
        {
            "term": rows[0]["term__canonical_name"],
            "facet": rows[0]["term__term_type"],
            "source": source or None,
            "days": days,
            "points": len(series),
            "metric_version": rows[-1]["metric_version"] or None,
            "series": series,
        },
        **extra,
    )


@require_GET
def assoc(request):
    """GET /api/assoc?term=발레코어&limit=20 — 연관어."""
    name = (request.GET.get("term") or "").strip()
    if not name:
        return _empty("term 을 지정해 주세요. 예: /api/assoc?term=발레코어")

    limit = _int(request, "limit", 20, 5, 100)
    latest = (
        TermAssocDaily.objects.filter(source_term__canonical_name=name)
        .aggregate(d=Max("metric_date"))["d"]
    )
    if latest is None:
        total = TermAssocDaily.objects.count()
        return _empty(
            (
                "연관어 표가 통째로 비어 있습니다. 적재가 아직 안 돌았습니다."
                if total == 0
                else f"‘{name}’ 의 연관어가 아직 없습니다. 함께 나온 글이 모자랍니다."
            ),
            term=name,
            total_rows=total,
        )

    rows = (
        TermAssocDaily.objects.filter(
            source_term__canonical_name=name, metric_date=latest
        )
        .order_by("-association_score", "-cooccurrence_count")
        .values(
            "cooccurrence_count", "association_score", "confidence",
            "target_term__canonical_name", "target_term__term_type",
        )[:limit]
    )
    return _ok(
        {
            "term": name,
            "as_of": latest,
            "items": [
                {
                    "term": r["target_term__canonical_name"],
                    "facet": r["target_term__term_type"],
                    "cooccurrence": r["cooccurrence_count"],
                    "score": _num(r["association_score"]),
                    "confidence": _num(r["confidence"]),
                }
                for r in rows
            ],
        }
    )


@require_GET
def products(request):
    """GET /api/products?q=엄브로&brand=UMBRO&limit=40

    가격은 가장 최근 스냅샷을 붙인다.
    스냅샷이 없으면 0 으로 채우지 않는다 — 0 은 '공짜'라는 뜻이 되어 버린다.
    """
    kw = (request.GET.get("q") or "").strip()
    brand = (request.GET.get("brand") or "").strip()
    limit = _int(request, "limit", 40, 1, 200)

    # select_related 는 Brand 의 모든 칸을 SELECT 한다 — trend 와 같은 이유로 피한다.
    qs = Product.objects.prefetch_related("sources")
    if kw:
        qs = qs.filter(canonical_name__icontains=kw)
    if brand:
        # Brand 는 name / english_name 이다 (canonical_name 은 0014 에서 지워졌다).
        qs = qs.filter(brand__name=brand) | qs.filter(brand__english_name=brand)

    rows = list(qs.order_by("-id")[:limit])
    if not rows:
        return _empty(
            f"조건에 맞는 상품이 없습니다 (검색어 ‘{kw or brand}’)."
            if (kw or brand)
            else "commerce.product 가 비어 있습니다."
        )

    # 브랜드 이름만 따로 한 번에 가져온다 (칸을 콕 집어서).
    from apps.core.models import Brand
    brand_names = dict(
        Brand.objects.filter(id__in=[p.brand_id for p in rows if p.brand_id])
        .values_list("id", "name")
    )

    items = []
    no_price = 0
    for p in rows:
        ps = next(iter(p.sources.all()), None)
        snap = (
            ps.snapshots.order_by("-observed_at").first() if ps is not None else None
        )
        if snap is None:
            no_price += 1
        items.append(
            {
                "id": p.id,
                "name": p.canonical_name,
                "brand": brand_names.get(p.brand_id),
                "source": ps.source.code if ps and ps.source_id else None,
                "url": ps.product_url if ps else None,
                "market": ps.market_type if ps else None,
                "price": {
                    "list": _num(snap.list_price) if snap else None,
                    "sale": _num(snap.sale_price) if snap else None,
                    "discount": _num(snap.discount_rate) if snap else None,
                    "stock": snap.stock_status if snap else None,
                    "as_of": snap.observed_at if snap else None,
                    "unavailable": None if snap else "이 상품은 아직 가격 스냅샷이 없습니다.",
                },
            }
        )

    extra = {"note": f"{no_price}건은 가격 기록이 아직 없습니다."} if no_price else {}
    return _ok({"count": len(items), "items": items}, **extra)


# ══════════════════════════════════════════════════════════════
#  세부 검색 — 축별 필터 후보 (2026-09-09)
# ══════════════════════════════════════════════════════════════
#  ★ 왜 새로 만들었나
#    화면의 세부 검색은 스타일 › 종류 › 브랜드 › 아이템명 을 **위에서부터
#    차례로 좁히는** 방식이었다. 그래서 브랜드만 알고 있어도 스타일부터
#    골라야 했고, 그 계층은 프론트 파일에 손으로 박아 둔 것이라 RDS 와
#    아무 상관이 없었다.
#
#    이제는 네 칸이 **서로 독립된 필터**다. 하나만 골라도 되고, 겹쳐 골라도
#    된다. 겹쳐 고르면 교집합이다 — 스타일만 고르면 그 스타일 전부,
#    브랜드까지 고르면 그 스타일의 그 브랜드만.
#
#  ★ 무엇을 세는가
#    계층의 근거는 `commerce.product` 다. 상품 한 줄이 브랜드·종류(item_term)를
#    들고 있고, `commerce.product_term` 이 그 상품에 붙은 스타일을 들고 있다.
#    그래서 "이 스타일에 실제로 있는 브랜드" 를 지어내지 않고 셀 수 있다.
#
#  ★ 자기 축은 자기를 좁히지 않는다
#    브랜드 후보를 셀 때 브랜드 선택은 빼고 센다. 그러지 않으면 브랜드를
#    하나 고르는 순간 브랜드 칸에 그것 하나만 남아, 칩을 바꿔 낄 수가 없다.
#    (패싯 검색의 기본 규칙이다.)
#
#  ★ 상품이 아직 없으면
#    `commerce.product` 가 비어 있으면 교차 계산은 의미가 없다. 그때는
#    사전(dictionary_term · brand)만 그대로 내려보내고 `narrowed:false` 로
#    **좁히지 못했다는 사실을 밝힌다.** 화면은 그걸 그대로 적는다.

FACET_PARAMS = ("style", "kind", "brand", "item")

# ★ 상품이 이만큼은 있어야 "축끼리 좁혔다" 고 말할 수 있다.
#   2026-09-09 실측: commerce.product 에 **1행**밖에 없었다. 그 상태로 교차
#   계산을 하면 스타일 칸에도 브랜드 칸에도 한 개씩만 남는다. 틀린 답은
#   아니지만, 화면에서는 "고를 게 없는 고장" 으로 보인다.
#   상품이 이 수보다 적으면 좁히기를 포기하고 사전을 그대로 준다 —
#   그리고 narrowed:false 로 **좁히지 못했다는 사실을 밝힌다.**
MIN_PRODUCTS_FOR_FACETS = 20


def _list(request, name):
    """?style=A&style=B → ['A','B'] (빈 값·중복 제거)"""
    out, seen = [], set()
    for v in request.GET.getlist(name):
        v = (v or "").strip()
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _apply(qs, sel, skip=None):
    """고른 조건을 상품 목록에 건다. `skip` 축 하나는 뺀다(자기 축 제외)."""
    if skip != "style" and sel["style"]:
        qs = qs.filter(
            id__in=ProductTerm.objects.filter(
                term__term_type="STYLE",
                term__canonical_name__in=sel["style"],
            ).values("product_id")
        )
    if skip != "kind" and sel["kind"]:
        qs = qs.filter(item_term__term__canonical_name__in=sel["kind"])
    if skip != "brand" and sel["brand"]:
        qs = qs.filter(brand__name__in=sel["brand"])
    if skip != "item" and sel["item"]:
        qs = qs.filter(canonical_name__in=sel["item"])
    return qs


def _rows(qs, field, keep, limit):
    """축 하나의 후보 — 값과 상품 수. 많이 걸리는 것부터."""
    agg = (
        qs.exclude(**{field + "__isnull": True})
        .exclude(**{field: ""})
        .values(field)
        .annotate(n=Count("id"))
        .order_by("-n", field)
    )
    out = []
    for r in agg:
        label = r[field]
        if not label:
            continue
        out.append({"label": label, "count": r["n"]})
        if len(out) >= limit:
            break
    # 이미 고른 것은 후보에서 밀려나도 남긴다 — 그래야 칩을 다시 뺄 수 있다.
    have = {o["label"] for o in out}
    for k in keep:
        if k not in have:
            out.append({"label": k, "count": 0, "picked_only": True})
    return out


def _style_rows(qs, keep, limit):
    """스타일은 상품에 직접 안 붙어 있다 — product_term 을 거쳐 센다."""
    agg = (
        ProductTerm.objects.filter(
            term__term_type="STYLE",
            product_id__in=qs.values("id"),
        )
        .values("term__canonical_name")
        .annotate(n=Count("product_id", distinct=True))
        .order_by("-n", "term__canonical_name")
    )
    out = []
    for r in agg:
        label = r["term__canonical_name"]
        if not label:
            continue
        out.append({"label": label, "count": r["n"]})
        if len(out) >= limit:
            break
    have = {o["label"] for o in out}
    for k in keep:
        if k not in have:
            out.append({"label": k, "count": 0, "picked_only": True})
    return out


def _dictionary_only(sel, limit):
    """상품이 없을 때 — 사전만 내려보낸다. 교차로 좁히지는 못한다."""

    def terms(kind):
        return [
            {"label": r["canonical_name"], "count": None}
            for r in DictionaryTerm.objects.filter(
                status="ACTIVE", term_type=kind
            ).values("canonical_name")[:limit]
            if r["canonical_name"]
        ]

    return {
        "style": terms("STYLE"),
        "kind": terms("ITEM"),
        "brand": [
            {"label": r["name"], "count": None}
            for r in Brand.objects.filter(status="ACTIVE").values("name")[:limit]
            if r["name"]
        ],
        # 아이템명(상품명)은 상품이 있어야 나온다.
        "item": [],
    }


@require_GET
def facets(request):
    """GET /api/facets?style=스트릿&brand=스투시&limit=200

    세부 검색 네 칸(STYLE · 종류 · 브랜드 · 아이템명)의 후보를 한 번에 준다.
    네 칸은 서로 독립이고, 겹쳐 고르면 교집합이다.

    돌려주는 것
        data.style / data.kind / data.brand / data.item
            [{label, count}] — count 는 그 조건에서 걸리는 상품 수
        matched   지금 조건에 걸리는 상품 수
        narrowed  교차로 좁혔는가 (상품이 없으면 false)
    """
    limit = _int(request, "limit", 200, 1, 1000)
    sel = {k: _list(request, k) for k in FACET_PARAMS}

    base = Product.objects.filter(status="ACTIVE")
    n_products = base.count()

    # 상품이 너무 적으면 교차 계산은 거짓말에 가깝다. 사전만 준다.
    if n_products < MIN_PRODUCTS_FOR_FACETS:
        data = _dictionary_only(sel, limit)
        if not any(data.values()):
            return _empty(
                "상품도 사전도 비어 있습니다. "
                "commerce.product · dictionary_term · brand 적재를 확인하세요.",
                narrowed=False,
                products=n_products,
            )
        return _ok(
            data,
            matched=0,
            narrowed=False,
            products=n_products,
            note=(
                f"commerce.product 가 {n_products}개뿐이라 축끼리 좁히지 못했습니다 "
                f"— 사전 목록을 그대로 보냅니다. 상품이 {MIN_PRODUCTS_FOR_FACETS}개를 "
                "넘으면 자동으로 좁히기 시작합니다."
            ),
        )

    matched = _apply(base, sel).count()

    data = {
        "style": _style_rows(_apply(base, sel, skip="style"), sel["style"], limit),
        "kind": _rows(
            _apply(base, sel, skip="kind"),
            "item_term__term__canonical_name",
            sel["kind"],
            limit,
        ),
        "brand": _rows(
            _apply(base, sel, skip="brand"), "brand__name", sel["brand"], limit
        ),
        "item": _rows(
            _apply(base, sel, skip="item"), "canonical_name", sel["item"], limit
        ),
    }

    if not any(len(v) for v in data.values()):
        return _empty(
            "고른 조건에 맞는 상품이 없습니다. 조건을 하나 빼고 다시 보세요.",
            matched=0,
            narrowed=True,
        )

    return _ok(data, matched=matched, narrowed=True, selected=sel,
               products=n_products)
