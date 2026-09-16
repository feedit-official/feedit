"""
소셜 수집 — 유튜브 · 네이버.

── 왜 이게 필요한가 ──
지표계산 설계서의 소스 가중치를 보면

    무신사 0.30 · 네이버 0.30 · 유튜브 0.25 · 지그재그 0.15

**가중치의 55%가 네이버·유튜브**다. 크롤러는 45%만 덮고 있었다.
커머스는 '구매 신호', 소셜은 '인지 신호'다. 커머스만으로 트렌드 온도를 내면
이미 팔리기 시작한 뒤에야 감지된다 — 선행성이 통째로 사라진다.

── 왜 크롤링이 아니라 API 인가 ──
둘 다 공식 API 가 있다. robots 눈치를 볼 필요도, 차단당할 걱정도 없다.
할당량 안에서 떳떳하게 쓰면 된다. 크롤링으로 할 수 있는 일을
굳이 크롤링으로 하지 않는다.

── 긍부정에 이게 왜 맞나 ──
설계서는 긍부정을 '감성이 아니라 **구매 의향**'으로 정의하고
라벨 6개(구매완료·재입고문의·구매고민·가격부담·실물불만·반품)를 쓴다.

상품 리뷰로는 이 지표가 안 된다. **리뷰는 이미 산 사람만 쓰기 때문에**
전부 '구매 완료'로 몰린다. "재입고 언제요", "살까 말까"는 리뷰에 안 나온다.
그런 말은 유튜브 댓글과 카페 글에 있다. 그래서 소스를 여기로 잡는다.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
import urllib.error
import urllib.parse
import urllib.request
import time
from datetime import datetime, timedelta, timezone

from .commentfilter import judge as judge_comment
from .keystore import KeyStore
from . import identity as _identity

UTC = timezone.utc
UA = _identity.crawler_ua()   # ★ 이름은 config/identity.yaml 한 곳에서만


class NotConfigured(Exception):
    """열쇠가 없다. 기능만 끄고 크롤러는 계속 돈다."""


# ── 열쇠는 한 곳에서만 읽는다 ────────────────────────────────
#  화면에서 넣은 값이 재시작 없이 바로 먹히려면, 클래스를 만들 때가 아니라
#  **쓸 때마다** 읽어야 한다. 전역 하나를 두고 그때그때 묻는다.
_KS = None
_TRANSCRIPT_CORRECTOR = None


def _key(env: str) -> str:
    global _KS
    if _KS is None:
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        _KS = KeyStore(root / "data" / "keys.json")
    return _KS.get(env)


def _get_json(url: str, headers: dict | None = None, timeout: float = 10.0):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post_json(url: str, body: dict, headers: dict, timeout: float = 10.0):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"User-Agent": UA, "Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ═══════════════════════════════════════════════════════════════
#  유튜브 Data API v3
# ═══════════════════════════════════════════════════════════════
def _author_hash(v) -> str:
    """작성자를 익명으로 구분하는 값.

    ★ 두 가지를 고친다
      ① 유튜브는 authorChannelId 를 문자열이 아니라 {"value": "UC…"} 로 준다.
         그대로 hash() 에 넣으면 TypeError 로 터진다. API 호출은 이미
         끝난 뒤라 할당량만 쓰고 댓글은 한 건도 안 남는다 —
         실제로 영상 188건에 댓글 0건이 나온 원인이 이것이다.
      ② 파이썬 hash() 는 실행할 때마다 값이 달라진다(PYTHONHASHSEED).
         그러면 같은 사람이 매번 다른 사람으로 보여서 중복 방지가 안 먹는다.
         sha256 으로 고정한다.
    """
    if isinstance(v, dict):
        v = v.get("value") or ""
    v = str(v or "").strip()
    if not v:
        return ""
    return hashlib.sha256(v.encode("utf-8")).hexdigest()[:16]


def _channel_id(v) -> str:
    """YouTube authorChannelId의 {value: ...}/문자열 변형을 같은 값으로 맞춘다."""
    if isinstance(v, dict):
        v = v.get("value") or ""
    return str(v or "").strip()


class YouTube:
    """검색 → 영상 통계 → 댓글.

    ★ 할당량을 아낀다
      하루 10,000 units 다. search 한 번이 100 units 라 검색만 100번이면 끝난다.
      videos·commentThreads 는 1 unit 이므로, 검색은 적게 하고
      영상 ID 를 재활용하는 쪽으로 짠다.
    """

    BASE = "https://www.googleapis.com/youtube/v3"
    # ★ 값이 100배 차이 난다
    #   search 만 100 units 고 나머지는 1 unit 이다. 그래서 '어느 채널을
    #   볼지 이미 안다면' 검색을 아예 건너뛸 수 있다. 채널의 업로드
    #   재생목록을 playlistItems 로 훑으면 영상 50개에 1 unit 이다.
    #   검색 방식으로 하루 100번이 한계인 것이, 채널 방식이면 사실상 무제한이다.
    COST = {"search": 100, "videos": 1, "commentThreads": 1, "comments": 1,
            "channels": 1, "playlistItems": 1}

    def __init__(self, key: str | None = None):
        self.key = key if key is not None else _key("YOUTUBE_API_KEY")
        self.used = 0            # 이번에 쓴 units

    @property
    def ready(self) -> bool:
        return bool(self.key)

    # ── 키 생김새 검사 ────────────────────────────────────────
    #  ★ 구글이 왜 거부했는지 말해 주기 전에, 우리가 먼저 알 수 있는 게 있다.
    #    구글 API 키는 'AIza' + 35자 = **정확히 39자** 다. 복사하다 끝이
    #    잘리는 일이 흔한데, 그러면 화면엔 "키가 거부됐습니다"만 뜬다.
    #    사용자는 복붙했으니 맞다고 믿고 클라우드 콘솔만 계속 들여다본다.
    #    실제로 35자짜리(4자 모자란) 키로 그런 일이 났다.
    KEY_LEN = 39

    @classmethod
    def check_key_shape(cls, key: str) -> str:
        """생김새만으로 알 수 있는 문제. 없으면 빈 문자열."""
        k = (key or "").strip()
        if not k:
            return "키가 비어 있습니다."
        if k.startswith(("YOUTUBE_API_KEY=", "KEY=")):
            return ("`YOUTUBE_API_KEY=` 까지 같이 붙여 넣으셨습니다. "
                    "등호 뒤의 값만 넣어 주세요.")
        if " " in k or "\n" in k:
            return "키 안에 공백이 섞여 있습니다. 앞뒤를 다시 확인해 주세요."
        if not k.startswith("AIza"):
            return (f"구글 API 키는 'AIza' 로 시작합니다. 지금 값은 "
                    f"'{k[:6]}…' 로 시작합니다 — 다른 값을 넣으신 것 같습니다.")
        if len(k) != cls.KEY_LEN:
            d = cls.KEY_LEN - len(k)
            how = f"{d}자 모자랍니다" if d > 0 else f"{-d}자 많습니다"
            return (f"키 길이가 {len(k)}자입니다. 구글 키는 {cls.KEY_LEN}자라 {how}. "
                    f"복사할 때 끝이 잘린 것 같습니다 — 클라우드 콘솔에서 "
                    f"복사 버튼으로 다시 받아 주세요.")
        return ""

    # 구글이 돌려주는 reason → 사람 말과 할 일
    WHY = {
        "keyInvalid":       ("키가 틀렸습니다.",
                             "클라우드 콘솔 → 사용자 인증 정보에서 키를 다시 복사해 주세요."),
        "badRequest":       ("키가 거부됐습니다.",
                             "키 값이 맞는지 다시 확인해 주세요."),
        "accessNotConfigured": ("이 프로젝트에서 YouTube Data API v3 가 안 켜져 있습니다.",
                             "클라우드 콘솔 → API 및 서비스 → 라이브러리에서 "
                             "'YouTube Data API v3' 를 켜 주세요. 켠 뒤 몇 분 걸립니다."),
        "SERVICE_DISABLED": ("이 프로젝트에서 YouTube Data API v3 가 안 켜져 있습니다.",
                             "클라우드 콘솔 → 라이브러리에서 켜 주세요."),
        "ipRefererBlocked": ("키에 사용 제한이 걸려 있습니다.",
                             "클라우드 콘솔에서 그 키의 '애플리케이션 제한'을 "
                             "'없음' 으로 두거나, 이 서버 IP 를 허용해 주세요."),
        "quotaExceeded":    ("오늘 할당량을 다 썼습니다.", "내일 다시 됩니다."),
        "dailyLimitExceeded": ("오늘 할당량을 다 썼습니다.", "내일 다시 됩니다."),
        "rateLimitExceeded": ("너무 빨리 불렀습니다.", "잠시 뒤 다시 해 보세요."),
    }

    def _call(self, endpoint: str, **params):
        if not self.ready:
            raise NotConfigured("YOUTUBE_API_KEY 가 없습니다 (.env 를 확인하세요)")
        bad = self.check_key_shape(self.key)
        if bad:
            # 부르기도 전에 안다. 구글에 요청을 보내 봐야 소용없다.
            raise RuntimeError(bad)
        params["key"] = self.key
        url = f"{self.BASE}/{endpoint}?" + urllib.parse.urlencode(params, doseq=True)
        try:
            j = _get_json(url)
        except urllib.error.HTTPError as e:
            raise RuntimeError(self._explain(e)) from e
        self.used += self.COST.get(endpoint, 1)
        return j

    def _explain(self, e) -> str:
        """구글이 준 응답을 열어 '왜'까지 읽어 낸다.

        403 하나에도 사연이 여럿이다 — 키가 틀렸거나, API 를 안 켰거나,
        키에 IP 제한이 걸렸거나, 할당량을 다 썼거나. 할 일이 전부 다르므로
        뭉뚱그리면 안 된다.
        """
        raw = ""
        try:
            raw = e.read().decode("utf-8", "replace")[:1200]
            err = (json.loads(raw).get("error") or {})
        except Exception:
            err = {}
        reason = ""
        errs = err.get("errors") or []
        if errs:
            reason = errs[0].get("reason") or ""
        reason = reason or err.get("status") or ""
        msg = (err.get("message") or "").strip()

        if reason in self.WHY:
            what, todo = self.WHY[reason]
            return f"{what} {todo}"
        low = (raw or str(e)).lower()
        if "quota" in low:
            return "오늘 할당량을 다 썼습니다. 내일 다시 됩니다."
        if "disabled" in low or "not been used" in low:
            what, todo = self.WHY["accessNotConfigured"]
            return f"{what} {todo}"
        if e.code in (400, 403):
            tail = f" (구글이 준 설명: {msg})" if msg else ""
            return (f"유튜브가 요청을 거부했습니다 ({e.code}). "
                    f"키가 맞는지, Data API v3 가 켜져 있는지 보세요.{tail}")
        return f"유튜브 호출이 실패했습니다 ({e.code}). {msg}"

    def search(self, q: str, days: int = 30, limit: int = 25) -> list[dict]:
        """최근 N일 안에 올라온 영상. 오래된 영상이 섞이면 트렌드가 아니다."""
        after = (datetime.now(UTC) - timedelta(days=days)).replace(
            microsecond=0).isoformat().replace("+00:00", "Z")
        j = self._call("search", part="snippet", q=q, type="video",
                       maxResults=min(limit, 50), order="relevance",
                       publishedAfter=after, regionCode="KR",
                       relevanceLanguage="ko")
        out = []
        for it in j.get("items", []):
            vid = (it.get("id") or {}).get("videoId")
            sn = it.get("snippet") or {}
            if vid:
                out.append({"video_id": vid, "title": sn.get("title"),
                            "channel_id": sn.get("channelId"),
                            "channel_title": sn.get("channelTitle"),
                            "published_at": sn.get("publishedAt"),
                            "description": sn.get("description")})
        return out

    # ── 채널 ──────────────────────────────────────────────
    #  팀이 추려 둔 채널을 그대로 쓰기 위한 것들.
    _HANDLE = re.compile(r"@([A-Za-z0-9._\-가-힣]+)")
    _CHID = re.compile(r"(UC[A-Za-z0-9_\-]{22})")

    @classmethod
    def parse_channel_ref(cls, text: str) -> tuple[str, str]:
        """사람이 붙여 넣은 한 줄에서 채널을 알아낸다.

        받아들이는 모양 (실제로 사람들이 복사해 오는 것들):
            https://www.youtube.com/@somechannel
            https://youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx
            @somechannel
            UCxxxxxxxxxxxxxxxxxxxxxx
        반환: ('id'|'handle'|'query', 값)
        """
        t = (text or "").strip()
        if not t:
            return ("", "")
        m = cls._CHID.search(t)
        if m:
            return ("id", m.group(1))
        m = cls._HANDLE.search(t)
        if m:
            return ("handle", m.group(1))
        # /c/이름 · /user/이름 은 API 로 바로 못 찾는다 → 검색으로 넘긴다
        m = re.search(r"youtube\.com/(?:c|user)/([^/?#]+)", t)
        if m:
            return ("query", urllib.parse.unquote(m.group(1)))
        return ("query", t)

    def channels(self, *, ids=None, handle=None) -> list[dict]:
        """채널 정보. 1 unit 이라 마음껏 불러도 된다."""
        if handle:
            j = self._call("channels", part="snippet,statistics,contentDetails",
                           forHandle=handle if handle.startswith("@") else "@" + handle)
        else:
            ids = [i for i in (ids or []) if i]
            if not ids:
                return []
            j = self._call("channels", part="snippet,statistics,contentDetails",
                           id=",".join(ids[:50]))
        out = []
        for it in j.get("items", []):
            sn = it.get("snippet") or {}
            st = it.get("statistics") or {}
            up = (((it.get("contentDetails") or {}).get("relatedPlaylists") or {})
                  .get("uploads"))
            out.append({
                "channel_id": it.get("id"),
                "title": sn.get("title"),
                "handle": (sn.get("customUrl") or "").lstrip("@"),
                "thumbnail_url": (((sn.get("thumbnails") or {}).get("default") or {})
                                  .get("url")),
                "description": (sn.get("description") or "")[:300],
                "subscriber_count": int(st.get("subscriberCount") or 0),
                "video_count": int(st.get("videoCount") or 0),
                "view_count": int(st.get("viewCount") or 0),
                "uploads_playlist_id": up,
            })
        return out

    def search_channels(self, q: str, limit: int = 10) -> list[dict]:
        """이름으로 채널 찾기. 100 units 이므로 아껴 쓴다.

        찾은 뒤 channels() 로 한 번 더 불러 구독자 수까지 채운다
        (+1 unit). 구독자 수가 있어야 '이 채널이 맞나'를 알아본다.
        """
        j = self._call("search", part="snippet", q=q, type="channel",
                       maxResults=min(limit, 25), regionCode="KR")
        ids = [((it.get("id") or {}).get("channelId")) for it in j.get("items", [])]
        return self.channels(ids=[i for i in ids if i])

    def channel_videos(self, uploads_playlist_id: str, *, days: int = 30,
                       limit: int = 20) -> list[dict]:
        """그 채널이 최근에 올린 영상. 50개에 1 unit.

        업로드 재생목록은 **최신순**이라, 기간을 벗어나면 바로 멈춘다.
        오래된 채널을 끝까지 훑는 낭비를 막는다.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        out, token = [], None
        while len(out) < limit:
            j = self._call("playlistItems", part="snippet,contentDetails",
                           playlistId=uploads_playlist_id,
                           maxResults=min(50, limit - len(out)),
                           **({"pageToken": token} if token else {}))
            stop = False
            for it in j.get("items", []):
                sn = it.get("snippet") or {}
                cd = it.get("contentDetails") or {}
                pub = cd.get("videoPublishedAt") or sn.get("publishedAt") or ""
                try:
                    when = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                except ValueError:
                    when = None
                if when and when < cutoff:
                    stop = True
                    break
                vid = cd.get("videoId") or ((sn.get("resourceId") or {}).get("videoId"))
                if vid:
                    out.append({"video_id": vid, "title": sn.get("title"),
                                "channel_id": sn.get("channelId"),
                                "channel_title": sn.get("channelTitle"),
                                "published_at": pub,
                                "description": sn.get("description")})
            token = j.get("nextPageToken")
            if stop or not token:
                break
        return out

    def video_stats(self, ids: list[str]) -> dict[str, dict]:
        """조회수·좋아요·댓글수. 50개씩 묶어 부른다 (1 unit)."""
        out = {}
        for i in range(0, len(ids), 50):
            j = self._call("videos", part="statistics,snippet",
                           id=",".join(ids[i:i + 50]))
            for it in j.get("items", []):
                st = it.get("statistics") or {}
                out[it["id"]] = {
                    "view_count": int(st.get("viewCount") or 0),
                    "like_count": int(st.get("likeCount") or 0),
                    "comment_count": int(st.get("commentCount") or 0),
                }
        return out

    #  댓글이 꺼진 영상은 오류가 아니다. 이 말들이 보이면 조용히 넘어간다.
    _COMMENTS_OFF = ("commentsdisabled", "disabled comments",
                     "has disabled comments", "comments are disabled",
                     "comments are turned off", "videonotfound",
                     "댓글이 비활성화", "댓글 사용이 중지")

    def comments(self, video_id: str, limit: int = 100,
                 video_channel_id: str = "", replies_per_thread: int = 20) -> list[dict]:
        """최상위 댓글과 답글 — 구매 의향·제품 정보 텍스트의 본체.

        댓글이 꺼진 영상이 흔하다. 그건 오류가 아니므로 조용히 빈 목록.
        commentThreads의 reply_count 숫자만 저장하면 크리에이터가 답글로 알려 준
        브랜드·아이템을 잃는다. 답글이 있는 thread는 comments.list로 본문을 읽되,
        폭주를 막기 위해 thread당 replies_per_thread까지만 가져온다.
        """
        out, token = [], None
        while len(out) < limit:
            try:
                j = self._call("commentThreads", part="snippet", videoId=video_id,
                               maxResults=min(100, limit - len(out)),
                               order="relevance", textFormat="plainText",
                               **({"pageToken": token} if token else {}))
            except RuntimeError as e:
                # ★ _call 은 HTTPError 가 아니라 RuntimeError 를 던진다.
                #   여기서 HTTPError 만 잡고 있어서 '댓글 꺼짐'이 진짜 오류로
                #   올라가고 있었다. 잡는 예외 종류를 맞춘다.
                if any(k in str(e).lower() for k in self._COMMENTS_OFF):
                    break
                raise
            for it in j.get("items", []):
                thread = it.get("snippet") or {}
                top = thread.get("topLevelComment") or {}
                s = top.get("snippet") or {}
                top_id = top.get("id") or ""
                author_channel_id = _channel_id(s.get("authorChannelId"))
                top_row = {
                    "comment_id": top_id,
                    "text": s.get("textDisplay") or s.get("textOriginal") or "",
                    "like_count": int(s.get("likeCount") or 0),
                    "reply_count": int(thread.get("totalReplyCount") or 0),
                    "published_at": s.get("publishedAt"),
                    "author_hash": _author_hash(s.get("authorChannelId")),
                    "is_reply": False, "parent_comment_id": "",
                    "is_creator_reply": bool(video_channel_id and
                                                author_channel_id == video_channel_id),
                }
                out.append(top_row)
                if top_row["reply_count"] and top_id and len(out) < limit:
                    reply_limit = min(replies_per_thread, limit - len(out))
                    out.extend(self.comment_replies(
                        top_id, limit=reply_limit, video_channel_id=video_channel_id))
            token = j.get("nextPageToken")
            if not token:
                break
        return out

    def comment_replies(self, parent_id: str, *, limit: int = 20,
                        video_channel_id: str = "") -> list[dict]:
        """한 최상위 댓글의 실제 답글. YouTube API comments.list를 사용한다."""
        out, token = [], None
        while len(out) < limit:
            j = self._call("comments", part="snippet", parentId=parent_id,
                           maxResults=min(100, limit - len(out)),
                           textFormat="plainText",
                           **({"pageToken": token} if token else {}))
            for it in j.get("items", []):
                s = it.get("snippet") or {}
                author_channel_id = _channel_id(s.get("authorChannelId"))
                out.append({
                    "comment_id": it.get("id") or "",
                    "text": s.get("textDisplay") or s.get("textOriginal") or "",
                    "like_count": int(s.get("likeCount") or 0), "reply_count": 0,
                    "published_at": s.get("publishedAt"),
                    "author_hash": _author_hash(s.get("authorChannelId")),
                    "is_reply": True, "parent_comment_id": parent_id,
                    "is_creator_reply": bool(video_channel_id and
                                                author_channel_id == video_channel_id),
                })
            token = j.get("nextPageToken")
            if not token:
                break
        return out


# ═══════════════════════════════════════════════════════════════
#  네이버 — 열쇠만 넣으면 바로 도는 구조
# ═══════════════════════════════════════════════════════════════
class Naver:
    """데이터랩(검색어 트렌드) + 검색 API(블로그·카페).

    ★ 둘은 성격이 다르다
      · 데이터랩  → 검색 '비율'(0~100 상대지수). **절대 검색수가 아니다.**
        설계서가 경고한 그대로다. 다른 소스와 그냥 더하면 안 된다.
      · 검색 API  → 문서 수와 본문. 긍부정 텍스트의 재료.

    ★★ 2026년에 창구가 바뀌었다 ★★
      예전에는 developers.naver.com 에서 키를 받아
          https://openapi.naver.com/v1/search/blog.json
          헤더 X-Naver-Client-Id / X-Naver-Client-Secret
      로 불렀다. 지금은 **NAVER API HUB**(네이버 클라우드) 로 옮겨 갔다.
          https://naverapihub.apigw.ntruss.com/search/v1/blog?format=json
          헤더 X-NCP-APIGW-API-KEY-ID / X-NCP-APIGW-API-KEY

      키는 맞는데 옛 주소로 부르면 그냥 "거부됐습니다"가 뜬다.
      어느 창구에서 받은 키인지 사람이 알기 어려우므로, 여기서는
      **세 방식을 차례로 시험해 보고 되는 것을 기억한다.**
    """

    # (이름, 검색 주소틀, 트렌드 주소, 헤더 만드는 법)
    DIALECTS = {
        "hub": {
            "name": "NAVER API HUB (네이버 클라우드)",
            "search": "https://naverapihub.apigw.ntruss.com/search/v1/{kind}",
            "trend": "https://naverapihub.apigw.ntruss.com/search-trend/v1/search",
            "ncp": True, "format_param": True,
            "where": "ncloud.com → NAVER API HUB",
        },
        "ncp": {
            "name": "AI·NAVER API (네이버 클라우드, 옛 이름)",
            "search": "https://naveropenapi.apigw.ntruss.com/search/v1/{kind}",
            "trend": "https://naveropenapi.apigw.ntruss.com/datalab/v1/search",
            "ncp": True, "format_param": True,
            "where": "ncloud.com → AI·NAVER API",
        },
        "legacy": {
            "name": "developers.naver.com (옛 방식 · 종료 예정)",
            "search": "https://openapi.naver.com/v1/search/{kind}.json",
            "trend": "https://openapi.naver.com/v1/datalab/search",
            "ncp": False, "format_param": False,
            "where": "developers.naver.com/apps",
        },
    }
    ORDER = ("hub", "ncp", "legacy")

    def __init__(self, cid: str | None = None, secret: str | None = None,
                 dialect: str | None = None):
        self.cid = cid if cid is not None else _key("NAVER_CLIENT_ID")
        self.secret = secret if secret is not None else _key("NAVER_CLIENT_SECRET")
        self.dialect = dialect or _key("NAVER_DIALECT") or "hub"
        if self.dialect not in self.DIALECTS:
            self.dialect = "hub"
        # ★ 검색과 트렌드가 서로 다른 문일 수 있다
        #   실제로 검색은 붙었는데 트렌드는 31번 전부 실패했다.
        #   같은 키라도 창구가 다르면 경로가 다르므로 따로 기억한다.
        self.trend_dialect = _key("NAVER_TREND_DIALECT") or self.dialect
        if self.trend_dialect not in self.DIALECTS:
            self.trend_dialect = self.dialect

    @property
    def ready(self) -> bool:
        return bool(self.cid and self.secret)

    @property
    def spec(self) -> dict:
        return self.DIALECTS[self.dialect]

    def _headers(self, dialect: str | None = None):
        if not self.ready:
            raise NotConfigured(
                "네이버 Client ID / Secret 이 없습니다. "
                "ncloud.com 의 NAVER API HUB 에서 발급받아 [API] 탭에 넣어 주세요.")
        d = self.DIALECTS[dialect or self.dialect]
        if d["ncp"]:
            return {"X-NCP-APIGW-API-KEY-ID": self.cid,
                    "X-NCP-APIGW-API-KEY": self.secret}
        return {"X-Naver-Client-Id": self.cid,
                "X-Naver-Client-Secret": self.secret}

    # ── 어느 창구인지 가려내기 ────────────────────────────────
    def detect(self) -> dict:
        """세 방식을 차례로 불러 보고 되는 것을 알려 준다.

        키가 맞는지 틀린지만 보는 게 아니라 **어디로 부를지**를 정한다.
        한 번 정해지면 그 뒤로는 그 방식만 쓴다.
        """
        if not self.ready:
            return {"ok": False, "error": "Client ID / Secret 이 비어 있습니다."}
        tried = []
        for name in self.ORDER:
            d = self.DIALECTS[name]
            url = d["search"].format(kind="blog")
            qs = {"query": "패션", "display": 1}
            if d["format_param"]:
                qs["format"] = "json"
            try:
                j = _get_json(url + "?" + urllib.parse.urlencode(qs),
                              self._headers(name))
            except urllib.error.HTTPError as e:
                tried.append({"dialect": name, "name": d["name"],
                              "why": _naver_why(e)})
                continue
            except Exception as e:
                tried.append({"dialect": name, "name": d["name"],
                              "why": str(e)[:90]})
                continue
            self.dialect = name
            return {"ok": True, "dialect": name, "name": d["name"],
                    "where": d["where"], "total": j.get("total"), "tried": tried}
        return {"ok": False, "tried": tried,
                "error": "세 가지 방식으로 다 불러 봤지만 전부 거부됐습니다."}

    def detect_trend(self, sample=("패션", "니트")) -> dict:
        """트렌드를 어느 문으로 부를지 가려낸다. 검색과 따로 본다."""
        if not self.ready:
            return {"ok": False, "error": "Client ID / Secret 이 비어 있습니다."}
        # 고정 날짜를 쓰면 시간이 흐른 뒤 진단 요청 자체가 낡는다.
        # 언제 실행해도 유효하도록 어제까지의 최근 7일을 사용한다.
        from datetime import date, timedelta
        end = date.today() - timedelta(days=1)
        start = end - timedelta(days=6)
        body = {"startDate": start.isoformat(), "endDate": end.isoformat(),
                "timeUnit": "date",
                "keywordGroups": [{"groupName": k, "keywords": [k]}
                                  for k in sample]}
        tried = []
        # 검색이 붙은 문을 먼저 본다. 대개 같은 문이다.
        order = [self.dialect] + [d for d in self.ORDER if d != self.dialect]
        for name in order:
            d = self.DIALECTS[name]
            try:
                j = _post_json(d["trend"], body, self._headers(name))
            except urllib.error.HTTPError as e:
                tried.append({"dialect": name, "name": d["name"],
                              "url": d["trend"], "why": _naver_why(e)})
                continue
            except Exception as e:
                tried.append({"dialect": name, "name": d["name"],
                              "url": d["trend"], "why": str(e)[:90]})
                continue
            self.trend_dialect = name
            return {"ok": True, "dialect": name, "name": d["name"],
                    "url": d["trend"], "groups": len(j.get("results") or []),
                    "tried": tried}
        return {"ok": False, "tried": tried,
                "error": "검색어 트렌드를 부를 수 있는 문을 못 찾았습니다."}

    def trend(self, keywords: list, start: str, end: str,
              unit: str = "date") -> list[dict]:
        """검색어 트렌드. 한 번에 최대 5개 묶음.

        돌려주는 ratio 는 **그 묶음 안에서의 상대값**이다.
        묶음이 달라지면 같은 키워드도 값이 달라진다 — 비교하려면
        기준 키워드를 항상 같이 넣어야 한다.
        """
        groups = []
        for item in keywords[:5]:
            if isinstance(item, (tuple, list)) and len(item) == 2:
                name, words = item
                words = list(words) if isinstance(words, (tuple, list)) else [words]
            else:
                name, words = item, [item]
            groups.append({"groupName": str(name),
                           "keywords": [str(w) for w in words if str(w).strip()][:20]})
        body = {
            "startDate": start, "endDate": end, "timeUnit": unit,
            "keywordGroups": groups,
        }
        url = self.DIALECTS[self.trend_dialect]["trend"]
        try:
            j = _post_json(url, body, self._headers(self.trend_dialect))
        except urllib.error.HTTPError as e:
            raise RuntimeError(_naver_why(e) + f" [{url}]") from e
        return j.get("results", [])

    def search(self, q: str, kind: str = "blog", display: int = 50,
               start: int = 1, sort: str = "date") -> dict:
        """블로그·카페 글. kind: blog | cafearticle | news"""
        d = self.spec
        qs = {"query": q, "display": min(display, 100), "start": start, "sort": sort}
        if d["format_param"]:
            qs["format"] = "json"
        url = d["search"].format(kind=kind) + "?" + urllib.parse.urlencode(qs)
        try:
            return _get_json(url, self._headers())
        except urllib.error.HTTPError as e:
            raise RuntimeError(_naver_why(e)) from e


def _naver_why(e) -> str:
    """네이버가 왜 거부했는지 사람 말로.

    401/210 은 '키는 맞는데 그 API 를 안 켰다' 는 뜻이다.
    '키가 틀렸다' 로 뭉뚱그리면 콘솔만 계속 들여다보게 된다.
    """
    raw, code = "", getattr(e, "code", 0)
    try:
        raw = e.read().decode("utf-8", "replace")[:600]
        j = json.loads(raw)
    except Exception:
        j = {}
    err = j.get("error") or j.get("errorMessage") or {}
    ecode = str((err or {}).get("errorCode") or j.get("errorCode") or "")
    msg = str((err or {}).get("message") or j.get("errorMessage") or "").strip()

    if ecode == "200" or code == 401 and "authentication" in raw.lower():
        return ("인증에 실패했습니다 — Client ID / Secret 이 맞는지 보세요. "
                "NAVER API HUB 키와 옛 developers.naver.com 키는 서로 다릅니다.")
    if ecode == "210":
        return ("키는 맞지만 이 API 를 쓸 권한이 없습니다. "
                "콘솔에서 Application 에 '검색'·'검색어 트렌드' 를 선택해 주세요.")
    if ecode in ("400", "410", "420"):
        return "호출 한도를 넘었습니다. 잠시 뒤 다시 해 보세요."
    if ecode == "300" or code == 404:
        return "그 주소가 없습니다 — 창구(HUB / 옛 방식)가 안 맞을 수 있습니다."
    return f"네이버가 거부했습니다 ({code}{' · ' + ecode if ecode else ''})" + \
           (f" — {msg}" if msg else "")


# ═══════════════════════════════════════════════════════════════
#  저장 — 스키마의 yt_* / text_document 로 들어간다
# ═══════════════════════════════════════════════════════════════
DDL = """
CREATE TABLE IF NOT EXISTS yt_video (
  video_id      TEXT PRIMARY KEY,
  channel_id    TEXT,
  channel_title TEXT,
  title         TEXT,
  description   TEXT,
  published_at  TEXT,
  query         TEXT,                  -- 어느 검색어로 찾았나
  quality_status TEXT DEFAULT 'active', -- active | quarantined
  quality_reason TEXT,
  has_caption INTEGER,
  transcript_status TEXT DEFAULT 'none',
  transcript_error TEXT,
  transcript_checked_at TEXT,
  replies_synced_at TEXT,
  first_seen_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS yt_video_stat (
  video_id      TEXT NOT NULL,
  stat_date     TEXT NOT NULL,
  view_count    INTEGER,
  like_count    INTEGER,
  comment_count INTEGER,
  PRIMARY KEY (video_id, stat_date)
);
CREATE INDEX IF NOT EXISTS ix_ytv_q ON yt_video (query, published_at DESC);
CREATE TABLE IF NOT EXISTS yt_transcript (
  video_id TEXT PRIMARY KEY,
  origin TEXT NOT NULL,
  lang TEXT,
  full_text TEXT NOT NULL,
  segments TEXT NOT NULL DEFAULT '[]',
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS yt_transcript_correction (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  video_id TEXT NOT NULL,
  start REAL DEFAULT 0,
  dur REAL DEFAULT 0,
  original TEXT NOT NULL,
  term_key TEXT NOT NULL,
  canonical TEXT NOT NULL,
  facet TEXT NOT NULL,
  method TEXT NOT NULL,
  confidence REAL NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now')),
  UNIQUE(video_id,start,original,term_key,method)
);
CREATE TABLE IF NOT EXISTS yt_asr_queue (
  video_id TEXT PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'pending',
  reason TEXT,
  priority INTEGER DEFAULT 50,
  attempts INTEGER DEFAULT 0,
  last_error TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

-- ★ 팀이 추려 둔 채널
--   검색(100 units)을 건너뛰고 이 채널들만 훑으면 1 unit 이면 된다.
--   enabled 로 껐다 켰다 할 수 있게 둔다 — 지웠다 다시 넣으면
--   '왜 뺐더라'가 기록에 안 남는다.
CREATE TABLE IF NOT EXISTS yt_channel (
  channel_id    TEXT PRIMARY KEY,
  handle        TEXT,
  title         TEXT,
  thumbnail_url TEXT,
  description   TEXT,
  subscriber_count INTEGER,
  video_count   INTEGER,
  uploads_playlist_id TEXT,
  enabled       INTEGER DEFAULT 1,
  gender        TEXT,                -- 남성|여성|공용 — 팀이 추릴 때 붙인 구분
  note          TEXT,
  added_by      TEXT,                -- 검색 | 주소 | 파일
  added_at      TEXT DEFAULT (datetime('now')),
  last_synced_at TEXT
);
"""


def install(store):
    with store._lock:
        store._conn.executescript(DDL)
        have = {r[1] for r in store._conn.execute("PRAGMA table_info(yt_video)")}
        for name, typ in (("quality_status", "TEXT DEFAULT 'active'"),
                          ("quality_reason", "TEXT"), ("has_caption", "INTEGER"),
                          ("transcript_status", "TEXT DEFAULT 'none'"),
                          ("transcript_error", "TEXT"),
                          ("transcript_checked_at", "TEXT"),
                          ("replies_synced_at", "TEXT")):
            if name not in have:
                store._conn.execute(f"ALTER TABLE yt_video ADD COLUMN {name} {typ}")
        # 기능 추가 전에 이미 자막 없음으로 판정된 영상도 ASR 후보에서 빠지지 않는다.
        store._conn.execute(
            "INSERT OR IGNORE INTO yt_asr_queue(video_id,status,reason,priority) "
            "SELECT video_id,'pending',transcript_status,50 FROM yt_video "
            "WHERE transcript_status IN ('disabled','unavailable','restricted')")
        store._conn.commit()


_CUE_TIME = re.compile(
    r"(?P<h1>\d{1,2}:)?(?P<m1>\d{1,2}):(?P<s1>\d{2})[,.](?P<ms1>\d{3})\s*-->\s*"
    r"(?P<h2>\d{1,2}:)?(?P<m2>\d{1,2}):(?P<s2>\d{2})[,.](?P<ms2>\d{3})")


def parse_transcript(raw: str) -> tuple[str, list[dict]]:
    """VTT/SRT 또는 일반 텍스트를 검색 가능한 본문과 타임라인으로 바꾼다."""
    text = str(raw or "").replace("\r\n", "\n").strip()
    if not text:
        return "", []
    if len(text) > 500_000:
        raise ValueError("자막은 한 영상당 500,000자까지만 넣을 수 있습니다.")
    lines, segments, current = text.split("\n"), [], None
    for line in lines:
        line = line.strip()
        match = _CUE_TIME.search(line)
        if match:
            def seconds(prefix):
                hour = int((match.group("h" + prefix) or "0:").rstrip(":"))
                return hour * 3600 + int(match.group("m" + prefix)) * 60 + \
                    int(match.group("s" + prefix)) + int(match.group("ms" + prefix)) / 1000
            current = {"start": seconds("1"),
                       "dur": max(0, seconds("2") - seconds("1")), "text": ""}
            segments.append(current)
        elif line and line != "WEBVTT" and not line.isdigit() and not line.startswith(("NOTE", "Kind:", "Language:")):
            clean = re.sub(r"<[^>]+>", "", line).strip()
            if current is not None:
                current["text"] = (current["text"] + " " + clean).strip()
    segments = [s for s in segments if s["text"]]
    if segments:
        full = " ".join(s["text"] for s in segments)
    else:
        full = re.sub(r"\s+", " ", text)
    return full.strip(), segments


def save_transcript(store, video_id: str, raw: str, *, origin: str = "caption",
                    lang: str = "ko") -> dict:
    install(store)
    if origin not in ("caption", "asr", "ocr"):
        raise ValueError("origin은 caption, asr 또는 ocr이어야 합니다.")
    full, segments = parse_transcript(raw)
    if len(full) < 10:
        raise ValueError("분석할 자막 내용이 너무 짧습니다.")
    with store.tx() as c:
        video = c.execute("SELECT * FROM yt_video WHERE video_id=?", (video_id,)).fetchone()
        if not video:
            raise ValueError("저장된 영상이 아닙니다.")
        c.execute("INSERT INTO yt_transcript(video_id,origin,lang,full_text,segments,created_at) "
                  "VALUES (?,?,?,?,?,datetime('now')) ON CONFLICT(video_id) DO UPDATE SET "
                  "origin=excluded.origin,lang=excluded.lang,full_text=excluded.full_text,"
                  "segments=excluded.segments,created_at=excluded.created_at",
                  (video_id, origin, lang, full, json.dumps(segments, ensure_ascii=False)))
        c.execute("UPDATE yt_video SET has_caption=?,transcript_status=?,transcript_error=NULL,"
                  "transcript_checked_at=datetime('now') WHERE video_id=?",
                  (1 if origin == "caption" else None, origin, video_id))
        c.execute("DELETE FROM yt_asr_queue WHERE video_id=?", (video_id,))
        if origin != "ocr":
            # OCR은 마지막 fallback이다. caption/충분한 ASR이 새로 저장되면 대기를 취소한다.
            try:
                c.execute("DELETE FROM yt_ocr_queue WHERE video_id=?", (video_id,))
            except Exception:
                pass
        c.execute("DELETE FROM yt_transcript_correction WHERE video_id=?", (video_id,))
        existing = c.execute("SELECT id FROM text_document WHERE source_code='youtube' "
                             "AND doc_kind='yt_transcript' AND product_uid=? LIMIT 1",
                             (f"yt:{video_id}",)).fetchone()
        if existing:
            text_id = existing[0]
            # The transcript is the source text for every downstream result.  Do not
            # leave an older LLM/entity judgment attached when an operator replaces it.
            for table in ("text_entity_opinion", "text_entity_mention",
                          "text_entity_resolution", "text_llm_analysis"):
                c.execute(f"DELETE FROM {table} WHERE text_document_id=?", (text_id,))
            c.execute("UPDATE text_document SET body=?,published_at=? WHERE id=?",
                      (full, video["published_at"], text_id))
        else:
            c.execute("INSERT INTO text_document(source_code,doc_kind,product_uid,body,"
                      "published_at,author_hash) VALUES ('youtube','yt_transcript',?,?,?,?)",
                      (f"yt:{video_id}", full, video["published_at"], f"transcript:{video_id}"))
            text_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    linker = store.text_entity_linker
    corrections = []
    try:
        global _TRANSCRIPT_CORRECTOR
        from pathlib import Path
        from .transcript_correction import TranscriptCorrector
        if _TRANSCRIPT_CORRECTOR is None:
            _TRANSCRIPT_CORRECTOR = TranscriptCorrector(
                Path(__file__).resolve().parent.parent / "config" / "lexicon_master.json")
        corrections = _TRANSCRIPT_CORRECTOR.scan(full, segments)
    except (OSError, ValueError):
        corrections = []
    if corrections:
        with store.tx() as c:
            c.executemany(
                "INSERT OR REPLACE INTO yt_transcript_correction "
                "(video_id,start,dur,original,term_key,canonical,facet,method,confidence,status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(video_id, x["start"], x["dur"], x["original"], x["term_key"],
                  x["canonical"], x["facet"], x["method"], x["confidence"], x["status"])
                 for x in corrections])
    if linker is not None:
        result, mentions = linker.rules_only({"id": text_id, "source_code": "youtube",
                                              "doc_kind": "yt_transcript", "body": full})
        for x in corrections:
            if x["status"] == "confirmed":
                mentions.append({"term_key": x["term_key"], "canonical": x["canonical"],
                                 "facet": x["facet"], "surface": x["original"],
                                 "status": "confirmed", "confidence": x["confidence"],
                                 "evidence": x["original"], "method": "asr_dictionary",
                                 "role": "target"})
                result["resolution_status"] = "confirmed"
        store.put_entity_resolution(text_id, result, mentions)
    return {"video_id": video_id, "origin": origin, "lang": lang,
            "characters": len(full), "segments": len(segments), "text_document_id": text_id,
            "corrections": len(corrections),
            "llm_review": sum(x["status"] == "review" for x in corrections)}


def _vtt_from_segments(rows) -> str:
    """youtube-transcript-api의 버전별 객체/딕셔너리를 내부 VTT로 정규화한다."""
    def value(row, key, default=None):
        return row.get(key, default) if isinstance(row, dict) else getattr(row, key, default)

    def stamp(sec):
        ms = max(0, round(float(sec or 0) * 1000))
        h, rest = divmod(ms, 3_600_000)
        m, rest = divmod(rest, 60_000)
        s, milli = divmod(rest, 1000)
        return f"{h:02d}:{m:02d}:{s:02d}.{milli:03d}"

    out = ["WEBVTT", ""]
    for row in rows:
        text = str(value(row, "text", "") or "").strip()
        if not text:
            continue
        start = float(value(row, "start", 0) or 0)
        duration = max(.001, float(value(row, "duration", value(row, "dur", 0)) or 0))
        out += [f"{stamp(start)} --> {stamp(start + duration)}", text, ""]
    return "\n".join(out)


def fetch_public_transcript(store, video_id: str, *, force: bool = False,
                            api_factory=None) -> dict:
    """비공식 공개 자막 어댑터. 실패는 영상/댓글 수집을 중단시키지 않는다."""
    install(store)
    with store._lock:
        video = store._conn.execute(
            "SELECT video_id,transcript_status FROM yt_video WHERE video_id=?", (video_id,)).fetchone()
    if not video:
        raise ValueError("저장된 영상이 아닙니다.")
    if video["transcript_status"] in ("caption", "asr") and not force:
        return {"video_id": video_id, "status": "skipped", "reason": "already_saved"}
    try:
        if api_factory is None:
            from youtube_transcript_api import YouTubeTranscriptApi
            api_factory = YouTubeTranscriptApi
        api = api_factory()
        # 1.x API. 한국어를 먼저 고르되 영어 자동 자막도 분석 원문으로 허용한다.
        if hasattr(api, "fetch"):
            fetched = api.fetch(video_id, languages=["ko", "en"])
            rows = list(fetched)
            lang = getattr(fetched, "language_code", None) or "unknown"
        else:  # 0.x 호환
            rows = api.get_transcript(video_id, languages=["ko", "en"])
            lang = "unknown"
        result = save_transcript(store, video_id, _vtt_from_segments(rows),
                                 origin="caption", lang=lang)
        return {**result, "status": "saved"}
    except ImportError:
        status, message = "not_installed", "youtube-transcript-api가 설치되지 않았습니다."
    except Exception as exc:
        name = type(exc).__name__
        mapped = {"TranscriptsDisabled": "disabled", "NoTranscriptFound": "unavailable",
                  "VideoUnavailable": "unavailable", "RequestBlocked": "blocked",
                  "IpBlocked": "blocked", "AgeRestricted": "restricted"}
        status = mapped.get(name, "error")
        message = f"{name}: {str(exc)[:300]}"
    with store.tx() as c:
        c.execute("UPDATE yt_video SET transcript_status=?,transcript_error=?,"
                  "transcript_checked_at=datetime('now') WHERE video_id=?",
                  (status, message, video_id))
        if status in ("disabled", "unavailable", "restricted"):
            c.execute("INSERT INTO yt_asr_queue(video_id,status,reason,priority) "
                      "VALUES (?,'pending',?,50) ON CONFLICT(video_id) DO UPDATE SET "
                      "status='pending',reason=excluded.reason,updated_at=datetime('now')",
                      (video_id, status))
    return {"video_id": video_id, "status": status, "error": message}


def fetch_missing_transcripts(store, *, limit: int = 20, force: bool = False,
                              video_ids: list[str] | None = None,
                              api_factory=None, on_event=None,
                              delay_seconds: float = 2.0) -> dict:
    """저장된 패션 영상의 공개 자막을 제한된 묶음으로 자동 수집한다."""
    install(store)
    say = on_event or (lambda *_: None)
    limit = max(1, min(int(limit), 100))
    with store._lock:
        recently_blocked = store._conn.execute(
            "SELECT count(*) FROM yt_video WHERE transcript_status='blocked' AND "
            "transcript_checked_at >= datetime('now','-6 hours')").fetchone()[0]
        if recently_blocked and not force:
            return {"attempted": 0, "counts": {"deferred": 0}, "details": [],
                    "circuit_open": True,
                    "message": "YouTube IP 차단 감지 후 6시간 냉각 중입니다."}
        args, extra = [], ""
        if video_ids:
            ids = list(dict.fromkeys(video_ids))[:limit]
            extra = f" AND video_id IN ({','.join('?' for _ in ids)})"
            args.extend(ids)
        elif not force:
            extra = (" AND (COALESCE(transcript_status,'none') IN "
                     "('none','error','not_installed') OR (transcript_status='blocked' AND "
                     "transcript_checked_at < datetime('now','-6 hours'))) ")
        rows = [r[0] for r in store._conn.execute(
            "SELECT video_id FROM yt_video WHERE COALESCE(quality_status,'active')='active'" +
            extra + " ORDER BY published_at DESC LIMIT ?", (*args, limit))]
    counts = Counter()
    details = []
    attempted = 0
    for index, video_id in enumerate(rows):
        if index and api_factory is None and delay_seconds > 0:
            time.sleep(min(float(delay_seconds), 10.0))
        got = fetch_public_transcript(store, video_id, force=force, api_factory=api_factory)
        attempted += 1
        counts[got["status"]] += 1
        details.append(got)
        say("info" if got["status"] == "saved" else "warn",
            {"msg": f"자막 {got['status']} · {video_id}"})
        if got["status"] == "blocked":
            deferred = len(rows) - attempted
            counts["deferred"] += deferred
            say("warn", {"msg": f"IP 차단 감지 · 남은 {deferred}건은 호출하지 않고 보류"})
            break
    return {"attempted": attempted, "counts": dict(counts), "details": details,
            "circuit_open": bool(counts.get("blocked")),
            "message": "IP 차단으로 남은 호출을 중단했습니다." if counts.get("blocked") else ""}


def transcript_summary(store) -> dict:
    install(store)
    with store._lock:
        statuses = {r[0] or "none": r[1] for r in store._conn.execute(
            "SELECT COALESCE(transcript_status,'none'),count(*) FROM yt_video GROUP BY 1")}
        rows = [dict(r) for r in store._conn.execute(
            "SELECT v.video_id,v.channel_title,v.title,v.published_at,"
            "COALESCE(v.transcript_status,'none') transcript_status,t.origin,t.lang,"
            "v.transcript_error,v.transcript_checked_at,length(t.full_text) characters,"
            "json_array_length(COALESCE(t.segments,'[]')) segments "
            "FROM yt_video v LEFT JOIN yt_transcript t ON t.video_id=v.video_id "
            "ORDER BY CASE WHEN t.video_id IS NULL THEN 0 ELSE 1 END,v.published_at DESC LIMIT 100")]
        correction_counts = {r[0]: r[1] for r in store._conn.execute(
            "SELECT status,count(*) FROM yt_transcript_correction GROUP BY status")}
        asr_counts = {r[0]: r[1] for r in store._conn.execute(
            "SELECT status,count(*) FROM yt_asr_queue GROUP BY status")}
    return {"statuses": statuses, "corrections": correction_counts,
            "asr_queue": asr_counts, "rows": rows}


def asr_queue(store, *, limit: int = 100) -> dict:
    install(store)
    with store._lock:
        rows = [dict(r) for r in store._conn.execute(
            "SELECT q.*,v.channel_title,v.title,v.published_at FROM yt_asr_queue q "
            "JOIN yt_video v ON v.video_id=q.video_id "
            "ORDER BY q.priority DESC,v.published_at DESC LIMIT ?", (min(limit, 200),))]
        counts = {r[0]: r[1] for r in store._conn.execute(
            "SELECT status,count(*) FROM yt_asr_queue GROUP BY status")}
    from .youtube_asr import explain_error
    for row in rows:
        row["error_help"] = explain_error(row.get("last_error")) if row.get("last_error") else ""
    return {"counts": counts, "rows": rows}


def backfill_youtube_replies(store, *, limit: int = 10, comments_per_video: int = 100,
                             youtube=None, video_ids: list[str] | None = None,
                             on_event=None) -> dict:
    """기존 영상의 실제 답글 본문을 백필하고 영상별 결과/실패 사유를 돌려준다."""
    install(store)
    yt = youtube or YouTube()
    if not yt.ready:
        raise NotConfigured("YOUTUBE_API_KEY 가 없습니다")
    say = on_event or (lambda *_: None)
    limit = max(1, min(int(limit), 50))
    comments_per_video = max(10, min(int(comments_per_video), 300))
    args, extra = [], ""
    if video_ids:
        ids = list(dict.fromkeys(str(x) for x in video_ids if str(x).strip()))[:limit]
        extra = f" AND video_id IN ({','.join('?' for _ in ids)})"
        args.extend(ids)
    else:
        extra = " AND replies_synced_at IS NULL"
    with store._lock:
        videos = [dict(r) for r in store._conn.execute(
            "SELECT video_id,channel_id,channel_title,title,published_at FROM yt_video "
            "WHERE COALESCE(quality_status,'active')='active'" + extra +
            " ORDER BY published_at DESC LIMIT ?", (*args, limit))]
    lex = _lexicon()
    result = {"attempted": 0, "succeeded": 0, "failed": 0, "replies_seen": 0,
              "replies_saved": 0, "creator_replies_saved": 0, "details": [],
              "quota": 0}
    for video in videos:
        video_id = video["video_id"]
        detail = {"video_id": video_id, "title": video.get("title") or "",
                  "status": "failed", "replies_seen": 0, "replies_saved": 0,
                  "creator_replies_saved": 0}
        result["attempted"] += 1
        try:
            rows = yt.comments(video_id, limit=comments_per_video,
                               video_channel_id=video.get("channel_id") or "")
            parent_ids, parent_texts = {}, {}
            for row in rows:
                if not str(row.get("text") or "").strip():
                    continue
                is_reply = bool(row.get("is_reply"))
                comment_id = row.get("comment_id") or ""
                if not is_reply:
                    parent_texts[comment_id] = row["text"]
                parent_comment_id = row.get("parent_comment_id") or ""
                parent_text = parent_texts.get(parent_comment_id, "")
                analysis_text = (f"질문: {parent_text}\n답글: {row['text']}"
                                 if is_reply and parent_text else row["text"])
                judged = judge_comment(analysis_text, lexicon=lex)
                creator = bool(is_reply and row.get("is_creator_reply") and parent_text)
                if not judged["keep"] and not creator:
                    continue
                text_id = store.put_text(
                    "youtube", "yt_comment_reply" if is_reply else "yt_comment",
                    analysis_text, parent_id=parent_ids.get(parent_comment_id),
                    product_uid=f"yt:{video_id}", published_at=row.get("published_at"),
                    like_count=row.get("like_count") or 0,
                    reply_count=row.get("reply_count") or 0,
                    author_hash=row.get("author_hash"))
                if not is_reply and text_id:
                    parent_ids[comment_id] = text_id
                if is_reply:
                    detail["replies_seen"] += 1
                    if text_id:
                        detail["replies_saved"] += 1
                        if row.get("is_creator_reply"):
                            detail["creator_replies_saved"] += 1
            with store.tx() as c:
                c.execute("UPDATE yt_video SET replies_synced_at=datetime('now') "
                          "WHERE video_id=?", (video_id,))
            detail["status"] = "saved" if detail["replies_saved"] else "no_replies"
            detail["message"] = ("답글 본문 저장 완료" if detail["replies_saved"] else
                                 "공개된 답글이 없거나 패션 문맥 필터를 통과하지 못했습니다.")
            result["succeeded"] += 1
            for key in ("replies_seen", "replies_saved", "creator_replies_saved"):
                result[key] += detail[key]
            say("info", {"msg": f"답글 백필 {detail['status']} · {video_id}"})
        except Exception as exc:
            detail["error"] = f"{type(exc).__name__}: {str(exc)[:350]}"
            detail["message"] = ("댓글이 비활성화됐거나 영상 접근이 제한됐습니다."
                                 if any(k in str(exc).lower() for k in YouTube._COMMENTS_OFF)
                                 else "YouTube API 오류입니다. 기술 오류를 확인하세요.")
            result["failed"] += 1
            say("warn", {"msg": f"답글 백필 실패 · {video_id}: {exc}"})
        result["details"].append(detail)
    result["quota"] = int(getattr(yt, "used", 0) or 0)
    return result


# ── 채널 목록 관리 ────────────────────────────────────────────
def channels(store, only_on: bool = False) -> list[dict]:
    install(store)
    q = "SELECT * FROM yt_channel"
    if only_on:
        q += " WHERE enabled = 1"
    q += " ORDER BY enabled DESC, subscriber_count DESC"
    with store._lock:
        return [dict(r) for r in store._conn.execute(q)]


def _add_missing_cols(store):
    """옛 DB 에 새 칸을 조용히 더한다. CREATE TABLE IF NOT EXISTS 는
    이미 있는 표를 안 고쳐 주므로, 없는 칸만 채워 넣는다."""
    with store._lock:
        have = {r[1] for r in store._conn.execute("PRAGMA table_info(yt_channel)")}
        for col, ddl in (("gender", "TEXT"), ("added_by", "TEXT")):
            if col not in have:
                store._conn.execute(f"ALTER TABLE yt_channel ADD COLUMN {col} {ddl}")
        store._conn.commit()


def import_channel_file(store, data) -> dict:
    """팀이 정리해 둔 목록 파일을 그대로 담는다. **API 를 한 번도 안 부른다.**

    ★ 왜 이 길이 필요한가
      이름으로 검색하면 채널 하나당 101칸이다. 스무 개면 2,020칸 —
      하루 몫의 5분의 1을 목록 만드는 데 태운다.
      채널 ID 를 이미 아는데 검색할 이유가 없다. 여기서는 0칸으로 담고,
      구독자 수 같은 부가 정보는 [정보 새로고침] 이 50개를 1칸에 받아 온다.

    받아들이는 모양
      [{"channel_id": "UC…", "name": "…", "gender": "남성"}, …]
      키 이름이 title·channel_title 이어도 알아듣는다.
    """
    if isinstance(data, dict):
        # {"channels": [...]} 처럼 감싸 온 경우
        for k in ("channels", "items", "list", "data"):
            if isinstance(data.get(k), list):
                data = data[k]
                break
    if not isinstance(data, list):
        return {"ok": False, "error": "채널 목록(배열)이 아닙니다."}

    install(store)
    _add_missing_cols(store)
    rows, failed = [], []
    for i, c in enumerate(data):
        if not isinstance(c, dict):
            failed.append({"line": str(c)[:40], "why": "형식이 아닙니다"})
            continue
        cid = str(c.get("channel_id") or c.get("id") or "").strip()
        name = (c.get("name") or c.get("title") or c.get("channel_title") or "").strip()
        if not _CHID_RX.fullmatch(cid):
            failed.append({"line": name or str(c)[:40],
                           "why": f"채널 ID 가 아닙니다 ('{cid[:26]}')"})
            continue
        rows.append({"channel_id": cid, "title": name or cid,
                     "handle": (c.get("handle") or "").lstrip("@") or None,
                     "gender": (c.get("gender") or "").strip() or None})
    n = save_channels(store, rows, added_by="파일")
    return {"ok": True, "saved": n, "lines": len(data),
            "channels": rows, "failed": failed, "quota": 0}


_CHID_RX = re.compile(r"UC[A-Za-z0-9_\-]{22}")


def save_channels(store, rows: list[dict], added_by: str = "") -> int:
    """찾아낸 채널을 담는다. 이미 있으면 이름·구독자만 새로 고친다.

    enabled 는 건드리지 않는다 — 꺼 둔 채널을 다시 담았다고
    멋대로 켜지면 왜 켜졌는지 알 수가 없다.
    """
    install(store)
    _add_missing_cols(store)
    n = 0
    with store._lock:
        for c in rows:
            if not c.get("channel_id"):
                continue
            # ★ COALESCE 로 덮는다.
            #   파일에는 구독자 수가 없고 API 응답에는 성별이 없다.
            #   그냥 excluded 로 덮으면 한쪽이 다른 쪽을 지운다 —
            #   파일로 담은 뒤 새로고침하면 성별이 날아가는 식이다.
            store._conn.execute(
                """INSERT INTO yt_channel
                   (channel_id, handle, title, thumbnail_url, description,
                    subscriber_count, video_count, uploads_playlist_id,
                    gender, added_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(channel_id) DO UPDATE SET
                     handle=COALESCE(excluded.handle, yt_channel.handle),
                     title=COALESCE(excluded.title, yt_channel.title),
                     thumbnail_url=COALESCE(excluded.thumbnail_url, yt_channel.thumbnail_url),
                     description=COALESCE(excluded.description, yt_channel.description),
                     subscriber_count=COALESCE(excluded.subscriber_count, yt_channel.subscriber_count),
                     video_count=COALESCE(excluded.video_count, yt_channel.video_count),
                     uploads_playlist_id=COALESCE(excluded.uploads_playlist_id,
                                                  yt_channel.uploads_playlist_id),
                     gender=COALESCE(excluded.gender, yt_channel.gender),
                     added_by=COALESCE(yt_channel.added_by, excluded.added_by)""",
                (c["channel_id"], c.get("handle"), c.get("title"),
                 c.get("thumbnail_url"), c.get("description"),
                 c.get("subscriber_count"), c.get("video_count"),
                 c.get("uploads_playlist_id"), c.get("gender"), added_by or None))
            n += 1
        store._conn.commit()
    return n


def set_channel(store, channel_id: str, *, enabled=None, note=None,
                gender=None, remove: bool = False) -> bool:
    install(store)
    with store._lock:
        if remove:
            cur = store._conn.execute(
                "DELETE FROM yt_channel WHERE channel_id=?", (channel_id,))
        elif enabled is not None:
            cur = store._conn.execute(
                "UPDATE yt_channel SET enabled=? WHERE channel_id=?",
                (int(bool(enabled)), channel_id))
        elif note is not None:
            cur = store._conn.execute(
                "UPDATE yt_channel SET note=? WHERE channel_id=?",
                (note, channel_id))
        elif gender is not None:
            value = gender if gender in ("남성", "여성", "공용") else None
            cur = store._conn.execute(
                "UPDATE yt_channel SET gender=? WHERE channel_id=?",
                (value, channel_id))
        else:
            return False
        store._conn.commit()
        return cur.rowcount > 0


def refresh_channels(store, only_missing: bool = True) -> dict:
    """담아 둔 채널의 이름·구독자·업로드 목록을 받아 온다.

    ★ 50개를 한 번에 묶어 부른다 — **1칸**이다.
      하나씩 부르면 20칸, 이름으로 검색하면 2,020칸이다.
      같은 정보를 받는 데 값이 2,000배 차이 난다.
    """
    yt = YouTube()
    if not yt.ready:
        raise NotConfigured("YOUTUBE_API_KEY 가 없습니다")
    install(store)
    _add_missing_cols(store)
    want = channels(store)
    if only_missing:
        want = [c for c in want if not c.get("uploads_playlist_id")
                or not c.get("subscriber_count")]
    ids = [c["channel_id"] for c in want]
    if not ids:
        return {"ok": True, "updated": 0, "quota": 0,
                "message": "새로 받아 올 게 없습니다."}
    got = []
    for i in range(0, len(ids), 50):
        got += yt.channels(ids=ids[i:i + 50])
    n = save_channels(store, got)
    missing = set(ids) - {c["channel_id"] for c in got}
    return {"ok": True, "updated": n, "quota": yt.used,
            "missing": sorted(missing),
            "message": f"{n}개를 새로 받았습니다 ({yt.used}칸 씀)."
                       + (f" 유튜브에 없는 채널 {len(missing)}개는 그대로 뒀습니다."
                          if missing else "")}


def add_channels_from_text(store, text: str) -> dict:
    """주소·핸들을 줄바꿈으로 여러 개 붙여 넣은 것을 한 번에 등록한다.

    한 줄에 하나씩 본다. 알아본 것만 담고, 못 알아본 줄은
    **왜 못 알아봤는지와 함께** 돌려준다 — 스무 줄 붙여 넣었는데
    "18개 등록됨"만 뜨면 나머지 둘을 찾느라 다시 헤맨다.
    """
    yt = YouTube()
    if not yt.ready:
        raise NotConfigured("YOUTUBE_API_KEY 가 없습니다")
    lines = [ln.strip() for ln in re.split(r"[\n,]", text or "") if ln.strip()]
    ids, handles, queries, failed = [], [], [], []
    for ln in lines:
        kind, val = YouTube.parse_channel_ref(ln)
        if kind == "id":
            ids.append(val)
        elif kind == "handle":
            handles.append((ln, val))
        elif kind == "query":
            queries.append((ln, val))

    found: dict[str, dict] = {}
    for c in (yt.channels(ids=ids) if ids else []):
        found[c["channel_id"]] = c
    miss_id = set(ids) - set(found)
    for i in miss_id:
        failed.append({"line": i, "why": "그런 채널 ID 가 없습니다"})

    for raw, h in handles:
        try:
            got = yt.channels(handle=h)
        except Exception as e:
            failed.append({"line": raw, "why": str(e)[:80]})
            continue
        if got:
            found[got[0]["channel_id"]] = got[0]
        else:
            failed.append({"line": raw, "why": f"@{h} 라는 채널을 못 찾았습니다"})

    # ★ 주소도 핸들도 아닌 줄은 **담지 않는다**
    #   이름으로 검색해서 첫 결과를 담으면, 메모 한 줄이 섞여 들어갔을 때
    #   엉뚱한 채널이 조용히 목록에 앉는다. 담긴 걸 눈치채는 건 한참 뒤
    #   "왜 이 채널 영상이 들어오지?" 할 때다.
    #   여기서는 못 알아봤다고 말하고, 검색은 [검색해서 담기] 쪽에 맡긴다.
    for raw, q in queries:
        failed.append({"line": raw,
                       "why": "주소·@핸들·채널ID 가 아닙니다. "
                              "[검색해서 담기] 에서 찾아 주세요"})

    saved = save_channels(store, list(found.values()))
    return {"ok": True, "saved": saved, "lines": len(lines),
            "channels": list(found.values()), "failed": failed,
            "quota": yt.used}


PROBLEMS = None          # 서버가 켤 때 꽂아 준다


def _lexicon():
    """어휘사전. 없으면 그냥 안 쓴다 — 필터가 죽으면 안 된다."""
    try:
        from pathlib import Path

        from .lexicon import Lexicon
        p = Path(__file__).resolve().parent.parent / "config" / "lexicon.yaml"
        return Lexicon(str(p)) if p.exists() else None
    except Exception:
        return None


_FASHION_VIDEO = re.compile(
    r"패션|코디|스타일|데일리룩|하객룩|출근룩|데이트룩|OOTD|GRWM"
    r"|옷|착장|신상|아이템|장바구니|드레스룸|룩북|쇼핑|편집샵|플리마켓",
    re.I)
_VIDEO_FACETS = {"style", "item", "material", "fit", "brand"}


def judge_video(video: dict, lexicon=None) -> dict:
    """패션 채널의 생활 영상과 검색 결과의 엉뚱한 영상을 걷어낸다.

    채널 자체가 패션이어도 향수·피부관리·여행 영상은 올라온다. 제목에
    명시적인 패션 문맥이 있거나, 상품/스타일/핏/소재 어휘가 있어야만
    댓글 수집 단계로 넘긴다. 설명은 채널 공통 홍보문이 섞이므로 제목보다
    약하게 보고 서로 다른 유효 어휘가 두 개 이상일 때만 보조 근거로 쓴다.
    """
    title = str(video.get("title") or "")
    desc = str(video.get("description") or "")[:500]

    def useful(text):
        if lexicon is None:
            return []
        try:
            return [(term, facet) for term, facet in lexicon.extract(text, "free")
                    if facet in _VIDEO_FACETS]
        except Exception:
            return []

    title_terms = useful(title)
    if _FASHION_VIDEO.search(title):
        return {"keep": True, "why": "fashion_context",
                "terms": title_terms + useful(desc)}
    if title_terms:
        return {"keep": True, "why": "fashion_term", "terms": title_terms}
    desc_terms = useful(desc)
    if len({term for term, _ in desc_terms}) >= 2:
        return {"keep": True, "why": "description_terms", "terms": desc_terms}
    return {"keep": False, "why": "패션 문맥이 없는 영상", "terms": []}


def collect_youtube(store, keywords: list[str] | None = None, *, days=30, per_kw=15,
                    comments_per_video=60, on_event=None,
                    mode: str = "both", channel_ids: list[str] | None = None,
                    videos_for_comments: int = 8) -> dict:
    """영상·통계·댓글을 모아 저장한다.

    mode
      'channels'  추려 둔 채널의 최근 영상만 (싸다 — 채널당 1 unit)
      'keywords'  검색어로 (검색 한 번에 100 units)
      'both'      채널 먼저, 그다음 검색어

    ★ 왜 채널 쪽이 훨씬 싼가
      search 는 100 units, playlistItems 는 1 unit 이다. 하루 10,000 units
      기준으로 검색은 100번이 한계지만, 채널 20개를 훑는 건 20 units 다.
      "누가 말하는지 이미 안다"는 정보가 곧 할당량을 아끼는 길이다.

    댓글은 text_document 로 들어간다 — 상품 리뷰와 같은 표다.
    doc_kind 로 구분하므로 나중에 따로 뽑을 수 있다.
    """
    say = on_event or (lambda *_: None)
    keywords = keywords or []
    yt = YouTube()
    if not yt.ready:
        raise NotConfigured("YOUTUBE_API_KEY 가 없습니다")
    install(store)

    total = {"videos": 0, "comments": 0, "quota": 0,
             "keywords": 0, "channels": 0, "mode": mode,
             # 왜 이만큼만 담겼는지 설명할 수 있어야 한다
             "comments_seen": 0, "videos_tried": 0, "comment_fail": 0,
             "replies_seen": 0, "replies_saved": 0, "creator_replies_saved": 0,
             "videos_seen": 0, "videos_dropped": 0,
             "new_videos": 0, "existing_videos": 0, "video_contexts": 0,
             "transcripts_saved": 0, "transcripts_failed": 0,
             "transcript_circuit_open": False,
             "kept_why": {}, "dropped": {}, "trend_candidates": []}
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    lex = _lexicon()
    trend_terms = Counter()

    def _save(vids, tag):
        """영상·통계 저장 + 댓글까지. 채널이든 검색어든 같은 길을 탄다."""
        seen_now = len(vids)
        total["videos_seen"] += seen_now
        judged = [(v, judge_video(v, lexicon=lex)) for v in vids]
        vids = [v for v, result in judged if result["keep"]]
        for _video, result in judged:
            if result["keep"]:
                trend_terms.update(term for term, _facet in result.get("terms") or [])
        total["videos_dropped"] += seen_now - len(vids)
        if not vids:
            return
        ids = [v["video_id"] for v in vids]
        with store._lock:
            marks = ",".join("?" for _ in ids)
            existing = {r[0] for r in store._conn.execute(
                f"SELECT video_id FROM yt_video WHERE video_id IN ({marks})", ids)}
            have_comments = {r[0][3:] for r in store._conn.execute(
                f"SELECT DISTINCT product_uid FROM text_document WHERE source_code='youtube' "
                f"AND doc_kind='yt_comment' AND product_uid IN ({marks})",
                [f"yt:{x}" for x in ids])} if ids else set()
            replies_synced = {r[0] for r in store._conn.execute(
                f"SELECT video_id FROM yt_video WHERE video_id IN ({marks}) "
                "AND replies_synced_at IS NOT NULL", ids)} if ids else set()
        total["new_videos"] += len(ids) - len(existing)
        total["existing_videos"] += len(existing)
        stats = yt.video_stats([v["video_id"] for v in vids])
        with store._lock:
            for v in vids:
                store._conn.execute(
                    """INSERT INTO yt_video
                       (video_id, channel_id, channel_title, title, description,
                        published_at, query) VALUES (?,?,?,?,?,?,?)
                       ON CONFLICT(video_id) DO UPDATE SET
                         channel_id=excluded.channel_id,channel_title=excluded.channel_title,
                         title=excluded.title,description=excluded.description,
                         published_at=excluded.published_at,query=excluded.query""",
                    (v["video_id"], v.get("channel_id"), v.get("channel_title"),
                     v.get("title"), v.get("description"),
                     v.get("published_at"), tag))
                st = stats.get(v["video_id"]) or {}
                if st:
                    store._conn.execute(
                        """INSERT OR REPLACE INTO yt_video_stat
                           (video_id, stat_date, view_count, like_count, comment_count)
                           VALUES (?,?,?,?,?)""",
                        (v["video_id"], today, st.get("view_count"),
                         st.get("like_count"), st.get("comment_count")))
            store._conn.commit()
        # 영상 자체도 여론의 원문이다. 제목·설명을 댓글과 같은 분석 파이프라인에 넣는다.
        for v in vids:
            context = ". ".join(x.strip() for x in
                                (v.get("title") or "", v.get("description") or "") if x.strip())
            if context:
                if store.put_text("youtube", "yt_video_context", context[:12000],
                                  product_uid=f"yt:{v['video_id']}",
                                  published_at=v.get("published_at"),
                                  author_hash=f"video:{v['video_id']}"):
                    total["video_contexts"] += 1
        total["videos"] += len(vids)

        # 새 영상은 공개 자막을 즉시 한 번 시도한다. 비공식 제공자가 실패해도
        # 댓글·통계 수집은 계속되며 상태만 남아 다음 재시도 대상을 알 수 있다.
        new_ids = [v["video_id"] for v in vids if v["video_id"] not in existing]
        if new_ids:
            transcript_run = fetch_missing_transcripts(
                store, limit=min(len(new_ids), videos_for_comments), video_ids=new_ids,
                on_event=say)
            total["transcripts_saved"] += transcript_run["counts"].get("saved", 0)
            total["transcript_circuit_open"] = (total["transcript_circuit_open"] or
                                                  transcript_run.get("circuit_open", False))
            total["transcripts_failed"] += sum(
                n for status, n in transcript_run["counts"].items()
                if status not in ("saved", "skipped"))

        vids = sorted(vids, key=lambda v: -(stats.get(v["video_id"], {})
                                            .get("view_count") or 0))
        # 새 영상 또는 아직 유효 댓글을 한 건도 못 담은 영상만 댓글을 다시 읽는다.
        comment_targets = [v for v in vids if (v["video_id"] not in existing
                           or v["video_id"] not in have_comments
                           or v["video_id"] not in replies_synced)]
        for v in comment_targets[:videos_for_comments]:
            total["videos_tried"] += 1
            try:
                cs = yt.comments(v["video_id"], limit=comments_per_video,
                                 video_channel_id=v.get("channel_id") or "")
            except Exception as e:
                if any(k in str(e).lower() for k in yt._COMMENTS_OFF):
                    continue
                total["comment_fail"] += 1
                # ★ 조용히 넘어가면 안 된다. 영상 188건에 댓글 0건이 나왔는데
                #   어디에도 기록이 없어서 원인을 못 찾았다.
                say("warn", {"msg": f"댓글 실패 · {(v['title'] or '')[:26]}: {e}"})
                if PROBLEMS is not None:
                    PROBLEMS.add(title=f"유튜브 댓글을 못 받았습니다 ({v['video_id']})",
                                 source_code="youtube", where="수집",
                                 detail=(v.get("title") or "")[:120], raw=str(e)[:400])
                continue
            total["comments_seen"] += len(cs)
            kept = 0
            parent_rows = {}
            parent_texts = {}
            for c in cs:
                if not (c["text"] or "").strip():
                    continue
                is_reply = bool(c.get("is_reply"))
                if is_reply:
                    total["replies_seen"] += 1
                else:
                    parent_texts[c.get("comment_id") or ""] = c["text"]
                parent_text = parent_texts.get(c.get("parent_comment_id") or "", "")
                # 크리에이터의 짧은 답변("르메르요", "정보란 링크요")은 답글만
                # 보면 필터에서 떨어진다. 질문과 이어 붙여 의미를 보존한다.
                analysis_text = (f"질문: {parent_text}\n답글: {c['text']}"
                                 if is_reply and parent_text else c["text"])
                got = judge_comment(analysis_text, lexicon=lex)
                keep_creator_answer = bool(is_reply and c.get("is_creator_reply")
                                           and parent_text)
                if not got["keep"]:
                    if not keep_creator_answer:
                        total["dropped"][got["drop_why"]] = \
                            total["dropped"].get(got["drop_why"], 0) + 1
                        continue
                if got["keep"]:
                    for w in got["why"]:
                        total["kept_why"][w] = total["kept_why"].get(w, 0) + 1
                doc_kind = "yt_comment_reply" if is_reply else "yt_comment"
                text_id = store.put_text(
                    "youtube", doc_kind, analysis_text,
                    parent_id=parent_rows.get(c.get("parent_comment_id") or ""),
                    product_uid=f"yt:{v['video_id']}",
                    published_at=c["published_at"], like_count=c["like_count"],
                    reply_count=c.get("reply_count") or 0,
                    author_hash=c["author_hash"])
                if not is_reply:
                    if text_id:
                        parent_rows[c.get("comment_id") or ""] = text_id
                elif text_id:
                    total["replies_saved"] += 1
                    if c.get("is_creator_reply"):
                        total["creator_replies_saved"] += 1
                if text_id:
                    kept += 1
            total["comments"] += kept
            with store._lock:
                store._conn.execute(
                    "UPDATE yt_video SET replies_synced_at=datetime('now') WHERE video_id=?",
                    (v["video_id"],))
                store._conn.commit()
            say("info", {"msg": f"  댓글 {len(cs)}건 중 {kept}건 담음 · "
                                f"{(v['title'] or '')[:26]}"})

    # ── ① 추려 둔 채널 ──
    if mode in ("channels", "both"):
        want = channels(store, only_on=True)
        if channel_ids:
            keep = set(channel_ids)
            want = [c for c in want if c["channel_id"] in keep]
        for ch in want:
            up = ch.get("uploads_playlist_id")
            if not up:                       # 옛날에 담은 채널이면 비어 있을 수 있다
                got = yt.channels(ids=[ch["channel_id"]])
                if got:
                    save_channels(store, got)
                    up = got[0].get("uploads_playlist_id")
            if not up:
                say("warn", {"msg": f"업로드 목록을 못 찾음 · {ch.get('title')}"})
                continue
            try:
                vids = yt.channel_videos(up, days=days, limit=per_kw)
            except Exception as e:
                say("warn", {"msg": f"{ch.get('title')} 실패: {e}"})
                continue
            say("info", {"msg": f"[채널] {ch.get('title')} 영상 {len(vids)}건"})
            _save(vids, f"channel:{ch['channel_id']}")
            with store._lock:
                store._conn.execute(
                    "UPDATE yt_channel SET last_synced_at=datetime('now') "
                    "WHERE channel_id=?", (ch["channel_id"],))
                store._conn.commit()
            total["channels"] += 1

    # ── ② 검색어 ──
    if mode not in ("channels",):
        for kw in keywords:
            vids = yt.search(kw, days=days, limit=per_kw)
            say("info", {"msg": f"[검색] '{kw}' 영상 {len(vids)}건"})
            _save(vids, kw)
            total["keywords"] += 1

    total["quota"] = yt.used
    total["transcript_statuses"] = transcript_summary(store)["statuses"]
    total["trend_candidates"] = [
        {"term": term, "videos": count} for term, count in trend_terms.most_common(20)]
    return total
