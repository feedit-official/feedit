"""무신사 USED 저장 HTML 전용 파서.

같은 musinsa.com 안에 신품과 USED가 함께 있으므로 도메인만으로는 구분할 수
없다. 화면 클래스 대신 Next.js의 ``__NEXT_DATA__``를 읽어 상품, 등급, 판매
상태와 현재가를 안정적으로 추출한다.
"""

from __future__ import annotations

import json
import re
from typing import Any


_NEXT = re.compile(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def next_data(html: str) -> dict[str, Any]:
    m = _NEXT.search(html)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except (TypeError, json.JSONDecodeError):
        return {}


def is_used_html(html: str) -> bool:
    """신품 무신사 HTML을 USED 소스로 잘못 넣지 않게 하는 판별식."""
    data = next_data(html)
    page = str(data.get("page") or "")
    props = data.get("props", {}).get("pageProps", {})
    if page == "/category/[[...slug]]" and "109" in json.dumps(
            props.get("query") or data.get("query") or {}, ensure_ascii=False):
        return True
    # 상세 페이지는 URL만으로 구분할 수 없다. comId가 가장 명확하다.
    compact = json.dumps(props, ensure_ascii=False, separators=(",", ":"))
    return '"comId":"musinsa_used"' in compact or '"usedProduct":{' in compact


def _queries(data: dict) -> list:
    return (data.get("props", {}).get("pageProps", {})
            .get("dehydratedState", {}).get("queries", [])) or []


def _detail(data: dict) -> dict:
    meta = data.get("props", {}).get("pageProps", {}).get("meta", {})
    if isinstance(meta.get("data"), dict) and meta["data"].get("goodsNo"):
        return meta["data"]
    for q in _queries(data):
        key = q.get("queryKey") or []
        if key and key[0] == "Detail":
            root = q.get("state", {}).get("data", {})
            root = root.get("data", root) if isinstance(root, dict) else {}
            if isinstance(root, dict) and root.get("goodsNo"):
                return root
    return {}


def _image(url: Any) -> str | None:
    if not url:
        return None
    url = str(url)
    return "https://image.msscdn.net" + url if url.startswith("/") else url


def parse_detail(html: str) -> dict[str, Any]:
    d = _detail(next_data(html))
    if not d:
        return {}
    price = d.get("goodsPrice") or {}
    used = d.get("usedProduct") or {}
    review = d.get("goodsReview") or {}
    brand = d.get("brandInfo") or {}
    sold = bool(d.get("isOutOfStock"))
    uid = str(d.get("goodsNo") or "")
    return {
        "source_uid": uid,
        "source_url": f"https://www.musinsa.com/products/{uid}" if uid else None,
        "name": d.get("goodsNm"),
        "brand": brand.get("brandName") or d.get("brand"),
        # USED 상세에도 원상품의 제품번호가 styleNo로 그대로 내려온다.
        # 신품↔유즈드 가격 비교의 연결 키이므로 버리면 안 된다.
        "model_code": d.get("styleNo"),
        "category_path": d.get("baseCategoryFullPath"),
        "image_url": _image(d.get("thumbnailImageUrl")),
        # USED의 normalPrice는 원상품 발매가가 아니라 판매자가 잡은 최초 판매가다.
        "price": price.get("finalPrice") or price.get("salePrice"),
        "initial_ask_price": price.get("normalPrice"),
        "discount": price.get("finalDiscount") or price.get("discountRate"),
        "review_count": review.get("totalCount"),
        "review_score": review.get("satisfactionScore"),
        "condition_grade": used.get("usedConditionGrade"),
        "original_goods_no": used.get("originalGoodsNo"),
        "availability_state": "sold_out" if sold else "available",
        "is_sold_out": sold,
        "sell_start": d.get("sellStartDate"),
        "listing_type": "ask",
    }


def parse_list(html: str) -> list[dict[str, Any]]:
    data = next_data(html)
    items = []
    for q in _queries(data):
        key = q.get("queryKey") or []
        if not key or str(key[0]) != "109":
            continue
        root = q.get("state", {}).get("data", {})
        pages = root.get("pages") or [] if isinstance(root, dict) else []
        for page in pages:
            block = page.get("data", page) if isinstance(page, dict) else {}
            if isinstance(block, dict):
                items.extend(block.get("list") or [])
        break
    out = []
    for x in items:
        uid = str(x.get("goodsNo") or "")
        if not uid:
            continue
        sold = bool(x.get("isSoldOut"))
        out.append({
            "source_uid": uid,
            "source_url": x.get("goodsLinkUrl") or f"https://www.musinsa.com/products/{uid}",
            "name": x.get("goodsName"), "brand": x.get("brandName") or x.get("brand"),
            "image_url": _image(x.get("thumbnail")),
            "price": x.get("finalPrice") or x.get("price"),
            "initial_ask_price": x.get("normalPrice"),
            "discount": x.get("finalDiscount") or x.get("saleRate"),
            "review_count": x.get("reviewCount"), "review_score": x.get("reviewScore"),
            "condition_grade": x.get("usedConditionGrade"),
            "availability_state": "sold_out" if sold else "available",
            "is_sold_out": sold, "listing_type": "ask",
        })
    return out
