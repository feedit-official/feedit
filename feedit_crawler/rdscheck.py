"""AWS RDS 연결이 왜 안 되는지 가려내고, 무엇을 하면 되는지 알려 준다.

왜 있는가
---------
연결 확인이 실패하면 화면에 psql 의 영어 오류가 그대로 나오고, 안내는 늘
"호스트·포트·사용자·비밀번호·보안 그룹과 SSL 을 확인하세요" 한 줄이었다.
원인이 여섯 가지인데 안내가 하나뿐이면, 정작 psql 이 안 깔린 것뿐인데도
보안 그룹을 뒤지며 한나절을 쓰게 된다.

    psql: error: connection to server at "feedit...rds.amazonaws.com"
    failed: Connection timed out
        → 보안 그룹에서 내 IP 의 5432 를 열어야 한다

    FATAL: password authentication failed for user "feedit"
        → 여긴 **네트워크는 뚫린 것이다.** 비밀번호만 틀렸다.

    psql 이 설치되지 않았습니다
        → 연결 실패가 아니다. 내 노트북에 도구가 없는 것이다.

그래서 원인을 나누고, 원인마다 다른 다음 걸음을 준다.

★ 여기서 판단만 한다. 실제 접속은 platformdb 가 한다.
"""

from __future__ import annotations

import re

# (원인 코드, 사람이 읽는 제목, 무엇을 하면 되는지)
# 위에서부터 먼저 맞는 것을 쓴다 — 구체적인 것을 앞에 둔다.
RULES: list[tuple[str, re.Pattern, str, str]] = [
    ("schema_mismatch", re.compile(r"column .* of relation .* does not exist|"
                                    r"null value in column .* violates not-null constraint"),
     "연결은 됐지만 적재 SQL과 RDS 표 구조가 다릅니다",
     ("호스트·비밀번호·보안 그룹 문제는 아닙니다. RDS까지 연결된 뒤 SQL이 "
      "거절된 상태입니다. 오류에 나온 표와 칼럼을 실제 information_schema와 "
      "맞춰야 합니다.")),

    ("no_psql", re.compile(r"psql이 설치되지 않았습니다|명령을 찾을 수 없습니다"),
     "psql 이 이 컴퓨터에 없습니다",
     ("연결이 안 되는 게 아니라 확인할 도구가 없는 것입니다. "
      "맥이면 터미널에 `brew install libpq` 를 넣고 "
      "`brew link --force libpq` 까지 하면 psql 이 생깁니다.")),

    #  ★ 자동 적재가 매번 900초를 버리던 자리.
    #    자동 적재는 비밀번호 없이 psql 을 부르고(저장하지 않으므로), psql 은
    #    터미널에서 암호를 묻는다. 서버가 부르는 자리엔 사람이 없어서 아무도
    #    못 치고 타임아웃까지 매달렸다. -w 를 붙여 이제 즉시 이 오류가 난다.
    ("no_password", re.compile(r"no password supplied|fe_sendauth|비밀번호가 없|"
                               r"password is required"),
     "비밀번호가 없어서 못 붙었습니다",
     ("화면에서 누를 때는 그 자리에서 입력한 비밀번호를 쓰지만, "
      "12시간마다 도는 자동 적재에는 넣어 줄 사람이 없습니다.\n"
      "PostgreSQL 표준 방식인 ~/.pgpass 에 적어 두면 psql 이 알아서 씁니다 "
      "(우리 코드에는 안 들어오고 깃에도 안 올라갑니다):\n"
      "  echo '호스트:포트:DB이름:사용자:비밀번호' >> ~/.pgpass\n"
      "  chmod 600 ~/.pgpass\n"
      "예: echo '127.0.0.1:5433:feedit:feedit_admin:비밀번호' >> ~/.pgpass\n"
      "★ 권한 600 이 아니면 psql 이 그 파일을 통째로 무시합니다.")),

    ("pgpass_perm", re.compile(r"password file .*(read access|permissions)|"
                               r"permissions .* are too open"),
     "~/.pgpass 의 권한이 너무 열려 있습니다",
     "psql 이 그 파일을 무시합니다. `chmod 600 ~/.pgpass` 를 해 주세요."),

    ("auth", re.compile(r"password authentication failed|authentication failed for user"),
     "비밀번호나 사용자 이름이 다릅니다",
     ("★ 네트워크는 뚫렸습니다 — 서버까지 갔고 거기서 거절당한 것이라 "
      "보안 그룹은 볼 필요가 없습니다. 사용자 이름과 비밀번호만 다시 보세요.")),

    ("no_role", re.compile(r'role ".*" does not exist'),
     "그 사용자가 RDS 에 없습니다",
     ("네트워크는 뚫렸습니다. RDS 를 만들 때 정한 마스터 사용자 이름을 쓰거나, "
      "그 사용자를 먼저 만들어야 합니다.")),

    ("ssl", re.compile(r"no pg_hba\.conf entry|SSL.*required|server does not support SSL|"
                       r"sslmode"),
     "SSL 설정이 서버와 안 맞습니다",
     ("네트워크는 뚫렸습니다. AWS RDS 는 보통 SSL 을 요구하므로 "
      "SSL 모드를 `require` 로 두세요.")),

    ("timeout", re.compile(r"Connection timed out|timeout expired|시간이 초과"),
     "서버까지 아예 닿지 못했습니다",
     ("십중팔구 보안 그룹입니다. RDS 의 보안 그룹 인바운드에 "
      "내 현재 IP 의 5432 포트를 열어 주세요. "
      "RDS 가 '퍼블릭 액세스 예' 인지도 함께 보세요.")),

    ("refused", re.compile(r"Connection refused|could not connect to server"),
     "그 주소는 열려 있는데 5432 가 닫혀 있습니다",
     "포트 번호가 맞는지, RDS 가 '사용 가능' 상태인지 보세요."),

    ("dns", re.compile(r"could not translate host name|Name or service not known|"
                       r"nodename nor servname"),
     "그런 주소를 찾지 못했습니다",
     ("엔드포인트 주소에 오타가 없는지 보세요. "
      "AWS 콘솔의 RDS 상세에서 '엔드포인트' 를 그대로 복사하면 됩니다.")),

    ("db_missing", re.compile(r'database ".*" does not exist'),
     "그 이름의 데이터베이스가 없습니다",
     "연결은 됐습니다. DB 이름을 확인하거나, 아직 안 만들었다면 먼저 만들어야 합니다."),
]

FALLBACK = ("unknown", "연결하지 못했습니다",
            "호스트·포트·사용자·DB 이름·비밀번호와 보안 그룹을 차례로 확인해 보세요.")


#  ★ 터널로 붙는 경우 — 호스트가 내 컴퓨터다
#    이 RDS 는 인터넷에 안 열려 있고, EC2 를 거친 SSM 포트 포워딩으로만 들어간다.
#        aws ssm start-session --target i-… \
#          --document-name AWS-StartPortForwardingSessionToRemoteHost \
#          --parameters 'host=feedit-db.….rds.amazonaws.com,portNumber=5432,localPortNumber=5433'
#    그러면 관리자 화면에는 127.0.0.1:5433 을 넣는다.
#    이때 못 붙는 건 보안 그룹이 아니라 **터널이 꺼진 것**이다.
#    같은 오류에 다른 안내를 줘야 해서 따로 가른다.
#    ※ 빈 값은 넣지 않는다. 호스트를 아직 안 적은 것과 '내 컴퓨터로 붙는 중'은
#      다른 이야기다. 빈 값까지 터널로 보면 설정 전 화면에도 터널 안내가 뜬다.
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")

TUNNEL_TODO = (
    "터널이 꺼진 것 같습니다. 보안 그룹이 아니라 터널을 먼저 보세요.\n"
    "터미널에서 이 명령이 떠 있어야 합니다 (창을 닫으면 끊깁니다):\n"
    "  aws ssm start-session --target i-… \\\n"
    "    --document-name AWS-StartPortForwardingSessionToRemoteHost \\\n"
    "    --parameters 'host=…rds.amazonaws.com,portNumber=5432,localPortNumber=5433' \\\n"
    "    --region ap-northeast-2\n"
    "포트 번호가 터널의 localPortNumber 와 같은지도 보세요."
)


def _is_tunnel(out: dict) -> bool:
    host = str((out.get("config") or {}).get("host") or "").strip().lower()
    return host in LOCAL_HOSTS


def diagnose(state: dict) -> dict:
    """`PlatformDB.state()` 결과에 '왜'와 '무엇을 하면 되는지'를 붙인다."""
    out = dict(state or {})
    err = str(out.get("error") or "")

    if out.get("ok"):
        out.update(_ok_shape(out))
        return out

    for code, pat, title, todo in RULES:
        if pat.search(err):
            # 내 컴퓨터로 붙는 중인데 못 닿았다면 터널 이야기다.
            if code in ("timeout", "refused", "dns") and _is_tunnel(out):
                out.update(cause="tunnel_down", tunnel=True,
                           title="터널이 안 열려 있습니다",
                           todo=TUNNEL_TODO, reachable=False, tool_missing=False)
                return out
            out.update(cause=code, title=title, todo=todo,
                       reachable=code not in ("no_psql", "timeout", "refused", "dns"),
                       tool_missing=(code == "no_psql"))
            return out

    code, title, todo = FALLBACK
    out.update(cause=code, title=title, todo=todo, tool_missing=False)
    return out


# FEEDIT FINAL 스키마가 다 깔렸다고 볼 표 개수
EXPECTED_TABLES = 35


def _ok_shape(out: dict) -> dict:
    """붙었을 때도 '이제 뭘 하면 되는지'까지 말해 준다."""
    if not out.get("database_exists"):
        return {"cause": "no_database", "reachable": True,
                "title": f"연결은 됐지만 '{out.get('config', {}).get('database', 'feedit')}' "
                         "데이터베이스가 없습니다",
                "todo": "DB 부터 만들어야 합니다. 이름이 맞는지 먼저 보세요."}

    n = int(out.get("tables") or 0)
    if n == 0:
        return {"cause": "no_schema", "reachable": True,
                "title": "연결은 됐지만 FEEDiT 표가 하나도 없습니다",
                "todo": "스키마 SQL 을 먼저 넣어야 적재할 수 있습니다."}
    if n < EXPECTED_TABLES:
        return {"cause": "partial_schema", "reachable": True,
                "title": f"표가 {n}개뿐입니다 (있어야 할 것은 {EXPECTED_TABLES}개)",
                "todo": "스키마가 덜 깔렸습니다. 이대로 적재하면 중간에 멈춥니다. "
                        "스키마 SQL 을 다시 넣어 주세요."}
    return {"cause": "ready", "reachable": True,
            "title": "연결됐고 FEEDiT 표도 다 있습니다",
            "todo": "이제 적재할 수 있습니다."}


def short_error(err: str, limit: int = 300) -> str:
    """psql 원문에서 쓸모 있는 줄만 남긴다. 원문도 봐야 할 때가 있어 버리진 않는다."""
    lines = [x.strip() for x in str(err or "").splitlines() if x.strip()]
    keep = [x for x in lines if not x.startswith(("Is the server", "TCP/IP"))]
    return " / ".join(keep or lines)[:limit]
