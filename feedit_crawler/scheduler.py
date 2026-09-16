"""
정기 실행 — 12시간~하루 주기로 알아서 돌게 한다.

세컨 PC 에 켜 두고 잊는 게 목표라, 사람이 버튼을 누르지 않아도 돌아야 한다.
대신 **혼자 조용히 틀리면 안 되므로** 매번 끝날 때 건강 점검을 남긴다.

설정 파일에 이렇게 적으면 된다:

    schedule:
      every_hours: 12      # 0 이거나 없으면 자동 실행 안 함
      list_only: false
      max_items: 200
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from . import health

UTC = timezone.utc
CHECK_EVERY = 60.0          # 1분마다 '돌 때가 됐나' 확인


class Scheduler:
    def __init__(self, server_mod):
        self.S = server_mod          # server 모듈 (jobs, store, 설정 읽기)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_run: dict[str, float] = {}
        self.last_error: dict[str, str] = {}
        self.enabled = True
        # 렌더 중인 플랫폼 — CrawlJob 이 아직 없는 구간을 화면에 알린다.
        self.rendering: dict[str, dict] = {}
        # 시험 모드 — 켜면 어디든 5개만 가져온다.
        # 설정을 고치는 동안 400개씩 기다리는 건 시간 낭비다.
        self.test_mode = False
        self.test_size = 5
        # ★ 플랫폼마다 켜고 끈다
        #   주기가 12시간이라고 해서 늘 돌아야 하는 건 아니다. 설정을 손보는
        #   동안이나 그 사이트가 말썽일 때는 그 하나만 쉬게 할 수 있어야 한다.
        #   껐다 켜도 유지되도록 data/ 에 적어 둔다.
        self.off: set[str] = set()
        self._load_off()

    def _off_path(self):
        from pathlib import Path
        return Path(self.S.DATA_DIR) / "auto_off.json"

    def _load_off(self):
        try:
            import json
            self.off = set(json.loads(self._off_path().read_text(encoding="utf-8")))
        except Exception:
            self.off = set()

    def _save_off(self):
        try:
            import json
            self._off_path().write_text(
                json.dumps(sorted(self.off), ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def set_auto(self, code: str, on: bool):
        if on:
            self.off.discard(code)
        else:
            self.off.add(code)
        self._save_off()

    # ── 설정에서 주기 읽기 ────────────────────────────────────
    def plans(self) -> dict[str, dict]:
        out = {}
        for p in self.S.iter_config_files():
            try:
                cfg = self.S.SiteConfig.load(p)
            except Exception:
                continue
            sc = getattr(cfg, "schedule", None) or {}
            if not isinstance(sc, dict):
                continue
            hours = float(sc.get("every_hours") or 0)
            if hours <= 0:
                continue
            out[cfg.code] = {
                "every_hours": hours,
                "list_only": bool(sc.get("list_only", False)),
                "max_items": sc.get("max_items"),
                "name": cfg.name,
            }
        # 소셜은 사이트 YAML이 아니라 공식 API 수집기다. 두 경로 모두 발표 타깃
        # 사전 타깃 12개와 고정 상품 1개만 사용하고 커머스보다 짧은 6시간 주기로 돈다.
        out["naver"] = {"every_hours": 6.0, "list_only": False,
                        "max_items": None, "name": "네이버"}
        out["youtube"] = {"every_hours": 6.0, "list_only": False,
                          "max_items": None, "name": "유튜브"}
        return out

    def due(self, code: str, hours: float) -> bool:
        last = self.last_run.get(code)
        if last is None:
            # 껐다 켜도 이어지도록 DB 의 마지막 실행 시각을 본다
            last = self._last_from_db(code)
            if last is not None:
                self.last_run[code] = last
        if last is None:
            return True
        return (time.time() - last) >= hours * 3600

    def _last_from_db(self, code: str):
        """마지막으로 이 사이트를 돈 시각. 껐다 켜도 이어지게 DB 에서 찾는다.

        ★ crawl_run 만 보면 안 된다
          에이블리처럼 **브라우저로 목록을 그려 오는** 사이트는 crawl_run 을
          안 남긴다. 그래서 서버를 켤 때마다 '한 번도 안 돈 것' 으로 보이고,
          곧바로 수집이 시작됐다. 켜자마자 브라우저가 뜨는 이유가 이것이었다.

          실제로 자료가 들어온 시각(staging_product.last_seen_at)도 같이 본다.
          어느 길로 모았든 '언제 마지막으로 들어왔나' 는 남기 때문이다.
        """
        best = None
        try:
            if code == "naver":
                with self.S.store._lock:
                    r = self.S.store._conn.execute(
                        "SELECT max(collected_at) FROM text_document WHERE source_code='naver'").fetchone()
                return datetime.fromisoformat(r[0]).replace(tzinfo=timezone.utc).timestamp() if r and r[0] else None
            if code == "youtube":
                with self.S.store._lock:
                    r = self.S.store._conn.execute(
                        "SELECT max(collected_at) FROM text_document WHERE source_code='youtube'").fetchone()
                return datetime.fromisoformat(r[0]).replace(tzinfo=timezone.utc).timestamp() if r and r[0] else None
            with self.S.store._lock:
                r = self.S.store._conn.execute(
                    "SELECT started_at FROM crawl_run WHERE source_code=? "
                    "ORDER BY id DESC LIMIT 1", (code,)).fetchone()
                if r and r[0]:
                    best = datetime.fromisoformat(r[0]).timestamp()
                r2 = self.S.store._conn.execute(
                    "SELECT max(last_seen_at) FROM staging_product WHERE source_code=?",
                    (code,)).fetchone()
            if r2 and r2[0]:
                # SQLite datetime('now') 는 UTC 다. 같은 잣대로 맞춘다.
                t = datetime.fromisoformat(r2[0]).replace(
                    tzinfo=timezone.utc).timestamp()
                best = t if best is None else max(best, t)
        except Exception:
            pass
        return best

    # ── 본체 ──────────────────────────────────────────────────
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.wait(CHECK_EVERY):
            if not self.enabled:
                continue
            try:
                self._tick()
            except Exception as e:                 # 스케줄러가 죽으면 안 된다
                self.last_error["__loop__"] = str(e)

    def _tick(self):
        for code, plan in self.plans().items():
            if self._stop.is_set():
                return
            job = self.S.jobs.get(code)
            if job and job.state.phase in ("list", "detail", "prepare"):
                continue                            # 이미 돌고 있으면 건너뛴다
            if code in self.off:
                continue                            # 꺼 둔 플랫폼은 쉰다
            # 같은 호스트의 수집기(예: musinsa / musinsa_used)는 절대 동시에
            # 열지 않는다. 한 작업이 끝난 다음 점검 주기에 다른 작업이 시작된다.
            if self._same_host_running(code):
                continue
            if not self.due(code, plan["every_hours"]):
                continue
            self._run(code, plan)

        # ★ 다음 수집이 코앞인데 Luna 대기열이 남아 있으면 미리 털어 낸다.
        #   수집은 6~12시간마다 도는데 분석은 사람이 눌러야 돌아서, 대기열에
        #   수천 건이 밀린 채 다음 회차가 오곤 했다 (실제로 7,108건이 밀려 있었다).
        try:
            # ★ due_in_min 은 plans() 가 아니라 snapshot() 이 만든다.
            #   plans() 는 '주기가 몇 시간인가'만 알고 '언제인가'는 모른다.
            snap = self.snapshot() or {}
            dues = [p["due_in_min"] for p in (snap.get("plans") or {}).values()
                    if isinstance(p, dict) and p.get("due_in_min") is not None
                    and p.get("auto") is not False]
            if dues:
                self.S.luna_autorun_if_due(min(dues))
        except Exception as e:      # noqa: BLE001 - 분석 실패로 수집을 멈추지 않는다
            self.last_error["luna"] = str(e)

    def _same_host_running(self, code: str) -> bool:
        from urllib.parse import urlsplit
        try:
            cfg = self.S.SiteConfig.load(self.S._config_path(code))
            host = urlsplit(cfg.base_url).netloc.lower().removeprefix("www.")
        except Exception:
            return False
        for other, job in self.S.jobs.items():
            if other == code or job.state.phase not in ("list", "detail", "prepare"):
                continue
            try:
                ocfg = self.S.SiteConfig.load(self.S._config_path(other))
                ohost = urlsplit(ocfg.base_url).netloc.lower().removeprefix("www.")
                if host == ohost:
                    return True
            except Exception:
                continue
        return False

    def _run(self, code: str, plan: dict):
        from .runner import CrawlJob
        if code in ("naver", "youtube"):
            self.last_run[code] = time.time()
            self.last_error.pop(code, None)
            threading.Thread(target=self._run_social, args=(code,), daemon=True).start()
            return
        if self._same_host_running(code):
            self.last_error[code] = "같은 사이트의 다른 수집이 실행 중이라 서버 보호를 위해 건너뛰었습니다."
            self.S._record("warn", {"t": _hhmmss(),
                "msg": f"[자동] {code} — {self.last_error[code]}"})
            return
        test = self.test_mode
        try:
            cfg = self.S.SiteConfig.load(self.S._config_path(code))
        except Exception as e:
            self.last_error[code] = f"설정을 읽지 못했습니다: {e}"
            return

        seeds = list(self.S._safe_seeds(cfg))
        revisit = (getattr(cfg, "revisit", None) or {})
        render = (getattr(cfg, "render", None) or {})

        if not seeds and not revisit.get("enabled") and not render.get("enabled"):
            self.last_error[code] = ("시드도 없고 재방문·렌더링도 꺼져 있어 돌 게 없습니다. "
                                     "자동 실행 대상에서 빼거나 시드를 채우세요.")
            self.S._record("warn", {"t": _hhmmss(),
                                    "msg": f"[자동] {cfg.name} — {self.last_error[code]}"})
            return

        self.last_run[code] = time.time()
        self.last_error.pop(code, None)
        self.S._record("info", {"t": _hhmmss(),
            "msg": (f"[자동] {cfg.name} 수집 시작"
                    + (f"  ※ 시험 모드 — {self.test_size}개만" if test else ""))})

        # ── ① 브라우저로 목록 그려 오기 ──
        #  지그재그·에이블리는 서버가 빈 껍데기를 준다. 여기서 목록을 채워야
        #  그 다음 단계(상세·재방문)가 볼 게 생긴다.
        #  ★ 예전엔 이 단계를 아예 안 불렀다. 렌더러를 만들어 두고 연결을 빠뜨려서,
        #    두 사이트가 '돌 게 없다'며 즉시 끝나고 있었다.
        if render.get("enabled"):
            # ★ 렌더 단계는 화면에서 안 보였다.
            #   jobs[code] 는 렌더가 다 끝난 뒤에야 생기는데, 렌더가 제일 오래
            #   걸린다(무신사는 15칸). 그동안 카드는 '대기 · 0/0 · 예상 –' 이고
            #   버튼도 살아 있어서, 도는 중인데 안 도는 것처럼 보였다.
            pages = len(render.get("pages") or [])
            self.rendering[code] = {"phase": "render", "done": 0, "total": pages,
                                    "label": "", "started_at": time.time()}
            try:
                self._render_step(code, cfg, test=test)
            finally:
                self.rendering.pop(code, None)

        # 렌더링으로 상품이 생겼으면 재방문 대상도 생겼을 수 있다.
        if not seeds and not revisit.get("enabled"):
            self._finish(code)
            return

        job = CrawlJob(cfg, self.S.store, on_event=self.S._record,
                       max_items=(self.test_size if test else plan.get("max_items")),
                       list_only=plan.get("list_only", False))
        self.S.jobs[code] = job
        job.start()

        # 끝나면 건강 점검을 남긴다 — 이게 자동 운전의 핵심이다.
        threading.Thread(target=self._after, args=(code, job), daemon=True).start()

    def _run_social(self, code: str):
        self.S._record("info", {"t": _hhmmss(), "msg": f"[자동] {code} 타깃 12개 + 고정 상품 1개 수집 시작"})
        try:
            result = self.S.run_automatic_social(code)
            if not result.get("ok"):
                raise RuntimeError(result.get("error") or "알 수 없는 실패")
            self.S._record("info", {"t": _hhmmss(), "msg": f"[자동] {code} 수집 완료"})
            self.S.after_automatic_collection(code)
        except Exception as exc:
            self.last_error[code] = str(exc)
            self.S._record("error", {"t": _hhmmss(), "msg": f"[자동] {code} 실패 — {exc}"})
            self._problem(f"{code} 자동 수집에 실패했습니다", code, raw=str(exc))

    def _render_step(self, code: str, cfg, test: bool = False):
        """브라우저로 목록을 그려 와서 곧바로 DB 에 넣는다.

        실패해도 전체를 멈추지 않는다 — 상세·재방문은 계속 갈 수 있다.
        다만 **왜 실패했는지는 반드시 로그에 남긴다.** 조용히 넘어가면
        '자동인데 왜 안 늘지' 하고 한참 헤매게 된다.
        """
        from .renderer import RenderBlocked, RenderUnavailable, render_and_import
        try:
            def _page_done(n, label, _code=code):
                st = self.rendering.get(_code)
                if st:
                    st["done"], st["label"] = n, label or ""

            got = render_and_import(cfg, self.S.store, on_event=self.S._record,
                                    save_dir=self.S.DATA_DIR / "rendered",
                                    limit=(self.test_size if test else 0),
                                    on_page=_page_done)
            # 페이지마다 결과를 남긴다. 합계만 보면 어느 카테고리가 막혔는지 모른다.
            for r in got.get("results", []):
                nm = r.get("label") or r.get("url", "")
                steps = " → ".join(r.get("steps") or []) or "(탭 없음)"
                # ★ 숫자를 먼저 남긴다. 실패했을 때 error 만 찍고 넘어갔더니
                #   '카드를 몇 개 주웠는지'를 알 수가 없어서 원인 추적이 막혔다.
                #   화면에서 몇 개를 봤는지가 제일 중요한 단서다.
                self.S._record(
                    "info" if r.get("products") else "warn",
                    {"t": _hhmmss(),
                     "msg": (f"[렌더링] {cfg.name} · {nm} — {steps} · "
                             f"화면에서 {r.get('count',0)}개 주움"
                             f"(목표 {r.get('target',0)}) · "
                             f"{r.get('kb',0)}KB → 저장 {r.get('products',0)}건")})
                for w in (r.get("warns") or []):
                    self.S._record("warn", {"t": _hhmmss(),
                        "msg": f"[렌더링] {cfg.name} · {nm} — {w[:120]}"})
                if r.get("error"):
                    self.S._record("error", {"t": _hhmmss(),
                        "msg": f"[렌더링] {cfg.name} · {nm} — {r['error'][:90]}"})
                    self._problem(f"{nm} 페이지를 못 읽었습니다", code,
                                  raw=r["error"], url=r.get("url", ""))
                elif not r.get("products"):
                    # 열리긴 했는데 아무것도 못 주웠다 — 화면이 바뀐 신호
                    self._problem(
                        f"{nm} 에서 상품을 하나도 못 찾았습니다", code,
                        detail=f"페이지는 열렸습니다 ({r.get('kb',0)}KB). "
                               f"화면에서 주운 것 {r.get('count',0)}개.",
                        raw="카드를 못 찾았습니다 (0건)", url=r.get("url", ""))
                if r.get("saved"):
                    self.S._record("info", {"t": _hhmmss(),
                        "msg": f"[렌더링] {cfg.name} · {nm} — 원본 저장 {r['saved']}"})
            self.S._record("info", {
                "t": _hhmmss(),
                "msg": (f"[렌더링] {cfg.name} 끝 — 페이지 {got['pages']}장에서 "
                        f"{got['products']}건 저장"
                        + (f" · 실패 {got['failed']}장" if got["failed"] else ""))})
            if not got["products"]:
                self.last_error[code] = (
                    "렌더링은 됐지만 상품을 하나도 못 찾았습니다. "
                    "설정의 list_page.card 또는 탭 글자를 확인하세요.")
        except RenderBlocked as e:
            msg = str(e).splitlines()[0]
            self.last_error[code] = msg
            self.S._record("error", {"t": _hhmmss(), "msg": f"[렌더링] {msg}"})
            self._problem("사이트가 자동 수집을 금지하고 있습니다", code,
                          kind="robots", raw=str(e))
        except RenderUnavailable as e:
            msg = str(e).splitlines()[0]
            self.last_error[code] = (
                msg + "  →  pip install playwright && python -m playwright install chromium")
            self.S._record("error", {"t": _hhmmss(),
                                     "msg": f"[렌더링] {cfg.name} — {self.last_error[code]}"})
            self._problem("브라우저가 준비되지 않았습니다", code,
                          kind="js_render", raw=str(e))
        except Exception as e:
            self.last_error[code] = f"렌더링 실패: {e}"
            self.S._record("error", {"t": _hhmmss(),
                                     "msg": f"[렌더링] {cfg.name} — {e}"})
            self._problem(f"{cfg.name} 수집 중 문제가 생겼습니다", code, exc=e)

    def _problem(self, title, code, **kw):
        """문제를 사람 말로 남긴다.

        ★ 여기서 실패해도 수집은 안 멈춘다. 다만 **조용히 넘어가지는 않는다** —
          기록하는 코드가 고장 나면 그 뒤로 아무 문제도 안 보이는데,
          화면은 '문제 없음'이라고 말한다. 그게 제일 위험하다.
        """
        try:
            self.S.PROBLEMS.add(title=title, source_code=code,
                                where="자동 수집", **kw)
        except Exception as e:
            self.S._record("error", {"t": _hhmmss(),
                "msg": f"[내부] 문제 기록에 실패했습니다: {e}"})

    def _finish(self, code: str):
        """수집 없이 렌더링만 하고 끝난 경우에도 점검 기록은 남긴다."""
        record = getattr(self.S, "_record_inspection", self.S._record)
        try:
            health.snapshot(self.S.store, code, note="자동 실행(렌더링)")
            res = health.check(self.S.store, code)
            for i in res["issues"]:
                record("error" if i["level"] == "bad" else "warn",
                       {"t": _hhmmss(), "msg": f"[점검] {code} — {i['text']}"})
        except Exception as e:
            self.last_error[code] = f"점검 실패: {e}"
        self.S.after_automatic_collection(code)

    def _after(self, code: str, job):
        t = getattr(job, "_thread", None)
        if t:
            t.join()
        snap = job.snapshot()
        f = snap.get("fetcher") or {}
        record = getattr(self.S, "_record_inspection", self.S._record)
        try:
            health.snapshot(self.S.store, code,
                            errors=snap.get("errors", 0),
                            blocked=bool(f.get("blocked")),
                            note="자동 실행")
            res = health.check(self.S.store, code)
            lv = res["level"]
            if lv in ("warn", "bad"):
                for i in res["issues"]:
                    record("error" if i["level"] == "bad" else "warn",
                           {"t": _hhmmss(), "msg": f"[점검] {code} — {i['text']}"})
            else:
                record("info", {"t": _hhmmss(), "msg": f"[점검] {code} 정상"})
        except Exception as e:
            self.last_error[code] = f"점검 실패: {e}"
        self.S.after_automatic_collection(code)

    def snapshot(self) -> dict:
        pl = self.plans()
        _ = None
        out = {}
        for code, p in pl.items():
            last = self.last_run.get(code) or self._last_from_db(code)
            nxt = (last + p["every_hours"] * 3600) if last else time.time()
            out[code] = {
                **p,
                "last_run": datetime.fromtimestamp(last, UTC).isoformat() if last else None,
                "next_run": datetime.fromtimestamp(nxt, UTC).isoformat(),
                "due_in_min": max(0, int((nxt - time.time()) / 60)),
                "error": self.last_error.get(code),
                "auto": code not in self.off,
            }
        return {"enabled": self.enabled, "test_mode": self.test_mode,
                "test_size": self.test_size, "plans": out}


def _hhmmss() -> str:
    return datetime.now().strftime("%H:%M:%S")
