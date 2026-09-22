"""코디 인계(Fit Handoff) — 스타일로 상품을 고르고, 연출을 검수한다.

왜 별도 모듈인가 (AGENTS.md §1) —
  슬롯별로 어떤 아이템을 찾을지 적은 표(SLOT_KINDS)가 답변 경로 안에 숨으면
  하드코딩이고, 도구가 읽는 자료로 바깥에 드러나 있으면 능력이다. season.py 가
  같은 자리에 있다 — 고치면 답이 바뀌고, 무엇을 기준으로 골랐는지 말할 수 있다.

이 모듈이 하지 않는 것 —
  · 옷의 구조(여밈·두께)를 상품명으로 판별하지 않는다. 그건 사진을 볼 수 있는
    쪽(vton.inspect)만 안다. 실제 반례: "[원단 선택 가능]카펜터 버뮤다 스웨트
    8부 팬츠" 는 '스웨트' 가 붙었지만 하의다.
  · 이미지를 생성하지 않는다. 생성은 사용자가 위젯에서 누를 때만 일어난다.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from . import vton


# ── 슬롯마다 무엇을 찾나 ────────────────────────────────────
#   ★ 값은 /api/products 의 kind 파라미터로 그대로 간다. kind 는 ITEM 태그
#     (commerce.product_term · term_type='ITEM') 와 표준 카테고리명 양쪽을 본다
#     (backend/apps/api/views.py `_apply`). 그래서 태그가 비어 있어도 카테고리로
#     걸린다 — 한쪽만 채워져 있어도 상품이 나온다.
#   ★ 이름은 vton.SLOT_ORDER 와 같아야 한다. 한쪽만 늘리면 화면의 칸과 어긋난다.
SLOT_KINDS: dict[str, list[str]] = {
    "상의": ["티셔츠", "셔츠", "니트", "스웨트셔츠", "후드", "블라우스"],
    "하의": ["팬츠", "데님", "스커트", "반바지", "트레이닝팬츠"],
    "아우터": ["재킷", "코트", "점퍼", "가디건", "베스트"],
    "원피스(셋업)": ["원피스", "점프수트", "셋업"],
    "신발": ["스니커즈", "운동화", "부츠", "로퍼", "샌들"],
}
# 기본 코디 — 상의·하의·신발 한 벌. 아우터와 레이어드는 모델이 요청할 때만 늘린다.
DEFAULT_SLOTS = ["상의", "하의", "신발"]
# 한 코디에 담을 수 있는 칸 수. 화면(VF_MAX)·서버(vton.MAX_ITEMS)와 같은 상한이다.
MAX_SLOTS = vton.MAX_ITEMS


# ── 상대 경로 사진 (2026-09-22) ─────────────────────────────
#   DB 실측: commerce.product_source.thumbnail_url 중 27,424건이 호스트 없는
#   무신사 상대 경로다(`thumbnails/images/goods_img/...`). 가장 큰 덩어리라
#   이것을 버리면 상의·하의가 통째로 빈다.
#   ★ 기준은 수집기가 원본이다 — backend/collection/musinsa/constants.py
#     IMAGE_BASE_URL = "https://image.msscdn.net". 여기서 새로 정하지 않는다.
#   ★ 같은 규칙이 화면 쪽에도 있다. 고칠 때 셋을 같이 고친다:
#       backend/apps/api/images.py       (Django)
#       frontend/api/_lib/image.js       (Vercel 함수 — 배포된 화면이 쓰는 길)
#     공통 계약은 backend/apps/api/test_images.py 의 표다.
IMAGE_BASE = {"MUSINSA": "https://image.msscdn.net",
              "MUSINSA_USED": "https://image.msscdn.net"}
# 상대 경로로 인정할 모양. 모르는 모양은 주소로 만들지 않고 버린다 —
# 앞에 아무 호스트나 붙이면 엉뚱한 사진을 입히게 된다.
RELATIVE_HINTS = ("thumbnails/images/", "images/goods_img/", "goods_img/")


def absolute_image(url: str, source: str = "") -> str:
    """상품 사진 주소를 받아 온전한 주소로 돌려준다. 못 만들면 빈 문자열."""
    text = str(url or "").strip()
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    if text.startswith("//"):
        return "https:" + text
    path = text.lstrip("/")
    if not path.startswith(RELATIVE_HINTS):
        return ""
    base = IMAGE_BASE.get(str(source or "").upper())
    if not base:
        # 소스를 모르면 모양으로 가른다 — goods_img 는 무신사 경로다.
        base = IMAGE_BASE["MUSINSA"] if "goods_img/" in path else ""
    return f"{base}/{path}" if base else ""


def _normalize_slots(slots) -> list[str]:
    """모르는 칸 이름은 버리고, 같은 칸이 두 번 와도 그대로 둔다.

    ★ 중복을 막지 않는다 — '아우터' 가 둘이어야 레이어드가 성립한다
      (chat_popup.cpFitItems 가 같은 이유로 중복을 허용한다).
    """
    rows = [str(s or "").strip() for s in (slots or [])]
    rows = [s for s in rows if s in SLOT_KINDS]
    return (rows or list(DEFAULT_SLOTS))[:MAX_SLOTS]


def propose(market, styles, slots=None, limit: int = 3) -> dict:
    """스타일 태그로 슬롯별 상품을 한 점씩 고른다. 생성하지 않는다.

    ★ 슬롯 조회는 서로 독립이다 — 차례로 물으면 한 바퀴가 어댑터 timeout×칸 수가
      된다(8초×3=24초). 예산의 절반을 조회가 먹던 자리라 병렬로 부른다.
    ★ 사진 없는 상품은 코디에 담지 않는다. 입힐 수 없는 것을 승인 카드에 올리면
      사용자는 눌러 보고 나서야 안다.
    """
    names = [str(s or "").strip() for s in (styles or []) if str(s or "").strip()]
    if not names:
        return {"unavailable": "어떤 스타일로 고를지 정해지지 않았습니다."}
    picks = _normalize_slots(slots)

    def one(slot: str) -> list[dict]:
        # 스타일은 하나씩 건다 — 여러 개를 한 번에 걸면 어느 태그로 걸린 상품인지
        # 알 수 없어 "왜 이걸 골랐나" 를 말할 수 없다.
        for style in names:
            rows = market.products({"style": style, "kind": SLOT_KINDS[slot][0]}, limit=limit)
            got = []
            for row in (rows or []):
                # 사진을 온전한 주소로 만든다. 못 만들면 담지 않는다 —
                # 입힐 수 없는 것을 승인 카드에 올리면 눌러 보고 나서야 안다.
                image = absolute_image(row.get("image"), row.get("source"))
                if image and vton.image_host_allowed(image):
                    got.append({**row, "image": image})
            if got:
                return [{**got[0], "slot": slot, "style": style}]
        return []

    with ThreadPoolExecutor(max_workers=min(4, len(picks))) as pool:
        found = list(pool.map(one, picks))

    items = [row for rows in found for row in rows]
    if not items:
        empty = " · ".join(sorted(set(picks)))
        return {"unavailable": f"'{names[0]}' 태그가 붙은 상품 중 사진이 있는 것을 "
                               f"{empty} 칸에서 찾지 못했습니다."}
    missed = [s for s, rows in zip(picks, found) if not rows]
    out = {"items": items, "styles": names, "slots": picks}
    if missed:
        # 없는 칸을 조용히 빼지 않는다 — 결측을 숨기지 않는 리포트 원칙과 같은 자리.
        out["missing_slots"] = sorted(set(missed))
    return out


def prune_options(options, items, seen) -> tuple[dict, list[str]]:
    """아이템과 맞지 않는 연출을 떼어내고, 무엇을 왜 뗐는지 함께 돌려준다.

    seen 은 vton.inspect() 결과이고 items 와 같은 순서다. 사진을 못 본 경우
    (seen 이 비었을 때)는 아무것도 떼지 않는다 — 확인하지 못한 것을 근거로
    지시를 지우면, 사용자가 켠 연출이 이유 없이 사라진다.
    """
    on = {k: bool(v) for k, v in (options or {}).items() if k in vton.OPTION_LINES}
    dropped: list[str] = []
    rows = list(items or [])
    looks = list(seen or [])

    def looked(slot: str) -> list[dict]:
        return [s for s, i in zip(looks, rows) if i.get("slot") == slot]

    # ① 레이어드는 아우터가 둘 이상일 때만 성립한다. 사진 판단이 아니라 산수다.
    outers = [i for i in rows if i.get("slot") == "아우터"]
    if on.get("outer_layered") and len(outers) < 2:
        on["outer_layered"] = False
        dropped.append("아우터가 한 벌이라 레이어드는 빼고 그립니다.")

    # ② 그 칸이 아예 없으면 그 칸의 여밈 지시도 없다.
    for key, slot in (("outer_open", "아우터"), ("outer_closed", "아우터"),
                      ("top_open", "상의"), ("top_closed", "상의")):
        if on.get(key) and not any(i.get("slot") == slot for i in rows):
            on[key] = False
            dropped.append(f"{slot} 가 없어 {slot} 열기/닫기는 뺐습니다.")

    # ③ 여밈이 없는 옷은 열 수 없다. 판단은 사진이 한다(vton.inspect).
    for slot, keys in (("상의", ("top_open", "top_closed")),
                       ("아우터", ("outer_open", "outer_closed"))):
        rows_seen = looked(slot)
        if not rows_seen or not any(on.get(k) for k in keys):
            continue
        if any(s.get("openable") == "yes" for s in rows_seen):
            continue
        if any(s.get("openable") == "no" for s in rows_seen):
            for k in keys:
                on[k] = False
            dropped.append(f"사진을 보니 {slot}에 여밈이 없어 열기/닫기는 뺐습니다.")
        else:
            # ★ 모르면 빼지도 넣지도 않는다. 켜진 채 두고 확인하지 못했다고 밝힌다.
            dropped.append(f"{slot} 사진에서 여밈을 확인하지 못했습니다.")

    # ④ 짝 충돌 — vton.option_lines 도 둘 다 버리지만 조용하다. 여기서 사유를 남긴다.
    for a, b in vton.OPTION_CONFLICTS:
        if on.get(a) and on.get(b):
            on[a] = on[b] = False
            dropped.append("열기와 닫기를 같이 켜서 둘 다 뺐습니다.")
    return on, dropped


def layer_order(items, seen) -> list[dict]:
    """아우터가 둘이면 얇은 것을 앞 칸에 둔다.

    생성 프롬프트는 "얇고 짧은 것을 안쪽" 이라고만 적혀 있어, 어느 쪽이 얇은지는
    사진을 본 쪽이 정해 줘야 한다(vton.inspect 의 layer). 모르면 순서를 바꾸지
    않는다.
    """
    weight = {"얇음": 0, "보통": 1, "두꺼움": 2}
    order = {id(i): weight.get((s or {}).get("layer"), 1)
             for i, s in zip(items or [], seen or [])}
    if not order:
        return list(items or [])
    return sorted(items, key=lambda i: (i.get("slot") != "아우터", order.get(id(i), 1)))
