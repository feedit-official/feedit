"""기준 사전 후보와 Luna 결과를 검색축 엔티티 연결로 합친다."""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from .lexicon import Lexicon

RULE_MODEL = "dictionary"
RULE_VERSION = "lexicon-master-v4"


def norm(value):
    value = unicodedata.normalize("NFC", str(value or "")).lower()
    return re.sub(r"[\s\-_·/&,.()\[\]]+", "", value)


class EntityLinker:
    FACETS = {"style", "material", "item", "brand", "detail"}

    def __init__(self, path: str | Path):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        self.terms = raw.get("terms") or []
        self.by_key = {t["term_key"]: t for t in self.terms}
        self.by_name = {(t["facet"], norm(t["canonical"])): t for t in self.terms}
        self.surfaces = defaultdict(list)
        for term in self.terms:
            for surface in term.get("surfaces") or []:
                key = norm(surface)
                if len(key) >= 2 and not (key.isascii() and len(key) < 3):
                    self.surfaces[key].append((term, surface))
        self.ordered = sorted(self.surfaces, key=len, reverse=True)
        self.risky = {norm(x) for x in Lexicon.RISKY}

    def candidates(self, row: dict) -> list[dict]:
        out = {}

        def add(term, surface, status, confidence, evidence, method, role):
            key = (term["term_key"], method)
            got = {"term_key": term["term_key"], "canonical": term["canonical"],
                   "facet": term["facet"], "surface": surface, "status": status,
                   "confidence": confidence, "evidence": evidence[:240],
                   "method": method, "role": role}
            if key not in out or confidence > out[key]["confidence"]:
                out[key] = got

        body = str(row.get("body") or "")
        hay = norm(body)
        for sf in self.ordered:
            if sf not in hay:
                continue
            options = self.surfaces[sf]
            # 자유 글의 브랜드는 부분문자열로 확정하지 않는다. Luna 후보로만 둔다.
            ambiguous = len({t[0]["term_key"] for t in options}) > 1
            accepted = False
            for term, surface in options:
                if term["facet"] == "brand":
                    # '사이즈' 안의 '사이' 같은 부분문자열은 브랜드 후보도 아니다.
                    # 원문에서 독립 토큰으로 등장한 브랜드만 Luna 후보로 보낸다.
                    if len(sf) < 3:
                        continue
                    token = re.escape(str(surface).strip())
                    if not re.search(rf"(?<![0-9A-Za-z가-힣]){token}(?![0-9A-Za-z가-힣])",
                                     body, re.IGNORECASE):
                        continue
                    add(term, surface, "candidate", .65, surface,
                        "dictionary", "context")
                    accepted = True
                elif ambiguous or sf in self.risky:
                    add(term, surface, "candidate", .45, surface, "dictionary", "context")
                    accepted = True
                else:
                    add(term, surface, "confirmed", .92, surface, "dictionary", "target")
                    accepted = True
            # 가장 긴 표기를 잡은 자리를 지워 '긱시크'가 '시크'로도 잡히는
            # 인위적 동시출현을 막는다. 같은 표기의 다중 축 후보는 위에서 모두 남긴다.
            if accepted:
                hay = hay.replace(sf, "\x00" * len(sf))

        # 상품 리뷰는 연결된 상품의 이름·브랜드·카테고리가 가장 강한 근거다.
        brand_name = str(row.get("brand_name") or "")
        metadata = " ".join(str(row.get(k) or "") for k in
                            ("product_name", "category_path", "site_tags"))
        if metadata.strip():
            mhay = norm(metadata)
            for sf in self.ordered:
                if sf not in mhay:
                    continue
                options = self.surfaces[sf]
                ambiguous = len({t[0]["term_key"] for t in options}) > 1
                for term, surface in options:
                    if term["facet"] == "brand":
                        continue
                    add(term, surface, "candidate" if ambiguous else "confirmed",
                        .55 if ambiguous else .98, metadata,
                        "product_metadata", "target" if not ambiguous else "context")
        # 브랜드는 별도 필드 전체가 사전 표기와 같을 때만 확정한다.
        brand_key = norm(brand_name)
        for term, surface in self.surfaces.get(brand_key, []):
            if term["facet"] == "brand":
                add(term, surface, "confirmed", .99, brand_name,
                    "product_metadata", "target")
        return sorted(out.values(), key=lambda x: (-x["confidence"], x["facet"]))[:30]

    def rules_only(self, row: dict) -> tuple[dict, list[dict]]:
        """API 호출 없이 확정 가능한 것과 검토 후보를 그대로 저장한다."""
        mentions = self.candidates(row)
        if any(m["status"] == "confirmed" for m in mentions):
            status = "confirmed"
        elif mentions:
            status = "candidate"
        else:
            # 사전에 없다고 패션 정보가 없다고 단정할 수 없으므로 unresolved다.
            status = "unresolved"
        return {
            "model": RULE_MODEL,
            "prompt_version": RULE_VERSION,
            "resolution_status": status,
            "no_signal_reason": "",
            "unresolved_terms": [],
        }, mentions

    def resolve(self, result: dict, candidates: list[dict]) -> tuple[dict, list[dict]]:
        mentions = {(m["term_key"], m["method"]): dict(m) for m in candidates
                    if m["status"] == "confirmed"}
        candidate_by_name = {(m["facet"], norm(m["canonical"])): m for m in candidates}
        for ent in result.get("entities") or []:
            facet, canonical = ent.get("facet"), str(ent.get("canonical") or "").strip()
            if facet not in self.FACETS or not canonical:
                continue
            base = candidate_by_name.get((facet, norm(canonical))) or self.by_name.get((facet, norm(canonical)))
            if not base:
                continue
            term = self.by_key.get(base["term_key"]) if "term_key" in base else base
            confidence = max(0, min(float(ent.get("confidence") or 0), 1))
            mention = {"term_key": term["term_key"], "canonical": term["canonical"],
                       "facet": facet, "surface": ent.get("surface") or canonical,
                       "role": ent.get("role") or "context",
                       "status": "confirmed" if confidence >= .8 else "candidate",
                       "confidence": confidence, "evidence": ent.get("evidence") or "",
                       "method": "llm"}
            mentions[(mention["term_key"], "llm")] = mention
        vals = list(mentions.values())
        if any(m["status"] == "confirmed" for m in vals):
            status = "confirmed"
        elif vals:
            status = "candidate"
        elif result.get("unresolved_terms"):
            status = "unresolved"
        else:
            status = "no_signal"
        result["resolution_status"] = status
        result["no_signal_reason"] = str(result.get("no_signal_reason") or "")
        return result, vals
