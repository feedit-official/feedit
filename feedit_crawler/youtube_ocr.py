"""화면에 구워진 YouTube 자막을 읽는 조건부 로컬 OCR 작업기.

공개 caption과 ASR이 먼저다. 이 모듈은 음악/무음 중심 영상처럼 음성 대본이
부족한 경우에만 수동 실행한다. 분석용 저해상도 영상은 임시 폴더에서만 살며,
DB에는 병합한 타임라인과 신뢰도만 남긴다.
"""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc
def _vision_runtime_state() -> tuple[bool, str]:
    """가벼운 사전 검사만 한다.

    Swift와 SDK의 patch 문자열은 달라도 실제 module import가 가능한 배포 조합이
    있다. 관리자가 Terminal에서 확인한 실행 가능 상태를 잘못 차단하지 않도록
    경로 존재만 보고, 진짜 호환성 오류는 OCR subprocess 결과로 표시한다.
    """
    if platform.system() != "Darwin":
        return False, "Apple Vision 화면 OCR은 macOS에서만 실행할 수 있습니다."
    if not shutil.which("swift"):
        return False, "swift 실행 파일이 없습니다. Command Line Tools를 확인하세요."
    return True, ""


def dependency_state() -> dict:
    vision_ok, vision_error = _vision_runtime_state()
    return {
        "yt_dlp": __import__("importlib.util").util.find_spec("yt_dlp") is not None,
        "swift": shutil.which("swift") is not None,
        "apple_vision": vision_ok,
        "apple_vision_error": vision_error,
    }


def install(store):
    with store._lock:
        store._conn.executescript("""
        CREATE TABLE IF NOT EXISTS yt_ocr_queue (
          video_id TEXT PRIMARY KEY,
          status TEXT NOT NULL DEFAULT 'pending',
          reason TEXT,
          priority INTEGER DEFAULT 40,
          attempts INTEGER DEFAULT 0,
          last_error TEXT,
          created_at TEXT DEFAULT (datetime('now')),
          updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS yt_ocr_evidence (
          video_id TEXT PRIMARY KEY,
          engine TEXT NOT NULL,
          sample_interval REAL NOT NULL,
          sampled_frames INTEGER DEFAULT 0,
          accepted_frames INTEGER DEFAULT 0,
          mean_confidence REAL,
          segments TEXT NOT NULL DEFAULT '[]',
          created_at TEXT DEFAULT (datetime('now'))
        );
        """)
        store._conn.commit()


def enqueue(store, video_id: str, reason: str, priority: int = 40) -> bool:
    install(store)
    with store.tx() as c:
        exists = c.execute("SELECT 1 FROM yt_video WHERE video_id=?", (video_id,)).fetchone()
        if not exists:
            return False
        c.execute("INSERT INTO yt_ocr_queue(video_id,status,reason,priority) "
                  "VALUES (?,'pending',?,?) ON CONFLICT(video_id) DO UPDATE SET "
                  "status=CASE WHEN yt_ocr_queue.status='running' THEN 'running' ELSE 'pending' END,"
                  "reason=excluded.reason,priority=max(yt_ocr_queue.priority,excluded.priority),"
                  "last_error=NULL,updated_at=datetime('now')",
                  (video_id, str(reason)[:200], max(0, min(int(priority), 100))))
    return True


def download_video(video_id: str, directory: Path) -> Path:
    from yt_dlp import YoutubeDL
    template = str(directory / "%(id)s.%(ext)s")
    # OCR에는 음성이 필요 없다. YouTube는 합쳐진 저해상도 A/V 포맷 없이
    # video-only DASH만 주는 영상이 많으므로 bestvideo를 직접 고른다.
    # Apple AVFoundation 호환성이 높은 AVC MP4 480p를 가장 먼저 선택한다.
    opts = {"format": ("bestvideo[height<=480][ext=mp4][vcodec^=avc1]/"
                       "bestvideo[height<=480][ext=mp4]/"
                       "bestvideo[height<=480]/"
                       "bestvideo[ext=mp4][vcodec^=avc1]/bestvideo"),
            "outtmpl": template, "quiet": True, "no_warnings": True,
            "noplaylist": True, "retries": 2, "socket_timeout": 25}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
        candidates = [Path(x.get("filepath")) for x in info.get("requested_downloads", [])
                      if x.get("filepath")]
        candidates.append(Path(ydl.prepare_filename(info)))
    found = next((p for p in candidates if p.exists()), None)
    if not found:
        raise RuntimeError("다운로드된 분석용 영상을 찾지 못했습니다.")
    return found


_VISION_SWIFT = r'''
import Foundation
import AVFoundation
import Vision
import AppKit

let args = CommandLine.arguments
guard args.count >= 5 else { fputs("usage: video interval maxFrames minConfidence\n", stderr); exit(2) }
let url = URL(fileURLWithPath: args[1])
let interval = max(0.5, Double(args[2]) ?? 2.0)
let maxFrames = max(1, Int(args[3]) ?? 120)
let minConfidence = Float(args[4]) ?? 0.55
let asset = AVURLAsset(url: url)
let duration = CMTimeGetSeconds(asset.duration)
if !duration.isFinite || duration <= 0 { fputs("invalid video duration\n", stderr); exit(3) }
let generator = AVAssetImageGenerator(asset: asset)
generator.appliesPreferredTrackTransform = true
generator.maximumSize = NSSize(width: 960, height: 960)
var output: [[String: Any]] = []
var sampled = 0
var second = 0.0
while second < duration && sampled < maxFrames {
  defer { sampled += 1; second += interval }
  guard let image = try? generator.copyCGImage(at: CMTime(seconds: second, preferredTimescale: 600), actualTime: nil) else { continue }
  let request = VNRecognizeTextRequest()
  request.recognitionLevel = .accurate
  request.recognitionLanguages = ["ko-KR", "en-US"]
  request.usesLanguageCorrection = true
  request.regionOfInterest = CGRect(x: 0.0, y: 0.0, width: 1.0, height: 0.62)
  let handler = VNImageRequestHandler(cgImage: image)
  guard (try? handler.perform([request])) != nil else { continue }
  let lines = (request.results ?? []).compactMap { observation -> [String: Any]? in
    guard let candidate = observation.topCandidates(1).first, candidate.confidence >= minConfidence else { return nil }
    return ["text": candidate.string, "confidence": Double(candidate.confidence)]
  }
  if !lines.isEmpty { output.append(["time": second, "lines": lines]) }
}
let data = try JSONSerialization.data(withJSONObject: ["sampled_frames": sampled, "frames": output])
FileHandle.standardOutput.write(data)
'''


def apple_vision_ocr(path: Path, *, interval: float = 2.0, max_frames: int = 120,
                     min_confidence: float = .55) -> dict:
    if not dependency_state()["apple_vision"]:
        raise RuntimeError("Apple Vision OCR은 macOS와 swift가 필요합니다.")
    with tempfile.TemporaryDirectory(prefix="feedit-vision-") as tmp:
        source = Path(tmp) / "ScreenOCR.swift"
        source.write_text(_VISION_SWIFT, encoding="utf-8")
        run = subprocess.run(
            ["swift", str(source), str(path), str(interval), str(max_frames),
             str(min_confidence)], capture_output=True, text=True, timeout=900,
            env={**__import__("os").environ, "CLANG_MODULE_CACHE_PATH": str(Path(tmp) / "cache")})
    if run.returncode:
        raise RuntimeError((run.stderr or run.stdout or "Vision OCR 실패")[-500:])
    return json.loads(run.stdout)


def _normal(text: str) -> str:
    return "".join(ch.lower() for ch in str(text) if ch.isalnum() or "가" <= ch <= "힣")


def merge_frames(result: dict, *, interval: float = 2.0,
                 min_confidence: float = .55) -> list[dict]:
    """연속 프레임의 같은 문장을 하나의 타임라인 구간으로 합친다."""
    segments = []
    for frame in result.get("frames") or []:
        at = max(0.0, float(frame.get("time") or 0))
        lines = [x for x in frame.get("lines") or []
                 if float(x.get("confidence") or 0) >= min_confidence]
        text = " ".join(str(x.get("text") or "").strip() for x in lines).strip()
        if len(_normal(text)) < 2:
            continue
        confidence = sum(float(x.get("confidence") or 0) for x in lines) / len(lines)
        key = _normal(text)
        if segments and (key == segments[-1]["key"] or
                         (len(key) >= 6 and (key in segments[-1]["key"] or
                                             segments[-1]["key"] in key))):
            segments[-1]["end"] = at + interval
            if len(text) > len(segments[-1]["text"]):
                segments[-1]["text"], segments[-1]["key"] = text, key
            segments[-1]["confidence"] = max(segments[-1]["confidence"], confidence)
        else:
            segments.append({"start": at, "end": at + interval, "text": text,
                             "confidence": confidence, "key": key})
    return [{"start": round(x["start"], 3), "dur": round(x["end"] - x["start"], 3),
             "text": x["text"], "confidence": round(x["confidence"], 4)}
            for x in segments]


def explain_error(message: str) -> str:
    text = str(message or "").lower()
    if "apple vision" in text or "swift" in text:
        return "이 로컬 OCR은 macOS Apple Vision이 필요합니다. 다른 OS에서는 OCR 어댑터를 교체하세요."
    if "video unavailable" in text or "private video" in text:
        return "현재 YouTube에서 영상을 볼 수 없습니다. 삭제·비공개·지역 제한 여부를 확인하세요."
    if "requested format is not available" in text:
        return "OCR용 호환 영상 포맷이 없습니다. 포맷 목록을 확인하거나 영상을 수동 검토하세요."
    if "sign in" in text or "login" in text or "age" in text:
        return "로그인 또는 연령 확인이 필요한 영상이라 자동으로 받을 수 없습니다."
    if "download" in text or "yt_dlp" in text:
        return "분석용 영상을 받지 못했습니다. 네트워크와 영상 공개 상태를 확인하세요."
    if "timed out" in text or "timeout" in text:
        return "영상 OCR 제한 시간을 넘었습니다. 프레임 수나 영상 처리 길이를 낮추세요."
    if "화면 글자를" in text:
        return "설정한 신뢰도 이상 화면 자막이 없었습니다. 영상 또는 OCR 임계값을 검토하세요."
    return "기술 오류를 펼쳐 확인한 뒤 이 영상만 다시 시도하세요."


class OCRWorker:
    def __init__(self, store, root: Path, downloader=download_video, recognizer=apple_vision_ocr):
        self.store, self.root = store, root
        self.downloader, self.recognizer = downloader, recognizer
        self._lock, self._stop = threading.RLock(), threading.Event()
        self._thread = None
        self._state = self._idle()
        install(store)
        with store.tx() as c:
            c.execute("UPDATE yt_ocr_queue SET status='pending',updated_at=datetime('now') "
                      "WHERE status='running'")

    @staticmethod
    def _idle():
        return {"phase": "idle", "selected": 0, "done": 0, "failed": 0,
                "current": None, "errors": [], "started_at": None, "ended_at": None}

    def snapshot(self):
        install(self.store)
        with self.store._lock:
            rows = [dict(r) for r in self.store._conn.execute(
                "SELECT q.*,v.channel_title,v.title,v.published_at FROM yt_ocr_queue q "
                "JOIN yt_video v ON v.video_id=q.video_id "
                "ORDER BY q.priority DESC,v.published_at DESC LIMIT 100")]
            counts = {r[0]: r[1] for r in self.store._conn.execute(
                "SELECT status,count(*) FROM yt_ocr_queue GROUP BY status")}
        for row in rows:
            row["error_help"] = explain_error(row.get("last_error")) if row.get("last_error") else ""
        with self._lock:
            return {**self._state, "dependencies": dependency_state(),
                    "queue": {"counts": counts, "rows": rows}}

    def start(self, *, limit=1, interval=2.0, max_frames=120, min_confidence=.55):
        limit = max(1, min(int(limit), 3))
        interval = max(.5, min(float(interval), 10.0))
        max_frames = max(10, min(int(max_frames), 300))
        min_confidence = max(.3, min(float(min_confidence), .95))
        with self._lock:
            if self._thread and self._thread.is_alive():
                return {"ok": False, "error": "이미 화면 OCR이 진행 중입니다."}
            deps = dependency_state()
            if self.recognizer is apple_vision_ocr and not (deps["yt_dlp"] and deps["apple_vision"]):
                return {"ok": False, "error": "yt-dlp와 macOS Apple Vision이 필요합니다.",
                        "dependencies": deps}
            with self.store._lock:
                ids = [r[0] for r in self.store._conn.execute(
                    "SELECT video_id FROM yt_ocr_queue WHERE status='pending' "
                    "ORDER BY priority DESC,created_at LIMIT ?", (limit,))]
            if not ids:
                return {"ok": False, "error": "화면 OCR 대기 영상이 없습니다."}
            self._stop.clear()
            self._state = {**self._idle(), "phase": "running", "selected": len(ids),
                           "started_at": datetime.now(UTC).isoformat()[:19]}
            args = (ids, interval, max_frames, min_confidence)
            self._thread = threading.Thread(target=self._run, args=args, daemon=True,
                                            name="feedit-youtube-ocr")
            self._thread.start()
            return {"ok": True, "selected": len(ids), "interval": interval,
                    "max_frames": max_frames, "min_confidence": min_confidence}

    def stop(self):
        self._stop.set()
        return {"ok": True, "message": "현재 영상 처리가 끝나면 중지합니다."}

    def retry_failed(self, limit=3):
        with self.store.tx() as c:
            ids = [r[0] for r in c.execute(
                "SELECT video_id FROM yt_ocr_queue WHERE status='failed' "
                "ORDER BY updated_at DESC LIMIT ?", (max(1, min(int(limit), 10)),))]
            for video_id in ids:
                c.execute("UPDATE yt_ocr_queue SET status='pending',last_error=NULL,"
                          "updated_at=datetime('now') WHERE video_id=?", (video_id,))
        return {"ok": True, "reset": len(ids)}

    def _run(self, ids, interval, max_frames, min_confidence):
        from . import social
        for video_id in ids:
            if self._stop.is_set():
                break
            with self._lock:
                self._state["current"] = video_id
            with self.store.tx() as c:
                c.execute("UPDATE yt_ocr_queue SET status='running',attempts=attempts+1,"
                          "updated_at=datetime('now') WHERE video_id=?", (video_id,))
            try:
                with tempfile.TemporaryDirectory(prefix="feedit-ocr-") as tmp:
                    video = self.downloader(video_id, Path(tmp))
                    raw = self.recognizer(video, interval=interval, max_frames=max_frames,
                                          min_confidence=min_confidence)
                    segments = merge_frames(raw, interval=interval,
                                            min_confidence=min_confidence)
                    if not segments:
                        raise RuntimeError("신뢰할 만한 화면 글자를 찾지 못했습니다.")
                    saved = social.save_transcript(store=self.store, video_id=video_id,
                        raw=social._vtt_from_segments(segments), origin="ocr", lang="ko")
                mean = sum(x["confidence"] for x in segments) / len(segments)
                with self.store.tx() as c:
                    c.execute("INSERT INTO yt_ocr_evidence(video_id,engine,sample_interval,"
                              "sampled_frames,accepted_frames,mean_confidence,segments) "
                              "VALUES (?,?,?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET "
                              "engine=excluded.engine,sample_interval=excluded.sample_interval,"
                              "sampled_frames=excluded.sampled_frames,accepted_frames=excluded.accepted_frames,"
                              "mean_confidence=excluded.mean_confidence,segments=excluded.segments,"
                              "created_at=datetime('now')", (video_id, "apple_vision", interval,
                              int(raw.get("sampled_frames") or 0), len(segments), mean,
                              json.dumps(segments, ensure_ascii=False)))
                    c.execute("DELETE FROM yt_ocr_queue WHERE video_id=?", (video_id,))
                with self._lock:
                    self._state["done"] += 1
                    self._state.setdefault("results", []).append(
                        {"video_id": video_id, "characters": saved["characters"],
                         "segments": len(segments), "confidence": round(mean, 3)})
            except Exception as exc:
                message = f"{type(exc).__name__}: {str(exc)[:450]}"
                with self.store.tx() as c:
                    c.execute("UPDATE yt_ocr_queue SET status='failed',last_error=?,"
                              "updated_at=datetime('now') WHERE video_id=?", (message, video_id))
                with self._lock:
                    self._state["failed"] += 1
                    self._state["errors"].append({"video_id": video_id, "error": message})
        with self._lock:
            self._state["phase"] = "stopped" if self._stop.is_set() else "done"
            self._state["current"] = None
            self._state["ended_at"] = datetime.now(UTC).isoformat()[:19]
