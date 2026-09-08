"""Luna 클라이언트 — OpenAI Responses API.

크롤러의 `llm_analysis.py` 와 **같은 방식**을 쓴다. 모델도 같다.
두 곳이 다른 모델을 쓰면 "왜 답이 다르지" 를 영영 못 쫓는다.

★ 이 모듈이 지키는 것

1. **키를 절대 출력하지 않는다.** 예외 문구에도 안 넣는다.
   실패하면 예외 종류와 HTTP 상태만 남긴다 (AGENTS.md §8).

2. **실패하면 None 을 돌려준다.** 던지지 않는다.
   LLM 이 죽어도 챗봇은 규칙으로 답해야 한다. LLM 은 거들 뿐이다.

3. **숫자를 만들게 하지 않는다.** 이 모듈은 전송만 한다.
   무엇을 시킬지는 부르는 쪽이 정하고, 숫자 보호는 polish.py 가 자리표시자로 막는다.

★ 키를 어디서 읽나
   ① 환경변수 OPENAI_API_KEY
      — 셸 지정, 도커 `env_file`, 그리고 저장소 루트 `feedit/.env`.
        .env 는 `app/__init__.py` 가 import 시점에 한 번 읽어 둔다(app/env.py).
   ② 크롤러의 data/keys.json (관리자 화면이 저장하는 곳)
   둘 다 없으면 available() 이 False 다 — 챗봇은 그냥 규칙으로 돈다.

   어디서 읽혔는지는 `source_hint()` 로 본다. 값은 안 나온다.
   설정이 맞는지 한 번에 보려면: `python3 tools_env_check.py`
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any

from .config import CRAWLER

# ── 어디로 · 어떤 모델로 보내나 ────────────────────────────────
#   전부 환경변수로 뺐다. 팀원마다 다른 값을 쓸 수 있어야 하고,
#   모델을 바꿀 때 코드를 고치면 누가 언제 바꿨는지가 기록에 안 남는다.
#
#   OPENAI_BASE_URL   기본 https://api.openai.com/v1
#                     사내 게이트웨이·프록시를 쓸 때만 바꾼다.
#   FEEDIT_LLM_MODEL  기본 gpt-5.6-luna
#   FEEDIT_LLM_EFFORT 기본 low — 부르는 쪽이 따로 정하면 그쪽이 이긴다.
#                     none · low · medium · high · xhigh · max
API = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
MODEL = os.getenv("FEEDIT_LLM_MODEL", "gpt-5.6-luna")
DEFAULT_EFFORT = (os.getenv("FEEDIT_LLM_EFFORT") or "low").strip().lower()
EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")
PROMPT_VERSION = "feedit-chat-v1"

# 챗봇 전체를 규칙만으로 돌리고 싶을 때 (FEEDIT_LLM_DISABLED=1)
DISABLED = (os.getenv("FEEDIT_LLM_DISABLED") or "").strip().lower() in ("1", "true", "yes")

# 마지막 실패 이유. 진단용이고 키는 절대 안 들어간다.
LAST_ERROR: str | None = None

_key_cache: str | None = None
_key_lock = threading.Lock()


def _read_key() -> str:
    global _key_cache
    if _key_cache is not None:
        return _key_cache
    with _key_lock:
        if _key_cache is not None:
            return _key_cache
        # ① 환경변수 (셸 · 도커 env_file · 저장소 .env — app/__init__.py 가 읽어 둔다)
        key = (os.getenv("OPENAI_API_KEY") or "").strip()
        if not key:
            # ② 크롤러 관리자 화면이 저장하는 곳. 크롤러를 같이 쓰는 사람만 해당된다.
            path = CRAWLER / "data" / "keys.json"
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
                key = str((d.get("OPENAI_API_KEY") or {}).get("value") or "").strip()
            except (OSError, ValueError, AttributeError):
                key = ""
        _key_cache = key
    return _key_cache


def source_hint() -> str:
    """키를 어디서 읽었나. 값은 안 보여 준다 — 팀원이 설정을 못 찾을 때 이것만 보면 된다."""
    if not _read_key():
        return "없음"
    if (os.getenv("OPENAI_API_KEY") or "").strip():
        from .env import where
        return f"환경변수 OPENAI_API_KEY (.env: {where()})"
    return f"{CRAWLER / 'data' / 'keys.json'}"


def available() -> bool:
    return (not DISABLED) and bool(_read_key())


def key_hint() -> str:
    """키가 있나 없나만. 값은 안 보여 준다."""
    k = _read_key()
    return f"있음 ({len(k)}자)" if k else "없음"


def respond(instructions: str, payload: Any, schema: dict | None = None,
            *, effort: str | None = None, timeout: int = 20,
            tools: list | None = None, max_output_tokens: int | None = None) -> dict | None:
    """Responses API 를 한 번 부른다. 실패하면 None.

    schema 를 주면 JSON 을 강제하고 파싱해서 돌려준다.
    schema 가 없으면 {"text": 출력문자열} 을 돌려준다.
    """
    global LAST_ERROR
    if DISABLED:
        LAST_ERROR = "DISABLED"           # 일부러 끈 것이다. 오류가 아니다.
        return None
    key = _read_key()
    if not key:
        LAST_ERROR = "NO_KEY"
        return None
    try:
        import requests
    except ImportError:
        LAST_ERROR = "NO_REQUESTS"
        return None

    body: dict[str, Any] = {
        "model": MODEL,
        "store": False,                       # 대화를 OpenAI 쪽에 남기지 않는다
        # 목록 밖의 값을 보내면 400 이 난다. 오타 하나로 챗봇이 통째로 규칙으로
        # 떨어지는 걸 막으려고 여기서 한 번 거른다.
        "reasoning": {"effort": (effort or DEFAULT_EFFORT) if (effort or DEFAULT_EFFORT) in EFFORTS else "low"},
        "instructions": instructions,
        "input": payload if isinstance(payload, str)
                 else json.dumps(payload, ensure_ascii=False),
    }
    if schema:
        body["text"] = {"format": schema}
    if tools:
        body["tools"] = tools
    if max_output_tokens:
        body["max_output_tokens"] = max_output_tokens

    try:
        r = requests.post(f"{API}/responses", timeout=timeout,
                          headers={"Authorization": f"Bearer {key}",
                                   "Content-Type": "application/json"},
                          json=body)
    except Exception as e:                     # noqa: BLE001
        LAST_ERROR = f"NET_{type(e).__name__}"  # 문구에 키가 섞일 수 있어 종류만
        return None

    if r.status_code >= 400:
        # ★ 키는 절대 안 넣는다. OpenAI 의 오류 코드만 덧붙인다 —
        #   401(키 틀림) · 404(모델명 틀림) · 429(한도)를 구분 못 하면
        #   팀원은 "그냥 안 돼요" 밖에 말할 수 없다.
        code = ""
        try:
            code = str(((r.json() or {}).get("error") or {}).get("code") or "")[:40]
        except ValueError:
            code = ""
        LAST_ERROR = f"HTTP_{r.status_code}" + (f"_{code}" if code else "")
        return None

    try:
        raw = r.json()
    except ValueError:
        LAST_ERROR = "BAD_JSON_ENVELOPE"
        return None

    out = raw.get("output_text") or _output_text(raw)
    if not out:
        LAST_ERROR = "EMPTY_OUTPUT"
        return None

    if not schema:
        LAST_ERROR = None
        return {"text": out, "_raw_sources": _sources(raw)}

    try:
        parsed = json.loads(out)
    except (TypeError, ValueError):
        LAST_ERROR = "BAD_JSON_OUTPUT"
        return None
    parsed["_raw_sources"] = _sources(raw)
    LAST_ERROR = None
    return parsed


def _output_text(raw: dict) -> str:
    """output_text 가 없을 때 조각을 이어 붙인다 (llm_analysis.py 와 같은 처리)."""
    parts = []
    for item in raw.get("output") or []:
        for c in item.get("content") or []:
            if isinstance(c, dict) and c.get("type") in ("output_text", "text"):
                parts.append(c.get("text") or "")
    return "".join(parts).strip()


def _sources(raw: dict) -> list[dict]:
    """web_search 도구가 쓴 출처를 긁어낸다. 출처 없는 문장은 화면에 못 올린다."""
    out, seen = [], set()
    for item in raw.get("output") or []:
        for c in item.get("content") or []:
            for a in (c.get("annotations") or []) if isinstance(c, dict) else []:
                url = a.get("url")
                if url and url not in seen:
                    seen.add(url)
                    out.append({"url": url, "title": a.get("title") or url})
    return out


def strict_schema(name: str, properties: dict, required: list[str]) -> dict:
    """Structured Outputs 스키마 껍데기.

    strict 모드는 additionalProperties:false 와 required 전부 나열을 요구한다.
    (llm_analysis.py 가 겪은 것과 같은 제약 — uniqueItems 도 못 쓴다)
    """
    return {"type": "json_schema", "name": name, "strict": True,
            "schema": {"type": "object", "additionalProperties": False,
                       "properties": properties, "required": required}}
