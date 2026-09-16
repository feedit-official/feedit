"""
로그인 — 사람별 코드로 어드민만 들어오게 한다.

인터넷에 공개하는 순간 전제가 바뀐다. 사내망이라면 "우리 팀만 아는 주소"가
어느 정도 울타리가 되지만, 공개 서버에는 **하루 종일 자동으로 문을 두드리는
프로그램들**이 붙는다. 그래서 여기서는 다음을 지킨다.

  ① 코드를 원문으로 저장하지 않는다
     DB 가 새도 코드는 못 쓴다. scrypt 해시만 남긴다.
     (bcrypt 를 쓰려면 패키지를 깔아야 하는데, 파이썬 표준 hashlib.scrypt 로
      충분하다. 의존성을 늘리지 않는 편이 배포가 쉽다.)

  ② 틀리면 점점 느려진다
     맞을 때까지 계속 넣어 보는 걸 막는다. 같은 곳에서 다섯 번 틀리면
     기다리게 하고, 더 틀리면 더 오래 기다리게 한다.

  ③ 세션 쿠키도 원문을 저장하지 않는다
     쿠키 값의 해시만 DB 에 둔다. 서버 DB 를 봐도 남의 세션을 못 훔친다.

  ④ 누가 무엇을 했는지 남긴다
     사람별 코드를 쓰는 이유가 이것이다. 설정을 바꾸거나 키를 넣으면
     누가 했는지 기록에 남는다. 한 사람만 골라 끊을 수도 있다.

  ⑤ 코드는 만들 때 딱 한 번만 보여 준다
     다시 볼 수 없다. 잃어버리면 새로 발급한다. 화면 어디에도
     원문이 다시 나타나지 않으므로 캡처 한 장으로 새지 않는다.

★ HTTPS 는 이 파일이 못 해 준다
  쿠키에 Secure 를 붙이지만, 실제 암호화는 앞단(Caddy·Nginx·클라우드 로드밸런서)이
  해야 한다. 배포 문서에 적어 두었다. HTTP 로 열면 코드가 그대로 흘러간다.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
import unicodedata
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

DDL = """
CREATE TABLE IF NOT EXISTS admin_user (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  name         TEXT NOT NULL UNIQUE,
  code_hash    TEXT NOT NULL,          -- scrypt(코드) — 원문은 어디에도 없다
  code_salt    TEXT NOT NULL,
  code_hint    TEXT,                   -- 'FEEDIT-4K7…' 앞부분만. 누구 코드인지 알아보게
  is_owner     INTEGER DEFAULT 0,      -- 다른 사람을 발급·회수할 수 있는가
  created_at   TEXT DEFAULT (datetime('now')),
  created_by   TEXT,
  last_login   TEXT,
  login_count  INTEGER DEFAULT 0,
  revoked_at   TEXT                    -- 채워지면 더는 못 들어온다
);

CREATE TABLE IF NOT EXISTS admin_session (
  token_hash   TEXT PRIMARY KEY,       -- 쿠키 원문이 아니라 해시
  user_id      INTEGER NOT NULL,
  created_at   TEXT NOT NULL,
  last_seen    TEXT NOT NULL,
  expires_at   TEXT NOT NULL,
  ip           TEXT,
  agent        TEXT
);
CREATE INDEX IF NOT EXISTS ix_sess_user ON admin_session (user_id);

CREATE TABLE IF NOT EXISTS audit_log (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  at           TEXT NOT NULL,
  user_name    TEXT,
  action       TEXT NOT NULL,
  detail       TEXT,
  ip           TEXT,
  ok           INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_audit ON audit_log (id DESC);

CREATE TABLE IF NOT EXISTS login_attempt (
  ip           TEXT PRIMARY KEY,
  fails        INTEGER DEFAULT 0,
  last_fail    REAL,
  blocked_until REAL
);
"""

# ── 코드 모양 ─────────────────────────────────────────────────
#  사람이 불러 주고 받아 적을 수 있어야 한다. 그래서
#  헷갈리는 глиф(0·O, 1·I·L)를 뺀 32글자만 쓴다.
#  12글자면 32^12 ≈ 1.15×10^18 — 초당 백만 번 찍어도 3만 년이 걸린다.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_GROUPS = 3
CODE_PER_GROUP = 4

SESSION_HOURS = 12          # 이만큼 안 쓰면 끊긴다
SESSION_MAX_DAYS = 7        # 계속 써도 이날엔 다시 로그인
COOKIE = "feedit_sid"

# ★ '지금 열려 있음' 의 기준
#   만료 시각으로 세면 안 된다. 만료는 12시간 뒤인데다 쓸 때마다 미뤄져서,
#   창을 그냥 닫고 나가도 반나절 동안 '열려 있음' 으로 남는다.
#   실제로 팀원 두 명이 다섯 시간 전에 나갔는데도 접속 중으로 보였다.
#
#   화면이 열려 있으면 실시간 스트림이 계속 붙어 있어서 last_seen 이
#   끊임없이 갱신된다. 그러니 **최근 몇 분 안에 움직였나**로 보면 된다.
#   로그아웃을 안 하고 닫아도 몇 분 뒤 저절로 사라진다.
ACTIVE_MINUTES = 5


def new_code() -> str:
    """'FEEDIT-A7K2-9MQX-3PWH' 같은 코드를 만든다."""
    parts = ["".join(secrets.choice(_ALPHABET) for _ in range(CODE_PER_GROUP))
             for _ in range(CODE_GROUPS)]
    return "FEEDIT-" + "-".join(parts)


def _canon(code: str) -> str:
    """받아 적을 때 생기는 차이를 없앤다.

    소문자로 써도, 하이픈을 빼도, 공백이 섞여도 같은 코드로 본다.
    사람이 옮겨 적는 값이라 여기서 너그럽지 않으면 "안 된다"는 문의만 늘어난다.
    """
    s = unicodedata.normalize("NFKC", str(code or "")).upper()
    return re.sub(r"[^A-Z0-9]", "", s)


def _hash(code: str, salt: str) -> str:
    """scrypt — 표준 라이브러리이고, GPU 로 밀어붙이기 어렵다.

    n=2^14 이면 한 번 계산에 수십 밀리초가 걸린다. 로그인 한 번에는
    아무렇지 않지만, 대량으로 찍어 보려는 쪽에는 벽이 된다.
    """
    return hashlib.scrypt(
        _canon(code).encode(), salt=bytes.fromhex(salt),
        n=2 ** 14, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024).hex()


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _now():
    return datetime.now(UTC)


class Auth:
    def __init__(self, store):
        self.store = store
        with store._lock:
            store._conn.executescript(DDL)
            store._conn.commit()

    # ── 기록 ─────────────────────────────────────────────────
    def log(self, action: str, detail: str = "", user: str = "",
            ip: str = "", ok: bool = True):
        with self.store._lock:
            self.store._conn.execute(
                "INSERT INTO audit_log (at, user_name, action, detail, ip, ok) "
                "VALUES (?,?,?,?,?,?)",
                (_now().isoformat()[:19], user or None, action, detail or None,
                 ip or None, int(ok)))
            self.store._conn.commit()

    def recent_log(self, limit: int = 80) -> list[dict]:
        with self.store._lock:
            return [dict(r) for r in self.store._conn.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))]

    # ── 사람 ─────────────────────────────────────────────────
    def users(self) -> list[dict]:
        with self.store._lock:
            rows = [dict(r) for r in self.store._conn.execute(
                "SELECT id, name, code_hint, is_owner, created_at, created_by, "
                "last_login, login_count, revoked_at FROM admin_user ORDER BY id")]
        cut = (_now() - timedelta(minutes=ACTIVE_MINUTES)).isoformat()[:19]
        now = _now().isoformat()[:19]
        for r in rows:
            r["active"] = not r["revoked_at"]
            with self.store._lock:
                # 지금 화면을 열어 두고 있는 곳
                r["open_now"] = self.store._conn.execute(
                    "SELECT count(*) FROM admin_session "
                    "WHERE user_id=? AND last_seen > ?", (r["id"], cut)).fetchone()[0]
                # 로그인 상태가 남아 있는 곳 (닫아 뒀지만 다시 열면 바로 들어감)
                r["sessions"] = self.store._conn.execute(
                    "SELECT count(*) FROM admin_session "
                    "WHERE user_id=? AND expires_at > ?", (r["id"], now)).fetchone()[0]
                last = self.store._conn.execute(
                    "SELECT max(last_seen) FROM admin_session WHERE user_id=?",
                    (r["id"],)).fetchone()[0]
            r["last_seen"] = last
        return rows

    def has_users(self) -> bool:
        with self.store._lock:
            return self.store._conn.execute(
                "SELECT count(*) FROM admin_user WHERE revoked_at IS NULL"
            ).fetchone()[0] > 0

    def create_user(self, name: str, *, owner: bool = False,
                    by: str = "") -> dict:
        """새 어드민을 만들고 코드를 딱 한 번 돌려준다."""
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "이름을 넣어 주세요."}
        if len(name) > 40:
            return {"ok": False, "error": "이름이 너무 깁니다 (40자까지)."}
        code = new_code()
        salt = secrets.token_hex(16)
        try:
            with self.store._lock:
                self.store._conn.execute(
                    "INSERT INTO admin_user (name, code_hash, code_salt, code_hint, "
                    "is_owner, created_by) VALUES (?,?,?,?,?,?)",
                    (name, _hash(code, salt), salt, code[:11] + "…",
                     int(owner), by or None))
                self.store._conn.commit()
        except Exception:
            return {"ok": False, "error": f"'{name}' 은 이미 있는 이름입니다."}
        self.log("사람 추가", f"{name}{' (관리자)' if owner else ''}", by)
        # ★ 코드 원문을 돌려주는 건 여기 한 번뿐이다.
        return {"ok": True, "name": name, "code": code, "is_owner": owner}

    def reissue(self, user_id: int, by: str = "") -> dict:
        """코드를 잃어버렸을 때. 새 코드를 주고 옛 세션을 전부 끊는다."""
        with self.store._lock:
            r = self.store._conn.execute(
                "SELECT name FROM admin_user WHERE id=?", (user_id,)).fetchone()
        if not r:
            return {"ok": False, "error": "그런 사람이 없습니다."}
        code, salt = new_code(), secrets.token_hex(16)
        with self.store._lock:
            self.store._conn.execute(
                "UPDATE admin_user SET code_hash=?, code_salt=?, code_hint=?, "
                "revoked_at=NULL WHERE id=?",
                (_hash(code, salt), salt, code[:11] + "…", user_id))
            # 옛 코드로 들어와 있던 창은 다 끊는다
            self.store._conn.execute(
                "DELETE FROM admin_session WHERE user_id=?", (user_id,))
            self.store._conn.commit()
        self.log("코드 재발급", r["name"], by)
        return {"ok": True, "name": r["name"], "code": code}

    def revoke(self, user_id: int, by: str = "") -> dict:
        """내보내기. 세션도 바로 끊는다 — 코드만 막고 세션을 두면 계속 들어와 있다."""
        with self.store._lock:
            r = self.store._conn.execute(
                "SELECT name, is_owner FROM admin_user WHERE id=?", (user_id,)).fetchone()
            if not r:
                return {"ok": False, "error": "그런 사람이 없습니다."}
            if r["is_owner"]:
                n = self.store._conn.execute(
                    "SELECT count(*) FROM admin_user "
                    "WHERE is_owner=1 AND revoked_at IS NULL").fetchone()[0]
                if n <= 1:
                    return {"ok": False,
                            "error": "마지막 관리자는 못 지웁니다. "
                                     "다른 사람을 관리자로 올린 뒤에 하세요."}
            self.store._conn.execute(
                "UPDATE admin_user SET revoked_at=? WHERE id=?",
                (_now().isoformat()[:19], user_id))
            self.store._conn.execute(
                "DELETE FROM admin_session WHERE user_id=?", (user_id,))
            self.store._conn.commit()
        self.log("접근 차단", r["name"], by)
        return {"ok": True, "name": r["name"]}

    # ── 시도 제한 ────────────────────────────────────────────
    def _throttle(self, ip: str) -> float:
        """얼마나 더 기다려야 하나 (초). 0 이면 지금 해도 된다."""
        with self.store._lock:
            r = self.store._conn.execute(
                "SELECT fails, blocked_until FROM login_attempt WHERE ip=?",
                (ip,)).fetchone()
        if not r or not r["blocked_until"]:
            return 0.0
        return max(0.0, r["blocked_until"] - time.time())

    def _fail(self, ip: str):
        """틀릴 때마다 기다리는 시간을 늘린다.

        5번까지는 봐준다 (오타는 흔하다). 그 뒤로는 2배씩 늘려
        30분까지 간다. 사람은 거의 안 겪고, 자동 프로그램은 못 버틴다.
        """
        with self.store._lock:
            r = self.store._conn.execute(
                "SELECT fails FROM login_attempt WHERE ip=?", (ip,)).fetchone()
            fails = (r["fails"] if r else 0) + 1
            wait = 0.0 if fails <= 5 else min(1800.0, 2 ** (fails - 5) * 5)
            self.store._conn.execute(
                "INSERT INTO login_attempt (ip, fails, last_fail, blocked_until) "
                "VALUES (?,?,?,?) ON CONFLICT(ip) DO UPDATE SET "
                "fails=excluded.fails, last_fail=excluded.last_fail, "
                "blocked_until=excluded.blocked_until",
                (ip, fails, time.time(), time.time() + wait))
            self.store._conn.commit()
        return wait

    def _clear_fails(self, ip: str):
        with self.store._lock:
            self.store._conn.execute("DELETE FROM login_attempt WHERE ip=?", (ip,))
            self.store._conn.commit()

    # ── 로그인 ───────────────────────────────────────────────
    def login(self, code: str, ip: str = "", agent: str = "") -> dict:
        wait = self._throttle(ip)
        if wait > 0:
            self.log("로그인 차단", f"{wait:.0f}초 대기", ip=ip, ok=False)
            return {"ok": False, "wait": int(wait),
                    "error": f"너무 여러 번 틀렸습니다. {int(wait)}초 뒤에 다시 해 주세요."}

        canon = _canon(code)
        if not canon:
            return {"ok": False, "error": "코드를 넣어 주세요."}

        # 코드로 사람을 찾는다. 어느 줄이 맞는지 모르니 전부 돌려 본다.
        # 사람이 몇 명뿐이라 느리지 않고, '없는 이름'과 '틀린 코드'의
        # 응답 시간이 같아져서 오히려 안전하다.
        with self.store._lock:
            rows = [dict(r) for r in self.store._conn.execute(
                "SELECT id, name, code_hash, code_salt, is_owner FROM admin_user "
                "WHERE revoked_at IS NULL")]
        found = None
        for u in rows:
            if hmac.compare_digest(_hash(canon, u["code_salt"]), u["code_hash"]):
                found = u
                break

        if not found:
            w = self._fail(ip)
            self.log("로그인 실패", "코드가 맞지 않음", ip=ip, ok=False)
            msg = "코드가 맞지 않습니다."
            if w:
                msg += f" ({int(w)}초 뒤에 다시 시도할 수 있습니다)"
            return {"ok": False, "error": msg}

        self._clear_fails(ip)
        token = secrets.token_urlsafe(32)
        now = _now()
        with self.store._lock:
            # ★ 같은 자리(같은 IP·같은 브라우저)에서 다시 로그인하면
            #   옛 세션을 지운다. 안 그러면 로그인할 때마다 하나씩 쌓여서
            #   '14곳에서 열려 있음' 같은 말이 된다 (실제로 그랬다).
            self.store._conn.execute(
                "DELETE FROM admin_session WHERE user_id=? AND ip IS ? AND agent IS ?",
                (found["id"], ip or None, (agent or "")[:200] or None))
            self.store._conn.execute(
                "INSERT INTO admin_session (token_hash, user_id, created_at, "
                "last_seen, expires_at, ip, agent) VALUES (?,?,?,?,?,?,?)",
                (_sha(token), found["id"], now.isoformat()[:19], now.isoformat()[:19],
                 (now + timedelta(hours=SESSION_HOURS)).isoformat()[:19],
                 ip or None, (agent or "")[:200]))
            self.store._conn.execute(
                "UPDATE admin_user SET last_login=?, login_count=login_count+1 "
                "WHERE id=?", (now.isoformat()[:19], found["id"]))
            self.store._conn.commit()
        self.log("로그인", "", found["name"], ip)
        return {"ok": True, "token": token, "name": found["name"],
                "is_owner": bool(found["is_owner"])}

    def logout(self, token: str, user: str = "", ip: str = ""):
        if not token:
            return
        with self.store._lock:
            self.store._conn.execute(
                "DELETE FROM admin_session WHERE token_hash=?", (_sha(token),))
            self.store._conn.commit()
        self.log("로그아웃", "", user, ip)

    # ── 세션 확인 ────────────────────────────────────────────
    def whoami(self, token: str) -> dict | None:
        """쿠키로 사람을 알아낸다. 쓸 때마다 만료 시각을 미룬다."""
        if not token:
            return None
        now = _now()
        with self.store._lock:
            r = self.store._conn.execute(
                "SELECT s.token_hash, s.user_id, s.created_at, s.expires_at, "
                "       u.name, u.is_owner, u.revoked_at "
                "FROM admin_session s JOIN admin_user u ON u.id = s.user_id "
                "WHERE s.token_hash = ?", (_sha(token),)).fetchone()
            if not r:
                return None
            r = dict(r)
            if r["revoked_at"]:
                # 내보낸 사람의 세션이 남아 있으면 즉시 끊는다
                self.store._conn.execute(
                    "DELETE FROM admin_session WHERE token_hash=?", (r["token_hash"],))
                self.store._conn.commit()
                return None
            if r["expires_at"] < now.isoformat()[:19]:
                self.store._conn.execute(
                    "DELETE FROM admin_session WHERE token_hash=?", (r["token_hash"],))
                self.store._conn.commit()
                return None
            # 절대 만료 — 계속 쓰고 있어도 이날엔 다시 로그인
            try:
                born = datetime.fromisoformat(r["created_at"]).replace(tzinfo=UTC)
                if now - born > timedelta(days=SESSION_MAX_DAYS):
                    self.store._conn.execute(
                        "DELETE FROM admin_session WHERE token_hash=?",
                        (r["token_hash"],))
                    self.store._conn.commit()
                    return None
            except (TypeError, ValueError):
                pass
            self.store._conn.execute(
                "UPDATE admin_session SET last_seen=?, expires_at=? WHERE token_hash=?",
                (now.isoformat()[:19],
                 (now + timedelta(hours=SESSION_HOURS)).isoformat()[:19],
                 r["token_hash"]))
            self.store._conn.commit()
        return {"id": r["user_id"], "name": r["name"],
                "is_owner": bool(r["is_owner"])}

    def sign_out_all(self, user_id: int, by: str = "") -> dict:
        """그 사람이 로그인해 둔 곳을 전부 끊는다. 코드는 그대로 쓴다.

        재발급과 다르다. 재발급은 코드를 새로 만들어서 전달까지 다시 해야 하는데,
        "어디 딴 데 로그인해 둔 것 같은데" 정도면 끊기만 하면 된다.
        """
        with self.store._lock:
            row = self.store._conn.execute(
                "SELECT name FROM admin_user WHERE id=?", (user_id,)).fetchone()
            if not row:
                return {"ok": False, "error": "없는 사람입니다."}
            cur = self.store._conn.execute(
                "DELETE FROM admin_session WHERE user_id=?", (user_id,))
            self.store._conn.commit()
        self.log("모두 로그아웃", f"{row['name']} · {cur.rowcount}곳", user=by)
        return {"ok": True, "closed": cur.rowcount, "name": row["name"]}

    def sweep(self):
        """만료된 세션·오래된 실패 기록을 치운다."""
        now = _now().isoformat()[:19]
        stale = (_now() - timedelta(hours=SESSION_HOURS)).isoformat()[:19]
        with self.store._lock:
            self.store._conn.execute(
                "DELETE FROM admin_session WHERE expires_at < ?", (now,))
            # 오래 안 쓴 것도 치운다. 만료 시각만 보면 옛 기록이 계속 남는다.
            self.store._conn.execute(
                "DELETE FROM admin_session WHERE last_seen < ?", (stale,))
            self.store._conn.execute(
                "DELETE FROM login_attempt WHERE last_fail < ?",
                (time.time() - 86400,))
            self.store._conn.commit()

    # ── 첫 실행 ──────────────────────────────────────────────
    def bootstrap(self) -> dict | None:
        """어드민이 하나도 없으면 첫 관리자를 만든다.

        코드는 **터미널에만** 찍는다. 화면으로 보내지 않는다 —
        아직 아무도 로그인하지 않은 상태라 화면은 누구나 볼 수 있다.
        """
        if self.has_users():
            return None
        r = self.create_user("관리자", owner=True, by="설치")
        return r if r.get("ok") else None
