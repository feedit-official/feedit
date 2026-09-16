"""무신사 상세에서 실측 사이즈·핏 후기·연관 태그를 읽는다.

★ 먼저 알아야 할 것 — 이 값들은 원본 HTML 에 없다
   `https://www.musinsa.com/products/4914421` 을 그냥 받아 보면 119,817자가
   오는데, 그 안에 '총장'도 '어깨너비'도 '<table>' 도 **하나도 없다.**
   `__NEXT_DATA__` 의 dehydratedState 에도 사이즈 질의가 없다.
   실측표는 화면을 그린 뒤에야 생긴다.

   → 그래서 상세도 **렌더링해서** 받아야 이 값들이 잡힌다.
     `render.detail: true` 로 켠다. 안 켜면 조용히 빈 값만 쌓인다.

무엇을 읽나 (2026-08-31 실제 화면에서 확인)
------------------------------------------
1. 실측 사이즈표
       cm  내 사이즈  S    M    L    XL      ← 사이즈 이름은 표 앞 <ul> 에
       총장     어깨너비  가슴단면  소매길이   ← 항목은 <thead><th>
       71.5     57      60.5    24.1      ← 값은 <tbody><tr>, 사이즈 순서대로
   항목은 분류마다 다르다 (바지는 허리단면·밑위, 신발은 굽높이…).
   그래서 항목 이름을 미리 못 박지 않고 표에 적힌 것을 그대로 쓴다.

2. 핏 후기 — ★ 사이즈 추천의 진짜 재료 ★
       구매옵션  XL
       체형정보  여성 · 160cm · 62kg
       만족도    사이즈 정사이즈 · 화면 대비 색감 화면과 비슷 · 퀄리티 좋음 · 구김 많음
   **키·몸무게·성별과 고른 사이즈와 그 평가가 한 줄에 같이 있다.**
   "165cm 55kg 인 사람들은 이 옷을 M 으로 사고 정사이즈라고 했다" 를
   그대로 만들 수 있다. 크림의 fit_note 보다 훨씬 값지다.

3. 연관 태그 — `#25SS #반팔셔츠 #셔츠 #하프셔츠`
   사람이 붙인 분류라 상품명에서 짐작하는 것보다 정확하다.

클래스 이름에 기대지 않는다
--------------------------
무신사 클래스는 `ActualSizeTable-sc-51c3613c-11` 처럼 해시가 붙는다.
빌드할 때마다 바뀌므로 여기에 기대면 어느 날 조용히 0건이 된다.
그래서 **글자와 구조**로 찾는다 — 머리글이 실측 항목인 표, '#' 로 시작하고
검색으로 가는 링크, '체형정보'와 '만족도'가 같이 있는 덩어리.
"""

from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup

# 실측 항목으로 인정하는 말. 표를 알아보는 데만 쓰고, 저장은 적힌 그대로 한다.
MEASURE_WORDS = {
    "총장", "어깨너비", "가슴단면", "소매길이", "암홀", "밑단단면", "소매단면",
    "허리단면", "엉덩이단면", "허벅지단면", "밑위", "밑단", "인심",
    "굽높이", "발볼", "굽", "높이", "너비", "깊이", "길이", "단면",
}
# 사이즈 이름 목록에서 빼야 하는 것
NOT_A_SIZE = {"cm", "내 사이즈", "사이즈", "inch", ""}

_WS = re.compile(r"\s+")
_NUM = re.compile(r"^-?\d+(?:\.\d+)?$")


def _t(el) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFC", el.get_text(" ", strip=True))).strip()


# ── 1) 실측 사이즈표 ──────────────────────────────────────────
def measurements(soup: BeautifulSoup) -> dict:
    """{'S': {'총장': 71.5, ...}, 'M': {...}} 로 돌려준다."""
    for table in soup.find_all("table"):
        heads = [_t(th) for th in table.select("thead th")] or \
                [_t(th) for th in table.select("tr th")]
        heads = [h for h in heads if h]
        if len(heads) < 2:
            continue
        # 머리글이 실측 항목처럼 생겼는가 — 절반 이상이면 인정한다
        looks = sum(1 for h in heads if any(w in h for w in MEASURE_WORDS))
        if looks * 2 < len(heads):
            continue

        rows = []
        for tr in table.select("tbody tr") or table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) != len(heads):
                continue                       # '직접 입력해주세요' 줄은 colspan 이라 걸러진다
            vals = [_t(td) for td in tds]
            if not any(_NUM.match(v) for v in vals):
                continue
            rows.append(vals)
        if not rows:
            continue

        sizes = _size_names(table, len(rows))
        out = {}
        for name, vals in zip(sizes, rows):
            got = {}
            for h, v in zip(heads, vals):
                got[h] = float(v) if _NUM.match(v) else v
            out[name] = got
        return out
    return {}


def _size_names(table, n: int) -> list[str]:
    """표 앞에 있는 목록에서 사이즈 이름을 가져온다. 못 찾으면 1,2,3… 으로 센다."""
    node = table
    for _ in range(4):                          # 몇 단계 위까지만 올려다본다
        node = node.parent
        if node is None:
            break
        for ul in node.find_all(["ul", "ol"]):
            names = [_t(li) for li in ul.find_all("li")]
            names = [x for x in names if x and x.lower() not in NOT_A_SIZE]
            if len(names) == n:
                return names
    return [str(i + 1) for i in range(n)]


# ── 2) 핏 후기 ────────────────────────────────────────────────
_BODY = re.compile(r"(남성|여성)\s*·\s*(\d{2,3})\s*cm\s*·\s*(\d{2,3})\s*kg")
# '사이즈 정사이즈 · 퀄리티 좋음' → {'사이즈': '정사이즈', '퀄리티': '좋음'}
_JUDGE_KEYS = ("사이즈", "화면 대비 색감", "색감", "퀄리티", "구김", "두께", "밝기")


def _has_inner_review(box) -> bool:
    """이 상자 안에 같은 조건을 만족하는 더 작은 상자가 있는가."""
    for child in box.find_all(["div", "li", "article"]):
        txt = child.get_text(" ", strip=True)
        if "체형정보" in txt and "만족도" in txt:
            return True
    return False


def fit_reviews(soup: BeautifulSoup, limit: int = 60) -> list[dict]:
    """후기에서 체형·고른 사이즈·평가를 뽑는다."""
    out: list[dict] = []
    seen = set()
    for box in soup.find_all(["div", "li", "article"]):
        txt = box.get_text(" ", strip=True)
        if "체형정보" not in txt or "만족도" not in txt or len(txt) > 1200:
            continue
        # 가장 안쪽 덩어리만 쓴다 — 바깥 상자도 같은 글자를 갖고 있다
        if _has_inner_review(box):
            continue
        rec = _one_review(box)
        if not rec:
            continue
        key = (rec.get("review_id"), rec.get("size"), rec.get("height"), rec.get("weight"))
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
        if len(out) >= limit:
            break
    return out


def _one_review(box) -> dict | None:
    rec: dict = {}
    rid = box.get("data-content-id") or ""
    root = box
    if not rid:
        up = box.find_parent(attrs={"data-content-id": True})
        rid = up.get("data-content-id") if up else ""
        if up is not None:
            root = up
    if rid:
        rec["review_id"] = str(rid)

    # 후기 원문. 작성자 닉네임은 읽거나 돌려주지 않는다. 화면의 후기 ID만
    # 중복 방지용 비식별 키로 쓰고, 실제 저장 때 다시 해시한다.
    content = root.select_one('[data-button-name="후기내용"]')
    if content:
        text = _t(content)
        if text:
            rec["body"] = text

    # 날짜와 별점은 작성자 링크 주변에 있지만 닉네임은 의도적으로 버린다.
    for span in root.find_all("span"):
        text = _t(span)
        if re.fullmatch(r"\d{2}\.\d{2}\.\d{2}", text):
            rec["published_at"] = "20" + text.replace(".", "-")
        elif text in {"1", "2", "3", "4", "5"} and "rating" not in rec:
            rec["rating"] = int(text)

    # '라벨 → 값' 짝. <span>라벨</span><span>값</span> 형태다.
    labels = {}
    for holder in box.find_all("div"):
        spans = holder.find_all("span", recursive=False)
        if len(spans) == 2:
            labels[_t(spans[0])] = _t(spans[1])

    if labels.get("구매옵션"):
        rec["size"] = labels["구매옵션"]

    body = labels.get("체형정보") or ""
    m = _BODY.search(body or box.get_text(" ", strip=True))
    if m:
        rec["gender"] = m.group(1)
        rec["height"] = int(m.group(2))
        rec["weight"] = int(m.group(3))

    judge = labels.get("만족도") or ""
    if judge:
        rec["judgements"] = _split_judge(judge)
        if rec["judgements"].get("사이즈"):
            rec["fit"] = rec["judgements"]["사이즈"]
    if not (rec.get("size") or rec.get("fit")):
        return None
    return rec


def _split_judge(s: str) -> dict:
    got = {}
    for part in re.split(r"\s*·\s*", s):
        part = part.strip()
        for k in _JUDGE_KEYS:
            if part.startswith(k):
                v = part[len(k):].strip()
                if v:
                    got[k] = v
                break
    return got


# ── 3) 연관 태그 ──────────────────────────────────────────────
def site_tags(soup: BeautifulSoup) -> list[str]:
    """`#반팔셔츠` 같은 사람이 붙인 태그."""
    out: list[str] = []
    for a in soup.find_all("a"):
        t = _t(a)
        if not t.startswith("#"):
            continue
        href = a.get("href") or ""
        if "/search/goods" not in href and "tag=" not in href:
            continue
        name = t.lstrip("#").strip()
        if name and name not in out:
            out.append(name)
    return out


# ── 한 번에 ───────────────────────────────────────────────────
def parse(html: str, review_limit: int = 60) -> dict:
    """그려진 상세 화면에서 사이즈·핏·태그를 한 번에 읽는다."""
    soup = BeautifulSoup(html or "", "html.parser")
    m = measurements(soup)
    r = fit_reviews(soup, limit=max(1, int(review_limit)))
    t = site_tags(soup)
    return {
        "measurements": m,
        "fit_reviews": r,
        "site_tags": t,
        "fit_summary": summarize(r),
        "_why": _why(m, r, t),
    }


def summarize(reviews: list[dict]) -> dict:
    """후기들을 한 줄로 — '정사이즈 12 · 작아요 3' 처럼."""
    if not reviews:
        return {}
    tally: dict[str, int] = {}
    hs, ws = [], []
    for r in reviews:
        f = r.get("fit")
        if f:
            tally[f] = tally.get(f, 0) + 1
        if r.get("height"):
            hs.append(r["height"])
        if r.get("weight"):
            ws.append(r["weight"])
    got = {"n": len(reviews), "fit_counts": tally}
    if tally:
        got["fit_note"] = max(tally, key=tally.get)
    if hs:
        got["avg_height"] = round(sum(hs) / len(hs), 1)
    if ws:
        got["avg_weight"] = round(sum(ws) / len(ws), 1)
    return got


def _why(m, r, t) -> str:
    """비었을 때 왜 비었는지 한 줄로 남긴다. 조용히 0건이 되는 걸 막는다."""
    if m or r or t:
        return ""
    return ("사이즈·핏·태그를 하나도 못 읽었습니다. 이 값들은 화면을 그려야 "
            "생깁니다 — 상세를 렌더링해서 받고 있는지 확인하세요 "
            "(render.detail). 원본 HTML 만 받으면 항상 빈 값입니다.")
