"""플랫폼 상품 후기 원문을 공통 문서로 바꾸는 작은 어댑터.

작성자 닉네임·프로필 주소는 결과에 포함하지 않는다. 후기 ID가 공개된 경우에도
원문 값은 저장하지 않고 Store 단계에서 비식별 해시로만 사용한다.
"""

from __future__ import annotations

import re
import unicodedata
from hashlib import sha256

from bs4 import BeautifulSoup

_WS = re.compile(r"[ \t\r\f\v]+")


def _clean(value: str) -> str:
    lines = []
    for line in unicodedata.normalize("NFC", value or "").splitlines():
        line = _WS.sub(" ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines).strip()


def parse(source_code: str, html: str, limit: int = 100) -> list[dict]:
    if source_code == "ably":
        return _ably(html, limit)
    if source_code == "zigzag":
        return _zigzag(html, limit)
    if source_code in ("musinsa", "musinsa_used"):
        return _musinsa(html, limit)
    return []


def _musinsa(html: str, limit: int) -> list[dict]:
    """렌더링된 무신사 후기 탭에서 원문만 비식별 수집한다."""
    soup = BeautifulSoup(html or "", "html.parser")
    out, seen = [], set()
    for content in soup.select('[data-button-name="후기내용"]'):
        body = _clean(content.get_text("\n", strip=True))
        if len(body) < 6 or body in seen:
            continue
        seen.add(body)
        root = content.find_parent(attrs={"data-content-id": True}) or content.parent
        full = _clean(root.get_text("\n", strip=True)) if root else body
        row = {
            "body": body,
            "review_id": ((root.get("data-content-id") if root else None) or
                          "body:" + sha256(body.encode("utf-8")).hexdigest()[:24]),
        }
        dm = re.search(r"(?<!\d)(\d{2})\.(\d{2})\.(\d{2})(?!\d)", full)
        if dm:
            row["published_at"] = "20" + "-".join(dm.groups())
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _ably(html: str, limit: int) -> list[dict]:
    """에이블리 후기 상자에서 본문·날짜·체형만 읽고 닉네임은 버린다."""
    soup = BeautifulSoup(html or "", "html.parser")
    out, seen = [], set()
    date_re = re.compile(r"(20\d{2})\.(\d{2})\.(\d{2})")
    body_reject = re.compile(r"^(?:상품정보|리뷰|사이즈|문의|댓글\s*\d*개|전체보기)")
    for box in soup.select("[data-feedit-review], body > div"):
        full = _clean(box.get_text("\n", strip=True))
        if not date_re.search(full) or not re.search(r"만족해요|별로예요", full):
            continue
        leaves = []
        for el in box.find_all("div"):
            if el.find("div"):
                continue
            text = _clean(el.get_text("\n", strip=True))
            if 15 <= len(text) <= 3000 and not body_reject.search(text):
                leaves.append(text)
        if not leaves:
            continue
        body = max(leaves, key=len)
        if body in seen:
            continue
        seen.add(body)
        m = date_re.search(full)
        row = {
            "body": body,
            "review_id": "body:" + sha256(body.encode("utf-8")).hexdigest()[:24],
            "published_at": "-".join(m.groups()),
        }
        hm = re.search(r"체형\s*(\d{3})cm\s*·\s*(\d{2,3})kg(?:\s*·\s*([^\n·]+?)\s*사이즈)?", full)
        if hm:
            row["height"], row["weight"] = int(hm.group(1)), int(hm.group(2))
            if hm.group(3):
                row["size"] = hm.group(3).strip()
        # 에이블리의 3단계 만족도를 5점 척도의 양 끝/중앙으로 보존한다.
        # 한 화면에 여러 후기 카드가 중첩되면 바깥 상자에는 양쪽 문구가 모두
        # 들어갈 수 있다. 본문 자체의 명시 평가를 우선해 오판을 줄인다.
        if "별로예요" in body:
            row["rating"] = 1
        elif "만족해요" in body:
            row["rating"] = 5
        elif "별로예요" in full and "만족해요" not in full:
            row["rating"] = 1
        elif "만족해요" in full and "별로예요" not in full:
            row["rating"] = 5
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _zigzag(html: str, limit: int) -> list[dict]:
    """지그재그 상세의 리뷰 슬라이더를 읽는다.

    빌드 해시(css-19s09oq)는 쓰지 않는다. `리뷰 N`을 포함하는 영역 안에서
    지그재그의 의미형 타이포 클래스(BODY_14 + REGULAR)와 슬라이드 구조를 함께
    확인한다. 배송·설명 영역의 같은 타이포 클래스는 제외된다.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    out, seen = [], set()
    for section in soup.find_all(["section", "div"]):
        head = _clean(section.get_text(" ", strip=True))[:80]
        if not re.search(r"리뷰\s*[\d,]+", head):
            continue
        for slide in section.select(".swiper-slide"):
            candidates = slide.select(".BODY_14.REGULAR")
            if not candidates:
                continue
            body = max((_clean(x.get_text("\n", strip=True)) for x in candidates),
                       key=len, default="")
            if len(body) < 15 or body in seen:
                continue
            seen.add(body)
            out.append({
                "body": body,
                # 작성자 대신 본문 기반 안정 키. DB에는 이 값조차 해시로만 저장된다.
                "review_id": "body:" + sha256(body.encode("utf-8")).hexdigest()[:24],
            })
            if len(out) >= limit:
                return out
        if out:
            break
    return out


def save(store, source_code: str, product_uid: str, rows: list[dict]) -> int:
    """후기를 익명 text_document로 저장하고 무료 사전 연결까지 실행한다."""
    inserted = 0
    for row in rows or []:
        body = _clean(str(row.get("body") or ""))
        if len(body) < 6:
            continue
        anonymous_key = str(row.get("review_id") or body)
        author_hash = sha256(
            f"{source_code}:{product_uid}:{anonymous_key}".encode("utf-8")
        ).hexdigest()[:16]
        text_id = store.put_text(
            source_code, "product_review", body,
            product_uid=str(product_uid),
            author_hash=author_hash,
            # SQLite UNIQUE는 NULL끼리를 같은 값으로 보지 않는다. 날짜 없는 후기가
            # 매 회차 복제되지 않도록 상품 후기에 한해 빈 문자열을 안정값으로 쓴다.
            published_at=row.get("published_at") or "",
            rating=row.get("rating"),
            author_height_cm=row.get("height"),
            author_weight_kg=row.get("weight"),
            author_size=row.get("size"),
        )
        inserted += int(text_id is not None)
    return inserted
