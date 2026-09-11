"""준비된 FEEDiT 모델과 상품 사진을 GPT Image 2 편집 API에 보낸다."""
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
CATEGORIES = {"상의", "하의", "아우터", "원피스(셋업)", "신발"}
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


def prompt(category: str) -> str:
    cat = category if category in CATEGORIES else "상의"
    return (
        f"첫 번째 이미지의 모델에게 두 번째 이미지의 {cat} 아이템을 자연스럽게 입혀 주세요. "
        "상품의 색상, 패턴, 로고, 소재 질감, 봉제선과 실루엣을 정확히 보존하세요. "
        "모델의 얼굴, 체형, 포즈, 머리, 배경과 조명은 바꾸지 마세요. "
        "사진처럼 자연스러운 전신 패션 화보로 만들고 입력 모델 이미지와 같은 구도를 유지하세요."
    )


def generate(*, image_data_url: str, model_id: str, category: str) -> dict:
    model = MODELS.get(model_id)
    if not model or not model["path"].is_file():
        raise ValueError("선택한 AI 모델을 찾을 수 없습니다.")
    raw, ext = decode_image(image_data_url)
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")
    with model["path"].open("rb") as model_file:
        files = [
            ("image[]", (model["path"].name, model_file, "image/png")),
            ("image[]", (f"item.{ext}", raw, f"image/{'jpeg' if ext == 'jpg' else ext}")),
        ]
        response = requests.post(
            "https://api.openai.com/v1/images/edits",
            headers={"Authorization": f"Bearer {key}"},
            data={"model": "gpt-image-2", "prompt": prompt(category),
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
    return {"image": "data:image/png;base64," + encoded, "model": "gpt-image-2",
            "model_label": model["label"], "category": category}
