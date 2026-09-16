"""YouTube ASR 대기열 수동 실행기.

비공식 음원 접근은 이 모듈 하나에 격리한다. 임시 파일은 TemporaryDirectory 밖으로
나가지 않으며, 성공하면 기존 save_transcript 경로로 들어가 원문·사전 보정이 이어진다.
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc
MODELS = {"tiny", "base", "small", "medium", "large-v3", "turbo"}


def dependency_state() -> dict:
    return {"yt_dlp": importlib.util.find_spec("yt_dlp") is not None,
            "faster_whisper": importlib.util.find_spec("faster_whisper") is not None}


def fashion_prompt(root: Path) -> str:
    try:
        terms = json.loads((root / "config" / "lexicon_master.json").read_text()).get("terms", [])
    except (OSError, ValueError):
        return "한국 패션, 스타일, 브랜드, 아이템, 소재와 코디를 설명하는 영상입니다."
    ordered = []
    for facet in ("style", "item", "material", "brand"):
        ordered += [str(t.get("canonical")) for t in terms
                    if t.get("facet") == facet and t.get("canonical")]
    # Whisper initial_prompt가 사전 전체로 오염되지 않도록 대표 용어만 제한한다.
    return "한국 패션 영상입니다. 정확히 표기할 주요 용어: " + ", ".join(ordered[:180])[:1400]


def download_audio(video_id: str, directory: Path) -> Path:
    from yt_dlp import YoutubeDL
    template = str(directory / "%(id)s.%(ext)s")
    opts = {"format": "bestaudio[ext=m4a]/bestaudio/best", "outtmpl": template,
            "quiet": True, "no_warnings": True, "noplaylist": True,
            "retries": 2, "socket_timeout": 20}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
        candidates = [Path(x.get("filepath")) for x in info.get("requested_downloads", [])
                      if x.get("filepath")]
        candidates.append(Path(ydl.prepare_filename(info)))
    found = next((p for p in candidates if p.exists()), None)
    if not found:
        raise RuntimeError("다운로드된 임시 음원을 찾지 못했습니다.")
    return found


def transcribe_audio(path: Path, model, prompt: str) -> tuple[list[dict], str]:
    def run(vad):
        segments, info = model.transcribe(str(path), language="ko", beam_size=5,
                                          vad_filter=vad, initial_prompt=prompt)
        rows = [{"start": float(s.start), "dur": max(0, float(s.end - s.start)),
                 "text": str(s.text).strip()} for s in segments if str(s.text).strip()]
        return rows, info

    rows, info = run(True)
    # 짧은 Shorts·배경음이 큰 영상은 VAD가 작은 목소리까지 무음으로 지울 수 있다.
    # 결과가 완전히 빌 때만 VAD 없이 한 번 재시도한다(정상 영상 비용은 늘지 않는다).
    if not rows:
        rows, info = run(False)
    return rows, str(getattr(info, "language", None) or "ko")


def explain_error(message: str) -> str:
    text = str(message or "")
    if "음성 인식 결과가 비어" in text:
        return "VAD 사용/미사용 두 방식 모두 말소리를 찾지 못했습니다. 음악·무음 중심 영상일 수 있습니다."
    if "모델 로드 실패" in text:
        return "Whisper 모델 다운로드 또는 로드에 실패했습니다. 네트워크와 저장 공간을 확인하세요."
    if "yt_dlp" in text or "DownloadError" in text or "download" in text.lower():
        return "YouTube 음원 접근에 실패했습니다. 삭제·연령 제한·로그인 요구 또는 차단 가능성이 있습니다."
    if "decode" in text.lower() or "InvalidData" in text:
        return "받은 오디오를 해석하지 못했습니다. 파일 형식 또는 다운로드 결과를 확인하세요."
    return "상세 오류를 확인한 뒤 다시 시도하세요. 같은 오류가 반복되면 영상을 수동 검토 대상으로 두세요."


def low_speech_signal(segments: list[dict]) -> bool:
    """음악/무음 영상의 짧은 감탄사를 유효 대본으로 오인하지 않는다."""
    chars = sum(len("".join(ch for ch in str(x.get("text") or "") if ch.isalnum()))
                for x in segments)
    speech_seconds = sum(max(0.0, float(x.get("dur") or 0)) for x in segments)
    return len(segments) < 3 or chars < 35 or speech_seconds < 6


class ASRWorker:
    def __init__(self, store, root: Path, downloader=download_audio, transcriber=transcribe_audio,
                 model_factory=None):
        self.store, self.root = store, root
        self.downloader, self.transcriber = downloader, transcriber
        self.model_factory = model_factory
        self._lock, self._stop = threading.RLock(), threading.Event()
        self._thread = None
        self._state = self._idle()
        with store.tx() as c:  # 이전 서버가 죽으며 남긴 running만 복구한다.
            c.execute("UPDATE yt_asr_queue SET status='pending',updated_at=datetime('now') "
                      "WHERE status='running'")

    @staticmethod
    def _idle():
        return {"phase": "idle", "selected": 0, "done": 0, "failed": 0,
                "current": None, "model": None, "errors": [],
                "started_at": None, "ended_at": None}

    def snapshot(self):
        from .social import asr_queue
        with self._lock:
            return {**self._state, "dependencies": dependency_state(),
                    "queue": asr_queue(self.store, limit=100)}

    def start(self, *, limit=1, model_name="small"):
        limit = max(1, min(int(limit), 3))
        if model_name not in MODELS:
            return {"ok": False, "error": "지원하지 않는 ASR 모델입니다."}
        with self._lock:
            if self._thread and self._thread.is_alive():
                return {"ok": False, "error": "이미 ASR 작업이 진행 중입니다."}
            deps = dependency_state()
            if self.model_factory is None and not all(deps.values()):
                return {"ok": False, "error": "yt-dlp와 faster-whisper 설치가 필요합니다.",
                        "dependencies": deps}
            with self.store._lock:
                rows = [r[0] for r in self.store._conn.execute(
                    "SELECT video_id FROM yt_asr_queue WHERE status='pending' "
                    "ORDER BY priority DESC,created_at LIMIT ?", (limit,))]
            if not rows:
                return {"ok": False, "error": "ASR 대기 영상이 없습니다."}
            self._stop.clear()
            self._state = {**self._idle(), "phase": "running", "selected": len(rows),
                           "model": model_name, "started_at": datetime.now(UTC).isoformat()[:19]}
            self._thread = threading.Thread(target=self._run, args=(rows, model_name),
                                            daemon=True, name="feedit-youtube-asr")
            self._thread.start()
            return {"ok": True, "selected": len(rows), "model": model_name}

    def stop(self):
        self._stop.set()
        return {"ok": True, "message": "현재 영상 처리가 끝나면 중지합니다."}

    def retry_failed(self, limit=3):
        limit = max(1, min(int(limit), 3))
        with self.store.tx() as c:
            ids = [r[0] for r in c.execute(
                "SELECT video_id FROM yt_asr_queue WHERE status='failed' "
                "ORDER BY updated_at DESC LIMIT ?", (limit,))]
            for video_id in ids:
                c.execute("UPDATE yt_asr_queue SET status='pending',last_error=NULL,"
                          "updated_at=datetime('now') WHERE video_id=?", (video_id,))
        return {"ok": True, "reset": len(ids)}

    def _load_model(self, name):
        if self.model_factory:
            return self.model_factory(name)
        from faster_whisper import WhisperModel
        return WhisperModel(name, device="cpu", compute_type="int8")

    def _run(self, rows, model_name):
        from . import social
        try:
            model = self._load_model(model_name)
        except Exception as exc:
            self._finish_all_failed(rows, f"모델 로드 실패: {str(exc)[:300]}")
            return
        prompt = fashion_prompt(self.root)
        for video_id in rows:
            if self._stop.is_set():
                break
            with self._lock:
                self._state["current"] = video_id
            with self.store.tx() as c:
                c.execute("UPDATE yt_asr_queue SET status='running',attempts=attempts+1,"
                          "updated_at=datetime('now') WHERE video_id=?", (video_id,))
            try:
                with tempfile.TemporaryDirectory(prefix="feedit-asr-") as tmp:
                    audio = self.downloader(video_id, Path(tmp))
                    segments, lang = self.transcriber(audio, model, prompt)
                    if not segments:
                        raise RuntimeError("음성 인식 결과가 비어 있습니다.")
                    social.save_transcript(self.store, video_id,
                                           social._vtt_from_segments(segments),
                                           origin="asr", lang=lang)
                    if low_speech_signal(segments):
                        from .youtube_ocr import enqueue
                        enqueue(self.store, video_id, "ASR 음성량 부족", priority=70)
                with self._lock:
                    self._state["done"] += 1
            except Exception as exc:
                message = f"{type(exc).__name__}: {str(exc)[:350]}"
                if "음성 인식 결과가 비어" in message:
                    from .youtube_ocr import enqueue
                    enqueue(self.store, video_id, "ASR 결과 없음 · 음악/무음 후보", priority=80)
                with self.store.tx() as c:
                    c.execute("UPDATE yt_asr_queue SET status='failed',last_error=?,"
                              "updated_at=datetime('now') WHERE video_id=?", (message, video_id))
                with self._lock:
                    self._state["failed"] += 1
                    self._state["errors"].append({"video_id": video_id, "error": message})
        with self._lock:
            self._state["phase"] = "stopped" if self._stop.is_set() else "done"
            self._state["current"] = None
            self._state["ended_at"] = datetime.now(UTC).isoformat()[:19]

    def _finish_all_failed(self, rows, message):
        with self.store.tx() as c:
            for video_id in rows:
                c.execute("UPDATE yt_asr_queue SET status='failed',last_error=?,"
                          "updated_at=datetime('now') WHERE video_id=?", (message, video_id))
        with self._lock:
            self._state.update(phase="done", failed=len(rows), current=None,
                               errors=[{"video_id": None, "error": message}],
                               ended_at=datetime.now(UTC).isoformat()[:19])
