"""
구조 탐색기 — 셀렉터를 사람이 손으로 찾지 않아도 되게.

이 도구의 가장 중요한 부분일 수 있다.

두 사이트 모두 공개 API 가 없고, HTML 구조는 예고 없이 바뀐다.
그래서 셀렉터를 코드에 박아 두면 어느 날 조용히 빈 값만 쌓이고,
크롤링을 처음 하는 팀원은 왜 안 되는지 알 방법이 없다.

대신 이렇게 한다.
  1) 팀원이 브라우저에서 페이지를 열고 저장(Ctrl+S)하거나 URL 을 넣는다
  2) 탐색기가 "가격처럼 생긴 것", "반복되는 카드 묶음"을 스스로 찾아 후보를 낸다
  3) 팀원은 후보 중 맞는 걸 고르기만 하면 된다 → YAML 로 저장

셀렉터가 코드가 아니라 설정이 되므로, 구조가 바뀌어도 개발자 없이 고칠 수 있다.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, asdict
from typing import Optional

from bs4 import BeautifulSoup

# 한국 커머스에서 가격이 나타나는 꼴들
PRICE_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{4,})\s*(?:원|won|KRW)?", re.I)
SIZE_RE = re.compile(r"^(XS|S|M|L|XL|XXL|2XL|3XL|F|FREE|ONE)$|^\d{2,3}(\.\d)?$", re.I)
DATE_RE = re.compile(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}")


@dataclass
class Candidate:
    """탐색기가 제안하는 셀렉터 하나."""
    selector: str
    kind: str            # price | name | brand | size | date | image | link | text
    sample: str
    count: int
    confidence: float
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# CSS 에서 뜻이 있는 글자들. 클래스 이름에 섞여 있으면 반드시 이스케이프해야 한다.
#  ★ Tailwind 를 쓰는 사이트에 `mo:br-bl-6` · `hover:bg-black` 같은 클래스가 있다.
#    그대로 셀렉터에 넣으면 콜론이 가상클래스(:hover)로 읽혀 통째로 죽는다.
#    크림에서 실제로 그렇게 터졌다 — 탐색기가 아예 안 돌았다.
_CSS_SPECIAL = re.compile(r'([ !"#$%&\'()*+,./:;<=>?@\[\\\]^`{|}~])')


def _esc_cls(c: str) -> str:
    return _CSS_SPECIAL.sub(r"\\\1", c)


def _css_path(el, max_depth: int = 4) -> str:
    """요소를 가리키는 짧은 CSS 경로. 너무 길면 오히려 잘 깨진다."""
    parts = []
    cur = el
    depth = 0
    while cur is not None and getattr(cur, "name", None) and depth < max_depth:
        if cur.get("id"):
            parts.append(f"#{cur['id']}")
            break
        cls = [c for c in (cur.get("class") or [])
               # 해시가 붙은 자동생성 클래스는 배포마다 바뀌므로 쓰지 않는다
               if not re.search(r"[0-9a-f]{6,}", c) and len(c) < 30]
        if cls:
            parts.append(cur.name + "." + ".".join(_esc_cls(c) for c in cls[:2]))
        else:
            parts.append(cur.name)
        cur = cur.parent
        depth += 1
    return " > ".join(reversed(parts))


def find_repeating_blocks(soup: BeautifulSoup, min_repeat: int = 4) -> list[Candidate]:
    """목록 페이지에서 '카드가 반복되는 묶음'을 찾는다.

    상품 목록은 거의 항상 같은 클래스를 가진 형제 요소의 반복이다.
    그 반복을 찾으면 카드 셀렉터가 나온다.
    """
    sig = Counter()
    holder: dict[str, object] = {}

    for el in soup.find_all(["li", "div", "article", "a"]):
        cls = [c for c in (el.get("class") or [])
               if not re.search(r"[0-9a-f]{6,}", c)]
        if not cls:
            continue
        key = el.name + "." + ".".join(sorted(cls)[:2])
        sig[key] += 1
        holder.setdefault(key, el)

    out = []
    for key, n in sig.most_common(14):
        if n < min_repeat:
            continue
        el = holder[key]
        # 링크와 이미지를 같이 품고 있어야 상품 카드일 확률이 높다
        has_link = el.find("a") is not None
        has_img = el.find("img") is not None
        text = " ".join(el.get_text(" ", strip=True).split())[:70]
        conf = 0.35 + (0.3 if has_link else 0) + (0.25 if has_img else 0)
        if PRICE_RE.search(text):
            conf += 0.1
        out.append(Candidate(
            selector=key.replace(".", ".", 1),
            kind="card",
            sample=text,
            count=n,
            confidence=round(min(conf, 0.98), 2),
            note=f"{n}개 반복" + (" · 링크·이미지 포함" if has_link and has_img else ""),
        ))
    return sorted(out, key=lambda c: -c.confidence)


def find_fields(soup: BeautifulSoup, scope_selector: Optional[str] = None) -> list[Candidate]:
    """가격·이름·사이즈·날짜처럼 '생긴 게 뚜렷한' 값들의 위치를 추정한다."""
    # 카드가 있으면 카드 안쪽만 본다 — 페이지 전체를 뒤지면 헤더·푸터 노이즈가 섞인다.
    # 단 카드를 못 찾았으면(상세 페이지 등) 문서 전체를 본다.
    roots = [soup]
    if scope_selector:
        try:
            found = soup.select(scope_selector)[:3]      # 앞의 몇 장만 표본으로
            if found:
                roots = found
        except Exception:
            pass

    out: list[Candidate] = []
    seen: set[str] = set()

    def add(el, kind, conf, note=""):
        path = _css_path(el)
        key = f"{kind}|{path}"
        if not path or key in seen:
            return
        seen.add(key)
        try:
            cnt = len(soup.select(path))
        except Exception:
            cnt = 1
        sample = (el.get("src") or el.get("data-src") or "") if el.name == "img" \
                 else " ".join(el.get_text(" ", strip=True).split())
        out.append(Candidate(
            selector=path, kind=kind, sample=sample[:60],
            count=cnt, confidence=conf, note=note,
        ))

    # find_all(True) = 모든 태그. text=False 는 문자열 노드를 찾는 인자라 여기선 안 맞는다.
    for root in roots:
      for el in root.find_all(True):
        if el.name in ("script", "style", "html", "body", "head", "meta", "link"):
            continue
        # 자식 태그가 없는 말단만 본다 — 부모는 텍스트가 섞여 판단이 흐려진다
        if el.name != "img" and el.find(True):
            continue
        txt = el.get_text(" ", strip=True)
        if el.name != "img" and (not txt or len(txt) > 90):
            continue

        if PRICE_RE.fullmatch(txt.replace(" ", "")):
            digits = re.sub(r"[^\d]", "", txt)
            if digits and 1000 <= int(digits) <= 100_000_000:
                add(el, "price", 0.9, "숫자 + 원 형태")
        elif SIZE_RE.match(txt):
            add(el, "size", 0.72, "사이즈 표기")
        elif DATE_RE.search(txt):
            add(el, "date", 0.7, "날짜 형태")
        elif 2 <= len(txt) <= 40 and not txt.isdigit():
            cls = " ".join(el.get("class") or [])
            if re.search(r"brand|label|maker", cls, re.I):
                add(el, "brand", 0.75, "class 에 brand 계열")
            elif re.search(r"name|title|prod", cls, re.I):
                add(el, "name", 0.75, "class 에 name/title 계열")

    for root in roots:
        for img in root.find_all("img", limit=4):
            src = img.get("src") or img.get("data-src") or ""
            if src and not src.startswith("data:"):
                add(img, "image", 0.65, f"이미지 · {src[:34]}")

    return sorted(out, key=lambda c: (-c.confidence, -c.count))[:40]


def find_embedded_json(html: str) -> list[Candidate]:
    """페이지에 박혀 있는 JSON 을 찾는다.

    요즘 사이트는 서버에서 렌더한 데이터를 `__NEXT_DATA__` 같은 script 에 통째로
    넣어 둔다. **이게 있으면 HTML 을 헤집을 이유가 없다** — 셀렉터보다 훨씬
    안정적이고, 구조가 바뀌어도 잘 안 깨진다. 항상 먼저 확인할 것.
    """
    out = []
    patterns = [
        (r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', "__NEXT_DATA__", 0.95),
        (r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', "__NUXT_DATA__", 0.95),
        (r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', "__INITIAL_STATE__", 0.9),
        (r'window\.__APOLLO_STATE__\s*=\s*(\{.*?\});', "__APOLLO_STATE__", 0.9),
        (r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', "JSON-LD", 0.8),
    ]
    for pat, name, conf in patterns:
        for m in re.finditer(pat, html, re.S):
            body = m.group(1).strip()
            if len(body) < 40:
                continue
            out.append(Candidate(
                selector=name, kind="embedded_json",
                sample=body[:120].replace("\n", " "),
                count=1, confidence=conf,
                note=f"{len(body):,} 바이트 — 셀렉터보다 안정적입니다. 이쪽을 우선 쓰세요.",
            ))
            break
    return out


def probe(html: str, url: str = "") -> dict:
    """페이지 하나를 통째로 훑어 후보를 낸다."""
    soup = BeautifulSoup(html, "html.parser")
    embedded = find_embedded_json(html)
    cards = find_repeating_blocks(soup)
    fields = find_fields(soup, cards[0].selector if cards else None)

    hint = None
    if embedded:
        hint = (
            f"{embedded[0].selector} 안에 데이터가 통째로 들어 있습니다. "
            "HTML 셀렉터 대신 이 JSON 을 쓰면 구조가 바뀌어도 잘 안 깨집니다."
        )
    elif not cards:
        hint = (
            "반복되는 카드를 못 찾았습니다. 자바스크립트로 그리는 페이지일 가능성이 큽니다 — "
            "브라우저에서 페이지를 다 띄운 뒤 저장(Ctrl+S)한 HTML 을 넣어 보세요."
        )

    return {
        "url": url,
        "title": (soup.title.string.strip() if soup.title and soup.title.string else ""),
        "embedded_json": [c.to_dict() for c in embedded],
        "cards": [c.to_dict() for c in cards[:8]],
        "fields": [c.to_dict() for c in fields],
        "hint": hint,
    }
