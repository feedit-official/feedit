"""
러너 — 목록을 훑고, 상세로 들어가고, 저장하고, 언제든 멈췄다 이어서 한다.

세컨 PC로 며칠 돌린다는 전제로 짰다. 그래서 중요한 건 속도가 아니라
  · 껐다 켜도 이어서 돈다 (체크포인트)
  · 막히면 스스로 멈춘다 (뚫지 않는다)
  · 지금 뭘 하고 있는지 밖에서 보인다 (이벤트)
세 가지다.
"""

from __future__ import annotations

import threading
import time
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from .adapter import ConfigAdapter, SiteConfig, to_int
from .stats import from_record as stat_fields
from .stats import retail_fields
from .fetcher import DEFAULT_UA, Fetcher
from .politeness import PaceConfig
from .store import Store


@dataclass
class JobState:
    job_key: str = ""
    source: str = ""
    phase: str = "idle"          # idle|prepare|list|detail|done|blocked|error|paused
    done: int = 0
    total: int = 0
    saved_products: int = 0
    saved_listings: int = 0
    errors: int = 0
    started_at: Optional[str] = None
    message: str = ""
    queue_left: int = 0
    recent: list = field(default_factory=list)   # 최근 이벤트 (UI 용)

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["recent"] = list(self.recent)[-40:]
        return d


def _now_iso() -> str:
    """SQLite 의 datetime('now') 와 같은 잣대(UTC)로 적는다."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class CrawlJob:
    """설정 하나를 돌리는 작업."""

    def __init__(
        self,
        cfg: SiteConfig,
        store: Store,
        on_event: Optional[Callable] = None,
        max_items: Optional[int] = None,
        dry_run: bool = False,
        list_only: bool = False,
    ):
        self.cfg = cfg
        self.store = store
        self.adapter = ConfigAdapter(cfg)
        self.max_items = max_items
        self.dry_run = dry_run
        # 목록만 수집 — 상세를 안 열고 목록 카드에서 바로 값을 뽑는다.
        # 상세 50번 대신 목록 1번이라 서버 부담이 50분의 1이다.
        self.list_only = list_only
        self._on_event = on_event or (lambda *_: None)

        self.state = JobState(job_key=f"{cfg.code}:main", source=cfg.code)
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.fetcher = Fetcher(
            base_url=cfg.base_url,
            source_code=cfg.code,
            store=store,
            pace=PaceConfig(**(cfg.pace or {})),
            user_agent=cfg.user_agent or DEFAULT_UA,
            respect_robots=not bool((cfg.authorization or {}).get("permission_granted")),
            error_threshold=int((cfg.authorization or {}).get("error_threshold", 5)),
            on_event=self._fetch_event,
        )

    def _musinsa_needs_detail(self, url: str) -> bool:
        """목록만 저장되어 상세 필드가 비어 있는 무신사 상품인가."""
        if self.cfg.code not in ("musinsa", "musinsa_used"):
            return False
        m = re.search(r"/products/(\d+)", str(url))
        if not m:
            return False
        with self.store._lock:
            row = self.store._conn.execute(
                """SELECT p.model_code, p.image_url, s.review_count, s.review_score
                   FROM staging_product p LEFT JOIN product_stat s
                     ON s.source_code=p.source_code AND s.source_uid=p.source_uid
                   WHERE p.source_code=? AND p.source_uid=?""",
                (self.cfg.code, m.group(1)),
            ).fetchone()
        return bool(row and any(row[k] in (None, "") for k in
                                ("model_code", "image_url", "review_count", "review_score")))

    # ── 이벤트 ───────────────────────────────────────────────
    def _emit(self, kind: str, payload: dict):
        item = {"t": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                "kind": kind, **payload}
        self.state.recent.append(item)
        if len(self.state.recent) > 200:
            self.state.recent = self.state.recent[-120:]
        self._on_event(kind, item)

    def _fetch_event(self, kind: str, payload: dict):
        if kind == "blocked":
            self.state.phase = "blocked"
            self.state.message = payload.get("reason", "차단 감지")
            self._stop.set()
        elif kind == "robots_block":
            self.state.message = payload.get("reason", "")
        self._emit(kind, payload)

    # ── 제어 ─────────────────────────────────────────────────
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._pause.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self):
        self._pause.set()
        self.state.phase = "paused"

    def resume(self):
        self._pause.clear()
        if self.state.phase == "paused":
            self.state.phase = "detail"

    def stop(self):
        self._stop.set()

    def _should_stop(self) -> bool:
        while self._pause.is_set() and not self._stop.is_set():
            time.sleep(0.4)
        return self._stop.is_set()

    # ── 본체 ─────────────────────────────────────────────────
    def _run(self):
        st = self.state
        st.started_at = datetime.now(timezone.utc).isoformat()
        st.phase = "prepare"
        run_id = self.store.start_run(self.cfg.code, "main")

        try:
            info = self.fetcher.prepare()
            self._emit("prepare", info)

            # ── 1단계: 목록에서 상세 URL 모으기 ──
            st.phase = "list"
            detail_urls: list[str] = []
            # ★ 못 박아 둔 상품 — 발표에 꼭 나와야 하는 것들.
            #   맨 앞에 둬서 max_items 상한에 밀려 빠지지 않게 한다.
            #   목록에서 안 나와도 매 회차 반드시 다시 본다.
            pinned = [str(u) for u in (getattr(self.cfg, "pinned_details", None) or []) if u]
            if pinned:
                detail_urls.extend(pinned)
                self._emit("list", {"url": "(못 박은 상품)", "found": len(pinned),
                                    "total_queued": len(detail_urls), "cards": 0})
            detail_urls.extend(self._sitemap_urls())
            for seed in self.adapter.iter_seed_urls():
                if self._should_stop():
                    break
                # 목록 페이지는 캐시를 건너뛴다.
                # 여기까지 걸러 버리면 재개할 때 상세 URL 을 하나도 못 모아
                # "이어서 하기"가 통째로 죽는다. 목록은 매번 새로 본다.
                res = self.fetcher.get(seed, skip_seen=False)
                if not res.ok:
                    st.errors += 1
                    continue
                # 목록 카드에서 바로 값을 뽑는다 (설정에 card_fields 가 있을 때)
                recs = self.adapter.parse_list_records(res.text)
                if recs and not self.dry_run:
                    for r in recs:
                        self._save_list_record(r)
                if recs:
                    st.saved_products += len(recs)
                    self._emit("cards", {"url": seed, "records": len(recs),
                                         "sample": (recs[0].get("name") or "")[:34]})

                found = [] if self.list_only else self.adapter.parse_list(res.text)
                detail_urls.extend(found)
                self._emit("list", {"url": seed, "found": len(found),
                                    "total_queued": len(detail_urls),
                                    "cards": len(recs)})
                # 목록이 갑자기 0이면 구조가 바뀐 것 — 계속 돌려도 빈 값만 쌓인다
                if not found and not recs:
                    self._emit("warn", {
                        "message": "이 목록에서 상세 URL 을 못 찾았습니다. "
                                   "구조 탐색기로 셀렉터를 다시 잡아 보세요.",
                        "url": seed,
                    })

            # ── 1.5단계: 이미 아는 상품 다시 보기 ──
            #  목록이 자동으로 안 되는 사이트(지그재그)의 생명줄이다.
            #  한 번 알아낸 상품 주소는 계속 다시 볼 수 있으므로,
            #  목록 없이도 매일 시세를 갱신할 수 있다.
            rv = getattr(self.cfg, "revisit", None) or {}
            if rv.get("enabled"):
                olds = self._revisit_urls(rv)
                if olds:
                    detail_urls.extend(olds)
                    self._emit("list", {"url": "(재방문)", "found": len(olds),
                                        "total_queued": len(detail_urls), "cards": 0})

            # 중복 제거 + 이어서 하기
            seen = set()
            queue = [u for u in detail_urls if not (u in seen or seen.add(u))]
            ck = self.store.load_cursor(st.job_key)
            if self.cfg.code != "musinsa" and ck and ck["cursor"] in queue:
                # 커서는 '마지막으로 끝낸 것'이므로 그 다음부터 시작한다.
                # 커서 자체를 포함하면 한 개가 두 번 세어진다.
                queue = queue[queue.index(ck["cursor"]) + 1:]
                st.done = ck["done_count"] or 0
                self._emit("resume", {"from": ck["cursor"], "done": st.done})

            # ★ 이미 받아 둔 주소를 먼저 걷어낸 뒤에 개수를 자른다
            #
            #   전에는 자르기부터 했다. 그러면 max_items=150 이
            #   '새로 150개'가 아니라 '앞에서부터 150칸'이 된다. 그 150칸이
            #   대부분 이미 받은 것이면, 한 바퀴 다 돌고도 새로 여는 건
            #   몇 개 안 된다 — 크림이 실제로 그랬다. 목록에 상품이 544개
            #   쌓이는 동안 상세는 178개(33%)에서 더 못 나갔고, 모델번호가
            #   상세에만 있어서 커버리지가 26% 에 멈춰 있었다.
            #
            #   여기서 걸러도 fetcher 가 한 번 더 확인하므로 안전하다.
            #   (그 사이에 다른 실행이 받아 갔을 수 있다)
            enrich = [u for u in queue if self._musinsa_needs_detail(u)]
            enrich_set = set(enrich)
            fresh = enrich + [u for u in queue if u not in enrich_set and
                              not self.store.seen(self.fetcher.abs_url(u))]
            skipped = len(queue) - len(fresh)
            if skipped:
                self._emit("skip_seen", {"n": skipped, "left": len(fresh)})
            queue = fresh

            if self.max_items:
                queue = queue[: self.max_items]
            st.total = st.done + len(queue)

            # ── 2단계: 상세 들어가기 ──
            st.phase = "detail"
            for url in queue:
                if self._should_stop():
                    break
                st.queue_left = st.total - st.done

                res = self.fetcher.get(url, skip_seen=not self._musinsa_needs_detail(url))
                if res.from_cache:
                    st.done += 1
                    continue
                if not res.ok:
                    st.errors += 1
                    st.done += 1
                    continue

                try:
                    if self.cfg.code == "musinsa_used":
                        from .musinsa_used import parse_detail
                        rec = parse_detail(res.text)
                        self._enrich_used_from_original(rec)
                    else:
                        rec = self.adapter.parse_detail(res.text, url)
                except Exception as e:
                    st.errors += 1
                    self._emit("parse_error", {"url": url, "error": str(e)})
                    st.done += 1
                    continue

                # ── 실측 사이즈·핏 후기·연관 태그 ──
                #   ★ 이 값들은 원본 HTML 에 없다. 화면을 그려야 생긴다.
                #     그래서 render.detail 을 켠 사이트에서만 한 번 더 연다.
                #     느리므로(한 건에 몇 초) 기본은 꺼져 있다.
                if (self.cfg.render or {}).get("detail"):
                    self._add_sizefit(rec, rec.get("_review_url") or url)

                # 에이블리는 후기 전체보기를 누른 뒤에만 원문이 생긴다.
                # 상품 상세 HTTP 응답만 파싱해서는 늘 0건이므로 별도 제한 렌더를 쓴다.
                if (self.cfg.render or {}).get("review_capture", {}).get("enabled"):
                    self._add_product_reviews(rec, rec.get("_review_url") or url)

                if not self.dry_run:
                    self._save(rec, res, url)

                st.done += 1
                self.store.save_cursor(st.job_key, url, st.done, st.total)
                self._emit("item", {
                    "url": url,
                    "name": (rec.get("name") or "")[:44],
                    "price": rec.get("price"),
                    "trades": len(rec.get("trades") or []),
                    "done": st.done, "total": st.total,
                })

            if st.phase not in ("blocked",):
                st.phase = "done" if not self._stop.is_set() else "paused"
            st.message = st.message or "완료"

        except Exception as e:
            st.phase = "error"
            st.message = str(e)
            self._emit("error", {"error": str(e)})
        finally:
            self.store.end_run(
                run_id,
                status=st.phase,
                fetched=st.done,
                errors=st.errors,
                blocked=(st.phase == "blocked"),
                note=st.message,
            )

    # ── 재방문 대상 뽑기 ─────────────────────────────────────
    def _revisit_urls(self, rv: dict) -> list[str]:
        """오래 안 본 상품부터 다시 볼 주소를 고른다.

        seen_url 에 남아 있으면 fetcher 가 건너뛰므로, 여기서 함께 지운다.
        '다시 보겠다'는 뜻이니 '본 적 있음' 표시를 치우는 게 맞다.
        """
        hours = float(rv.get("stale_hours", 12))
        batch = int(rv.get("batch", 300))
        try:
            with self.store._lock:
                rows = self.store._conn.execute(
                    """SELECT source_url FROM staging_product
                       WHERE source_code = ? AND source_url IS NOT NULL
                         AND trim(source_url) <> ''
                         -- ★★ 여기가 모델코드·리뷰·실측이 통째로 비던 자리 ★★
                         --
                         --  전에는 '오래된 것'만 골랐다. 그런데 렌더링이 **먼저**
                         --  돌면서 담은 상품 전부의 last_seen_at 을 지금으로 찍는다.
                         --  그래서 재방문 차례가 오면 남는 게 없었다.
                         --  2026-09-01 실측: 무신사 1,459건 중 후보 **29건**.
                         --  렌더링으로 담은 상품은 **영원히 상세를 못 받는** 구조였다.
                         --  (칸별로 재 보니 브랜드·소재·스타일·랭킹 칸은 모델코드
                         --   0%, 실측 0%. 상세를 받은 칸만 100% 였다.)
                         --
                         --  그래서 조건을 하나 더 둔다 — **아직 상세를 한 번도
                         --  안 받은 상품**. 이건 오래되고 말고와 상관없이 받아야 한다.
                         AND (detail_seen_at IS NULL
                              OR last_seen_at IS NULL
                              OR last_seen_at <= datetime('now', ?))
                       -- ★ 사진이 빈 것부터 본다.
                       --   목록에서 사진을 못 얻은 상품이 쌓여 있는데(2026-09-01
                       --   무신사 860건) 상세에는 thumbnailImageUrl 이 있다.
                       --   재방문은 어차피 도니까, 그중 구멍 난 것을 먼저 메운다.
                       -- 상세를 한 번도 못 받은 것 → 사진이 빈 것 → 오래된 것 순.
                       ORDER BY (detail_seen_at IS NOT NULL) ASC,
                                (image_url IS NOT NULL AND trim(image_url) <> '') ASC,
                                last_seen_at ASC LIMIT ?""",
                    (self.cfg.code, f"-{hours} hours", batch)).fetchall()
            urls = [r[0] for r in rows]
            if urls:
                with self.store.tx() as c:
                    for u in urls:
                        c.execute("DELETE FROM seen_url WHERE url=?", (u,))
            return urls
        except Exception as e:
            self._emit("warn", {"message": f"재방문 목록을 만들지 못했습니다: {e}"})
            return []

    def _sitemap_urls(self) -> list[str]:
        """허가된 사이트맵에서 제한된 수의 상품 URL만 발견한다.

        사이트맵 전체를 순회하면 상대 서버와 우리 DB 양쪽에 부담이다. 인덱스의
        자식 일부와 상품 경로만 읽고, 최종 상세 상한은 기존 max_items가 다시 건다.
        """
        sc = getattr(self.cfg, "sitemap", None) or {}
        if not sc.get("enabled"):
            return []
        index = sc.get("index_url")
        if not index:
            return []
        allow = re.compile(sc.get("allow_pattern") or r"/products/\d+(?:[/?#]|$)")
        deny = tuple(sc.get("deny_prefixes") or
                     ("/auth/", "/fashiontalk/", "/festival/", "/like/",
                      "/mypage/", "/showcase/", "/app/coupon/coupon_result/"))
        child_limit = max(0, int(sc.get("max_child_sitemaps", 1)))
        url_limit = max(1, int(sc.get("max_urls", 200)))

        def locs(xml: str) -> list[str]:
            return [x.strip() for x in re.findall(
                r"<loc>\s*(.*?)\s*</loc>", xml or "", flags=re.I | re.S)]

        first = self.fetcher.get(index, skip_seen=False)
        if not first.ok:
            self._emit("warn", {"message": "사이트맵 인덱스를 읽지 못했습니다.",
                                "url": index, "status": first.status})
            return []
        roots = locs(first.text)
        pages = [u for u in roots if u.lower().endswith((".xml", ".xml.gz"))]
        candidates = [u for u in roots if allow.search(u)]
        for child in pages[:child_limit]:
            if len(candidates) >= url_limit or self._should_stop():
                break
            got = self.fetcher.get(child, skip_seen=False)
            if got.ok:
                candidates.extend(u for u in locs(got.text) if allow.search(u))

        safe = []
        for url in candidates:
            try:
                from urllib.parse import urlsplit
                p = urlsplit(url).path
            except Exception:
                continue
            if any(p.startswith(x) for x in deny) or not allow.search(url):
                continue
            if url not in safe:
                safe.append(url)
            if len(safe) >= url_limit:
                break
        self._emit("sitemap", {"index": index, "children": min(len(pages), child_limit),
                               "products": len(safe), "limit": url_limit})
        return safe

    # ── 목록 카드 한 건 저장 ─────────────────────────────────

    # ── 실측 사이즈·핏 ────────────────────────────────────────
    def _enrich_used_from_original(self, rec: dict) -> None:
        """USED 자체에 없는 제품번호·후기를 원상품 상세에서 보강한다."""
        original = rec.get("original_goods_no")
        if not original:
            return
        original_url = f"https://www.musinsa.com/products/{original}"
        rec["_review_url"] = original_url
        # USED JSON의 styleNo가 null인 상품도 원상품에는 남아 있을 수 있다.
        if rec.get("model_code") and (rec.get("review_count") or 0) > 0:
            return
        try:
            from .musinsa_used import parse_detail
            result = self.fetcher.get(original_url, skip_seen=False)
            if not result.ok:
                return
            original_rec = parse_detail(result.text)
            for key in ("model_code", "review_count", "review_score"):
                if rec.get(key) in (None, "", 0) and original_rec.get(key) not in (None, ""):
                    rec[key] = original_rec[key]
        except Exception as exc:  # 원상품 보강 실패가 USED 가격 수집을 막지는 않는다.
            self._emit("warn", {"url": original_url,
                                "message": f"원상품 정보 보강 실패: {exc}"})

    def _add_sizefit(self, rec: dict, url: str):
        """상세를 한 번 더 '그려서' 실측표·핏 후기·연관 태그를 붙인다.

        원본 HTML 에는 이 값들이 없다 (2026-08-31 확인: 119,817자 안에
        '총장'도 '<table>' 도 없었다). 화면을 그려야만 생긴다.
        """
        from . import sizefit
        # 한 회차에 몇 건까지만 — 그리는 건 느리다(한 건에 몇 초).
        # ★ 이미 받아 둔 상품은 다시 그리지 않는다.
        #   한 건에 40초쯤 걸린다. detail_limit 이 100 이면 회차마다 70분을
        #   같은 상품에 쓰게 된다. 실측은 잘 안 바뀌므로 한 번이면 된다.
        # 실측과 후기 원문은 같은 렌더 화면에서 얻지만 수명은 다르다.
        # 예전에는 실측이 한 번만 저장돼도 여기서 끝나서, 후기 원문이 0건인
        # 상품은 영원히 다시 시도하지 못했다. 둘 다 있을 때만 건너뛴다.
        has_measurements = bool(rec.get("measurements") or rec.get("_had_measurements"))
        has_reviews = self._has_saved_product_reviews(rec)
        if has_measurements and has_reviews:
            return
        try:
            with self.store._lock:
                row = self.store._conn.execute(
                    "SELECT measurements FROM staging_product "
                    "WHERE source_code=? AND source_uid=?",
                    (self.cfg.code, str(rec.get("source_uid") or ""))).fetchone()
            if (row and row[0] and row[0] not in ("", "{}", "null")
                    and has_reviews):
                return
        except Exception:      # noqa: BLE001 - 확인 실패로 수집을 멈추지 않는다
            pass

        cap = int((self.cfg.render or {}).get("detail_limit") or 0)
        self._sizefit_n = getattr(self, "_sizefit_n", 0)
        if cap and self._sizefit_n >= cap:
            return
        self._sizefit_n += 1
        rec["_review_capture_attempted"] = True
        try:
            from .renderer import Renderer
            if getattr(self, "_renderer", None) is None:
                self._renderer = Renderer(self.cfg, on_event=self._fetch_event)
            # ★ 상세는 '통째로' 받는다. 전에는 목록 수집기(count_sel="body")를
            #   그대로 써서 늦게 그려지는 실측표를 놓쳤다.
            rendered = self._renderer.render(
                url, scroll=22, full_page=True,
                steps=[{"click_text": "후기", "wait_ms": 1800}],
            )
            got = sizefit.parse(rendered.html, review_limit=500)
        except Exception as e:              # noqa: BLE001 - 사이즈 못 읽었다고 수집을 멈추지 않는다
            self._emit("warn", {"url": url,
                                "message": f"사이즈·핏을 못 읽었습니다: {e}"})
            return

        # ★ 못 읽었을 때 '왜'를 함께 남긴다. 전에는 같은 문장만 반복돼서
        #   화면을 못 받은 건지 파서가 못 읽은 건지 구별할 수 없었다.
        if not (got["measurements"] or got["fit_reviews"] or got["site_tags"]):
            h = rendered.html or ""
            self._emit("warn", {"url": url, "message": (
                f"사이즈·핏·태그를 못 읽었습니다 — 받은 화면 {len(h):,}자 · "
                f"'총장' {'있음' if '총장' in h else '없음'} · "
                f"'실측' {'있음' if '실측' in h else '없음'} · "
                f"표 {h.count('<table')}개 · 누른 탭 {rendered.steps or '없음'}"
                + (f" · {rendered.warns[0][:60]}" if rendered.warns else ""))})

        if got["measurements"]:
            rec["measurements"] = got["measurements"]
        if got["site_tags"]:
            merged = list(rec.get("site_tags") or [])
            for tag in got["site_tags"]:
                if tag not in merged:
                    merged.append(tag)
            rec["site_tags"] = merged
        s = got.get("fit_summary") or {}
        if s.get("fit_note"):
            rec["fit_note"] = s["fit_note"]
        if got["fit_reviews"]:
            rec["fit_reviews"] = got["fit_reviews"]
        # 체형 정보가 없는 일반 후기 원문도 별도로 담는다.
        from . import reviews
        ordinary = reviews.parse(self.cfg.code, rendered.html, limit=500)
        if ordinary:
            rec["reviews"] = ordinary
        if got["_why"]:
            self._emit("warn", {"url": url, "message": got["_why"]})
        else:
            self._emit("sizefit", {
                "url": url, "sizes": len(got["measurements"]),
                "reviews": len(got["fit_reviews"]), "tags": len(got["site_tags"]),
                "fit": s.get("fit_note", ""),
            })

    def _has_saved_product_reviews(self, rec: dict) -> bool:
        """이 플랫폼 상품에 익명 후기 원문이 하나라도 이미 저장됐는지 본다."""
        uid = str(rec.get("source_uid") or "")
        if not uid:
            return False
        try:
            with self.store._lock:
                row = self.store._conn.execute(
                    "SELECT 1 FROM text_document "
                    "WHERE source_code=? AND product_uid=? AND doc_kind='product_review' "
                    "LIMIT 1", (self.cfg.code, uid)).fetchone()
            return bool(row)
        except Exception:  # noqa: BLE001 - 확인 실패면 안전하게 다시 수집한다
            return False

    def _add_product_reviews(self, rec: dict, url: str):
        """동적 후기 탭을 제한적으로 그려 새 후기 원문을 붙인다."""
        from . import reviews
        opt = (self.cfg.render or {}).get("review_capture") or {}
        cap = int(opt.get("detail_limit") or 0)
        self._review_detail_n = getattr(self, "_review_detail_n", 0)
        if cap and self._review_detail_n >= cap:
            return
        self._review_detail_n += 1
        rec["_review_capture_attempted"] = True
        try:
            from .renderer import Renderer
            renderer = Renderer(self.cfg, on_event=self._fetch_event)
            # 에이블리와 무신사 전체 후기는 가상 목록이라 보이는 리뷰 카드를
            # 스크롤 중에 계속 주워야 한다. 지그재그는 상세 안의 리뷰 영역
            # 전체를 파서가 문맥과 함께 봐야 하므로 화면 전체를 보존한다.
            is_ably = self.cfg.code == "ably"
            is_musinsa = self.cfg.code in ("musinsa", "musinsa_used")
            capture_url = url
            if is_musinsa:
                m = re.search(r"/products/(\d+)", str(url))
                if m:
                    capture_url = ("https://www.musinsa.com/review/goods/"
                                   f"{m.group(1)}?sort=up_cnt_desc")
            result = renderer.render(
                capture_url,
                scroll=int(opt.get("scroll") or 80),
                target=int(opt.get("target") or 200),
                count_sel=("__musinsa_product_reviews__" if is_musinsa else
                           "__ably_product_reviews__" if is_ably else ""),
                full_page=not (is_ably or is_musinsa),
                steps=[] if is_musinsa else [
                    {"click_text": opt.get("click_text") or "리뷰 전체보기",
                     "wait_ms": int(opt.get("click_wait_ms") or 2500)}],
            )
            if not result.ok:
                raise RuntimeError(result.error or "후기 화면을 읽지 못했습니다")
            rows = reviews.parse(self.cfg.code, result.html,
                                 limit=int(opt.get("target") or 200))
            rec["reviews"] = rows
            self._emit("review_capture", {
                "url": capture_url, "found": len(rows),
                "target": int(opt.get("target") or 200),
                "rounds": result.scrolled, "elapsed": round(result.elapsed, 1),
                "warns": result.warns,
            })
        except Exception as exc:  # 후기 실패가 가격·상품 수집까지 막으면 안 된다.
            self._emit("warn", {"url": url,
                                "message": f"동적 상품 후기를 못 읽었습니다: {exc}"})

    def _save_list_record(self, r: dict):
        code = self.cfg.code
        uid = str(r.get("source_uid") or "")
        if not uid:
            return
        self.store.put_raw(code, "product_card", uid, r,
                           url=r.get("source_url", ""), http_status=200)
        self.store.upsert_product(
            code, uid,
            source_url=r.get("source_url"),
            name=r.get("name"),
            brand_name=r.get("brand"),
            image_url=r.get("image_url"),
        )
        # ★ 인기 지표. 예전엔 파서가 뽑아 놓고도 넣을 칸이 없어 버려졌다.
        #   크림 카드의 거래 수 2,489 같은 값이 원본에만 남고 사라졌었다.
        self.store.put_stat(code, uid, **stat_fields(code, r))
        if r.get("price"):
            # 목록의 가격은 '즉시 구매가'(=지금 살 수 있는 최저 호가)다.
            # 체결가가 아니므로 ask 로 넣는다. 섞으면 지수가 부푼다.
            self.store.put_listing(
                code, f"{uid}:list", to_int(r["price"]), "ask",
                listed_at=datetime.now(timezone.utc).isoformat(),
            )
            self.state.saved_listings += 1

    # ── 저장 ─────────────────────────────────────────────────
    def _save(self, rec: dict, res, url: str):
        code = self.cfg.code
        uid = str(rec.get("source_uid") or url.rstrip("/").rsplit("/", 1)[-1])

        # L0 원본 — 파서가 틀려도 여기서 다시 뽑을 수 있다
        self.store.put_raw(code, "product", uid,
                           {"html_len": len(res.text), "parsed": rec},
                           url=url, http_status=res.status)

        image_url = rec.get("image_url")
        if image_url and str(image_url).startswith("//"):
            image_url = "https:" + str(image_url)
        elif image_url and str(image_url).startswith("/"):
            image_url = "https://image.msscdn.net" + str(image_url)

        self.store.upsert_product(
            code, uid,
            # ★ '상세를 받아 봤다'는 도장. 목록에서 스쳐도 찍히는
            #   last_seen_at 과 달리 여기서만 찍힌다. 재방문이 이걸 보고
            #   아직 한 번도 상세를 못 받은 상품을 먼저 고른다.
            detail_seen_at=_now_iso(),
            source_url=url,
            name=rec.get("name"),
            name_en=rec.get("name_en"),
            brand_name=rec.get("brand"),
            **_retail(rec, self.store),
            release_date=rec.get("release_date"),
            image_url=image_url,
            model_code=rec.get("model_code"),
            category_path=rec.get("category_path"),
            size_names=rec.get("size_names") or [],
            # 실측 치수 — 사이즈 표기가 제각각인 중고를 비교할 유일한 공통 자
            measurements=rec.get("measurements") or None,
            # ★ 사이트가 붙여 준 태그 (#발레코어 …) — 스타일 태깅의 정답지
            site_tags=rec.get("site_tags") or None,
        )
        # 상세에서만 나오는 지표 — 무신사 후기 수·만족도가 여기 있다.
        self.store.put_stat(code, uid, **stat_fields(code, rec))
        self.state.saved_products += 1

        # 상품 후기 원문은 상품 수치와 분리해 text_document에 넣는다. 작성자
        # 닉네임은 저장하지 않고 비식별 해시만 남으며, put_text가 저장 직후
        # 사전 연결을 실행하므로 Luna 배치 분석 대기열에도 자동으로 나타난다.
        from . import reviews
        review_rows = list(rec.get("reviews") or [])
        review_rows.extend(rec.get("fit_reviews") or [])
        if code == "zigzag":
            review_rows.extend(reviews.parse(code, res.text))
        if review_rows:
            inserted = reviews.save(self.store, code, uid, review_rows)
            self._emit("reviews", {"url": url, "found": len(review_rows),
                                   "inserted": inserted, "anonymous": True})
        elif ((rec.get("review_count") or 0) > 0
              and rec.get("_review_capture_attempted")):
            self._emit("warn", {
                "url": url,
                "message": (f"후기 수는 {rec.get('review_count')}건이지만 원문은 0건입니다. "
                            "후기 탭 동적 로딩 또는 상세 렌더링을 점검하세요."),
            })

        ltype = rec.get("listing_type", self.cfg.listing_type_default)

        # 현재 가격 한 건
        if rec.get("price"):
            self.store.put_listing(
                code, f"{uid}:now", to_int(rec["price"]), ltype,
                size_name=rec.get("size_name"),
                listed_at=datetime.now(timezone.utc).isoformat(),
            )
            self.state.saved_listings += 1
            # ★ 가격 시계열은 모든 출처에서 남긴다.
            #   전에는 musinsa_used 만 남겼는데, 그러면 신품 쪽 시계열이 없어
            #   "정가 129,000 → 유즈드 36,400" 같은 비교를 그릴 수가 없다.
            #   할인율 추이도 신품 값이 있어야 나온다. 표가 0행이던 이유다.
            self.store.put_price_snapshot(
                code, uid, to_int(rec["price"]),
                initial_ask_price=to_int(rec.get("initial_ask_price")),
                discount=to_int(rec.get("discount")),
                condition_grade=rec.get("condition_grade"),
                availability_state=rec.get("availability_state"),
            )

        # 체결 이력 — 있으면 이게 제일 값지다
        for i, t in enumerate(rec.get("trades") or []):
            if not t.get("price"):
                continue
            self.store.put_listing(
                code, f"{uid}:t{i}", t["price"], "settled",
                size_name=t.get("size_name"),
                settled_at=t.get("settled_at"),
            )
            self.state.saved_listings += 1

    # ── 현황 ─────────────────────────────────────────────────
    def snapshot(self) -> dict:
        return {
            **self.state.to_dict(),
            "fetcher": self.fetcher.snapshot(),
            "store": self.store.stats(),
        }


def _retail(rec, store):
    """발매가를 원화로 맞춰 돌려준다. 환율기는 저장소에 붙어 있다."""
    fx = getattr(store, "fx", None)
    return retail_fields(rec, fx)
