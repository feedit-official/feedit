"""우리가 밝히는 신분을 한 곳에서 만든다.

왜 있는가
---------
봇 이름이 설정 yaml 4곳과 파이썬 5곳에 흩어져 있었다. 사이트가 이름을
지정해 주면 아홉 군데를 다 고쳐야 하고, 그 중 하나만 놓쳐도 **놓친 그 경로만
옛 이름으로 나간다**. 그런 종류의 실수는 티가 안 난다 — 수집은 계속 되고,
어느 날 그 경로만 차단당한다.

그래서 이름은 `config/identity.yaml` 한 곳에서만 읽는다. 이 파일은 그 값을
용도별 User-Agent 로 조립해 주는 것뿐이다.

쓰는 법
-------
    from .identity import crawler_ua, browser_ua, plain_ua, expand

    crawler_ua()          # 일반 요청용   FEEDiTBot/1.0 (+https://…; contact …)
    browser_ua()          # 렌더링용     Mozilla/5.0 … Chrome/126 … FEEDiTBot/1.0 (+…)
    browser_ua(mobile=True)
    plain_ua()            # 짧은 것      Mozilla/5.0 (compatible; FEEDiTBot/1.0)

설정 yaml 안에서는 자리표를 쓴다. `SiteConfig` 가 읽을 때 채워 준다.

    user_agent: "{bot} (+{homepage}; authorized crawler; contact {contact})"

급할 때는 환경변수로 덮어쓸 수 있다 — `FEEDIT_BOT_NAME=NewBot/2.0`.

의존성
------
표준 라이브러리와 yaml 뿐이다. 다른 feedit_crawler 모듈을 부르지 않는다.
(부르면 import 고리가 생긴다. fetcher·renderer·adapter 가 전부 이걸 쓴다.)
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "identity.yaml"

# 설정 파일이 없어도 죽지 않게 하는 최소값.
_FALLBACK = {
    "bot_name": "Claude-User-Agent/1.0",
    "contact": ".",
    "homepage": ".",
    "browser_prefix": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "mobile_prefix": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 "
        "Safari/604.1"
    ),
}

_cache: dict | None = None


def load(refresh: bool = False) -> dict:
    """신분 설정을 읽는다. 한 번 읽고 기억한다."""
    global _cache
    if _cache is not None and not refresh:
        return _cache

    got = dict(_FALLBACK)
    try:
        raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        for k in _FALLBACK:
            v = str(raw.get(k) or "").strip()
            if v:
                got[k] = v
    except FileNotFoundError:
        pass
    except (OSError, yaml.YAMLError):
        # 설정이 깨졌다고 수집을 멈출 이유는 없다. 기본값으로 간다.
        pass

    env = (os.environ.get("FEEDIT_BOT_NAME") or "").strip()
    if env:
        got["bot_name"] = env

    _cache = got
    return got


# ── 용도별 신분 ────────────────────────────────────────────────
def bot_name() -> str:
    return load()["bot_name"]


def crawler_ua() -> str:
    """일반 HTTP 요청. robots.txt 판정도 이 이름으로 한다."""
    c = load()
    return f"{c['bot_name']} (+{c['homepage']}; authorized crawler; contact {c['contact']})"


def browser_ua(mobile: bool = False) -> str:
    """브라우저로 그려서 받아올 때. 크로미움 신분 뒤에 봇 이름을 붙인다."""
    c = load()
    prefix = c["mobile_prefix"] if mobile else c["browser_prefix"]
    return f"{prefix} {c['bot_name']} (+contact {c['contact']})"


def plain_ua() -> str:
    """이미지 한 장 받아오는 것처럼 가벼운 요청."""
    return f"Mozilla/5.0 (compatible; {load()['bot_name']})"


# ── 설정 yaml 안의 자리표 채우기 ────────────────────────────────
_KEYS = ("bot", "contact", "homepage", "browser_prefix", "mobile_prefix")


def expand(text):
    """`{bot}` 같은 자리표를 실제 값으로 바꾼다.

    문자열이 아니거나 자리표가 없으면 그대로 돌려준다. 모르는 자리표
    (`{keyword}` 처럼 주소 틀에 쓰이는 것)는 건드리지 않는다 — 그래서
    format() 이 아니라 하나씩 갈아 끼운다.
    """
    if not isinstance(text, str) or "{" not in text:
        return text
    c = load()
    out = text
    for key in _KEYS:
        holder = "{" + key + "}"
        if holder in out:
            out = out.replace(holder, c["bot_name" if key == "bot" else key])
    return out


if __name__ == "__main__":
    c = load()
    print(f"설정 파일 : {CONFIG_PATH}")
    print(f"봇 이름   : {c['bot_name']}"
          + ("   (환경변수 FEEDIT_BOT_NAME 로 덮어씀)"
             if os.environ.get("FEEDIT_BOT_NAME") else ""))
    print()
    print("실제로 나가는 이름")
    print(f"  일반 요청   {crawler_ua()}")
    print(f"  렌더링      {browser_ua()}")
    print(f"  렌더링(모바일) {browser_ua(mobile=True)}")
    print(f"  가벼운 요청 {plain_ua()}")
