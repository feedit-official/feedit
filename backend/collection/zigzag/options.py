from __future__ import annotations

import random
import time
from typing import Any

import requests


OPTION_ENDPOINT = (
    "https://api.zigzag.kr/api/2/graphql/GetCatalogProductDetailPageOption"
)

DEFAULT_OPTION_MIN_DELAY = 0.2
DEFAULT_OPTION_MAX_DELAY = 0.5

GET_CATALOG_PRODUCT_DETAIL_PAGE_OPTION_QUERY = r"""
fragment OptionItemList on PdpCatalogItem {
  id name price price_delta final_price item_code sales_status display_status
  remain_stock is_zigzin delivery_type badge_image_url zonly_badge_image_url
  expected_delivery_date expected_delivery_time option_type
  discount_info { image_url title color order }
  item_attribute_list { id name value value_id }
  wms_notification_info { active }
}
query GetCatalogProductDetailPageOption($catalog_product_id: ID!, $input: PdpBaseInfoInput) {
  pdp_option_info(catalog_product_id: $catalog_product_id, input: $input) {
    catalog_product {
      shop_id shop_name shop_main_domain id name fulfillment_type external_code
      minimum_order_quantity maximum_order_quantity coupon_available_status scheduled_sale_date
      discount_info { image_url title color }
      estimated_shipping_date { estimate_list { day probability } }
      shipping_fee { fee_type base_fee minimum_free_shipping_fee additional_shipping_fee_text }
      shipping_company { return_company }
      managed_category_list { id category_id value key depth }
      meta_catalog_product_info { id is_able_to_buy pdp_url browsing_type }
      product_price {
        first_order_discount { price promotion_id discount_type discount_amount discount_rate_bp min_required_amount }
        coupon_discount_info_list { target_type discount_type discount_amount discount_rate_bp discount_amount_of_amount_coupon min_required_amount max_discount_amount }
        display_final_price {
          final_price { badge { text color { normal } } color { normal } }
          final_price_additional { badge { text } color { normal } }
        }
        product_promotion_discount_info { discount_amount }
        max_price_info { price }
        final_discount_info { discount_price }
      }
      trait_list { type }
      promotion_info {
        promotion_id promotion_type
        bogo_info { required_quantity discount_type discount_amount discount_rate_bp badge { image_url } }
      }
      product_image_list { url origin_url pdp_thumbnail_url pdp_static_image_url image_type }
      product_option_list {
        id order name code required option_type
        value_list { id code value static_url jpeg_url }
      }
      matching_catalog_product_info {
        id name is_able_to_buy pdp_url fulfillment_type browsing_type external_code
        product_price {
          max_price_info { price color { normal } badge { text color { normal } } }
          final_discount_info { discount_price }
          first_order_discount { price promotion_id discount_type discount_amount discount_rate_bp min_required_amount }
          coupon_discount_info_list { target_type discount_type discount_amount discount_rate_bp discount_amount_of_amount_coupon min_required_amount max_discount_amount }
          display_final_price {
            final_price { badge { text color { normal } } color { normal } }
            final_price_additional { badge { text } color { normal } }
          }
        }
        discount_info { color title image_url order }
        shipping_fee { fee_type base_fee minimum_free_shipping_fee }
        option_list {
          id order name code required option_type
          value_list { id code value static_url jpeg_url }
        }
      }
      product_additional_option_list {
        id order name code required option_type
        value_list { id code value static_url jpeg_url }
      }
      custom_input_option_list { name is_required: required max_length }
      matched_item_list { ...OptionItemList }
      zigzin_item_list { ...OptionItemList }
      additional_item_list { ...OptionItemList }
      is_only_zigzin_button_visible
      color_image_list { is_main image_url image_width image_height webp_image_url color_list }
      store_deal_banner { title guide_text }
      category_list { category_id value }
      minimum_order_quantity_type
      option_size_recommendation { option_recommend_text option_value }
    }
    flags { is_purchase_only_one_at_time is_cart_button_visible }
    key_color {
      buy_button { text { disabled enabled } background { disabled enabled } }
      discount_info_of_atf
    }
  }
}
""".strip()


class ZigzagOptionError(RuntimeError):
    pass


class ZigzagProductOptionCollector:
    """Collect and normalize Zigzag PDP purchase options for one catalog product."""

    def __init__(
        self,
        *,
        min_delay: float = DEFAULT_OPTION_MIN_DELAY,
        max_delay: float = DEFAULT_OPTION_MAX_DELAY,
        timeout: int = 20,
        session: requests.Session | None = None,
    ):
        self.min_delay = float(min_delay)
        self.max_delay = float(max_delay)
        if self.min_delay < 0 or self.max_delay < self.min_delay:
            raise ValueError("Zigzag option delay 범위가 올바르지 않습니다.")
        self.timeout = int(timeout)
        self.session = session or requests.Session()
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://zigzag.kr",
            "Referer": "https://zigzag.kr/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/154.0.0.0 Safari/537.36"
            ),
        })

    def close(self) -> None:
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def collect_options(self, product_id: str | int) -> dict:
        requested_product_id = self._clean_id(product_id)
        if requested_product_id is None:
            raise ValueError("Zigzag option product_id가 없습니다.")

        if self.max_delay:
            time.sleep(random.uniform(self.min_delay, self.max_delay))

        payload = {
            "operationName": "GetCatalogProductDetailPageOption",
            "variables": {
                "catalog_product_id": requested_product_id,
                "input": {"catalog_product_id": requested_product_id},
            },
            "query": GET_CATALOG_PRODUCT_DETAIL_PAGE_OPTION_QUERY,
        }
        body = self._post(payload)
        return self._normalize_bundle(body, requested_product_id=requested_product_id)

    def _post(self, payload: dict, *, max_retries: int = 3) -> dict:
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                response = self.session.post(
                    OPTION_ENDPOINT,
                    json=payload,
                    timeout=self.timeout,
                )
                if response.status_code == 429 and attempt < max_retries:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        wait_seconds = float(retry_after) if retry_after else 0.0
                    except ValueError:
                        wait_seconds = 0.0
                    time.sleep(
                        wait_seconds if wait_seconds > 0 else
                        min(30.0, 2 ** attempt) + random.uniform(0.3, 1.0)
                    )
                    continue

                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise ZigzagOptionError("Zigzag option 응답이 object가 아닙니다.")
                if body.get("errors"):
                    raise ZigzagOptionError(
                        f"Zigzag option GraphQL errors: {body['errors']}"
                    )
                return body
            except (requests.RequestException, ValueError, ZigzagOptionError) as exc:
                last_error = exc
                if attempt >= max_retries:
                    break
                time.sleep(min(30.0, 2 ** attempt) + random.uniform(0.3, 1.0))

        raise ZigzagOptionError(
            f"Zigzag option request failed: {last_error}"
        ) from last_error

    @classmethod
    def _normalize_bundle(cls, body: dict, *, requested_product_id: str) -> dict:
        option_info = ((body.get("data") or {}).get("pdp_option_info") or {})
        product = option_info.get("catalog_product") or {}
        if not isinstance(product, dict):
            product = {}

        returned_product_id = cls._clean_id(product.get("id"))
        if returned_product_id and returned_product_id != requested_product_id:
            raise ZigzagOptionError(
                "Zigzag option product_id mismatch: "
                f"requested={requested_product_id} returned={returned_product_id}"
            )

        option_groups = [
            cls._normalize_option_group(row)
            for row in (product.get("product_option_list") or [])
            if isinstance(row, dict)
        ]
        option_groups = [row for row in option_groups if row]

        colors = cls._extract_named_values(option_groups, {"색상", "컬러", "color"})
        sizes = cls._extract_named_values(option_groups, {"사이즈", "size"})

        variants = []
        for list_name, variant_type in (
            ("matched_item_list", "MATCHED"),
            ("zigzin_item_list", "ZIGZIN"),
            ("additional_item_list", "ADDITIONAL"),
        ):
            for item in product.get(list_name) or []:
                if isinstance(item, dict):
                    variants.append(cls._normalize_variant(item, variant_type))

        color_images = [
            {
                "is_main": row.get("is_main"),
                "image_url": row.get("image_url"),
                "webp_image_url": row.get("webp_image_url"),
                "image_width": row.get("image_width"),
                "image_height": row.get("image_height"),
                "color_list": row.get("color_list") or [],
            }
            for row in (product.get("color_image_list") or [])
            if isinstance(row, dict)
        ]

        return {
            "source_product_id": requested_product_id,
            "source_product_name": product.get("name"),
            "shop_id": product.get("shop_id"),
            "shop_name": product.get("shop_name"),
            "option_groups": option_groups,
            "colors": colors,
            "sizes": sizes,
            "color_count": len(colors),
            "size_count": len(sizes),
            "variants": variants,
            "variant_count": len(variants),
            "color_images": color_images,
            "flags": option_info.get("flags") or {},
        }

    @classmethod
    def _normalize_option_group(cls, row: dict) -> dict:
        values = []
        for value in row.get("value_list") or []:
            if not isinstance(value, dict):
                continue
            values.append({
                "id": cls._clean_id(value.get("id")),
                "value": value.get("value"),
                "code": value.get("code"),
                "static_url": value.get("static_url"),
                "jpeg_url": value.get("jpeg_url"),
            })
        return {
            "id": cls._clean_id(row.get("id")),
            "order": row.get("order"),
            "name": row.get("name"),
            "code": row.get("code"),
            "required": row.get("required"),
            "option_type": row.get("option_type"),
            "values": values,
        }

    @staticmethod
    def _extract_named_values(option_groups: list[dict], names: set[str]) -> list[dict]:
        lowered = {name.casefold() for name in names}
        result: list[dict] = []
        seen: set[tuple[Any, Any, Any]] = set()
        for group in option_groups:
            group_name = str(group.get("name") or "").strip().casefold()
            if group_name not in lowered:
                continue
            for value in group.get("values") or []:
                key = (value.get("id"), value.get("value"), value.get("code"))
                if key in seen:
                    continue
                seen.add(key)
                result.append(dict(value))
        return result

    @classmethod
    def _normalize_variant(cls, item: dict, variant_type: str) -> dict:
        attributes = []
        for attr in item.get("item_attribute_list") or []:
            if not isinstance(attr, dict):
                continue
            attributes.append({
                "id": cls._clean_id(attr.get("id")),
                "name": attr.get("name"),
                "value": attr.get("value"),
                "value_id": cls._clean_id(attr.get("value_id")),
            })
        return {
            "variant_type": variant_type,
            "id": cls._clean_id(item.get("id")),
            "name": item.get("name"),
            "price": item.get("price"),
            "price_delta": item.get("price_delta"),
            "final_price": item.get("final_price"),
            "item_code": item.get("item_code"),
            "sales_status": item.get("sales_status"),
            "display_status": item.get("display_status"),
            "remain_stock": item.get("remain_stock"),
            "is_zigzin": item.get("is_zigzin"),
            "delivery_type": item.get("delivery_type"),
            "expected_delivery_date": item.get("expected_delivery_date"),
            "expected_delivery_time": item.get("expected_delivery_time"),
            "option_type": item.get("option_type"),
            "attributes": attributes,
        }

    @staticmethod
    def _clean_id(value: Any) -> str | None:
        if value in (None, ""):
            return None
        return str(value).strip() or None
