"""
문제 기록 — 왜 안 됐는지 사람 말로 남긴다.

지금까지 실패는 로그 한 줄로 흘러가 버렸다. `HTTPError 403` 이나
`AttributeError: 'NoneType' object has no attribute 'text'` 를 보고
비전공자가 할 수 있는 일은 없다.

여기서는 세 가지를 같이 남긴다.
    무엇이  — 사람이 읽는 한 문장
    왜     — 짐작되는 원인
    어떻게  — 지금 눌러 볼 수 있는 다음 행동

★ 원인을 '분류'하는 게 핵심이다
  같은 403 이라도 robots 가 막은 것과 열쇠가 틀린 것은 할 일이 전혀 다르다.
  분류해 두면 "이 사이트는 늘 이 문제"라는 것도 한눈에 보인다.

★ 기술 원문도 같이 둔다
  사람 말로만 남기면 개발자가 고칠 때 단서가 없다. 접어 두고 필요할 때 편다.
"""

from __future__ import annotations

import re
import traceback
from datetime import datetime, timezone

UTC = timezone.utc

DDL = """
CREATE TABLE IF NOT EXISTS problem (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  at          TEXT NOT NULL,
  source_code TEXT,
  where_      TEXT,                  -- 수집 · 가져오기 · 내보내기 · 열쇠 …
  kind        TEXT NOT NULL,         -- 아래 KINDS 의 열쇠
  title       TEXT NOT NULL,         -- 사람이 읽는 한 문장
  detail      TEXT,                  -- 무엇을 하다가
  raw         TEXT,                  -- 기술 원문 (접어 둔다)
  url         TEXT,
  resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_prob ON problem (id DESC);
CREATE INDEX IF NOT EXISTS ix_prob_src ON problem (source_code, id DESC);
"""

# ── 원인 종류 ─────────────────────────────────────────────────
#  fix 는 '지금 눌러 볼 수 있는 것'이어야 한다.
#  "설정을 확인하세요" 같은 말은 아무 도움이 안 된다.
KINDS = {
    "robots": {
        "name": "사이트가 막음",
        "why": "그 사이트의 robots.txt 가 우리 같은 프로그램의 접근을 금지했습니다.",
        "fix": "규칙이라 우회하지 않습니다. [가져오기] 탭에서 브라우저로 저장한 "
               "파일을 넣으면 같은 자료를 모을 수 있습니다.",
        "level": "info",
    },
    "blocked": {
        "name": "차단당함",
        "why": "너무 자주 요청해서 사이트가 우리를 막았을 수 있습니다.",
        "fix": "[설정] 에서 수집 주기를 늘리고 하루 쉬어 보세요. "
               "그래도 막히면 그 사이트는 저장본 방식으로 돌리세요.",
        "level": "bad",
    },
    "not_found": {
        "name": "주소가 없음",
        "why": "그 주소가 사라졌거나 처음부터 틀렸습니다 (404).",
        "fix": "[설정] 에서 그 주소를 브라우저에 붙여 넣어 열리는지 보세요. "
               "안 열리면 새 주소로 바꿔 주세요.",
        "level": "bad",
    },
    "selector": {
        "name": "화면이 바뀜",
        "why": "페이지는 열렸는데 상품을 못 찾았습니다. "
               "사이트가 화면 구조를 바꾼 것입니다.",
        "fix": "[탐색기] 에서 그 페이지를 다시 읽히면 새 셀렉터를 찾아 줍니다.",
        "level": "bad",
    },
    "empty": {
        "name": "값이 비어서 옴",
        "why": "상품은 찾았는데 이름이나 가격이 비어 있습니다. "
               "셀렉터 하나만 어긋났을 때 이렇게 됩니다.",
        "fix": "[데이터] 탭에서 그 상품의 상세를 열어 어느 칸이 비었는지 보고, "
               "[탐색기] 로 그 칸만 다시 잡으세요.",
        "level": "warn",
    },
    "js_render": {
        "name": "화면을 못 그림",
        "why": "자바스크립트로 그리는 사이트라 브라우저가 필요한데 "
               "브라우저가 준비되지 않았습니다.",
        "fix": "서버에서 `playwright install chromium` 을 한 번 실행해 주세요.",
        "level": "bad",
    },
    "network": {
        "name": "인터넷이 안 닿음",
        "why": "서버가 바깥으로 나가지 못했습니다.",
        "fix": "서버의 인터넷 연결과 방화벽을 확인해 주세요. "
               "회사 네트워크라면 프록시 설정이 필요할 수 있습니다.",
        "level": "bad",
    },
    "timeout": {
        "name": "응답이 너무 느림",
        "why": "사이트가 제때 답하지 않았습니다. 일시적일 때가 많습니다.",
        "fix": "잠시 뒤 다시 해 보세요. 계속 그러면 그 사이트가 느려진 것입니다.",
        "level": "warn",
    },
    "api_key": {
        "name": "열쇠 문제",
        "why": "API 키가 없거나, 틀렸거나, 해당 기능이 안 켜져 있습니다.",
        "fix": "[API] 탭에서 키를 확인하고 '연결 시험' 을 눌러 보세요.",
        "level": "bad",
    },
    "quota": {
        "name": "오늘 몫을 다 씀",
        "why": "그 API 의 하루 사용량을 다 썼습니다.",
        "fix": "내일 다시 됩니다. 급하면 검색어 수를 줄이세요.",
        "level": "warn",
    },
    "config": {
        "name": "설정이 잘못됨",
        "why": "설정 값에 빠진 것이 있거나 형식이 맞지 않습니다.",
        "fix": "[설정] 탭에서 그 사이트를 열어 빨갛게 표시된 칸을 채워 주세요.",
        "level": "bad",
    },
    "unknown": {
        "name": "알 수 없는 오류",
        "why": "예상하지 못한 문제입니다.",
        "fix": "아래 '기술 정보' 를 펼쳐 개발자에게 전달해 주세요.",
        "level": "bad",
    },
}


# ── 오류를 종류로 나눈다 ──────────────────────────────────────
#  위에서부터 먼저 맞는 것이 이긴다. 구체적인 것을 위에 둔다.
_RULES: list[tuple[str, str]] = [
    ("robots",    r"robots|RenderBlocked|수집이 금지|Disallow"),
    ("quota",     r"quota|할당량"),
    ("api_key",   r"API[_ ]?KEY|api key|열쇠|거부됐|invalid[_ ]?key|401|unauthorized"),
    ("js_render", r"playwright|chromium|Executable doesn't exist|browser.*not.*install"),
    ("blocked",   r"\b(403|429)\b|too many requests|blocked|차단|captcha|cloudflare"),
    ("not_found", r"\b404\b|not found|없는 페이지"),
    ("timeout",   r"timeout|timed out|시간 초과"),
    ("network",   r"urlopen|connection|getaddrinfo|name or service|ssl|network|dns"),
    ("selector",  r"셀렉터|selector|카드를 못|0 ?건|찾지 못했습니다|no such element"),
    ("empty",     r"비어 있|빈 값|empty"),
    ("config",    r"yaml|설정|config|KeyError|missing"),
]


def classify(text: str) -> str:
    t = str(text or "")
    for kind, pat in _RULES:
        if re.search(pat, t, re.I):
            return kind
    return "unknown"


class Problems:
    def __init__(self, store):
        self.store = store
        with store._lock:
            store._conn.executescript(DDL)
            store._conn.commit()

    def add(self, *, title: str, source_code: str = "", where: str = "",
            kind: str = "", detail: str = "", raw: str = "",
            url: str = "", exc: BaseException | None = None) -> dict:
        """문제 하나를 남긴다.

        exc 를 주면 종류를 알아서 나누고 원문도 담는다.
        """
        if exc is not None:
            raw = raw or "".join(traceback.format_exception_only(
                type(exc), exc)).strip()
            if not title:
                title = str(exc)[:160]
        kind = kind or classify(f"{title} {detail} {raw}")
        with self.store._lock:
            cur = self.store._conn.execute(
                "INSERT INTO problem (at, source_code, where_, kind, title, "
                "detail, raw, url) VALUES (?,?,?,?,?,?,?,?)",
                (datetime.now(UTC).isoformat()[:19], source_code or None,
                 where or None, kind, title[:300], detail or None,
                 (raw or "")[:4000] or None, url or None))
            self.store._conn.commit()
        return {"id": cur.lastrowid, "kind": kind, **KINDS.get(kind, KINDS["unknown"])}

    def recent(self, limit: int = 60, source_code: str = "",
               only_open: bool = False) -> list[dict]:
        q = "SELECT * FROM problem WHERE 1=1"
        args: list = []
        if source_code and source_code != "all":
            q += " AND source_code = ?"
            args.append(source_code)
        if only_open:
            q += " AND resolved_at IS NULL"
        q += " ORDER BY id DESC LIMIT ?"
        args.append(min(limit, 300))
        with self.store._lock:
            rows = [dict(r) for r in self.store._conn.execute(q, args)]
        for r in rows:
            k = KINDS.get(r["kind"], KINDS["unknown"])
            r["kind_name"] = k["name"]
            r["why"] = k["why"]
            r["fix"] = k["fix"]
            r["level"] = k["level"]
        return rows

    def summary(self) -> dict:
        """종류별로 몇 건인지. 무엇부터 손댈지 정하는 데 쓴다."""
        with self.store._lock:
            rows = self.store._conn.execute(
                "SELECT kind, source_code, count(*) n, max(at) last "
                "FROM problem WHERE resolved_at IS NULL "
                "GROUP BY kind, source_code ORDER BY n DESC").fetchall()
        out = []
        for r in rows:
            k = KINDS.get(r["kind"], KINDS["unknown"])
            out.append({"kind": r["kind"], "name": k["name"], "level": k["level"],
                        "source_code": r["source_code"], "n": r["n"],
                        "last": r["last"], "fix": k["fix"]})
        return {"groups": out, "total": sum(g["n"] for g in out)}

    # ── 스스로 접히게 ────────────────────────────────────────
    #  ★ 고쳤는데도 화면에 계속 떠 있으면, 고친 사람이
    #    "안 고쳐졌나?" 하고 다시 헤맨다. 실제로 그랬다 —
    #    브라우저를 깔았는데도 '브라우저가 준비되지 않았습니다' 가
    #    그대로 떠 있어서 몇 번을 다시 확인해야 했다.
    #
    #  원인이 사라졌는지 **지금 확인할 수 있는 것**은 스스로 접는다.
    #  확인할 수 없는 것(셀렉터가 맞는지 등)은 그대로 둔다 —
    #  함부로 접으면 진짜 문제를 숨기게 된다.
    CHECKS = {
        # 브라우저가 깔렸는지는 지금 바로 볼 수 있다
        "js_render": lambda: _browser_ok(),
    }

    def auto_resolve(self) -> list[str]:
        """고쳐진 게 확실한 문제를 접는다. 접은 종류를 돌려준다."""
        closed = []
        with self.store._lock:
            kinds = [r[0] for r in self.store._conn.execute(
                "SELECT DISTINCT kind FROM problem WHERE resolved_at IS NULL")]
        for k in kinds:
            check = self.CHECKS.get(k)
            if not check:
                continue
            try:
                if check():
                    n = self.resolve(kind=k)
                    if n:
                        closed.append(f"{KINDS[k]['name']} {n}건")
            except Exception:
                continue          # 확인 자체가 실패하면 그냥 둔다
        return closed

    def resolve(self, kind: str = "", source_code: str = "") -> int:
        """'이건 해결했다' 로 접는다. 지우지는 않는다 — 기록은 남는 게 낫다."""
        q = "UPDATE problem SET resolved_at=? WHERE resolved_at IS NULL"
        args: list = [datetime.now(UTC).isoformat()[:19]]
        if kind:
            q += " AND kind=?"
            args.append(kind)
        if source_code and source_code != "all":
            q += " AND source_code=?"
            args.append(source_code)
        with self.store._lock:
            cur = self.store._conn.execute(q, args)
            self.store._conn.commit()
        return cur.rowcount


def _browser_ok() -> bool:
    """브라우저가 지금 준비돼 있나."""
    from .renderer import installed
    return installed()
