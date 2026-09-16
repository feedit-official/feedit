"""
플랫폼 스키마로 내보내기 — 긁어 모은 것을 FEEDiT 스키마에 그대로 붓는다.

── 두 단계로 나눈 이유 ──
  ① 스키마 만들기  (한 번만)  → 01_schema.sql
  ② 데이터 내보내기 (매번)    → 02_seed.sql · 03_data.sql

표를 만드는 일과 값을 넣는 일은 성격이 다르다. 표는 한 번 만들면 끝이고,
값은 수집할 때마다 다시 넣는다. 섞어 두면 "다시 넣으면 표가 날아가나?"
하는 두려움 때문에 아무도 버튼을 못 누른다.

── ★ ID 곡예를 안 하는 법 ──
스키마의 product.id 는 IDENTITY 라 넣기 전에는 번호를 모른다.
보통은 INSERT ... RETURNING 으로 받아 와서 다음 표에 넣는데,
SQL 파일로 내보낼 때는 그게 안 된다.

그런데 product.slug 가 UNIQUE 다. **상품 열쇠를 slug 로 쓰면**
번호를 몰라도 이름으로 이을 수 있다.

    INSERT INTO product_source (product_id, ...)
    SELECT p.id, ... FROM product p WHERE p.slug = 'm-k87blk'

brand.slug · category.slug · lexicon_term(canonical,facet) 도 같은 방식이다.
덕분에 파일을 몇 번 돌려도 결과가 같다 (멱등).

── 안전 ──
모든 INSERT 에 ON CONFLICT 를 붙였다. 두 번 돌려도 안 깨지고,
이미 있는 값은 갱신된다. 지우는 문장은 하나도 없다.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .normalize import Normalizer, norm_brand

UTC = timezone.utc
SCHEMA_MARK = "-- FEEDiT schema v1"


# ── SQL 리터럴 ────────────────────────────────────────────────
def q(v) -> str:
    """SQL 값 한 개. 문자열은 작은따옴표를 두 번 써서 막는다."""
    if v is None or v == "":
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (dict, list)):
        return "'" + json.dumps(v, ensure_ascii=False).replace("'", "''") + "'"
    s = unicodedata.normalize("NFC", str(v))
    s = s.replace("\x00", "")          # 널바이트는 PG 가 거부한다
    return "'" + s.replace("'", "''") + "'"


def arr(vals) -> str:
    """TEXT[] 리터럴."""
    if not vals:
        return "'{}'"
    inner = ",".join('"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'
                     for v in vals)
    return "'{" + inner.replace("'", "''") + "}'"


def slugify(s: str, maxlen: int = 90) -> str:
    """상품 열쇠 → slug. 'm:K87-BLK' → 'm-k87-blk'

    한글은 그대로 둔다. PostgreSQL 은 유니코드를 잘 다루고,
    억지로 로마자로 바꾸면 서로 다른 상품이 같은 slug 가 된다.
    """
    s = unicodedata.normalize("NFC", str(s or "")).lower()
    s = re.sub(r"[^\w가-힣]+", "-", s, flags=re.UNICODE).strip("-")
    return (s[:maxlen] or "x")


class Exporter:
    def __init__(self, store, root: Path, schema_sql: Path | None = None):
        self.store = store
        self.root = Path(root)
        self.out = self.root / "export"
        self.out.mkdir(parents=True, exist_ok=True)
        self.schema_src = Path(schema_sql) if schema_sql else self._find_schema()
        self.norm = Normalizer(str(self.root / "config" / "lexicon.yaml"),
                               str(self.root / "config" / "category.yaml"))

    def _find_schema(self) -> Path | None:
        """schema.sql 을 찾는다. 프로젝트 구조가 바뀌어도 몇 군데는 뒤져 본다."""
        for p in (self.root / "config" / "schema.sql",
                  self.root.parent / "feedit-web" / "public" / "docs" / "schema.sql",
                  self.root / "schema.sql"):
            if p.exists():
                return p
        return None

    # ═══════════════════════════════════════════════════════════
    #  ① 스키마 만들기 — 한 번만
    # ═══════════════════════════════════════════════════════════
    # 표를 만들었다는 표시. 파일이 아니라 '넣었다'는 사실을 남긴다.
    DONE_MARK = "schema_done.json"

    def schema_state(self) -> dict:
        f = self.out / "01_schema.sql"
        done = self.out / self.DONE_MARK
        marked = {}
        if done.exists():
            try:
                marked = json.loads(done.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                marked = {}

        tables = 0
        if self.schema_src and self.schema_src.exists():
            tables = len(re.findall(
                r"CREATE TABLE", self.schema_src.read_text(encoding="utf-8")))

        return {
            "exists": f.exists(),
            "path": str(f),
            "name": f.name,
            "size_kb": (f.stat().st_size // 1024) if f.exists() else 0,
            "made_at": (datetime.fromtimestamp(f.stat().st_mtime, UTC)
                        .isoformat()[:19] if f.exists() else None),
            "source": str(self.schema_src) if self.schema_src else None,
            "source_found": bool(self.schema_src and self.schema_src.exists()),
            "tables": tables,
            # ★ '넣었다' 표시 — 이게 있으면 버튼을 잠근다.
            #   표를 만드는 파일을 두 번 넣을 일은 없다. 실수로 다시 눌러
            #   "혹시 데이터가 날아갔나" 하고 불안해할 이유를 없앤다.
            "installed": bool(marked.get("at")),
            "installed_at": marked.get("at"),
            "installed_by": marked.get("by"),
        }

    def mark_installed(self, by: str = "", undo: bool = False) -> dict:
        """'데이터베이스에 넣었다' 를 기록하거나 지운다."""
        done = self.out / self.DONE_MARK
        if undo:
            done.unlink(missing_ok=True)
            return {"ok": True, **self.schema_state()}
        done.write_text(json.dumps(
            {"at": datetime.now(UTC).isoformat()[:19], "by": by or None},
            ensure_ascii=False), encoding="utf-8")
        return {"ok": True, **self.schema_state()}

    def make_schema(self, force: bool = False) -> dict:
        f = self.out / "01_schema.sql"
        if f.exists() and not force:
            return {"ok": True, "already": True, **self.schema_state()}
        if not (self.schema_src and self.schema_src.exists()):
            return {"ok": False,
                    "error": "schema.sql 을 못 찾았습니다. "
                             "config/schema.sql 로 복사해 두면 찾습니다."}
        body = self.schema_src.read_text(encoding="utf-8")
        head = (
            f"{SCHEMA_MARK}\n"
            f"-- FEEDiT 플랫폼 스키마 — {datetime.now(UTC).isoformat()[:19]} 생성\n"
            f"-- 원본: {self.schema_src}\n"
            "--\n"
            "-- 쓰는 법 (한 번만):\n"
            "--   createdb feedit\n"
            "--   psql feedit -f 01_schema.sql\n"
            "--\n"
            "-- 그다음부터는 02_seed.sql · 03_data.sql 만 다시 부으면 됩니다.\n"
            "-- 이 파일은 표를 '만드는' 파일이라 다시 돌릴 일이 거의 없습니다.\n"
            "--\n"
            "-- ⚠ 필요한 확장: pg_trgm(오타 검색) · vector(pgvector, 의미 검색)\n"
            "--   vector 가 없으면 그 줄만 지우고 돌려도 나머지는 다 됩니다.\n\n")
        f.write_text(head + body, encoding="utf-8")
        return {"ok": True, "already": False, **self.schema_state()}

    # ═══════════════════════════════════════════════════════════
    #  ② 데이터 내보내기
    # ═══════════════════════════════════════════════════════════
    def _rows(self, sql, args=()):
        with self.store._lock:
            return [dict(r) for r in self.store._conn.execute(sql, args)]

    # ── 소스 ──
    def _sources(self, L):
        cfgs = sorted((self.root / "config").glob("*.yaml"))
        L.append("\n-- ── 수집처 ──")
        seen = set()
        for p in cfgs:
            if p.name.startswith("."):
                continue
            try:
                d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            code = d.get("code")
            if not code or code in seen or not isinstance(code, str):
                continue
            seen.add(code)
            kind = ("resale" if d.get("listing_type_default") in ("settled", "ask")
                    else "commerce")
            L.append(
                "INSERT INTO source (code, kind, display_name, base_url, enabled) "
                f"VALUES ({q(code)}, {q(kind)}, {q(d.get('name') or code)}, "
                f"{q(d.get('base_url'))}, TRUE) "
                "ON CONFLICT (code) DO UPDATE SET display_name=EXCLUDED.display_name, "
                "base_url=EXCLUDED.base_url;")
        # 소셜은 설정 파일이 없다
        for code, name, kind in (("youtube", "유튜브", "social"),
                                 ("naver", "네이버", "search")):
            if code not in seen:
                L.append(
                    "INSERT INTO source (code, kind, display_name, is_official_api, enabled) "
                    f"VALUES ({q(code)}, {q(kind)}, {q(name)}, TRUE, TRUE) "
                    "ON CONFLICT (code) DO NOTHING;")
        return len(seen)

    # ── 브랜드 ──
    def _brands(self, L):
        L.append("\n-- ── 브랜드 ──")
        L.append("--  ★ slug 는 표준 브랜드명이다. '아디다스'와 'Adidas' 가 같은 줄로 간다.")
        L.append("--    이게 없으면 무신사와 크림이 영영 안 만난다.")
        alias_path = self.root / "config" / "brand_alias.yaml"
        alias = {}
        if alias_path.exists():
            alias = (yaml.safe_load(alias_path.read_text(encoding="utf-8"))
                     or {}).get("alias") or {}

        # DB 에 실제로 나온 브랜드
        seen: dict[str, dict] = {}
        for r in self._rows("SELECT DISTINCT brand_name FROM staging_product "
                            "WHERE brand_name IS NOT NULL AND trim(brand_name)<>''"):
            nm = r["brand_name"].strip()
            canon = norm_brand(nm)
            e = seen.setdefault(canon, {"ko": None, "en": None, "aliases": set()})
            e["aliases"].add(nm)
            if re.search(r"[가-힣]", nm):
                e["ko"] = e["ko"] or nm
            else:
                e["en"] = e["en"] or nm

        for canon, names in alias.items():
            e = seen.setdefault(canon, {"ko": None, "en": None, "aliases": set()})
            for nm in names:
                e["aliases"].add(nm)
                if re.search(r"[가-힣]", nm):
                    e["ko"] = e["ko"] or nm
                else:
                    e["en"] = e["en"] or nm

        for canon, e in sorted(seen.items()):
            ko = e["ko"] or e["en"] or canon
            L.append(
                "INSERT INTO brand (name_ko, name_en, slug, aliases) "
                f"VALUES ({q(ko)}, {q(e['en'])}, {q(canon)}, {arr(sorted(e['aliases']))}) "
                "ON CONFLICT (slug) DO UPDATE SET "
                "name_ko=EXCLUDED.name_ko, name_en=COALESCE(EXCLUDED.name_en, brand.name_en), "
                "aliases=EXCLUDED.aliases;")
        return len(seen)

    # ── 카테고리 ──
    def _categories(self, L):
        L.append("\n-- ── 카테고리 ──")
        tree = self.norm.tree
        # 부모부터 넣어야 parent_id 를 걸 수 있다
        for lvl in (1, 2, 3):
            for slug, n in tree.items():
                if n.get("level") != lvl:
                    continue
                path = self.norm.path_of(slug)
                parent = n.get("parent")
                pid = (f"(SELECT id FROM category WHERE slug={q(parent)})"
                       if parent else "NULL")
                L.append(
                    "INSERT INTO category (parent_id, level, name, slug, path) "
                    f"VALUES ({pid}, {lvl}, {q(n['name'])}, {q(slug)}, {q(path)}) "
                    "ON CONFLICT (slug) DO UPDATE SET name=EXCLUDED.name, path=EXCLUDED.path;")

        L.append("\n-- 사이트 분류 → 우리 분류 대조표")
        for src_path, slug in self.norm.by_path.items():
            L.append(
                "INSERT INTO category_map (source_code, source_path, category_id, "
                "confidence, mapped_by) SELECT s.code, " + q(src_path) +
                f", c.id, 1.00, 'rule' FROM source s, category c WHERE c.slug={q(slug)} "
                "ON CONFLICT (source_code, source_path) DO NOTHING;")
        return len(tree)

    # ── 어휘 사전 ──
    def _lexicon(self, L):
        L.append("\n-- ── 어휘 사전 ──")
        L.append("--  스타일·핏·소재를 재는 자. 이게 EDIT 지표의 뿌리다.")
        lex = self.norm.lex
        exported = set()
        for canon, facet in sorted(lex.facet_of.items()):
            exported.add((canon, facet))
            trend = lex.trendable.get(canon, True)
            L.append(
                "INSERT INTO lexicon_term (canonical, facet, is_trendable) "
                f"VALUES ({q(canon)}, {q(facet)}, {q(trend)}) "
                "ON CONFLICT (canonical, facet) DO UPDATE SET "
                "is_trendable=EXCLUDED.is_trendable;")
        for surface, (canon, facet) in sorted(lex.surfaces.items()):
            kind = "canonical" if surface == canon else "variant"
            L.append(
                "INSERT INTO lexicon_surface (term_id, surface, kind) "
                f"SELECT id, {q(surface)}, {q(kind)} FROM lexicon_term "
                f"WHERE canonical={q(canon)} AND facet={q(facet)} "
                "ON CONFLICT (surface, term_id) DO NOTHING;")
        # 엑셀에서 만든 전체 기준 사전은 PostgreSQL에 직접 넣는다. 런타임 Lexicon은
        # 오탐 방지를 위해 한 표기를 한 축으로 우선하지만, DB는 동명이의 엔티티를
        # 둘 다 보존하고 is_ambiguous로 문맥 판정 대상으로 남겨야 한다.
        master_path = self.root / "config" / "lexicon_master.json"
        if master_path.exists():
            try:
                master = json.loads(master_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                master = {}
            ambiguous = set(master.get("ambiguous_surfaces") or [])
            from .lexicon import _norm as _lex_norm
            for term in master.get("terms") or []:
                canon, facet = term.get("canonical"), term.get("facet")
                if not canon or not facet:
                    continue
                exported.add((canon, facet))
                L.append(
                    "INSERT INTO lexicon_term (canonical, facet, is_trendable, description, note) "
                    f"VALUES ({q(canon)}, {q(facet)}, TRUE, {q(term.get('note'))}, "
                    f"{q('엑셀 기준 사전 · ' + str(term.get('sheet') or ''))}) "
                    "ON CONFLICT (canonical, facet) DO UPDATE SET "
                    "description=COALESCE(EXCLUDED.description, lexicon_term.description), "
                    "note=EXCLUDED.note;")
                for surface in term.get("surfaces") or [canon]:
                    kind = ("canonical" if surface == canon else
                            "en" if surface == term.get("english") else "variant")
                    is_amb = _lex_norm(surface) in ambiguous
                    L.append(
                        "INSERT INTO lexicon_surface (term_id, surface, kind, is_ambiguous) "
                        f"SELECT id, {q(surface)}, {q(kind)}, {q(is_amb)} FROM lexicon_term "
                        f"WHERE canonical={q(canon)} AND facet={q(facet)} "
                        "ON CONFLICT (surface, term_id) DO UPDATE SET "
                        "kind=EXCLUDED.kind, is_ambiguous=EXCLUDED.is_ambiguous;")
        # 2026-08-27 작업 중 구형 목업과 현재 배포 화면을 혼동해 잠시 차단했던
        # 실제 14종 라벨을 복구한다. 반복 실행해도 같은 상태가 된다.
        L.append(
            "UPDATE lexicon_term SET status='active', is_trendable=TRUE, merged_into=NULL "
            "WHERE facet='style' AND canonical IN "
            "('바이크코어','긱시크','Y2K','스트릿웨어');")
        return len(exported)

    # ── 상품 · 연결 · 가격 · 태그 ──
    def _products(self, L):
        rows = self._rows(
            "SELECT * FROM staging_product WHERE source_code NOT LIKE 'test%'")
        groups: dict[str, list[dict]] = {}
        keyed = {}
        for r in rows:
            k = self.norm.product_key(r)
            keyed[(r["source_code"], r["source_uid"])] = k
            groups.setdefault(k["key"], []).append(r)

        L.append(f"\n-- ── 상품 {len(groups)}건 (수집 {len(rows)}건을 묶은 결과) ──")
        L.append("--  ★ slug 가 곧 상품 열쇠다. 번호를 몰라도 이걸로 이을 수 있다.")

        for key, members in groups.items():
            # 대표값은 '가장 많이 채워진' 줄에서 고른다
            best = max(members, key=lambda m: sum(
                1 for f in ("name", "brand_name", "model_code", "retail_price",
                            "image_url", "category_path") if m.get(f)))
            items = [h["term"] for h in self.norm.lex.tag(
                name=best.get("name") or "",
                category=best.get("category_path") or "")["hits"]
                if h["facet"] == "item"]
            cat = self.norm.category(source_path=best.get("category_path") or "",
                                     item_terms=items)
            brand = norm_brand(best.get("brand_name") or "")
            slug = slugify(key)
            bid = (f"(SELECT id FROM brand WHERE slug={q(brand)})" if brand else "NULL")
            cid = (f"(SELECT id FROM category WHERE slug={q(cat['slug'])})"
                   if cat.get("slug") else "NULL")
            L.append(
                "INSERT INTO product (brand_id, name, slug, category_id, retail_price, "
                "image_url, size_names) VALUES ("
                f"{bid}, {q(best.get('name') or key)}, {q(slug)}, {cid}, "
                f"{q(best.get('retail_price'))}, {q(best.get('image_url'))}, "
                f"{arr(json.loads(best.get('size_names') or '[]'))}) "
                "ON CONFLICT (slug) DO UPDATE SET "
                "name=EXCLUDED.name, brand_id=COALESCE(EXCLUDED.brand_id, product.brand_id), "
                "category_id=COALESCE(EXCLUDED.category_id, product.category_id), "
                "retail_price=COALESCE(EXCLUDED.retail_price, product.retail_price), "
                "image_url=COALESCE(EXCLUDED.image_url, product.image_url), "
                "last_seen_at=now();")
        return groups, keyed

    def _product_sources(self, L, groups, keyed):
        L.append("\n-- ── 상품 ↔ 수집처 연결 ──")
        L.append("--  match_method 로 '어떻게 묶었는지'를 남긴다. 점수가 낮은 것만")
        L.append("--  뽑아서 사람이 확인할 수 있게 하려는 것이다.")
        n = 0
        for key, members in groups.items():
            slug = slugify(key)
            for m in members:
                k = keyed[(m["source_code"], m["source_uid"])]
                L.append(
                    "INSERT INTO product_source (product_id, source_code, source_uid, "
                    "source_url, source_name, match_method, match_score) "
                    f"SELECT p.id, {q(m['source_code'])}, {q(m['source_uid'])}, "
                    f"{q(m.get('source_url'))}, {q(m.get('name'))}, "
                    f"{q(k['method'])}, {q(k['score'])} FROM product p "
                    f"WHERE p.slug={q(slug)} "
                    "ON CONFLICT (source_code, source_uid) DO UPDATE SET "
                    "source_url=EXCLUDED.source_url, match_method=EXCLUDED.match_method, "
                    "match_score=EXCLUDED.match_score;")
                n += 1
        return n

    def _prices(self, L, keyed):
        L.append("\n-- ── 가격 ──")
        L.append("--  커머스 정가는 price_snapshot, 리세일 체결·호가는 resale_listing.")
        L.append("--  절대 섞지 않는다 — 섞이면 리세일 지수가 통째로 부푼다.")
        n = 0
        # 커머스 정가 + 인기 지표를 하루 한 줄로
        stats = {}
        for s in self._rows("SELECT * FROM product_stat"):
            stats[(s["source_code"], s["source_uid"], s["stat_date"])] = s
        for (code, uid, day), s in stats.items():
            if (code, uid) not in keyed:
                continue
            L.append(
                "INSERT INTO price_snapshot (product_source_id, observed_on, "
                "sale_price, discount_rate, review_count, like_count, rating_avg) "
                f"SELECT ps.id, {q(day)}, {q(s.get('price'))}, {q(s.get('discount'))}, "
                f"{q(s.get('review_count'))}, {q(s.get('wish_count'))}, "
                f"{q(s.get('review_score'))} FROM product_source ps "
                f"WHERE ps.source_code={q(code)} AND ps.source_uid={q(uid)} "
                "ON CONFLICT (product_source_id, observed_on) DO UPDATE SET "
                "sale_price=COALESCE(EXCLUDED.sale_price, price_snapshot.sale_price), "
                "review_count=COALESCE(EXCLUDED.review_count, price_snapshot.review_count), "
                "like_count=COALESCE(EXCLUDED.like_count, price_snapshot.like_count), "
                "rating_avg=COALESCE(EXCLUDED.rating_avg, price_snapshot.rating_avg);")
            n += 1

        # 리세일 체결·호가
        for r in self._rows(
                "SELECT * FROM resale_listing WHERE source_code NOT LIKE 'test%' "
                "AND listing_type IN ('settled','ask')"):
            puid = r["source_uid"].split(":")[0]
            if (r["source_code"], puid) not in keyed:
                continue
            L.append(
                "INSERT INTO resale_listing (product_id, source_code, source_uid, "
                "listing_type, size_name, price, settled_at, listed_at) "
                f"SELECT ps.product_id, {q(r['source_code'])}, {q(r['source_uid'])}, "
                f"{q(r['listing_type'])}, {q(r.get('size_name'))}, {q(r.get('price'))}, "
                f"{q(r.get('settled_at'))}, {q(r.get('listed_at'))} "
                f"FROM product_source ps WHERE ps.source_code={q(r['source_code'])} "
                f"AND ps.source_uid={q(puid)} "
                "ON CONFLICT DO NOTHING;")
            n += 1
        return n

    def _tags(self, L, groups):
        L.append("\n-- ── 상품 ↔ 어휘 ──")
        L.append("--  field 로 '어디서 나온 말인지'를 남긴다. 사이트 태그에서 나온")
        L.append("--  '오버핏'과 상품명에서 나온 '오버핏'은 신뢰도가 다르다.")
        n = 0
        for key, members in groups.items():
            slug = slugify(key)
            best = max(members, key=lambda m: len(m.get("name") or ""))
            # 묶인 상품 중 **아무나** 태그를 갖고 있으면 다 같이 쓴다.
            # 무신사에만 #발레코어 가 붙어 있어도 크림 쪽 같은 옷에 붙는다.
            from .normalize import site_tags as _st
            tags = []
            for m in members:
                for t in _st(m):
                    if t not in tags:
                        tags.append(t)
            res = self.norm.lex.tag(name=best.get("name") or "", tags=tags,
                                    category=best.get("category_path") or "")
            for h in res["hits"]:
                for field, w in h["fields"].items():
                    L.append(
                        "INSERT INTO product_term_hit (product_id, term_id, field, weight) "
                        f"SELECT p.id, t.id, {q(field)}, {q(round(w, 2))} "
                        f"FROM product p, lexicon_term t "
                        f"WHERE p.slug={q(slug)} AND t.canonical={q(h['term'])} "
                        f"AND t.facet={q(h['facet'])} "
                        "ON CONFLICT (product_id, term_id, field) DO UPDATE SET "
                        "weight=EXCLUDED.weight;")
                    n += 1
        return n

    def _texts(self, L):
        rows = self._rows(
            "SELECT * FROM text_document "
            "WHERE COALESCE(quality_status, 'active')='active' LIMIT 20000")
        if not rows:
            return []
        L.append(f"\n-- ── 텍스트 {len(rows)}건 ──")
        for t in rows:
            vid = (t.get("product_uid") or "")
            video = vid[3:] if vid.startswith("yt:") else None
            L.append(
                "INSERT INTO text_document (source_code, source_uid, doc_kind, video_id, body, "
                "published_at, like_count, rating, author_hash) SELECT "
                f"{q(t['source_code'])}, {q(str(t['id']))}, {q(t['doc_kind'])}, "
                f"{q(video)}, {q(t['body'])}, "
                f"{q(t.get('published_at'))}, {q(t.get('like_count') or 0)}, "
                f"{q(t.get('rating'))}, {q(t.get('author_hash'))} "
                "WHERE NOT EXISTS (SELECT 1 FROM text_document d WHERE "
                f"d.source_code={q(t['source_code'])} AND d.doc_kind={q(t['doc_kind'])} "
                f"AND d.source_uid={q(str(t['id']))}) "
                "ON CONFLICT DO NOTHING;")
        return rows


    # ── 수집 이력 (L0) ──
    def _runs(self, L):
        rows = self._rows("SELECT * FROM crawl_run WHERE source_code NOT LIKE 'test%' "
                          "ORDER BY id DESC LIMIT 500")
        if not rows:
            return 0
        L.append(f"\n-- ── 수집 이력 {len(rows)}건 ──")
        L.append("--  언제 무엇을 얼마나 긁었나. 지표가 이상할 때 '그날 수집이")
        L.append("--  덜 됐던 것'인지 '값이 진짜 변한 것'인지 가르는 근거가 된다.")
        for r in rows:
            status = r.get("status") or "done"
            L.append(
                "INSERT INTO crawl_run (source_code, target, started_at, ended_at, "
                "status, fetched_count, error_count, blocked, note) SELECT "
                f"{q(r['source_code'])}, {q(r.get('target'))}, {q(r.get('started_at'))}, "
                f"{q(r.get('ended_at'))}, {q(status)}, "
                f"{q(r.get('fetched_count') or 0)}, {q(r.get('error_count') or 0)}, "
                f"{q(bool(r.get('blocked')))}, {q(r.get('note'))} "
                "WHERE NOT EXISTS (SELECT 1 FROM crawl_run c WHERE "
                f"c.source_code={q(r['source_code'])} "
                f"AND c.target IS NOT DISTINCT FROM {q(r.get('target'))} "
                f"AND c.started_at={q(r.get('started_at'))} "
                f"AND c.ended_at IS NOT DISTINCT FROM {q(r.get('ended_at'))} "
                f"AND c.status={q(status)} "
                f"AND c.note IS NOT DISTINCT FROM {q(r.get('note'))}) "
                "ON CONFLICT DO NOTHING;")
        return len(rows)

    # ── 유튜브 ──
    def _youtube(self, L):
        try:
            vids = self._rows(
                "SELECT * FROM yt_video "
                "WHERE COALESCE(quality_status, 'active')='active'")
            stats = self._rows(
                "SELECT s.* FROM yt_video_stat s JOIN yt_video v "
                "ON v.video_id=s.video_id "
                "WHERE COALESCE(v.quality_status, 'active')='active'")
        except Exception:
            return 0
        try:
            transcripts = self._rows(
                "SELECT t.* FROM yt_transcript t JOIN yt_video v ON v.video_id=t.video_id "
                "WHERE COALESCE(v.quality_status, 'active')='active'")
        except Exception:
            transcripts = []
        try:
            corrections = self._rows("SELECT * FROM yt_transcript_correction")
            asr_rows = self._rows("SELECT * FROM yt_asr_queue")
        except Exception:
            corrections, asr_rows = [], []
        if not vids:
            return 0
        L.append(f"\n-- ── 유튜브 영상 {len(vids)}건 ──")
        chans = {}
        for v in vids:
            if v.get("channel_id"):
                chans[v["channel_id"]] = v.get("channel_title") or v["channel_id"]
        for cid, title in chans.items():
            L.append("INSERT INTO yt_channel (channel_id, title) "
                     f"VALUES ({q(cid)}, {q(title)}) ON CONFLICT (channel_id) DO NOTHING;")
        for v in vids:
            L.append(
                "INSERT INTO yt_video (video_id, channel_id, title, description, url, "
                "published_at,has_caption,transcript_status,transcript_error,"
                "transcript_checked_at) VALUES ("
                f"{q(v['video_id'])}, {q(v.get('channel_id'))}, "
                f"{q(v.get('title') or v['video_id'])}, {q(v.get('description'))}, "
                f"{q('https://www.youtube.com/watch?v=' + v['video_id'])}, "
                f"{q(v.get('published_at'))}, {q(bool(v.get('has_caption')))}, "
                f"{q(v.get('transcript_status') or 'none')},"
                f"{q(v.get('transcript_error'))},{q(v.get('transcript_checked_at'))}) "
                "ON CONFLICT (video_id) DO UPDATE SET title=EXCLUDED.title,"
                "description=EXCLUDED.description,has_caption=EXCLUDED.has_caption,"
                "transcript_status=EXCLUDED.transcript_status,"
                "transcript_error=EXCLUDED.transcript_error,"
                "transcript_checked_at=EXCLUDED.transcript_checked_at;")
        for st in stats:
            L.append(
                "INSERT INTO yt_video_stat (video_id, observed_on, view_count, "
                f"like_count, comment_count) VALUES ({q(st['video_id'])}, "
                f"{q(st['stat_date'])}, {q(st.get('view_count'))}, "
                f"{q(st.get('like_count'))}, {q(st.get('comment_count'))}) "
                "ON CONFLICT (video_id, observed_on) DO UPDATE SET "
                "view_count=EXCLUDED.view_count, like_count=EXCLUDED.like_count, "
                "comment_count=EXCLUDED.comment_count;")
        for tr in transcripts:
            segments = tr.get("segments") or "[]"
            L.append(
                "INSERT INTO yt_transcript (video_id,origin,lang,full_text,segments) VALUES ("
                f"{q(tr['video_id'])},{q(tr['origin'])},{q(tr.get('lang'))},"
                f"{q(tr['full_text'])},{q(segments)}::jsonb) ON CONFLICT (video_id) DO UPDATE SET "
                "origin=EXCLUDED.origin,lang=EXCLUDED.lang,full_text=EXCLUDED.full_text,"
                "segments=EXCLUDED.segments;")
        for row in corrections:
            L.append(
                "INSERT INTO yt_transcript_correction "
                "(video_id,start_sec,duration_sec,term_id,original,canonical,facet,method,"
                "confidence,status) SELECT "
                f"{q(row['video_id'])},{q(row.get('start'))},{q(row.get('dur'))},id,"
                f"{q(row['original'])},{q(row['canonical'])},{q(row['facet'])},"
                f"{q(row['method'])},{q(row['confidence'])},{q(row['status'])} "
                f"FROM lexicon_term WHERE term_key={q(row['term_key'])};")
        for row in asr_rows:
            L.append(
                "INSERT INTO yt_asr_queue(video_id,status,reason,priority,attempts,last_error) "
                f"VALUES ({q(row['video_id'])},{q(row['status'])},{q(row.get('reason'))},"
                f"{q(row.get('priority'))},{q(row.get('attempts'))},{q(row.get('last_error'))}) "
                "ON CONFLICT (video_id) DO UPDATE SET status=EXCLUDED.status,"
                "reason=EXCLUDED.reason,priority=EXCLUDED.priority,"
                "attempts=EXCLUDED.attempts,last_error=EXCLUDED.last_error;")
        return len(vids)

    # ── 구매의향 규칙 ──
    def _intent_rules(self, L):
        from .intent import LABELS, RULES
        L.append("\n-- ── 구매의향 판정 규칙 ──")
        L.append("--  '감성'이 아니라 '구매 의향'으로 본다. 설계서가 정한 라벨 6개.")
        L.append("--  규칙을 DB 에도 남기는 이유: 지표가 왜 그렇게 나왔는지")
        L.append("--  나중에 되짚으려면 그때 쓴 규칙을 알아야 한다.")
        for code, pattern in RULES:
            L.append(
                "INSERT INTO intent_rule (intent_code, pattern, weight, example) "
                f"VALUES ({q(code)}, {q(pattern)}, {q(LABELS[code]['w'])}, "
                f"{q(LABELS[code]['name'])}) ON CONFLICT DO NOTHING;")
        return len(RULES)

    # ── 텍스트에 붙은 어휘·의도 ──
    def _text_analysis(self, L, texts):
        """본문에서 어휘를 뽑고 구매의향을 붙인다.

        text_document.id 를 모르므로 본문으로 되찾는다. 본문이 길어서
        통째로 비교하면 느리니 앞 200자만 쓴다 — 그 정도면 충분히 유일하다.
        """
        from .intent import classify
        if not texts:
            return 0, 0
        L.append("\n-- ── 텍스트 분석 (어휘 · 구매의향) ──")
        n_hit = n_int = 0
        for t in texts:
            body = t.get("body") or ""
            if not body.strip():
                continue
            where = (f"(SELECT id FROM text_document WHERE source_code={q(t['source_code'])} "
                     f"AND doc_kind={q(t['doc_kind'])} "
                     f"AND source_uid={q(str(t['id']))} LIMIT 1)")
            # 후기·댓글은 자유 글이다. 상품명 기준으로 뽑으면 오탐이 쏟아진다.
            for h in self.norm.lex.tag(free=body)["hits"]:
                L.append(
                    "INSERT INTO text_term_hit (text_document_id, term_id, hit_count) "
                    f"SELECT {where}, t.id, 1 FROM lexicon_term t "
                    f"WHERE t.canonical={q(h['term'])} AND t.facet={q(h['facet'])} "
                    f"AND {where} IS NOT NULL "
                    "ON CONFLICT (text_document_id, term_id) DO NOTHING;")
                n_hit += 1
            r = classify(body)
            for lab in r["labels"]:
                from .intent import LABELS
                L.append(
                    "INSERT INTO text_intent (text_document_id, intent_code, weight) "
                    f"SELECT {where}, {q(lab)}, {q(LABELS[lab]['w'])} "
                    f"WHERE {where} IS NOT NULL "
                    "ON CONFLICT (text_document_id, intent_code) DO NOTHING;")
                n_int += 1
        return n_hit, n_int

    def _llm_analysis(self, L, texts):
        """저장된 Luna 분석을 플랫폼 DB의 같은 text_document에 연결한다."""
        if not texts:
            return 0
        try:
            rows = self._rows("SELECT * FROM text_llm_analysis")
        except Exception:
            return 0
        by_id = {int(t["id"]): t for t in texts}
        if rows:
            L.append("\n-- ── LLM 텍스트 분석 (GPT-5.6-luna) ──")
        n = 0
        for a in rows:
            t = by_id.get(int(a["text_document_id"]))
            if not t:
                continue
            where = (f"(SELECT id FROM text_document WHERE source_code={q(t['source_code'])} "
                     f"AND doc_kind={q(t['doc_kind'])} "
                     f"AND source_uid={q(str(t['id']))} LIMIT 1)")
            def js(name):
                raw = a.get(name) or "[]"
                try:
                    raw = json.dumps(json.loads(raw), ensure_ascii=False)
                except (TypeError, ValueError):
                    raw = "[]"
                return f"{q(raw)}::jsonb"
            L.append(
                "INSERT INTO text_llm_analysis (text_document_id, model, prompt_version, "
                "fashion_relevance, sentiment, sentiment_score, purchase_intents, related_terms, "
                "evidence, confidence, response_id, input_tokens, output_tokens, analyzed_at) SELECT "
                f"{where}, {q(a['model'])}, {q(a['prompt_version'])}, {q(a['fashion_relevance'])}, "
                f"{q(a['sentiment'])}, {q(a['sentiment_score'])}, {js('purchase_intents')}, "
                f"{js('related_terms')}, {js('evidence')}, {q(a['confidence'])}, "
                f"{q(a.get('response_id'))}, {q(a.get('input_tokens') or 0)}, "
                f"{q(a.get('output_tokens') or 0)}, {q(a.get('analyzed_at'))} "
                f"WHERE {where} IS NOT NULL "
                "ON CONFLICT (text_document_id, model, prompt_version) DO UPDATE SET "
                "fashion_relevance=EXCLUDED.fashion_relevance, sentiment=EXCLUDED.sentiment, "
                "sentiment_score=EXCLUDED.sentiment_score, purchase_intents=EXCLUDED.purchase_intents, "
                "related_terms=EXCLUDED.related_terms, evidence=EXCLUDED.evidence, "
                "confidence=EXCLUDED.confidence, response_id=EXCLUDED.response_id, "
                "input_tokens=EXCLUDED.input_tokens, output_tokens=EXCLUDED.output_tokens, "
                "analyzed_at=EXCLUDED.analyzed_at;")
            n += 1
        return n

    def _entity_analysis(self, L, texts):
        if not texts:
            return 0, 0, 0
        try:
            resolutions = self._rows("SELECT * FROM text_entity_resolution")
            mentions = self._rows("SELECT * FROM text_entity_mention")
            opinions = self._rows("SELECT * FROM text_entity_opinion")
        except Exception:
            return 0, 0, 0
        by_id = {int(t["id"]): t for t in texts}
        def text_id(local_id):
            t = by_id.get(int(local_id))
            if not t:
                return None
            return (f"(SELECT id FROM text_document WHERE source_code={q(t['source_code'])} "
                    f"AND doc_kind={q(t['doc_kind'])} AND source_uid={q(str(t['id']))} LIMIT 1)")
        if resolutions or mentions or opinions:
            L.append("\n-- ── 검색축 엔티티 해결 상태·언급 ──")
        nr = nm = 0
        for r in resolutions:
            where = text_id(r["text_document_id"])
            if not where:
                continue
            unresolved = r.get("unresolved_terms") or "[]"
            L.append(
                "INSERT INTO text_entity_resolution (text_document_id,model,prompt_version,status,"
                "no_signal_reason,unresolved_terms,resolved_at) SELECT "
                f"{where},{q(r['model'])},{q(r['prompt_version'])},{q(r['status'])},"
                f"{q(r.get('no_signal_reason'))},{q(unresolved)}::jsonb,{q(r.get('resolved_at'))} "
                f"WHERE {where} IS NOT NULL ON CONFLICT (text_document_id,model,prompt_version) "
                "DO UPDATE SET status=EXCLUDED.status,no_signal_reason=EXCLUDED.no_signal_reason,"
                "unresolved_terms=EXCLUDED.unresolved_terms,resolved_at=EXCLUDED.resolved_at;")
            nr += 1
        for m in mentions:
            where = text_id(m["text_document_id"])
            if not where:
                continue
            term = (f"(SELECT id FROM lexicon_term WHERE canonical={q(m['canonical'])} "
                    f"AND facet={q(m['facet'])} LIMIT 1)")
            L.append(
                "INSERT INTO text_entity_mention (text_document_id,term_id,surface,mention_role,"
                "status,confidence,evidence,extraction_method,model,prompt_version) SELECT "
                f"{where},{term},{q(m.get('surface'))},{q(m['mention_role'])},{q(m['status'])},"
                f"{q(m['confidence'])},{q(m.get('evidence'))},{q(m['extraction_method'])},"
                f"{q(m['model'])},{q(m['prompt_version'])} WHERE {where} IS NOT NULL AND {term} IS NOT NULL "
                "ON CONFLICT (text_document_id,term_id,mention_role,extraction_method,model,prompt_version) "
                "DO UPDATE SET status=EXCLUDED.status,confidence=EXCLUDED.confidence,"
                "evidence=EXCLUDED.evidence,surface=EXCLUDED.surface;")
            nm += 1
        no = 0
        for o in opinions:
            where = text_id(o["text_document_id"])
            if not where:
                continue
            term = (f"(SELECT id FROM lexicon_term WHERE canonical={q(o['canonical'])} "
                    f"AND facet={q(o['facet'])} LIMIT 1)")
            intents = q(o.get("purchase_intents") or "[]") + "::jsonb"
            evidence = q(o.get("evidence") or "[]") + "::jsonb"
            L.append(
                "INSERT INTO text_entity_opinion (text_document_id,term_id,sentiment,"
                "sentiment_score,purchase_intents,evidence,confidence,model,prompt_version,"
                "analyzed_at) SELECT "
                f"{where},{term},{q(o['sentiment'])},{q(o['sentiment_score'])},{intents},"
                f"{evidence},{q(o['confidence'])},{q(o['model'])},{q(o['prompt_version'])},"
                f"{q(o.get('analyzed_at'))} WHERE {where} IS NOT NULL AND {term} IS NOT NULL "
                "ON CONFLICT (text_document_id,term_id,model,prompt_version) DO UPDATE SET "
                "sentiment=EXCLUDED.sentiment,sentiment_score=EXCLUDED.sentiment_score,"
                "purchase_intents=EXCLUDED.purchase_intents,evidence=EXCLUDED.evidence,"
                "confidence=EXCLUDED.confidence,analyzed_at=EXCLUDED.analyzed_at;")
            no += 1
        return nr, nm, no

    def _metrics(self, L, version="feedit-l2-v2-shadow"):
        """로컬의 versioned L2 스냅샷을 플랫폼 term_id에 다시 연결한다."""
        try:
            daily = self._rows("SELECT * FROM metric_term_daily WHERE metric_version=?",
                               (version,))
            assoc = self._rows("SELECT * FROM metric_term_assoc_daily WHERE metric_version=?",
                               (version,))
            sentiment = self._rows(
                "SELECT * FROM metric_term_sentiment_daily WHERE metric_version=?",
                (version,))
        except Exception:
            return 0, 0, 0
        if daily or assoc or sentiment:
            L.append(f"\n-- ── L2 지표 스냅샷 ({version}) ──")
        def term(canonical, facet):
            return (f"(SELECT id FROM lexicon_term WHERE canonical={q(canonical)} "
                    f"AND facet={q(facet)} LIMIT 1)")
        for r in daily:
            tid = term(r["canonical"], r["facet"])
            L.append(
                "INSERT INTO term_daily_metric (term_id,source_code,observed_on,raw_count,"
                "log_value,pct_rank,level,ma7,ma28,momentum,temp,share_pct) SELECT "
                f"{tid},{q(r['source_code'])},{q(r['observed_on'])},{q(r['raw_count'])},"
                f"{q(r.get('log_value'))},{q(r.get('pct_rank'))},{q(r.get('level'))},"
                f"{q(r.get('ma7'))},{q(r.get('ma28'))},{q(r.get('momentum'))},"
                f"{q(r.get('temp'))},{q(r.get('share_pct'))} WHERE {tid} IS NOT NULL "
                "ON CONFLICT (term_id,source_code,observed_on) DO UPDATE SET "
                "raw_count=EXCLUDED.raw_count,log_value=EXCLUDED.log_value,"
                "pct_rank=EXCLUDED.pct_rank,level=EXCLUDED.level,ma7=EXCLUDED.ma7,"
                "ma28=EXCLUDED.ma28,momentum=EXCLUDED.momentum,temp=EXCLUDED.temp,"
                "share_pct=EXCLUDED.share_pct;")
        for r in assoc:
            base = term(r["base_canonical"], r["base_facet"])
            other = term(r["assoc_canonical"], r["assoc_facet"])
            L.append(
                "INSERT INTO term_assoc_daily (base_term_id,assoc_term_id,observed_on,co_count,"
                "lift,pmi,score_v,facet,rank_in_facet,is_new) SELECT "
                f"{base},{other},{q(r['observed_on'])},{q(r['co_count'])},{q(r.get('lift'))},"
                f"{q(r.get('pmi'))},{q(r.get('score_v'))},{q(r['assoc_facet'])},"
                f"{q(r.get('rank_in_facet'))},{q(bool(r.get('is_new')))} "
                f"WHERE {base} IS NOT NULL AND {other} IS NOT NULL "
                "ON CONFLICT (base_term_id,assoc_term_id,observed_on) DO UPDATE SET "
                "co_count=EXCLUDED.co_count,lift=EXCLUDED.lift,pmi=EXCLUDED.pmi,"
                "score_v=EXCLUDED.score_v,facet=EXCLUDED.facet,"
                "rank_in_facet=EXCLUDED.rank_in_facet,is_new=EXCLUDED.is_new;")
        for r in sentiment:
            tid = term(r["canonical"], r["facet"])
            L.append(
                "INSERT INTO term_sentiment_daily (term_id,observed_on,n_total,weighted_sum,"
                "pos_count,neg_count,index_value,pos_pct,neg_pct,top_pos_intent,top_pos_count,"
                "top_neg_intent,top_neg_count) SELECT "
                f"{tid},{q(r['observed_on'])},{q(r['n_total'])},{q(r.get('weighted_sum'))},"
                f"{q(r.get('pos_count'))},{q(r.get('neg_count'))},{q(r.get('index_value'))},"
                f"{q(r.get('pos_pct'))},{q(r.get('neg_pct'))},{q(r.get('top_pos_intent'))},"
                f"{q(r.get('top_pos_count'))},{q(r.get('top_neg_intent'))},"
                f"{q(r.get('top_neg_count'))} WHERE {tid} IS NOT NULL "
                "ON CONFLICT (term_id,observed_on) DO UPDATE SET n_total=EXCLUDED.n_total,"
                "weighted_sum=EXCLUDED.weighted_sum,pos_count=EXCLUDED.pos_count,"
                "neg_count=EXCLUDED.neg_count,index_value=EXCLUDED.index_value,"
                "pos_pct=EXCLUDED.pos_pct,neg_pct=EXCLUDED.neg_pct,"
                "top_pos_intent=EXCLUDED.top_pos_intent,top_pos_count=EXCLUDED.top_pos_count,"
                "top_neg_intent=EXCLUDED.top_neg_intent,top_neg_count=EXCLUDED.top_neg_count;")
        return len(daily), len(assoc), len(sentiment)

    # ═══════════════════════════════════════════════════════════
    def export(self) -> dict:
        """02_seed.sql (기준 정보) · 03_data.sql (수집분) 을 만든다."""
        stamp = datetime.now(UTC).isoformat()[:19]
        from .metrics import MetricAggregator, SHADOW_VERSION, SHADOW_SOURCE_WEIGHTS
        metric_build = MetricAggregator(
            self.store, SHADOW_VERSION, lexicon=self.norm.lex,
            weights=SHADOW_SOURCE_WEIGHTS).rebuild()

        seed = [f"-- FEEDiT 기준 정보 — {stamp}",
                "-- 수집처 · 브랜드 · 카테고리 · 어휘 사전.",
                "-- 값이 아니라 '자'에 해당하는 것들이라 데이터보다 먼저 넣습니다.",
                "BEGIN;"]
        n_src = self._sources(seed)
        n_brand = self._brands(seed)
        n_cat = self._categories(seed)
        n_lex = self._lexicon(seed)
        n_rule = self._intent_rules(seed)
        seed.append("COMMIT;")

        data = [f"-- FEEDiT 수집 데이터 — {stamp}",
                "-- ⚠ 02_seed.sql 을 먼저 넣어야 합니다 (브랜드·카테고리·어휘를 참조).",
                "BEGIN;"]
        groups, keyed = self._products(data)
        n_link = self._product_sources(data, groups, keyed)
        n_price = self._prices(data, keyed)
        n_tag = self._tags(data, groups)
        n_run = self._runs(data)
        n_yt = self._youtube(data)
        texts = self._texts(data)
        n_text = len(texts)
        n_hit, n_int = self._text_analysis(data, texts)
        n_llm = self._llm_analysis(data, texts)
        n_resolution, n_mention, n_opinion = self._entity_analysis(data, texts)
        n_metric, n_assoc, n_sentiment = self._metrics(data, SHADOW_VERSION)
        data.append("COMMIT;")

        f_seed = self.out / "02_seed.sql"
        f_data = self.out / "03_data.sql"
        f_seed.write_text("\n".join(seed), encoding="utf-8")
        f_data.write_text("\n".join(data), encoding="utf-8")

        readme = self.out / "README.md"
        readme.write_text(_README.format(
            stamp=stamp, products=len(groups), links=n_link, brands=n_brand,
            terms=n_lex, prices=n_price, tags=n_tag, texts=n_text), encoding="utf-8")

        return {
            "ok": True, "at": stamp,
            "files": [
                {"name": f_seed.name, "kb": f_seed.stat().st_size // 1024,
                 "what": f"수집처 {n_src} · 브랜드 {n_brand} · 카테고리 {n_cat} "
                         f"· 어휘 {n_lex} · 판정규칙 {n_rule}"},
                {"name": f_data.name, "kb": f_data.stat().st_size // 1024,
                 "what": f"상품 {len(groups)} · 연결 {n_link} · 가격 {n_price} "
                         f"· 태그 {n_tag} · 텍스트 {n_text} · 영상 {n_yt} "
                         f"· 수집이력 {n_run}"},
                {"name": readme.name, "kb": max(1, readme.stat().st_size // 1024),
                 "what": "넣는 방법"},
            ],
            "counts": {"products": len(groups), "links": n_link, "brands": n_brand,
                       "categories": n_cat, "terms": n_lex, "prices": n_price,
                       "tags": n_tag, "texts": n_text, "sources": n_src,
                       "videos": n_yt, "runs": n_run, "rules": n_rule,
                       "text_terms": n_hit, "intents": n_int,
                       "llm_analyses": n_llm, "entity_resolutions": n_resolution,
                       "entity_mentions": n_mention, "entity_opinions": n_opinion,
                       "term_metrics": n_metric,
                       "term_associations": n_assoc, "term_sentiments": n_sentiment,
                       "metric_documents": metric_build["documents"]},
            "dir": str(self.out),
        }


_README = """# FEEDiT 내보내기 — {stamp}

크롤러가 모은 것을 플랫폼 스키마에 부을 수 있는 SQL 입니다.

## 넣는 순서

```bash
createdb feedit
psql feedit -f 01_schema.sql   # 표 만들기 — 처음 한 번만
psql feedit -f 02_seed.sql     # 기준 정보 (브랜드·카테고리·어휘)
psql feedit -f 03_data.sql     # 수집 데이터
```

2·3번은 **몇 번 다시 돌려도 안전합니다.** 모든 INSERT 에 `ON CONFLICT` 를
붙였고, 지우는 문장은 하나도 없습니다.

## 이번에 담긴 것

| 무엇 | 개수 |
|---|---:|
| 상품 (묶은 뒤) | {products} |
| 상품↔수집처 연결 | {links} |
| 브랜드 | {brands} |
| 어휘 | {terms} |
| 가격·지표 줄 | {prices} |
| 상품 태그 | {tags} |
| 텍스트 | {texts} |

## 어떻게 이어져 있나

번호(IDENTITY)를 모르는 채로 SQL 파일을 만들어야 해서, **이름으로 잇습니다.**

- `product.slug` = 상품 열쇠 (`m-k87blk` = 모델번호로 묶인 상품)
- `brand.slug` = 표준 브랜드명 (`adidas` — '아디다스'와 'Adidas'가 같은 줄)
- `category.slug` = 우리 분류 (`top-tee`)

그래서 `product_source` 는 이렇게 들어갑니다.

```sql
INSERT INTO product_source (product_id, ...)
SELECT p.id, ... FROM product p WHERE p.slug = 'm-k87blk'
```

## 확인해 볼 것

```sql
-- 여러 사이트에 걸쳐 묶인 상품 (리세일 지수가 가능한 상품)
SELECT p.name, count(DISTINCT ps.source_code) AS 사이트수
FROM product p JOIN product_source ps ON ps.product_id = p.id
GROUP BY p.id, p.name HAVING count(DISTINCT ps.source_code) > 1
ORDER BY 사이트수 DESC;

-- 추정으로 묶인 것 — 사람이 확인할 대상
SELECT * FROM product_source WHERE match_score < 1.0 ORDER BY match_score;

-- 태그가 많이 붙은 어휘
SELECT t.canonical, t.facet, count(*) FROM product_term_hit h
JOIN lexicon_term t ON t.id = h.term_id
GROUP BY t.canonical, t.facet ORDER BY count(*) DESC LIMIT 30;
```
"""
