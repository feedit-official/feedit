"""준비된 FEEDiT 모델과 여러 상품 사진을 GPT Image 2.5 (Sunburst · Flare)에 보낸다."""
from __future__ import annotations

import base64
import contextlib
import os
import random
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests


ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / "assets" / "vton_models"
# ── 모델 사진 ────────────────────────────────────────────────
#   <id>/master/ 기준 사진 여섯 장 · <id>/poses/ 자세 여러 장.
MODELS = {
    "woman": {"label": "여성 모델", "dir": MODEL_DIR / "woman"},
    "man": {"label": "남성 모델", "dir": MODEL_DIR / "man"},
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
MASTER_DIR = "master"
POSE_DIR = "poses"
# ── 기준 사진 (2026-09-14) ──────────────────────────────────
#   왜 여섯 장이나 보내나 —
#     포즈 한 장만 보내면 그 한 장에 안 보이는 것은 모델이 지어낸다. 옆모습이
#     조금만 돌아가도 얼굴이 딴사람이 되고, 어깨너비와 다리 길이가 컷마다
#     달라졌다. 얼굴 셋(정면·좌45·우45)과 전신 셋(정면·측면·후면)을 같이 보내면
#     "이 사람은 어느 각도에서 이렇게 생겼다" 가 닫힌다 — 옷만 갈아입는 그림이 된다.
#   ★ 순서가 곧 프롬프트의 번호다. 파일 이름 앞의 01~06 이 그 순서를 잡는다 —
#     이름을 바꾸면 프롬프트가 가리키는 번호가 어긋난다(prompt() 주석 참고).
MASTER_COUNT = 6
REFERENCE_COUNT = MASTER_COUNT + 1          # 마스터 6 + 이번 컷의 포즈 1
# API 가 한 번에 받는 이미지 수. 기준 사진이 이 중 앞자리를 미리 쓴다.
MAX_IMAGES = 16


def _missing(model_id: str, folder: str, what: str, extra: str = "") -> str:
    """★ 무엇이 어디에 없는지까지 말한다 (2026-09-14).

    예전에는 어느 경우든 "선택한 AI 모델을 찾을 수 없습니다." 한 줄이었다.
    사진 폴더를 옮긴 뒤 옛 코드를 물고 있던 서버가 이 문구를 뱉었는데, 화면만
    봐서는 모델 이름이 틀린 건지 파일이 없는 건지 서버가 낡은 건지 알 수 없었다.
    """
    model = MODELS.get(model_id)
    label = model["label"] if model else model_id
    where = f"assets/vton_models/{model_id}/{folder}"
    tail = f" ({extra})" if extra else ""
    return (f"{label}의 {what}이 없습니다{tail} — {where} 를 확인하고, "
            f"사진을 옮겼다면 챗봇 서버를 다시 시작하세요.")


def _images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(path for path in folder.iterdir()
                  if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)


def masters(model_id: str) -> list[Path]:
    """얼굴 셋 + 전신 셋. 이름순이 곧 프롬프트가 부르는 순서다."""
    model = MODELS.get(model_id)
    return _images(model["dir"] / MASTER_DIR) if model else []


def poses(model_id: str) -> list[Path]:
    """이 모델로 쓸 수 있는 자세들."""
    model = MODELS.get(model_id)
    return _images(model["dir"] / POSE_DIR) if model else []


def pick_pose(model_id: str, pose: str | None = None) -> Path:
    """포즈 하나를 고른다. 이름을 콕 집어 주면 그것, 아니면 무작위.

    ★ 고른 결과를 화면에 돌려준다(generate 의 pose) — "왜 자세가 바뀌었나"
      하고 물었을 때 답할 수 있어야 한다.
    """
    found = poses(model_id)
    if not found:
        raise ValueError(_missing(model_id, POSE_DIR, "포즈 사진"))
    if pose:
        for path in found:
            if path.name == pose:
                return path
    return random.choice(found)


def references(model_id: str, pose: str | None = None) -> list[Path]:
    """모델에 대해 보낼 사진 전부 — 마스터 여섯 장 다음에 이번 컷의 포즈 한 장."""
    found = masters(model_id)
    if len(found) != MASTER_COUNT:
        raise ValueError(_missing(model_id, MASTER_DIR,
                                  f"기준 사진 {MASTER_COUNT}장",
                                  f"지금 {len(found)}장"))
    return found + [pick_pose(model_id, pose)]


# ── 착장 칸 (2026-09-14: 모자·벨트·안경 추가) ────────────────
#   ★ 순서가 곧 화면의 칸 순서다. 프론트(VF_CATEGORIES)와 같은 순서를 쓴다 —
#     한쪽만 늘리면 화면의 드롭다운과 서버가 아는 칸이 어긋난다.
SLOT_ORDER = ["상의", "하의", "아우터", "원피스(셋업)", "신발", "양말",
              "모자", "벨트", "안경"]
AUTO = "자동 분류"
CATEGORIES = set(SLOT_ORDER) | {AUTO}
# ── 생성 엔진 (2026-10-01) ──────────────────────────────────
#   사용자가 고른다. 기본은 화질 쪽(Sunburst), 빨리 보고 싶으면 Flare.
#   OpenAI 문서(2026-10-01 확인, developers.openai.com · GPT Image 2.5 prompting guide):
#     Sunburst — "optimized for quality", GPT Image 2 보다 높은 화질
#     Flare    — "optimized for speed", GPT Image 2 와 비슷한 화질
#     두 모델 모두 images/edits 를 받고, 해상도 한도(긴 변 3840 · 픽셀 8,294,400)와
#     quality 값(low … max)이 같다 — 그래서 SIZE · QUALITY 를 따로 두지 않는다.
#   ★ 얼마나 빨라지는지는 우리 입력(기준 사진 7장 + 상품)으로 재 봐야 안다.
#     결과의 elapsed_ms 로 남긴다. 문서도 "자기 작업으로 재라" 고 적어 두었다.
ENGINES = {
    "sunburst": {"model": "gpt-image-2.5-sunburst", "label": "GPT Image 2.5 Sunburst"},
    "flare": {"model": "gpt-image-2.5-flare", "label": "GPT Image 2.5 Flare"},
}
DEFAULT_ENGINE = "sunburst"
MODEL = ENGINES[DEFAULT_ENGINE]["model"]


def engine_of(name: str | None) -> str:
    """모르는 이름은 기본 엔진으로 — 옛 화면은 engine 을 보내지 않는다."""
    key = str(name or "").strip().lower()
    return key if key in ENGINES else DEFAULT_ENGINE
# ── 출력 해상도·품질 (2026-09-14) ───────────────────────────
#   1024x1024(정사각, 기본 품질)로 내던 것을 4K급 세로로 올린다.
#   ★ 왜 3840x2160(표준 4K)이 아니라 2480x3312 인가 —
#     모델 사진이 3:4 세로다. 가로 4K 로 내면 전신이 가운데 조금만 남고,
#     세로 4K(2160x3840, 9:16)로 내면 사진보다 훨씬 좁고 길어 양옆이 잘린다.
#     같은 3:4 를 유지한 채 Sunburst 가 받아 주는 한계까지 키운 값이 이것이다.
#   ★ API 제약 (images/edits): 두 변 모두 16의 배수, 긴 변 ≤ 3840px,
#     총 픽셀 ≤ 8,294,400, 가로세로비 1:3 ~ 3:1.
#       2480 = 16×155, 3312 = 16×207, 긴 변 3312, 2480×3312 = 8,213,760 픽셀.
#     2560x1440 을 넘는 해상도는 OpenAI 가 아직 실험적이라고 적어 두었다 —
#     결과가 이상하면 가장 먼저 의심할 값이다.
SIZE = "2480x3312"
# low·medium·high·auto 는 공통, xhigh·max 는 2.5 계열만 받는다. 지금은 high.
QUALITY = "high"
# ── 내보내는 형식 ──────────────────────────────────────────
#   ★ PNG 이 아니다. 화면까지 오는 길에 한도가 하나 있다 —
#     결과는 data URL(base64)로 JSON 에 실려 Vercel 함수(api/v1/virtual-fitting.js)를
#     거쳐 온다. Vercel 함수의 응답 본문 상한은 4.5MB 인데, 2480x3312 PNG 은
#     10MB 안팎이고 base64 로 싸면 1.33배라 13MB 쯤 된다 — 그대로 두면 배포된
#     화면에서는 4K 가 한 장도 안 나온다. webp 는 같은 해상도를 1~2MB 로 담는다.
#     quality(생성 품질)와는 별개다 — 그림을 덜 그리는 게 아니라 담는 그릇만 바꾼다.
#   되돌리려면 이 두 줄만 "png" 로 바꾸면 된다(대신 위의 한도를 먼저 풀어야 한다).
OUTPUT_FORMAT = "webp"
#   ★ 85 는 너무 낮았다 (2026-09-14). 원단 결과 머리카락이 눈에 띄게 뭉개져서
#     "4K 로 올렸는데 오히려 화질이 나빠졌다" 는 말을 들었다. 100 으로 올려도
#     같은 사진이 1MB 안쪽이라(base64 1.4MB) 4.5MB 한도에 한참 못 미친다 —
#     아낄 이유가 없던 자리에서 화질을 깎고 있었다.
OUTPUT_COMPRESSION = "100"
MIME = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}
# 칸 수만큼은 받을 수 있어야 한다 — 칸을 9개로 늘려 놓고 6장에서 자르면
# 사용자가 채운 사진이 조용히 버려진다.
# ★ 다만 API 한 번에 16장이고 기준 사진이 7장을 먼저 쓴다. 칸을 더 늘리려면
#   기준 사진을 줄이든지 해야 한다 — 조용히 잘리지 않게 여기서 함께 계산한다.
MAX_ITEMS = min(len(SLOT_ORDER), MAX_IMAGES - REFERENCE_COUNT)

# 칸마다 어떻게 입혀야 하는가. prompt() 가 이 표를 읽는다 —
# 칸을 늘릴 때 프롬프트 문장을 손으로 이어 붙이지 않도록 한자리에 모은다.
WEAR_GUIDE = {
    # ★ '여밈 방식' 이다 — 단추·지퍼가 어디에 어떻게 달렸나. 열었나 여몄나(상태)는
    #   옵션(top_open/top_closed)이 정한다. 예전 "여밈 … 그대로" 는 기본 '열어 입기'
    #   문장과 맞섰다 (2026-10-01).
    "상의": "상체에 입히고 기장과 여밈 방식(단추·지퍼 위치)은 상품 사진을 그대로 따르세요",
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
#   ★ 2026-10-01 — 화면이 바뀌었다. 열기/여미기는 칸(상의·아우터)마다 스위치 하나이고
#     기본이 '열어 입기' 다. 그래서 이제 **아무 것도 안 만진 요청에도 outer_open ·
#     top_open 이 실린다.** 두 가지를 같이 고쳤다.
#       ① 문장이 그 칸의 옷이 있을 때만 붙는다(SLOT_OF). 하의만 넣었는데 "아우터는 앞을
#          열어" 가 실리면 모델이 없던 아우터를 그려 넣는다.
#       ② 여밈이 없는 옷(티셔츠·니트·풀오버)은 그대로 두라고 문장 안에서 말한다. 기본이
#          켜진 이상, 이 옷에 열린 트임을 새로 만들라는 지시가 되면 안 된다.
#     상의를 '열어 입기' 로 두고 안에 받쳐 입을 것이 없을 때는 맨살이 드러나지 않게
#     단추를 위쪽만 풀라고 적는다 — 기본값이 사진을 망치면 안 된다.
OPTION_LINES = {
    "outer_layered": ("아우터가 둘 이상이면 얇고 짧은 것을 안쪽, 두껍고 긴 것을 "
                      "바깥쪽으로 두어 자연스럽게 레이어드하세요."),
    "outer_open": ("앞여밈(지퍼·단추)이 있는 아우터는 앞을 열어 입은 상태로 표현하고 안에 "
                   "입은 옷이 보이게 하세요. 앞여밈이 없는 아우터는 그대로 두세요."),
    "outer_closed": ("앞여밈(지퍼·단추)이 있는 아우터는 앞을 여미거나 잠근 상태로 표현하세요."),
    "top_open": ("앞여밈(단추·지퍼)이 있는 상의는 앞을 열어 입은 상태로 표현하세요. 안에 받쳐 "
                 "입은 상의가 없으면 단추를 위쪽 한두 개만 풀어 자연스럽게 연출하세요. "
                 "티셔츠·니트처럼 앞여밈이 없는 상의는 그대로 두고 트임을 새로 만들지 마세요."),
    "top_closed": "앞여밈(단추·지퍼)이 있는 상의는 끝까지 여민 상태로 표현하세요.",
    # ── 핏 (2026-10-01) — 화면은 오버핏 · 정핏 · 슬림핏 세 칸, 기본 정핏.
    #   정핏은 문장을 붙이지 않는다 — 상품 사진의 핏 그대로가 정핏이고, 예전 동작이다.
    "fit_over": ("핏은 오버핏으로 표현하세요 — 한두 치수 크게 입은 것처럼 어깨선이 살짝 "
                 "내려오고 몸판·소매·바짓단에 여유가 생기게 하세요. 이 핏 지시가 상품 "
                 "사진의 실루엣보다 우선합니다."),
    "fit_slim": ("핏은 슬림핏으로 표현하세요 — 몸판·소매·바짓단이 몸선을 따라 좁게 "
                 "떨어지게 하세요. 이 핏 지시가 상품 사진의 실루엣보다 우선합니다."),
}
# 서로 맞서는 짝. 둘 다 켜져 오면 어느 쪽도 쓰지 않는다 —
# 모순된 지시를 보내느니 모델이 알아서 하게 두는 편이 낫다.
OPTION_CONFLICTS = [("outer_open", "outer_closed"), ("top_open", "top_closed"),
                    ("fit_over", "fit_slim")]
# 이 옵션은 이 칸의 옷이 있을 때만 의미가 있다. 칸을 모르는 사진('자동 분류')이
# 있으면 그 사진이 이 칸일 수 있으니 붙인다 — 문장 자체가 조건부다.
SLOT_OF = {"outer_open": "아우터", "outer_closed": "아우터",
           "top_open": "상의", "top_closed": "상의"}
FIT_KEYS = ("fit_over", "fit_slim")


def option_keys(options, categories: list[str] | None = None) -> list[str]:
    """프롬프트에 실제로 실을 옵션 이름. 모르는 이름은 조용히 버린다.

    categories 를 주면 그 칸의 옷이 없는 옵션을 뺀다(None 이면 칸을 보지 않는다).
    """
    if not isinstance(options, dict):
        return []
    on = [k for k in OPTION_LINES if options.get(k)]
    for a, b in OPTION_CONFLICTS:
        if a in on and b in on:
            on = [k for k in on if k not in (a, b)]
    if categories is not None:
        cats = set(categories)
        on = [k for k in on
              if k not in SLOT_OF or SLOT_OF[k] in cats or AUTO in cats]
    return on


def option_lines(options, categories: list[str] | None = None) -> list[str]:
    """켜진 옵션만 문장으로."""
    return [OPTION_LINES[k] for k in option_keys(options, categories)]


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


# ── DB 상품 사진을 주소로 받는다 (2026-09-22) ────────────────
#   왜 서버가 받나 —
#     상품 썸네일(commerce.product_source.thumbnail_url)은 플랫폼 CDN 주소다.
#     화면에서 fetch 하면 CORS 로 막히고, 막히는 자리가 브라우저라 서버 로그에는
#     아무것도 안 남는다. 받는 쪽을 서버로 옮긴다.
#   부수 이득 — 요청 본문이 몇 백 바이트로 줄어 버셀 중계 함수의 4.5MB 상한
#     (api/v1/virtual-fitting.js)에 걸리지 않는다.
#   ★ 아무 주소나 대신 받아 주지 않는다. 허용한 호스트만 — 그러지 않으면 우리
#     서버가 남의 요청을 대신 쏘는 통로(SSRF)가 된다.
#   ★ 호스트 목록은 환경변수로 넓힌다. 실제 값은 DB 가 원본이다:
#       SELECT DISTINCT split_part(thumbnail_url,'/',3) FROM commerce.product_source;
#   ★ 아래 넷은 2026-09-22 DB 실측이다(commerce.product_source 72,352건):
#       image.msscdn.net 24,251 · cf.product-image.s3.zigzag.kr 18,268 ·
#       d3ha2047wt6x28.cloudfront.net 1,353 · kream-phinf.pstatic.net 655.
#     같은 조회에서 호스트가 아예 없는 상대 경로가 27,424건 나왔다 — 그것은
#     fit.absolute_image() 가 주소로 만든다.
#   ★ 2026-10-01 — 지그재그 사진이 **s3 가 없는** 호스트(cf.product-image.s.zigzag.kr)로도
#     온다. 운영 /api/products 실측: 긱시크·미니멀 상의·하의 21건 중 7건이 이 호스트였고,
#     목록에 없어 코디에서 전부 빠졌다. 둘 다 받는다.
ALLOWED_IMAGE_HOSTS = {
    h.strip().lower() for h in (
        os.getenv("FEEDIT_VTON_IMAGE_HOSTS")
        or "image.msscdn.net,cf.product-image.s3.zigzag.kr,cf.product-image.s.zigzag.kr,"
           "d3ha2047wt6x28.cloudfront.net,kream-phinf.pstatic.net"
    ).split(",") if h.strip()
}
FETCH_TIMEOUT = 8
FETCH_MAX_BYTES = 5 * 1024 * 1024


def image_host_allowed(url: str) -> bool:
    """이 주소를 우리가 받아도 되는가. 사진을 보내기 전에 먼저 묻는 자리다."""
    return (urlparse(str(url or "")).hostname or "").lower() in ALLOWED_IMAGE_HOSTS


def fetch_as_data_url(url: str, max_bytes: int = FETCH_MAX_BYTES) -> str:
    """상품 사진 주소 하나를 data URL 로 바꾼다. 실패는 사유를 담아 올린다."""
    host = (urlparse(str(url or "")).hostname or "").lower()
    if not host:
        raise ValueError("상품 사진 주소를 읽을 수 없습니다.")
    if host not in ALLOWED_IMAGE_HOSTS:
        # ★ 호스트를 문구에 적는다 — 목록에 한 줄 더하면 되는 일을, 화면만 보고는
        #   무엇이 막혔는지 알 수 없던 자리다.
        raise ValueError(f"허용되지 않은 상품 사진 주소입니다 ({host}) — "
                         f"FEEDIT_VTON_IMAGE_HOSTS 를 확인하세요.")
    try:
        # 일부 CDN 은 User-Agent 없는 요청을 막는다.
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"},
                           timeout=FETCH_TIMEOUT)
        res.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"상품 사진을 받지 못했습니다 ({type(exc).__name__}).") from exc
    mime = (res.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if mime not in set(MIME.values()):
        raise ValueError(f"지원하는 이미지 형식이 아닙니다 ({mime or '알 수 없음'}).")
    raw = res.content
    if not raw or len(raw) > max_bytes:
        raise ValueError("상품 사진은 5MB 이하만 사용할 수 있습니다.")
    return "data:" + mime + ";base64," + base64.b64encode(raw).decode("ascii")


def prompt(categories: list[str], options: dict | None = None) -> str:
    """보내는 이미지 순서를 그대로 글로 옮긴다.

    ★ 번호가 references() 의 순서와 한 칸도 어긋나면 안 된다 —
        1~3   얼굴 기준 (정면 · 우45 · 좌45)
        4~6   체형 기준 (전신 정면 · 측면 · 후면)
        7     이번 컷의 자세와 구도
        8~    입힐 상품
      기준 사진을 늘리거나 줄이면 MASTER_COUNT 와 이 문장을 같이 고쳐야 한다.
    """
    cats = [c if c in CATEGORIES else AUTO for c in categories]
    first = REFERENCE_COUNT + 1                 # 상품이 시작하는 번호
    item_guide = ", ".join(
        (f"{i + first}번째 이미지는 사진을 보고 종류를 먼저 판별"
         if category == AUTO
         else f"{i + first}번째 이미지는 {category} — {WEAR_GUIDE[category]}")
        for i, category in enumerate(cats)
    )
    body = [
        f"1번부터 {REFERENCE_COUNT}번까지는 모두 같은 한 사람을 찍은 기준 사진입니다. "
        "새로운 인물을 만들지 말고 이 사람을 그대로 쓰세요.",
        "1~3번은 얼굴 기준(정면·우45·좌45)입니다. 이목구비, 얼굴형, 피부 톤, "
        "머리 색과 길이와 결을 이 셋과 같게 하세요.",
        "4~6번은 체형 기준(전신 정면·측면·후면)입니다. 키, 어깨너비, 허리와 골반 "
        "폭, 팔다리 길이와 굵기를 이 셋과 같게 하세요.",
        # ★ 다리가 짧아 보인다는 말을 자주 들었다 (2026-09-14). 자세를 따라
        #   그리다 보면 허리선과 다리 길이가 같이 눌린다 — 비율만은 체형 기준을
        #   보라고 따로 못 박는다. 포즈 쪽에서도 단축법이 심한 컷은 빼 두었다.
        "특히 다리 길이와 허리선 높이는 4~6번의 비율을 그대로 지키세요. "
        "자세 때문에 다리가 짧아 보이게 만들지 마세요.",
        f"{REFERENCE_COUNT}번은 이번 컷의 기준입니다. 자세, 팔다리 위치, 얼굴 방향, "
        "카메라 각도, 화면 안에서의 크기와 위치, 배경과 조명을 이 사진 그대로 두세요.",
        f"{first}번째 이미지부터가 입힐 상품입니다. {item_guide}.",
        # ★ 핏을 골랐으면 '실루엣 보존' 을 빼고 말한다 — 같은 프롬프트 안에서 "실루엣을
        #   그대로" 와 "오버핏으로" 가 맞서면 모델이 어느 쪽도 제대로 하지 않는다.
        ("각 상품의 색상, 패턴, 로고, 소재 질감, 봉제선을 정확히 보존하세요."
         if any(k in FIT_KEYS for k in option_keys(options, cats))
         else "각 상품의 색상, 패턴, 로고, 소재 질감, 봉제선과 실루엣을 정확히 보존하세요."),
        "여러 상품은 실제 옷을 입는 순서와 레이어 관계에 맞춰 하나의 코디로 조합하세요.",
    ]
    body += option_lines(options, cats)
    body += [
        f"바꾸는 것은 옷뿐입니다. 얼굴, 머리, 체형, 자세, 배경, 조명은 "
        f"기준 사진 그대로 두세요 — 특히 얼굴이 다른 사람처럼 보이면 안 됩니다.",
        f"사진처럼 자연스러운 전신 패션 화보로 만들고 {REFERENCE_COUNT}번 이미지와 "
        "같은 구도를 유지하세요.",
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
        if not isinstance(row, dict):
            continue
        # ★ 사진은 data URL 이거나 상품 사진 주소다 (2026-09-22). 주소로 오면
        #   여기서 받아 둔다 — 아래 decode_image 는 data URL 만 읽는다.
        if not row.get("image") and row.get("image_url"):
            row = {**row, "image": fetch_as_data_url(str(row["image_url"]))}
        if not row.get("image"):
            continue
        cat = str(row.get("category") or AUTO)
        clean.append({"image": str(row["image"]),
                      "category": cat if cat in CATEGORIES else AUTO})
    if not clean:
        raise ValueError("입혀볼 아이템 사진이 필요합니다.")
    return clean


def generate(*, model_id: str, items: list[dict] | None = None,
             image_data_url: str | None = None, category: str | None = None,
             options: dict | None = None, pose: str | None = None,
             engine: str | None = None) -> dict:
    model = MODELS.get(model_id)
    engine = engine_of(engine)
    image_model = ENGINES[engine]["model"]
    if not model:
        raise ValueError(f"'{model_id}' 는 없는 AI 모델입니다 "
                         f"(쓸 수 있는 것: {', '.join(sorted(MODELS))}).")
    # 마스터 여섯 장 + 이번 컷의 포즈 한 장. 마지막 것이 뽑힌 포즈다.
    refs = references(model_id, pose)
    model_path = refs[-1]
    chosen = _items(items, image_data_url, category)
    decoded = [(decode_image(row["image"]), row["category"]) for row in chosen]
    if sum(len(raw) for ((raw, _ext), _cat) in decoded) > 20 * 1024 * 1024:
        raise ValueError("아이템 이미지 전체 용량은 20MB 이하만 사용할 수 있습니다.")
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")
    categories = [row["category"] for row in chosen]
    started = time.monotonic()
    # ★ 기준 사진이 먼저, 상품이 나중 — prompt() 가 부르는 번호 그대로다.
    #   파일은 보내는 동안 열어 둔다(ExitStack). 하나씩 열고 닫으면 requests 가
    #   읽을 때는 이미 닫혀 있다.
    with contextlib.ExitStack() as stack:
        files = [("image[]", (path.name, stack.enter_context(path.open("rb")),
                              "image/png"))
                 for path in refs]
        for index, ((raw, ext), _cat) in enumerate(decoded, start=1):
            files.append(("image[]",
                          (f"item-{index}.{ext}", raw,
                           f"image/{'jpeg' if ext == 'jpg' else ext}")))
        response = requests.post(
            "https://api.openai.com/v1/images/edits",
            headers={"Authorization": f"Bearer {key}"},
            data={"model": image_model,
                  "prompt": prompt(categories, options),
                  "size": SIZE, "quality": QUALITY,
                  "output_format": OUTPUT_FORMAT,
                  "output_compression": OUTPUT_COMPRESSION,
                  "n": "1"},
            files=files,
            # 4K·high 한 장은 1024 정사각보다 한참 오래 걸린다.
            # 120초로는 다 만들어 놓고도 우리가 먼저 끊는다.
            timeout=300,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"이미지 생성 요청이 실패했습니다 (HTTP {response.status_code}).")
    payload = response.json()
    encoded = ((payload.get("data") or [{}])[0]).get("b64_json")
    if not encoded:
        raise RuntimeError("생성된 이미지를 받지 못했습니다.")
    mime = MIME.get(OUTPUT_FORMAT, "image/png")
    return {"image": "data:" + mime + ";base64," + encoded, "model": image_model,
            "engine": engine, "engine_label": ENGINES[engine]["label"],
            # 요청을 보내고 받기까지 — 엔진별로 얼마나 걸리는지 재는 자리다.
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "model_label": model["label"],
            "size": SIZE, "quality": QUALITY, "format": OUTPUT_FORMAT,
            # 어느 포즈가 뽑혔나 — 같은 자세를 한 번 더 내고 싶을 때 이 이름을
            # pose 로 되돌려 주면 된다.
            "pose": model_path.name,
            # 기준 사진이 실제로 몇 장 실렸나 — 폴더가 비어도 조용히 넘어가지
            # 않게 여기서 드러낸다.
            "references": [path.name for path in refs],
            "categories": categories,
            # 어떤 옵션이 실제로 프롬프트에 실렸나. 화면엔 안 뜨지만 로그로 본다.
            "options": option_keys(options, categories),
            "item_count": len(chosen)}


# ── 사진 → 착장 칸 자동 분류 (2026-09-13) ──────────────────────
#   왜 서버가 하나 —
#     화면은 사진을 순서대로 칸에 넣을 수밖에 없다. 스커트를 올렸는데 '상의' 칸이
#     차 버리면 사용자가 지우고 다시 넣어야 했다. 어떤 옷인지 아는 것은 사진을
#     볼 수 있는 쪽뿐이라, 판별은 여기서 한다.
#   ★ 값을 지어내지 않는다. 확실하지 않으면 "자동 분류" 로 남긴다 —
#     그러면 생성 프롬프트가 예전처럼 스스로 판별한다(위 prompt()).
SLOTS = list(SLOT_ORDER)

_INSPECT_INSTRUCTIONS = (
    "FEEDiT 착장 합성용 검수기입니다. 각 사진에 담긴 의류·잡화를 보고 세 가지만 "
    "고르세요 — 어느 칸에 들어가는지, 앞을 열 수 있는 옷인지, 겹쳐 입을 때 얇은 "
    "쪽인지.\n"
    "- 상의: 티셔츠·셔츠·니트·블라우스·후디 등 상체에 입는 옷\n"
    "- 하의: 바지·스커트·반바지 등 하체에 입는 옷\n"
    "- 아우터: 코트·재킷·점퍼·가디건 등 겉에 걸치는 옷\n"
    "- 원피스(셋업): 원피스·점프수트·상하 세트\n"
    "- 신발 / 양말: 각각 신발과 양말\n"
    "- 모자: 캡·버킷햇·비니 등 머리에 쓰는 것\n"
    "- 벨트: 허리에 채우는 벨트\n"
    "- 안경: 안경·선글라스\n"
    "- 어느 칸인지 확실하지 않거나 착용물이 아니면 '자동 분류'\n"
    "closure 는 사진에 실제로 보이는 여밈입니다(지퍼·버튼·스냅). 머리로 입는 옷처럼 "
    "여밈이 없으면 '없음', 사진에서 안 보이면 '모르겠음' 입니다.\n"
    "openable 은 앞을 열어 입은 모습으로 그릴 수 있는 옷인지입니다. 여밈이 보이면 "
    "yes, 머리로 입는 옷이면 no, 판단이 안 서면 unknown.\n"
    "layer 는 겹쳐 입을 때의 두께감입니다. 안 보이면 '모르겠음'.\n"
    "★ 지어내지 마세요. 사진에 보이는 것만 보고 고르고, 확실하지 않으면 "
    "'모르겠음'·unknown·'자동 분류' 를 고르세요. 브랜드·가격·트렌드는 판단하지 "
    "마세요.\n"
    "items 배열은 입력한 사진과 같은 순서, 같은 개수로 돌려주세요."
)
# 예전 이름 — /v1/fit-classify 와 테스트가 아직 이 이름을 쓴다.
_CLASSIFY_INSTRUCTIONS = _INSPECT_INSTRUCTIONS
CLOSURES = ["지퍼", "버튼", "스냅", "없음", "모르겠음"]
OPENABLE = ["yes", "no", "unknown"]
LAYERS = ["얇음", "보통", "두꺼움", "모르겠음"]
# 사진을 못 봤을 때의 값. ★ 빈칸이 아니라 "모른다" 다 — 아래 fit.prune_options 가
#   "모르면 연출을 빼지도 넣지도 않는다" 를 이 값으로 판단한다.
UNKNOWN = {"slot": AUTO, "closure": "모르겠음", "openable": "unknown", "layer": "모르겠음"}


def _inspect_schema():
    """★ strict 모드는 중첩 객체에도 additionalProperties:false 와 required 전부
    나열을 요구한다(llm.strict_schema 주석). 그래서 손으로 짠다."""
    from . import llm
    row = {"type": "object", "additionalProperties": False,
           "properties": {"slot": {"type": "string", "enum": SLOTS + [AUTO]},
                          "closure": {"type": "string", "enum": CLOSURES},
                          "openable": {"type": "string", "enum": OPENABLE},
                          "layer": {"type": "string", "enum": LAYERS}},
           "required": ["slot", "closure", "openable", "layer"]}
    return llm.strict_schema("feedit_vton_items",
                             {"items": {"type": "array", "items": row}}, ["items"])


def inspect(images: list[str]) -> list[dict]:
    """사진 순서대로 {slot, closure, openable, layer} 를 돌려준다.

    ★ 실패하면 전부 UNKNOWN 이다. 예전 classify() 가 못 판별한 사진을 '자동 분류' 로
      남겨 생성 프롬프트가 스스로 판별하게 넘긴 것과 같은 태도 — 모르는 것을 아는
      척하지 않는다.
    """
    from . import llm

    rows = [u for u in (images or []) if isinstance(u, str) and u.strip()][:MAX_ITEMS]
    fallback = [dict(UNKNOWN) for _ in rows]
    if not rows or not llm.available():
        return fallback
    content: list[dict] = [{"type": "input_text",
                            "text": "각 사진의 칸·여밈·두께를 순서대로 골라 주세요."}]
    for u in rows:
        content.append({"type": "input_image", "image_url": u})
    got = llm.respond(_INSPECT_INSTRUCTIONS, [{"role": "user", "content": content}],
                      _inspect_schema(), timeout=20, **llm.role("vision"))
    got_rows = (got or {}).get("items")
    if not isinstance(got_rows, list):
        return fallback
    out: list[dict] = []
    for i in range(len(rows)):
        row = got_rows[i] if i < len(got_rows) and isinstance(got_rows[i], dict) else {}
        slot = str(row.get("slot") or "")
        out.append({
            "slot": slot if slot in CATEGORIES else AUTO,
            "closure": row.get("closure") if row.get("closure") in CLOSURES else "모르겠음",
            "openable": row.get("openable") if row.get("openable") in OPENABLE else "unknown",
            "layer": row.get("layer") if row.get("layer") in LAYERS else "모르겠음",
        })
    return out


def classify(images: list[str]) -> list[str]:
    """사진 순서대로 칸 이름만 돌려준다 — 화면의 칸 배치가 쓰는 값.

    ★ 판별은 inspect() 한 번으로 끝난다. 칸과 여밈을 따로 물으면 vision 호출이
      두 번이 된다(AGENTS.md §3 — 한 번에 받게 만든다).
    """
    return [row["slot"] for row in inspect(images)]
