"""
수동 저장본 가져오기 — 브라우저로 저장한 HTML 을 읽어 DB 에 넣는다.

── 왜 필요한가 ──
무신사는 공개 robots 규칙과 별도로 2026-08-31 직접 수집 허가를 받았다.
자동 수집과 함께 사람이 브라우저로 저장한 파일을 다시 읽는 경로도 유지한다.
→ 사람이 저장한 파일을 읽는 이 경로를 열어 두면, 규칙을 지키면서도
  데이터를 모을 수 있다. 요청을 단 한 번도 보내지 않는다.

가상 스크롤 때문에 한 번에 다 안 담기는 페이지가 있어서(무신사 랭킹은 72개씩),
같은 페이지를 여러 번 저장해 겹쳐 넣게 된다. 중복은 여기서 걸러진다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import parse_qs, urlparse, urlsplit

from .adapter import ConfigAdapter, SiteConfig, to_int
from .stats import from_record as stat_fields
from .stats import retail_fields

# 브라우저가 저장할 때 남기는 원본 주소 주석
_SAVED_FROM = re.compile(r'saved from url=\(\d+\)(\S+)')


@dataclass
class ImportResult:
    filename: str
    site: Optional[str] = None
    kind: str = "unknown"          # list | detail | unknown
    url: str = ""
    products: int = 0
    listings: int = 0
    trades: int = 0
    skipped: int = 0               # 이미 있어서 건너뛴 것
    error: str = ""
    label: str = ""                # 어느 분류 페이지에서 왔나 (주소에서 읽음)
    style: str = ""                # 어느 스타일을 검색해서 담았나
    sample: list = field(default_factory=list)

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["ok"] = not self.error
        return d


_CANON = re.compile(
    r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', re.I)
_OGURL = re.compile(
    r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)', re.I)


def saved_from_url(html: str) -> str:
    """이 파일이 어느 주소였는지 알아낸다.

    ① 브라우저가 남기는 'saved from url' 주석
    ② 없으면 <link rel=canonical>  ← 저장 방식에 따라 주석이 안 붙는 파일이 많다
    ③ 그래도 없으면 og:url
    주소를 알아야 목록인지 상세인지 정확히 가를 수 있다.
    """
    head = html[:200_000]
    for rx in (_SAVED_FROM, _CANON, _OGURL):
        m = rx.search(head)
        if m:
            u = m.group(1).strip()
            if u.startswith(("http://", "https://", "/")):
                return u
    return ""


def _detail_re(cfg: SiteConfig):
    """상세 주소인지 알아볼 정규식. detail_url_template 에서 만든다.

    '/products/{id}' → '/products/<뭔가>'
    """
    tmpl = (cfg.list_page or {}).get("detail_url_template") or ""
    if "{id}" not in tmpl:
        return None
    head = re.escape(tmpl.split("{id}")[0])
    return re.compile(head + r"[^/?#]+")


def _list_type(cfg: SiteConfig) -> str:
    """목록에 적힌 가격의 성격.

    리세일(크림·후르츠)에서는 '지금 살 수 있는 값' = 호가(ask) 다.
    커머스(무신사·지그재그)에서는 정상 판매가 = retail 이다.
    체결가(settled)로는 절대 들어가면 안 된다 — 지수가 부푼다.
    """
    return "retail" if cfg.listing_type_default == "retail" else "ask"


#  카테고리 슬러그 → 스타일 진행판이 쓰는 칸 이름
#  ★ 왜 필요한가
#    주소에서 카테고리 필터를 빼고 담으면 '어느 파츠인지' 가 안 온다.
#    그러면 진행판이 못 세고, 담긴 게 없는 것처럼 보인다.
#    상품 이름에 '부츠'·'스커트' 가 있으니 거기서 유추하면 된다.
_SLUG_TO_CELL = {
    "top": "상의", "outer": "아우터", "bottom": "바지",
    "shoes": "신발", "dress": "원피스/스커트",
}


def guess_cell(name: str, norm=None) -> str:
    """상품 이름으로 '상의·아우터·바지·신발·원피스/스커트' 중 무엇인지 짐작한다."""
    if not name:
        return ""
    try:
        if norm is None:
            from pathlib import Path

            from .normalize import Normalizer
            root = Path(__file__).resolve().parent.parent / "config"
            norm = Normalizer(str(root / "lexicon.yaml"), str(root / "category.yaml"))
        items = [c for c, f in norm.lex.extract(name) if f == "item"]
        got = norm.category(item_terms=items)
        slug = got.get("slug") or ""
    except Exception:
        return ""
    if not slug:
        return ""
    if slug.startswith("bottom-skirt"):
        return "원피스/스커트"        # 스커트는 원피스 칸과 같이 본다
    return _SLUG_TO_CELL.get(slug.split("-")[0], "")


PROBLEMS = None          # 서버가 켤 때 꽂아 준다


def _merge_tags(existing, style: str):
    """사이트 태그와 '검색해서 담은 스타일' 을 합친다. 중복은 뺀다."""
    out = list(existing or [])
    if isinstance(existing, str):
        out = [x.strip() for x in existing.split(",") if x.strip()]
    st = (style or "").strip()
    if st and st not in out:
        out.append(st)
    return out or None


def label_from_url(url: str, cfg: SiteConfig) -> str:
    """저장본 주소에서 '어느 분류 페이지였나'를 읽는다.

    ★ 왜 필요한가
      커머스 사이트의 랭킹 목록에는 카테고리가 안 적혀 있다. 카드에는
      브랜드·이름·가격뿐이다. 그래서 무신사 상품 1,304개의 카테고리가
      전부 비어 있었다 — 분류별로 나눠서 저장했는데도 그렇다.

      하지만 **어느 페이지에서 가져왔는지는 주소에 남아 있다.**
      ?gf=F&categoryCode=001000 이면 여성 상의다. 그걸 읽어서 붙인다.

    설정에 이렇게 적으면 동작한다 (없으면 그냥 넘어간다):

        list_page:
          label_from_url:
            join: " "                    # 조각을 잇는 글자
            parts:
              - param: gf                # 주소의 ?gf= 값
                map: {A: "", M: 남성, F: 여성}
              - param: categoryCode
                prefix: 3                # 앞 3글자만 본다 (001000 → 001)
                map: {"001": 상의, "002": 아우터, "003": 바지, "020": 원피스/스커트}
    """
    rule = (cfg.list_page or {}).get("label_from_url")
    if not rule or not url:
        return ""
    try:
        qs = parse_qs(urlparse(url).query)
    except Exception:
        return ""
    out = []
    for part in rule.get("parts") or []:
        vals = qs.get(str(part.get("param") or ""))
        if not vals:
            continue
        v = str(vals[0])
        if part.get("prefix"):
            v = v[:int(part["prefix"])]
        # map 에 없는 값은 버린다. 모르는 코드를 그대로 붙이면
        # '001000 상의' 같은 카테고리가 생겨서 나중에 다 손봐야 한다.
        got = (part.get("map") or {}).get(v)
        if got:
            out.append(str(got))
    return (rule.get("join") or " ").join(out).strip()


def looks_like_detail(url: str, cfg: SiteConfig) -> bool:
    rx = _detail_re(cfg)
    return bool(url and rx and rx.search(url))


def detect_site(html: str, configs: list[SiteConfig]) -> Optional[SiteConfig]:
    """어느 사이트에서 저장한 파일인지 알아낸다.

    ① 저장 주석의 주소로 판단 (가장 확실)
    ② 없으면 본문에 그 사이트 도메인이 몇 번 나오는지로 판단
    """
    # 무신사 신품과 USED는 같은 도메인을 쓴다. 도메인 비교보다 먼저 페이지
    # 내부의 comId/category 109를 확인해야 신품 무신사로 잘못 들어가지 않는다.
    try:
        from .musinsa_used import is_used_html
        if is_used_html(html):
            used = next((c for c in configs if c.code == "musinsa_used"), None)
            if used:
                return used
    except Exception:
        pass

    url = saved_from_url(html)
    if url:
        host = urlsplit(url).netloc.lower()
        for cfg in configs:
            base = urlsplit(cfg.base_url).netloc.lower()
            # www 유무를 무시하고 뒤에서 맞춰 본다
            if host and base and (host.endswith(base) or base.endswith(host)
                                  or host.split(".")[-2:] == base.split(".")[-2:]):
                return cfg

    head = html[:400_000]
    best, best_n = None, 0
    for cfg in configs:
        base = urlsplit(cfg.base_url).netloc.lower()
        core = ".".join(base.split(".")[-2:])          # musinsa.com
        n = head.lower().count(core)
        if n > best_n:
            best, best_n = cfg, n
    return best if best_n >= 3 else None


def import_html(html: str, cfg: SiteConfig, store, filename: str = "",
                dry_run: bool = False, force_kind: str = "",
                page_label: str = "", style: str = "") -> ImportResult:
    """파일 한 장을 읽어 저장한다. 목록인지 상세인지는 알아서 판단한다.

    force_kind 로 못박을 수 있다 — 북마클릿은 목록 카드만 모아 보내므로
    한 개만 담겼을 때도 상세로 오해하지 않게 'list' 를 넘긴다.
    """
    res = ImportResult(filename=filename, site=cfg.code, url=saved_from_url(html))

    # 무신사 USED는 신품과 같은 URL/도메인이지만 JSON 구조와 가격의 의미가
    # 다르다. 전용 파서에서 호가·등급·판매완료를 명시적으로 분리한다.
    if cfg.code == "musinsa_used":
        return _import_musinsa_used(html, cfg, store, res, dry_run, style)
    ad = ConfigAdapter(cfg)

    # ── 목록인지 상세인지 판단 ──
    #  ★ 카드 개수만으로 정하면 안 된다. 상세 페이지에도 '연관 상품' 캐러셀이
    #    깔려 있어서, 후르츠 상세 한 장이 목록 35건으로 잡혔었다.
    #    주소가 상세 형태면 그걸 먼저 믿는다 — 주소가 가장 확실한 단서다.
    is_detail_url = looks_like_detail(res.url, cfg) and force_kind != "list"

    # 사람이 고른 라벨이 없으면 주소에서 읽어 본다.
    # 이 한 줄이 없어서 무신사 카테고리가 통째로 비어 있었다.
    if not page_label:
        page_label = label_from_url(res.url, cfg)
    res.label = page_label
    # ★ 스타일별로 담을 때는 **검색어가 곧 정답 태그**다.
    #   '발레코어' 를 검색해 나온 옷은 발레코어다 — 사람이 고른 것이므로
    #   상품명에서 짐작하는 것보다 훨씬 믿을 만하다. 사이트 태그와 같은
    #   자리(site_tags)에 넣어 가중치 1.0 을 받게 한다.
    res.style = style

    cards = []
    if not is_detail_url:
        try:
            cards = ad.parse_list_records(html)
        except Exception:
            cards = []
        cards = [c for c in cards if c.get("source_uid")]

    if len(cards) >= (1 if force_kind == "list" else 2):   # 카드가 여럿이면 목록
        res.kind = "list"
        # 이름을 못 읽은 카드가 있으면 생김새를 [점검] 탭에 한 장 남긴다
        blind = [c for c in cards if not c.get("name") and c.get("_card_html")]
        if blind and PROBLEMS is not None and not dry_run:
            PROBLEMS.add(
                title=f"카드에서 상품명을 못 읽었습니다 ({len(blind)}/{len(cards)}건)",
                source_code=cfg.code, where="가져오기",
                detail=(f"{filename} — 셀렉터가 이 화면과 안 맞습니다. "
                        f"아래 '기술 정보' 의 HTML 을 보고 고쳐야 합니다."),
                raw=blind[0]["_card_html"])

        for c in cards:
            c.pop("_card_html", None)
            uid = str(c["source_uid"])
            if dry_run:
                res.products += 1
                if len(res.sample) < 5:
                    res.sample.append({k: c.get(k) for k in
                                       ("source_uid", "brand", "name", "price", "rank")})
                continue
            store.put_raw(cfg.code, "product_card", uid, c,
                          url=c.get("source_url", ""), http_status=200)
            store.upsert_product(
                cfg.code, uid,
                source_url=c.get("source_url"),
                name=c.get("name"),
                brand_name=c.get("brand"),
                image_url=c.get("image_url"),
                retail_price=to_int(c.get("retail_price")),
                # ★ 사이트가 카테고리를 안 주면 '우리가 어느 페이지에서
                #   가져왔는지'가 유일한 근거다. 그동안 이걸 버리고 있었다.
                #   '여성 상의' 랭킹에서 온 것은 여성 상의가 맞다.
                category_path=(c.get("category_path") or page_label
                               or (guess_cell(c.get("name") or "") if style else None)
                               or None),
                site_tags=_merge_tags(c.get("site_tags"), style),
            )
            store.put_stat(cfg.code, uid, **stat_fields(cfg.code, c))
            res.products += 1
            price = to_int(c.get("price"))
            if price:
                # ★ 목록의 가격은 '지금 살 수 있는 값'이지 팔린 값이 아니다.
                #   크림의 기본값(settled)을 그대로 쓰면 호가가 체결가로 둔갑해
                #   리세일 지수가 통째로 부푼다. 러너도 같은 이유로 ask 로 넣는다.
                #   커머스(무신사·지그재그)는 애초에 정상 판매가라 retail 이다.
                store.put_listing(cfg.code, f"{uid}:list", price, _list_type(cfg))
                res.listings += 1
            if len(res.sample) < 5:
                res.sample.append({k: c.get(k) for k in
                                   ("source_uid", "brand", "name", "price", "rank")})
        return res

    # ── 상세로 읽어 본다 ──
    url = res.url or ""
    try:
        rec = ad.parse_detail(html, url=url)
    except Exception as e:
        res.error = f"읽지 못했습니다: {e}"
        return res

    uid = str(rec.get("source_uid") or "")
    if not uid and url:
        uid = ad._uid_from(url, cfg.list_page or {}) or ""
    if not uid:
        res.error = ("상품 번호를 찾지 못했습니다. 목록도 상세도 아닌 페이지이거나, "
                     "브라우저에서 '웹페이지, 전체'로 저장하지 않은 파일일 수 있습니다.")
        return res

    res.kind = "detail"
    if dry_run:
        res.products = 1
        res.trades = len(rec.get("trades") or [])
        res.sample.append({k: rec.get(k) for k in
                           ("source_uid", "brand", "name", "model_code",
                            "retail_price", "price")})
        return res

    store.put_raw(cfg.code, "product", uid, {"parsed": rec, "manual_import": True},
                  url=url, http_status=200)
    store.upsert_product(
        cfg.code, uid,
        source_url=url or rec.get("source_url"),
        name=rec.get("name"), name_en=rec.get("name_en"),
        brand_name=rec.get("brand"),
        category_path=rec.get("category_path"),
        **_retail(rec, store),
        image_url=rec.get("image_url"),
        model_code=rec.get("model_code"),
        measurements=rec.get("measurements") or None,
        # ★ 사이트가 붙여 준 태그 (#발레코어 …) — 스타일 태깅의 정답지
        site_tags=_merge_tags(rec.get("site_tags"), style),
    )
    # 상세에만 있는 지표 (무신사 후기 수·만족도 등)
    store.put_stat(cfg.code, uid, **stat_fields(cfg.code, rec))
    res.products = 1

    price = to_int(rec.get("price"))
    if price:
        store.put_listing(cfg.code, f"{uid}:now", price,
                          rec.get("listing_type", cfg.listing_type_default))
        res.listings += 1
    for i, t in enumerate(rec.get("trades") or []):
        if not t.get("price"):
            continue
        store.put_listing(cfg.code, f"{uid}:t{i}", t["price"], "settled",
                          size_name=t.get("size_name"), settled_at=t.get("settled_at"))
        res.trades += 1

    res.sample.append({k: rec.get(k) for k in
                       ("source_uid", "brand", "name", "model_code",
                        "retail_price", "price")})
    return res


def _import_musinsa_used(html, cfg, store, res, dry_run=False, style=""):
    from .musinsa_used import parse_detail, parse_list

    rec = parse_detail(html)
    records = [rec] if rec else parse_list(html)
    res.kind = "detail" if rec else "list"
    if not records:
        res.error = "무신사 USED 상품 JSON을 찾지 못했습니다. 웹페이지 전체 저장본인지 확인하세요."
        return res

    for item in records:
        uid = str(item.get("source_uid") or "")
        if not uid:
            continue
        if dry_run:
            res.products += 1
        else:
            store.put_raw(cfg.code, "product" if rec else "product_card", uid, item,
                          url=item.get("source_url") or res.url, http_status=200)
            store.upsert_product(
                cfg.code, uid, source_url=item.get("source_url"), name=item.get("name"),
                brand_name=item.get("brand"), category_path=item.get("category_path"),
                image_url=item.get("image_url"),
                site_tags=_merge_tags(None, style),
            )
            store.put_stat(cfg.code, uid, **stat_fields(cfg.code, item))
            price = to_int(item.get("price"))
            if price:
                store.put_listing(cfg.code, f"{uid}:now", price, "ask",
                                  condition=item.get("condition_grade"))
                store.put_price_snapshot(
                    cfg.code, uid, price,
                    initial_ask_price=to_int(item.get("initial_ask_price")),
                    discount=to_int(item.get("discount")),
                    condition_grade=item.get("condition_grade"),
                    availability_state=item.get("availability_state"),
                )
                res.listings += 1
            res.products += 1
        if len(res.sample) < 5:
            res.sample.append({k: item.get(k) for k in
                               ("source_uid", "brand", "name", "price",
                                "condition_grade", "availability_state")})
    return res


def _retail(rec, store):
    """발매가를 원화로 맞춰 돌려준다. 환율기는 저장소에 붙어 있다."""
    fx = getattr(store, "fx", None)
    return retail_fields(rec, fx)
