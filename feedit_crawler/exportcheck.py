# -*- coding: utf-8 -*-
"""내보낸 SQL 을 들여다본다 — 진짜 DB 없이 '뭐가 들어가는지' 확인.

★ 왜 필요한가
  [내보내기] 를 눌러도 화면엔 건수만 뜬다. 파일은 17MB 짜리 SQL 이라
  열어 볼 수도 없다. 그래서 "정말 들어간 게 맞나?" 를 확인할 길이 없었다.
  실제로 "적재를 했는데 확인할 방법이 없다"는 말이 나왔다.

  여기서는 파일을 읽어 **표마다 몇 줄이 들어가는지**와 **실제 값 몇 개**를
  뽑아 준다. psql 을 돌리기 전에 눈으로 확인할 수 있게.

★ 01_schema.sql 은 안 커진다
  그 파일은 '표를 만드는 설계도' 라 자료가 아무리 늘어도 크기가 그대로다.
  자료는 03_data.sql 에 쌓인다. 이걸 화면에서 분명히 말해 줘야 한다 —
  스키마 파일 크기가 안 변한다고 적재가 안 된 걸로 오해하기 딱 좋다.
"""
from __future__ import annotations

import re
from pathlib import Path

_INSERT = re.compile(r"^INSERT\s+INTO\s+(\w+)\s*\(([^)]*)\)", re.I)
_CREATE = re.compile(r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)", re.I)
_VALUES = re.compile(r"\bVALUES\b", re.I)


def _rows_in(stmt: str) -> int:
    """한 INSERT 문에 몇 줄이 담겼나.

    ★ 괄호를 그냥 세면 안 된다
      VALUES 뒤에는 값 묶음 말고도 괄호가 널려 있다.
          VALUES ((SELECT id FROM brand WHERE slug='nike'), '이름', …)
          ON CONFLICT (slug) DO UPDATE SET x=COALESCE(…)
      깊이 0 의 여는 괄호를 다 세면 상품 3,773개가 26,286줄로 부풀었다.

      그래서 **VALUES 바로 뒤의 묶음만** 센다. 묶음 하나가 끝나고
      쉼표가 오면 다음 묶음, 아니면 거기서 끝(ON CONFLICT 등)이다.
      따옴표 안의 괄호는 값이지 문법이 아니므로 건너뛴다.
    """
    m = _VALUES.search(stmt)
    if not m:
        return 0
    i, s_len, n = m.end(), len(stmt), 0
    while i < s_len:
        while i < s_len and stmt[i] in " \t":
            i += 1
        if i >= s_len or stmt[i] != "(":
            break                       # 값 묶음이 아니면 끝
        depth, quoted = 0, False
        while i < s_len:
            ch = stmt[i]
            if quoted:
                if ch == "'":
                    # '' 는 따옴표 한 개를 뜻한다. 닫는 게 아니다.
                    if i + 1 < s_len and stmt[i + 1] == "'":
                        i += 1
                    else:
                        quoted = False
            elif ch == "'":
                quoted = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
        n += 1
        while i < s_len and stmt[i] in " \t":
            i += 1
        if i < s_len and stmt[i] == ",":
            i += 1                      # 다음 묶음
            continue
        break
    return n


def scan(export_dir) -> dict:
    """내보낸 폴더를 훑어 '무엇이 얼마나' 를 돌려준다."""
    d = Path(export_dir)
    files, tables, samples = [], {}, {}
    created = set()

    for name in ("01_schema.sql", "02_seed.sql", "03_data.sql"):
        p = d / name
        if not p.exists():
            files.append({"name": name, "exists": False})
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        created |= set(_CREATE.findall(text))
        n_ins, n_rows = 0, 0
        for line in text.split("\n"):
            m = _INSERT.match(line.strip())
            if not m:
                continue
            n_ins += 1
            tbl = m.group(1)
            rows = _rows_in(line) or 1
            n_rows += rows
            t = tables.setdefault(tbl, {"rows": 0, "from": set()})
            t["rows"] += rows
            t["from"].add(name)
            if tbl not in samples:
                cols = [c.strip() for c in m.group(2).split(",")]
                vm = _VALUES.search(line)
                first = line[vm.end():].strip() if vm else ""
                # 첫 괄호 한 덩어리만 잘라 본다 (전체를 보여 주면 화면이 넘친다)
                if first.startswith("("):
                    depth, cut = 0, len(first)
                    for i, ch in enumerate(first):
                        if ch == "(":
                            depth += 1
                        elif ch == ")":
                            depth -= 1
                            if depth == 0:
                                cut = i + 1
                                break
                    first = first[:cut]
                samples[tbl] = {"cols": cols, "value": first[:600]}
        files.append({"name": name, "exists": True,
                      "kb": round(p.stat().st_size / 1024),
                      "at": p.stat().st_mtime,
                      "inserts": n_ins, "rows": n_rows,
                      "creates": len(_CREATE.findall(text))})

    rows = [{"table": k, "rows": v["rows"], "from": sorted(v["from"]),
             **samples.get(k, {})}
            for k, v in sorted(tables.items(), key=lambda x: -x[1]["rows"])]
    empty = sorted(created - set(tables))
    return {"files": files, "tables": rows,
            "total_rows": sum(t["rows"] for t in rows),
            "filled": len(rows), "created": len(created),
            "empty": empty}


def verify(export_dir, schema_path=None) -> dict:
    """문법과 이름을 검사한다. sqlglot 이 없으면 이름 검사만 한다."""
    d = Path(export_dir)
    schema = Path(schema_path or (d / "01_schema.sql"))
    if not schema.exists():
        return {"ok": False, "error": "01_schema.sql 이 없습니다. 먼저 표 만들기를 하세요."}

    cols = {}
    s = schema.read_text(encoding="utf-8")
    for name, body in re.findall(
            r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)\s*\((.*?)\n\);", s, re.S):
        got = set()
        for raw in body.split("\n"):
            code = raw.split("--")[0].strip().rstrip(",")
            m = re.match(r"^([a-z_][a-z0-9_]*)\s+[A-Za-z]", code)
            if m:
                got.add(m.group(1))
        cols[name] = got

    bad_table, bad_col, syntax = [], [], []
    for name in ("02_seed.sql", "03_data.sql"):
        p = d / name
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8",
                                             errors="replace").split("\n"), 1):
            m = _INSERT.match(line.strip())
            if not m:
                continue
            tbl = m.group(1)
            if tbl not in cols:
                if len(bad_table) < 20:
                    bad_table.append({"file": name, "line": i, "table": tbl})
                continue
            for c in [x.strip() for x in m.group(2).split(",")]:
                if c and c not in cols[tbl] and len(bad_col) < 20:
                    bad_col.append({"file": name, "line": i,
                                    "table": tbl, "column": c})

    try:
        import sqlglot
        for name in ("01_schema.sql", "02_seed.sql"):
            p = d / name
            if not p.exists():
                continue
            try:
                sqlglot.parse(p.read_text(encoding="utf-8"), read="postgres")
            except Exception as e:
                syntax.append({"file": name, "error": str(e)[:200]})
        checked = "문법 + 표·칸 이름"
    except ImportError:
        checked = "표·칸 이름 (sqlglot 이 없어 문법 검사는 건너뜀)"

    ok = not (bad_table or bad_col or syntax)
    return {"ok": ok, "checked": checked, "tables": len(cols),
            "bad_table": bad_table, "bad_column": bad_col, "syntax": syntax}


# ── 내보낸 파일 안을 표처럼 들여다보기 ────────────────────────
def _split_tuple(body: str) -> list[str]:
    """VALUES 묶음 하나를 칸별로 자른다.

    따옴표 안의 쉼표는 값이지 구분자가 아니다.
    '나이키, 에어포스' 를 두 칸으로 자르면 안 된다.

    ★ '' 는 따옴표 한 글자를 뜻한다 (SQL 의 이스케이프)
      for 문으로 돌면 두 번째 따옴표를 건너뛸 수가 없어서, 거기서
      문자열이 끝난 걸로 읽힌다. '나이키 에어포스 1 ''07 화이트' 가
      '나이키 에어포스 1 ' 에서 끊기고 뒤가 통째로 한 칸에 뭉쳤다.
      그래서 자리를 직접 옮기는 while 문으로 쓴다.
    """
    out, cur, depth, quoted = [], [], 0, False
    i, n = 0, len(body)
    while i < n:
        ch = body[i]
        if quoted:
            if ch == "'":
                if i + 1 < n and body[i + 1] == "'":
                    cur.append("''")
                    i += 2                  # 두 글자를 한꺼번에 지나간다
                    continue
                quoted = False
            cur.append(ch)
        elif ch == "'":
            quoted = True
            cur.append(ch)
        elif ch == "(":
            depth += 1
            cur.append(ch)
        elif ch == ")":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    if cur:
        out.append("".join(cur).strip())
    return out


def _unquote(v: str) -> dict:
    """SQL 값 하나를 화면용으로."""
    v = v.strip()
    if v.upper() == "NULL":
        return {"kind": "null", "text": ""}
    if v.startswith("'") and v.endswith("'") and len(v) >= 2:
        t = v[1:-1].replace("''", "'")
        return ({"kind": "long", "text": t[:400], "len": len(t)}
                if len(t) > 400 else {"kind": "v", "text": t})
    if v.upper().startswith("(SELECT"):
        # 다른 표를 찾아 넣는 자리. 그대로 보여 주는 게 정직하다.
        return {"kind": "ref", "text": v[:120]}
    return {"kind": "v", "text": v}


def peek(export_dir, table: str, limit: int = 50, offset: int = 0) -> dict:
    """내보낸 SQL 에서 그 표에 들어갈 줄을 뽑아 격자로 보여 준다.

    실제 DB 없이 '넣으면 이렇게 생긴 게 들어간다'를 미리 본다.
    17MB 파일을 매번 통째로 읽으므로 한 표씩만 뽑는다.
    """
    d = Path(export_dir)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table or ""):
        return {"error": "표 이름이 올바르지 않습니다."}
    want = re.compile(r"^INSERT\s+INTO\s+" + re.escape(table) + r"\s*\(([^)]*)\)", re.I)

    cols, rows, seen = [], [], 0
    for name in ("02_seed.sql", "03_data.sql"):
        p = d / name
        if not p.exists():
            continue
        with p.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = want.match(line.strip())
                if not m:
                    continue
                if not cols:
                    cols = [c.strip() for c in m.group(1).split(",")]
                vm = _VALUES.search(line)
                if not vm:
                    continue
                rest = line[vm.end():].strip()
                # 값 묶음 하나씩 (대개 한 줄에 하나)
                i = 0
                while i < len(rest) and rest[i] == "(":
                    depth, quoted, j = 0, False, i
                    while j < len(rest):
                        ch = rest[j]
                        if quoted:
                            if ch == "'":
                                if j + 1 < len(rest) and rest[j + 1] == "'":
                                    j += 1
                                else:
                                    quoted = False
                        elif ch == "'":
                            quoted = True
                        elif ch == "(":
                            depth += 1
                        elif ch == ")":
                            depth -= 1
                            if depth == 0:
                                break
                        j += 1
                    seen += 1
                    if offset < seen <= offset + limit:
                        vals = _split_tuple(rest[i + 1:j])
                        rows.append([_unquote(v) for v in vals])
                    i = j + 1
                    while i < len(rest) and rest[i] in " \t":
                        i += 1
                    if i < len(rest) and rest[i] == ",":
                        i += 1
                        while i < len(rest) and rest[i] in " \t":
                            i += 1
                    else:
                        break
    if not cols:
        return {"table": table, "columns": [], "rows": [], "total": 0,
                "note": "이 표에는 아직 들어갈 자료가 없습니다."}
    return {"table": table, "columns": cols, "rows": rows, "total": seen,
            "limit": limit, "offset": offset}
