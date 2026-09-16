"""
서버 — 팀원이 브라우저로 쓰는 조종석.

터미널을 몰라도 되게 만드는 게 목적이다.
`python -m feedit_crawler` 한 줄이면 브라우저가 열리고, 그 다음부터는 클릭.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
import re
import time
from datetime import datetime
import threading
import webbrowser
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import Body, FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import (HTMLResponse, JSONResponse, RedirectResponse,
                               StreamingResponse, FileResponse)
from pydantic import BaseModel

from . import auth, coverage, health, intent, keystore, problems, siteform, wizard
from . import settings as cfgset, social, trend_chat, youtube_insights
from .adapter import SiteConfig
from .probe import probe
from .runner import CrawlJob
from .scheduler import Scheduler
from .store import Store
from .llm_analysis import AnalysisError, OpenAITextAnalyzer, MODEL, PROMPT_VERSION
from .llm_batch import LLMBatch
from .entity_linker import EntityLinker
from .entity_backfill import EntityBackfill
from .lexicon import Lexicon
from .metrics import MetricAggregator, SHADOW_SOURCE_WEIGHTS, SHADOW_VERSION
from .youtube_asr import ASRWorker
from .youtube_ocr import OCRWorker

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
BACKUP_DIR = CONFIG_DIR / ".backup"      # 직전 버전과 삭제한 설정이 쌓이는 곳
# ★ 시험할 때는 진짜 데이터를 건드리지 않는다.
#   FEEDIT_DATA_DIR 를 주면 그쪽을 쓴다.
#
#   이걸 안 만들어 두고 시험을 돌렸다가 실제 관리자 코드를 재발급해
#   쓰던 코드가 무효가 된 적이 있다. 시험이 운영 데이터를 만지면
#   언젠가는 반드시 사고가 난다.
DATA_DIR = Path(cfgset.get("FEEDIT_DATA_DIR") or (ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
UI_FILE = ROOT / "ui" / "index.html"

UI_LOGIN = ROOT / "ui" / "login.html"

app = FastAPI(title="FEEDiT 관리자")

store = Store(DATA_DIR / "feedit.db")
store.target_scope_enabled = True
AUTH = auth.Auth(store)
# 켜질 때 한 번 치운다. 만료됐거나 오래 안 쓴 세션이 계속 쌓여
# '14곳에서 열려 있음' 처럼 보이던 것을 여기서 걷어 낸다.
#
# ★ 다만 살아 있는 세션까지 지우지는 않는다.
#   코드를 고칠 때마다 서버가 다시 뜨는데, 그때마다 전원 로그아웃되면
#   팀원들이 작업 중에 계속 튕긴다. 대신 '지금 접속 중'은 최근 활동으로
#   판단하므로, 창을 닫고 나가면 화면에서는 몇 분 안에 사라진다.
AUTH.sweep()
PROBLEMS = problems.Problems(store)
# 댓글 실패 같은 조용한 사고를 [점검] 탭에 남긴다
social.PROBLEMS = PROBLEMS
from . import importer as _imp_mod
_imp_mod.PROBLEMS = PROBLEMS
from . import naver as _nv_mod
from . import identity as _identity
_nv_mod.PROBLEMS = PROBLEMS
jobs: dict[str, CrawlJob] = {}
_events: list[dict] = []
_lock = threading.Lock()

# Ctrl+C 를 눌렀다는 신호. 진행 상황 스트림이 이걸 보고 스스로 끝낸다.
# 이게 없으면 스트림이 영원히 안 끝나서 서버가 종료를 기다리다 멈춰 있는다.
_shutdown = threading.Event()

health.install(store._conn)          # 점검 기록 표를 준비한다
SCHED = Scheduler(__import__(__name__.rsplit('.',1)[0] + '.server',
                             fromlist=['server']))


def _record(kind: str, payload: dict):
    with _lock:
        _events.append({"kind": kind, **payload})
        if len(_events) > 600:
            del _events[:300]


def _record_inspection(kind: str, payload: dict):
    """Luna·태깅·AWS 후처리 로그를 수집 로그와 분리한다."""
    _record(kind, {**payload, "channel": "inspection"})


# ── 설정 ──────────────────────────────────────────────────────
def iter_config_files():
    """**수집할 사이트** 설정만 골라 낸다.

    ★ config/ 에는 두 종류가 산다.
        사이트 설정   musinsa.yaml · kream.yaml …   → 수집기 하나가 된다
        참고 자료     lexicon.yaml (어휘 사전)
                     category.yaml (카테고리 대조표)
                     brand_alias.yaml (아디다스 ↔ Adidas)
      뒤엣것은 '어디를 긁을지'가 아니라 '긁은 걸 어떻게 해석할지'다.

      그런데 *.yaml 을 다 집으니 사전까지 수집기 목록에 나타났다.
      '지그재그' 옆에 'lexicon' 이라는 정체불명 수집기가 서 있는 셈이다.

      이름으로 거르면 참고 자료가 하나 늘 때마다 또 깨진다.
      **사이트 설정에는 base_url 이 반드시 있다** — 그걸로 가른다.

    ★ 점으로 시작하는 파일도 거른다.
      Path.glob 은 셸과 달리 그것들도 잡는다. 예전에 저장 백업
      (.kream.bak.yaml)이 '.kream.bak' 이라는 유령 수집기로 나타났다.
    """
    for p in sorted(CONFIG_DIR.glob("*.yaml")):
        if p.name.startswith("."):
            continue
        try:
            head = p.read_text(encoding="utf-8")[:4000]
        except OSError:
            continue
        if not re.search(r"^base_url\s*:", head, re.M):
            continue
        # 과거 데이터는 DB에 보존하되 신규 수집기 목록에서는 내릴 수 있다.
        if re.search(r"^enabled\s*:\s*false\s*$", head, re.M | re.I):
            continue
        yield p


def list_configs() -> list[dict]:
    out = []
    for p in iter_config_files():
        try:
            cfg = SiteConfig.load(p)
            seeds = len(list(_safe_seeds(cfg)))
            render_plan = ((cfg.render or {}).get("pages")
                           or (cfg.render or {}).get("plan") or [])
            pinned = cfg.pinned_details or []
            has_list_parser = bool((cfg.list_page or {}).get("deep_items")
                                   or (cfg.list_page or {}).get("item_link")
                                   or (cfg.list_page or {}).get("card"))
            # 자동 수집형은 seeds를 일부러 비운다. 렌더링 계획이나 고정 상세가
            # 있으면 준비 완료이며, seeds는 수동 HTML 수집기에만 필요한 값이다.
            automatic_ready = bool(render_plan or pinned) and has_list_parser
            out.append({
                "code": cfg.code, "name": cfg.name, "file": p.name,
                "base_url": cfg.base_url,
                "listing_type": cfg.listing_type_default,
                "seed_count": seeds,
                "ready": automatic_ready or (seeds > 0 and has_list_parser),
                "automatic_ready": automatic_ready,
                "notes": cfg.notes,
            })
        except Exception as e:
            out.append({"code": p.stem, "name": p.stem, "file": p.name,
                        "error": str(e), "ready": False})
    out.extend(_social_sites())
    return out


# ── 소셜 두 곳 ────────────────────────────────────────────────
#  유튜브·네이버는 설정 yaml 이 없다. 공식 API 라서 셀렉터도 robots 도 필요
#  없고, 열쇠만 있으면 된다. 그래서 지금까지 수집 탭 카드에 안 나왔다.
#  하지만 **우리 지표의 절반이 이 둘에서 나온다.** 화면에 없으면 언제 돌았는지,
#  열쇠가 살아 있는지, 몇 건이 들어왔는지를 볼 데가 없다.
#  → 커머스 카드와 같은 모양으로 만들어 같은 자리에 세운다.
SOCIAL_SITES = {
    "youtube": {"name": "유튜브", "base_url": "https://www.youtube.com",
                "key_env": "YOUTUBE_API_KEY", "listing_type": "social"},
    "naver":   {"name": "네이버", "base_url": "https://naverapihub.apigw.ntruss.com",
                "key_env": "NAVER_CLIENT_ID", "listing_type": "social"},
}


def _social_sites() -> list[dict]:
    out = []
    for code, meta in SOCIAL_SITES.items():
        try:
            ready = bool(KEYS.get(meta["key_env"]))
        except Exception:      # noqa: BLE001 - 열쇠를 못 읽어도 카드는 보여야 한다
            ready = False
        out.append({
            "code": code, "name": meta["name"], "base_url": meta["base_url"],
            "listing_type": meta["listing_type"], "kind": "social",
            "seed_count": 0, "ready": ready, "automatic_ready": ready,
            "file": "(설정 파일 없음 · 공식 API)",
            "notes": "공식 API 로 받습니다. 열쇠만 있으면 되고 robots·셀렉터가 없습니다.",
        })
    return out


def _safe_seeds(cfg: SiteConfig):
    from .adapter import ConfigAdapter
    try:
        yield from ConfigAdapter(cfg).iter_seed_urls()
    except Exception:
        return


# ══════════════════════════════════════════════════════════════
#  문지기 — 로그인한 사람만 들여보낸다
# ══════════════════════════════════════════════════════════════
#  인터넷에 공개하는 순간 "우리만 아는 주소"는 울타리가 아니다.
#  자동으로 문을 두드리는 프로그램이 하루 종일 붙는다.
#
#  열어 두는 곳은 딱 셋이다.
#    · 로그인 화면과 로그인 요청
#    · 살아 있는지 확인하는 주소 (로드밸런서가 부른다)
#    · 북마클릿이 쓰는 /paste·/api/collect — 자기 토큰이 따로 있다
OPEN_PATHS = {"/login", "/api/auth/login", "/api/auth/state", "/healthz",
              "/paste", "/api/collect", "/favicon.ico"}

# 쿠키에 Secure 를 붙일지. HTTPS 뒤에 두면 반드시 켠다.
# 로컬에서 http 로 열어 볼 때만 끈다.
SECURE_COOKIE = (cfgset.get("FEEDIT_SECURE_COOKIE", "auto") != "off")


def _client_ip(req: Request) -> str:
    """앞단 프록시를 지나오면 진짜 주소가 헤더에 있다.

    ★ X-Forwarded-For 를 그냥 믿으면 안 된다 — 아무나 넣을 수 있다.
      우리가 세운 프록시 뒤에 있을 때만 의미가 있으므로,
      맨 앞 값(가장 바깥 클라이언트)만 쓰고 형식도 확인한다.
    """
    fwd = (req.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if fwd and len(fwd) <= 45 and re.match(r"^[0-9a-fA-F:.]+$", fwd):
        return fwd
    return (req.client.host if req.client else "") or "?"


@app.middleware("http")
async def _gate(req: Request, call_next):
    path = req.url.path
    if path in OPEN_PATHS or path.startswith("/static/"):
        return await call_next(req)

    who = AUTH.whoami(req.cookies.get(auth.COOKIE, ""))
    if not who:
        if path == "/" or req.headers.get("accept", "").startswith("text/html"):
            return RedirectResponse("/login", status_code=302)
        return JSONResponse({"error": "로그인이 필요합니다.", "need_login": True},
                            status_code=401)

    # ★ 다른 사이트가 우리 쿠키로 몰래 요청을 보내는 걸 막는다 (CSRF).
    #   브라우저는 다른 출처에서 온 요청에 임의 헤더를 못 붙인다 —
    #   붙이려면 사전 요청(preflight)이 필요한데 우리는 CORS 를 안 열어 뒀다.
    #   그래서 '값을 바꾸는 요청'에만 이 헤더를 요구한다.
    if req.method in ("POST", "PUT", "DELETE", "PATCH"):
        if req.headers.get("x-feedit") != "1":
            return JSONResponse(
                {"error": "요청이 올바르지 않습니다. 화면을 새로고침해 주세요."},
                status_code=403)

    req.state.user = who
    return await call_next(req)


def _who(req: Request) -> dict:
    return getattr(req.state, "user", None) or {"name": "?", "is_owner": False}


@app.get("/healthz")
def healthz():
    """살아 있는지만 알려 준다. 안에 무엇이 있는지는 말하지 않는다."""
    return {"ok": True}


# ── 로그인 ────────────────────────────────────────────────────
@app.get("/login", response_class=HTMLResponse)
def login_page():
    if UI_LOGIN.exists():
        return HTMLResponse(UI_LOGIN.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>ui/login.html 이 없습니다.</h1>", status_code=500)


@app.get("/api/auth/state")
def api_auth_state(req: Request):
    """로그인 화면이 부른다. 아직 아무도 없으면 그렇다고 알려 준다."""
    who = AUTH.whoami(req.cookies.get(auth.COOKIE, ""))
    return {"logged_in": bool(who), "name": (who or {}).get("name"),
            "any_user": AUTH.has_users()}


@app.post("/api/auth/login")
def api_auth_login(req: Request, body: dict = Body(...)):
    r = AUTH.login(str(body.get("code") or ""), ip=_client_ip(req),
                   agent=req.headers.get("user-agent", ""))
    if not r.get("ok"):
        return JSONResponse(r, status_code=401)
    resp = JSONResponse({"ok": True, "name": r["name"], "is_owner": r["is_owner"]})
    resp.set_cookie(auth.COOKIE, r["token"], httponly=True, samesite="lax",
                    secure=SECURE_COOKIE, max_age=auth.SESSION_HOURS * 3600,
                    path="/")
    return resp


@app.post("/api/auth/logout")
def api_auth_logout(req: Request):
    who = _who(req)
    AUTH.logout(req.cookies.get(auth.COOKIE, ""), who["name"], _client_ip(req))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


@app.get("/api/auth/me")
def api_auth_me(req: Request):
    return _who(req)


# ── 사람 관리 (관리자만) ──────────────────────────────────────
def _need_owner(req: Request):
    if not _who(req).get("is_owner"):
        raise HTTPException(403, "관리자만 할 수 있습니다.")


@app.get("/api/admin/users")
def api_users(req: Request):
    _need_owner(req)
    return {"users": AUTH.users(), "me": _who(req)["name"]}


@app.post("/api/admin/users")
def api_user_new(req: Request, body: dict = Body(...)):
    _need_owner(req)
    return AUTH.create_user(str(body.get("name") or ""),
                            owner=bool(body.get("owner")), by=_who(req)["name"])


@app.post("/api/admin/users/{uid}/reissue")
def api_user_reissue(req: Request, uid: int):
    _need_owner(req)
    return AUTH.reissue(uid, by=_who(req)["name"])


@app.post("/api/admin/users/{uid}/signout")
def api_user_signout(req: Request, uid: int):
    _need_owner(req)
    return AUTH.sign_out_all(uid, by=_who(req)["name"])


@app.post("/api/admin/users/{uid}/revoke")
def api_user_revoke(req: Request, uid: int):
    _need_owner(req)
    return AUTH.revoke(uid, by=_who(req)["name"])


@app.get("/api/admin/audit")
def api_audit(req: Request, limit: int = 80):
    _need_owner(req)
    return {"log": AUTH.recent_log(min(limit, 300))}


@app.get("/", response_class=HTMLResponse)
def index():
    if UI_FILE.exists():
        return HTMLResponse(UI_FILE.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>ui/index.html 이 없습니다.</h1>", status_code=500)


@app.get("/api/sites")
def api_sites():
    return {"sites": list_configs()}


@app.get("/api/config/{code}")
def api_config(code: str):
    p = _config_path(code)
    if not p.exists():
        raise HTTPException(404, "설정 파일이 없습니다.")
    return {"code": code, "yaml": p.read_text(encoding="utf-8")}


class ConfigBody(BaseModel):
    yaml: str


@app.put("/api/config/{code}")
def api_save_config(code: str, body: ConfigBody):
    """대시보드에서 고친 설정을 저장한다. 개발자 없이 셀렉터를 고칠 수 있게."""
    import re as _re
    import yaml as _y
    # 가장 흔한 실수를 먼저 잡아 준다 — YAML 은 콜론 뒤에 공백이 있어야
    # 뒤따르는 { } 를 값으로 읽는다. 없으면 엉뚱한 위치에서 에러가 나서
    # 처음 쓰는 사람은 원인을 못 찾는다.
    bad = _re.findall(r"^\s*([\w-]+):\{", body.yaml, _re.M)
    if bad:
        raise HTTPException(400,
            f"콜론 뒤에 공백이 빠졌습니다: {', '.join(bad[:3])}: {{ … }} "
            "→ 콜론과 { 사이에 한 칸 띄우세요.")
    try:
        _y.safe_load(body.yaml)          # 문법이 깨진 걸 저장하면 다음 실행이 죽는다
    except Exception as e:
        raise HTTPException(400, f"YAML 문법 오류: {e}")
    p = _config_path(code)
    if p.exists():                        # 덮어쓰기 전에 직전 버전을 남긴다
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        (BACKUP_DIR / f"{code}.bak.yaml").write_text(
            p.read_text(encoding="utf-8"), encoding="utf-8")
    p.write_text(body.yaml, encoding="utf-8")
    return {"ok": True}


# ── 사이트 추가 · 삭제 ────────────────────────────────────────
NEW_TEMPLATE = """\
# ═══════════════════════════════════════════════════════════════
#  {name} — 수집 설정
#  ---------------------------------------------------------------
#  ① robots.txt 를 먼저 확인하세요 — {base}/robots.txt
#  ② 목록 페이지를 브라우저에서 열고 저장(Ctrl+S) 한 뒤
#     [구조 탐색기] 에 올려 셀렉터 후보를 받으세요.
#  ③ 받은 셀렉터를 아래 빈칸에 채우고 저장하면 [수집] 탭에서 돌 수 있습니다.
# ═══════════════════════════════════════════════════════════════

code: {code}
name: {name}
base_url: {base}

# 가격의 성격. settled(체결가) / ask(호가) 중 하나.
# ★ 섞으면 리세일 지수가 통째로 망가집니다. 팔린 값이 아니면 ask 입니다.
listing_type_default: ask

pace:
  base_delay: 5.0          # 요청 사이 기본 간격(초). 모르면 그대로 두세요.
  jitter: 2.0
  max_delay: 300.0
  burst_pause_every: 40    # 40건마다
  burst_pause_sec: 60.0    #   60초 쉼
  max_rps: 0.25

# ── 시드 ── 수집을 시작할 '목록' 페이지
#  ※ 메인페이지는 넣지 마세요. 배너·큐레이션이라 매일 바뀌어 비교가 안 됩니다.
#    상품이 여러 개 나열되는 카테고리·브랜드·검색 결과 페이지를 넣으세요.
seeds: []
  # - "/category/outer"

list_page:
  item_link: ""            # 상세로 가는 <a> 셀렉터
  card: ""                 # 카드 하나를 감싸는 셀렉터
  card_fields: {{}}
    # brand: {{ css: "", cast: str }}
    # name:  {{ css: "", cast: str }}
    # price: {{ css: "", cast: int }}

detail_page:
  fields: {{}}

notes: |
  아직 채우는 중입니다.
"""


def _config_path(code: str) -> Path:
    """경로 조작을 막는다 — code 에 ../ 나 / 가 섞이면 딴 파일을 덮어쓸 수 있다."""
    import re as _re
    if not _re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", code or ""):
        raise HTTPException(400,
            "사이트 코드는 영문 소문자·숫자·- ·_ 만 쓸 수 있습니다 (예: musinsa).")
    return CONFIG_DIR / f"{code}.yaml"


class NewSiteBody(BaseModel):
    code: str
    name: str
    base_url: str


@app.post("/api/config")
def api_new_config(body: NewSiteBody):
    p = _config_path(body.code.strip().lower())
    if p.exists():
        raise HTTPException(409, f"'{p.stem}' 설정이 이미 있습니다.")
    base = body.base_url.strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise HTTPException(400, "주소는 https:// 로 시작해야 합니다.")
    p.write_text(
        NEW_TEMPLATE.format(code=p.stem, name=body.name.strip() or p.stem, base=base),
        encoding="utf-8")
    return {"ok": True, "code": p.stem}


@app.delete("/api/config/{code}")
def api_delete_config(code: str):
    """설정을 목록에서 없앤다.

    지우지 않고 .backup/ 으로 옮긴다 — 잘못 눌렀을 때 되돌릴 수 있어야 한다.
    모아 둔 데이터는 건드리지 않는다. 그건 [데이터] 탭에서 따로 지운다.
    """
    p = _config_path(code)
    if not p.exists():
        raise HTTPException(404, "설정 파일이 없습니다.")

    job = jobs.get(code)
    if job and job.state.phase in ("list", "detail", "prepare"):
        raise HTTPException(409, "지금 돌고 있습니다. 먼저 중단하세요.")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    from datetime import datetime as _dt
    dest = BACKUP_DIR / f"{code}.deleted-{_dt.now():%Y%m%d-%H%M%S}.yaml"
    p.rename(dest)
    jobs.pop(code, None)
    rows = store.stats()
    return {"ok": True, "moved_to": dest.name, "note": rows}


# ── 작업 제어 ─────────────────────────────────────────────────
class StartBody(BaseModel):
    code: str
    max_items: Optional[int] = None
    dry_run: bool = False
    list_only: bool = False


@app.post("/api/start")
def api_start(body: StartBody):
    p = _config_path(body.code)
    if not p.exists():
        raise HTTPException(404, "설정 파일이 없습니다.")
    cfg = SiteConfig.load(p)

    job = jobs.get(body.code)
    if job and job.state.phase in ("list", "detail", "prepare"):
        raise HTTPException(409, "이미 돌고 있습니다.")

    # ★ '시작' 은 자동 수집과 **같은 길**을 타야 한다.
    #   전에는 여기서 seeds 가 비면 거절했는데, 무신사·지그재그·에이블리는
    #   seeds 를 일부러 비우고 render.pages(브라우저로 목록 그리기)와
    #   pinned_details 로 돈다. 그래서 카드에는 '설정 완료' 라고 떠 있는데
    #   버튼만 "시드 URL 이 비어 있습니다" 로 튕겼다 — 화면과 버튼이 서로 딴말.
    #   판단을 두 군데 두면 반드시 이렇게 어긋난다. 스케줄러 것 하나만 쓴다.
    seeds = list(_safe_seeds(cfg))
    revisit = getattr(cfg, "revisit", None) or {}
    render = getattr(cfg, "render", None) or {}
    pinned = getattr(cfg, "pinned_details", None) or []
    if not (seeds or revisit.get("enabled") or render.get("enabled") or pinned):
        raise HTTPException(400,
            f"{cfg.name}: 돌 게 없습니다. 시드도 없고 재방문·렌더링도 꺼져 있으며 "
            "못 박은 상품도 없습니다. 설정 탭에서 seeds 를 채우거나 "
            "render.pages 를 켜 주세요.")

    plan = dict((SCHED.plans() or {}).get(body.code) or {})
    if body.max_items is not None:
        plan["max_items"] = body.max_items
    if body.list_only:
        plan["list_only"] = True

    # _render_step 은 브라우저를 띄워 몇 분씩 걸린다. 화면이 멈추면 안 되니
    # 스케줄러가 하던 그대로 딴 갈래에서 돌린다.
    threading.Thread(target=SCHED._run, args=(body.code, plan), daemon=True).start()
    return {"ok": True, "seeds": len(seeds),
            "render_pages": len((render.get("pages") or [])),
            "pinned": len(pinned)}


@app.post("/api/recrawl")
def api_recrawl(req: Request, body: dict = Body(default={})):
    """★ 재수집 — 주기가 안 돼도 **처음부터** 다시 훑는다.

    '시작' 과 무엇이 다른가
      시작은 이어서 하기 커서를 그대로 두고, 이미 받아 둔 주소는 건너뛴다
      (`seen_url`). 그래서 이미 다 받은 플랫폼에서는 몇 건 안 늘고 끝난다.
      재수집은 그 두 가지를 지우고 처음부터 본다. 파서를 고친 뒤 예전 것을
      제대로 다시 받아야 할 때 쓴다.
    ★ 상품은 지우지 않는다. 같은 uid 로 덮어써지므로(COALESCE) 값이 제자리에서
      고쳐질 뿐이다.
    """
    code = str(body.get("code") or "").strip()
    if not code or not _config_path(code).exists():
        raise HTTPException(404, "그런 설정이 없습니다.")
    job = jobs.get(code)
    # ★ 일시정지도 '돌고 있는 중' 으로 본다. 화면은 그때 재수집을 잠그는데
    #   여기서만 통과시키면 화면과 서버가 또 딴말을 하게 된다.
    if job and job.state.phase in ("list", "detail", "prepare", "paused"):
        raise HTTPException(409, "이미 돌고 있습니다. 먼저 중단하고 다시 눌러 주세요."
                            if job.state.phase == "paused" else "이미 돌고 있습니다.")
    cfg = SiteConfig.load(_config_path(code))

    with store.tx() as c:
        seen = c.execute("DELETE FROM seen_url WHERE source_code=?", (code,)).rowcount
        cur = c.execute("DELETE FROM checkpoint WHERE job_key LIKE ?", (f"{code}:%",)).rowcount
    _record("info", {"t": datetime.now().strftime("%H:%M:%S"),
                     "msg": f"[재수집] {cfg.name} — 받은 기록 {seen}건과 이어서 하기 "
                            f"{cur}건을 지우고 처음부터 훑습니다"})
    AUTH.log("재수집", f"{cfg.name} (seen {seen} · cursor {cur})",
             _who(req)["name"], _client_ip(req))

    plan = dict((SCHED.plans() or {}).get(code) or {})
    threading.Thread(target=SCHED._run, args=(code, plan), daemon=True).start()
    return {"ok": True, "cleared_seen": seen, "cleared_cursor": cur}


@app.post("/api/testrun")
def api_testrun(req: Request, body: dict = Body(default={})):
    """★ 맛보기 수집 — 플랫폼마다 몇 건만 담고 끝낸다.

    화면을 고친 뒤 '진행바가 제대로 차는지' 보고 싶은데, 정식 수집은 한 회차에
    100건씩 30분이 걸린다. 방금 다 긁어 온 다음이면 더더욱 다시 돌리기 곤란하다.
    그래서 상세 상한만 3건으로 줄여 같은 길을 그대로 태운다.
    ★ 새 길을 만들지 않았다 — 진짜 수집과 같은 CrawlJob 을 쓰므로, 여기서 잘
      돌면 정식 수집도 잘 도는 것이다.
    """
    from urllib.parse import urlsplit
    n = max(1, min(int(body.get("count") or 3), 10))
    want = [c for c in (body.get("codes") or []) if c]

    # ★ 설정 파일을 직접 훑지 않는다. iter_config_files() 가 고른 것만 쓴다.
    #   전에 config/*.yaml 을 그대로 돌렸다가, 내려 둔 후르츠패밀리
    #   (enabled: false)까지 시작했다. 화면에 카드도 없는 곳을 긁은 셈이다.
    #   '수집할 곳'의 판단은 한 곳에만 있어야 한다.
    plan: dict[str, list] = {}
    for path in iter_config_files():
        try:
            cfg = SiteConfig.load(path)
        except Exception:      # noqa: BLE001 - 설정 하나가 깨져도 나머지는 돈다
            continue
        code = getattr(cfg, "code", "")
        if not code or (want and code not in want):
            continue
        # 같은 사이트끼리는 한 줄로 세운다 (무신사 / 무신사 유즈드).
        plan.setdefault(urlsplit(cfg.base_url).netloc, []).append(cfg)

    started, skipped = [], []
    for host, cfgs in plan.items():
        busy = [c.name for c in cfgs
                if (jobs.get(c.code) and
                    jobs[c.code].state.phase in ("list", "detail", "prepare"))]
        if busy:
            skipped.append(f"{', '.join(busy)}: 이미 돌고 있습니다")
            continue
        threading.Thread(target=_testrun_host, args=(cfgs, n), daemon=True).start()
        started.extend(c.name for c in cfgs)

    # ★ 유튜브·네이버도 맛보기에 넣는다.
    #   설정 yaml 이 없어 iter_config_files() 에 안 잡히는데, 그렇다고 빼 두면
    #   "5곳 시작" 이라고 뜨면서 정작 지표의 절반을 차지하는 둘이 빠진다.
    for code, meta in SOCIAL_SITES.items():
        if want and code not in want:
            continue
        if not KEYS.get(meta["key_env"]):
            skipped.append(f"{meta['name']}: 열쇠가 없습니다")
            continue
        threading.Thread(target=_testrun_social, args=(code, meta["name"], n),
                         daemon=True).start()
        started.append(meta["name"])

    _record("info", {"t": datetime.now().strftime("%H:%M:%S"),
                     "msg": f"[맛보기] 플랫폼별 {n}건만 담습니다 — "
                            f"{', '.join(started) or '없음'}"})
    AUTH.log("맛보기 수집", f"{n}건 × {len(started)}곳",
             _who(req)["name"], _client_ip(req))
    return {"ok": bool(started), "count": n, "started": started, "skipped": skipped}



def _testrun_social(code: str, name: str, n: int):
    """유튜브·네이버 맛보기 — 대상 몇 개만, 적은 양으로.

    정식 회차는 대상 12개에 유튜브 검색만 1,200 units 를 쓴다. 화면 확인용으로
    그걸 다 쓸 이유가 없어서 **대상 n 개, 건수도 n 배수**로 줄인다.
    (유튜브 하루 할당량이 10,000 units 뿐이다.)
    """
    try:
        terms = (_target_terms() or [])[:max(1, n)]
        if not terms:
            raise RuntimeError("발표 대상 목록이 비어 있습니다")
        if code == "naver":
            from . import naver as NV
            NV.collect_trend(store, terms, days=30, on_event=_record)
            NV.collect_text(store, terms, per_term=n, on_event=_record)
        else:
            social.collect_youtube(store, terms, mode="keywords", days=30,
                                   per_kw=n, comments_per_video=n * 2,
                                   on_event=_record)
        _record("info", {"t": datetime.now().strftime("%H:%M:%S"),
                         "msg": f"[맛보기] {name} — 대상 {len(terms)}개로 끝"})
    except Exception as exc:   # noqa: BLE001 - 한 곳이 실패해도 나머지는 돈다
        _record("error", {"t": datetime.now().strftime("%H:%M:%S"),
                          "msg": f"[맛보기] {name} 실패 — {exc}"})

def _testrun_host(cfgs: list, n: int):
    """같은 사이트의 수집기들을 **차례로** 돌린다.

    무신사와 무신사 유즈드는 같은 musinsa.com 이다. 동시에 두 갈래로
    두들기지 않기로 했는데, 그렇다고 뒤엣것을 건너뛰면 맛보기로 확인이 안 된다
    (실제로 유즈드가 매번 '같은 사이트의 다른 수집이 도는 중' 으로 빠졌다).
    그래서 건너뛰지 말고 앞엣것이 끝나기를 기다렸다가 잇는다.
    """
    for cfg in cfgs:
        job = CrawlJob(cfg, store, on_event=_record, max_items=n)
        jobs[cfg.code] = job
        job.start()
        t = job._thread
        if t:
            t.join(timeout=600)


@app.post("/api/pause/{code}")
def api_pause(code: str):
    j = jobs.get(code)
    if not j:
        raise HTTPException(404, "그런 작업이 없습니다.")
    j.pause()
    return {"ok": True}


@app.post("/api/resume/{code}")
def api_resume(code: str):
    j = jobs.get(code)
    if not j:
        raise HTTPException(404, "그런 작업이 없습니다.")
    j.resume()
    return {"ok": True}


@app.post("/api/stop/{code}")
def api_stop(code: str):
    j = jobs.get(code)
    if not j:
        raise HTTPException(404, "그런 작업이 없습니다.")
    j.stop()
    return {"ok": True}


@app.get("/api/status")
def api_status():
    # 자동 실행 상태도 함께 보낸다 — 수집 탭에서 바로 보여야 하기 때문이다.
    return {
        "jobs": {k: v.snapshot() for k, v in jobs.items()},
        "store": store.stats(),
        "runs": store.recent_runs(10),
        "last": store.last_seen_by_source(),   # 사이트별 '언제 들어왔나'
        "schedule": SCHED.snapshot(),
        # ★ 렌더 단계에는 CrawlJob 이 아직 없다. 그래서 jobs 만 보면
        #   무신사가 15칸을 그리는 몇 분 동안 카드가 '대기'로 보였고
        #   버튼도 다시 눌리는 상태가 됐다. 이 구간을 따로 알린다.
        "rendering": dict(getattr(SCHED, "rendering", {}) or {}),
        # 수집 탭의 큰 진행바가 '지금 몇 단계인지'를 여기서 읽는다.
        # 카드마다 두던 진행바는 total 이 작아 0→100 으로 튀었다.
        "pipeline": {**_PIPELINE, "active": _PIPELINE_ACTIVE.is_set(),
                     # 스타일 태깅은 한 장에 몇 초라 500장이면 몇 분이다.
                     # 그동안 소식이 없으면 멈춘 줄 안다.
                     "style_progress": dict(getattr(STYLE_TAGGER, "progress", {}) or {}),
                     "aws_progress": dict(_AWS_PROGRESS)},
    }


@app.get("/api/stream")
async def api_stream(request: Request):
    """진행 상황을 흘려보낸다 (SSE). 새로고침 없이 화면이 살아 움직이게.

    ★ 끝낼 구멍을 세 개 둔다. 하나라도 없으면 Ctrl+C 가 안 먹는다 —
      uvicorn 은 종료할 때 '열린 응답이 끝나기'를 기다리는데,
      이 함수가 while True 로 돌면 그 응답이 영원히 안 끝난다.
        ① Ctrl+C  → _shutdown
        ② 탭을 닫음 → is_disconnected
        ③ 그래도 안 끝나면 → 1시간 뒤 스스로 종료 (브라우저가 다시 붙는다)
    """
    async def gen():
        last = 0
        started = asyncio.get_event_loop().time()
        while not _shutdown.is_set():
            if await request.is_disconnected():
                break
            if asyncio.get_event_loop().time() - started > 3600:
                break
            with _lock:
                n = len(_events)
                new = _events[last:n]
                last = n
            for e in new:
                yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
            snap = {"kind": "__status__", **api_status()}
            yield f"data: {json.dumps(snap, ensure_ascii=False, default=str)}\n\n"
            try:
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
    return StreamingResponse(gen(), media_type="text/event-stream")


# ── 구조 탐색기 ───────────────────────────────────────────────
@app.post("/api/probe/upload")
async def api_probe_upload(file: UploadFile = File(...)):
    """브라우저에서 저장한 HTML 을 올려 셀렉터 후보를 받는다.

    URL 을 넣어 가져오는 방식이 아니라 '이미 받아 둔 파일'을 쓰는 게 기본이다.
    자바스크립트로 그리는 페이지는 서버가 준 HTML 에 내용이 없어서,
    브라우저가 다 그린 뒤 저장한 파일이라야 제대로 보인다.
    """
    raw = await file.read()
    try:
        html = raw.decode("utf-8")
    except UnicodeDecodeError:
        html = raw.decode("cp949", errors="replace")
    return probe(html, url=file.filename or "")


# ── 저장된 데이터 보기 · 관리 ─────────────────────────────────
@app.get("/api/data/products")
def api_data_products(source: str = "all", q: str = "", issue: str = "all",
                      sort: str = "recent", limit: int = 50, offset: int = 0):
    return store.browse_products(source_code=source, q=q.strip(), issue=issue,
                                 sort=sort, limit=min(limit, 200), offset=max(offset, 0))


_NORM = None


def _normalizer():
    """어휘·카테고리 정규화기. 설정 파일을 매번 읽지 않게 한 번만 만든다."""
    global _NORM
    if _NORM is None:
        from .normalize import Normalizer
        _NORM = Normalizer(str(CONFIG_DIR / "lexicon.yaml"), str(CONFIG_DIR / "category.yaml"))
    return _NORM


@app.post("/api/lexicon/reload")
def api_lexicon_reload():
    """사전을 고친 뒤 서버를 안 끄고 다시 읽는다."""
    global _NORM
    _NORM = None
    n = _normalizer()
    return {"ok": True, "surfaces": len(n.lex.surfaces), "terms": len(n.lex.facet_of)}


@app.get("/api/data/product/{code}/{uid:path}")
def api_data_product(code: str, uid: str):
    """상품 하나에 대해 **우리가 아는 전부**를 돌려준다.

    예전에는 상품 표의 몇 칸만 보냈다. 그래서 "뭘 긁어온 건지 알 수가 없다"는
    말이 나왔다. 지금은 네 갈래를 다 붙인다.
      · 상품 표 (이름·브랜드·모델번호·발매가·실측…)
      · 지표 추이 (순위·후기·관심·거래, 날짜별)
      · 가격 (호가·체결·정가)
      · **원본 파싱 결과** — 파서가 뽑았지만 표에 칸이 없어 안 들어간 것까지
      · 어휘 태깅과 카테고리 판정 근거
    """
    d = store.product_detail(code, uid)
    if not d:
        raise HTTPException(404, "그런 상품이 없습니다.")

    p = d.get("product") or {}

    # ── 원본에서 파싱 결과를 꺼낸다 ──
    #  표에 칸이 없어 안 들어간 값도 여기엔 남아 있다.
    #  (후기 수가 몇 주 동안 버려졌던 게 바로 이 경우였다.)
    raw_fields, tags = {}, []
    for r in (d.get("raws") or []):
        try:
            payload = json.loads(r.get("payload") or "{}")
        except (TypeError, ValueError):
            continue
        parsed = payload.get("parsed", payload)
        if not isinstance(parsed, dict):
            continue
        for k, v in parsed.items():
            if v in (None, "", [], {}):
                continue
            if k in ("trades", "html_len"):
                continue
            raw_fields.setdefault(k, v)
        for t in (parsed.get("tags") or []):
            if t not in tags:
                tags.append(t)

    # ── 어휘 태깅 · 카테고리 판정 ──
    n = _normalizer()
    norm = n.run(p, tags=tags)

    d["raw_fields"] = raw_fields
    d["site_tags"] = tags
    d["normalized"] = {
        "tags": norm["tags"],
        "unknown": norm["unknown"],
        "category": norm["category"],
        "category_path": norm["category_path"],
        "match": norm["match"],
    }
    # 같은 열쇠로 묶인 다른 사이트의 상품 — '같은 상품'이 이어졌는지 보여 준다
    d["siblings"] = _siblings(norm["match"]["key"], code, uid)
    return d


def _siblings(key: str, code: str, uid: str) -> list[dict]:
    """이 상품과 같은 열쇠를 가진 다른 상품들.

    다 뒤지면 느리므로, 열쇠가 자기 자신뿐인 경우(s:)는 건너뛴다.
    """
    if not key or key.startswith("s:"):
        return []
    n = _normalizer()
    with store._lock:
        rows = [dict(r) for r in store._conn.execute(
            "SELECT source_code, source_uid, name, brand_name, model_code, source_url "
            "FROM staging_product WHERE source_code <> ? OR source_uid <> ?",
            (code, uid))]
    out = []
    for r in rows:
        if n.product_key(r)["key"] == key:
            out.append(r)
            if len(out) >= 12:
                break
    return out


@app.get("/api/data/summary")
def api_data_summary(source: str = "all"):
    return store.data_summary(source)


class KeysBody(BaseModel):
    keys: list[list[str]]          # [[source_code, source_uid], ...]


@app.post("/api/data/delete")
def api_data_delete(body: KeysBody):
    keys = [(k[0], k[1]) for k in body.keys if len(k) >= 2]
    if not keys:
        raise HTTPException(400, "지울 대상이 없습니다.")
    return {"ok": True, "deleted": store.delete_products(keys, forget_url=True)}


@app.post("/api/data/recrawl")
def api_data_recrawl(body: KeysBody):
    """데이터는 두고 '본 적 없음'으로 되돌린다 → 다음 실행 때 다시 받아 덮어쓴다."""
    keys = [(k[0], k[1]) for k in body.keys if len(k) >= 2]
    if not keys:
        raise HTTPException(400, "대상이 없습니다.")
    return {"ok": True, "forgot": store.forget_urls(keys)}


@app.get("/api/data/csv")
def api_data_csv(source: str = "all", q: str = "", issue: str = "all"):
    """지금 보고 있는 목록을 CSV 로. 엑셀로 열어 눈으로 훑을 때 쓴다."""
    import csv, io
    d = store.browse_products(source_code=source, q=q.strip(), issue=issue,
                              sort="recent", limit=20000, offset=0)
    cols = ["source_code", "source_uid", "brand_name", "name", "model_code",
            "ask_price", "settled_n", "settled_min", "settled_avg", "settled_max",
            "retail_price", "source_url", "last_seen_at"]
    buf = io.StringIO()
    buf.write("﻿")                       # 엑셀이 한글을 깨뜨리지 않게 BOM
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in d["rows"]:
        w.writerow(r)
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="feedit_{source}.csv"'})


# ── API 열쇠 ─────────────────────────────────────────────────
KEYS = keystore.KeyStore(DATA_DIR / "keys.json")
ENTITY_LINKER = EntityLinker(CONFIG_DIR / "lexicon_master.json")
store.text_entity_linker = ENTITY_LINKER
METRIC_LEXICON = Lexicon(CONFIG_DIR / "lexicon.yaml")


def _rebuild_shadow_metrics():
    return MetricAggregator(store, SHADOW_VERSION, lexicon=METRIC_LEXICON,
                            weights=SHADOW_SOURCE_WEIGHTS).rebuild()


def _rebuild_and_continue_pipeline():
    """Luna 500건 배치가 끝날 때마다 지표→태깅→RDS 적재를 실행한다."""
    metrics = _rebuild_shadow_metrics()
    with _PIPELINE_LOCK:
        code = _PIPELINE.get("source")
        step = int(_PIPELINE.get("step") or 0)
    source = code if code and step == 6 else "luna_batch"
    threading.Thread(target=_finish_after_luna, args=(source,), daemon=True,
                     name="feedit-post-luna").start()
    return metrics


def _target_terms() -> list[str]:
    from .target_scope import terms
    return terms()


_PIPELINE_LOCK = threading.RLock()
# ★ '지금 진짜 돌고 있나' 는 **문자열이 아니라 이 깃발로** 판단한다.
#
#   전에는 저장된 phase 가 'running' 인지를 봤다. 그런데 후처리는 6단계
#   (Luna 대기) 에서 **멈춰 서서 기다린다** — 사람이 Luna 를 돌려야 다음이
#   간다. 그때도 phase 는 'running' 으로 남는다. 아무도 안 도는데 '도는 중'
#   으로 보인 것이다. 그 바람에
#     · 화면의 [멈춘 자리에서 이어서] 버튼이 영영 잠겼고
#     · /api/pipeline/resume 도 409 로 막았다.
#   즉 **멈췄을 때 쓰라고 만든 버튼이 멈췄을 때만 안 눌렸다.**
#   깃발은 실제로 함수가 도는 동안에만 서 있으므로 이런 일이 안 생긴다.
_PIPELINE_ACTIVE = threading.Event()

_PIPELINE = {"phase": "idle", "source": None, "step": 0, "steps": 8,
             "started_at": None, "updated_at": None, "message": "대기",
             "details": {}, "error": None}
_PIPELINE_STEPS = ["수집 완료", "중복 제거", "소셜 관련성 검사", "사전 연결",
                   "자막·ASR·OCR 보완", "Luna 분석 대기열", "스타일 태깅", "AWS 적재"]
_AWS_PROGRESS = {"running": False, "stage": None, "done": 0, "total": 0,
                 "pct": 0, "message": "", "started_at": None}

# ★ 파이프라인 상태를 파일에 남긴다.
#   주기가 6~12시간인데 서버를 다시 켜면 게이지가 0으로 돌아가 '대기' 로만
#   보였다. 그러면 Luna 대기열에 몇 건이 밀려 있는지, 마지막으로 언제 돌았는지
#   알 길이 없다. 다음 회차까지 반나절을 깜깜하게 기다리게 된다.
_PIPELINE_PATH = DATA_DIR / "pipeline.json"


def _pipeline_load():
    try:
        raw = json.loads(_PIPELINE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(raw, dict):
        with _PIPELINE_LOCK:
            _PIPELINE.update({k: v for k, v in raw.items() if k in _PIPELINE})
            # 켜는 순간 '돌고 있음' 으로 남아 있으면 거짓말이 된다.
            # 실제로 도는 스레드는 재시작과 함께 사라졌다.
            if _PIPELINE.get("phase") == "running":
                _PIPELINE["phase"] = "interrupted"
                _PIPELINE["message"] = (_PIPELINE.get("message") or "") + \
                    " (서버가 다시 켜져 중간에 끊겼습니다)"


def _pipeline_save():
    try:
        _PIPELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PIPELINE_PATH.write_text(
            json.dumps(_PIPELINE, ensure_ascii=False, default=str, indent=2),
            encoding="utf-8")
    except OSError:
        pass       # 기록에 실패했다고 수집을 멈출 이유는 없다


def _pipeline_update(source: str, step: int, message: str, **details):
    now = time.time()
    with _PIPELINE_LOCK:
        if step == 1 or not _PIPELINE.get("started_at"):
            _PIPELINE.update({"started_at": now, "details": {}, "error": None})
        _PIPELINE.update({"phase": "running" if step < len(_PIPELINE_STEPS) else "done",
                          "source": source, "step": step, "steps": len(_PIPELINE_STEPS),
                          "updated_at": now, "message": message})
        _PIPELINE["details"].update(details)
    # 매 단계마다 남긴다. 서버가 꺼져도 어디까지 갔는지 남아 있어야 한다.
    _pipeline_save()


@app.get("/api/automation/status")
def api_automation_status():
    with _PIPELINE_LOCK:
        out = dict(_PIPELINE)
    elapsed = max(0, time.time() - (out.get("started_at") or time.time()))
    done = max(0, int(out.get("step") or 0))
    remaining = (elapsed / done * max(0, out["steps"] - done)) if done else None

    # ★ "언제 돌았고 언제 또 도나" — 주기가 6~12시간이라 이게 없으면
    #   화면만 봐서는 멈춘 건지 기다리는 건지 알 수가 없다.
    since_min = next_min = None
    if out.get("updated_at"):
        since_min = round((time.time() - out["updated_at"]) / 60)
    try:
        plans = (SCHED.snapshot() or {}).get("plans") or {}
        dues = [p["due_in_min"] for p in plans.values()
                if isinstance(p, dict) and p.get("due_in_min") is not None
                and p.get("auto") is not False]
        if dues:
            next_min = max(0, min(dues))
    except Exception:          # noqa: BLE001 - 시각을 못 읽어도 나머지는 보여야 한다
        pass

    return {"ok": True, **out, "step_names": _PIPELINE_STEPS,
            "elapsed_seconds": round(elapsed),
            "eta_seconds": round(remaining) if remaining is not None else None,
            "since_min": since_min, "next_min": next_min,
            "luna": _luna_state(), "totals": _pipeline_totals()}


def _pipeline_totals() -> dict:
    """지금까지 **누적으로** 몇 건이 됐나.

    파이프라인 막대는 Luna 대기열에서 멈춰 서 있는 일이 많아, 7·8단계가
    돌았는지를 막대만 봐서는 알 수 없다. 그래서 DB 에서 직접 센다 —
    회차가 끝났든 말든 '지금 몇 건이 태깅됐고 몇 건이 올라갔나' 가 보인다.
    """
    out = {}
    try:
        with store._lock:
            row = store._conn.execute(
                "SELECT count(*) FROM staging_product "
                "WHERE image_url IS NOT NULL AND trim(image_url)<>''").fetchone()
            out["taggable"] = int(row[0] or 0)
            row = store._conn.execute(
                "SELECT count(*) FROM staging_product "
                "WHERE site_tags LIKE '%\"facet\": \"style\"%' "
                "   OR site_tags LIKE '%\"facet\":\"style\"%'").fetchone()
            out["styled"] = int(row[0] or 0)
            row = store._conn.execute("SELECT count(*) FROM staging_product").fetchone()
            out["products"] = int(row[0] or 0)
    except Exception as e:      # noqa: BLE001 - 세다 실패해도 나머지는 보여야 한다
        out["error"] = str(e)
    with _PIPELINE_LOCK:
        det = dict(_PIPELINE.get("details") or {})
    out["last_style"] = (det.get("style") or {}).get("tagged")
    aws = det.get("aws") or {}
    out["last_aws_products"] = aws.get("products")
    out["last_aws_snapshots"] = aws.get("snapshots")
    return out


# ── Luna 자동 분석 ────────────────────────────────────────────
#  왜 있는가
#    수집은 6~12시간마다 도는데 Luna 분석은 사람이 눌러야 돌았다. 그래서
#    대기열에 수백 건이 밀린 채 다음 회차가 와 버렸다. 화면에는 '대기' 로만
#    보여서 밀린 줄도 몰랐다.
#  규칙
#    다음 수집 **1시간 전**까지 Luna 가 한 번도 안 돌았고 대기열이 남아 있으면
#    100건씩 자동으로 돌린다. 다음 회차가 오기 전에 밀린 것을 털어 낸다.
#    ★ 사람이 이미 돌리고 있으면 건드리지 않는다 (LLMBatch 가 스스로 막는다).
LUNA_AUTO_LEAD_MIN = 60      # 다음 수집 몇 분 전부터 자동으로 돌릴까
LUNA_AUTO_BATCH = 500        # 500건 분석 완료마다 태깅 후 RDS에 증분 적재
_LUNA_QUEUE_CACHE = {"at": 0.0, "count": 0}


def _luna_queue_pending(refresh: bool = False) -> int:
    """Luna가 실제로 선택할 수 있는 대기열 수.

    llm_stats.remaining은 단순히 '아직 분석 안 한 원문'이라 관련성 규칙에서
    제외되는 글까지 셌다. 버튼은 llm_candidates를 써서 두 숫자가 달랐다.
    화면과 실행기가 반드시 같은 후보 함수를 보게 한다.
    """
    now = time.time()
    if refresh or now - _LUNA_QUEUE_CACHE["at"] > 5:
        _LUNA_QUEUE_CACHE["count"] = len(store.llm_candidates(
            MODEL, PROMPT_VERSION, 50000, "all"))
        _LUNA_QUEUE_CACHE["at"] = now
    return int(_LUNA_QUEUE_CACHE["count"])


def _luna_state() -> dict:
    """대기열이 몇 건이고 지금 돌고 있는지."""
    try:
        from .llm_batch import MODEL, PROMPT_VERSION
        st = store.llm_stats(MODEL, PROMPT_VERSION) or {}
        snap = LLM_BATCH.snapshot() or {}
        return {"pending": _luna_queue_pending(),
                "unfiltered_remaining": int(st.get("remaining") or 0),
                "running": bool(snap.get("running")),
                "auto_batch": LUNA_AUTO_BATCH,
                "auto_lead_min": LUNA_AUTO_LEAD_MIN}
    except Exception as e:      # noqa: BLE001
        return {"pending": None, "running": False, "error": str(e)}


def luna_autorun_if_due(next_min) -> dict:
    """다음 수집이 코앞인데 대기열이 남아 있으면 500건 돌린다."""
    if next_min is None or next_min > LUNA_AUTO_LEAD_MIN:
        return {"ok": False, "why": "아직 다음 수집까지 여유가 있습니다"}
    s = _luna_state()
    if s.get("running"):
        return {"ok": False, "why": "이미 분석 중입니다"}
    if not s.get("pending"):
        return {"ok": False, "why": "대기열이 비어 있습니다"}
    # 자동 파이프라인은 발표 타깃만이 아니라 상품 리뷰를 포함한 실제 공통 큐를
    # 처리한다. 발표 타깃은 UI에서 필요할 때 별도로 좁혀 볼 수 있다.
    r = LLM_BATCH.start(limit=LUNA_AUTO_BATCH, source="all", target_keys=None)
    if r.get("ok"):
        _record_inspection("info", {"t": datetime.now().strftime("%H:%M:%S"),
                         "msg": f"[Luna] 다음 수집 {next_min}분 전 — 밀린 "
                                f"{s['pending']}건 중 {LUNA_AUTO_BATCH}건을 자동 분석합니다"})
    return r


@app.post("/api/automation/luna-autorun")
def api_luna_autorun():
    """화면에서도 같은 규칙으로 돌려 볼 수 있게."""
    plans = (SCHED.snapshot() or {}).get("plans") or {}
    dues = [p["due_in_min"] for p in plans.values()
            if isinstance(p, dict) and p.get("due_in_min") is not None]
    return luna_autorun_if_due(min(dues) if dues else None)


def run_automatic_social(code: str) -> dict:
    """스케줄러 전용 소셜 원루트. UI 수동 버튼과 다른 범위를 만들지 않는다."""
    terms = _target_terms()
    if code == "naver":
        from . import naver as NV
        trend = NV.collect_trend(store, terms, days=90, on_event=_record)
        texts = NV.collect_text(store, terms, per_term=30, on_event=_record)
        return {"ok": True, "trend": trend, "text": texts, "terms": len(terms)}
    if code == "youtube":
        got = social.collect_youtube(
            store, terms, mode="both", days=90, per_kw=15,
            comments_per_video=60, on_event=_record)
        return {"ok": True, **got, "terms": len(terms)}
    return {"ok": False, "error": f"지원하지 않는 자동 소셜 소스: {code}"}


def after_automatic_collection(code: str) -> None:
    """수집 뒤 공통 후처리. 실패는 다음 수집을 막지 않고 점검 화면에 남긴다."""
    _PIPELINE_ACTIVE.set()
    try:
        _after_automatic_collection(code)
    finally:
        _PIPELINE_ACTIVE.clear()


def _after_automatic_collection(code: str) -> None:
    try:
        _pipeline_update(code, 1, "원본 수집이 끝났습니다.")
        dedupe = store.dedupe_social_texts()
        _pipeline_update(code, 2, f"중복 {dedupe['removed']}건 제거", dedupe=dedupe)
        from . import quality
        audited = quality.audit(store, apply=True)
        quarantined = (audited["videos"]["quarantined"] +
                       sum(v["quarantined"] for v in audited["texts"].values()))
        _pipeline_update(code, 3, f"관련성 미달 {quarantined}건 격리",
                         quarantined=quarantined)
        linked = ENTITY_BACKFILL.start(
            limit=50000, source=code if code in ("naver", "youtube") else "all")
        _pipeline_update(code, 4, "신규 글은 저장 즉시 사전 연결 완료",
                         entity_backfill=linked)
        if code == "youtube":
            asr = ASR_WORKER.start(limit=3, model_name="small")
            _pipeline_update(code, 5, "공개 자막 실패분을 ASR 대기열로 전달",
                             asr=asr, ocr="ASR 무음 판정 시 자동 전달")
        else:
            _pipeline_update(code, 5, "영상 보완 단계 해당 없음")
        pending = _luna_queue_pending(refresh=True)
        _pipeline_update(code, 6, f"Luna 수동 분석 대기 {pending}건", luna_pending=pending)
    except Exception as exc:
        SCHED.last_error[code] = f"수집 후 분석 실패: {exc}"
        with _PIPELINE_LOCK:
            _PIPELINE.update({"phase": "error", "error": str(exc),
                              "message": f"자동화 중단: {exc}", "updated_at": time.time()})
        _record_inspection("error", {"t": datetime.now().strftime("%H:%M:%S"),
                          "msg": f"[후처리] {code} — {exc}"})
        return
    # Luna 대기 자료가 있으면 여기서 멈춘다. 이전 코드는 6단계를 기록한 직후
    # 7·8단계를 실행해 분석 중에도 AWS 적재 실패가 반복됐다.
    luna_phase = (LLM_BATCH.snapshot() or {}).get("phase")
    if pending or luna_phase == "running":
        if luna_phase == "running":
            _pipeline_update(code, 6, "Luna 분석 실행 중 — 완료 뒤 다음 단계 진행",
                             luna_pending=pending, luna_phase=luna_phase)
        else:
            # ★ 여기서 **멈춰 선다**. 사람이 Luna 를 돌려야 다음이 간다.
            #   전에는 이때도 phase 가 'running' 이라 '도는 중' 으로 보였고,
            #   그래서 화면의 [이어서] 버튼이 잠겨 손을 쓸 수가 없었다.
            with _PIPELINE_LOCK:
                _PIPELINE.update({
                    "phase": "waiting", "updated_at": time.time(),
                    "message": f"Luna 분석 대기 {pending:,}건 — 분석이 끝나야 "
                               f"스타일 태깅·AWS 적재로 넘어갑니다"})
            _pipeline_save()
        return
    _finish_after_luna(code)


def _finish_after_luna(code: str) -> None:
    """Luna 완료 뒤에만 스타일 태깅과 AWS 적재를 순서대로 실행한다."""
    _PIPELINE_ACTIVE.set()
    try:
        _finish_after_luna_inner(code)
    finally:
        _PIPELINE_ACTIVE.clear()


def _finish_after_luna_inner(code: str) -> None:
    try:
        tagged = STYLE_TAGGER.run(limit=500)
        if tagged.get("skipped"):
            _record_inspection("warn", {"t": datetime.now().strftime("%H:%M:%S"),
                              "msg": "[스타일 태깅] 팀 모델 어댑터 미연결 — 상품은 태깅 대기로 유지"})
            _pipeline_update(code, 7, "스타일 모델 연결 대기", style=tagged)
            return
        else:
            _record_inspection("info", {"t": datetime.now().strftime("%H:%M:%S"),
                              "msg": f"[스타일 태깅] {tagged.get('tagged',0)}건 완료"})
            _pipeline_update(code, 7, f"스타일 {tagged.get('tagged',0)}건 태깅", style=tagged)
    except Exception as exc:
        SCHED.last_error[code] = f"스타일 태깅 실패: {exc}"
        with _PIPELINE_LOCK:
            _PIPELINE.update({"phase": "error", "error": str(exc),
                              "message": f"스타일 태깅에서 중단: {exc}",
                              "updated_at": time.time()})
        return
    _sync_aws_only(code)


def _sync_aws_only(code: str) -> None:
    """이미 끝난 태깅은 되풀이하지 않고 AWS 단계만 재시도한다."""
    # ★ 돌기 전에 비밀번호부터 본다.
    #   없으면 psql 이 '접속 할 수 없음' 이라고 뱉는데, 그건 네트워크가
    #   끊긴 것처럼 읽혀서 보안 그룹·터널을 헤매게 만든다. 실제로는
    #   비밀번호를 안 준 것뿐이다.
    ready, why = RDS_SYNC.password_ready()
    if not ready:
        _record_inspection("warn", {"t": datetime.now().strftime("%H:%M:%S"),
                         "msg": f"[AWS] 적재를 건너뜁니다 — {why.splitlines()[0]}"})
        with _PIPELINE_LOCK:
            _PIPELINE.update({"phase": "waiting", "updated_at": time.time(),
                              "message": why, "error": None})
        _pipeline_save()
        return
    try:
        _AWS_PROGRESS.update({"running": True, "stage": "connect", "done": 0,
                              "total": 0, "pct": 0, "message": "RDS 구조 확인 중",
                              "started_at": time.time()})
        last_logged = -10

        def _aws_progress(p):
            nonlocal last_logged
            _AWS_PROGRESS.update({"running": True, **p})
            pct = int(float(p.get("pct") or 0))
            if pct >= last_logged + 10 or p.get("stage") == "done":
                last_logged = pct
                _record_inspection("info", {
                    "t": datetime.now().strftime("%H:%M:%S"),
                    "msg": f"[AWS] {p.get('message') or p.get('stage')} · {pct}%"})

        synced = RDS_SYNC.sync(on_progress=_aws_progress)
        if not synced.get("ok"):
            raise RuntimeError(synced.get("error") or "RDS 적재 실패")
        _record_inspection("info", {"t": datetime.now().strftime("%H:%M:%S"),
                          "msg": f"[AWS] 상품 {synced.get('products',0)} · 가격 {synced.get('snapshots',0)} 증분 적재"})
        _pipeline_update(code, 8, "자동화 완료", aws=synced)
        _AWS_PROGRESS.update({"running": False, "stage": "done", "pct": 100,
                              "message": "AWS 적재 완료"})
    except Exception as exc:
        _AWS_PROGRESS.update({"running": False, "stage": "error",
                              "message": str(exc)[:240]})
        SCHED.last_error[code] = f"AWS 자동 적재 실패: {exc}"
        with _PIPELINE_LOCK:
            _PIPELINE.update({"phase": "error", "error": str(exc),
                              "message": f"AWS 적재에서 중단: {exc}", "updated_at": time.time()})
        # psql 원문은 사람이 읽기 어렵다. rdscheck 가 원인을 갈라 준다.
        try:
            from . import rdscheck
            d = rdscheck.diagnose({"ok": False, "error": str(exc),
                                   "config": RDS_SYNC.db.config().public()})
            human = f"{d.get('title') or '적재 실패'} — {(d.get('todo') or '').splitlines()[0]}"
        except Exception:      # noqa: BLE001
            human = str(exc)[:200]
        _record_inspection("error", {"t": datetime.now().strftime("%H:%M:%S"),
                           "msg": f"[AWS] {code} 자동 적재 실패 — {human}"})
        with _PIPELINE_LOCK:
            _PIPELINE["message"] = f"AWS 적재에서 중단: {human}"


def _resume_aws_only(code: str) -> None:
    _PIPELINE_ACTIVE.set()
    try:
        _sync_aws_only(code)
    finally:
        _PIPELINE_ACTIVE.clear()


@app.get("/api/aws/codemap")
def api_aws_codemap(limit: int = 40):
    """우리 값이 팀 코드표에 얼마나 붙는지, 안 붙는 건 무엇인지.

    ★ 왜 화면에 두는가
      코드가 안 붙은 값은 조용히 NULL 로 들어간다. 숫자로 안 보면 아무도
      모른 채 지나간다. 여기 뜨는 목록이 곧 **팀이 사전에 채워야 할 일감**이다.
    """
    from .codemap import CodeMap
    cm = CodeMap()                       # 셈이 섞이지 않게 새로 만든다
    with store._lock:
        rows = [dict(r) for r in store._conn.execute(
            "SELECT name, brand_name, category_path FROM staging_product")]
    brand = Counter(); cat = Counter()
    for r in rows:
        m = cm.map_product(r)
        brand[m["brand_match"]] += 1
        cat[m["category_match"]] += 1
    n = max(len(rows), 1)
    return {
        "ok": True, "products": len(rows),
        "brand": {k: {"n": v, "pct": round(v * 100 / n, 1)} for k, v in brand.items()},
        "category": {k: {"n": v, "pct": round(v * 100 / n, 1)} for k, v in cat.items()},
        "unmatched": cm.unmatched(limit),
        "dict": {"terms": len(cm.terms), "brands": len(cm.brands),
                 "categories": len(cm.categories)},
    }


@app.post("/api/pipeline/resume")
def api_pipeline_resume(body: dict = Body(default={})):
    """막힌 자동화를 사람이 이어서 돌린다.

    ★ 왜 필요한가
      후처리는 8단계를 한 줄로 잇는다. 가운데 한 단계가 오류로 죽으면
      (실제로 스타일 태깅이 sklearn 문제로 매번 죽었다) 그 뒤 단계는 다음
      수집이 올 때까지 영영 안 돈다. 6~12시간을 기다려야 했고, 그 회차도
      같은 자리에서 또 죽으면 끝이 없었다.

      고친 다음에 사람이 한 번 눌러 이어 붙일 수 있어야 한다.

    what:
      "auto"  — 멈춘 자리에서 이어서 (기본)
      "after_luna" — 스타일 태깅 + AWS 적재만
      "all"   — 1단계부터 다시
    """
    what = str(body.get("what") or "auto")
    code = str(body.get("source") or _PIPELINE.get("source") or "musinsa")
    if _PIPELINE_ACTIVE.is_set() and not body.get("force"):
        raise HTTPException(409, "지금 자동화가 돌고 있습니다. 끝난 뒤에 눌러 주세요.")

    step = int(_PIPELINE.get("step") or 0)
    if what == "auto":
        # 7단계까지 성공했다면 적재만 재시도한다. 실패할 때마다 모델을 다시
        # 올리고 태깅을 반복하던 원인이 이 분기 하나가 없었기 때문이다.
        what = "aws_only" if step >= 7 else ("after_luna" if step >= 6 else "all")

    if what == "aws_only":
        fn = _resume_aws_only
    elif what == "after_luna":
        fn = _finish_after_luna
    else:
        fn = after_automatic_collection
    with _PIPELINE_LOCK:
        _PIPELINE.update({"phase": "running", "error": None,
                          "message": f"수동 진행 — " +
                          ("AWS 적재만" if what == "aws_only" else
                           "스타일 태깅부터" if what == "after_luna" else "처음부터"),
                          "updated_at": time.time()})
    _record_inspection("info", {"t": datetime.now().strftime("%H:%M:%S"),
                     "msg": f"[후처리] {code} — 사람이 이어서 진행 ({what})"})
    threading.Thread(target=fn, args=(code,), daemon=True).start()
    return {"ok": True, "source": code, "what": what, "from_step": step}


LLM_BATCH = LLMBatch(store, lambda: KEYS.get("OPENAI_API_KEY"), ENTITY_LINKER,
                     _rebuild_and_continue_pipeline)
ENTITY_BACKFILL = EntityBackfill(store, ENTITY_LINKER, _rebuild_shadow_metrics)
social.install(store)
ASR_WORKER = ASRWorker(store, ROOT)
OCR_WORKER = OCRWorker(store, ROOT)
from .style_tagging import StyleTagger
from .rds_sync import RDSSync
STYLE_TAGGER = StyleTagger(store)
RDS_SYNC = RDSSync(ROOT, store)


@app.get("/api/keys")
def api_keys():
    """플랫폼마다 뭐가 들어 있는지.

    ★ 값 원문은 절대 안 보낸다 — 앞 네 글자만 보낸다.
      화면 캡처 한 장으로 열쇠가 새는 일을 막는다.
    """
    return {"platforms": KEYS.state()}


@app.post("/api/keys")
def api_keys_save(req: Request, body: dict = Body(...)):
    """화면에서 넣은 값을 저장한다. 재시작 없이 바로 먹는다."""
    who = _who(req)["name"]
    saved, errs, notes = [], [], []
    for env, val in (body.get("values") or {}).items():
        if env not in keystore.BY_ENV:
            continue
        # 화면이 '안 바꿈'을 뜻할 때 보내는 값. 실수로 지우지 않게.
        if val == "__KEEP__":
            continue
        r = KEYS.put(env, str(val), by=who)
        if r.get("ok"):
            saved.append(env)
            if r.get("note"):
                notes.append(r["note"])
        else:
            # 서버가 받은 길이를 붙여 준다 — '내 메모장은 39자인데'와
            # 대조할 수 있어야 어디서 잘렸는지 안다.
            got = r.get("got_len")
            errs.append(f"{r.get('error')}"
                        + (f" (서버가 받은 길이: {got}자)" if got is not None else ""))
    if saved:
        # ★ 값은 기록에 남기지 않는다. 어느 항목을 바꿨는지만 남긴다.
        AUTH.log("열쇠 변경", ", ".join(saved), who, _client_ip(req))
    return {"ok": not errs, "saved": saved, "errors": errs,
            "notes": notes, "platforms": KEYS.state()}


@app.post("/api/keys/test/{platform_id}")
def api_keys_test(req: Request, platform_id: str):
    """진짜로 되는지 한 번 불러 본다."""
    r = keystore.test(platform_id, KEYS)
    AUTH.log("연결 시험", f"{platform_id} — {'성공' if r.get('ok') else r.get('error','')}",
             _who(req)["name"], _client_ip(req), ok=bool(r.get("ok")))
    return r


@app.post("/api/llm/analyze")
def api_llm_analyze(req: Request, body: dict = Body(...)):
    """임의 문장 또는 저장된 text_document 한 건을 Luna로 분석한다."""
    text_id = body.get("text_document_id")
    row = store.text_for_analysis(int(text_id)) if text_id not in (None, "") else None
    if text_id not in (None, "") and not row:
        raise HTTPException(404, "그 텍스트를 찾지 못했습니다.")
    text = str((row or {}).get("body") or body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "분석할 문장을 넣어 주세요.")
    if len(text) > 12000:
        raise HTTPException(400, "한 번에 12,000자까지만 분석할 수 있습니다.")
    key = KEYS.get("OPENAI_API_KEY")
    if not key:
        raise HTTPException(400, "API 탭에서 OpenAI 키를 먼저 저장해 주세요.")
    try:
        candidates = ENTITY_LINKER.candidates(row or {"body": text})
        result = OpenAITextAnalyzer(key).analyze(text, candidates)
    except AnalysisError as e:
        raise HTTPException(502, str(e)) from e
    if row:
        store.put_llm_analysis(row["id"], result)
        result, mentions = ENTITY_LINKER.resolve(result, candidates)
        store.put_entity_resolution(row["id"], result, mentions)
    AUTH.log("LLM 텍스트 분석", f"text_document={row['id'] if row else '미리보기'}",
             _who(req)["name"], _client_ip(req))
    return {"ok": True, "saved": bool(row), "analysis": result,
            "candidates": candidates[:12]}


@app.get("/api/llm/batch")
def api_llm_batch_state(limit: int = 20, source: str = "all", preview: bool = False):
    if preview:
        targets = _demo_targets() if source == "demo" else []
        result = LLM_BATCH.preview(limit=limit, source=source,
                                   target_keys=[t["term_key"] for t in targets])
        if targets:
            result["demo_status"] = store.demo_sentiment_status(
                [t["raw"] for t in targets], MODEL, PROMPT_VERSION)
        return result
    return {"ok": True, **LLM_BATCH.snapshot()}


@app.get("/api/llm/results")
def api_llm_results(limit: int = 50, source: str = "all"):
    return {"ok": True, "rows": store.recent_llm_results(
        MODEL, PROMPT_VERSION, limit, source)}


@app.get("/api/metrics/results")
def api_metric_results(kind: str = "trend", limit: int = 50, q: str = ""):
    return {"ok": True, "kind": kind,
            "rows": store.metric_results(SHADOW_VERSION, kind, limit, q)}


@app.post("/api/test/trend-chat")
def api_trend_chat(req: Request, body: dict = Body(default={})):
    try:
        result = trend_chat.answer(store, METRIC_LEXICON,
                                   str(body.get("question") or ""), SHADOW_VERSION)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    AUTH.log("트렌드 챗 테스트", result["question"][:120],
             _who(req)["name"], _client_ip(req))
    return {"ok": True, **result}


@app.get("/api/test/demo-targets")
def api_demo_targets(limit: int = 10):
    return {"ok": True, **trend_chat.demo_targets(store, SHADOW_VERSION, limit)}


@app.post("/api/llm/batch")
def api_llm_batch_start(req: Request, body: dict = Body(default={})):
    limit = max(1, min(int(body.get("limit") or 500), 500))
    source = str(body.get("source") or "all")
    targets = _demo_targets() if source == "demo" else []
    r = LLM_BATCH.start(limit=limit, source=source,
                        target_keys=[t["term_key"] for t in targets])
    AUTH.log("LLM 배치 시작", f"{source} · 최대 {limit}건",
             _who(req)["name"], _client_ip(req), ok=bool(r.get("ok")))
    return r


def _demo_targets() -> list[dict]:
    """Locked presentation targets, kept out of arbitrary request bodies."""
    try:
        data = json.loads((CONFIG_DIR / "demo_targets.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    return [{"term_key": f"{t['facet']}:{t['canonical']}", "raw": t}
            for t in data.get("targets", []) if t.get("facet") and t.get("canonical")]


@app.get("/api/llm/demo-sentiment")
def api_demo_sentiment_status():
    targets = _demo_targets()
    return {"ok": True, **store.demo_sentiment_status(
        [t["raw"] for t in targets], MODEL, PROMPT_VERSION)}


@app.post("/api/llm/batch/stop")
def api_llm_batch_stop(req: Request):
    r = LLM_BATCH.stop()
    AUTH.log("LLM 배치 중지", "현재 호출 뒤 중지", _who(req)["name"], _client_ip(req))
    return r


@app.get("/api/entity/backfill")
def api_entity_backfill_state():
    return {"ok": True, **ENTITY_BACKFILL.snapshot()}


@app.post("/api/entity/backfill")
def api_entity_backfill_start(req: Request, body: dict = Body(default={})):
    limit = max(1, min(int(body.get("limit") or 5000), 50000))
    source = str(body.get("source") or "all")
    r = ENTITY_BACKFILL.start(limit=limit, source=source)
    AUTH.log("사전 엔티티 백필", f"{source} · 최대 {limit}건",
             _who(req)["name"], _client_ip(req), ok=bool(r.get("ok")))
    return r


@app.post("/api/entity/backfill/stop")
def api_entity_backfill_stop(req: Request):
    r = ENTITY_BACKFILL.stop()
    AUTH.log("사전 엔티티 백필 중지", "현재 문서 뒤 중지",
             _who(req)["name"], _client_ip(req))
    return r


# ── 네이버 ────────────────────────────────────────────────────
@app.get("/api/social/naver")
def api_naver_state():
    """지금까지 받은 트렌드·글 요약. 검색어는 어휘사전에서 온다."""
    from . import naver as NV
    try:
        terms = NV.terms_from_lexicon(str(CONFIG_DIR / "lexicon.yaml"), store=store)
    except Exception:
        terms = []
    got = NV.summary(store)
    return {**got, "term_count": len(terms), "sample": terms[:12],
            # 어림하지 말고 실제로 나눠 본다 — 앵커가 목록에 있냐 없냐로 하나 틀린다
            "trend_calls": len(NV._batches(terms)),
            "text_calls": len(terms) * 2}


@app.post("/api/social/naver")
def api_naver_run(req: Request, body: dict = Body(default={})):
    """네이버에서 트렌드·글을 모은다. 지금은 사람이 눌러야 돈다."""
    from . import naver as NV
    what = str(body.get("what") or "both")     # trend | text | both
    # ★ 발표 대상만 — config/demo_targets.json 의 11개로 좁힌다.
    #   사전 전체는 2,400개가 넘어 묶음이 600회를 넘는다. 과거치를 받을 때는
    #   대상만 좁혀야 몇 분 안에 끝난다.
    #   (데이터랩은 한 번 부를 때 기간 전체를 주므로, 1년치나 30일치나 호출 수는 같다.)
    if body.get("targets_only"):
        try:
            import json as _json
            d = _json.loads((CONFIG_DIR / "demo_targets.json").read_text(encoding="utf-8"))
            terms = [t["canonical"] for t in d.get("targets", [])]
        except Exception as e:
            return {"ok": False, "error": f"발표 대상 목록을 못 읽었습니다: {e}"}
    else:
        try:
            terms = NV.terms_from_lexicon(str(CONFIG_DIR / "lexicon.yaml"),
                                          limit=int(body.get("limit") or 0), store=store)
        except Exception as e:
            return {"ok": False, "error": f"어휘사전을 못 읽었습니다: {e}"}
    if not terms:
        return {"ok": False, "error": "어휘사전에 트렌드로 볼 말이 없습니다."}

    out = {"ok": True, "terms": len(terms), "what": what}
    try:
        if what in ("trend", "both"):
            out["trend"] = NV.collect_trend(
                store, terms, days=int(body.get("days") or 30), on_event=_record)
        if what in ("text", "both"):
            out["text"] = NV.collect_text(
                store, terms, per_term=int(body.get("per_term") or 30),
                on_event=_record)
    except social.NotConfigured as e:
        return {"ok": False, "error": str(e), "need_key": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    AUTH.log("네이버 수집",
             f"{what} · 어휘 {len(terms)}개", _who(req)["name"], _client_ip(req))
    return out


# ── 유튜브 채널 ───────────────────────────────────────────────
@app.get("/api/social/channels")
def api_yt_channels():
    return {"channels": social.channels(store)}


@app.post("/api/social/channels/search")
def api_yt_channel_search(body: dict = Body(...)):
    """이름으로 채널을 찾는다. 고른 것만 담으므로 여기선 저장하지 않는다."""
    q = str(body.get("q") or "").strip()
    if not q:
        return {"ok": False, "error": "채널 이름을 넣어 주세요."}
    try:
        yt = social.YouTube()
        if not yt.ready:
            return {"ok": False, "error": "YOUTUBE_API_KEY 가 없습니다.",
                    "need_key": True}
        found = yt.search_channels(q, limit=int(body.get("limit") or 10))
    except Exception as e:
        return {"ok": False, "error": str(e)}
    have = {c["channel_id"] for c in social.channels(store)}
    for c in found:
        c["already"] = c["channel_id"] in have
    return {"ok": True, "channels": found, "quota": yt.used}


@app.post("/api/social/channels/add")
def api_yt_channel_add(req: Request, body: dict = Body(...)):
    """고른 채널을 담거나(ids), 붙여 넣은 주소를 한꺼번에 등록한다(text)."""
    ids = [str(i) for i in (body.get("ids") or []) if str(i).strip()]
    text = str(body.get("text") or "").strip()
    try:
        if ids:
            yt = social.YouTube()
            if not yt.ready:
                return {"ok": False, "error": "YOUTUBE_API_KEY 가 없습니다.",
                        "need_key": True}
            got = yt.channels(ids=ids)
            n = social.save_channels(store, got)
            AUTH.log("유튜브 채널 추가", f"{n}개", user=_who(req)["name"])
            return {"ok": True, "saved": n, "channels": got,
                    "failed": [], "quota": yt.used}
        if text:
            r = social.add_channels_from_text(store, text)
            AUTH.log("유튜브 채널 추가", f"{r.get('saved', 0)}개 (붙여넣기)",
                     user=_who(req)["name"])
            return r
        return {"ok": False, "error": "담을 채널이 없습니다."}
    except social.NotConfigured as e:
        return {"ok": False, "error": str(e), "need_key": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── 모은 영상·댓글 들여다보기 ─────────────────────────────────
@app.get("/api/social/videos")
def api_yt_videos(channel: str = "all", q: str = "", sort: str = "recent",
                  limit: int = 40, offset: int = 0):
    """모은 영상 목록. '뭘 가져왔는지'를 눈으로 보려고 만든 것."""
    social.install(store)
    where, args = ["1=1"], []
    if channel and channel != "all":
        where.append("v.channel_id = ?")
        args.append(channel)
    if q.strip():
        where.append("(v.title LIKE ? OR v.channel_title LIKE ?)")
        args += [f"%{q.strip()}%"] * 2
    w = " AND ".join(where)
    order = {"recent": "v.published_at DESC",
             "views": "st.view_count DESC",
             "comments": "got DESC"}.get(sort, "v.published_at DESC")
    sql = f"""
      SELECT v.*, st.view_count, st.like_count, st.comment_count,
             (SELECT count(*) FROM text_document t
               WHERE t.source_code='youtube'
                 AND t.doc_kind IN ('yt_comment','yt_comment_reply')
                 AND t.product_uid = 'yt:' || v.video_id) AS got
      FROM yt_video v
      LEFT JOIN (SELECT s.* FROM yt_video_stat s
                 JOIN (SELECT video_id, max(stat_date) d FROM yt_video_stat
                       GROUP BY video_id) m
                   ON s.video_id=m.video_id AND s.stat_date=m.d) st
        ON st.video_id = v.video_id
      WHERE {w} ORDER BY {order} LIMIT ? OFFSET ?"""
    with store._lock:
        total = store._conn.execute(
            f"SELECT count(*) FROM yt_video v WHERE {w}", args).fetchone()[0]
        rows = [dict(r) for r in store._conn.execute(
            sql, args + [min(limit, 200), max(offset, 0)])]
    return {"total": total, "rows": rows, "limit": limit, "offset": offset,
            "channels": [{"channel_id": c["channel_id"], "title": c["title"]}
                         for c in social.channels(store)]}


@app.get("/api/social/youtube/insights")
def api_yt_insights(limit: int = 50, facet: str = "all", gender: str = "all"):
    social.install(store)
    if facet not in ("all", "style", "item", "material", "brand"):
        facet = "all"
    if gender not in ("all", "남성", "여성", "공용", "미분류"):
        gender = "all"
    return {"ok": True, **youtube_insights.build(
        store, METRIC_LEXICON, limit=limit, facet_filter=facet, gender=gender)}


@app.get("/api/social/youtube/transcripts")
def api_yt_transcripts():
    return {"ok": True, **social.transcript_summary(store)}


@app.get("/api/social/youtube/asr-queue")
def api_yt_asr_queue(limit: int = 100):
    return {"ok": True, **ASR_WORKER.snapshot()}


@app.post("/api/social/youtube/asr-queue/run")
def api_yt_asr_run(req: Request, body: dict = Body(default={})):
    result = ASR_WORKER.start(limit=int(body.get("limit") or 1),
                              model_name=str(body.get("model") or "small"))
    AUTH.log("유튜브 ASR 시작", f"{result.get('model','')} · {result.get('selected',0)}건",
             _who(req)["name"], _client_ip(req), ok=bool(result.get("ok")))
    return result


@app.post("/api/social/youtube/asr-queue/stop")
def api_yt_asr_stop(req: Request):
    result = ASR_WORKER.stop()
    AUTH.log("유튜브 ASR 중지", "현재 영상 뒤 중지", _who(req)["name"], _client_ip(req))
    return result


@app.post("/api/social/youtube/asr-queue/retry-failed")
def api_yt_asr_retry_failed(req: Request, body: dict = Body(default={})):
    result = ASR_WORKER.retry_failed(limit=int(body.get("limit") or 3))
    AUTH.log("유튜브 ASR 실패 재대기", f"{result['reset']}건",
             _who(req)["name"], _client_ip(req))
    return result


@app.get("/api/social/youtube/ocr-queue")
def api_yt_ocr_queue():
    return {"ok": True, **OCR_WORKER.snapshot()}


@app.post("/api/social/youtube/ocr-queue/run")
def api_yt_ocr_run(req: Request, body: dict = Body(default={})):
    result = OCR_WORKER.start(limit=int(body.get("limit") or 1),
                              interval=float(body.get("interval") or 2),
                              max_frames=int(body.get("max_frames") or 120),
                              min_confidence=float(body.get("min_confidence") or .55))
    AUTH.log("유튜브 화면 OCR 시작", f"{result.get('selected', 0)}건",
             _who(req)["name"], _client_ip(req), ok=bool(result.get("ok")))
    return result


@app.post("/api/social/youtube/ocr-queue/stop")
def api_yt_ocr_stop(req: Request):
    result = OCR_WORKER.stop()
    AUTH.log("유튜브 화면 OCR 중지", "현재 영상 뒤 중지",
             _who(req)["name"], _client_ip(req))
    return result


@app.post("/api/social/youtube/ocr-queue/retry-failed")
def api_yt_ocr_retry(req: Request, body: dict = Body(default={})):
    result = OCR_WORKER.retry_failed(limit=int(body.get("limit") or 3))
    AUTH.log("유튜브 화면 OCR 실패 재대기", f"{result['reset']}건",
             _who(req)["name"], _client_ip(req))
    return result


@app.post("/api/social/youtube/transcripts/auto")
def api_yt_transcript_auto(req: Request, body: dict = Body(default={})):
    """기존 영상의 미수집 공개 자막을 비공식 어댑터로 제한 수량 재시도한다."""
    result = social.fetch_missing_transcripts(
        store, limit=int(body.get("limit") or 20), force=bool(body.get("force")),
        on_event=_record)
    AUTH.log("유튜브 공개 자막 자동 수집",
             f"시도 {result['attempted']} · 저장 {result['counts'].get('saved', 0)}",
             _who(req)["name"])
    return {"ok": True, **result}


@app.post("/api/social/youtube/transcripts/{video_id}")
def api_yt_transcript_save(req: Request, video_id: str, body: dict = Body(...)):
    try:
        result = social.save_transcript(
            store, video_id, str(body.get("text") or ""),
            origin=str(body.get("origin") or "caption"),
            lang=str(body.get("lang") or "ko")[:12])
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    AUTH.log("유튜브 영상 내용 저장", f"{video_id} · {result['origin']} · "
             f"{result['characters']}자", _who(req)["name"])
    return {"ok": True, **result}


@app.get("/api/social/comments/{video_id}")
def api_yt_comments(video_id: str, limit: int = 200):
    """한 영상의 댓글과 그 판정. 왜 남겼는지가 같이 보여야 믿을 수 있다."""
    from .commentfilter import judge
    from .intent import LABELS, classify
    with store._lock:
        v = store._conn.execute(
            "SELECT * FROM yt_video WHERE video_id=?", (video_id,)).fetchone()
        transcript = store._conn.execute(
            "SELECT origin,lang,full_text,segments,created_at FROM yt_transcript "
            "WHERE video_id=?", (video_id,)).fetchone()
        corrections = [dict(r) for r in store._conn.execute(
            "SELECT start,original,canonical,facet,confidence,status "
            "FROM yt_transcript_correction WHERE video_id=? "
            "ORDER BY start,confidence DESC LIMIT 100", (video_id,))]
        rows = [dict(r) for r in store._conn.execute(
            """SELECT doc_kind,body,like_count,reply_count,published_at,collected_at,parent_id
               FROM text_document
               WHERE source_code='youtube'
                 AND doc_kind IN ('yt_comment','yt_comment_reply')
                 AND product_uid=? ORDER BY like_count DESC LIMIT ?""",
            (f"yt:{video_id}", min(limit, 500)))]
    lex = social._lexicon()
    out, counts = [], {}
    for r in rows:
        j = judge(r["body"], lexicon=lex)
        c = classify(r["body"])
        for lb in c["labels"]:
            counts[lb] = counts.get(lb, 0) + 1
        out.append({**r, "why": j.get("why", []),
                    "intent": c["labels"], "score": c["score"]})
    scored = [x["score"] for x in out if x["score"] is not None]
    return {"video": dict(v) if v else None,
            "transcript": dict(transcript) if transcript else None,
            "corrections": corrections, "comments": out,
            "counts": counts,
            "labels": {k: v2["name"] for k, v2 in LABELS.items()},
            "avg": round(sum(scored) / len(scored), 3) if scored else None}


@app.post("/api/social/youtube/replies/backfill")
def api_yt_replies_backfill(req: Request, body: dict = Body(default={})):
    try:
        result = social.backfill_youtube_replies(
            store, limit=int(body.get("limit") or 10),
            comments_per_video=int(body.get("comments") or 100),
            video_ids=body.get("video_ids") or None, on_event=_record)
    except social.NotConfigured as exc:
        return {"ok": False, "error": str(exc), "need_key": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    AUTH.log("유튜브 답글 백필", f"시도 {result['attempted']} · 저장 {result['replies_saved']}",
             _who(req)["name"], _client_ip(req), ok=result["failed"] == 0)
    return {"ok": True, **result}


@app.post("/api/social/channels/import")
async def api_yt_channel_import(req: Request, file: UploadFile = File(...)):
    """팀이 정리해 둔 목록 파일(.json)을 그대로 담는다. API 를 안 부른다."""
    raw = await file.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"JSON 을 읽지 못했습니다: {e}"}
    r = social.import_channel_file(store, data)
    if r.get("ok"):
        AUTH.log("유튜브 채널 파일 가져오기",
                 f"{r['saved']}개 · {file.filename}", _who(req)["name"])
    return r


@app.post("/api/social/channels/refresh")
def api_yt_channel_refresh(req: Request, body: dict = Body(default={})):
    """구독자 수·업로드 목록을 받아 온다. 50개에 1칸."""
    try:
        r = social.refresh_channels(store, only_missing=not body.get("all"))
    except social.NotConfigured as e:
        return {"ok": False, "error": str(e), "need_key": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    AUTH.log("유튜브 채널 정보 새로고침",
             f"{r.get('updated', 0)}개 · {r.get('quota', 0)}칸", _who(req)["name"])
    return r


@app.post("/api/social/channels/{channel_id}")
def api_yt_channel_set(req: Request, channel_id: str, body: dict = Body(...)):
    ok = social.set_channel(store, channel_id,
                            enabled=body.get("enabled"),
                            note=body.get("note"),
                            gender=body.get("gender"),
                            remove=bool(body.get("remove")))
    if ok:
        what = ("뺌" if body.get("remove") else
                f"채널군 {body.get('gender')}" if body.get("gender") is not None else
                ("켬" if body.get("enabled") else "끔"))
        AUTH.log("유튜브 채널 " + what, channel_id, user=_who(req)["name"])
    return {"ok": ok}


@app.post("/api/social/youtube")
def api_youtube(body: dict = Body(...)):
    """선정 채널 업데이트가 기본이며 검색은 명시한 보조 조사에서만 쓴다."""
    kws = [k.strip() for k in (body.get("keywords") or []) if str(k).strip()]
    mode = str(body.get("mode") or "channels")
    if mode not in ("channels", "keywords", "both"):
        mode = "both"
    on = [c for c in social.channels(store, only_on=True)]
    if mode == "keywords" and not kws:
        return {"ok": False, "error": "검색어를 하나 이상 넣어 주세요."}
    if mode == "channels" and not on:
        return {"ok": False,
                "error": "켜 둔 채널이 없습니다. 위에서 채널을 담고 켜 주세요."}
    if mode == "both" and not kws and not on:
        return {"ok": False, "error": "채널을 담거나 검색어를 넣어 주세요."}
    try:
        got = social.collect_youtube(
            store, kws[:20], mode=mode,
            days=int(body.get("days") or 30),
            per_kw=int(body.get("per_kw") or 15),
            comments_per_video=int(body.get("comments") or 60),
            on_event=_record)
    except social.NotConfigured as e:
        return {"ok": False, "error": str(e), "need_key": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, **got}


@app.get("/api/social/intent")
def api_intent(source: str = "youtube", limit: int = 4000):
    """모아 둔 텍스트로 구매의향 지수를 낸다."""
    with store._lock:
        rows = [r[0] for r in store._conn.execute(
            "SELECT body FROM text_document WHERE source_code=? LIMIT ?",
            (source, limit))]
    return {"source": source, **intent.aggregate(rows),
            "labels": {k: v["name"] for k, v in intent.LABELS.items()}}


@app.get("/api/fx")
def api_fx(days: int = 14):
    """최근 환율. 달러 발매가를 원화로 바꾼 근거를 볼 수 있게."""
    with store._lock:
        rows = [dict(r) for r in store._conn.execute(
            "SELECT * FROM fx_rate ORDER BY rate_date DESC LIMIT ?", (days,))]
    return {"rates": rows}


@app.post("/api/fx/set")
def api_fx_set(body: dict = Body(...)):
    """환율을 손으로 넣는다 — 사내망 등에서 환율 API 가 안 될 때."""
    try:
        store.fx._put(str(body["date"])[:10], body.get("base", "USD"),
                      body.get("quote", "KRW"), float(body["rate"]), "수동 입력")
    except (KeyError, TypeError, ValueError) as e:
        return {"ok": False, "error": f"날짜와 환율을 확인해 주세요: {e}"}
    return {"ok": True}


# ── 플랫폼 스키마 만들기 · 내보내기 ───────────────────────────
_EXPORTER = None


def _exporter():
    global _EXPORTER
    if _EXPORTER is None:
        from .export_pg import Exporter
        _EXPORTER = Exporter(store, ROOT)
    return _EXPORTER


# ── 표 안 들여다보기 ──────────────────────────────────────────
_BROWSER = None


def _browser():
    global _BROWSER
    if _BROWSER is None:
        from .browse import Browser
        _BROWSER = Browser(store.path)
    return _BROWSER


@app.get("/api/db/tables")
def api_db_tables(src: str = "crawler"):
    """표 목록. src=crawler 는 지금 쌓인 것, src=export 는 내보낼 것."""
    if src == "aws":
        from .platformdb import PlatformDB
        got = PlatformDB(ROOT).tables()
        if not got.get("ok"):
            raise HTTPException(400, got.get("error") or "AWS RDS를 읽지 못했습니다.")
        return {**got, "src": src}
    if src == "export":
        from . import exportcheck
        got = exportcheck.scan(_exporter().out)
        rows = [{"name": t["table"], "ko": "", "rows": t["rows"],
                 "cols": len(t.get("cols") or [])} for t in got["tables"]]
        rows += [{"name": n, "ko": "", "rows": 0, "cols": 0} for n in got["empty"]]
        return {"tables": rows, "src": src}
    return {"tables": _browser().tables(),
            "groups": _browser().groups(), "src": src}


@app.get("/api/db/rows")
def api_db_rows(table: str, src: str = "crawler", q: str = "", sort: str = "",
                desc: bool = True, limit: int = 50, offset: int = 0):
    if src == "aws":
        from .platformdb import PlatformDB
        got = PlatformDB(ROOT).rows(table, limit=limit, offset=offset)
        if not got.get("ok"):
            raise HTTPException(400, got.get("error") or "AWS RDS를 읽지 못했습니다.")
        return {**got, "src": src}
    if src == "export":
        from . import exportcheck
        got = exportcheck.peek(_exporter().out, table,
                               limit=min(limit, 200), offset=max(offset, 0))
        if got.get("error"):
            raise HTTPException(400, got["error"])
        # 크롤러 쪽과 같은 모양으로 맞춘다 — 화면이 한 벌이면 된다
        return {**got,
                "columns": [{"name": c, "type": "", "pk": False}
                            for c in got["columns"]],
                "rows": [dict(zip(got["columns"], r)) for r in got["rows"]],
                "src": src}
    got = _browser().rows(table, q=q, sort=sort, desc=desc,
                          limit=limit, offset=offset)
    if got.get("error"):
        raise HTTPException(400, got["error"])
    return {**got, "src": src}


@app.get("/api/export/inspect")
def api_export_inspect():
    """내보낸 SQL 안에 뭐가 들었는지. psql 을 돌리기 전에 확인용."""
    from . import exportcheck
    try:
        out = _exporter().out
        got = exportcheck.scan(out)
        got["verify"] = exportcheck.verify(out)
        return {"ok": True, **got}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/export/state")
def api_export_state():
    """스키마를 이미 만들었는지, 내보낸 파일이 뭐가 있는지."""
    ex = _exporter()
    outs = []
    for f in sorted(ex.out.glob("*")):
        if f.is_file():
            outs.append({"name": f.name, "kb": max(1, f.stat().st_size // 1024),
                         "at": datetime.fromtimestamp(f.stat().st_mtime).isoformat()[:19]})
    return {"schema": ex.schema_state(), "files": outs, "dir": str(ex.out)}


@app.get("/api/platform-db/state")
def api_platform_db_state():
    """로컬 PostgreSQL 또는 RDS 연결 상태. 비밀번호는 반환하지 않는다."""
    from .platformdb import PlatformDB
    try:
        return PlatformDB(ROOT).state()
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/platform-db/test")
def api_platform_db_test(req: Request, body: dict = Body(default={})):
    """입력한 RDS 설정으로 읽기 전용 연결만 확인한다. 적재는 수행하지 않는다."""
    from . import rdscheck
    from .platformdb import PlatformDB
    now = datetime.now().isoformat(timespec="seconds")
    try:
        db = PlatformDB(ROOT)
        out = rdscheck.diagnose(db.state(body))
        out["raw_error"] = rdscheck.short_error(out.get("error"))
        if out.get("ok"):
            db.save_public(db.config(body))
            db.remember_session(body)
        # 실패도 남긴다. 발표 전에 몇 번을 어떤 이유로 못 붙었는지 봐야 한다.
        AUTH.log("AWS RDS 연결 확인",
                 f"{(body or {}).get('database') or 'feedit'} — {out.get('title', '')}",
                 _who(req)["name"], _client_ip(req))
        return {**out, "checked_at": now}
    except Exception as e:
        return {"ok": False, "reachable": False, "checked_at": now,
                "cause": "unknown", "title": "연결 확인 중 오류가 났습니다",
                "todo": "입력값을 다시 보시고, 그래도 같으면 이 메시지를 알려 주세요.",
                "error": f"{type(e).__name__}: {e}"}


@app.post("/api/platform-db/load")
def api_platform_db_load(req: Request, body: dict = Body(default={})):
    """이미 설치된 FEEDIT FINAL RDS 35개 테이블에 수동 재적재한다."""
    try:
        out = RDS_SYNC.sync(body)
        if out.get("ok"):
            AUTH.log("AWS RDS 수동 재적재",
                     str((body or {}).get("database") or "feedit"),
                     _who(req)["name"], _client_ip(req))
        return out
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@app.post("/api/platform-db/drop")
def api_platform_db_drop(req: Request, body: dict = Body(default={})):
    """플랫폼 DB 삭제. 소유자만, DB 이름을 다시 입력해야 한다."""
    _need_owner(req)
    from .platformdb import PlatformDB
    try:
        out = PlatformDB(ROOT).drop_database(body)
        if out.get("ok"):
            AUTH.log("플랫폼 DB 삭제", out.get("database", ""),
                     _who(req)["name"], _client_ip(req))
        return out
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@app.post("/api/export/schema")
def api_export_schema(body: dict = Body(default={})):
    """플랫폼 스키마 SQL 을 만든다. 이미 있으면 그렇다고 알려 준다."""
    return _exporter().make_schema(force=bool(body.get("force")))


@app.post("/api/export/schema/installed")
def api_export_mark(req: Request, body: dict = Body(default={})):
    """'데이터베이스에 넣었다' 표시. 눌러 두면 버튼이 잠긴다."""
    ex = _exporter()
    r = ex.mark_installed(by=_who(req)["name"], undo=bool(body.get("undo")))
    AUTH.log("스키마 설치 표시", "취소" if body.get("undo") else "완료",
             _who(req)["name"], _client_ip(req))
    return r


@app.post("/api/export/run")
def api_export_run():
    """수집한 것을 스키마에 맞춰 SQL 로 내보낸다."""
    try:
        return _exporter().export()
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@app.get("/api/export/file/{name}")
def api_export_file(name: str):
    """만든 파일 내려받기."""
    ex = _exporter()
    f = (ex.out / name).resolve()
    # 경로 탈출 방지 — 내보내기 폴더 밖은 절대 안 준다
    if ex.out.resolve() not in f.parents or not f.is_file():
        raise HTTPException(404, "그런 파일이 없습니다.")
    return FileResponse(str(f), filename=f.name, media_type="text/plain")


# ── 새 플랫폼 마법사 ─────────────────────────────────────────
_WZ: dict = {}          # 방금 열어 본 화면을 잠깐 들고 있는다


@app.post("/api/wizard/open")
def api_wizard_open(req: Request, body: dict = Body(...)):
    """주소를 열어 보고 무엇이 어디 있는지 짐작한다."""
    url = str(body.get("url") or "").strip()
    if not url:
        return {"ok": False, "error": "주소를 넣어 주세요."}
    if "://" not in url:
        url = "https://" + url

    info = wizard.domain_of(url)
    html, how, warn = "", "", ""

    # 브라우저로 열어 본다 — 요즘 사이트는 대부분 JS 로 그린다.
    # robots 확인은 Renderer.ensure_allowed 가 먼저 한다 (RenderBlocked 로 튄다).
    # 여기서 또 확인하지 않는 이유: 규칙을 지키는 곳이 한 군데여야 안 어긋난다.
    try:
        from .renderer import Renderer, RenderBlocked, RenderUnavailable
        cfg = SiteConfig.from_dict({
            "code": info["code"], "name": info["code"],
            "base_url": info["base_url"],
            "render": {"enabled": True, "wait_ms": 3500, "target": 40,
                       "mobile": bool(body.get("mobile"))},
            "list_page": {}, "pace": {}})
        got = Renderer(cfg).render(info["path"] or "/", scroll=6)
        html, how = got.html, "브라우저로 열었습니다"
        if got.error:
            warn = got.error
    except RenderBlocked as e:
        return {"ok": False, "blocked": True,
                "error": "이 사이트는 자동 접근을 금지하고 있습니다 (robots.txt).",
                "hint": "규칙이라 우회하지 않습니다. 브라우저로 그 페이지를 저장한 뒤 "
                        "아래 '저장한 파일로 시작하기' 를 쓰시면 같은 결과를 얻습니다.",
                "raw": str(e)[:200], **info}
    except RenderUnavailable:
        warn = ("브라우저가 준비되지 않았습니다. "
                "서버에서 `playwright install chromium` 을 한 번 실행해 주세요.")
    except Exception as e:
        warn = str(e)[:200]

    if not html:
        return {"ok": False, "error": warn or "페이지를 열지 못했습니다.",
                "hint": "브라우저로 저장한 HTML 파일을 넣어도 됩니다.", **info}

    a = wizard.analyze(html, url)
    _WZ["html"] = html
    _WZ["url"] = url
    return {**info, **a, "how": how, "warn": warn, "kb": len(html) // 1024}


@app.post("/api/wizard/file")
async def api_wizard_file(file: UploadFile = File(...)):
    """저장본으로 시작하기 — 자동 접근이 막힌 사이트를 위한 길."""
    raw = (await file.read()).decode("utf-8", "replace")
    from .importer import saved_from_url
    url = saved_from_url(raw) or ""
    info = wizard.domain_of(url) if url else {
        "host": "", "base_url": "", "path": "", "code": "site"}
    a = wizard.analyze(raw, url)
    _WZ["html"] = raw
    _WZ["url"] = url
    return {**info, **a, "how": "저장본을 읽었습니다", "kb": len(raw) // 1024}


@app.post("/api/wizard/preview")
def api_wizard_preview(body: dict = Body(...)):
    """초안대로 뽑으면 무엇이 나오는지 실제로 보여 준다."""
    if not _WZ.get("html"):
        return {"ok": False, "error": "먼저 주소를 열어 주세요."}
    return wizard.preview(_WZ["html"], body.get("draft") or {})


@app.post("/api/wizard/save")
def api_wizard_save(req: Request, body: dict = Body(...)):
    r = wizard.save(CONFIG_DIR, body.get("draft") or {},
                    notes=str(body.get("notes") or ""))
    if r.get("ok"):
        AUTH.log("사이트 추가", r["code"], _who(req)["name"], _client_ip(req))
    return r


# ── 설정 폼 ──────────────────────────────────────────────────
FORM = siteform.SiteForm(CONFIG_DIR)


@app.get("/api/site/form/{code}")
def api_site_form(code: str):
    """설정을 폼으로 읽는다 — YAML 을 안 보고도 고칠 수 있게."""
    try:
        return FORM.read(code)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/site/form/{code}")
def api_site_form_save(req: Request, code: str, body: dict = Body(...)):
    """폼에서 온 값만 갈아 끼운다. 주석은 그대로 둔다."""
    who = _who(req)["name"]
    try:
        r = FORM.write(code, body.get("values") or {},
                       body.get("pages"), by=who)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if r.get("ok"):
        AUTH.log("설정 변경", code, who, _client_ip(req))
        # 다시 불러올 필요가 없다 — 스케줄러의 plans() 가 돌 때마다
        # 설정 파일을 새로 읽는다. 다음 주기부터 바뀐 값으로 돈다.
    else:
        PROBLEMS.add(title=f"{code} 설정을 저장하지 못했습니다",
                     source_code=code, where="설정", kind="config",
                     raw=r.get("error", ""))
    return r


# ── 문제 기록 ────────────────────────────────────────────────
@app.get("/api/problems")
def api_problems(source: str = "all", limit: int = 60, open_only: bool = True):
    """무엇이 왜 안 됐고, 무엇을 하면 되는지.

    ★ 볼 때마다 '이미 고쳐진 것' 을 먼저 접는다.
      브라우저를 깔았는데도 옛 기록이 그대로 떠 있어서
      "안 고쳐졌나?" 하고 헤매게 만든 적이 있다.
    """
    fixed = PROBLEMS.auto_resolve()
    return {"items": PROBLEMS.recent(limit, source, only_open=open_only),
            "summary": PROBLEMS.summary(),
            "auto_fixed": fixed,
            "kinds": problems.KINDS}


@app.post("/api/problems/resolve")
def api_problems_resolve(req: Request, body: dict = Body(default={})):
    n = PROBLEMS.resolve(str(body.get("kind") or ""),
                         str(body.get("source") or ""))
    AUTH.log("문제 접기", f"{n}건", _who(req)["name"], _client_ip(req))
    return {"ok": True, "closed": n}


@app.get("/api/quality/relevance")
def api_quality_relevance():
    """새 필터로 기존 소셜 데이터를 재검사하되 상태는 바꾸지 않는다."""
    from . import quality
    return quality.audit(store, apply=False)


@app.post("/api/quality/relevance")
def api_quality_relevance_apply(req: Request):
    """삭제 없이 격리 표시를 적용한다. 다시 실행하면 정상 행은 복구된다."""
    from . import quality
    out = quality.audit(store, apply=True)
    AUTH.log("소셜 데이터 품질 재분류",
             f"영상 {out['videos']['quarantined']} · 텍스트 "
             f"{sum(v['quarantined'] for v in out['texts'].values())}건 격리",
             _who(req)["name"], _client_ip(req))
    return out


@app.get("/api/coverage")
def api_coverage():
    """'우리 지표에 필요한 값이 사이트별로 들어오고 있나' 표.

    데이터 탭은 상품 하나를 보여 주지만, 정작 알아야 할 건
    '기능 하나를 만들 만큼 값이 모였나' 다. 그래서 따로 둔다.
    """
    return coverage.report(store)


# ── 정기 실행 · 건강 점검 ─────────────────────────────────────
@app.get("/api/health")
def api_health():
    """어드민 화면용. 사이트마다 '조용히 틀리고 있지 않은지' 본다."""
    hours = {c: p["every_hours"] for c, p in SCHED.plans().items()}
    return {"sites": health.check_all(store, hours), "schedule": SCHED.snapshot()}


@app.post("/api/health/check/{code}")
def api_health_check(code: str):
    """지금 당장 재 본다 (수집 없이 현재 DB 상태만)."""
    _config_path(code)
    health.snapshot(store, code, note="수동 점검")
    return health.check(store, code)


class SchedBody(BaseModel):
    enabled: Optional[bool] = None
    test_mode: Optional[bool] = None
    test_size: Optional[int] = None


@app.post("/api/schedule/toggle")
def api_sched_toggle(body: SchedBody):
    if body.enabled is not None:
        SCHED.enabled = body.enabled
    if body.test_mode is not None:
        SCHED.test_mode = body.test_mode
    if body.test_size:
        SCHED.test_size = max(1, min(int(body.test_size), 500))
    return {"ok": True, "enabled": SCHED.enabled,
            "test_mode": SCHED.test_mode, "test_size": SCHED.test_size}


@app.post("/api/schedule/auto/{code}")
def api_sched_auto(req: Request, code: str, body: dict = Body(default={})):
    """이 플랫폼만 자동 수집을 켜거나 끈다."""
    on = bool(body.get("on"))
    SCHED.set_auto(code, on)
    AUTH.log("자동 수집 " + ("켬" if on else "끔"), code, _who(req)["name"])
    return {"ok": True, "code": code, "auto": on}


@app.post("/api/schedule/run/{code}")
def api_sched_run_now(code: str):
    """예정 시각을 기다리지 않고 지금 돌린다."""
    plan = SCHED.plans().get(code)
    if not plan:
        raise HTTPException(404, "이 사이트에는 자동 실행 계획이 없습니다. "
                                 "설정의 schedule.every_hours 를 채우세요.")
    SCHED._run(code, plan)
    return {"ok": True}


_MANUAL_ALL_LOCK = threading.Lock()
_MANUAL_ALL_RUNNING = False


def _run_all_collection_plans():
    """상단 버튼 한 번으로 모든 자동 수집 계획을 안전하게 한 회차 실행한다.

    한꺼번에 브라우저를 여러 개 띄우면 사이트와 로컬 서버 양쪽에 부담이 된다.
    특히 musinsa/musinsa_used는 같은 호스트라 반드시 앞 작업이 끝난 다음 돈다.
    사용자에게는 한 번의 실행이지만 내부에서는 설정 순서대로 안전하게 진행한다.
    """
    global _MANUAL_ALL_RUNNING
    try:
        plans = SCHED.plans()
        order = ["musinsa", "musinsa_used", "kream", "zigzag", "ably",
                 "youtube", "naver"]
        codes = [c for c in order if c in plans and c not in SCHED.off]
        codes += [c for c in plans if c not in codes and c not in SCHED.off]
        _record("info", {"t": datetime.now().strftime("%H:%M:%S"),
                          "msg": f"[전체 수동 수집] {len(codes)}곳 한 회차 시작"})
        for code in codes:
            SCHED._run(code, plans[code])
            if code in ("naver", "youtube"):
                continue
            # 렌더링과 CrawlJob이 모두 끝날 때까지 기다려 다음 플랫폼을 연다.
            # 무한 대기는 막고, 실제 중단/오류 상태도 종료로 취급한다.
            started = time.time()
            while time.time() - started < 4 * 3600:
                job = jobs.get(code)
                busy = code in SCHED.rendering or (
                    job and job.state.phase in ("prepare", "list", "detail", "paused"))
                if not busy:
                    break
                time.sleep(1)
        _record("info", {"t": datetime.now().strftime("%H:%M:%S"),
                          "msg": "[전체 수동 수집] 모든 플랫폼 실행 요청 완료"})
    finally:
        with _MANUAL_ALL_LOCK:
            _MANUAL_ALL_RUNNING = False


@app.post("/api/schedule/run-all")
def api_sched_run_all():
    """수집 탭 최상단의 '전체 지금 수집' 버튼."""
    global _MANUAL_ALL_RUNNING
    with _MANUAL_ALL_LOCK:
        if _MANUAL_ALL_RUNNING:
            raise HTTPException(409, "전체 수집이 이미 진행 중입니다.")
        _MANUAL_ALL_RUNNING = True
    threading.Thread(target=_run_all_collection_plans, daemon=True).start()
    return {"ok": True, "plans": len([
        c for c in SCHED.plans() if c not in SCHED.off])}


# ── 담아오기 (북마클릿) ───────────────────────────────────────
#
#  무신사는 2026-08-31 직접 허가를 받아 자동 수집도 가능하지만,
#  사용자가 직접 연 화면을 추가로 담는 수동 경로도 계속 제공한다.
#
#  그래서 북마클릿을 쓴다. 사용자가 자기 브라우저에서 버튼을 누르면
#  화면에 있는 카드를 긁어 이 서버로 보낸다. 우리 쪽에서 나가는 요청은 0이다.
#  저장(Ctrl+S) → 파일 찾기 → 끌어다 놓기 세 단계가 클릭 한 번이 된다.
#
#  ★ 안전장치 — 이 창구는 토큰이 있어야 열린다.
#    localhost 서버라도 브라우저에서 아무 사이트나 부를 수 있으면,
#    사용자가 방문한 악성 페이지가 우리 DB 에 쓰레기를 밀어 넣을 수 있다.
TOKEN_FILE = DATA_DIR / "collect_token.txt"


def collect_token() -> str:
    if TOKEN_FILE.exists():
        t = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if t:
            return t
    import secrets
    t = secrets.token_urlsafe(18)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(t, encoding="utf-8")
    return t


class CollectBody(BaseModel):
    token: str
    site: Optional[str] = None
    url: str = ""
    html: str = ""
    count: int = 0


def _style_from_url(url: str) -> tuple[str, str]:
    """무신사 스타일 검색 주소에서 (스타일, 카테고리) 를 읽는다.

    .../search/goods?keyword=발레코어&category=103  →  ('발레코어', '신발')

    ★ 아무 검색어나 스타일로 받아들이면 안 된다
      '나이키' 를 검색한 페이지에서 담았다고 나이키가 스타일이 되면
      태그가 엉망이 된다. **계획에 적힌 14종일 때만** 스타일로 인정한다.
    """
    from urllib.parse import parse_qs, unquote, urlsplit
    try:
        q = parse_qs(urlsplit(url).query)
    except Exception:
        return "", ""
    kw = unquote((q.get("keyword") or [""])[0]).strip()
    code = (q.get("category") or [""])[0].strip()
    if not kw:
        return "", ""

    sp = _style_plan()
    # 본 이름이거나 연관 검색어면 그 스타일로 본다
    style = ""
    for st in sp["styles"]:
        if kw == st or kw in (sp.get("aliases") or {}).get(st, []):
            style = st
            break
    if not style:
        return "", ""
    label = next((c["name"] for c in sp["categories"] if c["code"] == code), "")
    return style, label


@app.options("/api/collect")
def api_collect_pre():
    return HTMLResponse("", headers=_cors())


def _cors() -> dict:
    # 브라우저가 다른 사이트에서 부를 수 있게 허용한다.
    # 토큰 검사가 실제 문지기이고, 이건 브라우저를 통과시키는 절차일 뿐이다.
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Max-Age": "600",
    }


@app.post("/api/collect")
def api_collect(body: CollectBody):
    import json as _j
    from .importer import detect_site, import_html

    if body.token != collect_token():
        raise HTTPException(403, "토큰이 맞지 않습니다. 북마클릿을 다시 등록하세요.")
    if not body.html.strip():
        raise HTTPException(400, "보낸 내용이 비어 있습니다.")

    configs = []
    for p in iter_config_files():
        try:
            configs.append(SiteConfig.load(p))
        except Exception:
            pass
    cfg = None
    if body.site:
        cfg = next((c for c in configs if c.code == body.site), None)
    if cfg is None:
        cfg = detect_site(body.html, configs)
    if cfg is None:
        raise HTTPException(404, "어느 사이트인지 알 수 없습니다.")

    # ★ 주소에서 스타일과 카테고리를 읽는다
    #   '발레코어' 를 검색한 페이지에서 담았으면 그 옷들은 발레코어다.
    #   버튼을 칸마다 만들 필요 없이, 주소가 이미 답을 갖고 있다.
    style, label = _style_from_url(body.url or "")
    r = import_html(body.html, cfg, store, filename=body.url or "(북마클릿)",
                    force_kind="list", style=style, page_label=label)
    # 어느 페이지를 담았는지 남긴다 — 진행판이 이걸 보고 칸을 채운다
    try:
        rid = store.start_run(cfg.code, f"collect:{body.url}")
        store.end_run(rid, "done", r.products, 0, False, "북마클릿")
    except Exception:
        pass
    from datetime import datetime as _dt
    _record("info", {"t": _dt.now().strftime("%H:%M:%S"),
                     "msg": f"[담아오기] {cfg.name} — {r.products}건 저장"})
    return StreamingResponse(
        iter([_j.dumps(r.as_dict(), ensure_ascii=False).encode()]),
        media_type="application/json", headers=_cors())


# ── 무신사 수집 진행판 ────────────────────────────────────────
#  무신사는 사람이 페이지를 열어 담아오므로 '어디까지 했는지'를
#  기억해 주는 게 필요하다. 10칸을 눈으로 보면서 채우면 빠뜨리지 않는다.
# ── 무신사 수동 수집 계획 ─────────────────────────────────────
#  ★ 코드를 여기 박아 두지 않는다
#    무신사가 카테고리 코드를 바꾼다. 실제로 '원피스/스커트' 가
#    020000 이 아니라 100000 이었다. 코드가 파일 안에 박혀 있으면
#    그때마다 개발자를 불러야 한다. config/musinsa.yaml 에서 읽고,
#    화면에서 주소를 붙여넣어 고칠 수 있게 한다.
def _musinsa_plan() -> dict:
    # SiteConfig 는 자기가 아는 키만 남기고 나머지를 버린다.
    # manual_plan 은 수집기 설정이 아니라 '사람이 담을 계획' 이라
    # 그 안에 없다. 그래서 YAML 을 직접 읽는다.
    try:
        import yaml
        raw = (CONFIG_DIR / "musinsa.yaml").read_text(encoding="utf-8")
        mp = dict((yaml.safe_load(raw) or {}).get("manual_plan") or {})
    except Exception:
        mp = {}
    cells = mp.get("cells") or []
    return {
        "cells": [c for c in cells if isinstance(c, dict) and c.get("code")],
        "target": int(mp.get("target_per_cell") or 200),
        "period": str(mp.get("period") or "MONTHLY"),
        "section": str(mp.get("section_id") or "200"),
    }


def _musinsa_url(gf: str, cat: str, period: str = "", section: str = "") -> str:
    pl = _musinsa_plan()
    return ("https://www.musinsa.com/main/musinsa/ranking"
            f"?gf={gf}&storeCode=musinsa&sectionId={section or pl['section']}&contentsId="
            f"&categoryCode={cat}&ageBand=AGE_BAND_ALL"
            f"&period={period or pl['period']}&subPan=product")


def _style_plan() -> dict:
    try:
        import yaml
        raw = (CONFIG_DIR / "musinsa.yaml").read_text(encoding="utf-8")
        sp = dict((yaml.safe_load(raw) or {}).get("style_plan") or {})
    except Exception:
        sp = {}
    return {
        "styles": list(sp.get("styles") or []),
        "categories": list(sp.get("categories") or []),
        "genders": list(sp.get("genders") or [{"code": "A", "name": "전체"}]),
        "aliases": dict(sp.get("aliases") or {}),
        "target": int(sp.get("target_per_cell") or 100),
        "url": str(sp.get("search_url") or ""),
    }


@app.get("/api/plan/musinsa/style")
def api_plan_style():
    """스타일 × 카테고리 진행판.

    담은 개수는 **그 스타일 태그가 붙은 상품**을 센다. 검색해서 담을 때
    검색어를 태그로 넣어 두므로, 따로 기록을 만들지 않아도 셀 수 있다.
    """
    sp = _style_plan()
    gall = [g["code"] for g in sp["genders"]]
    gname = {g["code"]: g["name"] for g in sp["genders"]}
    gname.setdefault("F", "여성")
    rows = []
    with store._lock:
        for st in sp["styles"]:
            for cat in sp["categories"]:
                # 카테고리가 성별을 못박아 두면 그걸 따른다
                # (원피스·스커트는 여성 검색에서만 나온다)
                for gf in (cat.get("genders") or gall):
                    # 과거 대표명(예: 스트릿웨어)으로 저장된 정확한 태그도
                    # 현재 프론트 대표명(스트릿)의 진행률에 포함한다.
                    names = [st] + list((sp.get("aliases") or {}).get(st, []))
                    marks = ",".join("?" for _ in names)
                    n = store._conn.execute(
                        f"""SELECT count(DISTINCT p.id) FROM staging_product p
                            WHERE p.source_code='musinsa' AND p.category_path = ?
                              AND EXISTS (
                                SELECT 1 FROM json_each(
                                  CASE WHEN json_valid(p.site_tags)
                                       THEN p.site_tags ELSE '[]' END)
                                WHERE value IN ({marks})
                              )""",
                        [cat["name"], *names]).fetchone()[0]
                    rows.append({
                        "style": st, "category": cat["name"],
                        "code": cat["code"], "gf": gf,
                        "gender": gname.get(gf, gf),
                        "done": n, "target": sp["target"],
                        "url": sp["url"].format(style=quote(st),
                                                code=cat["code"], gf=gf),
                    })
    return {"rows": rows, "styles": sp["styles"],
            "categories": [c["name"] for c in sp["categories"]],
            "aliases": sp.get("aliases") or {},
            "target": sp["target"],
            "total_target": sp["target"] * len(rows),
            "total_done": sum(r["done"] for r in rows)}


class PlanCell(BaseModel):
    index: int
    url: str


@app.post("/api/plan/musinsa/cell")
def api_plan_fix(req: Request, body: PlanCell):
    """칸 하나의 주소를 실제 주소로 고친다.

    사람이 브라우저에서 그 탭을 열고 주소창을 통째로 붙여넣으면,
    거기서 gf 와 categoryCode 를 읽어 설정에 적어 둔다.
    코드가 또 바뀌어도 파일을 안 열어도 된다.
    """
    from urllib.parse import parse_qs, urlsplit
    q = parse_qs(urlsplit(body.url.strip()).query)
    cat = (q.get("categoryCode") or [""])[0].strip()
    gf = (q.get("gf") or [""])[0].strip().upper()
    if not cat:
        return {"ok": False,
                "error": "주소에 categoryCode 가 없습니다. "
                         "무신사 랭킹 페이지 주소를 통째로 붙여넣어 주세요."}
    pl = _musinsa_plan()
    if not (0 <= body.index < len(pl["cells"])):
        return {"ok": False, "error": "없는 칸입니다."}
    cur = pl["cells"][body.index]
    if gf and gf != str(cur.get("gf", "")).upper():
        return {"ok": False,
                "error": f"이 칸은 '{cur.get('gender')}'({cur.get('gf')}) 인데 "
                         f"붙여넣은 주소는 gf={gf} 입니다. 탭을 다시 확인해 주세요."}
    old = str(cur.get("code") or "")
    r = siteform.set_plan_cell(CONFIG_DIR / "musinsa.yaml", body.index, cat)
    if not r.get("ok"):
        return r
    AUTH.log("무신사 칸 주소 고침",
             f"{cur.get('gender')} {cur.get('category')}: {old} → {cat}",
             _who(req)["name"], _client_ip(req))
    return {"ok": True, "old": old, "code": cat,
            "cell": f"{cur.get('gender')} {cur.get('category')}"}


@app.get("/api/plan/musinsa")
def api_plan_musinsa():
    """10개 조합을 각각 얼마나 담았는지.

    담아온 주소(gf·categoryCode)로 어느 칸인지 알아낸다.
    필터(1개월)는 주소에 안 남으므로 여기서 확인할 수 없다 —
    화면에서 맞추고 누르는 수밖에 없어 안내로만 적어 둔다.
    """
    from urllib.parse import urlsplit, parse_qs
    with store._lock:
        rows = store._conn.execute(
            """SELECT target, started_at, fetched_count FROM crawl_run
               WHERE source_code='musinsa' AND target LIKE 'collect:%'
               ORDER BY id DESC LIMIT 400""").fetchall()
    seen, stray = {}, []
    for r in rows:
        url = (r["target"] or "")[len("collect:"):]
        q = parse_qs(urlsplit(url).query)
        gf = (q.get("gf") or ["?"])[0].upper()
        cat = (q.get("categoryCode") or ["?"])[0]
        period = (q.get("period") or [""])[0].upper()
        rec = {"at": r["started_at"], "n": r["fetched_count"] or 0, "period": period}
        key = f"{gf}|{cat}"
        if key not in seen:
            seen[key] = rec
        if period and period != _musinsa_plan()["period"]:
            stray.append({"gf": gf, "cat": cat, "period": period,
                          "n": rec["n"], "at": rec["at"]})

    out = []
    pl = _musinsa_plan()
    for i, c in enumerate(pl["cells"]):
        gf, code = str(c.get("gf", "")).upper(), str(c["code"])
        hit = None
        for k, v in seen.items():
            g, cc = k.split("|", 1)
            # 코드가 001000 · 001 처럼 섞여 들어온다. 짧은 쪽 기준으로 맞춘다.
            if g == gf and (cc.startswith(code[:3]) or code.startswith(cc[:3])):
                hit = v
                break
        out.append({
            "index": i,
            "gender": c.get("gender"), "gender_code": gf,
            "category": c.get("category"), "category_code": code,
            "verified": bool(c.get("verified")),
            "target": pl["target"],
            "done": (hit or {}).get("n", 0),
            "at": (hit or {}).get("at"),
            "period": (hit or {}).get("period", ""),
            "period_ok": (hit or {}).get("period", pl["period"]) == pl["period"],
            "url": _musinsa_url(gf, code),
        })
    return {"rows": out, "target": pl["target"], "period": pl["period"],
            "total_target": pl["target"] * len(out),
            "total_done": sum(x["done"] for x in out),
            "unverified": sum(1 for x in out if not x["verified"]),
            "stray": stray[:6]}


@app.get("/paste", response_class=HTMLResponse)
def api_paste():
    """북마클릿이 보낸 것을 받아 서버로 넘기는 창.

    ★ 왜 창을 하나 더 여는가 —
      무신사 같은 큰 사이트는 CSP(콘텐츠 보안 정책)로
      '남의 스크립트 불러오기'와 '남의 주소로 요청 보내기'를 둘 다 막는다.
      그 페이지 안에서 fetch 를 하면 조용히 차단당한다.
      이 창은 관리자와 같은 출처라 그 제약을 받지 않는다.
      북마클릿은 postMessage 로 건네주기만 하면 된다 — 이건 CSP 대상이 아니다.
    """
    f = ROOT / "ui" / "paste.html"
    if not f.exists():
        return HTMLResponse("<h1>ui/paste.html 이 없습니다.</h1>", status_code=500)
    return HTMLResponse(f.read_text(encoding="utf-8"))


@app.get("/api/bookmarklet")
def api_bookmarklet(req: Request):
    """북마크에 넣을 javascript: 한 줄을 만들어 준다.

    ★ 스크립트를 밖에서 불러오지 않고 통째로 담는다.
      예전엔 <script src=...> 로 우리 서버 파일을 불러왔는데,
      CSP 가 그걸 막으면 아무 일도 안 일어난다(에러 표시조차 없다).
      실제로 그렇게 조용히 실패했다.
    """
    js = (ROOT / "ui" / "collect.js").read_text(encoding="utf-8")
    # 요청이 들어온 공개 주소를 넣는다. 로컬 접속이면 localhost가,
    # Cloudflare 터널로 접속하면 그 HTTPS 호스트가 들어간다.
    # JSON 문자열로 만들어 따옴표·특수문자도 안전하게 JS에 삽입한다.
    import json as _json
    base = str(req.base_url).rstrip("/")
    js = js.replace("__TOKEN__", collect_token()).replace(
        "__BASE__", _json.dumps(base, ensure_ascii=False))
    from urllib.parse import quote
    return {"href": "javascript:" + quote(js, safe="") ,
            "bytes": len(js), "token_set": True}


_PORT = [8765]


# ── 수동 저장본 가져오기 ──────────────────────────────────────
@app.post("/api/import")
async def api_import(files: list[UploadFile] = File(...),
                     site: str = "auto", dry_run: bool = False,
                     label: str = "", style: str = ""):
    """브라우저로 저장한 HTML 을 읽어 DB 에 넣는다. 요청은 한 번도 안 나간다.

    무신사처럼 robots.txt 가 막아 둔 곳은 이 길로만 모을 수 있다.
    사람이 직접 열어 저장한 파일이므로 크롤링이 아니다.
    """
    from .importer import detect_site, import_html

    configs = []
    for p in iter_config_files():
        try:
            configs.append(SiteConfig.load(p))
        except Exception:
            pass
    picked = None
    if site and site != "auto":
        picked = next((c for c in configs if c.code == site), None)
        if picked is None:
            raise HTTPException(404, f"'{site}' 설정이 없습니다.")

    out = []
    for f in files:
        raw = await f.read()
        try:
            html = raw.decode("utf-8")
        except UnicodeDecodeError:
            html = raw.decode("cp949", errors="replace")

        cfg = picked or detect_site(html, configs)
        if cfg is None:
            out.append({"filename": f.filename, "ok": False, "site": None,
                        "error": "어느 사이트인지 알 수 없습니다. 위에서 사이트를 직접 고르세요.",
                        "kind": "unknown", "products": 0, "listings": 0,
                        "trades": 0, "skipped": 0, "url": "", "sample": []})
            continue
        try:
            r = import_html(html, cfg, store, filename=f.filename or "",
                            dry_run=dry_run, page_label=label.strip(),
                            style=style.strip())
            out.append(r.as_dict())
        except Exception as e:
            out.append({"filename": f.filename, "ok": False, "site": cfg.code,
                        "error": str(e), "kind": "unknown", "products": 0,
                        "listings": 0, "trades": 0, "skipped": 0, "url": "", "sample": []})

    tot = {k: sum(r.get(k, 0) for r in out) for k in ("products", "listings", "trades")}
    tot["files"] = len(out)
    tot["failed"] = sum(1 for r in out if not r.get("ok"))
    return {"results": out, "total": tot, "dry_run": dry_run}


# ── 이미지 중계 ───────────────────────────────────────────────
IMG_CACHE = DATA_DIR / "imgcache"


@app.get("/api/img")
def api_img(u: str):
    """상품 이미지를 서버가 대신 받아 온다.

    왜 필요한가 — 크림 이미지는 네이버 CDN(pstatic.net)에 있는데, 브라우저가
    127.0.0.1 에서 바로 부르면 Referer 가 낯설어 막히는 경우가 있다.
    그러면 화면에 빈 칸만 남아서 '이미지를 못 긁었나' 하고 오해하게 된다.
    실제로는 주소를 멀쩡히 모아 뒀고, 보여 주는 쪽만 막힌 것이다.

    ★ 안전장치: DB 에 저장된 이미지 주소만 받아 온다.
      아무 주소나 받아 주면 이 서버가 남의 심부름꾼(오픈 프록시)이 되고,
      내부망 주소를 찔러 보는 통로로도 쓰일 수 있다.
    """
    with store._lock:
        known = store._conn.execute(
            "SELECT 1 FROM staging_product WHERE image_url = ? LIMIT 1", (u,)
        ).fetchone()
    if not known:
        raise HTTPException(403, "수집한 이미지 주소가 아닙니다.")

    import hashlib
    IMG_CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(u.encode()).hexdigest()[:32]
    hit = next(IMG_CACHE.glob(f"{key}.*"), None)
    if hit:                                   # 한 번 받은 건 다시 안 받는다
        return FileResponse(hit)

    import requests
    from urllib.parse import urlsplit
    origin = f"{urlsplit(u).scheme}://{urlsplit(u).netloc}/"
    try:
        r = requests.get(u, timeout=12, headers={
            "User-Agent": _identity.plain_ua(),   # config/identity.yaml 한 곳에서 나온다
            "Referer": origin,                # 자기 사이트에서 부르는 것처럼
            "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        })
    except requests.RequestException as e:
        raise HTTPException(502, f"이미지를 받지 못했습니다: {e}")
    if not r.ok or not r.content:
        raise HTTPException(r.status_code if r.status_code >= 400 else 502,
                            "이미지를 받지 못했습니다.")

    ctype = (r.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
           "image/gif": "gif", "image/avif": "avif"}.get(ctype, "img")
    path = IMG_CACHE / f"{key}.{ext}"
    path.write_bytes(r.content)
    return FileResponse(path, media_type=ctype)


def _shutdown_now():
    """Ctrl+C 를 눌렀을 때 할 일. 두 번 눌러야 꺼지는 상황을 없앤다."""
    if _shutdown.is_set():
        return
    _shutdown.set()
    try:
        SCHED.stop()
    except Exception:
        pass

    # 돌던 수집을 세운다. 이게 없으면 daemon 스레드가 종료 순간까지
    # 상대 서버를 계속 두드린다 — 끈 줄 알았는데 요청이 나가는 건 예의가 아니다.
    running = [c for c, j in jobs.items()
               if j.state.phase in ("list", "detail", "prepare")]
    for code in running:
        try:
            jobs[code].stop()
        except Exception:
            pass
    if running:
        print(f"\n수집을 세우는 중… ({', '.join(running)})")
        # 체크포인트가 저장될 틈만 준다. 오래 안 기다린다 —
        # 어디까지 했는지는 건마다 이미 기록돼 있어서 언제 끊겨도 이어서 돈다.
        for code in running:
            t = getattr(jobs[code], "_thread", None)
            if t and t.is_alive():
                t.join(timeout=2.0)
    print("종료합니다.")


def main(port: int = 8765, open_browser: bool = True):
    import uvicorn
    _PORT[0] = port          # 북마클릿이 부를 주소에 쓰인다

    # ★ 어디에서 들어오게 할지
    #   내 PC 에서만 볼 거면 127.0.0.1 이 안전하다 — 바깥에서 아예 안 보인다.
    #   클라우드에 올릴 때만 0.0.0.0 으로 연다. 실수로 열리지 않게
    #   환경변수를 명시해야만 열리도록 했다.
    host = cfgset.get("FEEDIT_HOST", "127.0.0.1")
    if host not in ("127.0.0.1", "localhost"):
        print(f"⚠ 바깥에 열려 있습니다 ({host}). 앞단에 HTTPS 를 꼭 두세요.")

    config = uvicorn.Config(
        app, host=host, port=port, log_level="warning",
        # 앞단 프록시가 넘겨주는 진짜 주소를 믿는다 (X-Forwarded-For).
        # 프록시 없이 열면 이 헤더를 아무나 넣을 수 있으니 주의.
        proxy_headers=(host not in ("127.0.0.1", "localhost")),
        forwarded_allow_ips="*" if host not in ("127.0.0.1", "localhost") else None,
        # 그래도 안 끝나는 게 있으면 5초 뒤 끊는다. 마지막 안전장치.
        timeout_graceful_shutdown=5,
    )
    server = uvicorn.Server(config)

    # uvicorn 이 자기 신호 처리기를 심기 때문에, 그걸 감싸서 우리 정리를 먼저 끼운다.
    # 순서가 중요하다 — 스트림을 먼저 깨워야 uvicorn 이 기다릴 게 없어진다.
    _orig = server.handle_exit

    def handle_exit(sig, frame):
        _shutdown_now()
        _orig(sig, frame)

    server.handle_exit = handle_exit

    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()

    # ── 첫 실행: 관리자 코드 만들기 ──
    #  코드는 여기 한 번만 찍는다. 화면으로는 절대 안 보낸다 —
    #  아직 아무도 로그인하지 않은 상태라 화면은 누구나 볼 수 있다.
    first = AUTH.bootstrap()
    if first:
        print()
        print("┌" + "─" * 56 + "┐")
        print("│  처음 실행입니다. 관리자 코드를 만들었습니다.".ljust(50) + "│")
        print("│" + " " * 56 + "│")
        print(f"│      {first['code']}".ljust(57) + "│")
        print("│" + " " * 56 + "│")
        print("│  ⚠ 이 코드는 다시 볼 수 없습니다. 지금 옮겨 적으세요.".ljust(48) + "│")
        print("│    잃어버리면:  python tools/admin_code.py --new".ljust(51) + "│")
        print("└" + "─" * 56 + "┘")
        print()
    AUTH.sweep()

    # ── 브라우저가 준비됐는지 미리 본다 ──
    #  지그재그·에이블리는 자바스크립트로 화면을 그려서 브라우저가 있어야 한다.
    #  없으면 12시간 뒤 자동 수집이 실패할 때까지 아무도 모른다.
    #  켤 때 한 번 확인해서 지금 알려 주는 편이 훨씬 낫다.
    need_browser = []
    for p_ in iter_config_files():
        try:
            c_ = SiteConfig.load(p_)
        except Exception:
            continue
        if (c_.render or {}).get("enabled"):
            need_browser.append(c_.name)
    if need_browser:
        from .renderer import installed as _browser_installed
        if not _browser_installed():
            print()
            print("⚠  브라우저가 준비되지 않았습니다.")
            print(f"   {' · '.join(need_browser)} 수집이 안 됩니다"
                  " (화면을 자바스크립트로 그리는 곳이라 브라우저가 필요합니다).")
            print()
            print("   한 번만 실행해 주세요:")
            print("       python -m playwright install chromium")
            print()

    # 지난 회차가 어디까지 갔는지 되살린다 — 주기가 6~12시간이라
    # 껐다 켜면 게이지가 0으로 돌아가 아무것도 알 수 없었다.
    _pipeline_load()
    SCHED.start()
    plans = SCHED.plans()
    if plans:
        print("자동 실행: " + ", ".join(
            f"{v['name']} {v['every_hours']:.0f}시간마다" for v in plans.values()))
    print(f"FEEDiT 관리자 → http://{'127.0.0.1' if host in ('127.0.0.1','localhost') else host}:{port}   (끄려면 Ctrl+C)")
    try:
        server.run()
    except KeyboardInterrupt:
        _shutdown_now()
