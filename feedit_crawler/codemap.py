"""우리 값을 팀 AWS 코드로 옮겨 적는다.

── 무엇을 하는가 ────────────────────────────────────────────
우리는 사이트에서 **글자**를 긁어온다 — '엄브로', '셔츠', '새틴'.
AWS 표는 **코드**를 받는다 — BRAND_UMBRO, TOP_SHIRT, MATERIAL_SATIN.
그 사이를 잇는 것이 전부다. 원본은 `config/aws_codes.json`
(팀이 준 FEEDIT_DICT_UNIQUE_VALUES.xlsx 를 그대로 옮긴 것) 하나뿐이다.

── ★ 지키는 규칙 ────────────────────────────────────────────
① **못 붙었다고 버리지 않는다.**
   코드는 비우고 원문을 함께 보낸다. 2026-09-01 실측으로 브랜드는
   상품 3,350건 중 40% 만 붙었다. 버리는 설계였다면 60% 가 사라진다.
   나중에 팀이 사전에 추가하면 코드만 채우면 된다.

② **애매하면 안 붙인다.**
   비슷한 이름을 유사도로 이어 붙이지 않는다. 잘못 붙은 코드는
   빈 코드보다 나쁘다 — 빈 것은 눈에 띄지만 틀린 것은 안 띈다.
   'Stone Island' 가 사전에 없으면 없는 채로 둔다.

③ **어디서 정해졌는지 남긴다.**
   같은 카테고리라도 '상세에서 받은 것'과 '상품명에서 짐작한 것'은
   신뢰도가 다르다. 그래서 (코드, 근거) 를 함께 돌려준다.

④ **못 붙은 값을 세어 둔다.**
   그래야 팀이 '사전에 뭘 더 넣어야 하나'를 숫자로 볼 수 있다.
   `unmatched()` 가 그 목록이다.
"""

from __future__ import annotations

import json
import re
import threading
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CODES = _ROOT / "config" / "aws_codes.json"

# 브랜드 자리에 잘못 들어온 배지들. musinsa.yaml 의 name.reject 와 같은 목록이다.
_JUNK_BRAND = re.compile(
    r"^(?:(?:FW|SS)\s*\d+\s*신상|무배당발|무료배송|오직\s*무신사|무신사\s*단독|단독"
    r"|쿠폰|최저가|품절|재입고|\d+%|[\d,]+원?)$", re.I)

# 우리 facet 이름 → 팀 term_type
FACET_TO_TYPE = {
    "style": "STYLE", "material": "MATERIAL", "color": "COLOR",
    "item": "ITEM", "detail": "DETAIL", "fit": "DETAIL", "tpo": "TPO",
}


def _norm(s) -> str:
    """비교용으로만 다듬는다. 저장할 값은 절대 이걸로 바꾸지 않는다.

    'Stone Island' / 'STONE ISLAND' / '스톤 아일랜드' 처럼 **띄어쓰기와
    대소문자만 다른** 경우를 같게 본다. 그 이상은 건드리지 않는다 —
    글자를 더 지우면 서로 다른 브랜드가 같아져 버린다.
    """
    return re.sub(r"[\s\-_.·/'\"()]+", "", str(s or "")).lower()


# ── 카테고리 추론용 낱말 ──────────────────────────────────────
#  상품명에 이 말이 있으면 그 분류로 본다. **긴 말을 먼저 본다** —
#  '반소매 티셔츠' 를 '셔츠' 로 잡으면 안 되기 때문이다.
#  분류 이름 자체가 가장 좋은 낱말이라, 여기에는 이름만으로 부족한
#  것들(줄임말·다른 표기)만 손으로 적는다.
_CATEGORY_HINTS: dict[str, tuple[str, ...]] = {
    "TOP_SHORT_SLEEVE_TSHIRT": ("반팔티", "반팔 티", "반소매티", "숏슬리브", "half tee"),
    "TOP_LONG_SLEEVE_TSHIRT": ("긴팔티", "긴팔 티", "롱슬리브", "긴소매티"),
    "TOP_SWEATSHIRT": ("맨투맨", "스웨트셔츠", "크루넥"),
    "TOP_HOODIE": ("후드티", "후디", "후드 티"),
    "TOP_KNIT_SWEATER": ("니트", "스웨터", "가디건니트"),
    "TOP_SHIRT": ("셔츠", "남방"),
    "TOP_BLOUSE": ("블라우스",),
    "TOP_POLO_SHIRT": ("피케", "카라티", "폴로"),
    "TOP_SLEEVELESS": ("민소매", "슬리브리스", "나시", "탱크탑"),
    "OUTER_CARDIGAN": ("가디건",),
    "OUTER_BLOUSON_MA1": ("블루종", "MA-1", "MA1"),
    "OUTER_DENIM_JACKET": ("데님자켓", "데님 자켓", "데님재킷", "청자켓"),
    "OUTER_LEATHER_JACKET": ("레더자켓", "가죽자켓", "라이더자켓"),
    "OUTER_BLAZER_SUIT": ("블레이저", "자켓 셋업", "수트자켓"),
    "OUTER_COACH_JACKET": ("코치자켓", "코치 자켓"),
    "OUTER_TRAINING_JACKET": ("트랙탑", "트레이닝자켓", "저지자켓", "트랙자켓",
                              "트랙 자켓", "트랙재킷", "져지", "피스테"),
    "OUTER_HOOD_ZIPUP": ("후드집업", "후드 집업", "집업"),
    "OUTER_WINDBREAKER": ("바람막이", "윈드브레이커", "아노락점퍼"),
    "OUTER_ANORAK": ("아노락",),
    "OUTER_FLEECE": ("플리스", "후리스", "뽀글이"),
    "OUTER_VEST": ("베스트", "조끼"),
    "OUTER_LIGHT_PADDING": ("경량패딩", "경량 패딩", "라이트다운"),
    "OUTER_SHORT_PADDING": ("숏패딩", "숏 패딩"),
    # ★ '패딩'·'자켓'·'팬츠'·'원피스'·'스커트' 처럼 **종류를 안 밝힌 말**은
    #   맨 뒤에서 받는다. 위의 자세한 낱말이 먼저 걸리고, 아무것도 안 걸릴
    #   때만 큰 분류로 떨어진다. 짐작이 섞이는 자리이므로 근거를 'name' 으로
    #   남겨 나중에 신뢰도를 가릴 수 있게 한다.
    "OUTER_OTHER": ("패딩", "자켓", "재킷", "점퍼", "코트", "야상"),
    "BOTTOM_OTHER": ("팬츠", "바지", "슬랙스팬츠"),
    "DRESS_SKIRT_OTHER": ("원피스", "스커트", "치마", "드레스"),
    "TOP_OTHER": ("티셔츠", "상의", "크롭탑", "뷔스티에"),
    "OUTER_LONG_PADDING": ("롱패딩", "롱 패딩"),
    "OUTER_MUSTANG_FUR": ("무스탕", "퍼자켓", "양털"),
    "OUTER_TRENCH_COAT": ("트렌치",),
    "OUTER_LONG_COAT": ("롱코트", "롱 코트", "맥시코트"),
    "OUTER_SHORT_HALF_COAT": ("하프코트", "숏코트"),
    "BOTTOM_DENIM": ("데님팬츠", "데님 팬츠", "청바지", "데님진", "진팬츠"),
    "BOTTOM_SLACKS": ("슬랙스",),
    "BOTTOM_COTTON_CHINO": ("치노", "코튼팬츠", "면바지"),
    "BOTTOM_CARGO": ("카고",),
    "BOTTOM_SWEAT_JOGGER": ("스웨트팬츠", "조거", "트레이닝팬츠"),
    "BOTTOM_TRAINING": ("트레이닝 팬츠",),
    "BOTTOM_SHORTS": ("숏팬츠", "숏 팬츠", "반바지", "하프팬츠", "쇼츠", "쇼트팬츠"),
    "BOTTOM_LEGGINGS": ("레깅스",),
    "SKIRT_MINI": ("미니스커트", "미니 스커트"),
    "SKIRT_MIDI": ("미디스커트", "미디 스커트"),
    "SKIRT_MAXI": ("롱스커트", "맥시스커트"),
    "SKIRT_DENIM": ("데님스커트", "청치마"),
    "DRESS_MINI": ("미니원피스", "미니 원피스", "MINI ONEPIECE"),
    "DRESS_MIDI": ("미디원피스", "미디 원피스"),
    "DRESS_MAXI": ("롱원피스", "맥시원피스"),
    "JUMPSUIT_OVERALL": ("점프수트", "오버올", "멜빵"),
    "SHOES_SNEAKERS": ("스니커즈", "운동화"),
    "SHOES_SPORTS": ("러닝화", "축구화", "트레일화"),
    "SHOES_LOAFER": ("로퍼",),
    "SHOES_BOOTS": ("부츠", "워커"),
    "SHOES_SANDAL_SLIPPER": ("샌들", "슬리퍼", "쪼리", "슬라이드"),
    "SHOES_HEEL_PUMPS": ("펌프스", "하이힐", "킬힐", "스틸레토"),
    "SHOES_FLAT": ("플랫슈즈", "발레플랫", "메리제인", "메리 제인", "플랫 슈즈"),
    "SHOES_DERBY_LACEUP": ("더비슈즈", "레이스업슈즈"),
    "ACC_HAT": ("볼캡", "비니", "버킷햇", "캡모자", "차양캡", "모자"),
    "ACC_EYEWEAR": ("선글라스", "안경", "아이웨어"),
    "ACC_BELT": ("벨트",),
    "ACC_LEGWEAR": ("양말", "삭스", "스타킹"),
    "ACC_SCARF_MUFFLER": ("머플러", "스카프"),
    "ACC_GLOVES": ("장갑",),
    "ACC_JEWELRY": ("목걸이", "귀걸이", "반지", "팔찌"),
    "ACC_WATCH": ("시계",),
    "ACC_WALLET": ("지갑", "카드케이스"),
    "ACC_HAIR": ("헤어밴드", "집게핀", "헤어핀"),
    "BAG_ALL": ("백팩", "숄더백", "토트백", "크로스백", "가방", "파우치"),
    "ETC_INNERWEAR": ("이너웨어", "속옷", "브라탑"),
}


class CodeMap:
    """코드표 하나를 읽어 두고 계속 물어보는 객체."""

    def __init__(self, path: Path | str = _CODES):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        self.terms = raw["terms"]
        self.brands = raw["brands"]
        self.categories = raw["categories"]

        # 용어: (타입, 다듬은이름) → 코드. 한글·영문 둘 다 열쇠로 쓴다.
        self._term: dict[tuple[str, str], str] = {}
        for t in self.terms:
            for nm in (t["ko"], t["en"]):
                if nm:
                    self._term.setdefault((t["type"], _norm(nm)), t["code"])

        # 브랜드: 다듬은이름 → 코드
        self._brand: dict[str, str] = {}
        for b in self.brands:
            if str(b.get("status") or "ACTIVE") != "ACTIVE":
                continue
            for nm in (b["ko"], b["en"]):
                if nm:
                    self._brand.setdefault(_norm(nm), b["code"])

        self._cat = {c["code"]: c for c in self.categories}
        self._cat_by_name = {_norm(c["ko"]): c["code"] for c in self.categories}

        # 상품명 추론용 — 긴 낱말부터 본다
        pairs: list[tuple[str, str]] = []
        for code, words in _CATEGORY_HINTS.items():
            if code in self._cat:
                pairs += [(w, code) for w in words]
        for c in self.categories:
            if c["level"] == 2:
                pairs.append((c["ko"], c["code"]))
        # ★ 한 글자 낱말은 버린다.
        #   전에 어휘사전에서 '면'·'마'·'립' 이 엉뚱한 말 속에서 걸려
        #   상품을 잘못 분류한 적이 있다. 같은 사고를 구조로 막는다.
        #   ('진' 하나만 있어도 '진저'·'진주'가 전부 데님이 된다.)
        pairs = [(w, c) for (w, c) in pairs if len(str(w).strip()) >= 2]
        self._cat_hints = sorted(set(pairs), key=lambda p: -len(p[0]))

        self._missing: Counter = Counter()
        self._lock = threading.Lock()

    # ── 못 붙은 값 세기 ──────────────────────────────────────
    def _miss(self, kind: str, value: str):
        v = str(value or "").strip()
        if v:
            with self._lock:
                self._missing[(kind, v)] += 1

    def unmatched(self, limit: int = 50) -> list[dict]:
        """사전에 없어서 코드를 못 준 값. 팀이 이걸 보고 채우면 된다."""
        with self._lock:
            items = self._missing.most_common(limit)
        return [{"kind": k, "value": v, "count": n} for (k, v), n in items]

    def reset(self):
        with self._lock:
            self._missing.clear()

    # ── 브랜드 ──────────────────────────────────────────────
    def brand(self, name: str) -> tuple[str | None, str]:
        """(코드, 근거). 못 찾으면 (None, 'unmatched')."""
        key = _norm(name)
        if not key:
            return None, "empty"
        # ★ 브랜드 자리에 배지가 들어온 것은 '사전에 없는 브랜드'가 아니다.
        #   무신사 카드에서 'FW 26 신상'·'무배당발' 같은 배지를 브랜드로
        #   주워 온 자국이 남아 있다(2026-09-01 기준 405건). 이걸 미매칭으로
        #   세면 팀이 사전에 넣어야 할 목록이 쓰레기로 덮인다.
        if _JUNK_BRAND.match(str(name).strip()):
            return None, "junk"
        code = self._brand.get(key)
        if code:
            return code, "exact"
        self._miss("brand", name)
        return None, "unmatched"

    # ── 용어 (스타일·소재·색·아이템·디테일·TPO) ──────────────
    def term(self, facet: str, name: str) -> tuple[str | None, str]:
        tt = FACET_TO_TYPE.get(str(facet).lower())
        if not tt:
            return None, "unknown_facet"
        key = _norm(name)
        if not key:
            return None, "empty"
        code = self._term.get((tt, key))
        if code:
            return code, "exact"
        self._miss(f"term:{tt}", name)
        return None, "unmatched"

    # ── 카테고리 ────────────────────────────────────────────
    def category(self, *, detail_category: str = "", name: str = "",
                 category_path: str = "") -> tuple[str | None, str]:
        """상세 분류가 있으면 그것을, 없으면 상품명에서 짐작한다.

        ★ category_path 는 믿지 않는다.
          우리는 거기에 **수집한 칸 이름**을 넣고 있다 ('브랜드/아디다스',
          '새틴'). 분류가 아니라 '어디서 주웠나'라서, 78종 taxonomy 와
          겹치는 게 사실상 없다. 혹시 진짜 분류 이름이 들어 있으면 쓰되,
          그건 마지막 순서다.
        """
        # ① 상세에서 받은 분류 이름
        if detail_category:
            code = self._cat_by_name.get(_norm(detail_category))
            if code:
                return code, "detail"
            for word, c in self._cat_hints:
                if _norm(word) and _norm(word) in _norm(detail_category):
                    return c, "detail_keyword"

        # ② 상품명에서 짐작
        n = _norm(name)
        if n:
            for word, c in self._cat_hints:
                if _norm(word) in n:
                    return c, "name"

        # ③ 수집 칸 이름에 우연히 분류가 들어 있으면
        if category_path:
            for part in re.split(r"[/>,]", category_path):
                code = self._cat_by_name.get(_norm(part))
                if code:
                    return code, "path"

        self._miss("category", name or category_path)
        return None, "unmatched"

    # ── 한 상품을 통째로 ────────────────────────────────────
    def map_product(self, row: dict) -> dict:
        """적재용 코드 묶음. **원문도 같이 돌려준다** — 하나도 안 버린다."""
        bc, bsrc = self.brand(row.get("brand_name") or "")
        raw_brand = (row.get("brand_name") or "").strip()
        if bsrc == "junk":
            raw_brand = ""      # 배지는 원문으로도 보내지 않는다
        cc, csrc = self.category(
            detail_category=row.get("detail_category") or "",
            name=row.get("name") or "",
            category_path=row.get("category_path") or "")
        return {
            "brand_code": bc,
            "brand_name_raw": raw_brand or None,
            "brand_match": bsrc,
            "category_code": cc,
            "category_path_raw": (row.get("category_path") or "").strip() or None,
            "category_match": csrc,
        }


_INSTANCE: CodeMap | None = None


def get() -> CodeMap:
    """한 번만 읽어 두고 함께 쓴다."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = CodeMap()
    return _INSTANCE
