"""
새 플랫폼 마법사 — 주소만 넣으면 나머지를 짐작한다.

지금까지 새 사이트를 붙이려면 YAML 을 손으로 짜야 했다. 셀렉터가 뭔지
아는 사람만 할 수 있는 일이었다. 여기서는 이렇게 간다.

    주소 넣기 → 열어 보기 → 후보 찾기 → **미리보기로 확인** → 저장

★ 미리보기가 핵심이다
  자동 추측은 반드시 틀린다. 중요한 건 '틀렸는지 바로 보이는 것'이다.
  셀렉터를 보여 주는 대신 **실제로 뽑힌 값**을 보여 준다 —
  '나이키 에어포스 · 129,000원' 이 나오면 맞은 것이고,
  '(빈 값)' 이 나오면 그 칸만 다시 고르면 된다.

★ 브라우저로 여는 게 기본이다
  요즘 사이트는 대부분 자바스크립트로 그린다. 그냥 받아 오면 빈 껍데기다.
  robots 를 먼저 확인하고, 막혀 있으면 '저장본을 넣어 주세요' 로 안내한다.

★ 못 하는 것도 분명히 말한다
  상세 페이지 셀렉터까지는 못 짐작한다. 목록만 잡아 준다.
  목록만으로도 이름·가격·사진·순위가 들어오므로 첫걸음으로는 충분하다.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .probe import probe

UTC = timezone.utc


def _slug(host: str) -> str:
    """'www.musinsa.com' → 'musinsa'"""
    parts = [p for p in host.lower().split(".") if p not in ("www", "m", "mobile")]
    core = parts[0] if parts else "site"
    return re.sub(r"[^a-z0-9_]", "", core)[:20] or "site"


# ── 값의 성격을 알아본다 ──────────────────────────────────────
#
#  ★ 자리(nth)로만 짐작하면 안 된다.
#    무신사 카드에는 '품절' 배지가 붙는 것과 안 붙는 것이 섞여 있어서
#    같은 [1]번 자리에 브랜드가 오기도 하고 '품절'이 오기도 한다.
#    실제로 그렇게 밀려서 상품명 자리에 브랜드가 들어왔다.
#
#  그래서 **생김새로 알아볼 수 있는 값은 생김새로 잡는다.**
#      가격   19,000원 · 129,000        → 쉼표가 있거나 '원'이 붙는다
#      할인율  20%                       → 두 자리 + %
#      순위    894                       → 쉼표 없는 작은 정수
#  이건 자리가 밀려도 안 틀린다. 실제 설정들이 다 이 방식이다.
#
#  브랜드·상품명만 자리로 잡는다. 생김새로는 구분이 안 되기 때문이다.
#  대신 '숫자가 아닌 것 중 앞의 둘' 로 좁혀서 배지에 덜 밀리게 한다.

_PRICE = re.compile(r"^(₩|\$)?\s*\d{1,3}(,\d{3})+\s*원?$|^\d{4,}\s*원$")
_PCT = re.compile(r"^\d{1,2}%$")
_RANK = re.compile(r"^\d{1,4}$")
_NOISE = re.compile(r"명이 보는|도착|배송|무료|쿠폰|적립|품절|재입고|옵션|리뷰|후기|별점")


def _looks(v: str) -> str:
    """글자 하나가 무엇처럼 생겼나."""
    v = (v or "").strip()
    if not v:
        return ""
    if _PRICE.match(v):
        return "price"
    if _PCT.match(v):
        return "discount"
    if _RANK.match(v):
        return "rank"
    if _NOISE.search(v):
        return "noise"
    return "text"


def _guess_kind(texts: list[str]) -> str:
    """같은 자리에 오는 글자들을 모아서 무슨 칸인지 본다."""
    vals = [t.strip() for t in texts if t and t.strip()]
    if not vals:
        return ""
    n = len(vals)
    kinds = [_looks(v) for v in vals]
    for k in ("price", "discount", "rank"):
        if kinds.count(k) > n * 0.6:
            return k
    if kinds.count("noise") > n * 0.5:
        return "noise"
    if kinds.count("text") > n * 0.5:
        avg = sum(len(v) for v, k in zip(vals, kinds) if k == "text") / max(
            1, kinds.count("text"))
        return "name" if avg > 14 else "brand"
    return ""


KIND_KO = {"price": "가격", "discount": "할인율", "rank": "순위",
           "name": "상품명", "brand": "브랜드", "noise": "그 밖의 것", "": "?"}


def _read_card(soup, sel: str) -> tuple[list, list]:
    """카드 하나를 뜯어 '글자를 직접 담은 요소'를 자리 순서대로 모은다."""
    try:
        els = soup.select(sel)[:12]
    except Exception:
        return [], []
    rows = []
    for el in els:
        leaves = [e.get_text(" ", strip=True)
                  for e in el.select("div,span,p,b,strong")
                  if not e.find(["div", "span", "p", "a", "li"])
                  and e.get_text(strip=True)]
        rows.append(leaves)
    return els, rows


def _plan(rows: list) -> tuple[list, dict]:
    """자리별로 무엇인지 짐작하고, 어떻게 잡을지 정한다."""
    width = max((len(r) for r in rows), default=0)
    slots = []
    for i in range(min(width, 12)):
        col = [r[i] for r in rows if len(r) > i]
        kind = _guess_kind(col)
        slots.append({"nth": i, "kind": kind, "kind_ko": KIND_KO.get(kind, "?"),
                      "samples": col[:4]})

    fields: dict = {}
    #  가격·할인율은 생김새로 (자리가 밀려도 안 틀린다)
    for k in ("price", "discount"):
        if any(s["kind"] == k for s in slots):
            fields[k] = {"how": "match"}
    #  순위는 조심한다 — 사이즈(S·M·2·5) 나 개수도 작은 정수라 잘 헷갈린다.
    #  **맨 앞 자리에 있을 때만** 순위로 본다. 랭킹은 늘 카드 맨 위에 붙는다.
    if slots and slots[0]["kind"] == "rank":
        fields["rank"] = {"how": "match"}

    text_slots = [s for s in slots if s["kind"] in ("brand", "name")]
    if text_slots:
        def avglen(s):
            v = [x for x in s["samples"] if x]
            return sum(len(x) for x in v) / max(1, len(v))
        ordered = sorted(text_slots[:4], key=avglen)
        if len(ordered) >= 2:
            fields["brand"] = {"how": "nth", "nth": ordered[0]["nth"]}
            fields["name"] = {"how": "nth", "nth": ordered[-1]["nth"]}
        else:
            fields["name"] = {"how": "nth", "nth": ordered[0]["nth"]}
    return slots, fields


def analyze(html: str, url: str = "") -> dict:
    """페이지 하나를 보고 '무엇이 어디 있는지' 초안을 만든다.

    ★ 첫 후보만 보고 포기하지 않는다.
      반복되는 덩어리는 여럿이다 — 상품 카드도 있고, 배너 목록도 있고,
      카드를 감싼 바깥 상자도 있다. 어느 것이 상품 카드인지는
      **뜯어 봐야** 안다. 그래서 후보마다 뜯어 보고,
      쓸 만한 칸이 가장 많이 나오는 것을 고른다.
    """
    p = probe(html, url)
    soup = BeautifulSoup(html, "html.parser")

    cards = p.get("cards") or []
    if not cards:
        return {"ok": False, "hint": p.get("hint"),
                "error": "반복되는 상품 카드를 못 찾았습니다.",
                "probe": p}

    tried = []
    for c in cards[:6]:
        els, rows = _read_card(soup, c["selector"])
        if not els:
            continue
        slots, fields = _plan(rows)
        # 점수: 잡은 칸 수가 먼저, 같으면 카드가 많은 쪽
        score = (len(fields), min(len(els) * 0 + c.get("count", 0), 500))
        tried.append({"selector": c["selector"], "count": c.get("count", 0),
                      "els": els, "slots": slots, "fields": fields,
                      "score": score})
    if not tried:
        return {"ok": False, "hint": p.get("hint"),
                "error": "카드를 찾았지만 안을 못 읽었습니다.", "probe": p}

    tried.sort(key=lambda t: t["score"], reverse=True)
    best = tried[0]
    els = best["els"]

    link_sel, detail_tmpl = "", ""
    for el in els[:4]:
        a = el.find("a", href=True)
        if a:
            href = a["href"]
            m = re.match(r"^(?:https?://[^/]+)?(/[a-z0-9\-_]+/)", href)
            if m:
                link_sel = f'a[href*="{m.group(1)}"]'
                detail_tmpl = m.group(1) + "{id}"
            else:
                link_sel = "a[href]"
            break
    has_img = any(el.find("img") for el in els[:5])

    return {
        "ok": True,
        "card": best["selector"],
        "card_count": best["count"],
        "item_link": link_sel,
        "detail_url_template": detail_tmpl,
        "has_image": has_img,
        "slots": best["slots"],
        "fields": best["fields"],
        "other_cards": [{"selector": t["selector"], "count": t["count"],
                         "guessed": len(t["fields"])}
                        for t in tried[1:5]],
        "embedded": p.get("embedded_json") or [],
        "hint": p.get("hint"),
    }


def preview(html: str, draft: dict) -> dict:
    """초안대로 뽑으면 무엇이 나오는지 실제로 보여 준다.

    셀렉터를 보여 주는 대신 값을 보여 주는 게 이 함수의 전부다.
    """
    from .adapter import ConfigAdapter, SiteConfig

    try:
        cfg = SiteConfig.from_dict(build_config(draft))
        recs = ConfigAdapter(cfg).parse_list_records(html)
    except Exception as e:
        return {"ok": False, "error": f"뽑아 보다 실패했습니다: {e}"}

    if not recs:
        return {"ok": False,
                "error": "이 설정으로는 아무것도 안 나옵니다. "
                         "카드 셀렉터를 다른 후보로 바꿔 보세요."}

    watch = ["brand", "name", "price", "discount", "rank", "image_url"]
    n = len(recs)
    fill = {k: sum(1 for r in recs if r.get(k)) for k in watch}

    # ── 이게 쓸 만한 결과인지 스스로 판단한다 ──
    #  자동 추측은 반드시 틀린다. 그러면 **틀렸다고 말해 주는 것**이
    #  이 함수가 할 수 있는 가장 쓸모 있는 일이다.
    #  "8건 뽑았습니다" 만 보여 주면 사람은 맞은 줄 안다.
    problems = []
    if not fill["name"]:
        problems.append("상품명이 하나도 안 잡혔습니다")
    elif fill["name"] < n * 0.7:
        problems.append(f"상품명이 {fill['name']}/{n} 만 잡혔습니다")
    if not fill["price"]:
        problems.append("가격이 하나도 안 잡혔습니다")
    if not recs[0].get("source_uid"):
        problems.append("상품 주소를 못 잡았습니다 (같은 상품인지 구분이 안 됩니다)")

    # 브랜드 자리에 사이즈·배지가 들어오는 흔한 사고를 잡아낸다
    brands = [str(r.get("brand") or "") for r in recs if r.get("brand")]
    if brands:
        short = sum(1 for b in brands if len(b) <= 2)
        if short > len(brands) * 0.5:
            problems.append("브랜드 자리에 사이즈나 배지가 들어온 것 같습니다")

    core = ["name", "price"]
    score = sum(fill[k] for k in core) / max(1, n * len(core))
    verdict = ("good" if not problems and score > 0.8 else
               "partial" if fill["name"] else "bad")

    return {"ok": True, "count": n, "verdict": verdict, "problems": problems,
            "rows": [{k: r.get(k) for k in watch + ["source_uid"]}
                     for r in recs[:8]],
            "fill": fill, "total": n}


def build_config(draft: dict) -> dict:
    """초안 → 설정 딕셔너리."""
    code = draft.get("code") or "site"
    base = draft.get("base_url") or ""
    fields = draft.get("fields") or {}

    # 생김새로 잡는 칸들의 정규식. 실제 설정들에서 검증된 것과 같은 모양이다.
    MATCH = {
        "price": {"match": r"^(₩|\$)?\s*[\d,]{4,}\s*원?$", "regex": r"([\d,]+)",
                  "cast": "int"},
        "discount": {"match": r"^\d{1,2}%$", "regex": r"(\d+)", "cast": "int"},
        "rank": {"match": r"^\d{1,4}$", "cast": "int"},
    }

    card_fields: dict = {}
    for key, spec in fields.items():
        if not spec or spec.get("off"):
            continue
        base_rule = {"css_all": "div, span, p, b, strong", "leaf": True}
        if spec.get("how") == "match" and key in MATCH:
            card_fields[key] = {**base_rule, **MATCH[key]}
        elif spec.get("nth") is not None:
            card_fields[key] = {**base_rule, "nth": int(spec["nth"]), "cast": "str"}

    if draft.get("has_image"):
        card_fields["image_url"] = {"css": "img", "attr": "src", "cast": "str"}

    lp: dict = {"card": draft.get("card") or "",
                "card_fields": card_fields}
    if draft.get("item_link"):
        lp["item_link"] = draft["item_link"]
    if draft.get("detail_url_template"):
        lp["detail_url_template"] = draft["detail_url_template"]

    return {
        "code": code,
        "name": draft.get("name") or code,
        "base_url": base,
        "listing_type_default": draft.get("listing_type") or "retail",
        "pace": {"base_delay": float(draft.get("delay") or 5.0), "jitter": 2.0,
                 "max_delay": 240.0, "max_rps": 0.25},
        "schedule": {"every_hours": float(draft.get("every_hours") or 0)},
        "seeds": [],
        "render": {
            "enabled": True,
            "mobile": bool(draft.get("mobile")),
            "wait_ms": 3000,
            "scroll_wait_ms": 900,
            "target": int(draft.get("target") or 100),
            "pages": draft.get("pages") or [],
        },
        "list_page": lp,
        "detail_page": {"fields": {}},
    }


def to_yaml(draft: dict, notes: str = "") -> str:
    """사람이 읽을 수 있는 YAML 로 쓴다.

    yaml.dump 를 안 쓰는 이유: 순서가 뒤섞이고 주석을 못 넣는다.
    이 파일은 사람이 이어서 고칠 것이라 읽는 순서가 중요하다.
    """
    import yaml as _y

    d = build_config(draft)
    head = f"""# ═══════════════════════════════════════════════════════════════
#  {d['name']} — 수집 설정
#  ---------------------------------------------------------------
#  ★ 마법사가 자동으로 만든 초안입니다 ({datetime.now(UTC).strftime('%Y-%m-%d')}).
#    화면을 보고 짐작한 것이라 **틀릴 수 있습니다.**
#    [데이터] 탭에서 값이 제대로 들어오는지 꼭 확인해 주세요.
#
#  자주 고치는 값(주기·목표 개수·수집할 페이지)은 [설정] 탭의 폼에서
#  바꿀 수 있습니다. 셀렉터는 여기서 고치거나 [탐색기] 를 쓰세요.
#
#  ⚠ 목록만 잡혀 있습니다. 상세 페이지에서 뽑을 값(모델번호·발매가 등)은
#    아직 비어 있습니다 — 필요해지면 detail_page 에 채우세요.
"""
    if notes:
        head += "#\n" + "\n".join(f"#  {ln}" for ln in notes.splitlines()[:8]) + "\n"
    head += "# ═══════════════════════════════════════════════════════════════\n\n"

    body = _y.safe_dump(d, allow_unicode=True, sort_keys=False,
                        default_flow_style=False, width=100)
    return head + body


def domain_of(url: str) -> dict:
    u = urlsplit(url if "://" in url else "https://" + url)
    return {"host": u.netloc, "base_url": f"{u.scheme}://{u.netloc}",
            "path": u.path + (("?" + u.query) if u.query else ""),
            "code": _slug(u.netloc)}


def save(config_dir: Path, draft: dict, notes: str = "") -> dict:
    code = draft.get("code") or ""
    if not re.fullmatch(r"[a-z0-9_]{2,30}", code):
        return {"ok": False,
                "error": "코드는 영문 소문자·숫자·밑줄로 2~30자여야 합니다."}
    p = Path(config_dir) / f"{code}.yaml"
    if p.exists():
        return {"ok": False, "error": f"'{code}' 는 이미 있습니다. 다른 코드를 쓰세요."}
    p.write_text(to_yaml(draft, notes), encoding="utf-8")
    return {"ok": True, "code": code, "path": str(p)}
