"""준비된 FEEDiT 모델과 여러 상품 사진을 GPT Image 2.5 Sunburst에 보낸다."""
from __future__ import annotations

import base64
import os
import re
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / "assets" / "vton_models"
MODELS = {
    "woman": {"label": "여성 모델", "path": MODEL_DIR / "woman.png"},
    "man": {"label": "남성 모델", "path": MODEL_DIR / "man.png"},
}
# ── 착장 칸 (2026-09-14: 모자·벨트·안경 추가) ────────────────
#   ★ 순서가 곧 화면의 칸 순서다. 프론트(VF_CATEGORIES)와 같은 순서를 쓴다 —
#     한쪽만 늘리면 화면의 드롭다운과 서버가 아는 칸이 어긋난다.
SLOT_ORDER = ["상의", "하의", "아우터", "원피스(셋업)", "신발", "양말",
              "모자", "벨트", "안경"]
AUTO = "자동 분류"
CATEGORIES = set(SLOT_ORDER) | {AUTO}
MODEL = "gpt-image-2.5-sunburst"
# 칸 수만큼은 받을 수 있어야 한다 — 칸을 9개로 늘려 놓고 6장에서 자르면
# 사용자가 채운 사진이 조용히 버려진다.
MAX_ITEMS = len(SLOT_ORDER)

# 칸마다 어떻게 입혀야 하는가. prompt() 가 이 표를 읽는다 —
# 칸을 늘릴 때 프롬프트 문장을 손으로 이어 붙이지 않도록 한자리에 모은다.
WEAR_GUIDE = {
    "상의": "상체에 입히고 여밈과 기장은 상품 사진의 형태를 그대로 따르세요",
    "하의": "허리선에 맞춰 입히고 기장과 밑단 처리를 그대로 두세요",
    "아우터": "상의 위에 겹쳐 입히고 어깨선과 소매 길이를 몸에 맞추세요",
    "원피스(셋업)": "한 벌로 입히고 다른 상·하의와 겹치지 않게 하세요",
    "신발": "두 발에 맞춰 신기고 발목 각도와 바닥 접지를 자연스럽게 하세요",
    "양말": "신발 안쪽과 발목 높이에 맞게 자연스럽게 신기세요",
    "모자": "머리 크기에 맞춰 씌우고 헤어라인과 머리 모양이 부자연스럽게 눌리지 않게 하세요",
    "벨트": "허리선의 벨트 고리 위치에 채우고 버클 방향과 남는 스트랩을 자연스럽게 두세요",
    "안경": "눈 위치와 얼굴 폭에 맞춰 씌우고 렌즈 너머로 눈이 비치게 하세요",
}

# ── 착장 옵션 (2026-09-14) ──────────────────────────────────
#   ★ 켠 것만 문장이 붙는다. 전부 꺼 두면 예전 프롬프트와 같다 —
#     끄는 것이 "닫아라"는 지시가 되면 사용자가 고르지 않은 연출이 들어간다.
OPTION_LINES = {
    "outer_layered": ("아우터가 둘 이상이면 얇고 짧은 것을 안쪽, 두껍고 긴 것을 "
                      "바깥쪽으로 두어 자연스럽게 레이어드하세요."),
    "outer_open": "아우터는 앞을 열어 입은 상태로 표현하고 안에 입은 옷이 보이게 하세요.",
    "outer_closed": "아우터는 앞을 여미거나 잠근 상태로 표현하세요.",
    "top_open": "상의는 앞을 열어 입은 상태로 표현하고 안에 받쳐 입은 옷이 보이게 하세요.",
    "top_closed": "상의는 앞을 여미거나 잠근 상태로 표현하세요.",
}
# 서로 맞서는 짝. 둘 다 켜져 오면 어느 쪽도 쓰지 않는다 —
# 모순된 지시를 보내느니 모델이 알아서 하게 두는 편이 낫다.
OPTION_CONFLICTS = [("outer_open", "outer_closed"), ("top_open", "top_closed")]


def option_lines(options) -> list[str]:
    """켜진 옵션만 문장으로. 모르는 이름은 조용히 버린다."""
    if not isinstance(options, dict):
        return []
    on = [k for k in OPTION_LINES if options.get(k)]
    for a, b in OPTION_CONFLICTS:
        if a in on and b in on:
            on = [k for k in on if k not in (a, b)]
    return [OPTION_LINES[k] for k in OPTION_LINES if k in on]
_DATA_URL = re.compile(r"^data:(image/(?:png|jpeg|webp));base64,(.+)$", re.I | re.S)


def decode_image(data_url: str, max_bytes: int = 5 * 1024 * 1024) -> tuple[bytes, str]:
    hit = _DATA_URL.match(str(data_url or ""))
    if not hit:
        raise ValueError("지원하는 이미지 형식이 아닙니다.")
    try:
        raw = base64.b64decode(hit.group(2), validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("이미지를 읽을 수 없습니다.") from exc
    if not raw or len(raw) > max_bytes:
        raise ValueError("이미지는 5MB 이하만 사용할 수 있습니다.")
    ext = "jpg" if hit.group(1).lower() == "image/jpeg" else hit.group(1).split("/")[1]
    return raw, ext


def prompt(categories: list[str], options: dict | None = None) -> str:
    cats = [c if c in CATEGORIES else AUTO for c in categories]
    item_guide = ", ".join(
        (f"{i + 2}번째 이미지는 사진을 보고 종류를 먼저 판별"
         if category == AUTO
         else f"{i + 2}번째 이미지는 {category} — {WEAR_GUIDE[category]}")
        for i, category in enumerate(cats)
    )
    body = [
        f"첫 번째 이미지의 모델에게 나머지 상품을 한 번에 자연스럽게 입혀 주세요. {item_guide}.",
        "각 상품의 색상, 패턴, 로고, 소재 질감, 봉제선과 실루엣을 정확히 보존하세요.",
        "여러 상품은 실제 옷을 입는 순서와 레이어 관계에 맞춰 하나의 코디로 조합하세요.",
    ]
    body += option_lines(options)
    body += [
        "모델의 얼굴, 체형, 포즈, 머리, 배경과 조명은 바꾸지 마세요.",
        "사진처럼 자연스러운 전신 패션 화보로 만들고 입력 모델 이미지와 같은 구도를 유지하세요.",
    ]
    return " ".join(body)


def _items(items: list[dict] | None, image_data_url: str | None,
           category: str | None) -> list[dict]:
    """새 다중 입력과 이전 단일 입력을 같은 검증 경로로 정리한다."""
    rows = items if isinstance(items, list) else []
    if not rows and image_data_url:
        rows = [{"image": image_data_url, "category": category or "상의"}]
    clean = []
    for row in rows[:MAX_ITEMS]:
        if not isinstance(row, dict) or not row.get("image"):
            continue
        cat = str(row.get("category") or AUTO)
        clean.append({"image": str(row["image"]),
                      "category": cat if cat in CATEGORIES else AUTO})
    if not clean:
        raise ValueError("입혀볼 아이템 사진이 필요합니다.")
    return clean


def generate(*, model_id: str, items: list[dict] | None = None,
             image_data_url: str | None = None, category: str | None = None,
             options: dict | None = None) -> dict:
    model = MODELS.get(model_id)
    if not model or not model["path"].is_file():
        raise ValueError("선택한 AI 모델을 찾을 수 없습니다.")
    chosen = _items(items, image_data_url, category)
    decoded = [(decode_image(row["image"]), row["category"]) for row in chosen]
    if sum(len(raw) for ((raw, _ext), _cat) in decoded) > 20 * 1024 * 1024:
        raise ValueError("아이템 이미지 전체 용량은 20MB 이하만 사용할 수 있습니다.")
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")
    with model["path"].open("rb") as model_file:
        files = [
            ("image[]", (model["path"].name, model_file, "image/png")),
        ]
        for index, ((raw, ext), _cat) in enumerate(decoded, start=1):
            files.append(("image[]",
                          (f"item-{index}.{ext}", raw,
                           f"image/{'jpeg' if ext == 'jpg' else ext}")))
        response = requests.post(
            "https://api.openai.com/v1/images/edits",
            headers={"Authorization": f"Bearer {key}"},
            data={"model": MODEL,
                  "prompt": prompt([row["category"] for row in chosen], options),
                  "size": "1024x1024", "n": "1"},
            files=files,
            timeout=120,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"이미지 생성 요청이 실패했습니다 (HTTP {response.status_code}).")
    payload = response.json()
    encoded = ((payload.get("data") or [{}])[0]).get("b64_json")
    if not encoded:
        raise RuntimeError("생성된 이미지를 받지 못했습니다.")
    return {"image": "data:image/png;base64," + encoded, "model": MODEL,
            "model_label": model["label"],
            "categories": [row["category"] for row in chosen],
            # 어떤 옵션이 실제로 프롬프트에 실렸나. 화면엔 안 뜨지만 로그로 본다.
            "options": [k for k in OPTION_LINES
                        if OPTION_LINES[k] in option_lines(options)],
            "item_count": len(chosen)}


# ── 사진 → 착장 칸 자동 분류 (2026-09-13) ──────────────────────
#   왜 서버가 하나 —
#     화면은 사진을 순서대로 칸에 넣을 수밖에 없다. 스커트를 올렸는데 '상의' 칸이
#     차 버리면 사용자가 지우고 다시 넣어야 했다. 어떤 옷인지 아는 것은 사진을
#     볼 수 있는 쪽뿐이라, 판별은 여기서 한다.
#   ★ 값을 지어내지 않는다. 확실하지 않으면 "자동 분류" 로 남긴다 —
#     그러면 생성 프롬프트가 예전처럼 스스로 판별한다(위 prompt()).
SLOTS = list(SLOT_ORDER)

_CLASSIFY_INSTRUCTIONS = (
    "FEEDiT 착장 합성용 분류기입니다. 각 사진에 담긴 의류·잡화가 어느 칸에 들어가야 "
    "하는지만 고르세요.\n"
    "- 상의: 티셔츠·셔츠·니트·블라우스·후디 등 상체에 입는 옷\n"
    "- 하의: 바지·스커트·반바지 등 하체에 입는 옷\n"
    "- 아우터: 코트·재킷·점퍼·가디건 등 겉에 걸치는 옷\n"
    "- 원피스(셋업): 원피스·점프수트·상하 세트\n"
    "- 신발 / 양말: 각각 신발과 양말\n"
    "- 모자: 캡·버킷햇·비니 등 머리에 쓰는 것\n"
    "- 벨트: 허리에 채우는 벨트\n"
    "- 안경: 안경·선글라스\n"
    "- 어느 칸인지 확실하지 않거나 착용물이 아니면 '자동 분류'\n"
    "사진에 보이는 것만 보고 고르세요. 브랜드·가격·트렌드는 판단하지 마세요.\n"
    "categories 배열은 입력한 사진과 같은 순서, 같은 개수로 돌려주세요."
)


def classify(images: list[str]) -> list[str]:
    """사진 순서대로 칸 이름을 돌려준다. 실패하면 전부 '자동 분류'."""
    from . import llm

    rows = [u for u in (images or []) if isinstance(u, str) and u.strip()][:MAX_ITEMS]
    fallback = [AUTO] * len(rows)
    if not rows or not llm.available():
        return fallback
    content: list[dict] = [{"type": "input_text",
                            "text": "각 사진이 어느 칸인지 순서대로 골라 주세요."}]
    for u in rows:
        content.append({"type": "input_image", "image_url": u})
    schema = llm.strict_schema("feedit_vton_slots", {
        "categories": {"type": "array",
                       "items": {"type": "string", "enum": SLOTS + [AUTO]}},
    }, ["categories"])
    got = llm.respond(_CLASSIFY_INSTRUCTIONS, [{"role": "user", "content": content}],
                      schema, timeout=20, **llm.role("vision"))
    cats = (got or {}).get("categories")
    if not isinstance(cats, list):
        return fallback
    out = [str(c) if str(c) in CATEGORIES else AUTO for c in cats[:len(rows)]]
    out += [AUTO] * (len(rows) - len(out))
    return out
