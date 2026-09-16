"""플랫폼 PostgreSQL 생성·적재 관리.

로컬 PostgreSQL과 AWS RDS가 같은 길을 탄다. 비밀번호는 저장하지 않고 호출
중인 프로세스의 PGPASSWORD로만 넘긴다. 셸을 사용하지 않아 입력값이 명령으로
해석되지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$-]{0,62}$")
RDS_GROUPS = {
    "collection": ["source", "crawl_run", "raw_document"],
    "dictionary": ["dictionary_term", "term_alias", "category", "style", "item", "detail", "material", "color", "tpo", "term_relation", "term_candidate", "brand", "brand_alias", "category_alias"],
    "commerce": ["product", "product_source"],
    "snapshot": ["product_source_snapshot", "resale_snapshot", "content_snapshot"],
    "content": ["content_profile", "content_item"],
    "analysis": ["text_document", "term_metric_daily", "term_assoc_daily"],
    "app": ["app_user", "user_taste", "user_event", "user_saved_item", "vote_card", "vote_ballot", "chat_session", "chat_message"],
}

# 연결 확인에서 받은 비밀번호는 파일에 쓰지 않고 서버 프로세스 메모리에만 둔다.
# 표 보기/AWS 자동 적재는 별도 HTTP 요청이므로 이 짧은 세션 연결 정보가 없으면
# 바로 다음 요청에서 인증을 잃어 "연결은 됐는데 표가 안 보이는" 상태가 된다.
_SESSION_CONNECTION: dict = {}


@dataclass
class Config:
    host: str = ""
    port: int = 5432
    user: str = ""
    database: str = "feedit"
    sslmode: str = "prefer"
    password: str = ""

    @classmethod
    def from_dict(cls, raw: dict | None):
        raw = raw or {}
        cfg = cls(
            host=str(raw.get("host") or "").strip(),
            port=int(raw.get("port") or 5432),
            user=str(raw.get("user") or "").strip(),
            database=str(raw.get("database") or "feedit").strip(),
            sslmode=str(raw.get("sslmode") or "prefer").strip(),
            password=str(raw.get("password") or ""),
        )
        if not 1 <= cfg.port <= 65535:
            raise ValueError("포트는 1~65535여야 합니다.")
        for label, value in (("사용자", cfg.user), ("DB 이름", cfg.database)):
            if value and not _IDENT.fullmatch(value):
                raise ValueError(f"{label}에 쓸 수 없는 문자가 있습니다.")
        if cfg.sslmode not in ("disable", "allow", "prefer", "require",
                               "verify-ca", "verify-full"):
            raise ValueError("SSL 모드가 올바르지 않습니다.")
        return cfg

    def public(self):
        return {"host": self.host, "port": self.port, "user": self.user,
                "database": self.database, "sslmode": self.sslmode,
                "password_set": bool(self.password)}


# ── psql 찾기 ──────────────────────────────────────────────────
#  ★ shutil.which 만으로는 모자란다.
#    Homebrew 의 postgresql@17·libpq 는 keg-only 라 /opt/homebrew/bin 에 링크가
#    안 생길 수 있다. 그런 경우 사람은 .zshrc 에 PATH 를 넣어 쓰는데, 그러면
#    **그 터미널에서만** 잡힌다. 서버를 런치에이전트나 다른 셸에서 띄우면
#    PATH 가 달라 psql 을 못 찾고, 깔려 있는데도 "psql 이 없습니다" 가 뜬다.
#    (2026-08-31 사용자 맥이 정확히 이 모양이었다:
#     /opt/homebrew/opt/postgresql@17/bin/psql — opt 경로 직접)
#  그래서 PATH 에 없으면 흔한 설치 자리를 직접 뒤진다.
EXTRA_BIN_GLOBS = (
    "/opt/homebrew/opt/postgresql@*/bin",     # 애플 실리콘 · 버전별
    "/opt/homebrew/opt/libpq/bin",
    "/opt/homebrew/bin",
    "/usr/local/opt/postgresql@*/bin",        # 인텔 맥
    "/usr/local/opt/libpq/bin",
    "/usr/local/bin",
    "/Library/PostgreSQL/*/bin",              # 공식 설치본
    "/Applications/Postgres.app/Contents/Versions/*/bin",
)


def find_tool(name: str) -> str | None:
    """psql 같은 도구의 실제 경로. PATH 를 먼저 보고, 없으면 흔한 자리를 뒤진다."""
    got = shutil.which(name)
    if got:
        return got
    import glob as _glob
    seen = []
    for pattern in EXTRA_BIN_GLOBS:
        seen.extend(_glob.glob(pattern))
    # 버전 폴더가 여럿이면 최신(사전순 뒤)을 쓴다
    for d in sorted(set(seen), reverse=True):
        cand = Path(d) / name
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return None


class PlatformDB:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.config_path = self.root / "data" / "platform_db.json"

    def saved(self) -> dict:
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            return {}

    def config(self, incoming: dict | None = None) -> Config:
        raw = {**self.saved(), **_SESSION_CONNECTION, **(incoming or {})}
        return Config.from_dict(raw)

    def remember_session(self, incoming: dict | None = None):
        """성공한 연결 정보만 메모리에 보관한다. 프로세스 종료 시 사라진다."""
        cfg = Config.from_dict({**self.saved(), **(incoming or {})})
        _SESSION_CONNECTION.clear()
        _SESSION_CONNECTION.update({
            "host": cfg.host, "port": cfg.port, "user": cfg.user,
            "database": cfg.database, "sslmode": cfg.sslmode,
            "password": cfg.password,
        })

    def save_public(self, cfg: Config):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(
            {k: v for k, v in cfg.public().items() if k != "password_set"},
            ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def tools() -> dict:
        return {name: find_tool(name) for name in ("psql", "createdb", "dropdb")}

    def _env(self, cfg: Config):
        env = os.environ.copy()
        env["PGCONNECT_TIMEOUT"] = "8"
        env["PGSSLMODE"] = cfg.sslmode
        if cfg.password:
            env["PGPASSWORD"] = cfg.password
        return env

    def _conn_args(self, cfg: Config, database: str | None = None):
        out = []
        if cfg.host:
            out += ["-h", cfg.host]
        if cfg.port:
            out += ["-p", str(cfg.port)]
        if cfg.user:
            out += ["-U", cfg.user]
        if database:
            out += ["-d", database]
        return out

    # psql·createdb·dropdb 는 비밀번호가 없으면 터미널에서 물어본다.
    # 서버가 부르는 자리엔 사람이 없어서, 물어보는 순간 타임아웃까지 매달린다.
    # (실제로 자동 적재가 매번 900초를 버리고 "작업 시간이 초과됐습니다" 로 끝났다.)
    # -w 를 주면 묻지 않고 바로 실패해서, 무엇이 없는지 즉시 알 수 있다.
    NO_PROMPT = {"psql": "-w", "createdb": "-w", "dropdb": "-w"}

    def _run(self, args: list[str], cfg: Config, timeout=120) -> dict:
        # ★ 이름 대신 찾아낸 실제 경로로 부른다.
        #   PATH 에 없고 /opt/homebrew/opt/... 에만 있는 경우가 흔하다.
        #   tools() 는 찾아 놓고 실행은 이름으로 하면, 찾았는데도 못 여는 꼴이 된다.
        tool = args[0]
        args = [find_tool(tool) or tool, *args[1:]]
        flag = self.NO_PROMPT.get(tool)
        if flag and flag not in args:
            args.insert(1, flag)
        try:
            p = subprocess.run(args, env=self._env(cfg), text=True,
                               capture_output=True, timeout=timeout, check=False)
        except FileNotFoundError:
            return {"ok": False, "error": f"{args[0]} 명령을 찾을 수 없습니다."}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"{args[0]} 작업 시간이 초과됐습니다."}
        # 비밀번호는 args에 없지만 서버 오류가 길 수 있어 마지막 부분만 보여 준다.
        err = (p.stderr or "").strip()
        out = (p.stdout or "").strip()
        return {"ok": p.returncode == 0, "code": p.returncode,
                "output": out[-2000:], "error": err[-2000:]}

    def _scalar(self, cfg: Config, database: str, sql: str) -> dict:
        return self._run(["psql", *self._conn_args(cfg, database),
                          "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1",
                          "-c", sql], cfg, timeout=20)

    def state(self, incoming: dict | None = None) -> dict:
        cfg = self.config(incoming)
        tools = self.tools()
        if not tools["psql"]:
            return {"ok": False, "config": cfg.public(), "tools": tools,
                    "error": "psql이 설치되지 않았습니다."}
        ping = self._scalar(cfg, "postgres", "SELECT 1")
        if not ping["ok"]:
            return {"ok": False, "config": cfg.public(), "tools": tools,
                    "reachable": False, "error": ping["error"]}
        # database는 정규식 검증을 통과한 값이라 SQL literal로 안전하게 넣을 수 있다.
        exists = self._scalar(cfg, "postgres",
                              f"SELECT 1 FROM pg_database WHERE datname='{cfg.database}'")
        db_exists = exists["ok"] and exists["output"].strip() == "1"
        tables = 0
        schema = False
        if db_exists:
            got = self._scalar(cfg, cfg.database,
                               "SELECT count(*) FROM information_schema.tables "
                               "WHERE table_schema IN ('collection','dictionary','commerce','content','snapshot','analysis','app')")
            if got["ok"]:
                try:
                    tables = int(got["output"].strip() or 0)
                except ValueError:
                    tables = 0
            schema = tables > 0
        return {"ok": True, "config": cfg.public(), "tools": tools,
                "reachable": True, "database_exists": db_exists,
                "schema_installed": schema, "tables": tables}

    @staticmethod
    def _qualified(table: str) -> tuple[str, str]:
        bits = str(table).split(".")
        if len(bits) != 2 or bits[0] not in RDS_GROUPS or bits[1] not in RDS_GROUPS[bits[0]]:
            raise ValueError("허용된 FEEDiT RDS 테이블이 아닙니다.")
        return bits[0], bits[1]

    def tables(self, incoming: dict | None = None) -> dict:
        cfg = self.config(incoming)
        groups, total, success, first_error = [], 0, 0, ""
        for schema, names in RDS_GROUPS.items():
            rows = []
            for name in names:
                got = self._scalar(cfg, cfg.database, f'SELECT count(*) FROM "{schema}"."{name}"')
                if got.get("ok"):
                    success += 1
                elif not first_error:
                    first_error = got.get("error") or "RDS 표를 읽지 못했습니다."
                try: count = int(got.get("output") or 0) if got.get("ok") else -1
                except ValueError: count = -1
                total += max(0, count)
                rows.append({"name": f"{schema}.{name}", "ko": name, "rows": count,
                             "cols": 0, "exists": bool(got.get("ok"))})
            groups.append({"key": schema, "name": schema.upper(), "why": "AWS RDS",
                           "tables": rows, "rows": sum(max(0, x["rows"]) for x in rows)})
        if not success:
            return {"ok": False, "error": first_error, "groups": groups,
                    "tables": [t for g in groups for t in g["tables"]]}
        return {"ok": True, "tables": [t for g in groups for t in g["tables"]],
                "groups": groups, "rows": total}

    def rows(self, table: str, limit: int = 50, offset: int = 0,
             incoming: dict | None = None) -> dict:
        schema, name = self._qualified(table)
        cfg = self.config(incoming)
        limit, offset = min(max(int(limit), 1), 200), max(int(offset), 0)
        cols_r = self._scalar(cfg, cfg.database,
            "SELECT string_agg(column_name || ':' || data_type, E'\\n' ORDER BY ordinal_position) FROM information_schema.columns "
            f"WHERE table_schema='{schema}' AND table_name='{name}'")
        columns = []
        for line in cols_r.get("output", "").splitlines():
            col, _, typ = line.partition(":")
            if col: columns.append({"name": col, "type": typ, "pk": col == "id"})
        count_r = self._scalar(cfg, cfg.database, f'SELECT count(*) FROM "{schema}"."{name}"')
        data_r = self._scalar(cfg, cfg.database,
            f'''SELECT COALESCE(json_agg(x),'[]'::json)::text FROM (SELECT * FROM "{schema}"."{name}" ORDER BY 1 DESC LIMIT {limit} OFFSET {offset}) x''')
        if not data_r.get("ok"):
            return {"ok": False, "error": data_r.get("error")}
        try: raw_data = json.loads(data_r.get("output") or "[]")
        except ValueError: raw_data = []
        data = []
        for raw in raw_data:
            row = {}
            for key, value in raw.items():
                if value is None:
                    row[key] = {"kind": "null", "text": ""}
                else:
                    text = (json.dumps(value, ensure_ascii=False)
                            if isinstance(value, (dict, list)) else str(value))
                    row[key] = {"kind": "value", "text": text,
                                "len": len(text) if len(text) > 120 else 0}
            data.append(row)
        try: total = int(count_r.get("output") or 0)
        except ValueError: total = 0
        return {"ok": True, "table": table, "columns": columns, "rows": data,
                "total": total, "limit": limit, "offset": offset, "note": "AWS RDS 읽기 전용"}

    def create_database(self, cfg: Config) -> dict:
        state = self.state(cfg.public() | {"password": cfg.password})
        if not state.get("ok"):
            return state
        if state["database_exists"]:
            return {"ok": True, "already": True, **state}
        r = self._run(["createdb", *self._conn_args(cfg), cfg.database], cfg, timeout=30)
        if not r["ok"]:
            return r
        return {"ok": True, "created": True, **self.state(
            cfg.public() | {"password": cfg.password})}

    def run_file(self, cfg: Config, path: Path, timeout=600) -> dict:
        if not path.is_file():
            return {"ok": False, "error": f"{path.name} 파일이 없습니다."}
        return self._run(["psql", *self._conn_args(cfg, cfg.database), "-X",
                          "-v", "ON_ERROR_STOP=1", "-f", str(path)],
                         cfg, timeout=timeout)

    def install_and_load(self, incoming: dict | None = None) -> dict:
        cfg = self.config(incoming)
        self.save_public(cfg)
        created = self.create_database(cfg)
        if not created.get("ok"):
            return created
        state = self.state(cfg.public() | {"password": cfg.password})
        steps = []
        if not state.get("schema_installed"):
            r = self.run_file(cfg, self.root / "export" / "01_schema.sql")
            steps.append({"file": "01_schema.sql", **r})
            if not r["ok"]:
                return {"ok": False, "steps": steps, "error": r["error"]}
        else:
            steps.append({"file": "01_schema.sql", "ok": True, "skipped": True})
        # 이미 운영 중인 DB는 01_schema.sql을 다시 실행할 수 없다. 새 표·인덱스는
        # IF NOT EXISTS로 작성한 작은 마이그레이션만 매번 적용한다.
        migrations = self.root / "config" / "migrations"
        for path in sorted(migrations.glob("*.sql")) if migrations.exists() else []:
            r = self.run_file(cfg, path)
            steps.append({"file": f"migrations/{path.name}", **r})
            if not r["ok"]:
                return {"ok": False, "steps": steps, "error": r["error"]}
        for name in ("02_seed.sql", "03_data.sql"):
            r = self.run_file(cfg, self.root / "export" / name)
            steps.append({"file": name, **r})
            if not r["ok"]:
                return {"ok": False, "steps": steps, "error": r["error"]}
        return {"ok": True, "steps": steps,
                "state": self.state(cfg.public() | {"password": cfg.password})}

    def drop_database(self, incoming: dict | None = None) -> dict:
        cfg = self.config(incoming)
        confirm = str((incoming or {}).get("confirm") or "")
        if confirm != cfg.database:
            return {"ok": False, "error": "삭제 확인란에 DB 이름을 정확히 입력하세요."}
        r = self._run(["dropdb", *self._conn_args(cfg), "--if-exists", cfg.database],
                      cfg, timeout=30)
        return {**r, "database": cfg.database}
