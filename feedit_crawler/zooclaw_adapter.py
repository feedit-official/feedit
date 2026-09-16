"""ZooClaw FashionSigLIP2 임베딩 + 팀 linear probe 운영 어댑터."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from threading import Lock

_ROOT = Path(__file__).resolve().parent.parent
_MODEL_DIR = _ROOT / "models" / "style"
_LOCK = Lock()
_RUNTIME = None


def _load_pipeline_module():
    path = _MODEL_DIR / "style_prompts_and_pipeline.py"
    spec = importlib.util.spec_from_file_location("feedit_team_style_pipeline", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"스타일 파이프라인을 읽지 못했습니다: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _proba(runtime, emb):
    """분류기의 확률. sklearn 판이 달라도 되게 한다.

    ★ 왜 감싸는가
      모델은 팀이 다른 컴퓨터에서 학습해 joblib 로 저장한 것이다. 저장할 때의
      sklearn 과 여기서 도는 sklearn 이 다르면, 되살린 객체에 `multi_class`
      같은 내부 속성이 비어 `predict_proba` 가 AttributeError 로 죽는다.

          AttributeError: 'LogisticRegression' object has no attribute 'multi_class'

      2026-09-01 확인: 사용자 맥은 sklearn 1.9.0 인데 v3·v4 모델 **둘 다** 이
      오류가 났다. 즉 스타일 태깅이 조용히 한 건도 안 되고 있었다
      (한 장씩 except 로 삼켜서 '오류'로만 쌓였다).

      `predict` 와 `decision_function` 은 멀쩡하므로, 확률은 결정값에서 직접
      만든다. 다중분류 로지스틱의 predict_proba 는 결정값의 softmax 와 같다 —
      같은 자료 400장으로 재 보니 **최대 차이 0.0** 이었고 predict 와도 100%
      일치했다. 그래서 결과가 달라질 걱정 없이 갈아탈 수 있다.
    """
    clf, np = runtime["clf"], runtime["np"]
    try:
        return clf.predict_proba(emb)
    except AttributeError:
        d = clf.decision_function(emb)
        if d.ndim == 1:                      # 2분류면 열이 하나로 온다
            d = np.column_stack([-d, d])
        e = np.exp(d - d.max(axis=1, keepdims=True))
        return e / e.sum(axis=1, keepdims=True)


def _load_runtime():
    global _RUNTIME
    if _RUNTIME is not None:
        return _RUNTIME
    with _LOCK:
        if _RUNTIME is not None:
            return _RUNTIME
        try:
            import joblib
            import numpy as np
        except ImportError as exc:
            raise RuntimeError(f"스타일 분류 실행 패키지가 없습니다: {exc.name}") from exc

        pipeline = _load_pipeline_module()
        clf = joblib.load(_MODEL_DIR / "linear_probe_balanced.joblib")
        cache = np.load(_MODEL_DIR / "embeddings_cache.npz", allow_pickle=False)
        embeddings, urls = cache["embeddings"], cache["urls"]
        if embeddings.ndim != 2 or embeddings.shape[1] != int(clf.n_features_in_):
            raise RuntimeError("임베딩 캐시와 linear probe 입력 차원이 다릅니다.")
        cache_by_url = {str(url): embeddings[i] for i, url in enumerate(urls)}
        _RUNTIME = {"np": np, "pipeline": pipeline, "clf": clf,
                    "cache": cache_by_url, "tagger": None}
        return _RUNTIME


def _embedding(runtime, url: str):
    cached = runtime["cache"].get(url)
    if cached is not None:
        return cached
    if runtime["tagger"] is None:
        device = os.environ.get("FEEDIT_STYLE_DEVICE", "auto")
        runtime["tagger"] = runtime["pipeline"].FashionTagger(device=device)
    image = runtime["pipeline"].load_image_from_url(url)
    return runtime["tagger"].embed_image(image).cpu().numpy()


def tag_products(rows: list[dict], prompts: list[dict], on_step=None) -> list[dict]:
    """StyleTagger 계약: 각 상품에 Top-1 스타일과 확률을 돌려준다.

    on_step(i, total) 를 주면 한 장 끝낼 때마다 부른다. 한 장에 몇 초가
    걸려서 500장이면 몇 분이다. 그동안 화면에 아무 소식이 없으면
    '도는 건가 멈춘 건가'를 알 수 없다.
    """
    runtime = _load_runtime()
    supported = set(map(str, runtime["clf"].classes_))
    configured = {str(item["ko"]) for item in prompts}
    if not supported.issubset(configured):
        raise RuntimeError("분류기 클래스와 FEEDIT 스타일 매핑이 일치하지 않습니다: "
                           + ", ".join(sorted(supported - configured)))
    results = []
    for row in rows:
        url = str(row.get("image_url") or "").strip()
        if not url:
            continue
        try:
            emb = _embedding(runtime, url).reshape(1, -1)
            probability = _proba(runtime, emb)[0]
            idx = int(runtime["np"].argmax(probability))
            results.append({"source_code": row["source_code"],
                            "source_uid": row["source_uid"],
                            "style": str(runtime["clf"].classes_[idx]),
                            "confidence": float(probability[idx])})
        except Exception as exc:
            # 한 이미지 오류가 같은 회차의 나머지 상품 태깅까지 막지 않게 한다.
            results.append({"source_code": row.get("source_code"),
                            "source_uid": row.get("source_uid"),
                            "style": "", "confidence": 0.0, "error": str(exc)})
        if on_step:
            try:
                on_step(len(results), len(rows))
            except Exception:      # noqa: BLE001 - 알림 때문에 태깅이 멈추면 안 된다
                pass
    return results
