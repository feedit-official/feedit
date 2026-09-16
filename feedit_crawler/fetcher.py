"""
가져오기 계층 — 예의 계층을 통과한 요청만 실제로 나간다.

여기서 하지 않는 것들을 먼저 적어 둔다. 일부러 안 넣은 것이지 빠뜨린 게 아니다.
  · 프록시 로테이션 / IP 우회
  · 캡차 자동 해결
  · 봇 감지 회피용 브라우저 지문 위조
이 셋은 상대가 "오지 마세요"라고 한 걸 뚫는 행위다. 막히면 뚫지 말고 멈춘다.
막혔다는 건 대개 우리가 너무 빨랐다는 뜻이고, 답은 우회가 아니라 감속이다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import requests

from . import identity as _identity
from .politeness import BlockDetector, Pacer, PaceConfig, RobotsGate

# 우리가 누구인지 밝힌다. 숨기면 그 순간부터 성격이 달라진다.
# ★ HTTP 헤더는 latin-1 로만 인코딩된다. 한글을 넣으면 요청이 나가기도 전에
#   UnicodeEncodeError 로 죽는다 — ASCII 로만 적을 것.
# ★ 이름은 config/identity.yaml 한 곳에서만 고칩니다.
DEFAULT_UA = _identity.crawler_ua()


@dataclass
class FetchResult:
    url: str
    status: int
    text: str = ""
    json: Optional[dict] = None
    elapsed: float = 0.0
    from_cache: bool = False
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class Fetcher:
    def __init__(
        self,
        base_url: str,
        source_code: str,
        store=None,
        user_agent: str = DEFAULT_UA,
        pace: Optional[PaceConfig] = None,
        respect_robots: bool = True,
        timeout: float = 20.0,
        on_event=None,
        error_threshold: int = 5,
    ):
        self.base_url = base_url.rstrip("/")
        self.source_code = source_code
        self.store = store
        self.ua = user_agent
        self.timeout = timeout
        self.respect_robots = respect_robots
        self.on_event = on_event or (lambda *_: None)

        # 헤더는 latin-1 만 허용된다. 여기서 미리 걸러야 실행 중에 안 죽는다.
        try:
            user_agent.encode("latin-1")
        except UnicodeEncodeError:
            raise ValueError(
                "User-Agent 에 한글·이모지를 넣을 수 없습니다. "
                "HTTP 헤더는 latin-1 로만 인코딩됩니다. 영문으로 적어 주세요."
            )

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        })

        self.robots = RobotsGate(self.base_url, user_agent)
        self.pacer = Pacer(pace or PaceConfig())
        self.blocked = False
        self.detector = BlockDetector(error_threshold=max(1, int(error_threshold)))
        self.stats = {"ok": 0, "err": 0, "skipped": 0, "blocked_by_robots": 0}

    # ── 준비 ──────────────────────────────────────────────────
    def prepare(self) -> dict:
        """robots.txt 를 읽고 크롤링 간격을 확정한다. 시작 전에 반드시 한 번."""
        def _raw(url):
            r = self.session.get(url, timeout=self.timeout)
            return r.status_code, r.text

        status = self.robots.load(_raw)
        if self.robots.crawl_delay:
            # 사이트가 지정한 간격이 우리 기본값보다 느리면 그쪽을 따른다
            self.pacer = Pacer(self.pacer.cfg, robots_delay=self.robots.crawl_delay)

        info = {
            "robots": status,
            "crawl_delay": self.robots.crawl_delay,
            "floor_delay": self.pacer.floor,
            "user_agent": self.ua,
        }
        if status == "missing":
            info["warning"] = (
                "robots.txt 가 없습니다. 규칙을 선언하지 않았을 뿐 "
                "'무엇이든 해도 된다'는 뜻은 아닙니다. 이용약관을 확인하세요."
            )
        self.on_event("prepare", info)
        return info

    # ── 한 번 가져오기 ────────────────────────────────────────
    def abs_url(self, url: str) -> str:
        """상대 주소를 절대 주소로. **여기 한 곳에서만 만든다.**

        목록 파서는 '/products/123' 을 돌려주는데 seen_url 에는
        'https://kream.co.kr/products/123' 으로 저장된다. 두 자리에서
        따로 이어 붙이면 한쪽이 어긋나도 조용히 지나간다 — 실제로
        '이미 받았나' 검사가 통째로 헛돌았다.
        """
        if url.startswith("http"):
            return url
        return self.base_url + ("" if url.startswith("/") else "/") + url

    def get(self, url: str, as_json: bool = False, skip_seen: bool = True) -> FetchResult:
        if self.blocked:
            return FetchResult(url, 0, error="차단 감지로 중단된 상태입니다.")

        url = self.abs_url(url)

        # robots 가 막은 곳은 아예 요청하지 않는다
        if self.respect_robots and not self.robots.allowed(url):
            self.stats["blocked_by_robots"] += 1
            msg = self.robots.why_blocked(url)
            self.on_event("robots_block", {"url": url, "reason": msg})
            return FetchResult(url, 0, error=msg)

        # 이미 본 URL 은 다시 묻지 않는다 — 서버에도 우리에게도 낭비
        if skip_seen and self.store and self.store.seen(url):
            self.stats["skipped"] += 1
            return FetchResult(url, 304, from_cache=True)

        waited = self.pacer.wait()
        t0 = time.time()
        try:
            r = self.session.get(url, timeout=self.timeout)
            elapsed = time.time() - t0
        except requests.RequestException as e:
            self.stats["err"] += 1
            delay = self.pacer.on_error(None)
            self.on_event("error", {"url": url, "error": str(e), "next_delay": delay})
            return FetchResult(url, 0, error=str(e))

        res = FetchResult(url, r.status_code, elapsed=elapsed)

        if res.ok:
            # ★ 인코딩. 서버가 Content-Type 에 charset 을 안 주면 requests 는
            #   ISO-8859-1 로 가정해 한글이 통째로 깨진다. 그러면 '97,000원' 이
            #   '97,000ì' 이 되어 가격 정규식이 조용히 실패한다 —
            #   에러도 안 나고 값만 비어서 원인을 찾기가 매우 어렵다.
            if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
                head = r.content[:2048].decode("ascii", errors="ignore").lower()
                if "utf-8" in head or "utf8" in head:
                    r.encoding = "utf-8"
                elif "euc-kr" in head or "cp949" in head:
                    r.encoding = "cp949"
                else:
                    r.encoding = r.apparent_encoding or "utf-8"
            res.text = r.text
            if as_json:
                try:
                    res.json = r.json()
                except ValueError:
                    res.error = "JSON 파싱 실패 — 응답이 HTML 일 수 있습니다."
            self.stats["ok"] += 1
            self.pacer.on_success()
            if self.store:
                self.store.mark_seen(url, self.source_code, r.status_code)
        else:
            self.stats["err"] += 1
            delay = self.pacer.on_error(r.status_code)
            self.on_event("error", {
                "url": url, "status": r.status_code, "next_delay": delay,
            })

        # 차단 판정
        if self.detector.check(
            r.status_code, 1 if res.ok else 0, self.pacer.state.consecutive_errors
        ):
            self.blocked = True
            self.on_event("blocked", {"reason": self.detector.reason})

        self.on_event("fetch", {
            "url": url, "status": res.status, "elapsed": round(elapsed, 2),
            "waited": round(waited, 2), **self.pacer.snapshot(),
        })
        return res

    def snapshot(self) -> dict:
        return {
            **self.stats,
            **self.pacer.snapshot(),
            "blocked": self.blocked,
            "block_reason": self.detector.reason,
            "robots_status": self.robots.status,
        }
