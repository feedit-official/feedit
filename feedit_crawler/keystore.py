"""
열쇠 보관 — 화면에서 넣으면 바로 쓰인다.

지금까지는 `.env` 를 손으로 고치고 서버를 다시 켜야 했다. 비전공자에게는
"파일을 열어 텍스트를 고치고 프로그램을 재시작하세요"가 큰 벽이다.
여기서는 화면에서 넣으면 그 즉시 반영된다.

★ 저장 위치와 우선순위
    ① 환경변수         — 배포에서 주입한 값. 가장 세다.
    ② data/keys.json   — 화면에서 넣은 값
    ③ .env             — 개발자가 파일로 둔 값
  ①이 있으면 화면에서 못 바꾸게 막는다. 클라우드에서 환경변수로 넣어 두고
  화면에서 덮어써 버리면, 다시 배포할 때 조용히 원복돼서 아무도 이유를 모른다.

★ 왜 암호화를 안 하나
  같은 서버에 열쇠와 열쇠를 푸는 방법이 같이 있으면 암호화가 아니다.
  기분만 안전해진다. 대신 실제로 도움이 되는 걸 한다 —
  파일 권한을 0600 으로 좁히고, 화면에는 앞 네 글자만 보내고,
  누가 언제 바꿨는지 기록을 남긴다.
  진짜로 지켜야 하면 클라우드의 비밀 저장소(Secret Manager)를 쓰고
  환경변수로 주입하는 게 맞다 — 그 길을 ①로 열어 뒀다.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from . import settings

UTC = timezone.utc


# ── 우리가 다루는 열쇠들 ──────────────────────────────────────
#  화면이 이 목록을 그대로 그린다. 새 플랫폼이 생기면 여기만 늘리면 된다.
SPECS = [
    {
        "id": "openai", "name": "OpenAI · 키워드 분석", "icon": "AI",
        "why": "패션 관련도 · 감성 · 구매 의향 · 연관어를 GPT-5.6-luna로 분석",
        "where": "platform.openai.com → API keys",
        "note": "키는 이 서버에만 저장되며 화면에는 마스킹됩니다. 모델은 gpt-5.6-luna로 고정합니다.",
        "fields": [
            {"env": "OPENAI_API_KEY", "label": "OpenAI API 키",
             "placeholder": "sk-…", "secret": True},
        ],
    },
    {
        "id": "youtube", "name": "유튜브", "icon": "▶",
        "why": "구매 의향 텍스트 — 지표 가중치의 25%",
        "where": "console.cloud.google.com → API 및 서비스 → 사용자 인증 정보",
        "note": "만든 뒤 'YouTube Data API v3' 를 켜 주세요. 안 켜면 403 이 납니다.",
        "fields": [
            {"env": "YOUTUBE_API_KEY", "label": "API 키",
             "placeholder": "AIza…", "secret": True},
        ],
    },
    {
        "id": "naver", "name": "네이버", "icon": "N",
        "why": "검색 트렌드 + 블로그·카페 본문 — 지표 가중치의 30%",
        "where": "ncloud.com → NAVER API HUB → 신청하기 (2026년에 여기로 옮겨졌습니다)",
        "note": "Application 에 '검색' 과 '검색어 트렌드' 를 둘 다 선택하세요. "
                "옛 developers.naver.com 키를 쓰셔도 [연결 시험] 이 알아서 맞춥니다.",
        "fields": [
            {"env": "NAVER_CLIENT_ID", "label": "Client ID",
             "placeholder": "영문+숫자 10자쯤", "secret": False},
            {"env": "NAVER_CLIENT_SECRET", "label": "Client Secret",
             "placeholder": "40자쯤", "secret": True},
            # 사람이 넣는 값이 아니라 [연결 시험] 이 알아내서 적어 두는 값.
            # 어느 창구(HUB / 옛 방식)로 부를지를 기억한다.
            {"env": "NAVER_DIALECT", "label": "연결 방식",
             "placeholder": "", "secret": False, "hidden": True},
            {"env": "NAVER_TREND_DIALECT", "label": "트렌드 연결 방식",
             "placeholder": "", "secret": False, "hidden": True},
        ],
    },
    {
        "id": "musinsa", "name": "무신사", "icon": "M",
        "why": "지금은 저장본을 사람이 넣는 방식으로 대신하고 있습니다",
        "where": "제휴 신청",
        "note": "키가 없어도 [가져오기] 로 모을 수 있습니다.",
        "fields": [
            {"env": "MUSINSA_API_KEY", "label": "API 키",
             "placeholder": "", "secret": True},
        ],
    },
]

BY_ENV = {f["env"]: (s, f) for s in SPECS for f in s["fields"]}


class KeyStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict | None = None

    # ── 파일 ─────────────────────────────────────────────────
    def _load(self) -> dict:
        if self._cache is not None:
            return self._cache
        try:
            self._cache = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            self._cache = {}
        return self._cache

    def _save(self, d: dict):
        self.path.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        try:
            # 나만 읽고 쓰게. 같은 서버의 다른 계정이 못 읽는다.
            self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        self._cache = d

    # ── 읽기 ─────────────────────────────────────────────────
    def get(self, env: str) -> str:
        """환경변수 > 화면에서 넣은 값 > .env 순으로 찾는다."""
        v = os.environ.get(env)
        if v and self._from_real_env(env):
            return v.strip()
        saved = (self._load().get(env) or {}).get("value")
        if saved:
            return saved.strip()
        return settings.get(env)

    def _from_real_env(self, env: str) -> bool:
        """이 값이 진짜 환경변수인가, 아니면 .env 를 읽어 넣은 것인가.

        settings.load_env() 가 os.environ 에 넣어 두기 때문에 그냥 보면
        구분이 안 된다. .env 에 적힌 값과 **똑같을 때만** 파일 출신으로 본다.

        ★ 'env 에 이름이 있는가'로만 보면 안 된다.
          .env 에 `MUSINSA_API_KEY=` 처럼 빈 줄로 자리만 잡아 두는 일이 흔한데,
          그러면 배포에서 진짜로 넣은 환경변수까지 '파일 출신'으로 오해해
          잠금이 풀린다. 실제로 그렇게 틀렸다.
        """
        cur = (os.environ.get(env) or "").strip()
        if not cur:
            return False
        # .env 에서 온 값이면 배포가 정한 게 아니다
        if cur == (settings.load_env().get(env) or "").strip():
            return False
        # ★ 우리가 화면에서 넣고 os.environ 에도 반영해 둔 값이면 당연히 아니다.
        #   이걸 빠뜨려서, 화면에서 저장하는 순간 '서버가 정한 값'으로 잠겨
        #   다시는 못 고치게 됐다. 저장한 사람이 자기 값에 갇히는 셈이었다.
        if cur == ((self._load().get(env) or {}).get("value") or "").strip():
            return False
        return True

    def is_locked(self, env: str) -> bool:
        """배포에서 환경변수로 넣은 값은 화면에서 못 바꾼다."""
        return bool(os.environ.get(env)) and self._from_real_env(env)

    # ── 쓰기 ─────────────────────────────────────────────────
    def put(self, env: str, value: str, by: str = "") -> dict:
        if env not in BY_ENV:
            return {"ok": False, "error": "모르는 항목입니다."}
        if self.is_locked(env):
            return {"ok": False,
                    "error": "이 값은 서버 환경변수로 정해져 있어 화면에서 못 바꿉니다."}
        d = self._load()
        value, cleaned = clean_value(value)
        # ★ 저장하기 전에 생김새부터 본다.
        #   잘린 키를 그대로 받아 두면 "저장했습니다"가 뜨고, 문제는
        #   나중에 수집이 실패할 때에야 드러난다. 그때는 원인이 키인지
        #   사이트인지도 헷갈린다. 넣는 순간 말해 주는 편이 훨씬 낫다.
        bad = shape_error(env, value)
        if bad:
            # ★ 서버가 **실제로 받은 길이**를 같이 알려 준다.
            #   "내 메모장엔 39자인데?" 와 "서버엔 35자가 왔다" 사이의
            #   간격이 곧 원인이다. 그 간격을 화면에 그대로 보여 줘야
            #   붙여넣기가 잘린 건지 딴 값을 넣은 건지 가릴 수 있다.
            return {"ok": False, "error": bad, "got_len": len(value)}
        if not value:
            d.pop(env, None)
        else:
            d[env] = {"value": value, "by": by or None,
                      "at": datetime.now(UTC).isoformat()[:19]}
        self._save(d)
        note = ("붙여넣기에서 " + " · ".join(cleaned) + " 을 털어냈습니다."
                if cleaned else "")
        # 지금 돌고 있는 코드가 바로 쓰도록 환경에도 반영한다.
        # (재시작 없이 적용되는 이유가 이 두 줄이다.)
        if value:
            os.environ[env] = value
        else:
            os.environ.pop(env, None)
        return {"ok": True, "len": len(value), "note": note}

    # ── 화면용 ───────────────────────────────────────────────
    @staticmethod
    def mask(v: str) -> str:
        if not v:
            return ""
        if len(v) <= 8:
            return v[0] + "…" + v[-1]
        return f"{v[:4]}…{v[-2:]} ({len(v)}자)"

    def state(self) -> list[dict]:
        """플랫폼마다 뭐가 들어 있는지. **값 원문은 절대 안 보낸다.**"""
        saved = self._load()
        out = []
        for spec in SPECS:
            fields, ready = [], True
            for f in spec["fields"]:
                if f.get("hidden"):
                    continue
                v = self.get(f["env"])
                if not v:
                    ready = False
                meta = saved.get(f["env"]) or {}
                fields.append({
                    **f,
                    "filled": bool(v),
                    "masked": self.mask(v) if f.get("secret") else (v or ""),
                    "locked": self.is_locked(f["env"]),
                    "by": meta.get("by"), "at": meta.get("at"),
                    "source": ("환경변수" if self.is_locked(f["env"])
                               else "화면에서 입력" if f["env"] in saved
                               else ".env 파일" if v else None),
                    # ★ 시험 버튼을 눌러야만 아는 건 늦다.
                    #   .env 에 잘린 키가 들어 있으면 화면을 열자마자 보여 준다.
                    "shape_warn": shape_error(f["env"], v) if v else "",
                })
            out.append({**spec, "fields": fields, "ready": ready})
        return out


_SHARED = None


def _store() -> "KeyStore":
    """이 모듈 안에서 쓰는 기본 보관소 (data/keys.json)."""
    global _SHARED
    if _SHARED is None:
        _SHARED = KeyStore(Path(__file__).resolve().parent.parent / "data" / "keys.json")
    return _SHARED


# ── 연결 시험 ─────────────────────────────────────────────────
# 붙여 넣을 때 딸려 오는, 눈에 안 보이는 글자들.
#  콘솔·메모장·슬랙을 거치면 제로폭 공백이나 BOM 이 섞여 온다.
#  글자 수를 세면 39자가 맞는데 실제로는 40바이트인 식이라, 사람은
#  절대 못 찾는다. 조용히 털어내고 '털어냈다'고 알려 준다.
INVISIBLE = "\u200b\u200c\u200d\ufeff\u2060\u00a0\u3000"


def clean_value(v: str) -> tuple[str, list[str]]:
    """(다듬은 값, 없앤 것들). 무엇을 없앴는지 말해 줘야 믿을 수 있다."""
    raw = str(v or "")
    removed = []
    if raw != raw.strip():
        removed.append("앞뒤 공백")
    out = raw.strip()
    hits = {c for c in out if c in INVISIBLE}
    if hits:
        removed.append(f"보이지 않는 글자 {len(hits)}종")
        for c in INVISIBLE:
            out = out.replace(c, "")
    if out.startswith(("'", '"')) and out.endswith(("'", '"')) and len(out) > 1:
        out = out[1:-1]
        removed.append("따옴표")
    return out, removed


def shape_error(env: str, value: str) -> str:
    """값 생김새로 알 수 있는 문제. 부르기 전에 거른다."""
    v = (value or "").strip()
    if not v:
        return ""                      # 빈 값 = '안 바꿈/지움'. 여기선 통과.
    if env == "YOUTUBE_API_KEY":
        from .social import YouTube
        return YouTube.check_key_shape(v)
    if env == "OPENAI_API_KEY" and (not v.startswith("sk-") or len(v) < 20):
        return "OpenAI API 키는 보통 sk- 로 시작합니다. 전체 키를 다시 붙여 넣어 주세요."
    if env in ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET") and len(v) < 6:
        return f"값이 너무 짧습니다 ({len(v)}자). 잘못 붙여 넣으신 것 같습니다."
    return ""


def test(platform_id: str, keys: KeyStore | None = None) -> dict:
    """진짜로 되는지 한 번 불러 본다.

    '저장했습니다'만 띄우면 오타가 있어도 몇 시간 뒤 수집이 실패할 때까지 모른다.
    넣자마자 확인해 주는 게 훨씬 낫다.
    """
    from . import social
    keys = keys or _store()
    try:
        if platform_id == "openai":
            from .llm_analysis import OpenAITextAnalyzer
            key = keys.get("OPENAI_API_KEY")
            if not key:
                return {"ok": False, "error": "OpenAI API 키가 비어 있습니다."}
            model = OpenAITextAnalyzer(key).test_connection()
            return {"ok": True, "message": f"잘 됩니다. {model} 모델을 사용할 수 있습니다."}
        if platform_id == "youtube":
            yt = social.YouTube()
            if not yt.ready:
                return {"ok": False, "error": "키가 비어 있습니다."}
            # ★ 시험에 search(100칸) 를 쓰면 안 된다.
            #   버튼 한 번이 검색 한 번 값이라, 몇 번 눌러 보다 하루치의
            #   상당수를 태운다. channels 는 1칸이고 키가 맞는지는 똑같이 알 수 있다.
            got = yt.channels(handle="@YouTube")
            who = (got[0]["title"] if got else "")
            return {"ok": True,
                    "message": f"잘 됩니다. 유튜브가 응답했습니다"
                               f"{f' (확인용으로 @YouTube 채널을 읽었습니다: {who})' if who else ''}."
                               f" 이번 시험에 {yt.used}칸 썼습니다 (하루 10,000칸)."}
        if platform_id == "naver":
            nv = social.Naver()
            if not nv.ready:
                return {"ok": False, "error": "Client ID 또는 Secret 이 비어 있습니다."}
            # ★ 어느 창구인지 가려낸다
            #   네이버가 2026년에 API HUB 로 옮겼는데, 키는 그대로 두고
            #   옛 주소로 부르면 "거부됐습니다"만 뜬다. 세 방식을 다 시험해
            #   되는 것을 찾아 기억해 둔다.
            r = nv.detect()
            if not r.get("ok"):
                lines = "\n".join(f"· {t['name']} → {t['why']}"
                                  for t in r.get("tried", []))
                return {"ok": False,
                        "error": "어느 방식으로도 안 됩니다.\n" + lines,
                        "tried": r.get("tried", [])}
            keys.put("NAVER_DIALECT", r["dialect"], by="연결 시험")
            n = r.get("total")
            msg = ("검색 — **" + r["name"] + "** 으로 붙었습니다"
                   + (f" (결과 {n:,}건)." if n else "."))
            # ★ 트렌드도 따로 확인한다
            #   검색만 보고 넘어갔더니, 트렌드는 31번 전부 실패하는데도
            #   '잘 됩니다' 가 떴다. 쓸 기능은 둘인데 하나만 본 셈이다.
            nv2 = social.Naver(dialect=r["dialect"])
            t = nv2.detect_trend()
            if t.get("ok"):
                keys.put("NAVER_TREND_DIALECT", t["dialect"], by="연결 시험")
                msg += f"\n검색어 트렌드 — **{t['name']}** 으로 붙었습니다."
            else:
                lines = "\n".join(f"  · {x['name']} → {x['why']}"
                                  for x in t.get("tried", []))
                msg += ("\n검색어 트렌드 — ✕ 안 됩니다.\n" + lines +
                        "\n  콘솔에서 Application 에 '검색어 트렌드' 를 "
                        "선택했는지 확인해 주세요.")
            return {"ok": True, "dialect": r["dialect"],
                    "trend_ok": bool(t.get("ok")), "message": msg}
        if platform_id == "musinsa":
            return {"ok": False,
                    "error": "무신사는 아직 시험할 API 가 없습니다. "
                             "[가져오기] 로 저장본을 넣어 주세요."}
    except social.NotConfigured as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": _friendly(e)}
    return {"ok": False, "error": "모르는 플랫폼입니다."}


def _friendly(e: Exception) -> str:
    """오류를 사람 말로 바꾼다.

    'HTTPError 403' 을 그대로 띄우면 비전공자는 무엇을 해야 할지 모른다.
    무엇이 문제고 무엇을 하면 되는지까지 적는다.
    """
    s = str(e)
    low = s.lower()
    if "quota" in low or "할당량" in s:
        return "오늘 쓸 수 있는 양을 다 썼습니다. 내일 다시 됩니다."
    if "403" in s or "401" in s or "거부" in s:
        return ("키가 거부됐습니다. 값이 맞는지, 해당 API 가 켜져 있는지 "
                "확인해 주세요.")
    if "timed out" in low or "timeout" in low:
        return "응답이 없습니다. 네트워크나 방화벽을 확인해 주세요."
    if "urlopen" in low or "name or service" in low or "connection" in low:
        return "바깥으로 나가지 못했습니다. 서버의 인터넷 연결을 확인해 주세요."
    return s[:200]
