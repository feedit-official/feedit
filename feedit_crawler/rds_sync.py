"""SQLite 정제 결과를 FEEDIT FINAL 35-table RDS에 증분 적재한다."""
from __future__ import annotations

import json
import re

from .codemap import FACET_TO_TYPE, get as _codemap
import subprocess

from .platformdb import PlatformDB


CODEMAP = _codemap()


def _q(value) -> str:
    if value is None or value == "": return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def _norm(value) -> str:
    return re.sub(r"[\s\-_.·/'\"()]+", "", str(value or "")).lower()


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _valid_brand(value) -> bool:
    value = str(value or "").strip()
    return bool(value and not value.isdigit() and not re.match(
        r"^(?:FW|SS)\s*\d+|무배당발|무료배송|쿠폰|최저가|품절|\d+%$", value, re.I))


def _product_terms(row) -> list[tuple[str, str]]:
    """상품에 붙일 수 있는 표준 사전 용어만 반환한다.

    사이트 자유 태그를 억지로 분류하지 않고 코드표와 정확히 맞는 값만 쓴다.
    모델이 만든 객체 태그는 facet을 이미 알고 있으므로 그 facet으로 확인한다.
    """
    found = {}
    candidates = list(_json_list(row.get("site_tags")))
    candidates += list(_json_list(row.get("color_names")))
    for tag in candidates:
        if isinstance(tag, dict):
            name = str(tag.get("canonical") or tag.get("name") or "").strip()
            facets = [str(tag.get("facet") or "").lower()]
        else:
            name = str(tag or "").strip()
            facets = ["style", "material", "color", "item", "detail", "tpo"]
        if not name:
            continue
        for facet in facets:
            code, _ = CODEMAP.term(facet, name)
            if code:
                found[(FACET_TO_TYPE[facet], _norm(name))] = name
                break
    return [(kind, name) for (kind, _), name in found.items()]


class RDSSync:
    def __init__(self, root, store):
        self.db = PlatformDB(root)
        self.store = store

    def _run_sql(self, sql: str, incoming=None) -> dict:
        cfg = self.db.config(incoming)
        # 이름이 아니라 찾아낸 실제 경로로 부른다 (platformdb.find_tool 설명 참고).
        from .platformdb import find_tool
        # -w : 비밀번호를 터미널에서 묻지 않는다. 물어보면 사람이 없어서
        #      900초 타임아웃까지 매달린다 (자동 적재가 매번 그랬다).
        args = [find_tool("psql") or "psql", "-w",
                *self.db._conn_args(cfg, cfg.database), "-X", "-v", "ON_ERROR_STOP=1", "-q"]
        try:
            p = subprocess.run(args, input=sql, text=True, capture_output=True,
                               env=self.db._env(cfg), timeout=900, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": p.returncode == 0, "error": (p.stderr or "")[-3000:],
                "output": (p.stdout or "")[-1000:]}

    def password_ready(self, incoming=None) -> tuple[bool, str]:
        """비밀번호를 psql 이 얻을 수 있는 상태인가.

        ★ 왜 미리 보는가
          비밀번호는 **일부러** 프로세스 메모리에만 둔다(파일에 안 적는다).
          그래서 서버를 다시 켜면 사라진다. 그 상태로 자동 적재가 돌면
          psql 이 이렇게 뱉는다:

              psql: 오류: "127.0.0.1" 포트 5433 서버에 접속 할 수 없음:
              fe_sendauth: no password supplied

          '접속할 수 없음' 이라 네트워크가 끊긴 것처럼 읽히지만, 실은
          **비밀번호를 안 줘서** 생긴 일이다. 서버까지는 갔다. 이 오해로
          보안 그룹·터널을 헤매게 되므로, 돌기 전에 먼저 보고 사람 말로 알린다.

          .pgpass 는 열어 보지 않는다 — 있는지만 본다. 남의 비밀번호를
          우리 코드가 읽을 이유가 없다.
        """
        cfg = self.db.config(incoming)
        if cfg.password:
            return True, "이번 서버 세션에 비밀번호가 있습니다"
        from pathlib import Path as _P
        if (_P.home() / ".pgpass").exists():
            return True, "~/.pgpass 를 psql 이 읽습니다"
        return False, (
            f"AWS 비밀번호가 없습니다. 비밀번호는 파일에 적지 않아서 "
            f"**서버를 다시 켜면 사라집니다**.\n"
            f"  ① 지금 한 번만 → [AWS] 탭에서 비밀번호를 넣고 연결을 확인하세요.\n"
            f"  ② 다시 안 넣으려면 → ~/.pgpass 에 한 줄 넣고 chmod 600 하세요:\n"
            f"     {cfg.host}:{cfg.port}:{cfg.database}:{cfg.user}:<비밀번호>")

    def sync(self, incoming=None, on_progress=None) -> dict:
        cfg = self.db.config(incoming)
        self.db.save_public(cfg)
        state = self.db.state(incoming)
        if not state.get("ok") or state.get("tables", 0) < 35:
            return {"ok": False, "error": state.get("error") or
                    f"FEEDIT FINAL RDS 35개 테이블을 확인하지 못했습니다 (현재 {state.get('tables',0)}개)."}
        with self.store._lock:
            products = [dict(r) for r in self.store._conn.execute(
                "SELECT * FROM staging_product ORDER BY id")]
            snapshots = [dict(r) for r in self.store._conn.execute(
                "SELECT * FROM product_price_snapshot ORDER BY id")]
            stats = [dict(r) for r in self.store._conn.execute(
                "SELECT * FROM product_stat ORDER BY id")]
        source_meta = {
            "musinsa": ("무신사", "COMMERCE", "BROWSER", 720),
            "musinsa_used": ("무신사 USED", "COMMERCE", "BROWSER", 720),
            "zigzag": ("지그재그", "COMMERCE", "BROWSER", 720),
            "ably": ("에이블리", "COMMERCE", "BROWSER", 720),
            "kream": ("크림", "COMMERCE", "HTML", 720),
            "naver": ("네이버", "CONTENT", "API", 360),
            "youtube": ("유튜브", "CONTENT", "API", 360),
        }
        total = len(source_meta) + len(products) + len(snapshots) + len(stats)
        done = 0

        def progress(stage, amount=0, message=""):
            nonlocal done
            done += amount
            if on_progress:
                on_progress({"stage": stage, "done": done, "total": total,
                             "pct": round(done * 100 / max(total, 1), 1),
                             "message": message})

        progress("sources", message="플랫폼 7곳 확인 중")
        sql = ["BEGIN;"]
        for code, (name, typ, method, interval) in source_meta.items():
            # 팀 RDS의 collection.source.created_at/updated_at 은 NOT NULL 이지만
            # 기본값이 없다. 칼럼을 생략하면 연결은 성공해도 첫 source 행에서
            # 전체 트랜잭션이 롤백된다.
            sql.append(f"INSERT INTO collection.source(code,name,source_type,collection_method,crawl_interval_minutes,status,created_at,updated_at) VALUES({_q(code)},{_q(name)},{_q(typ)},{_q(method)},{interval},'ACTIVE',now(),now()) ON CONFLICT(code) DO UPDATE SET name=excluded.name,collection_method=excluded.collection_method,crawl_interval_minutes=excluded.crawl_interval_minutes,updated_at=now();")
        sql.append("COMMIT;")
        result = self._run_sql("\n".join(sql), incoming)
        if not result.get("ok"):
            return {**result, "stage": "sources", "products": 0, "snapshots": 0}
        progress("dictionary", len(source_meta), "브랜드·카테고리 사전 연결 중")

        # 상품에서 실제 쓰인 브랜드와 표준 카테고리부터 만든다. 상품 행은 아래에서
        # 이 ID를 FK로 연결한다. 플랫폼 원문을 attributes 한 칸에 몰아넣지 않는다.
        dictionaries = []
        mapped = {}
        terms_by_product = {}
        product_by_key = {(p["source_code"], p["source_uid"]): p for p in products}
        for p in products:
            codes = CODEMAP.map_product(p)
            mapped[(p["source_code"], p["source_uid"])] = codes
            product_terms = _product_terms(p)
            terms_by_product[(p["source_code"], p["source_uid"])] = product_terms
            brand = str(p.get("brand_name") or "").strip()
            if _valid_brand(brand):
                dictionaries.append(
                    "INSERT INTO dictionary.brand(canonical_name,normalized_name,status,created_at,updated_at) "
                    f"VALUES({_q(brand)},{_q(_norm(brand))},'ACTIVE',now(),now()) "
                    "ON CONFLICT(normalized_name) DO UPDATE SET canonical_name=excluded.canonical_name,updated_at=now();")
            cat_code = codes.get("category_code")
            cat = getattr(CODEMAP, "_cat", {}).get(cat_code) if cat_code else None
            if cat:
                dictionaries.append(
                    "INSERT INTO dictionary.category(code,name,level,status,created_at,updated_at) "
                    f"VALUES({_q(cat_code)},{_q(cat.get('ko') or cat_code)},{int(cat.get('level') or 1)},'ACTIVE',now(),now()) "
                    "ON CONFLICT(code) DO UPDATE SET name=excluded.name,level=excluded.level,updated_at=now();")
            for term_type, canonical in product_terms:
                dictionaries.append(
                    "INSERT INTO dictionary.dictionary_term(term_type,canonical_name,normalized_name,status,first_seen_at,last_seen_at,created_at,updated_at) "
                    f"VALUES({_q(term_type)},{_q(canonical)},{_q(_norm(canonical))},'ACTIVE',now(),now(),now(),now()) "
                    "ON CONFLICT(term_type,normalized_name) DO UPDATE SET canonical_name=excluded.canonical_name,last_seen_at=now(),updated_at=now();")
                subtype = {"STYLE": "style", "MATERIAL": "material", "COLOR": "color",
                           "ITEM": "item", "DETAIL": "detail", "TPO": "tpo"}.get(term_type)
                if subtype:
                    dictionaries.append(
                        f"INSERT INTO dictionary.{subtype}(term_id,created_at,updated_at) "
                        "SELECT id,now(),now() FROM dictionary.dictionary_term "
                        f"WHERE term_type={_q(term_type)} AND normalized_name={_q(_norm(canonical))} "
                        "ON CONFLICT(term_id) DO UPDATE SET updated_at=now();")
        for start in range(0, len(dictionaries), 300):
            result = self._run_sql("BEGIN;\n" + "\n".join(dictionaries[start:start + 300]) + "\nCOMMIT;", incoming)
            if not result.get("ok"):
                return {**result, "stage": "dictionary", "products": 0, "snapshots": 0}

        progress("products", message="상품·플랫폼 연결 적재 시작")

        # psql 한 번에 수천 문장을 넣으면 끝날 때까지 진행률을 알 수 없다.
        # 100개 단위로 커밋해 실제 완료 건수를 화면에 전달한다.
        for start in range(0, len(products), 100):
            sql = ["BEGIN;"]
            chunk = products[start:start + 100]
            for p in chunk:
                # 이 네 값은 팀 RDS에 독립 컬럼/테이블이 없다. 그 경우만 JSON에
                # 보존한다. 브랜드·카테고리·랭킹·반응 지표는 여기 넣지 않는다.
                attrs = {k: v for k, v in {
                    "image_url": p.get("image_url"), "model_code": p.get("model_code"),
                    "colors": _json_list(p.get("color_names")),
                    "sizes": _json_list(p.get("size_names")),
                    "measurements": p.get("measurements"),
                    "release_date": p.get("release_date"),
                }.items() if v not in (None, "", [], {})}
                codes = mapped.get((p["source_code"], p["source_uid"]), {})
                brand_norm = _norm(p.get("brand_name")) if _valid_brand(p.get("brand_name")) else ""
                cat_code = codes.get("category_code") or ""
                market = ("RESALE" if p["source_code"] in
                          ("kream", "musinsa_used") else "RETAIL")
                sql.append(f"""WITH s AS (SELECT id FROM collection.source WHERE code={_q(p['source_code'])}), b AS (SELECT id FROM dictionary.brand WHERE normalized_name={_q(brand_norm)} LIMIT 1), c AS (SELECT id FROM dictionary.category WHERE code={_q(cat_code)} LIMIT 1), existing AS (SELECT product_id FROM commerce.product_source ps,s WHERE ps.source_id=s.id AND ps.source_product_id={_q(p['source_uid'])}), made AS (INSERT INTO commerce.product(canonical_name,normalized_name,brand_id,category_id,attributes,status,created_at,updated_at) SELECT {_q(p.get('name') or p['source_uid'])},{_q(_norm(p.get('name') or p['source_uid']))},(SELECT id FROM b),(SELECT id FROM c),{_q(json.dumps(attrs,ensure_ascii=False))}::jsonb,'ACTIVE',now(),now() WHERE NOT EXISTS(SELECT 1 FROM existing) RETURNING id), chosen AS (SELECT product_id id FROM existing UNION ALL SELECT id FROM made LIMIT 1), upd AS (UPDATE commerce.product pr SET canonical_name={_q(p.get('name') or p['source_uid'])},normalized_name={_q(_norm(p.get('name') or p['source_uid']))},brand_id=COALESCE((SELECT id FROM b),pr.brand_id),category_id=COALESCE((SELECT id FROM c),pr.category_id),attributes=pr.attributes || {_q(json.dumps(attrs,ensure_ascii=False))}::jsonb,updated_at=now() FROM chosen WHERE pr.id=chosen.id RETURNING pr.id) INSERT INTO commerce.product_source(product_id,source_id,source_product_id,market_type,product_url,first_seen_at,last_seen_at,status,created_at,updated_at) SELECT chosen.id,s.id,{_q(p['source_uid'])},{_q(market)},{_q(p.get('source_url'))},COALESCE({_q(p.get('first_seen_at'))}::timestamptz,now()),COALESCE({_q(p.get('last_seen_at'))}::timestamptz,now()),'ACTIVE',now(),now() FROM chosen,s ON CONFLICT(source_id,source_product_id) DO UPDATE SET product_url=excluded.product_url,last_seen_at=excluded.last_seen_at,updated_at=now();""")
                for term_type, canonical in terms_by_product.get(
                        (p["source_code"], p["source_uid"]), []):
                    sql.append(
                        "INSERT INTO commerce.product_term(product_id,term_id,created_at) "
                        "SELECT ps.product_id,t.id,now() FROM commerce.product_source ps "
                        "JOIN collection.source s ON s.id=ps.source_id "
                        "JOIN dictionary.dictionary_term t ON "
                        f"t.term_type={_q(term_type)} AND t.normalized_name={_q(_norm(canonical))} "
                        f"WHERE s.code={_q(p['source_code'])} AND ps.source_product_id={_q(p['source_uid'])} "
                        "ON CONFLICT(product_id,term_id) DO NOTHING;")
                    if term_type == "ITEM":
                        sql.append(
                            "UPDATE commerce.product pr SET item_term_id=i.term_id,updated_at=now() "
                            "FROM commerce.product_source ps,collection.source s,dictionary.item i,"
                            "dictionary.dictionary_term t WHERE ps.product_id=pr.id AND s.id=ps.source_id "
                            "AND i.term_id=t.id "
                            f"AND s.code={_q(p['source_code'])} AND ps.source_product_id={_q(p['source_uid'])} "
                            f"AND t.term_type='ITEM' AND t.normalized_name={_q(_norm(canonical))};")
            sql.append("COMMIT;")
            result = self._run_sql("\n".join(sql), incoming)
            if not result.get("ok"):
                return {**result, "stage": "products", "products": start,
                        "snapshots": 0}
            progress("products", len(chunk),
                     f"상품 {min(start + len(chunk), len(products)):,}/{len(products):,}건")

        # product_stat 에만 랭킹·평점·리뷰 수·좋아요 수가 있다. 예전 적재기는
        # price_snapshot 만 읽어 이 값들을 전부 NULL로 만들었다.
        for start in range(0, len(stats), 200):
            sql = ["BEGIN;"]
            chunk = stats[start:start + 200]
            for s in chunk:
                product_row = product_by_key.get((s["source_code"], s["source_uid"]), {})
                ranking = {"scope": s.get("rank_scope")} if s.get("rank_scope") else {}
                platform = {k: s.get(k) for k in (
                    "trade_count", "buy_count", "style_count", "review_dist",
                    "fit_note", "thickness_note", "quality_note") if s.get(k) not in (None, "")}
                sql.append(f"""INSERT INTO snapshot.product_source_snapshot(product_source_id,observed_at,list_price,sale_price,discount_rate,rank_position,ranking_scope,ranking_context,rating,review_count,like_count,platform_metrics,created_at) SELECT ps.id,{_q(s['captured_at'])}::timestamptz,{_q(product_row.get('retail_price'))}::numeric,{_q(s.get('price'))}::numeric,{_q(s.get('discount'))}::numeric,{_q(s.get('rank'))}::integer,{_q(s.get('rank_scope'))},{_q(json.dumps(ranking,ensure_ascii=False))}::jsonb,{_q(s.get('review_score'))}::numeric,{_q(s.get('review_count'))}::bigint,{_q(s.get('wish_count'))}::bigint,{_q(json.dumps(platform,ensure_ascii=False))}::jsonb,now() FROM commerce.product_source ps JOIN collection.source src ON src.id=ps.source_id WHERE src.code={_q(s['source_code'])} AND ps.source_product_id={_q(s['source_uid'])} ON CONFLICT(product_source_id,observed_at) DO UPDATE SET list_price=excluded.list_price,sale_price=excluded.sale_price,discount_rate=excluded.discount_rate,rank_position=excluded.rank_position,ranking_scope=excluded.ranking_scope,rating=excluded.rating,review_count=excluded.review_count,like_count=excluded.like_count,platform_metrics=excluded.platform_metrics;""")
            sql.append("COMMIT;")
            result = self._run_sql("\n".join(sql), incoming)
            if not result.get("ok"):
                return {**result, "stage": "stats", "products": len(products), "snapshots": start}
            progress("stats", len(chunk), f"랭킹·평점·리뷰 {min(start + len(chunk), len(stats)):,}/{len(stats):,}건")

        for start in range(0, len(snapshots), 200):
            sql = ["BEGIN;"]
            chunk = snapshots[start:start + 200]
            for s in chunk:
                sql.append(f"""INSERT INTO snapshot.product_source_snapshot(product_source_id,observed_at,list_price,sale_price,discount_rate,stock_status,ranking_context,platform_metrics,created_at) SELECT ps.id,{_q(s['captured_at'])}::timestamptz,{_q(s.get('initial_ask_price'))}::numeric,{_q(s.get('price'))}::numeric,{_q(s.get('discount'))}::numeric,{_q(s.get('availability_state'))},'{{}}'::jsonb,'{{}}'::jsonb,now() FROM commerce.product_source ps JOIN collection.source src ON src.id=ps.source_id WHERE src.code={_q(s['source_code'])} AND ps.source_product_id={_q(s['source_uid'])} ON CONFLICT(product_source_id,observed_at) DO UPDATE SET list_price=excluded.list_price,sale_price=excluded.sale_price,discount_rate=excluded.discount_rate,stock_status=excluded.stock_status;""")
            sql.append("COMMIT;")
            result = self._run_sql("\n".join(sql), incoming)
            if not result.get("ok"):
                return {**result, "stage": "snapshots", "products": len(products),
                        "snapshots": start}
            progress("snapshots", len(chunk),
                     f"가격 {min(start + len(chunk), len(snapshots)):,}/{len(snapshots):,}건")
        progress("done", message="AWS 적재 완료")
        return {**result, "products": len(products),
                "snapshots": len(snapshots) + len(stats), "stats": len(stats),
                "scope": "collection.source + dictionary.brand/category + commerce + snapshot"}
