"""운영 RDS 스키마를 직접 사용하는 FEEDiT API.

DB 팀의 운영 스키마가 이 저장소의 오래된 Django 모델보다 앞서 있으므로,
사용자 화면용 조회는 필요한 컬럼만 명시하는 SQL로 읽는다. 계정 테이블은
현재 모델과 운영 DB가 일치하므로 Django auth/session과 함께 사용한다.
"""
from __future__ import annotations

import json
import re
from datetime import date

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from apps.core.models import (
    AppUser,
    ChatMessage,
    ChatSession,
    UserEvent,
    UserSavedItem,
    UserTaste,
    VoteBallot,
    VoteCard,
)


def _rows(sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        names = [col[0] for col in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]


def _one(sql, params=()):
    rows = _rows(sql, params)
    return rows[0] if rows else None


def _ok(data=None, **extra):
    return JsonResponse({"status": "ok", **extra, "data": data})


def _empty(reason, **extra):
    return JsonResponse({"status": "empty", "reason": reason, **extra, "data": None})


def _error(reason, status=400, **extra):
    return JsonResponse({"status": "error", "reason": reason, **extra, "data": None}, status=status)


def _body(request):
    if len(request.body or b"") > 1_000_000:
        raise ValueError("요청이 너무 큽니다.")
    try:
        value = json.loads((request.body or b"{}").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("JSON 형식이 올바르지 않습니다.") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON 객체를 보내 주세요.")
    return value


def _limit(request, default=40, maximum=500):
    try:
        return max(1, min(maximum, int(request.GET.get("limit", default))))
    except (TypeError, ValueError):
        return default


@require_GET
def health(request):
    counts = _rows(
        """
        SELECT 'dictionary.dictionary_term' name, count(*) n FROM dictionary.dictionary_term
        UNION ALL SELECT 'commerce.product', count(*) FROM commerce.product
        UNION ALL SELECT 'commerce.product_source', count(*) FROM commerce.product_source
        UNION ALL SELECT 'analysis.term_metric_daily', count(*) FROM analysis.term_metric_daily
        UNION ALL SELECT 'analysis.term_assoc_daily', count(*) FROM analysis.term_assoc_daily
        UNION ALL SELECT 'app.app_user', count(*) FROM app.app_user
        UNION ALL SELECT 'app.chat_session', count(*) FROM app.chat_session
        """
    )
    latest = _one("SELECT max(metric_date) latest FROM analysis.term_metric_daily")
    return JsonResponse({
        "ok": True,
        "database": connection.settings_dict.get("NAME"),
        "tables": {row["name"]: row["n"] for row in counts},
        "latest_metric_date": latest["latest"] if latest else None,
        "metric_contract": {
            "temperature": "trend_temperature",
            "percentile": "percentile",
            "version": "metric_version",
        },
    })


@require_GET
def terms(request):
    limit = _limit(request, 300, 1000)
    rows = _rows(
        """
        SELECT t.canonical_name term, lower(t.term_type) facet,
               count(*) points, max(m.metric_date) last_date
          FROM analysis.term_metric_daily m
          JOIN dictionary.dictionary_term t ON t.id=m.term_id
         WHERE m.source_id IS NULL
         GROUP BY t.id,t.canonical_name,t.term_type
         ORDER BY max(m.metric_date) DESC, max(m.trend_temperature) DESC NULLS LAST
         LIMIT %s
        """, [limit]
    )
    return _ok(rows) if rows else _empty("RDS에 계산된 트렌드 용어가 없습니다.")


@require_GET
def dictionary(request):
    limit = _limit(request, 4000, 8000)
    terms = _rows(
        """
        SELECT t.canonical_name label, t.term_type facet, 'term' kind,
               coalesce(t.english_name,'') en,
               coalesce(array_agg(a.alias ORDER BY a.alias)
                 FILTER (WHERE a.alias IS NOT NULL), ARRAY[]::varchar[]) aliases
          FROM dictionary.dictionary_term t
          LEFT JOIN dictionary.term_alias a ON a.term_id=t.id
         WHERE t.status='ACTIVE'
         GROUP BY t.id,t.canonical_name,t.term_type,t.english_name
         ORDER BY t.id LIMIT %s
        """, [limit]
    )
    brands = _rows(
        """
        SELECT name label, 'BRAND' facet, 'brand' kind,
               coalesce(english_name,'') en, ARRAY[]::varchar[] aliases
          FROM dictionary.brand
         WHERE status='ACTIVE' AND name IS NOT NULL AND name<>''
         ORDER BY id LIMIT %s
        """, [limit]
    )
    rows = terms + brands
    counts = {}
    facet_ko = {"BRAND":"브랜드","STYLE":"스타일","ITEM":"아이템","MATERIAL":"소재",
                "DETAIL":"디테일","COLOR":"색","TPO":"TPO"}
    for row in rows:
        row["facet"] = facet_ko.get(row["facet"], row["facet"])
        counts[row["facet"]] = counts.get(row["facet"], 0) + 1
    return _ok(rows, counts=counts, total=len(rows)) if rows else _empty("RDS 사전이 비어 있습니다.")


@require_GET
def trend(request):
    term = (request.GET.get("term") or "").strip()
    if not term:
        return terms(request)
    try:
        days = max(7, min(400, int(request.GET.get("days", 90))))
    except ValueError:
        days = 90
    source = (request.GET.get("source") or "").strip()
    source_sql = "AND lower(s.code)=lower(%s)" if source else "AND m.source_id IS NULL"
    params = [term, days] + ([source] if source else [])
    rows = _rows(
        f"""
        SELECT m.metric_date date, m.raw_count, m.mention_count, m.document_count,
               m.content_count, m.creator_count, m.level, m.ma7, m.ma28, m.momentum,
               m.trend_temperature temp, m.percentile pct_rank, m.sentiment_avg,
               m.purchase_intent_index, m.positive_count, m.negative_count,
               m.neutral_count, m.metric_version, m.metrics,
               t.canonical_name term, lower(t.term_type) facet,
               lower(s.code) source_code
          FROM analysis.term_metric_daily m
          JOIN dictionary.dictionary_term t ON t.id=m.term_id
          LEFT JOIN collection.source s ON s.id=m.source_id
         WHERE (t.canonical_name=%s OR t.normalized_name=lower(%s))
           AND m.metric_date >= current_date-%s::int
           {source_sql}
         ORDER BY m.metric_date
        """, [term, term, days] + ([source] if source else [])
    )
    if not rows:
        known = _one("SELECT id FROM dictionary.dictionary_term WHERE canonical_name=%s LIMIT 1", [term])
        return _empty(
            f"‘{term}’은 사전에 있지만 최근 {days}일 지표가 없습니다."
            if known else f"‘{term}’을 RDS 사전에서 찾지 못했습니다.",
            term=term, known=bool(known),
        )
    version = rows[-1].pop("metric_version", None)
    facet = rows[-1].pop("facet", None)
    canonical = rows[-1].pop("term", term)
    for row in rows:
        row["mention"] = row.get("mention_count")
        row["document"] = row.get("document_count")
        row["source"] = None
        row["sentiment"] = row.get("sentiment_avg")
        row["score"] = None
        row.pop("term", None); row.pop("facet", None)
    return _ok({"term": canonical, "facet": facet, "source": source or None,
                "days": days, "points": len(rows), "metric_version": version,
                "series": rows})


@require_GET
def assoc(request):
    term = (request.GET.get("term") or "").strip()
    if not term:
        return _empty("term을 지정해 주세요.")
    limit = _limit(request, 20, 100)
    rows = _rows(
        """
        SELECT tgt.canonical_name term, lower(tgt.term_type) facet,
               a.metric_date, a.cooccurrence_count cooccurrence,
               a.pmi, a.lift, a.association_percentile percentile,
               a.association_rank rank, a.is_new, a.metric_version
          FROM analysis.term_assoc_daily a
          JOIN dictionary.dictionary_term src ON src.id=a.source_term_id
          JOIN dictionary.dictionary_term tgt ON tgt.id=a.target_term_id
         WHERE src.canonical_name=%s
           AND a.metric_date=(SELECT max(x.metric_date) FROM analysis.term_assoc_daily x
                               WHERE x.source_term_id=a.source_term_id)
         ORDER BY a.association_rank NULLS LAST, a.association_percentile DESC NULLS LAST,
                  a.pmi DESC NULLS LAST, a.cooccurrence_count DESC
         LIMIT %s
        """, [term, limit]
    )
    if not rows:
        return _empty("연관어가 아직 RDS에 적재되지 않았습니다.", term=term)
    return _ok({"term": term, "as_of": rows[0]["metric_date"], "items": rows})


@require_GET
def products(request):
    keyword = (request.GET.get("q") or "").strip()
    brand = (request.GET.get("brand") or "").strip()
    limit = _limit(request, 40, 200)
    filters, params = ["ps.status='ACTIVE'"], []
    if keyword:
        filters.append("(coalesce(p.canonical_name,ps.source_name) ILIKE %s OR bs.name ILIKE %s)")
        params += [f"%{keyword}%", f"%{keyword}%"]
    if brand:
        filters.append("coalesce(b.name,bs.name) ILIKE %s")
        params.append(brand)
    params.append(limit)
    rows = _rows(
        f"""
        SELECT coalesce(p.id,0) id, ps.id product_source_id,
               coalesce(p.canonical_name,ps.source_name,'(이름 없음)') name,
               coalesce(b.name,bs.name) brand, coalesce(b.english_name,bs.english_name) brand_en,
               coalesce(c.name,cs.source_category_name) category,
               lower(src.code) source, src.name source_label, ps.market_type market,
               ps.product_url url, ps.thumbnail_url image_url, ps.mapping_status,
               sn.list_price, sn.sale_price, sn.discount_rate, sn.stock_status,
               sn.rating, sn.review_count, sn.like_count, sn.sales_count, sn.view_count,
               sn.observed_at
          FROM commerce.product_source ps
          LEFT JOIN commerce.product p ON p.id=ps.product_id
          LEFT JOIN dictionary.brand b ON b.id=p.brand_id
          LEFT JOIN dictionary.brand_source bs ON bs.id=ps.source_brand_id
          LEFT JOIN dictionary.category c ON c.id=p.category_id
          LEFT JOIN dictionary.category_source cs ON cs.id=ps.source_category_id
          JOIN collection.source src ON src.id=ps.source_id
          LEFT JOIN LATERAL (
              SELECT * FROM snapshot.product_source_snapshot x
               WHERE x.product_source_id=ps.id ORDER BY observed_at DESC LIMIT 1
          ) sn ON true
         WHERE {' AND '.join(filters)}
         ORDER BY ps.last_seen_at DESC NULLS LAST
         LIMIT %s
        """, params
    )
    if not rows:
        return _empty("조건에 맞는 RDS 상품이 없습니다.")
    no_price = 0
    for row in rows:
        if row.get("observed_at") is None:
            no_price += 1
        row["price"] = {
            "list": row.get("list_price"), "sale": row.get("sale_price"),
            "discount": row.get("discount_rate"), "stock": row.get("stock_status"),
            "as_of": row.get("observed_at"),
            "unavailable": None if row.get("observed_at") else "이 상품은 아직 가격 스냅샷이 없습니다.",
        }
    return _ok({"count": len(rows), "items": rows},
               **({"note": f"{no_price}건은 가격 기록이 아직 없습니다."} if no_price else {}))


@require_GET
def facets(request):
    limit = _limit(request, 200, 1000)
    def picked(name):
        values = []
        for raw in request.GET.getlist(name):
            values.extend(part.strip() for part in raw.split(",") if part.strip())
        return list(dict.fromkeys(values))

    selected = {name: picked(name) for name in ("style", "kind", "brand", "item")}

    def where(skip=None):
        clauses, params = ["ps.status='ACTIVE'"], []
        for axis, term_type in (("style", "STYLE"), ("kind", "ITEM")):
            if axis != skip and selected[axis]:
                clauses.append(
                    "EXISTS (SELECT 1 FROM commerce.product_term sx "
                    "JOIN dictionary.dictionary_term st ON st.id=sx.term_id "
                    "WHERE sx.product_source_id=ps.id AND st.term_type=%s "
                    "AND st.canonical_name=ANY(%s))"
                )
                params += [term_type, selected[axis]]
        if skip != "brand" and selected["brand"]:
            clauses.append("coalesce(b.name,bs.name)=ANY(%s)"); params.append(selected["brand"])
        if skip != "item" and selected["item"]:
            clauses.append("coalesce(p.canonical_name,ps.source_name)=ANY(%s)"); params.append(selected["item"])
        return " AND ".join(clauses), params

    joins = """FROM commerce.product_source ps
               LEFT JOIN commerce.product p ON p.id=ps.product_id
               LEFT JOIN dictionary.brand b ON b.id=p.brand_id
               LEFT JOIN dictionary.brand_source bs ON bs.id=ps.source_brand_id"""

    def term_axis(axis, term_type):
        clause, params = where(axis)
        return _rows(
            f"""SELECT t.canonical_name label,count(DISTINCT ps.id) count {joins}
                 JOIN commerce.product_term pt ON pt.product_source_id=ps.id
                 JOIN dictionary.dictionary_term t ON t.id=pt.term_id
                WHERE {clause} AND t.term_type=%s
                GROUP BY t.id,t.canonical_name ORDER BY count DESC LIMIT %s""",
            [*params, term_type, limit],
        )

    def plain_axis(axis, expression):
        clause, params = where(axis)
        return _rows(
            f"""SELECT {expression} label,count(DISTINCT ps.id) count {joins}
                WHERE {clause} AND {expression} IS NOT NULL
                GROUP BY {expression} ORDER BY count DESC LIMIT %s""", [*params, limit]
        )

    data = {
        "style": term_axis("style", "STYLE"), "kind": term_axis("kind", "ITEM"),
        "brand": plain_axis("brand", "coalesce(b.name,bs.name)"),
        "item": plain_axis("item", "coalesce(p.canonical_name,ps.source_name)"),
    }
    for axis, values in selected.items():
        labels = {row["label"] for row in data[axis]}
        data[axis].extend({"label": value, "count": 0, "picked_only": True}
                          for value in values if value not in labels)
    matched_where, matched_params = where()
    matched = _one(f"SELECT count(DISTINCT ps.id) n {joins} WHERE {matched_where}", matched_params)["n"]
    products = _one("SELECT count(*) n FROM commerce.product_source WHERE status='ACTIVE'")["n"]
    return _ok(data, matched=matched, narrowed=True, selected=selected, products=products)


def _salmal_payload(card_id):
    card = _one(
        """
        SELECT vc.id,vc.title,vc.description,vc.image_url,vc.tags,vc.status,
               vc.created_at,vc.user_id,vc.product_id,
               p.canonical_name product_name,b.name brand,c.name category,
               count(vb.id) total,
               count(vb.id) FILTER (WHERE vb.choice='BUY') buy
          FROM app.vote_card vc
          LEFT JOIN commerce.product p ON p.id=vc.product_id
          LEFT JOIN dictionary.brand b ON b.id=p.brand_id
          LEFT JOIN dictionary.category c ON c.id=p.category_id
          LEFT JOIN app.vote_ballot vb ON vb.card_id=vc.id
         WHERE vc.id=%s
         GROUP BY vc.id,p.id,b.id,c.id
        """, [card_id]
    )
    if not card:
        return None
    tags = [str(value).strip() for value in (card.get("tags") or []) if str(value).strip()]
    product_tags = []
    if card.get("product_id"):
        product_tags = [row["label"] for row in _rows(
            """SELECT DISTINCT t.canonical_name label
                 FROM commerce.product_source ps
                 JOIN commerce.product_term pt ON pt.product_source_id=ps.id
                 JOIN dictionary.dictionary_term t ON t.id=pt.term_id
                WHERE ps.product_id=%s ORDER BY t.canonical_name LIMIT 20""",
            [card["product_id"]],
        )]
    snapshot = None
    if card.get("product_id"):
        snapshot = _one(
            """SELECT sn.list_price,sn.sale_price,sn.discount_rate,sn.stock_status,sn.observed_at
                 FROM commerce.product_source ps
                 JOIN snapshot.product_source_snapshot sn ON sn.product_source_id=ps.id
                WHERE ps.product_id=%s ORDER BY sn.observed_at DESC LIMIT 1""",
            [card["product_id"]],
        )
    total, buy = int(card.get("total") or 0), int(card.get("buy") or 0)
    return {
        "card": {key: card.get(key) for key in (
            "id", "title", "description", "image_url", "tags", "status", "created_at"
        )},
        "product": None if not card.get("product_id") else {
            "id": card["product_id"], "name": card.get("product_name"),
            "brand": card.get("brand"), "category": card.get("category"),
            "tags": list(dict.fromkeys([*tags, *product_tags])),
        },
        "vote_summary": {
            "total": total, "buy": buy, "pass": total - buy,
            "buy_pct": round(buy / total * 100, 1) if total else None,
            "closed": card.get("status") == "CLOSED",
        },
        "price_snapshot": snapshot,
    }


@require_GET
def salmal_card(request):
    try:
        card_id = int(request.GET.get("card_id") or 0)
    except ValueError:
        card_id = 0
    if not card_id:
        return _empty("card_id를 지정해 주세요.")
    payload = _salmal_payload(card_id)
    return _ok(payload) if payload else _empty("해당 살!말? 카드를 찾지 못했습니다.", card_id=card_id)


@require_GET
def salmal_search(request):
    term = (request.GET.get("term") or "").strip()
    if not term:
        return _empty("term을 지정해 주세요.")
    limit = _limit(request, 5, 10)
    ids = _rows(
        """SELECT DISTINCT vc.id,vc.created_at
             FROM app.vote_card vc
             LEFT JOIN commerce.product p ON p.id=vc.product_id
             LEFT JOIN dictionary.brand b ON b.id=p.brand_id
            WHERE vc.title ILIKE %s OR p.canonical_name ILIKE %s OR b.name ILIKE %s
            ORDER BY vc.created_at DESC LIMIT %s""",
        [f"%{term}%", f"%{term}%", f"%{term}%", limit],
    )
    items = [_salmal_payload(row["id"]) for row in ids]
    items = [item for item in items if item]
    return _ok({"term": term, "items": items, "count": len(items)}) if items else _empty(
        f"‘{term}’과 연결된 살!말? 카드가 없습니다.", term=term
    )


def _profile(app_user):
    tastes = list(app_user.tastes.filter(taste_type="TERM", term__term_type="STYLE")
                  .values_list("term__canonical_name", flat=True))
    meta = dict(app_user.profile_metadata or {})
    return {
        "id": app_user.id, "username": app_user.user.username,
        "email": app_user.user.email or "", "nickname": app_user.nickname or app_user.user.username,
        "birth_year": app_user.birth_year, "body_type": app_user.body_type,
        "birth": meta.get("birth"), "height_cm": meta.get("height_cm"),
        "weight_kg": meta.get("weight_kg"), "bio": meta.get("bio", ""),
        "avatar": meta.get("avatar", 0), "styles": tastes,
    }


def _current(request):
    if not request.user.is_authenticated:
        return None
    return AppUser.objects.select_related("user").filter(user=request.user).first()


def _body_type(height, weight):
    if not height or not weight:
        return None
    bmi = float(weight) / ((float(height) / 100) ** 2)
    return "슬림" if bmi < 18.5 else "표준" if bmi < 23 else "스탠다드 플러스" if bmi < 25 else "볼륨"


def _replace_styles(app_user, labels):
    clean = list(dict.fromkeys(str(x).strip() for x in (labels or []) if str(x).strip()))[:10]
    UserTaste.objects.filter(user=app_user, taste_type="TERM", source="USER").delete()
    if not clean:
        return
    term_rows = _rows(
        "SELECT id,canonical_name FROM dictionary.dictionary_term WHERE status='ACTIVE' "
        "AND term_type='STYLE' AND canonical_name=ANY(%s)", [clean]
    )
    UserTaste.objects.bulk_create([
        UserTaste(user=app_user, taste_type="TERM", term_id=row["id"], weight=1, source="USER")
        for row in term_rows
    ])


@csrf_exempt
@require_http_methods(["GET", "POST", "PATCH", "DELETE"])
def account(request):
    action = (request.GET.get("action") or "me").strip().lower()
    try:
        data = _body(request) if request.method != "GET" else {}
    except ValueError as exc:
        return _error(str(exc))

    if action == "signup" and request.method == "POST":
        username = str(data.get("username") or "").strip()
        nickname = str(data.get("nickname") or "").strip()
        password = str(data.get("password") or "")
        if not re.fullmatch(r"[A-Za-z0-9]{4,16}", username):
            return _error("아이디는 영문·숫자 4~16자로 입력해 주세요.")
        if not 2 <= len(nickname) <= 12:
            return _error("닉네임은 2~12자로 입력해 주세요.")
        try:
            validate_password(password)
        except ValidationError as exc:
            return _error(" ".join(exc.messages))
        User = get_user_model()
        if User.objects.filter(username__iexact=username).exists():
            return _error("이미 사용 중인 아이디입니다.", status=409)
        with transaction.atomic():
            user = User.objects.create_user(username=username, password=password)
            meta = {k: data.get(k) for k in ("birth", "height_cm", "weight_kg", "bio", "avatar") if data.get(k) not in (None, "")}
            birth_year = None
            if meta.get("birth"):
                try: birth_year = date.fromisoformat(str(meta["birth"])).year
                except ValueError: pass
            app_user = AppUser.objects.create(user=user, nickname=nickname, birth_year=birth_year,
                                              body_type=_body_type(meta.get("height_cm"), meta.get("weight_kg")),
                                              profile_metadata=meta)
            _replace_styles(app_user, data.get("styles"))
            login(request, user)
        return _ok(_profile(app_user))

    if action == "login" and request.method == "POST":
        user = authenticate(request, username=str(data.get("username") or "").strip(),
                            password=str(data.get("password") or ""))
        if user is None:
            return _error("아이디 또는 비밀번호가 올바르지 않습니다.", status=401)
        login(request, user)
        app_user, _ = AppUser.objects.get_or_create(user=user, defaults={"nickname": user.username})
        return _ok(_profile(app_user))

    if action == "logout" and request.method == "POST":
        logout(request)
        return _ok({"logged_out": True})

    if action == "cards" and request.method == "GET":
        ids = _rows("SELECT id FROM app.vote_card ORDER BY created_at DESC LIMIT %s",
                    [_limit(request, 100, 200)])
        payloads = [payload for payload in (_salmal_payload(row["id"]) for row in ids) if payload]
        current = _current(request)
        choices = ({row.card_id: row.choice for row in VoteBallot.objects.filter(
            user=current, card_id__in=[payload["card"]["id"] for payload in payloads]
        )} if current else {})
        for payload in payloads:
            payload["vote_summary"]["my_choice"] = choices.get(payload["card"]["id"])
        return _ok(payloads)

    app_user = _current(request)
    if app_user is None:
        return _error("로그인이 필요합니다.", status=401)

    if action == "me" and request.method == "GET":
        return _ok(_profile(app_user))

    if action == "profile" and request.method in ("POST", "PATCH"):
        nickname = str(data.get("nickname") or app_user.nickname or "").strip()
        if not 2 <= len(nickname) <= 12:
            return _error("닉네임은 2~12자로 입력해 주세요.")
        meta = dict(app_user.profile_metadata or {})
        for key in ("birth", "height_cm", "weight_kg", "bio", "avatar"):
            if key in data: meta[key] = data[key]
        app_user.nickname = nickname
        app_user.profile_metadata = meta
        if meta.get("birth"):
            try: app_user.birth_year = date.fromisoformat(str(meta["birth"])).year
            except ValueError: return _error("생년월일 형식이 올바르지 않습니다.")
        app_user.body_type = _body_type(meta.get("height_cm"), meta.get("weight_kg"))
        app_user.save(update_fields=["nickname","profile_metadata","birth_year","body_type","updated_at"])
        if "styles" in data:
            with transaction.atomic(): _replace_styles(app_user, data.get("styles"))
        password = str(data.get("password") or "")
        if password:
            try: validate_password(password, user=app_user.user)
            except ValidationError as exc: return _error(" ".join(exc.messages))
            app_user.user.set_password(password); app_user.user.save(update_fields=["password"])
            login(request, app_user.user)
        return _ok(_profile(app_user))

    if action == "chat" and request.method == "POST":
        conversation_id = str(data.get("conversation_id") or "").strip()[:64]
        question = str(data.get("question") or "").strip()[:4000]
        answer = str(data.get("answer") or "").strip()[:20000]
        if not conversation_id or not question:
            return _error("대화 ID와 질문이 필요합니다.")
        with transaction.atomic():
            session = ChatSession.objects.filter(user=app_user, context__conversation_id=conversation_id).first()
            if session is None:
                session = ChatSession.objects.create(user=app_user, title=question[:80],
                                                     context={"conversation_id": conversation_id,
                                                              "mode": data.get("mode") or "general"})
            ChatMessage.objects.create(session=session, role="USER", content=question,
                                       metadata={"client_message_id": data.get("message_id")})
            if answer:
                ChatMessage.objects.create(session=session, role="ASSISTANT", content=answer,
                                           metadata={"intent": data.get("intent"), "report": data.get("report") or {}})
            session.save(update_fields=["updated_at"])
            UserEvent.objects.create(user=app_user, event_type="CHAT", metadata={"conversation_id":conversation_id})
        return _ok({"session_id": session.id})

    if action == "conversations" and request.method == "GET":
        sessions = ChatSession.objects.filter(user=app_user).order_by("-updated_at")[:50]
        return _ok([{"id":s.id,"title":s.title,"context":s.context,"updated_at":s.updated_at,
                     "messages":[{"role":m.role,"content":m.content,"metadata":m.metadata,"created_at":m.created_at}
                                 for m in s.messages.order_by("created_at")[:100]]} for s in sessions])

    if action == "event" and request.method == "POST":
        allowed = {"VIEW","CLICK","SAVE","SEARCH","VOTE","CHAT"}
        event_type = str(data.get("event_type") or "").upper()
        if event_type not in allowed: return _error("지원하지 않는 이벤트 유형입니다.")
        event = UserEvent.objects.create(user=app_user, event_type=event_type,
                                         product_id=data.get("product_id") or None,
                                         term_id=data.get("term_id") or None,
                                         content_item_id=data.get("content_item_id") or None,
                                         metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {})
        return _ok({"id":event.id})

    if action == "saved" and request.method == "GET":
        rows = _rows(
            """SELECT usi.id saved_id,usi.created_at,p.id product_id,p.canonical_name name,
                      b.name brand,c.name category,ps.product_url url,ps.thumbnail_url image_url,
                      sn.list_price,sn.sale_price,sn.discount_rate,sn.stock_status,sn.observed_at
                 FROM app.user_saved_item usi
                 JOIN commerce.product p ON p.id=usi.product_id
                 LEFT JOIN dictionary.brand b ON b.id=p.brand_id
                 LEFT JOIN dictionary.category c ON c.id=p.category_id
                 LEFT JOIN LATERAL (
                     SELECT x.* FROM commerce.product_source x WHERE x.product_id=p.id
                     ORDER BY x.last_seen_at DESC NULLS LAST LIMIT 1
                 ) ps ON true
                 LEFT JOIN LATERAL (
                     SELECT x.* FROM snapshot.product_source_snapshot x
                     WHERE x.product_source_id=ps.id ORDER BY x.observed_at DESC LIMIT 1
                 ) sn ON true
                WHERE usi.user_id=%s AND usi.product_id IS NOT NULL
                ORDER BY usi.created_at DESC LIMIT 200""",
            [app_user.id],
        )
        return _ok(rows)

    if action == "saved" and request.method == "POST":
        try:
            product_id = int(data.get("product_id") or 0)
        except (TypeError, ValueError):
            product_id = 0
        if not product_id or not _one("SELECT id FROM commerce.product WHERE id=%s", [product_id]):
            return _error("저장할 RDS 상품을 찾지 못했습니다.", status=404)
        saved = UserSavedItem.objects.filter(user=app_user, product_id=product_id).first()
        if saved:
            saved.delete()
            is_saved = False
        else:
            UserSavedItem.objects.create(user=app_user, product_id=product_id)
            is_saved = True
        UserEvent.objects.create(user=app_user, event_type="SAVE", product_id=product_id,
                                 metadata={"saved": is_saved})
        return _ok({"product_id": product_id, "saved": is_saved})

    if action == "vote" and request.method == "POST":
        try:
            card_id = int(data.get("card_id") or 0)
        except (TypeError, ValueError):
            card_id = 0
        choice = str(data.get("choice") or "").upper()
        card = VoteCard.objects.filter(id=card_id, status="ACTIVE").first()
        if card is None:
            return _error("투표할 카드를 찾지 못했거나 종료되었습니다.", status=404)
        if choice not in {"BUY", "PASS"}:
            return _error("choice는 BUY 또는 PASS여야 합니다.")
        VoteBallot.objects.update_or_create(card=card, user=app_user, defaults={"choice": choice})
        UserEvent.objects.create(user=app_user, event_type="VOTE",
                                 product_id=card.product_id,
                                 metadata={"card_id": card_id, "choice": choice})
        return _ok(_salmal_payload(card_id))

    if action == "card" and request.method == "POST":
        title = str(data.get("title") or "").strip()
        if not title:
            return _error("카드 제목을 입력해 주세요.")
        product_id = data.get("product_id") or None
        if product_id and not _one("SELECT id FROM commerce.product WHERE id=%s", [product_id]):
            return _error("연결할 RDS 상품을 찾지 못했습니다.", status=404)
        image_url = str(data.get("image_url") or "").strip() or None
        if image_url and not re.match(r"^https?://", image_url, flags=re.I):
            return _error("이미지는 먼저 S3 등에 업로드한 HTTPS URL이어야 합니다.")
        tags = data.get("tags") if isinstance(data.get("tags"), list) else []
        card = VoteCard.objects.create(
            user=app_user, product_id=product_id, title=title[:300],
            description=str(data.get("description") or "").strip() or None,
            image_url=image_url, tags=[str(tag).strip() for tag in tags if str(tag).strip()][:20],
        )
        return _ok(_salmal_payload(card.id))

    if action == "delete" and request.method == "DELETE":
        user = app_user.user
        logout(request)
        user.delete()
        return _ok({"deleted": True})

    return _error("지원하지 않는 계정 작업입니다.", status=405)
