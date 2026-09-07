"""feedit-chat 개발 서버 — 표준 라이브러리만 쓴다.

왜 FastAPI 를 안 쓰나
  이 기기의 python3 에 fastapi 가 없다. 크롤러 venv 에는 있지만,
  그걸 쓰게 하면 "venv 를 켜야 챗봇이 돈다" 는 조건이 하나 더 붙는다.
  전송 계층은 나중에 Django/FastAPI 로 갈아 끼울 것이라 지금 얇게 둔다.
  ChatEngine 은 HTTP 를 모른다 — 갈아 끼울 때 손댈 곳은 이 파일뿐이다.

  ⚠ 개발용이다. 인증이 없다. 0.0.0.0 에 열지 말 것.

엔드포인트
  GET  /v1/health                    떠 있나 · 기준일 · 적재 term 수
  GET  /v1/me?plan=FREE              플랜과 하루 한도 (아직 계정이 없어 질의로 받는다)
  POST /v1/chat                      SSE 스트림
       {question, mode, plan, conversation_id, history?}
       history 는 [{q, intent, terms:[{canonical,facet,term_key}]}] — 최근 8턴까지.
       보내면 그쪽을 쓰고, 안 보내면 서버가 conversation_id 로 기억한 것을 쓴다.
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

HOST = "127.0.0.1"
PORT = 8770
# vite dev 서버만 허용한다. 와일드카드를 쓰지 않는다.
ALLOW_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173",
                 "http://localhost:4173", "http://127.0.0.1:4173"}
MAX_BODY = 64 * 1024

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
        if path == "/v1/lexicon/requests":
            return self._lexicon_request()
        if path != "/v1/chat":
            return self._json(404, {"ok": False, "error": "NOT_FOUND"})
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
            rep = e.ask(question, mode=mode, plan=plan,
                        conversation_id=conv, history_in=hist)

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
            acts = actions_for(rep)
            if acts:
                push("actions", acts)
            push("done", {"ok": True, "intent": rep.get("intent"),
                          "as_of": rep.get("as_of")})
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
    engine()                                        # 사전을 미리 읽어 첫 요청을 빠르게
    srv = ThreadingHTTPServer((HOST, port), Handler)
    e = engine()
    print(f"feedit-chat  http://{HOST}:{port}")
    print(f"  기준일 {e.store.latest_day()} · 지표 term {len(e.gate.prefer):,}개")
    print(f"  허용 오리진 {sorted(ALLOW_ORIGINS)}")
    print("  개발용입니다. 인증이 없습니다.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n종료")
        srv.shutdown()


if __name__ == "__main__":
    main()
