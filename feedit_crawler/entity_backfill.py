"""API 비용 없이 기준 사전으로 기존 텍스트 엔티티를 백필한다."""
from __future__ import annotations

import threading
from datetime import datetime, timezone

UTC = timezone.utc


class EntityBackfill:
    def __init__(self, store, linker, on_complete=None):
        self.store = store
        self.linker = linker
        self.on_complete = on_complete
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._state = self._idle()

    @staticmethod
    def _idle():
        return {"phase": "idle", "selected": 0, "done": 0, "failed": 0,
                "confirmed": 0, "candidate": 0, "unresolved": 0,
                "current": None, "errors": [], "metric_build": None,
                "started_at": None, "ended_at": None}

    def snapshot(self):
        with self._lock:
            return {**self._state, "stats": self.store.entity_backfill_stats()}

    def start(self, limit=5000, source="all"):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return {"ok": False, "error": "사전 직접 연결이 이미 진행 중입니다."}
            rows = self.store.entity_backfill_candidates(limit, source)
            if not rows:
                return {"ok": False, "error": "새로 사전 연결할 텍스트가 없습니다."}
            self._stop.clear()
            self._state = {**self._idle(), "phase": "running", "selected": len(rows),
                           "started_at": datetime.now(UTC).isoformat()[:19]}
            self._thread = threading.Thread(target=self._run, args=(rows,), daemon=True,
                                            name="feedit-entity-backfill")
            self._thread.start()
            return {"ok": True, "selected": len(rows)}

    def stop(self):
        self._stop.set()
        return {"ok": True, "message": "현재 문서 처리가 끝나면 멈춥니다."}

    def _run(self, rows):
        for row in rows:
            if self._stop.is_set():
                break
            try:
                result, mentions = self.linker.rules_only(row)
                self.store.put_entity_resolution(row["id"], result, mentions)
                status = result["resolution_status"]
                with self._lock:
                    self._state["done"] += 1
                    self._state[status] += 1
                    self._state["current"] = {"id": row["id"], "source": row["source_code"]}
            except Exception as exc:
                with self._lock:
                    self._state["failed"] += 1
                    if len(self._state["errors"]) < 10:
                        self._state["errors"].append({"id": row["id"], "error": str(exc)[:240]})
        metric_build = None
        if not self._stop.is_set() and self.on_complete:
            try:
                metric_build = self.on_complete()
            except Exception as exc:
                with self._lock:
                    self._state["errors"].append({"id": None, "error": f"지표 재계산: {exc}"})
        with self._lock:
            self._state["phase"] = "stopped" if self._stop.is_set() else "done"
            self._state["current"] = None
            self._state["metric_build"] = metric_build
            self._state["ended_at"] = datetime.now(UTC).isoformat()[:19]
