"""팀 ZooClaw/FashionSigLIP 분류기를 크롤러에 꽂는 얇은 계약."""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
from pathlib import Path

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "style"
_DEFAULT_ADAPTER = "feedit_crawler.zooclaw_adapter:tag_products"


class StyleTagger:
    """``FEEDIT_STYLE_MODEL_ADAPTER=package.module:function`` 형식의 어댑터.

    함수는 상품 dict 목록과 스타일 프롬프트 목록을 받고
    ``[{source_code, source_uid, style, confidence}]``를 반환한다.
    """
    def __init__(self, store):
        self.store = store
        # 지금 몇 장째인지. 화면이 1초마다 읽어 간다.
        self.progress: dict = {"running": False, "done": 0, "total": 0,
                               "started_at": None}
        configured = os.environ.get("FEEDIT_STYLE_MODEL_ADAPTER", "").strip()
        self.adapter_name = configured or (_DEFAULT_ADAPTER if self._artifacts_exist() else "")

    @staticmethod
    def _artifacts_exist() -> bool:
        return all((_MODEL_DIR / name).exists() for name in (
            "linear_probe_balanced.joblib", "embeddings_cache.npz",
            "style_prompts_and_pipeline.py",
        ))

    def state(self) -> dict:
        required = ("joblib", "sklearn", "PIL", "torch", "transformers")
        missing = [name for name in required if importlib.util.find_spec(name) is None]
        trained = [p["ko"] for p in self.prompts()[:14]]
        # 학습 파일의 실제 클래스 순서는 런타임에서 다시 검증한다. 여기서는 운영 UI가
        # 19종 중 14종 모델이라는 사실을 서버 시작 전에도 표시할 수 있게 한다.
        unsupported = [p["ko"] for p in self.prompts() if p["ko"] not in trained]
        ready = bool(self.adapter_name) and not missing
        if not self.adapter_name:
            message = "팀 모델 파일 경로/어댑터를 기다리는 중"
        elif missing:
            message = "모델 파일 연결됨 · 실행 패키지 미설치: " + ", ".join(missing)
        else:
            message = "ZooClaw + linear probe 연결됨"
        return {"ready": ready, "adapter": self.adapter_name or None,
                "artifacts": self._artifacts_exist(), "missing_dependencies": missing,
                "trained_style_count": 14, "frontend_style_count": len(self.prompts()),
                "unsupported_styles": unsupported, "message": message}

    def _adapter(self):
        module, sep, func = self.adapter_name.partition(":")
        if not sep:
            raise ValueError("FEEDIT_STYLE_MODEL_ADAPTER는 package.module:function 형식이어야 합니다.")
        return getattr(importlib.import_module(module), func)

    def prompts(self) -> list[dict]:
        path = _CONFIG_DIR / "style_prompts.json"
        return json.loads(path.read_text(encoding="utf-8"))["styles"]

    def run(self, limit: int = 200) -> dict:
        if not self.adapter_name:
            return {"ok": True, "skipped": True, **self.state(), "tagged": 0}
        with self.store._lock:
            candidates = [dict(r) for r in self.store._conn.execute(
                "SELECT source_code,source_uid,name,brand_name,image_url,site_tags "
                "FROM staging_product WHERE image_url IS NOT NULL AND trim(image_url)<>'' "
                "ORDER BY last_seen_at DESC LIMIT ?", (max(1, min(int(limit) * 4, 8000)),))]
        rows = []
        for row in candidates:
            try:
                tags = json.loads(row.get("site_tags") or "[]")
            except (TypeError, ValueError):
                tags = []
            if not any(isinstance(tag, dict) and tag.get("facet") == "style" for tag in tags):
                rows.append(row)
            if len(rows) >= limit:
                break
        # ★ _adapter() 는 '어댑터 함수를 찾아 돌려주는' 메서드다.
        #   그래서 두 번 부른다 — 먼저 함수를 얻고, 그 함수에 자료를 넘긴다.
        #   전에는 self._adapter(rows, prompts) 라고 써서
        #     StyleTagger._adapter() takes 1 positional argument but 3 were given
        #   로 죽었다. 스타일 태깅이 매번 여기서 멈췄다.
        import time as _time
        self.progress = {"running": True, "done": 0, "total": len(rows),
                         "started_at": _time.time()}

        def _step(i, n):
            self.progress["done"] = i
            self.progress["total"] = n

        fn = self._adapter()
        try:
            try:
                results = fn(rows, self.prompts(), on_step=_step)
            except TypeError:
                # 진행 알림을 안 받는 어댑터도 그대로 돌아가야 한다
                results = fn(rows, self.prompts())
        finally:
            self.progress["running"] = False
        tagged = 0
        with self.store.tx() as c:
            for row in results or []:
                style = str(row.get("style") or "").strip()
                confidence = float(row.get("confidence") or 0)
                if not style or confidence < 0.45:
                    continue
                existing = next((r.get("site_tags") for r in rows
                                 if str(r.get("source_code")) == str(row.get("source_code"))
                                 and str(r.get("source_uid")) == str(row.get("source_uid"))), "")
                try:
                    tags = json.loads(existing or "[]")
                except (TypeError, ValueError):
                    tags = []
                tags.append({"facet": "style", "canonical": style,
                             "confidence": confidence, "method": "zooclaw-linear-probe"})
                payload = json.dumps(tags, ensure_ascii=False)
                cur = c.execute("UPDATE staging_product SET site_tags=? WHERE source_code=? AND source_uid=?",
                    (payload, str(row.get("source_code")), str(row.get("source_uid"))))
                tagged += cur.rowcount
        return {"ok": True, "tagged": tagged, "attempted": len(rows), **self.state()}
