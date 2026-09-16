"""
정규화 (L0 → L1) — 사이트별로 긁어 온 것을 '우리 어휘'로 바꾼다.

지금까지 크롤러는 L0(원본 그대로)만 만들고 있었다. 플랫폼 스키마는
L1(정규화)을 전제로 짜여 있는데 그 사이가 비어 있었다. 이 파일이 그 사이다.

하는 일 세 가지:

  ① 카테고리 통일    다섯 사이트의 제각각인 분류 → 우리 slug 하나
  ② 어휘 태깅        태그·상품명 → 스타일·핏·소재·아이템
  ③ 상품 동일시      흩어진 다섯 개의 '같은 옷' → 하나의 product_key

★ ③이 이 파일의 핵심이다.
  무신사 4923323 · 크림 231041 · 후르츠 68q7g 가 같은 옷일 수 있다.
  이걸 못 이으면 '무신사 정가 대비 크림 체결가'라는 리세일 지수가
  아예 성립하지 않는다. 플랫폼 기능의 절반이 여기에 달려 있다.

★ 근거를 반드시 남긴다 (match_method / match_score)
  느슨하게 묶으면 커버리지는 오르지만 틀린 것도 같이 묶인다.
  나중에 "이건 왜 묶였지?"를 되짚을 수 없으면 손을 못 댄다.
  그래서 어떤 방법으로 몇 점에 묶었는지를 같이 적는다. 점수가 낮은 것만
  뽑아서 사람이 보면 된다.
"""

from __future__ import annotations

import json

import re
import unicodedata
from pathlib import Path

import yaml

from .lexicon import Lexicon

# ── 상품명에서 지워야 할 것들 ──────────────────────────────────
#  이름으로 상품을 맞추려면 먼저 '같은 옷인데 다르게 보이게 하는 것'을
#  걷어내야 한다. 실제 데이터에서 확인한 것만 넣었다.
_NOISE = [
    (re.compile(r"\[[^\]]{0,40}\]"), " "),          # [MADE] [컬렉션] [누적5천장]
    (re.compile(r"\([^)]{0,40}\)"), " "),           # (BLACK) (free)
    (re.compile(r"[│|/]\s*[A-Z0-9\-]{4,}\s*$"), " "),   # / KQ6863
    (re.compile(r"\b\d+(개|장|만장|천장)\b"), " "),      # 누적 1만장
    (re.compile(r"[★☆♥♡🌊✨]+"), " "),
    # 색상 꼬리 — '- 블랙' '_Blue Latte' 는 같은 옷의 다른 색이다.
    # 색까지 같아야 같은 상품인 건 맞지만, 리세일 지수는 색을 안 가리고
    # 묶는 편이 쓸모 있다. 색은 따로 색 칸에 남긴다.
    (re.compile(r"[-_]\s*[가-힣A-Za-z ]{2,14}$"), " "),
    # 크림이 이름 꼬리에 붙이는 것들
    (re.compile(r"[-–]\s*(KR|US|JP|EU)\s*사이즈.*$"), " "),
    (re.compile(r"\(논?\s*마킹.*$"), " "),
]

# ★ 사이트마다 브랜드를 이름에 넣기도, 빼기도 한다.
#     무신사  '와플 클래식 트랙탑'            (브랜드 없음)
#     크림    '아디다스 아디컬러 파이어버드 트랙 탑'  (브랜드 있음)
#   이걸 안 맞추면 같은 옷도 절대 안 만난다.
_BRAND_HEAD = re.compile(r"^\s*(?:\(W\)|\(M\))?\s*")
_SPACE = re.compile(r"\s+")


def site_tags(row: dict) -> list:
    """staging_product.site_tags 를 목록으로. 글자로 저장돼 있어도 받아 준다."""
    v = row.get("site_tags") if isinstance(row, dict) else None
    if not v:
        return []
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:
            return [x.strip() for x in v.split(",") if x.strip()]
    return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []


def norm_name(s: str, brand: str = "") -> str:
    """'[MADE]릴카 언발 오프숄더 반팔 티셔츠' → '릴카언발오프숄더반팔티셔츠'

    brand 를 주면 이름 앞뒤의 브랜드 표기를 떼어낸다.
    """
    s = unicodedata.normalize("NFC", str(s or ""))
    if brand:
        # 브랜드의 모든 표기를 지운다 ('아디다스'·'Adidas' 둘 다).
        if not _BRAND:
            _load_brands()
        canon = norm_brand(brand)
        forms = {brand} | {k for k, v in _BRAND.items() if v == canon}
        for f in sorted(forms, key=len, reverse=True):
            if len(f) < 2:
                continue
            s = re.sub(re.escape(f), " ", s, flags=re.I)
    for pat, rep in _NOISE:
        s = pat.sub(rep, s)
    s = _SPACE.sub(" ", s).strip().lower()
    # 쇼핑몰마다 곡선 따옴표 방향이 달라도 같은 상품명으로 본다.
    # 예: 1990‘s / 1990’s old Stussy Archive shirts
    return re.sub(r"[\s\-_·,\.'‘’`]+", "", s)


def norm_model(s: str) -> str:
    """'K87-BLK' · 'k87 blk' → 'K87BLK'"""
    s = unicodedata.normalize("NFC", str(s or "")).upper()
    return re.sub(r"[^A-Z0-9]", "", s)


# ── 브랜드 대조표 ────────────────────────────────────────────
#  '아디다스' 와 'Adidas' 를 같게 본다. 이게 없으면 무신사와 크림이
#  영원히 안 만나고, 리세일 지수(정가↔체결가)가 통째로 성립하지 않는다.
_BRAND: dict[str, str] = {}


def _load_brands(path="config/brand_alias.yaml"):
    global _BRAND
    try:
        d = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return
    for canon, names in (d.get("alias") or {}).items():
        for nm in names:
            _BRAND[_bare(nm)] = canon


def _bare(s: str) -> str:
    s = unicodedata.normalize("NFC", str(s or "")).lower()
    return re.sub(r"[\s\-_\.'‘’`&,]+", "", s)


def norm_brand(s: str) -> str:
    """'Nike' · '나이키' → 'nike'.

    대조표에 없으면 표기만 정리해서 돌려준다 — 같은 표기끼리만 묶인다.
    억지로 비슷한 걸 붙이면 엉뚱한 브랜드의 시세가 섞인다.
    """
    if not _BRAND:
        _load_brands()
    b = _bare(s)
    return _BRAND.get(b, b)


class Normalizer:
    def __init__(self, lex_path="config/lexicon.yaml",
                 cat_path="config/category.yaml"):
        self.lex = Lexicon(lex_path)
        d = yaml.safe_load(Path(cat_path).read_text(encoding="utf-8")) or {}
        self.tree = {n["slug"]: n for n in (d.get("tree") or [])}
        self.by_path = d.get("path") or {}
        # 긴 것부터 맞춘다. '데님 팬츠' 가 '팬츠' 보다 먼저 걸려야 한다.
        self._path_keys = sorted(self.by_path, key=len, reverse=True)
        self.by_page = d.get("page") or {}
        self.by_item = d.get("item") or {}
        self.conf = d.get("confidence") or {}

    # ── 카테고리 ─────────────────────────────────────────────
    def category(self, *, source_path: str = "", page_label: str = "",
                 item_terms: list[str] | None = None) -> dict:
        """세 갈래로 정한다. 위에서부터 이긴다."""
        sp = unicodedata.normalize("NFC", str(source_path or ""))
        if sp:
            for k in self._path_keys:
                if k in sp:
                    return {"slug": self.by_path[k], "by": "path",
                            "confidence": self.conf.get("path", 1.0), "evidence": k}

        pl = unicodedata.normalize("NFC", str(page_label or "")).strip()
        if pl in self.by_page:
            hit = self.by_page[pl]
            return {"slug": hit["slug"], "by": "page", "gender": hit.get("gender"),
                    "confidence": self.conf.get("page", 0.9), "evidence": pl}

        for t in (item_terms or []):
            if t in self.by_item:
                return {"slug": self.by_item[t], "by": "item",
                        "confidence": self.conf.get("item", 0.7), "evidence": t}
        return {"slug": None, "by": None, "confidence": 0.0, "evidence": ""}

    def path_of(self, slug: str) -> str:
        """'top-tee' → '상의 > 티셔츠'"""
        n = self.tree.get(slug)
        if not n:
            return ""
        parts = [n["name"]]
        while n.get("parent"):
            n = self.tree.get(n["parent"]) or {}
            if not n:
                break
            parts.insert(0, n["name"])
        return " > ".join(parts)

    # ── 상품 동일시 ───────────────────────────────────────────
    def product_key(self, row: dict) -> dict:
        """이 상품에 붙일 열쇠와, 그 근거.

        1단계 model  모델번호가 같으면 같은 옷이다. 거의 틀리지 않는다.
        2단계 name   브랜드 + 정리한 상품명. 색·프로모션 문구를 걷어낸 뒤 비교.
        3단계 self   못 묶었다. 자기 자신만으로 열쇠를 만든다 (나중에 사람이).
        """
        mc = norm_model(row.get("model_code") or "")
        if len(mc) >= 5:
            # 5자 미만은 'PRO3' 같은 것이 섞여 위험하다.
            return {"key": f"m:{mc}", "method": "model", "score": 1.0}

        br = norm_brand(row.get("brand_name") or "")
        nm = norm_name(row.get("name") or "", row.get("brand_name") or "")
        if br and len(nm) >= 6:
            return {"key": f"n:{br}:{nm}", "method": "name", "score": 0.8}

        return {"key": f"s:{row.get('source_code')}:{row.get('source_uid')}",
                "method": "self", "score": 0.0}

    # ── 한 상품 통째로 ────────────────────────────────────────
    def run(self, row: dict, *, tags=(), page_label="") -> dict:
        # ★ 사이트가 붙여 준 태그를 빠뜨리지 않는다
        #   site_tags 는 DB 에 JSON 글자로 들어 있다. 꺼내서 넘기지 않으면
        #   애써 긁어 온 '#발레코어' 가 아무 데도 안 쓰인다.
        t = self.lex.tag(name=row.get("name") or "",
                         tags=list(tags) + site_tags(row),
                         category=row.get("category_path") or "")
        items = [h["term"] for h in t["hits"] if h["facet"] == "item"]
        cat = self.category(source_path=row.get("category_path") or "",
                            page_label=page_label, item_terms=items)
        key = self.product_key(row)
        return {"tags": t["hits"], "unknown": t["unknown"],
                "category": cat, "category_path": self.path_of(cat["slug"] or ""),
                "match": key}
