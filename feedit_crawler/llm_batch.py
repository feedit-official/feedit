"""비용 폭주 없이 LLM 텍스트 분석을 조금씩 실행하는 단일 작업 큐."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from .llm_analysis import MODEL, PROMPT_VERSION, AnalysisError, OpenAITextAnalyzer

UTC = timezone.utc
INPUT_USD_PER_M = .20
OUTPUT_USD_PER_M = 1.20


class LLMBatch:
    def __init__(self, store, key_getter, linker=None, on_complete=None):
        self.store = store
        self.key_getter = key_getter
        self.linker = linker
        self.on_complete = on_complete
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._state = self._idle()

    @staticmethod
    def _idle():
        return {"phase": "idle", "requested": 0, "selected": 0, "done": 0,
                "failed": 0, "input_tokens": 0, "output_tokens": 0,
                "current": None, "errors": [], "estimate": None, "metric_build": None,
                "started_at": None, "ended_at": None}

    @staticmethod
    def _estimate(rows):
        # 한국어는 글자당 토큰 변동이 커서 보수적으로 1.5 token/char + 스키마 비용.
        input_tokens = sum(450 + round(len(r.get("body") or "") * 1.5) for r in rows)
        output_tokens = 650 * len(rows)
        usd = input_tokens / 1_000_000 * INPUT_USD_PER_M + \
              output_tokens / 1_000_000 * OUTPUT_USD_PER_M
        return {"documents": len(rows), "input_tokens": input_tokens,
                "output_tokens": output_tokens, "usd": round(usd, 4),
                "basis": "2026-08-27 공개 단가 기반 보수적 추정"}

    def snapshot(self):
        with self._lock:
            return {**self._state, "stats": self.store.llm_stats(MODEL, PROMPT_VERSION)}

    def preview(self, limit=20, source="all", target_keys=None):
        all_rows = self.store.llm_candidates(MODEL, PROMPT_VERSION, 50000, source,
                                             target_keys=target_keys)
        # 실행 상한과 미리보기 선택 건수가 같아야 한다. 500건을 고르고도
        # 미리보기에는 100건이라고 떠 사용자가 다른 큐로 오해했다.
        rows = all_rows[:max(1, min(int(limit), 500))]
        breakdown = {}
        for row in all_rows:
            reason = row.get("queue_reason") or "기타"
            breakdown[reason] = breakdown.get(reason, 0) + 1
        return {"ok": True, "selected": len(rows), "estimate": self._estimate(rows),
                "queue_total": len(all_rows), "queue_breakdown": breakdown,
                "queue_estimate": self._estimate(all_rows),
                "rows": [{**r, "body": (r.get("body") or "")[:220]} for r in rows],
                "stats": self.store.llm_stats(MODEL, PROMPT_VERSION)}

    def start(self, limit=20, source="all", target_keys=None):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return {"ok": False, "error": "이미 LLM 분석이 진행 중입니다."}
            key = self.key_getter()
            if not key:
                return {"ok": False, "error": "API 탭에서 OpenAI 키를 먼저 저장해 주세요."}
            rows = self.store.llm_candidates(MODEL, PROMPT_VERSION, limit, source,
                                             target_keys=target_keys)
            if not rows:
                return {"ok": False, "error": "새로 분석할 텍스트가 없습니다."}
            self._stop.clear()
            self._state = {**self._idle(), "phase": "running", "requested": int(limit),
                           "selected": len(rows), "estimate": self._estimate(rows),
                           "started_at": datetime.now(UTC).isoformat()[:19]}
            self._thread = threading.Thread(target=self._run, args=(key, rows),
                                            daemon=True, name="feedit-llm-batch")
            self._thread.start()
            return {"ok": True, "selected": len(rows)}

    def stop(self):
        self._stop.set()
        return {"ok": True, "message": "현재 호출이 끝나면 멈춥니다."}

    def _run(self, key, rows):
        analyzer = OpenAITextAnalyzer(key)
        for row in rows:
            if self._stop.is_set():
                break
            with self._lock:
                self._state["current"] = {"id": row["id"], "source": row["source_code"],
                                          "body": row["body"][:100]}
            last = None
            for attempt in range(2):
                try:
                    candidates = self.linker.candidates(row) if self.linker else []
                    result = analyzer.analyze(row["body"], candidates)
                    self.store.put_llm_analysis(row["id"], result)
                    if self.linker:
                        result, mentions = self.linker.resolve(result, candidates)
                        self.store.put_entity_resolution(row["id"], result, mentions)
                    with self._lock:
                        self._state["done"] += 1
                        self._state["input_tokens"] += result.get("input_tokens", 0)
                        self._state["output_tokens"] += result.get("output_tokens", 0)
                    last = None
                    break
                except Exception as e:
                    last = str(e)[:240]
                    if attempt == 0 and not self._stop.is_set():
                        time.sleep(1)
            if last:
                with self._lock:
                    self._state["failed"] += 1
                    if len(self._state["errors"]) < 10:
                        self._state["errors"].append({"id": row["id"], "error": last})
                # 인증·한도 오류는 뒤의 모든 호출도 똑같이 실패한다. 즉시 멈춘다.
                if "키가 거부" in last or "사용 한도" in last:
                    self._stop.set()
        metric_build = None
        if not self._stop.is_set() and self.on_complete:
            try:
                metric_build = self.on_complete()
            except Exception as exc:
                with self._lock:
                    if len(self._state["errors"]) < 10:
                        self._state["errors"].append({"id": None,
                                                       "error": f"지표 재계산: {str(exc)[:200]}"})
        with self._lock:
            self._state["phase"] = "stopped" if self._stop.is_set() else "done"
            self._state["current"] = None
            self._state["metric_build"] = metric_build
            self._state["ended_at"] = datetime.now(UTC).isoformat()[:19]
