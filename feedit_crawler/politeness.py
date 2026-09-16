"""
예의 계층 — 서버를 괴롭히지 않고 긁기 위한 장치들.

이 파일이 이 크롤러의 성격을 정한다.
빠르게 긁는 게 목적이 아니라 **오래, 안 막히고, 티 안 나게** 긁는 게 목적이다.
세컨 PC로 며칠씩 돌릴 수 있으니 속도를 포기하는 대신 안정성을 산다.

세 겹으로 막는다.
  1) robots.txt   — 애초에 가면 안 되는 곳을 거른다
  2) 레이트 리밋   — 사람이 브라우징하는 속도를 흉내낸다
  3) 적응형 백오프 — 서버가 힘들어하는 낌새가 보이면 스스로 느려진다
"""

from __future__ import annotations

import random
import threading
import time
import re
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Optional


# ──────────────────────────────────────────────────────────────────────
#  1) robots.txt
# ──────────────────────────────────────────────────────────────────────
class _Rules:
    """robots.txt 규칙을 직접 해석한다.

    파이썬 기본 urllib.robotparser 를 못 쓰는 이유:
    경로 가운데 오는 * 를 처리하지 못한다. 에이블리가 이렇게 써 두었는데

        Disallow: /api/*
        Disallow: /goods/*/measurement

    기본 파서는 이걸 전부 '허용'으로 흘려보냈다. 오지 말라고 명시한 곳을
    긁게 되는 것이라 그냥 둘 수 없다.

    구현은 널리 쓰이는 규칙을 따른다.
      · '*' 는 아무 문자열, '$' 는 끝을 뜻한다
      · 우리 UA 이름과 정확히 맞는 그룹이 있으면 그것만 본다. 없으면 '*' 그룹
      · 가장 길게 맞는 규칙이 이긴다. 길이가 같으면 Allow 가 이긴다
    """

    def __init__(self):
        self.groups: dict[str, list[tuple[str, str]]] = {}   # ua → [(allow|disallow, path)]
        self.delays: dict[str, float] = {}

    @classmethod
    def parse(cls, lines) -> "_Rules":
        self = cls()
        current: list[str] = []
        last_was_ua = False
        for raw in lines:
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            field, _, value = line.partition(":")
            field = field.strip().lower()
            value = value.strip()

            if field == "user-agent":
                if not last_was_ua:
                    current = []
                current.append(value.lower())
                self.groups.setdefault(value.lower(), [])
                last_was_ua = True
                continue

            last_was_ua = False
            if field in ("allow", "disallow"):
                for ua in current:
                    # 'Disallow:' (빈 값) 은 '아무것도 막지 않음' 이라는 뜻
                    if field == "disallow" and value == "":
                        continue
                    self.groups.setdefault(ua, []).append((field, value))
            elif field == "crawl-delay":
                try:
                    for ua in current:
                        self.delays[ua] = float(value)
                except ValueError:
                    pass
        return self

    @staticmethod
    def _to_regex(pattern: str) -> re.Pattern:
        end = pattern.endswith("$")
        if end:
            pattern = pattern[:-1]
        parts = [re.escape(p) for p in pattern.split("*")]
        body = ".*".join(parts)
        return re.compile("^" + body + ("$" if end else ""))

    def _group_for(self, ua: str) -> list[tuple[str, str]]:
        ua_l = (ua or "").lower()
        # 이름이 들어 있는 그룹 중 가장 구체적인(긴) 것
        best, best_len = None, -1
        for name in self.groups:
            if name == "*":
                continue
            if name and name in ua_l and len(name) > best_len:
                best, best_len = name, len(name)
        if best is not None:
            return self.groups[best]
        return self.groups.get("*", [])

    def can_fetch(self, ua: str, path: str) -> bool:
        rules = self._group_for(ua)
        if not rules:
            return True
        winner, winner_len = None, -1
        for kind, pat in rules:
            if not pat:
                continue
            try:
                rx = self._to_regex(pat)
            except re.error:
                continue
            if rx.match(path):
                # 같은 길이면 allow 가 이긴다
                n = len(pat)
                if n > winner_len or (n == winner_len and kind == "allow"):
                    winner, winner_len = kind, n
        if winner is None:
            return True
        return winner == "allow"

    def crawl_delay(self, ua: str):
        ua_l = (ua or "").lower()
        for name, d in self.delays.items():
            if name != "*" and name and name in ua_l:
                return d
        return self.delays.get("*")


class RobotsGate:
    """robots.txt 를 읽고 '가도 되는 길'만 통과시킨다.

    체크를 옵션으로 두지 않은 이유 — 옵션이면 급할 때 꺼버리게 된다.
    막힌 경로는 그냥 통과가 안 되게 만들어 두는 편이 안전하다.

    robots.txt 가 없는 사이트(404·빈 파일)는 '규칙을 선언하지 않은 것'이지
    '뭐든 해도 된다'는 뜻이 아니다. 그런 사이트는 이용약관이 기준이 되므로
    allow_when_missing 을 켜더라도 경고를 남긴다.
    """

    def __init__(self, base_url: str, user_agent: str, allow_when_missing: bool = True):
        self.base = base_url.rstrip("/")
        self.ua = user_agent
        self.allow_when_missing = allow_when_missing
        self.status = "unknown"          # ok | missing | error
        self.crawl_delay: Optional[float] = None
        self._rp: Optional[_Rules] = None
        self._loaded = False

    def load(self, fetcher) -> str:
        """fetcher(url) -> (status_code, text) 를 받아 robots.txt 를 읽는다."""
        url = f"{self.base}/robots.txt"
        try:
            code, text = fetcher(url)
        except Exception:
            self.status = "error"
            self._loaded = True
            return self.status

        if code != 200 or not (text or "").strip():
            self.status = "missing"
            self._loaded = True
            return self.status

        self._rp = _Rules.parse(text.splitlines())
        self.status = "ok"
        self._loaded = True

        # 사이트가 직접 알려 준 간격이 있으면 그걸 최우선으로 존중한다
        try:
            d = self._rp.crawl_delay(self.ua)
            if d:
                self.crawl_delay = float(d)
        except Exception:
            pass
        return self.status

    def allowed(self, url: str) -> bool:
        if not self._loaded:
            raise RuntimeError("robots.txt 를 먼저 load() 해야 합니다.")

        # ★ '없다' 와 '못 읽었다' 는 전혀 다르다 ★
        #   missing = 404. 사이트가 규칙을 안 만든 것 → 통과시킨다(경고는 남긴다).
        #   error   = 네트워크 실패·타임아웃. 규칙이 있는데 우리가 못 본 것일 수 있다.
        #             이때 통과시키면, 잠깐 끊긴 사이에 '오지 마세요'라고 써 둔 곳을
        #             마음껏 긁게 된다. 모를 때는 멈추는 쪽이 맞다.
        #   (예전엔 둘을 같이 취급해서, 무신사처럼 Disallow: / 인 곳도
        #    robots.txt 를 못 받으면 전부 허용으로 새어 나갔다.)
        if self.status == "error":
            return False
        if self.status != "ok":
            return self.allow_when_missing
        path = urllib.parse.urlparse(url).path or "/"
        q = urllib.parse.urlparse(url).query
        if q:
            path = path + "?" + q
        return self._rp.can_fetch(self.ua, path)

    def why_blocked(self, url: str) -> str:
        path = urllib.parse.urlparse(url).path or "/"
        if self.status == "error":
            return ("robots.txt 를 읽지 못했습니다. 규칙을 모르는 상태라 "
                    "안전하게 멈춥니다. 네트워크를 확인하고 다시 시도하세요.")
        return f"robots.txt 가 {self.ua} 에게 {path} 를 막고 있습니다."


# ──────────────────────────────────────────────────────────────────────
#  2) 레이트 리밋 + 3) 적응형 백오프
# ──────────────────────────────────────────────────────────────────────
@dataclass
class PaceConfig:
    """기본값은 일부러 느리다. 며칠 돌릴 수 있으니 서두를 이유가 없다."""

    base_delay: float = 3.0        # 요청 사이 기본 간격(초)
    jitter: float = 1.5            # ± 흔들기. 일정한 리듬은 봇 티가 난다
    max_delay: float = 120.0       # 백오프 상한
    burst_pause_every: int = 50    # N개마다
    burst_pause_sec: float = 30.0  # 한 번 길게 쉰다 (사람이 커피 마시듯)
    max_rps: float = 0.5           # 안전 상한 — 초당 0.5회 = 2초에 1회


@dataclass
class PaceState:
    consecutive_errors: int = 0
    consecutive_ok: int = 0
    current_delay: float = 0.0
    total_requests: int = 0
    last_request_at: float = 0.0
    backoff_events: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


class Pacer:
    """요청 간격을 관리한다.

    잘 되면 조금씩 빨라지고(단, 상한 안에서), 막히는 낌새가 보이면
    즉시 크게 느려진다. 느려지는 건 빠르게, 빨라지는 건 천천히 —
    차단당하는 것보다 느린 편이 항상 낫기 때문이다.
    """

    def __init__(self, cfg: PaceConfig, robots_delay: Optional[float] = None):
        self.cfg = cfg
        # 사이트가 robots.txt 로 간격을 지정했으면 그게 하한선이다
        self.floor = max(cfg.base_delay, robots_delay or 0.0)
        self.state = PaceState(current_delay=self.floor)

    # ── 요청 전 ──
    def wait(self) -> float:
        with self.state.lock:
            n = self.state.total_requests
            delay = self.state.current_delay

        # 일정 개수마다 길게 한 번 쉰다
        if n and self.cfg.burst_pause_every and n % self.cfg.burst_pause_every == 0:
            delay += self.cfg.burst_pause_sec

        # 흔들기 — 기계적으로 정확한 간격이 오히려 눈에 띈다
        delay += random.uniform(-self.cfg.jitter, self.cfg.jitter)
        delay = max(1.0 / self.cfg.max_rps, delay)

        # 직전 요청 이후 이미 흐른 시간은 빼 준다
        elapsed = time.time() - self.state.last_request_at
        sleep_for = max(0.0, delay - elapsed)
        if sleep_for:
            time.sleep(sleep_for)

        with self.state.lock:
            self.state.last_request_at = time.time()
            self.state.total_requests += 1
        return sleep_for

    # ── 요청 후 ──
    def on_success(self) -> None:
        with self.state.lock:
            self.state.consecutive_errors = 0
            self.state.consecutive_ok += 1
            # 20번 연속 성공해야 5%만 빨라진다. 아주 보수적으로.
            if self.state.consecutive_ok >= 20:
                self.state.consecutive_ok = 0
                self.state.current_delay = max(
                    self.floor, self.state.current_delay * 0.95
                )

    def on_error(self, status: Optional[int] = None) -> float:
        """실패하면 지수적으로 물러난다. 429/403 은 특히 크게."""
        with self.state.lock:
            self.state.consecutive_errors += 1
            self.state.consecutive_ok = 0
            self.state.backoff_events += 1

            factor = 2.0
            if status in (429, 503):      # 명시적 '천천히' 신호
                factor = 4.0
            elif status == 403:           # 차단 낌새 — 가장 크게 물러난다
                factor = 6.0

            self.state.current_delay = min(
                self.cfg.max_delay,
                max(self.floor, self.state.current_delay) * factor,
            )
            return self.state.current_delay

    # ── 지금 상태를 UI 로 ──
    def snapshot(self) -> dict:
        with self.state.lock:
            s = self.state
            return {
                "current_delay": round(s.current_delay, 2),
                "floor": round(self.floor, 2),
                "total_requests": s.total_requests,
                "consecutive_errors": s.consecutive_errors,
                "backoff_events": s.backoff_events,
                "rps": round(1.0 / s.current_delay, 3) if s.current_delay else 0,
            }


class BlockDetector:
    """차단당했는지 판단한다.

    HTTP 코드만 보면 늦다. 200 을 주면서 내용만 빈 껍데기로 바꾸는 경우가
    흔해서, 연속 실패와 '내용 없음'을 같이 본다.

    막혔다고 판단되면 **멈춘다.** 우회하지 않는다 —
    우회는 상대가 명시적으로 거부한 걸 뚫는 행위이고, 그건 이 도구의 선을 넘는다.
    """

    def __init__(self, error_threshold: int = 5, empty_threshold: int = 10):
        self.error_threshold = error_threshold
        self.empty_threshold = empty_threshold
        self.consecutive_empty = 0
        self.reason: Optional[str] = None

    def check(self, status: Optional[int], parsed_count: int, consecutive_errors: int) -> bool:
        if status == 403:
            self.reason = "403 Forbidden — 접근이 거부됐습니다."
            return True
        if consecutive_errors >= self.error_threshold:
            self.reason = f"연속 {consecutive_errors}회 실패 — 차단으로 판단합니다."
            return True

        if parsed_count == 0:
            self.consecutive_empty += 1
        else:
            self.consecutive_empty = 0

        if self.consecutive_empty >= self.empty_threshold:
            self.reason = (
                f"{self.consecutive_empty}개 연속으로 내용이 비어 있습니다. "
                "구조가 바뀌었거나 봇 감지에 걸렸습니다."
            )
            return True
        return False
