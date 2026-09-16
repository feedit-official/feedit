"""
Nuxt 페이지에 박힌 __NUXT_DATA__ 를 읽는다.

── 왜 필요한가 ──
크림은 서버가 완성된 화면을 주지 않는다. 데이터만 JSON 으로 보내고
브라우저가 그걸로 화면을 그린다. 그래서 크롤러가 받는 HTML 에는
div.text_body 같은 요소가 아예 없다 — 1.5MB 를 받았는데 74%가 이 JSON 이다.

브라우저에서 저장한 HTML 로 셀렉터를 잡으면 잘 되는 것처럼 보이는데,
그건 이미 다 그려진 뒤의 모습이라 크롤러는 그 상태를 받을 수 없다.
→ 답은 DOM 을 포기하고 이 JSON 을 직접 읽는 것이다.

── devalue 형식 ──
평평한 배열 하나에 모든 값이 들어 있고, 서로를 '인덱스 번호'로 가리킨다.

    [ {"name": 3, "price": 4}, ..., "칼하트 티셔츠", 27000 ]
        └ 3번칸을 보라는 뜻            ↑ 3번칸      ↑ 4번칸

그래서 그냥 훑으면 숫자만 보인다. 참조를 따라가 줘야 값이 나온다.
순환 참조가 있으므로 지나온 칸을 기억하며 끊는다.

── 크림 페이지에서 확인된 것 (로그아웃 상태) ──
페이지 대부분은 SDUI(화면 배치 설명)라 값이 text 칸에 흩어져 있지만,
거래 내역과 상품 정보는 **제대로 된 레코드**로 들어 있다.

    거래  {product_id, product_option, price, date_created, ...}
    상품  {brand_name, name, translated_name, category, image_url, ...}

date_created 는 '36분 전' 이 아니라 ISO 시각이라 DOM 보다 오히려 낫다.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Optional

_NUXT_RE = re.compile(
    r'<script[^>]+id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S | re.I)

MAX_DEPTH = 12          # 순환을 만나기 전에 끊는 깊이


class NuxtDoc:
    """해독된 __NUXT_DATA__ 한 장."""

    def __init__(self, flat: list):
        self.flat = flat
        self._texts: Optional[list[str]] = None

    # ── 기본 ──────────────────────────────────────────────────
    def __len__(self) -> int:
        return len(self.flat)

    def resolve(self, i: Any, depth: int = 0, seen: frozenset = frozenset()) -> Any:
        """인덱스를 따라가 실제 값을 만든다."""
        if not isinstance(i, int) or not (0 <= i < len(self.flat)):
            return None
        if depth > MAX_DEPTH or i in seen:
            return None
        v = self.flat[i]
        if v is None or isinstance(v, (str, float, bool, int)):
            return v                      # 숫자 자체가 값인 칸도 있다
        s2 = seen | {i}
        if isinstance(v, list):
            return [self.resolve(x, depth + 1, s2) for x in v]
        if isinstance(v, dict):
            return {k: self.resolve(x, depth + 1, s2) for k, x in v.items()}
        return v

    def _str_at(self, i: Any) -> Optional[str]:
        if isinstance(i, int) and 0 <= i < len(self.flat):
            v = self.flat[i]
            if isinstance(v, str):
                return v
        return None

    # ── 레코드 찾기 ────────────────────────────────────────────
    def records(self, keys: Iterable[str], limit: int = 2000) -> list[dict]:
        """지정한 키를 모두 가진 dict 를 찾아 값까지 채워 돌려준다.

        같은 내용이 두 번씩 나오는 게 정상이다 — PC용·모바일용 레이아웃이
        따로 실려서다. 그래서 내용이 같은 건 하나로 줄인다.
        """
        need = set(keys)
        if not need:
            return []
        out, seen = [], set()
        for i, v in enumerate(self.flat):
            if not isinstance(v, dict) or not need.issubset(v.keys()):
                continue
            rec = self.resolve(i)
            if not isinstance(rec, dict):
                continue
            try:
                sig = json.dumps(rec, sort_keys=True, ensure_ascii=False, default=str)
            except Exception:
                sig = repr(rec)
            if sig in seen:
                continue
            seen.add(sig)
            out.append(rec)
            if len(out) >= limit:
                break
        return out

    # ── SDUI 텍스트 ────────────────────────────────────────────
    def texts(self) -> list[str]:
        """화면에 글자로 뿌려지는 값들을 실린 순서대로 모은다.

        모델번호·색상처럼 레코드가 아니라 '모델번호 K87-BLK' 같은
        한 덩어리 문구로만 들어 있는 값이 있어서 필요하다.
        """
        if self._texts is None:
            t = []
            for v in self.flat:
                if isinstance(v, dict) and "text" in v:
                    s = self._str_at(v["text"])
                    if s and s.strip():
                        t.append(s.strip())
            self._texts = t
        return self._texts

    def find_text(self, pattern: str, group: int = 1) -> Optional[str]:
        """정규식에 처음 걸리는 문구에서 값을 뽑는다.

        괄호가 있으면 그 안을, 없으면 걸린 문구 전체를 준다.
        """
        rx = re.compile(pattern)
        for s in self.texts():
            m = rx.search(s)
            if m:
                val = m.group(group) if m.groups() and group <= len(m.groups()) \
                    else m.group(0)
                return (val or "").strip() or None
        return None

    def find_texts(self, pattern: str, group: int = 1, limit: int = 50) -> list[str]:
        rx, out, seen = re.compile(pattern), [], set()
        for s in self.texts():
            m = rx.search(s)
            if not m:
                continue
            val = m.group(group) if m.groups() and group <= len(m.groups()) else m.group(0)
            val = (val or "").strip()
            if val and val not in seen:
                seen.add(val)
                out.append(val)
                if len(out) >= limit:
                    break
        return out


def parse_nuxt(html: str) -> Optional[NuxtDoc]:
    """HTML 에서 __NUXT_DATA__ 를 찾아 해독한다. 없으면 None."""
    if not html or "__NUXT_DATA__" not in html:
        return None
    m = _NUXT_RE.search(html)
    if not m:
        return None
    try:
        flat = json.loads(m.group(1))
    except (ValueError, TypeError):
        return None
    if not isinstance(flat, list):
        return None
    return NuxtDoc(flat)


# ── 편의: 점 표기로 중첩 값 꺼내기 ───────────────────────────────
def dig(obj: Any, path: str) -> Any:
    """'product_option.name' 처럼 파고든다. 배열은 [0] 으로."""
    cur = obj
    for part in str(path).split("."):
        if cur is None:
            return None
        m = re.match(r"^(.*?)\[(\d+)\]$", part)
        idx = None
        if m:
            part, idx = m.group(1), int(m.group(2))
        if part:
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return None
        if idx is not None:
            if isinstance(cur, list) and idx < len(cur):
                cur = cur[idx]
            else:
                return None
    return cur


def dominant(records: list[dict], key: str) -> list[dict]:
    """가장 많이 나온 key 값만 남긴다.

    상세 페이지에는 연관 상품 정보도 함께 실린다. 거래 내역을 그대로 쓰면
    남의 상품 거래가 섞여 시세가 엉망이 되므로, 이 페이지의 주인공만 남긴다.
    """
    from collections import Counter
    vals = [r.get(key) for r in records if r.get(key) is not None]
    if not vals:
        return records
    top = Counter(vals).most_common(1)[0][0]
    return [r for r in records if r.get(key) == top]
