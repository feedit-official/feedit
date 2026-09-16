"""중간발표 집중 수집 범위의 단일 기준."""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

COMMERCE_SOURCES = {"musinsa", "musinsa_used", "zigzag", "ably", "kream"}
_CONFIG = Path(__file__).resolve().parent.parent / "config" / "demo_targets.json"
_SEP = re.compile(r"[\s\-_·/&,.()\[\]]+")


def _norm(value) -> str:
    return _SEP.sub("", unicodedata.normalize("NFC", str(value or "")).lower())


@lru_cache(maxsize=1)
def policy() -> dict:
    data = json.loads(_CONFIG.read_text(encoding="utf-8"))
    targets = []
    for row in data.get("targets", []):
        aliases = {row.get("canonical"), row.get("search_as"), row.get("english"),
                   row.get("model_code")}
        aliases.update(row.get("aliases") or [])
        targets.append({**row, "aliases": [_norm(x) for x in aliases if x]})
    for row in data.get("searchable_products", []):
        aliases = {row.get("canonical"), row.get("model_code")}
        aliases.update(row.get("aliases") or [])
        targets.append({**row, "aliases": [_norm(x) for x in aliases if x]})
    pins = {(str(p.get("source")), str(p.get("uid")))
            for p in data.get("pinned_products", [])}
    return {"version": data.get("version"), "targets": targets, "pins": pins}


def judge(source_code: str, source_uid: str, fields: dict) -> tuple[bool, str]:
    if source_code not in COMMERCE_SOURCES:
        return True, ""
    cfg = policy()
    if (source_code, str(source_uid)) in cfg["pins"]:
        return True, ""
    haystack = " ".join(str(fields.get(k) or "") for k in (
        "name", "brand_name", "category_path", "site_tags", "rank_scope"))
    normalized = _norm(haystack)
    for target in cfg["targets"]:
        if any(alias and alias in normalized for alias in target["aliases"]):
            return True, ""
    return False, f"집중 수집 대상 12개 밖입니다 ({cfg['version']})"


def terms() -> list[str]:
    return [t["canonical"] for t in policy()["targets"]]
