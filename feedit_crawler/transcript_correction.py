"""비용 없는 패션 자막 보정 후보 생성기.

원문은 바꾸지 않는다. 사전 표기와 한 글자만 다른 ASR 조각을 찾아 검색용 엔티티
연결로 남기고, 짧거나 충돌하는 것은 LLM 검토 대상으로만 표시한다.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from .entity_linker import norm

MODEL = "dictionary-asr-correction"
VERSION = "lexicon-master-v4-edit1"
_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")
_CONTEXT = ("패션", "코디", "스타일", "착용", "옷", "룩", "소재", "브랜드", "시즌")
_ENDINGS = {"은", "는", "이", "가", "을", "를", "에", "의", "도", "만", "랑", "과", "와",
            "로", "으로", "고", "한", "하고", "해서", "에서", "에는", "으로는"}


class TranscriptCorrector:
    def __init__(self, path: str | Path):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        self.exact = defaultdict(list)
        self.deleted = defaultdict(list)
        for term in raw.get("terms") or []:
            if term.get("facet") not in {"style", "material", "item", "brand", "detail"}:
                continue
            for surface in term.get("surfaces") or [term.get("canonical")]:
                key = norm(surface)
                if not 3 <= len(key) <= 18:
                    continue
                item = {"term_key": term["term_key"], "canonical": term["canonical"],
                        "facet": term["facet"], "surface": str(surface)}
                self.exact[key].append(item)
                for i in range(len(key)):
                    self.deleted[key[:i] + key[i + 1:]].append(item)

    @staticmethod
    def _distance_one_candidates(value, exact, deleted):
        out = []
        # 사전 표기가 한 글자 더 긴 경우
        out.extend(deleted.get(value, []))
        for i in range(len(value)):
            shorter = value[:i] + value[i + 1:]
            # 자막에 한 글자가 더 들어간 경우 / 같은 길이 한 글자 치환
            out.extend(exact.get(shorter, []))
            out.extend(deleted.get(shorter, []))
        return out

    def scan(self, full_text: str, segments: list[dict]) -> list[dict]:
        rows, seen = [], set()
        source_segments = segments or [{"start": 0, "dur": 0, "text": full_text}]
        for segment in source_segments:
            text = str(segment.get("text") or "")
            tokens = _TOKEN.findall(text)
            contextual = any(word in text for word in _CONTEXT)
            for size in (1, 2, 3):
                for i in range(0, len(tokens) - size + 1):
                    original = " ".join(tokens[i:i + size])
                    key = norm(original)
                    if not 3 <= len(key) <= 18 or key in self.exact:
                        continue
                    options = self._distance_one_candidates(key, self.exact, self.deleted)
                    unique = {(x["term_key"], x["surface"]): x for x in options}
                    # 여러 표준어로 갈 수 있는 일반어는 Luna에도 보내지 않는다. 후보를
                    # 많이 보내는 것 자체가 비용이며, 희귀 브랜드 오탐의 주원인이다.
                    term_count = len({x["term_key"] for x in unique.values()})
                    if term_count != 1:
                        continue
                    for item in unique.values():
                        target = norm(item["surface"])
                        tail = key[len(target):] if key.startswith(target) else ""
                        morphology = bool(tail and tail in _ENDINGS)
                        same_edges = key[0] == target[0] and key[-1] == target[-1]
                        one_edge = key[0] == target[0] or key[-1] == target[-1]
                        # 브랜드는 일상어와 우연히 비슷한 이름이 많다. 두문자+끝문자가
                        # 모두 같을 때만 검토 후보로 남기고 자동 확정하지 않는다.
                        if item["facet"] == "brand":
                            if len(key) < 4 or key[:2] != target[:2] or key[-1] != target[-1]:
                                continue
                            auto = False
                        else:
                            if len(key) < 4 or not (morphology or one_edge):
                                continue
                            auto = morphology or (same_edges and size == 1)
                        marker = (segment.get("start", 0), key, item["term_key"])
                        if marker in seen:
                            continue
                        seen.add(marker)
                        confidence = .90 if auto and contextual else .86 if auto else .68
                        rows.append({**item, "original": original,
                                     "start": float(segment.get("start") or 0),
                                     "dur": float(segment.get("dur") or 0),
                                     "confidence": confidence,
                                     "status": "confirmed" if auto else "review",
                                     "method": "dictionary_edit_distance_1"})
        return sorted(rows, key=lambda x: (-x["confidence"], x["start"]))[:100]
