# -*- coding: utf-8 -*-
"""표 안을 들여다보는 조회기 — Supabase 테이블 에디터 같은 것.

지금까지는 "상품 3,477건" 같은 숫자만 봤다. 그 안에 실제로 무슨 값이
들어 있는지 보려면 DB 도구를 따로 깔아야 했다. 여기서는 화면에서 바로 본다.

★ 읽기만 한다
  조회 전용 연결(mode=ro)을 따로 연다. 코드가 실수로 UPDATE 를 만들어도
  SQLite 가 거부한다. 화면에는 SQL 을 칠 칸이 아예 없다 —
  공개 서버에 SQL 입력칸을 두는 건 문을 열어 두는 것과 같다.

★ 이름은 반드시 대조한다
  표 이름·칸 이름을 문자열로 이어 붙여 SQL 을 만드는 자리가 있다.
  값은 물음표로 넘길 수 있지만 **이름은 못 넘긴다**. 그래서 실제 DB 에
  있는 이름인지 매번 확인하고, 없으면 거절한다.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

MAX_LIMIT = 200
_SAFE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# 사람이 볼 일 없는 내부 표
_HIDE = {"sqlite_sequence", "sqlite_stat1", "admin_session", "login_attempt"}

# ── 갈래 → 표 ────────────────────────────────────────────────
#  ★ 표를 그냥 죽 늘어놓으면 못 찾는다
#    이름이 영어라 'text_document' 안에 블로그 글이 있다는 걸 알 수가 없다.
#    실제로 7,064건이 들어 있는데 "블로그 데이터가 어디 갔는지 모르겠다"는
#    말이 나왔다. 그래서 하는 일별로 묶고 한글 이름을 붙인다.
GROUPS = [
    ("commerce", "커머스 · 리세일", "상품과 가격 — 크림·무신사·지그재그·에이블리", [
        ("staging_product", "상품", "긁어온 상품 하나하나"),
        ("product_stat", "인기 지표", "순위·후기 수·관심·거래"),
        ("resale_listing", "리세일 시세", "체결가·호가"),
    ]),
    ("social", "소셜 · 여론", "유튜브와 네이버 — 지표 가중치의 55%", [
        ("text_document", "글·댓글", "★ 유튜브 댓글 · 네이버 블로그/카페 글"),
        ("naver_trend", "네이버 검색어 트렌드", "얼마나 찾아보는가"),
        ("yt_channel", "유튜브 채널", "팀이 추려 둔 채널"),
        ("yt_video", "유튜브 영상", "채널에서 받아 온 영상"),
        ("yt_video_stat", "영상 지표", "조회·좋아요·댓글 수"),
    ]),
    ("raw", "원본 · 수집 기록", "되짚어 볼 때 쓰는 것", [
        ("raw_document", "원본 문서", "파싱 전 그대로. 파서가 틀려도 다시 뽑을 수 있음"),
        ("crawl_run", "수집 실행", "언제 돌았고 몇 건 받았나"),
        ("run_quality", "수집 품질", "칸이 얼마나 채워졌나"),
        ("seen_url", "이미 받은 주소", "중복 수집을 막는 기록"),
        ("checkpoint", "이어서 하기", "어디까지 했나"),
        ("problem", "문제 기록", "무엇이 왜 안 됐나"),
    ]),
    ("etc", "설정 · 관리", "", [
        ("fx_rate", "환율", "달러 발매가를 원화로"),
        ("admin_user", "관리자", "누가 들어올 수 있나"),
        ("audit_log", "활동 기록", "누가 무엇을 했나"),
    ]),
]

KO = {t: ko for _, _, _, ts in GROUPS for t, ko, _ in ts}
NOTE = {t: note for _, _, _, ts in GROUPS for t, _, note in ts}
_ORDER = {t: i for i, (t, _, _) in enumerate(
    [x for _, _, _, ts in GROUPS for x in ts])}


class Browser:
    """조회 전용. store 와 같은 파일을 읽기 전용으로 다시 연다."""

    def __init__(self, db_path):
        self.path = Path(db_path)
        self._conn = None

    @property
    def conn(self):
        if self._conn is None:
            # ro = read only. 쓰기 시도는 SQLite 가 막는다.
            self._conn = sqlite3.connect(
                f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _names(self) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            if r[0] not in _HIDE and not r[0].startswith("sqlite_")]

    def _cols(self, table: str) -> list[dict]:
        return [{"name": r[1], "type": r[2] or "", "pk": bool(r[5])}
                for r in self.conn.execute(f"PRAGMA table_info({table})")]

    def tables(self) -> list[dict]:
        """평평한 목록 (예전 화면 호환용)."""
        out = []
        for t in self._names():
            out.append({"name": t, "ko": KO.get(t, ""), "note": NOTE.get(t, ""),
                        "rows": self._count(t), "cols": len(self._cols(t))})
        out.sort(key=lambda x: -x["rows"])
        return out

    def _count(self, t: str) -> int:
        try:
            return self.conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        except sqlite3.DatabaseError:
            return -1

    def groups(self) -> list[dict]:
        """갈래 → 표. 화면이 접었다 폈다 할 수 있게."""
        have = set(self._names())
        used, out = set(), []
        for key, name, why, items in GROUPS:
            rows = []
            for t, ko, note in items:
                if t not in have:
                    continue
                used.add(t)
                rows.append({"name": t, "ko": ko, "note": note,
                             "rows": self._count(t), "cols": len(self._cols(t))})
            if rows:
                out.append({"key": key, "name": name, "why": why, "tables": rows,
                            "rows": sum(r["rows"] for r in rows if r["rows"] > 0)})
        # 목록에 안 적어 둔 표가 생기면 조용히 숨기지 않고 '그 밖' 으로 보여 준다
        rest = [{"name": t, "ko": "", "note": "", "rows": self._count(t),
                 "cols": len(self._cols(t))} for t in sorted(have - used)]
        if rest:
            out.append({"key": "other", "name": "그 밖", "why": "아직 분류 안 한 표",
                        "tables": rest,
                        "rows": sum(r["rows"] for r in rest if r["rows"] > 0)})
        return out

    def rows(self, table: str, *, q: str = "", sort: str = "", desc: bool = True,
             limit: int = 50, offset: int = 0) -> dict:
        if not _SAFE.match(table or "") or table not in self._names():
            return {"error": f"'{table}' 이라는 표가 없습니다."}
        cols = self._cols(table)
        names = {c["name"] for c in cols}

        where, args = "", []
        if q.strip():
            # 글자가 든 칸에서만 찾는다. 숫자 칸에 LIKE 를 걸면 느리기만 하다.
            targets = [c["name"] for c in cols
                       if "CHAR" in c["type"].upper() or "TEXT" in c["type"].upper()
                       or not c["type"]]
            if targets:
                where = " WHERE (" + " OR ".join(
                    f"{c} LIKE ?" for c in targets) + ")"
                args = [f"%{q.strip()}%"] * len(targets)

        order = ""
        if sort and sort in names:
            order = f" ORDER BY {sort} {'DESC' if desc else 'ASC'}"
        elif any(c["pk"] for c in cols):
            pk = next(c["name"] for c in cols if c["pk"])
            order = f" ORDER BY {pk} DESC"

        total = self.conn.execute(
            f"SELECT count(*) FROM {table}{where}", args).fetchone()[0]
        lim = max(1, min(int(limit), MAX_LIMIT))
        got = self.conn.execute(
            f"SELECT * FROM {table}{where}{order} LIMIT ? OFFSET ?",
            args + [lim, max(0, int(offset))]).fetchall()

        return {"table": table, "ko": KO.get(table, ""),
                "note": NOTE.get(table, ""),
                "columns": cols, "total": total,
                "rows": [{k: _cell(r[k]) for k in r.keys()} for r in got],
                "limit": lim, "offset": max(0, int(offset))}


def _cell(v):
    """화면으로 보낼 값. 너무 긴 건 잘라서 보낸다 —
    원본 payload 하나가 수백 KB 라 그대로 보내면 화면이 멈춘다."""
    if isinstance(v, bytes):
        return {"kind": "bin", "text": f"({len(v):,} 바이트)"}
    s = "" if v is None else str(v)
    if len(s) > 400:
        return {"kind": "long", "text": s[:400], "len": len(s)}
    return {"kind": "null" if v is None else "v", "text": s}
