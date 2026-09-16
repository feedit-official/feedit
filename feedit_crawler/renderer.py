"""
화면을 그려서 받아오기 — 자바스크립트로 그리는 목록을 정기 수집하기 위한 길.

── 왜 필요한가 ──
지그재그 목록과 에이블리 랭킹은 서버가 빈 껍데기를 준다. 화면을 그린 뒤에야
상품이 나타난다. 그래서 지금까지는 사람이 브라우저로 저장해 넣어야 했다.
브라우저를 대신 띄워 주면 그 과정을 12시간마다 자동으로 돌릴 수 있다.

── ★ 여기가 갈리는 지점이다 ★ ──
"사람이 저장한 파일을 읽는 것"과 "프로그램이 정기적으로 받아오는 것"은
겉보기 결과가 같아도 성격이 완전히 다르다. 후자는 그냥 크롤러다.
브라우저를 쓴다고 해서 크롤러가 아니게 되는 게 아니다.

그래서 이 모듈은 **robots.txt 가 허락한 사이트에서만** 동작한다.
막아 둔 곳(무신사)에서는 실행을 거부한다. 우회 수단이 아니라,
'자바스크립트로 그리는 페이지'라는 기술적 문제만 푸는 도구다.

    지그재그  User-agent: * → Allow: /      ✅ 렌더링 허용
    에이블리  User-agent: * → Allow: /      ✅ 렌더링 허용
    무신사    User-agent: * → Disallow: /   ⛔ 거부. 예외 없음.

── 설정 예 ──
    render:
      enabled: true
      pages:
        - url: "/ranking"
          scroll: 12            # 몇 번 내릴지 (가상 스크롤 대비)
      wait_ms: 2500             # 첫 화면이 그려질 때까지
      scroll_wait_ms: 900       # 한 번 내리고 기다릴 시간
"""

from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import identity as _identity
from .politeness import PaceConfig, Pacer, RobotsGate

# 렌더링할 때 쓰는 신분.
# ★ 속이는 게 아니다 — 우리는 **정말로 크로미움**이다. 그래서 그렇게 말한다.
#   대신 뒤에 FEEDiTBot 을 붙여 봇이라는 사실을 숨기지 않는다.
#   robots.txt 판정도 이 이름으로 하므로, 어디까지 가도 되는지는 그대로다.
#
#   왜 필요한가 — 'FEEDiTBot' 만 적어 보내면 모바일 웹앱이 화면을 아예 안 그린다.
#   에이블리에서 82KB 빈 껍데기가 온 원인이 이것이었다.
#
# ★ 이름은 config/identity.yaml 한 곳에서만 고칩니다.
BROWSER_UA = _identity.browser_ua()
MOBILE_UA = _identity.browser_ua(mobile=True)


# 브라우저 안에서 도는 수집기.
# 스크롤하며 카드를 모으고, 목표에 닿거나 더 안 늘어나면 멈춘다.
HARVEST_JS = r"""
async (opt) => {
  const { sel, target, rounds, waitMs } = opt;
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  // 무엇으로 같은 카드인지 알아볼까 — 링크 주소가 가장 확실하고,
  // 없으면 data-* 속성, 그것도 없으면 글자 앞부분으로 본다.
  const keyOf = (el) => {
    const a = el.matches('a[href]') ? el : el.querySelector('a[href]');
    if (a) return a.getAttribute('href');
    for (const at of el.attributes) if (at.name.startsWith('data-')) return at.name + '=' + at.value;
    return (el.textContent || '').trim().slice(0, 60);
  };

  // 실제로 스크롤되는 요소를 찾는다. 창이 아니라 안쪽 div 인 경우가 많다.
  const scroller = () => {
    const c = [...document.querySelectorAll('div,main,section')].filter(e => {
      const s = getComputedStyle(e);
      return /(auto|scroll)/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 80;
    });
    return c.sort((a, b) => b.scrollHeight - a.scrollHeight)[0] || null;
  };

  const found = new Map();
  const grab = () => {
    let els = [];
    if (sel === '__musinsa_product_reviews__') {
      // 전체 후기 페이지는 스크롤할 때 앞 카드를 DOM에서 치운다. 본문에서
      // data-content-id를 가진 가장 가까운 카드까지 올려 카드 단위로 누적한다.
      const roots = new Set();
      for (const body of document.querySelectorAll('[data-button-name="후기내용"]')) {
        const root = body.closest('[data-content-id]') || body.parentElement;
        if (root) roots.add(root);
      }
      els = [...roots];
    } else if (sel === '__ably_product_reviews__') {
      // 해시형 클래스에 기대지 않는다. 날짜·평가·옵션/체형을 함께 가진 가장
      // 작은 후기 상자와 그 안의 긴 leaf 본문으로 실제 후기만 고른다.
      const roots = new Set();
      for (const leaf of document.querySelectorAll('div')) {
        if (leaf.querySelector('div')) continue;
        const body = (leaf.innerText || '').trim();
        if (body.length < 15 || body.length > 3000) continue;
        let p = leaf.parentElement;
        for (let depth = 0; p && depth < 5; depth++, p = p.parentElement) {
          const t = (p.innerText || '').trim();
          if (t.length > 3500) break;
          if (/20\d{2}\.\d{2}\.\d{2}/.test(t) &&
              /(만족해요|별로예요)/.test(t) && /(옵션|체형)/.test(t)) {
            roots.add(p); break;
          }
        }
      }
      els = [...roots];
    } else {
      try { els = document.querySelectorAll(sel); } catch (e) { return; }
    }
    for (const el of els) {
      const k = keyOf(el);
      if (k) found.set(k, el.outerHTML);
    }
  };

  let still = 0, last = -1, i = 0;
  for (; i < rounds; i++) {
    grab();
    if (target && found.size >= target) break;
    if (found.size === last) still++; else still = 0;
    if (still >= 6) break;          // 여러 번 굴려도 안 늘면 진짜 끝
    last = found.size;

    const s = scroller();
    // ★ 두 번 연속 제자리면 바닥까지 한 번 차 준다.
    //   조금씩만 내리다 보면 '더 불러오기'가 안 걸리는 페이지가 있다.
    //   바닥을 찍으면 대개 다음 묶음을 부른다. 줍는 건 매 바퀴 하므로
    //   중간이 건너뛰어도 이미 챙긴 것은 잃지 않는다.
    const kick = still >= 2;
    if (s) {
      s.scrollTop = kick ? s.scrollHeight : s.scrollTop + s.clientHeight * 0.75;
    }
    const de = document.scrollingElement || document.documentElement;
    if (kick) window.scrollTo(0, de.scrollHeight);
    else window.scrollBy(0, window.innerHeight * 0.75);

    await sleep(kick ? waitMs * 2 : waitMs);
    if (kick) {                     // 바닥을 찍은 뒤 살짝 올렸다 내리면
      if (s) s.scrollTop = s.scrollTop - 60;   // 스크롤 이벤트가 한 번 더 뜬다
      await sleep(250);
      if (s) s.scrollTop = s.scrollHeight;
      await sleep(waitMs);
    }
  }
  grab();
  return { count: found.size, rounds: i, html: [...found.values()].join('\n') };
}
"""


# 화면이 안 그려졌을 때 "그럼 뭐가 온 건데?" 를 대신 봐 주는 코드.
# 파일을 주고받으며 추측하는 대신, 도구가 스스로 답하게 한다.
DIAGNOSE_JS = r"""
() => {
  const t = (document.body ? document.body.innerText : '') || '';
  const html = document.documentElement.outerHTML || '';
  const has = (s) => html.toLowerCase().includes(s);

  // 어떤 요소가 몇 개나 반복되는지 — 카드 셀렉터 후보를 찾는 단서
  const cnt = {};
  for (const el of document.querySelectorAll('a[href]')) {
    const h = el.getAttribute('href') || '';
    const k = h.replace(/\d+/g, 'N').split('?')[0].slice(0, 40);
    if (k) cnt[k] = (cnt[k] || 0) + 1;
  }
  const links = Object.entries(cnt).sort((a, b) => b[1] - a[1]).slice(0, 5);

  return {
    title: document.title || '',
    bodyLen: t.length,
    bodyHead: t.replace(/\s+/g, ' ').slice(0, 160),
    anchors: document.querySelectorAll('a[href]').length,
    imgs: document.querySelectorAll('img').length,
    divs: document.querySelectorAll('div').length,
    topLinks: links,
    // ★ '사람인지 확인' 화면인지 판정.
    //   주의: Cloudflare 를 쓰는 평범한 사이트도 challenge-platform 스크립트를
    //   달고 있다. 그것만 보고 '차단'이라고 하면 오탐이 난다 —
    //   실제로 404 페이지를 Cloudflare 차단으로 잘못 읽은 적이 있다.
    //   그래서 '내용이 거의 없다' 는 조건을 함께 본다.
    cloudflare: (has('cf-chl-bypass') || has('cf_chl_opt') || has('_cf_chl')) &&
                t.length < 400,
    captcha: (has('captcha') || has('recaptcha') || has('hcaptcha')) && t.length < 800,
    needJs: has('enable javascript') || has('자바스크립트를'),
    notFound: /페이지를 찾을 수|찾을 수 없|not found|404/i.test(t.slice(0, 300)),
    webdriver: !!navigator.webdriver,
  };
}
"""



def _click_tab(page, txt: str, wait_ms: int = 2000):
    """탭·버튼을 누른다. 안 되면 다른 방법으로 다시 해 본다.

    ★ 왜 여러 번 시도하나
      에이블리에서 '상의'·'아우터' 는 눌리는데 '하의'·'원피스' 만
      8초 기다리다 실패했다. 탭이 가로로 늘어서 있어서 뒤쪽 두 개가
      **화면 밖에 있었다.** 보이지 않는 요소는 playwright 가 안 누른다.

      그래서 ① 화면 안으로 끌어온 뒤 ② 역할(탭·버튼·링크)로 찾고
      ③ 그래도 안 되면 글자로 찾고 ④ 마지막엔 자바스크립트로 누른다.
      실패해도 왜 실패했는지 한 줄로 남긴다.
    """
    tries = [
        ("역할(탭)",   lambda: page.get_by_role("tab", name=txt, exact=True)),
        ("역할(버튼)", lambda: page.get_by_role("button", name=txt, exact=True)),
        ("역할(링크)", lambda: page.get_by_role("link", name=txt, exact=True)),
        ("글자(정확)", lambda: page.get_by_text(txt, exact=True)),
        ("글자(부분)", lambda: page.get_by_text(txt)),
    ]
    last = ""
    for name, make in tries:
        try:
            loc = make()
            n = loc.count()
        except Exception as e:
            last = f"{name}: {str(e).splitlines()[0][:50]}"
            continue
        for i in range(min(n, 4)):          # 같은 글자가 여럿이면 차례로
            el = loc.nth(i)
            try:
                # ★ 화면 밖 탭을 끌어온다 — 이 한 줄이 하의·원피스를 살린다
                el.scroll_into_view_if_needed(timeout=3000)
                el.click(timeout=4000)
                page.wait_for_timeout(wait_ms)
                return True, name
            except Exception as e:
                last = f"{name}#{i}: {str(e).splitlines()[0][:50]}"
    # 마지막 수단 — 눈에 안 보여도 자바스크립트로는 눌린다
    try:
        hit = page.evaluate(
            """(t) => {
                 const els = [...document.querySelectorAll('a,button,[role=tab],li,span,div')];
                 const el = els.find(e => (e.innerText || '').trim() === t
                                          && e.offsetParent !== null);
                 if (!el) return false;
                 el.scrollIntoView({block:'center'}); el.click(); return true;
               }""", txt)
        if hit:
            page.wait_for_timeout(wait_ms)
            return True, "자바스크립트"
    except Exception as e:
        last = f"js: {str(e).splitlines()[0][:50]}"
    return False, last or "찾지 못했습니다"


class RenderBlocked(RuntimeError):
    """robots.txt 가 막아 둔 곳. 렌더링으로도 우회하지 않는다."""


class RenderUnavailable(RuntimeError):
    """playwright 나 브라우저가 안 깔려 있음."""


@dataclass
class RenderResult:
    url: str
    label: str = ""            # '여성 아우터' 처럼 사람이 알아볼 이름
    html: str = ""
    elapsed: float = 0.0
    scrolled: int = 0
    status: int = 0            # HTTP 응답 코드
    count: int = 0             # 화면에서 센 카드 수
    target: int = 0            # 목표
    steps: list = field(default_factory=list)   # 실제로 누른 탭
    warns: list = field(default_factory=list)
    diag: dict = field(default_factory=dict)
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.html) and not self.error


def installed() -> bool:
    """브라우저가 깔려 있나 — **띄워 보지 않고** 파일만 본다.

    available() 은 실제로 브라우저를 띄워 봐서 확실하지만 2~3초가 걸리고,
    드라이버 프로세스를 하나 만든다. 서버를 켤 때마다 그럴 이유는 없다.
    여기서는 '설치돼 있나'만 빠르게 본다.

    playwright 는 브라우저를 정해진 폴더에 받아 둔다.
        리눅스   ~/.cache/ms-playwright
        맥      ~/Library/Caches/ms-playwright
        윈도우   %LOCALAPPDATA%\\ms-playwright
    PLAYWRIGHT_BROWSERS_PATH 로 옮길 수도 있어서 그것도 본다.
    """
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False

    import os
    import sys

    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env == "0":
        return True          # 패키지 안에 같이 넣은 경우 — 있다고 본다
    if env:
        # ★ 이 값이 있으면 playwright 는 **거기만** 본다.
        #   기본 폴더까지 같이 보면, 엉뚱한 곳을 지정해 둔 상태에서도
        #   '있다'고 말해 버린다. 실제로 그렇게 틀렸다.
        roots = [Path(env)]
    else:
        home = Path.home()
        roots = [home / ".cache" / "ms-playwright",
                 home / "Library" / "Caches" / "ms-playwright"]
        if sys.platform == "win32":
            local = os.environ.get("LOCALAPPDATA")
            if local:
                roots.append(Path(local) / "ms-playwright")

    for r in roots:
        try:
            if r.is_dir() and any(r.glob("chromium*")):
                return True
        except OSError:
            continue
    return False


def available() -> tuple[bool, str]:
    """쓸 수 있는 상태인지 본다. 없으면 왜 없는지 알려 준다."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False, ("playwright 가 없습니다. 설치하세요:\n"
                       "  pip install playwright\n"
                       "  python -m playwright install chromium")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return False, f"playwright 를 불러오지 못했습니다: {e}"
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            b.close()
    except Exception as e:
        msg = str(e).strip().splitlines()[0] if str(e) else "알 수 없는 오류"
        return False, (f"브라우저를 띄우지 못했습니다: {msg}\n"
                       "  python -m playwright install chromium\n"
                       "  (리눅스라면 python -m playwright install-deps 도 필요할 수 있습니다)")
    return True, "사용 가능합니다."


class Renderer:
    """설정에 적힌 페이지를 브라우저로 열어 HTML 을 돌려준다."""

    def __init__(self, cfg, on_event=None):
        self.cfg = cfg
        self.on_event = on_event or (lambda *_: None)
        self.base = cfg.base_url.rstrip("/")
        rc = getattr(cfg, "render", None) or {}
        self.rc = rc
        # 모바일 사이트는 모바일 화면·신분으로 봐야 제대로 그려진다
        self.mobile = bool(rc.get("mobile", False))
        self.ua = rc.get("user_agent") or (MOBILE_UA if self.mobile else BROWSER_UA)
        vp = rc.get("viewport") or {}
        self.viewport = {
            "width": int(vp.get("width", 390 if self.mobile else 1280)),
            "height": int(vp.get("height", 844 if self.mobile else 1000)),
        }
        self.robots = RobotsGate(self.base, self.ua)
        pace = {k: v for k, v in (cfg.pace or {}).items()
                if k in PaceConfig.__dataclass_fields__}
        self.pacer = Pacer(PaceConfig(**pace))
        self._checked = False
        self.permission_granted = bool(
            (getattr(cfg, "authorization", None) or {}).get("permission_granted"))

    # ── 안전장치 ──────────────────────────────────────────────
    def ensure_allowed(self, url: str):
        """robots.txt 를 확인한다. 막혀 있으면 여기서 끝난다.

        이 검사를 건너뛸 수 있는 설정은 일부러 만들지 않았다.
        옵션으로 두면 급할 때 꺼 버리게 된다.
        """
        if self.permission_granted:
            full = url if url.startswith("http") else self.base + (
                "" if url.startswith("/") else "/") + url
            self.on_event("authorization", {
                "source": self.cfg.code, "mode": "direct_permission",
                "user_agent": self.ua,
            })
            return full
        if not self._checked:
            import requests
            def _raw(u):
                r = requests.get(u, timeout=15, headers={"User-Agent": self.ua})
                return r.status_code, r.text
            self.robots.load(_raw)
            self._checked = True

        full = url if url.startswith("http") else self.base + (
            "" if url.startswith("/") else "/") + url
        if not self.robots.allowed(full):
            raise RenderBlocked(
                f"{self.cfg.name}: robots.txt 가 이 주소를 막고 있습니다 — {full}\n"
                f"  {self.robots.why_blocked(full)}\n"
                "  브라우저로 그린다고 해서 허락되는 것이 아닙니다. "
                "정기 수집을 하려면 사이트에 문의해 허락을 받아야 합니다."
            )
        return full

    # ── 본체 ──────────────────────────────────────────────────
    def render(self, url: str, scroll: int = 0, target: int = 0,
               count_sel: str = "", steps: Optional[list] = None,
               full_page: bool = False) -> RenderResult:
        """full_page=True 면 카드를 줍지 않고 **화면 전체**를 그대로 뜬다.

        ★ 왜 나눴는가
          이 함수의 원래 일은 **목록**을 훑는 것이다. 그런 화면은 보이는
          카드만 DOM 에 남기고 지나간 것을 지우므로, 스크롤하며 카드를
          하나씩 주워 모은다.

          상세 페이지에는 그 방식이 맞지 않는다. 주울 '카드'가 없다.
          그런데 실측 사이즈를 받으려고 count_sel="body" 로 이 기계를
          그대로 썼다. body 하나만 잡히니 '더 안 늘어난다'고 판단해 몇 바퀴
          만에 멈췄고, 늦게 그려지는 실측표·후기를 놓쳤다.
          그래서 `사이즈·핏·태그를 하나도 못 읽었습니다` 가 매번 떴다.

          상세는 그냥 **끝까지 내리고 통째로 뜨면** 된다.
        """
        full = self.ensure_allowed(url)

        ok, why = available()
        if not ok:
            raise RenderUnavailable(why)

        from playwright.sync_api import sync_playwright

        wait_ms = int(self.rc.get("wait_ms", 2500))
        step_ms = int(self.rc.get("scroll_wait_ms", 900))

        self.pacer.wait()                       # 사람보다 느리게
        t0 = time.time()
        res = RenderResult(url=full)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(args=["--disable-dev-shm-usage"])
                ctx = browser.new_context(
                    user_agent=self.ua,
                    locale="ko-KR",
                    viewport=self.viewport,
                    is_mobile=self.mobile,
                    has_touch=self.mobile,
                    device_scale_factor=2 if self.mobile else 1,
                )
                page = ctx.new_page()
                if self.rc.get("block_heavy_resources"):
                    # ★★ 끊지 않고 '빈 성공'을 돌려준다 ★★
                    #
                    #   전에는 route.abort() 였다. 상대 서버에 안 묻는다는 목적은
                    #   같지만, **브라우저에는 실패로 보인다.** 무신사 이미지
                    #   컴포넌트는 실패한 사진을 회색 자리표시로 바꾸면서
                    #   <img> 의 src 를 지운다. 그래서 주소까지 같이 사라졌다.
                    #
                    #   2026-09-01 실측: 검색 저장본 107칸에 goods_img 가 **0개**.
                    #   같은 페이지를 사람 브라우저로 열면 47/47(100%) 이었다.
                    #   즉 '사진을 못 받는' 게 아니라 '주소를 잃는' 문제였다.
                    #
                    #   fulfill 은 요청을 여기서 끝낸다 — 무신사에는 한 번도
                    #   나가지 않으므로 부하는 abort 와 똑같이 0 이고, src 는 남는다.
                    def _route(route):
                        rt = route.request.resource_type
                        if rt == "image":
                            route.fulfill(status=200, content_type="image/gif",
                                          body=_BLANK_GIF)
                        elif rt in ("media", "font"):
                            route.abort()
                        else:
                            route.continue_()
                    page.route("**/*", _route)
                resp = page.goto(full, wait_until="domcontentloaded",
                                 timeout=int(self.rc.get("timeout_ms", 45000)))
                # ★ 응답 코드를 반드시 본다.
                #   404 를 받고도 '화면이 안 그려졌다'고만 해석하느라
                #   주소가 틀린 걸 한참 못 찾았다. 숫자 하나면 될 일이었다.
                res.status = resp.status if resp else 0
                if res.status and res.status >= 400:
                    res.warns.append(
                        f"HTTP {res.status} — 주소가 맞는지 확인하세요: {full}")
                if res.status in (429, 502, 503, 504) or res.status >= 500:
                    res.error = f"HTTP {res.status} — 서버 보호를 위해 즉시 중단합니다."
                    self.pacer.on_error(res.status)
                    browser.close()
                    return res
                # ★ 정해진 시간만 기다리면 늦게 뜨는 화면을 놓친다.
                #   '상품이 실제로 보일 때까지' 기다리는 게 맞다.
                #   그래도 안 나오면 아래 진단이 이유를 알려 준다.
                wait_sel = (self.cfg.list_page or {}).get("card") \
                    or (self.cfg.list_page or {}).get("item_link") or ""
                if isinstance(wait_sel, list):
                    wait_sel = wait_sel[0] if wait_sel else ""
                if wait_sel:
                    try:
                        page.wait_for_selector(wait_sel, timeout=wait_ms + 12000,
                                               state="attached")
                    except Exception:
                        pass
                page.wait_for_timeout(min(wait_ms, 2500))

                # ── 카테고리 탭 누르기 ──
                #  지그재그는 카테고리를 주소로 못 고른다. 탭이 <a> 가 아니라
                #  JS 버튼이라 주소가 안 바뀌기 때문이다. 그래서 눌러서 바꾼다.
                #  ★ 클래스명 대신 '글자'로 찾는다. 클래스는 빌드마다 바뀌는
                #    해시라 금방 깨지지만, '아우터'라는 글자는 잘 안 바뀐다.
                for st in (steps or []):
                    txt = st.get("click_text")
                    if not txt:
                        continue
                    ok, why = _click_tab(page, txt,
                                         int(st.get("wait_ms", 2000)))
                    if ok:
                        res.steps.append(txt)
                    else:
                        res.warns.append(f"'{txt}' 를 누르지 못했습니다: {why}")

                # ── ★ 내려가면서 줍는다 ★ ──
                #  예전엔 스크롤을 다 한 뒤 page.content() 를 한 번 떴다.
                #  그게 틀렸다. 이런 목록은 **화면에 보이는 것만 DOM 에 남기고
                #  지나간 건 지운다.** 끝나고 한 번 뜨면 마지막 한 화면만 잡힌다.
                #  실제로 에이블리에서 82KB(빈 껍데기)에 0건이 나왔다.
                #
                #  그래서 브라우저 안에서 스크롤하며 카드를 계속 모은다.
                #  지워지기 전에 챙기는 것이다 — 북마클릿이 쓰는 방법과 같다.
                #
                #  스크롤도 창(window)이 아니라 **안쪽 div** 를 굴린다.
                #  모바일 웹앱은 대개 안쪽 컨테이너가 스크롤돼서
                #  window.scrollBy 는 아무 일도 안 일어난다.
                sel = count_sel or (self.cfg.list_page or {}).get("card") \
                    or (self.cfg.list_page or {}).get("item_link") or ""
                if isinstance(sel, list):
                    sel = sel[0] if sel else ""
                # ── 상세 페이지: 카드를 줍지 않고 통째로 ──
                if full_page:
                    for _ in range(max(1, int(scroll or 12))):
                        page.mouse.wheel(0, 2200)
                        page.wait_for_timeout(int(step_ms))
                    page.wait_for_timeout(1200)
                    res.html = page.content()
                    res.count = len(res.html)
                    res.scrolled = max(1, int(scroll or 12))
                    self.pacer.on_ok()
                    browser.close()
                    return res

                got = page.evaluate(HARVEST_JS, {
                    "sel": sel,
                    "target": int(target or 0),
                    "rounds": int(max(1, scroll or 40)),
                    "waitMs": int(step_ms),
                })
                res.count = got.get("count", 0)
                res.scrolled = got.get("rounds", 0)
                body = got.get("html") or ""
                if body:
                    # 수집기가 평소 읽는 모양으로 감싼다 — 설정을 그대로 쓸 수 있게
                    title = (page.title() or "").replace("<", "&lt;")
                    next_data = ""
                    if self.cfg.code == "musinsa_used":
                        try:
                            next_data = page.locator("#__NEXT_DATA__").evaluate(
                                "el => el.outerHTML")
                        except Exception:
                            pass
                    res.html = ('<!DOCTYPE html><html><head><meta charset="utf-8">'
                                f'<link rel="canonical" href="{full}">'
                                f'<title>{title}</title>{next_data}</head>'
                                f'<body>{body}</body></html>')
                else:
                    # 하나도 못 주웠으면 통째로라도 남긴다 (원인 파악용)
                    res.html = page.content()
                    res.warns.append(
                        f"'{sel}' 로 카드를 하나도 못 찾았습니다.")
                    # ★ 그리고 '그럼 뭐가 왔는지' 를 스스로 본다.
                    #   이게 없으면 파일을 주고받으며 추측만 반복하게 된다.
                    try:
                        d = page.evaluate(DIAGNOSE_JS)
                        res.diag = d
                        bits = [f"HTTP {res.status}",
                                f"제목 '{(d.get('title') or '')[:40]}'",
                                f"본문 {d.get('bodyLen',0)}자",
                                f"링크 {d.get('anchors',0)}",
                                f"이미지 {d.get('imgs',0)}",
                                f"div {d.get('divs',0)}"]
                        if d.get("notFound"):
                            bits.append("★ 없는 페이지(404) — 주소를 고치세요")
                        if d.get("cloudflare"):
                            bits.append("★ Cloudflare 확인 화면")
                        if d.get("captcha"):
                            bits.append("★ 캡차")
                        if d.get("needJs"):
                            bits.append("★ '자바스크립트를 켜세요' 문구")
                        res.warns.append("화면 진단 — " + " · ".join(bits))
                        if d.get("bodyHead"):
                            res.warns.append(f"본문 앞부분: {d['bodyHead'][:110]}")
                        tl = d.get("topLinks") or []
                        if tl:
                            res.warns.append(
                                "가장 많은 링크 모양: " +
                                ", ".join(f"{k}×{v}" for k, v in tl[:3]))
                    except Exception as e:
                        res.warns.append(f"진단 실패: {e}")
                browser.close()
            self.pacer.on_success()
        except Exception as e:
            res.error = str(e).strip().splitlines()[0]
            self.pacer.on_error(None)

        res.elapsed = time.time() - t0
        self.on_event("render", {
            "url": full, "bytes": len(res.html), "scrolled": res.scrolled,
            "elapsed": round(res.elapsed, 1), "error": res.error,
        })
        return res

    def render_all(self, limit: int = 0) -> list[RenderResult]:
        """설정의 render.pages 를 전부 그려 온다.

        limit 을 주면 첫 페이지에서 그만큼만 가져오고 끝낸다(시험용).
        """
        out = []
        default_target = int(self.rc.get("target", 0))
        pages = list(self.rc.get("pages") or [])
        if limit:
            pages = pages[:1]
        for item in pages:
            if isinstance(item, str):
                item = {"url": item}
            r = self.render(
                item["url"],
                scroll=(6 if limit else int(item.get("scroll", self.rc.get("scroll", 40)))),
                target=(limit or int(item.get("target", default_target))),
                count_sel=item.get("count_sel", ""),
                steps=item.get("steps") or [],
            )
            r.label = item.get("label", "")
            r.target = limit or int(item.get("target", default_target))
            out.append(r)
            if self.rc.get("fail_fast", True) and (
                    r.status in (429, 502, 503, 504) or r.status >= 500 or r.error):
                break
        return out


# 1x1 투명 GIF. 사진 요청에 이걸 돌려주면 브라우저는 '받았다'고 보고,
# 페이지는 src 를 지우지 않는다. 상대 서버에는 요청이 나가지 않는다.
_BLANK_GIF = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")


def render_and_import(cfg, store, on_event=None, save_dir: Optional[Path] = None,
                      limit: int = 0, on_page=None) -> dict:
    """그려서 곧바로 DB 에 넣는다. 수동 [가져오기] 와 같은 경로를 쓴다.

    save_dir 을 주면 원본 HTML 도 남긴다. 나중에 파서를 고쳤을 때
    다시 받지 않고 다시 뽑을 수 있어서, 상대 서버에 두 번 묻지 않아도 된다.
    """
    from .importer import import_html

    r = Renderer(cfg, on_event=on_event)
    total = {"pages": 0, "products": 0, "listings": 0, "failed": 0, "results": []}

    # 시험 모드 — 페이지 한 장에서 몇 개만. 설정을 고치는 동안 쓰는 것이라
    # 오래 기다릴 이유가 없다.
    for res in r.render_all(limit=limit):
        total["pages"] += 1
        # ★ 한 장 끝날 때마다 바깥에 알린다.
        #   렌더는 무신사 기준 15칸이라 몇 분씩 걸리는데, 그동안 밖에서는
        #   아무 소식이 없어 화면이 '대기'로 보였다.
        if on_page:
            try:
                on_page(total["pages"], res.label or res.url)
            except Exception:      # noqa: BLE001 - 알림 때문에 수집이 멈추면 안 된다
                pass
        if not res.ok:
            total["failed"] += 1
            total["results"].append({
                "url": res.url, "label": res.label, "error": res.error,
                "count": res.count, "target": res.target, "kb": 0,
                "steps": res.steps, "warns": res.warns, "products": 0})
            continue
        saved = ""
        if save_dir:
            save_dir = Path(save_dir)
            save_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            safe = (res.label or res.url.rstrip("/").rsplit("/", 1)[-1])[:40] or "page"
            safe = re.sub(r"[^\w가-힣.-]+", "_", safe)
            f = save_dir / f"{cfg.code}_{safe}_{stamp}.html"
            f.write_text(res.html, encoding="utf-8")
            saved = f.name
            _prune_saved(Path(save_dir))

        got = import_html(res.html, cfg, store, filename=res.url, force_kind="list",
                          page_label=res.label or "")
        total["products"] += got.products
        total["listings"] += got.listings
        total["results"].append({
            "url": res.url, "label": res.label, "kind": got.kind,
            "products": got.products, "count": res.count, "target": res.target,
            "kb": len(res.html) // 1024, "saved": saved,
            "steps": res.steps, "warns": res.warns, "error": got.error,
        })
        # 목표에 한참 못 미치면 알려 준다 — 조용히 적게 모으는 게 제일 나쁘다
        if res.target and got.products < res.target * 0.6:
            total.setdefault("short", []).append(
                f"{res.label or res.url}: 목표 {res.target} 중 {got.products}개")
    return total


# ── 저장본 정리 ───────────────────────────────────────────────
#  받아 온 화면을 남겨 두면 파서를 고쳤을 때 다시 요청하지 않아도 된다.
#  그런데 그냥 두면 끝없이 쌓인다 — 12시간마다 10장이면 한 달에 600장이다.
#  사이트별로 최근 것만 남기고 나머지는 지운다.
KEEP_PER_SITE = 8


def _prune_saved(d: Path, keep: int = KEEP_PER_SITE):
    try:
        files = [f for f in d.glob("*.html") if f.is_file()]
    except OSError:
        return
    by_site: dict[str, list[Path]] = {}
    for f in files:
        by_site.setdefault(f.name.split("_")[0], []).append(f)
    for site, fs in by_site.items():
        fs.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        for old in fs[keep:]:
            try:
                old.unlink()
            except OSError:
                pass
