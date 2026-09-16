"""FEEDiT 패션 용어 엑셀을 검증 가능한 중간 사전으로 읽는다.

운영 lexicon.yaml을 바로 덮지 않는다. 먼저 충돌과 실제 텍스트 커버리지를 보고
승인할 수 있도록 data/lexicon_workbook.json에 별도 저장한다.
"""
from __future__ import annotations

import io
import json
import re
import unicodedata
import zipfile
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "pr": "http://schemas.openxmlformats.org/package/2006/relationships"}
SHEETS = {"스타일": "style", "소재": "material", "아이템": "item",
          "디테일": "detail", "브랜드": "brand"}


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFC", str(value or "")).lower()
    return re.sub(r"[\s\-_·/&,.()\[\]]+", "", value)


def _split(value) -> list[str]:
    return [x.strip() for x in re.split(r"[,·]", str(value or "")) if x.strip()]


def _xlsx_rows(raw: bytes) -> dict[str, list[list]]:
    """외부 패키지 없이 xlsx의 값만 읽는다(수식·서식은 변경하지 않음)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as e:
        raise ValueError("올바른 .xlsx 파일이 아닙니다.") from e
    if sum(x.file_size for x in z.infolist()) > 100 * 1024 * 1024:
        raise ValueError("압축을 푼 엑셀 내용이 너무 큽니다 (최대 100MB).")
    try:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in si.findall(".//m:t", NS))
                      for si in root.findall("m:si", NS)]
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rel = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {x.attrib["Id"]: x.attrib["Target"] for x in rel.findall("pr:Relationship", NS)}
        out = {}
        for sh in wb.findall("m:sheets/m:sheet", NS):
            name = sh.attrib["name"]
            target = targets[sh.attrib[f"{{{NS['r']}}}id"]].lstrip("/")
            path = target if target.startswith("xl/") else "xl/" + target
            root = ET.fromstring(z.read(path))
            rows = []
            for row in root.findall(".//m:sheetData/m:row", NS):
                vals = {}
                for c in row.findall("m:c", NS):
                    col = re.match(r"[A-Z]+", c.attrib.get("r", "A")).group()
                    idx = 0
                    for ch in col:
                        idx = idx * 26 + ord(ch) - 64
                    typ = c.attrib.get("t")
                    if typ == "inlineStr":
                        value = "".join(t.text or "" for t in c.findall(".//m:t", NS))
                    else:
                        node = c.find("m:v", NS)
                        value = node.text if node is not None else ""
                        if typ == "s" and value != "":
                            value = shared[int(value)]
                    vals[idx - 1] = value
                if vals:
                    width = max(vals) + 1
                    rows.append([vals.get(i) for i in range(width)])
            out[name] = rows
        return out
    except (KeyError, ET.ParseError, IndexError, ValueError) as e:
        raise ValueError(f"엑셀 구조를 읽지 못했습니다: {e}") from e


def parse(raw: bytes) -> dict:
    sheets = _xlsx_rows(raw)
    missing = [name for name in SHEETS if name not in sheets]
    if missing:
        raise ValueError("필수 시트가 없습니다: " + ", ".join(missing))
    terms, warnings = [], []
    for sheet, facet in SHEETS.items():
        rows = sheets[sheet]
        if not rows or len(rows[0]) < 4 or rows[0][1] != "대표 용어":
            raise ValueError(f"{sheet} 시트의 헤더가 예상과 다릅니다.")
        for number, row in enumerate(rows[1:], 2):
            row += [None] * (8 - len(row))
            canonical = str(row[1] or "").strip()
            if not canonical:
                continue
            english = str(row[2] or "").strip()
            if facet == "style" and canonical == "긱시크" and english.lower() != "geek-chic":
                warnings.append({"kind": "spelling", "where": f"{sheet}!C{number}",
                                 "message": f"{english}을 기준 사전에서 Geek-chic으로 보정했습니다."})
                english = "Geek-chic"
            aliases = _split(row[3])
            surfaces = list(dict.fromkeys(x for x in [canonical, english, *aliases] if x))
            terms.append({"term_key": f"{facet}:{_norm(canonical)}", "facet": facet,
                          "canonical": canonical, "english": english,
                          "aliases": aliases, "surfaces": surfaces,
                          "category": str(row[4] or "").strip(),
                          "note": str(row[-1] or "").strip(),
                          "sheet": sheet, "row": number})
    by_surface = defaultdict(list)
    for term in terms:
        for surface in term["surfaces"]:
            key = _norm(surface)
            if key:
                by_surface[key].append({"surface": surface, "term_key": term["term_key"],
                                        "canonical": term["canonical"], "facet": term["facet"]})
    collisions = []
    ambiguous = set()
    for key, hits in by_surface.items():
        unique = {(x["term_key"], x["facet"]) for x in hits}
        if len(unique) > 1:
            collisions.append({"normalized": key, "matches": hits})
            ambiguous.add(key)
    return {"version": 1, "terms": terms, "collisions": collisions,
            "ambiguous_surfaces": sorted(ambiguous), "warnings": warnings,
            "counts": {facet: sum(1 for t in terms if t["facet"] == facet)
                       for facet in SHEETS.values()}}


def coverage(parsed: dict, texts: list[dict], limit=1000) -> dict:
    """표본에서 고신뢰 직접 매칭/충돌 후보/미확정을 나눈다."""
    surface_map = defaultdict(list)
    for term in parsed["terms"]:
        for raw in term["surfaces"]:
            key = _norm(raw)
            # 한 글자와 영문 2자 이하는 자유 글 부분매칭에 쓰지 않는다.
            if len(key) < 2 or (key.isascii() and len(key) < 3):
                continue
            surface_map[key].append({"term": term, "surface": str(raw).strip()})
    ordered = sorted(surface_map, key=len, reverse=True)
    brand_keys = set()
    max_brand_words = 1
    for sf, options in surface_map.items():
        if not all(x["term"]["facet"] == "brand" for x in options):
            continue
        raw_surface = re.sub(r"[^0-9a-z가-힣]+", " ", options[0]["surface"].lower()).strip()
        if len(_norm(raw_surface)) >= 3:
            brand_keys.add(sf)
            max_brand_words = max(max_brand_words, len(raw_surface.split()))
    totals = {"confirmed": 0, "candidate": 0, "unresolved": 0}
    facets = defaultdict(int)
    samples = {k: [] for k in totals}
    for row in texts[:limit]:
        body = unicodedata.normalize("NFC", str(row.get("body") or "")).lower()
        hay = _norm(body)
        token_hay = re.sub(r"[^0-9a-z가-힣]+", " ", body).strip()
        words = token_hay.split()
        brand_hits = set()
        for i in range(len(words)):
            for size in range(1, min(max_brand_words, len(words) - i) + 1):
                phrase = " ".join(words[i:i + size])
                variants = [phrase]
                if size == 1:
                    stripped = re.sub(r"(에서|으로|은|는|이|가|을|를|의|와|과)$", "", phrase)
                    if stripped != phrase:
                        variants.append(stripped)
                brand_hits.update(_norm(v) for v in variants if _norm(v) in brand_keys)
        matches, candidate = {}, False
        for sf in ordered:
            options = surface_map[sf]
            # 브랜드는 부분 문자열로 잡지 않는다. 2,738개 중 짧은 이름이 일반
            # 문장 안에 우연히 포함되는 오탐이 매우 많기 때문이다.
            brand_only = all(x["term"]["facet"] == "brand" for x in options)
            if brand_only:
                if sf not in brand_hits:
                    continue
            elif sf not in hay:
                continue
            if len({x["term"]["term_key"] for x in options}) > 1:
                candidate = True
                continue
            term = options[0]["term"]
            matches[term["term_key"]] = term
        state = "confirmed" if matches else "candidate" if candidate else "unresolved"
        totals[state] += 1
        for term in matches.values():
            facets[term["facet"]] += 1
        if len(samples[state]) < 8:
            samples[state].append({"id": row.get("id"), "source": row.get("source_code"),
                                   "body": (row.get("body") or "")[:180],
                                   "terms": [x["canonical"] for x in matches.values()]})
    n = sum(totals.values())
    return {"sampled": n, **totals,
            "confirmed_rate": round(totals["confirmed"] / n, 4) if n else 0,
            "facets": dict(facets), "samples": samples}


def save(parsed: dict, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
