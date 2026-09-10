"""feedit-chat 개발 서버 — 표준 라이브러리만 쓴다.

왜 FastAPI 를 안 쓰나
  이 기기의 python3 에 fastapi 가 없다. 크롤러 venv 에는 있지만,
  그걸 쓰게 하면 "venv 를 켜야 챗봇이 돈다" 는 조건이 하나 더 붙는다.
  전송 계층은 나중에 Django/FastAPI 로 갈아 끼울 것이라 지금 얇게 둔다.
  ChatEngine 은 HTTP 를 모른다 — 갈아 끼울 때 손댈 곳은 이 파일뿐이다.

  ⚠ 로그인은 아직 없다. 대신 밖에 열 때를 위해 두 가지를 둔다 —
     ① IP 당 분당 횟수 제한 (항상 켜짐, 설정 필요 없음)
     ② 공유 토큰 FEEDIT_CHAT_TOKEN (설정했을 때만 검사)
     둘 다 로그인의 대체물이 아니다. 스캐너가 우리 OpenAI 키를 태우는 것을
     막는 최소한이다. 사용자별 한도·과금은 여전히 없다.

엔드포인트
  GET  /v1/health                    떠 있나 · 기준일 · 적재 term 수
  GET  /v1/llm                       LLM 배선 진단 (모델 · 키 유무 · 마지막 오류)
  GET  /v1/me?plan=FREE              플랜과 하루 한도 (아직 계정이 없어 질의로 받는다)
  POST /v1/chat                      SSE 스트림
       {question, mode, plan, conversation_id, history?, images?}
       history 는 [{q, intent, terms:[{canonical,facet,term_key}]}] — 최근 8턴까지.
       보내면 그쪽을 쓰고, 안 보내면 서버가 conversation_id 로 기억한 것을 쓴다.
       images 는 data URL 문자열 배열(최대 MAX_IMAGES장, data:image/... 로 시작)이다.
       사진이 오면 지표 게이트·도구 루프를 타지 않고 곧장 비전 모델로 간다
       (ChatEngine._vision_ask, 2026-09-10 — 아래 이미지 첨부 절 참고).
  POST /v1/lexicon/requests          어휘 등록 요청
       {surface, facet_guess, question}

SSE 순서는 프론트가 이미 그리는 순서에 맞춘다 (chat_popup.js:105~121).
  status → text(여러 번) → report → actions → done
  글자를 먼저 흘리고 카드를 나중에 보내야 .ansCard.reveal.in 이 뒤따라 떠오른다.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from app import plans
from app.engine import ChatEngine

# ── 어디에 여나 ────────────────────────────────────────────
#   기본은 127.0.0.1 이다. 그대로 둔다 — 인증이 없기 때문이다.
#   도커 안에서는 컨테이너 밖에서 못 닿으므로 compose 가 0.0.0.0 을 넣어 준다.
#   그때도 포트는 `127.0.0.1:8770:8770` 로 묶어 호스트 밖으로는 안 나간다.
HOST = os.getenv("FEEDIT_CHAT_HOST", "127.0.0.1")
PORT = int(os.getenv("FEEDIT_CHAT_PORT", "8770"))

# vite dev 서버만 허용한다. 와일드카드를 쓰지 않는다.
#   팀원이 다른 포트를 쓰면 FEEDIT_CHAT_ORIGINS 에 쉼표로 이어 붙인다.
_DEFAULT_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173",
                    "http://localhost:4173", "http://127.0.0.1:4173")
ALLOW_ORIGINS = {o.strip() for o in
                 (os.getenv("FEEDIT_CHAT_ORIGINS") or ",".join(_DEFAULT_ORIGINS)).split(",")
                 if o.strip()}
# ★ 이미지 첨부(2026-09-10) 전에는 64KB였다. 사진은 base64로 실려 오면
#   원본보다 33% 정도 불어나므로, 프론트가 축소·압축해 보내는 걸 전제로 하고도
#   여유를 넉넉히 둔다. MAX_IMAGES · MAX_IMAGE_DATAURL 이 실제 상한을 잡는다.
MAX_BODY = 8 * 1024 * 1024
MAX_IMAGES = 3
MAX_IMAGE_DATAURL = 6 * 1024 * 1024   # data URL 문자열 길이 기준 — 대략 디코딩 4.5MB

# ── 밖에 열 때의 최소 방어 ──────────────────────────────────
#   ★ 이건 로그인이 아니다. "주소를 아무도 모른다" 는 방어가 아니라서 둔다 —
#     공개된 주소는 봇이 몇 시간 안에 찾아낸다. 그때 막아 주는 건 이 둘뿐이다.
#
#   FEEDIT_CHAT_TOKEN  비워 두면 검사하지 않는다(로컬 개발 그대로).
#                      넣으면 X-FEEDiT-Token 머리글이 같아야 통과한다.
#                      버셀 함수가 붙여 주므로 브라우저는 토큰을 모른다.
CHAT_TOKEN = (os.getenv("FEEDIT_CHAT_TOKEN") or "").strip()

#   IP 당 분당 질문 수. 사람은 분당 몇 번 못 묻는다.
RATE_PER_MIN = int(os.getenv("FEEDIT_CHAT_RATE_PER_MIN", "20"))
_hits: dict[str, list[float]] = {}
_hits_lock = threading.Lock()


def rate_ok(ip: str) -> bool:
    """최근 60초 안에 RATE_PER_MIN 을 넘었나. 넘으면 False."""
    now = time.time()
    with _hits_lock:
        q = [t for t in _hits.get(ip, ()) if now - t < 60]
        if len(q) >= RATE_PER_MIN:
            _hits[ip] = q
            return False
        q.append(now)
        _hits[ip] = q
        if len(_hits) > 5000:                 # 메모리가 무한정 늘지 않게
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > 300]:
                _hits.pop(k, None)
    return True


# ── 하루 사용 한도 (FREE 만) ─────────────────────────────────
#   기획대로 FREE 는 하루 plans.QUOTA[FREE]["turns"]회 — 숫자를 여기 새로 적지 않고
#   plans.py 값을 그대로 쓴다. 한 곳에서만 정해야 화면 문구와 여기가 어긋나지 않는다.
#   PRO·BUSINESS 는 막지 않는다 (plans.py 주석 — "300 은 사실상 무제한").
#
#   ★ 아직 로그인이 없어(이 파일 머리말) IP 로 센다. plan 값도 요청이 스스로 말한 값이라
#     클라이언트가 "PRO" 라고 우기면 지금은 못 막는다 — 로그인이 붙기 전까지의 한계다.
_daily: dict[str, tuple[str, int]] = {}
_daily_lock = threading.Lock()


def _today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def daily_ok(ip: str, plan: str) -> bool:
    """오늘 이 IP 가 FREE 하루 한도를 넘었나. FREE 가 아니면 항상 True."""
    if plan != plans.FREE:
        return True
    limit = plans.QUOTA[plans.FREE]["turns"]
    today = _today()
    with _daily_lock:
        day, count = _daily.get(ip, (today, 0))
        if day != today:
            day, count = today, 0
        if count >= limit:
            _daily[ip] = (day, count)
            return False
        _daily[ip] = (day, count + 1)
        if len(_daily) > 5000:                # 메모리가 무한정 늘지 않게
            for k, (d, _c) in list(_daily.items()):
                if d != today:
                    _daily.pop(k, None)
    return True

# 어휘 등록 요청을 어디에 쌓나.
#   배포되면 RDS 의 dictionary.term_candidate 로 간다 (설계서 3.5).
#   지금은 RDS 에 붙을 수 없어 파일에 줄 단위로 쌓는다.
#   ★ 버튼만 만들어 두고 아무 데도 안 보내면 "누르면 되는 척" 이 된다. 실제로 남긴다.
REQ_LOG = Path(__file__).resolve().parent / "data" / "lexicon_requests.jsonl"
KST = timezone(timedelta(hours=9))
_req_lock = threading.Lock()

_engine: ChatEngine | None = None
_engine_lock = threading.Lock()


def engine() -> ChatEngine:
    """엔진은 하나만 만든다. 사전 로딩이 무거워 매 요청 만들면 안 된다."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = ChatEngine()
    return _engine


def sse(event: str, data) -> bytes:
    return (f"event: {event}\n"
            f"data: {json.dumps(data, ensure_ascii=False)}\n\n").encode("utf-8")


def _log_turn(question: str, rep: dict) -> None:
    """답 하나가 어떻게 끝났는지 한 줄. (2026-09-10)

    ★ 왜 필요한가 — 화면에 안내문이 뜨면 원인이 **시간(NET_ReadTimeout)** 인지
      **한도(HTTP_429)** 인지 구분할 방법이 없었다. 둘 다 같은 문구로 나온다.
      trace 는 report 이벤트에 실려 나가지만 그걸 보려면 개발자도구를 열어야 하고,
      서버 콘솔에는 아무것도 남지 않았다. 추측하지 않으려고 한 줄 남긴다.
    ★ 질문은 앞 40자만. 로그는 원본이 아니다.
    """
    tr = rep.get("trace") or {}
    if not tr:
        return
    mark = "!" if (tr.get("stopped") not in ("done", None) or tr.get("over_budget")) else " "
    try:
        rounds = "+".join(str(x) for x in (tr.get("round_ms") or [])) or "-"
        hosted = tr.get("hosted") or 0
        print(f"{mark} [{time.strftime('%H:%M:%S')}] {tr.get('ms')}ms "
              f"stopped={tr.get('stopped')} 바퀴={tr.get('rounds')}({rounds}ms) "
              f"웹검색={hosted} 호출={tr.get('calls')} "
              f"도구={','.join(tr.get('tools') or []) or '-'} "
              f"| {question[:40]}", flush=True)
    except Exception:                              # noqa: BLE001
        pass                                       # 로그가 대화를 막지 않는다


def split_deltas(html: str) -> list[str]:
    """한 줄 결론을 조각으로 나눈다.

    태그(<b>…</b>)는 통째로 한 조각으로 보낸다.
    프론트가 어느 순간에 잘라도 항상 닫힌 HTML 만 그리게 하기 위해서다
    (chat_popup.js 의 cpTypeHTML 이 쓰는 규칙과 같다).
    """
    out, buf = [], ""
    for tok in re.split(r"(<[^>]+>)", html):
        if not tok:
            continue
        if tok.startswith("<"):
            if buf:
                out.append(buf)
                buf = ""
            out.append(tok)
            continue
        for ch in tok:
            buf += ch
            if len(buf) >= 3:
                out.append(buf)
                buf = ""
    if buf:
        out.append(buf)
    return out


def actions_for(rep: dict) -> list[dict]:
    """다음에 무엇을 할 수 있는지. 화면에 실제로 있는 곳으로만 보낸다."""
    acts = []
    terms = rep.get("terms") or []
    first = terms[0] if terms else None
    if first and first.get("facet") == "style":
        acts.append({"label": "Style 탭에서 자세히", "type": "view",
                     "view": "style", "style": first.get("canonical")})
    if first and first.get("available"):
        acts.append({"label": "지표로 보기", "type": "view", "view": "trend",
                     "part": "temp", "keyword": first.get("canonical")})
    if rep.get("hint", {}).get("code") == "MODE_MISMATCH":
        acts.append(rep["hint"]["action"] | {"label": "살!말? 모드로"})
    return acts


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "feedit-chat/dev"

    # 접속 로그를 조용히 — 개발 중 콘솔이 SSE 로 도배된다
    def log_message(self, fmt, *args):
        if "--verbose" in sys.argv:
            super().log_message(fmt, *args)

    # ── 공통 ──────────────────────────────────────────
    def _origin_ok(self) -> str | None:
        o = self.headers.get("Origin")
        return o if o in ALLOW_ORIGINS else None

    def _cors(self):
        o = self._origin_ok()
        if o:
            self.send_header("Access-Control-Allow-Origin", o)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ── GET ───────────────────────────────────────────
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/v1/health":
            try:
                e = engine()
                return self._json(200, {"ok": True, "as_of": e.store.latest_day(),
                                        "metric_version": e.store.version,
                                        "terms": len(e.gate.prefer)})
            except Exception as ex:                       # noqa: BLE001
                return self._json(500, {"ok": False, "error": type(ex).__name__})
        if u.path == "/v1/llm":
            # 배선 진단. **키 값은 절대 안 나간다** — 있나 없나와 길이뿐이다.
            from app import llm
            from app.env import where
            return self._json(200, {"ok": True, "model": llm.MODEL, "api": llm.API,
                                    "effort": llm.DEFAULT_EFFORT,
                                    "disabled": llm.DISABLED,
                                    "key": llm.key_hint(), "key_from": llm.source_hint(),
                                    "env_file": where(), "last_error": llm.LAST_ERROR})
        if u.path == "/v1/me":
            q = parse_qs(u.query)
            plan = plans.normalize((q.get("plan") or ["FREE"])[0])
            return self._json(200, {"ok": True, "plan": plan,
                                    "quota": plans.QUOTA[plan],
                                    "note": "인증이 아직 없습니다. 개발용으로 질의 문자열의 plan 을 그대로 씁니다."})
        return self._json(404, {"ok": False, "error": "NOT_FOUND"})

    # ── POST ──────────────────────────────────────────
    def _read_json(self) -> dict | None:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if n <= 0 or n > MAX_BODY:
            return None
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    def _client_ip(self) -> str:
        """앞단(Caddy)이 붙여 주는 X-Forwarded-For 의 **맨 앞**이 진짜 손님이다.
        뒤쪽은 중간 프록시라 그걸 쓰면 전원이 한 IP 로 묶여 다 같이 막힌다."""
        fwd = self.headers.get("X-Forwarded-For") or ""
        return (fwd.split(",")[0].strip() or self.client_address[0])

    def _guard(self) -> bool:
        """토큰·횟수 검사. 막으면 응답까지 보내고 False 를 돌려준다."""
        if CHAT_TOKEN and self.headers.get("X-FEEDiT-Token") != CHAT_TOKEN:
            # 왜 막혔는지 자세히 알려 주지 않는다 — 맞히는 데 도움이 된다.
            self._json(401, {"ok": False, "reason": "UNAUTHORIZED",
                             "message": "허용되지 않은 요청입니다."})
            return False
        if not rate_ok(self._client_ip()):
            self._json(429, {"ok": False, "reason": "RATE_LIMITED",
                             "message": f"질문이 너무 잦습니다. 잠시 후 다시 시도해 주세요 "
                                        f"(분당 {RATE_PER_MIN}회)."})
            return False
        return True

    def _lexicon_request(self):
        req = self._read_json()
        if not req:
            return self._json(400, {"ok": False, "error": "BAD_BODY"})
        surface = " ".join(str(req.get("surface") or "").split())[:60]
        if not surface:
            return self._json(400, {"ok": False, "error": "EMPTY_SURFACE"})
        row = {
            "surface": surface,
            "facet_guess": (str(req.get("facet_guess") or "") or None),
            "question": " ".join(str(req.get("question") or "").split())[:300],
            "source": "chatbot",
            "at": datetime.now(KST).isoformat(timespec="seconds"),
        }
        with _req_lock:
            REQ_LOG.parent.mkdir(parents=True, exist_ok=True)
            with REQ_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            # 같은 말이 몇 번 요청됐나 — 사전 보강 우선순위가 된다
            count = sum(1 for ln in REQ_LOG.open(encoding="utf-8")
                        if json.loads(ln).get("surface") == surface)
        return self._json(200, {"ok": True, "surface": surface, "count": count,
                                "message": f"'{surface}' 등록 요청을 받았습니다. 검토 후 사전에 추가됩니다."})

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/v1/chat", "/v1/lexicon/requests"):
            return self._json(404, {"ok": False, "error": "NOT_FOUND"})
        # ★ 쓰는 길은 전부 여기를 지난다. 검사를 분기 뒤에 두면
        #   새 엔드포인트를 더할 때 조용히 빠뜨리게 된다.
        if not self._guard():
            return
        if path == "/v1/lexicon/requests":
            return self._lexicon_request()
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > MAX_BODY:
            return self._json(400, {"ok": False, "error": "BAD_BODY"})
        try:
            req = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._json(400, {"ok": False, "error": "BAD_JSON"})

        question = str(req.get("question") or "")
        mode = "salmal" if req.get("mode") == "salmal" else "general"
        plan = plans.normalize(req.get("plan"))
        conv = str(req.get("conversation_id") or "")[:64] or None
        # 클라이언트가 최근 턴을 같이 보낼 수 있다 (세션 목록의 원본은 클라이언트다).
        # 안 보내면 서버 메모리의 같은 conversation_id 를 쓴다.
        hist = req.get("history") if isinstance(req.get("history"), list) else None

        # ── 이미지 첨부 (2026-09-10) ─────────────────────────
        #   data URL 문자열만 받는다 — 형식이 아니면(잘못된 값·주소만 온 것 등)
        #   조용히 버린다. 개수·장당 용량은 여기서 미리 자른다 —
        #   ChatEngine 안까지 큰 문자열을 들고 가지 않게.
        images_in = req.get("images") if isinstance(req.get("images"), list) else []
        images: list[str] = []
        for u in images_in[:MAX_IMAGES]:
            if not isinstance(u, str):
                continue
            u = u.strip()
            if not u.startswith("data:image/"):
                continue
            if len(u) > MAX_IMAGE_DATAURL:
                return self._json(400, {"ok": False, "error": "IMAGE_TOO_LARGE",
                                        "message": "이미지 용량이 너무 큽니다. 더 작은 이미지로 다시 시도해 주세요."})
            images.append(u)

        if not daily_ok(self._client_ip(), plan):
            limit = plans.QUOTA[plans.FREE]["turns"]
            return self._json(429, {
                "ok": False, "reason": "DAILY_LIMIT",
                "message": f"오늘 무료 이용 횟수({limit}회)를 다 쓰셨습니다.\n"
                           "내일 다시 이용하시거나, 더 넉넉한 플랜으로 올려 보세요.",
            })

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self._cors()
        self.end_headers()

        def push(ev, data):
            self.wfile.write(sse(ev, data))
            self.wfile.flush()

        try:
            push("status", {"stage": "lexicon"})
            e = engine()
            push("status", {"stage": "metric"})
            # 화면 컨텍스트 — 새 경로가 "이거 어때?" 를 푸는 재료.
            #   없으면 없는 대로 돈다(도구 목록만 줄어든다).
            extra = {k: req.get(k) for k in
                     ("screen_term", "salmal_card_id", "user_id", "region")
                     if req.get(k)}
            # ★ 도구를 부를 때마다 사용자의 말로 흘려보낸다 (설계도 부록 10).
            #   답이 완성될 때까지 화면이 비어 있으면 3초만 지나도 고장난 것처럼
            #   보인다. 같은 시간이라도 무엇을 보고 있는지 알면 기다림이 된다.
            def say(msg):
                push("status", {"stage": "tool", "message": msg})

            rep = e.ask(question, mode=mode, plan=plan,
                        conversation_id=conv, history_in=hist, extra=extra,
                        on_progress=say, images=images or None)

            if not rep.get("ok"):
                # 실패도 대화다. 에러 코드로 끝내지 않고 할 말을 준다.
                push("error", rep)
                push("done", {"ok": False, "reason": rep.get("reason")})
                return

            if rep.get("kind") == "meta":
                for d in split_deltas(rep["message"]):
                    push("text", {"delta": d})
                    time.sleep(0.012)
                push("done", {"ok": True})
                return

            for d in split_deltas(rep["headline"]):
                push("text", {"delta": d})
                time.sleep(0.012)
            push("report", rep)
            _log_turn(question, rep)
            acts = actions_for(rep)
            if acts:
                push("actions", acts)
            push("done", {"ok": True, "intent": rep.get("intent"),
                          "as_of": rep.get("as_of"),
                          "partial": bool(rep.get("partial"))})
        except BrokenPipeError:
            pass                                   # 사용자가 창을 닫았다. 정상이다.
        except Exception as ex:                    # noqa: BLE001
            try:
                push("error", {"ok": False, "reason": "SERVER_ERROR",
                               "message": "서버에서 답을 만들지 못했습니다.",
                               "detail": type(ex).__name__})
                push("done", {"ok": False})
            except OSError:
                pass


def main():
    port = PORT
    for a in sys.argv[1:]:
        if a.startswith("--port="):
            port = int(a.split("=", 1)[1])

    # ★ 준비물이 없으면 여기서 멈춘다.
    #   없는 채로 engine() 을 부르면 ImportError 스택트레이스가 뜨는데,
    #   처음 켜 보는 팀원에게 그건 "고장났다" 로 읽힌다. 무엇이 없는지 말해 준다.
    from app import config, llm
    gaps = config.missing_inputs()
    if gaps:
        print("먼저 채워야 할 것이 있습니다 — 챗봇 엔진을 켤 수 없습니다.\n")
        for g in gaps:
            print("  · " + g)
        print("\n크롤러 저장소를 받은 뒤 저장소 루트 .env 에 경로를 적어 주세요:")
        print("  FEEDIT_CRAWLER_DIR=/절대/경로/feedit-crawler")
        print("\n자세한 진단:  python3 tools_env_check.py")
        return 2

    engine()                                        # 사전을 미리 읽어 첫 요청을 빠르게
    srv = ThreadingHTTPServer((HOST, port), Handler)
    e = engine()
    print(f"feedit-chat  http://{HOST}:{port}")
    print(f"  기준일 {e.store.latest_day()} · 지표 term {len(e.gate.prefer):,}개")
    print(f"  모델 {llm.MODEL} · 키 {llm.key_hint()}")
    print(f"  허용 오리진 {sorted(ALLOW_ORIGINS)}")
    print(f"  토큰 {'검사함' if CHAT_TOKEN else '없음(로컬 개발)'} · 분당 {RATE_PER_MIN}회 제한")
    if HOST not in ("127.0.0.1", "localhost") and not CHAT_TOKEN:
        print("  ⚠ 밖에 열면서 FEEDIT_CHAT_TOKEN 이 없습니다. 주소가 알려지면 누구나 질문할 수 있습니다.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n종료")
        srv.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
