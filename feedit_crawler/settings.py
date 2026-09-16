"""
설정·열쇠 읽기 — .env 한 곳에서만 읽는다.

열쇠를 코드에 박으면 깃에 올라가고, 올라가면 되돌릴 수 없다.
(깃 기록에서 지워도 이미 받아 간 사람은 계속 쓴다.)
그래서 열쇠는 .env 에만 두고, .gitignore 로 막아 둔다.

★ 없으면 조용히 꺼진다
  키가 없다고 크롤러 전체가 죽으면 안 된다. 유튜브 키가 없으면
  유튜브 수집만 안 하고 나머지는 그대로 돈다. 대신 화면에는
  '키가 없어 꺼져 있음'이라고 분명히 적는다 — 조용히 안 도는 게 제일 나쁘다.

★ python-dotenv 를 안 쓴다
  줄 몇 개면 되는 일에 의존성을 늘리지 않는다. 이 파일이 그 줄 몇 개다.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
_loaded = False


def load_env(path: str | Path = ".env") -> dict:
    """.env 를 읽어 os.environ 에 넣는다. 이미 있는 값은 안 덮는다.

    안 덮는 이유: 진짜 배포에서는 환경변수로 주입하는 게 정석이라
    파일이 그걸 밀어내면 안 된다.
    """
    global _loaded
    out = {}
    p = Path(path)
    if not p.exists():
        _loaded = True
        return out
    for raw in p.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = _LINE.match(raw)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k] = v
        os.environ.setdefault(k, v)
    _loaded = True
    return out


def get(key: str, default: str = "") -> str:
    if not _loaded:
        load_env()
    return (os.environ.get(key) or default).strip()


def has(key: str) -> bool:
    return bool(get(key))


def mask(key: str) -> str:
    """화면에 보여 줄 때 쓴다. 'AIza…SV' 처럼 앞뒤만.

    전체를 보여 주면 화면 캡처 한 장으로 열쇠가 샌다.
    """
    v = get(key)
    if not v:
        return ""
    if len(v) <= 8:
        return v[0] + "…" + v[-1]
    return f"{v[:4]}…{v[-2:]} ({len(v)}자)"


# 어떤 열쇠가 필요한지는 keystore.SPECS 가 갖고 있다.
# 화면이 그리는 목록과 저장 로직을 한 곳에 두는 편이 안 어긋난다.
