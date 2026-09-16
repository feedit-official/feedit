"""
어댑터 — 설정(YAML)만 보고 페이지에서 값을 뽑는다.

사이트마다 파이썬 파일을 따로 두지 않은 이유:
구조가 바뀔 때마다 개발자를 불러야 하면, 크롤링을 처음 하는 팀원은
영원히 남에게 부탁해야 한다. 셀렉터를 설정으로 빼면 탐색기가 찾아 준 값을
그대로 붙여 넣어 스스로 고칠 수 있다.

값을 뽑는 방법은 두 가지고, 위쪽을 늘 먼저 시도한다.
  1) embedded JSON  — 페이지에 박힌 __NEXT_DATA__ 등. 훨씬 안 깨진다
  2) CSS 셀렉터     — 위가 없을 때
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

import yaml
from bs4 import BeautifulSoup

from .nuxt import dig as ndig, dominant, parse_nuxt

NUM_RE = re.compile(r"[^\d]")


def to_int(v: Any) -> Optional[int]:
    """'298,000원' → 298000. 실패하면 None (0 으로 뭉개지 않는다)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    d = NUM_RE.sub("", str(v))
    return int(d) if d else None


def dig(obj: Any, path: str) -> Any:
    """'props.pageProps.item.price' 또는 'items[0].name' 을 따라 들어간다."""
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        m = re.match(r"^([^\[]*)\[(\d+)\]$", part)
        idx = None
        if m:
            part, idx = m.group(1), int(m.group(2))
        if part:
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                cur = getattr(cur, part, None)
        if idx is not None and isinstance(cur, list):
            cur = cur[idx] if idx < len(cur) else None
    return cur


def _as_list(v) -> list:
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def to_strlist(v: Any) -> list[str]:
    """태그를 글자 목록으로 고른다.

    사이트마다 모양이 제각각이다. 전부 받아 준다.
        ["발레코어", "스니커즈"]
        [{"name": "발레코어"}, {"tagName": "스니커즈"}]
        "#발레코어 #스니커즈"
        "발레코어,스니커즈"
    """
    if v in (None, "", [], {}):
        return []
    out: list[str] = []
    if isinstance(v, str):
        parts = re.split(r"[#,|·/\n]+", v)
        out = [p.strip() for p in parts if p.strip()]
    elif isinstance(v, (list, tuple)):
        for it in v:
            if isinstance(it, str):
                out.append(it.strip())
            elif isinstance(it, dict):
                for k in ("name", "tagName", "title", "label",
                          "text", "value", "keyword"):
                    if isinstance(it.get(k), str) and it[k].strip():
                        out.append(it[k].strip())
                        break
    elif isinstance(v, dict):
        return to_strlist(list(v.values()))
    # '#' 을 떼고, 너무 길거나 짧은 건 태그가 아니다
    clean = []
    for t in out:
        t = t.lstrip("#").strip()
        if 1 < len(t) <= 20 and t not in clean:
            clean.append(t)
    return clean


def find_key_deep(obj: Any, key: str, limit: int = 200) -> list:
    """중첩된 JSON 어디에 있든 그 키를 전부 찾아온다.

    __NEXT_DATA__ 는 구조가 깊고 배포마다 경로가 바뀐다. 경로를 박아 두는 것보다
    키 이름으로 훑는 편이 오래 간다.
    """
    out, stack = [], [obj]
    while stack and len(out) < limit:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k == key:
                    out.append(v)
                elif isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(x for x in cur if isinstance(x, (dict, list)))
    return out


# ──────────────────────────────────────────────────────────────
@dataclass
class SiteConfig:
    code: str
    name: str
    base_url: str
    listing_type_default: str = "ask"     # 이 사이트가 주는 가격이 호가인가 체결가인가
    pace: dict = field(default_factory=dict)
    seeds: list = field(default_factory=list)
    list_page: dict = field(default_factory=dict)
    detail_page: dict = field(default_factory=dict)
    # 정기 실행 계획 — {every_hours: 12, list_only: false, max_items: 200}
    schedule: dict = field(default_factory=dict)
    # 이미 아는 상품을 다시 보기 — 목록이 안 되는 사이트(지그재그)의 생명줄
    revisit: dict = field(default_factory=dict)
    # 브라우저로 그려서 받아오기 — robots 가 허락한 사이트에서만 쓴다
    render: dict = field(default_factory=dict)
    sitemap: dict = field(default_factory=dict)
    # robots 정책과 별개로 사이트가 서면/계약으로 직접 허용한 경우에만 사용.
    authorization: dict = field(default_factory=dict)
    user_agent: str = ""
    # 못 박아 둔 상세 주소 — 목록에 안 나와도 매 회차 반드시 다시 본다.
    # 발표에 꼭 나와야 하는 상품에 쓴다 (config/demo_targets.json 의 pinned_products).
    pinned_details: list = field(default_factory=list)
    notes: str = ""

    @classmethod
    def load(cls, path: str | Path) -> "SiteConfig":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict) -> "SiteConfig":
        """딕셔너리에서 바로 만든다 — 마법사가 미리보기에 쓴다.

        모르는 칸은 조용히 버린다. 설정에 우리가 아직 안 읽는 값이
        섞여 있어도 통째로 죽지 않게 하려는 것이다.
        """
        known = {f for f in cls.__dataclass_fields__}
        got = cls(**{k: v for k, v in (raw or {}).items() if k in known})

        # 신분은 config/identity.yaml 한 곳에서 나온다.
        # yaml 에 "{bot} (+{homepage}; …)" 처럼 적어 두면 여기서 채운다.
        # 자리표를 안 쓰고 통째로 적어 둔 설정도 그대로 통과한다.
        from .identity import expand
        got.user_agent = expand(got.user_agent)
        if isinstance(got.render, dict) and got.render.get("user_agent"):
            got.render = {**got.render,
                          "user_agent": expand(got.render["user_agent"])}
        return got


class ConfigAdapter:
    """설정대로 페이지를 해석한다."""

    def __init__(self, cfg: SiteConfig):
        self.cfg = cfg

    # ── 페이지에 박힌 JSON 꺼내기 ─────────────────────────────
    def embedded(self, html: str) -> Optional[dict]:
        for pat in (
            r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>',
            r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});',
            r'window\.__APOLLO_STATE__\s*=\s*(\{.*?\});',
        ):
            m = re.search(pat, html, re.S)
            if m:
                try:
                    return json.loads(m.group(1))
                except json.JSONDecodeError:
                    continue

        # JSON-LD (schema.org) — 후르츠패밀리 상세가 이걸 쓴다.
        # 표준 규격이라 사이트 개편에도 잘 안 깨진다. 셀렉터보다 훨씬 안전하다.
        # @type=Product 인 블록만 고른다 (BreadcrumbList·Organization 등이 섞여 있다).
        best = None
        for m in re.finditer(
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S
        ):
            try:
                d = json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
            for cand in (d if isinstance(d, list) else [d]):
                if not isinstance(cand, dict):
                    continue
                if cand.get("@type") == "Product":
                    return cand
                best = best or cand
        return best

    # ── 값 하나 뽑기 ─────────────────────────────────────────
    def _pull(self, rule: Any, soup: Optional[BeautifulSoup],
              data: Optional[dict], nx: Any = None) -> Any:
        """rule 은 문자열(셀렉터) 이거나 dict(자세한 지정).

        dict 예:
          { json: "props.pageProps.item.price", cast: int }
          { deep: "salePrice", cast: int }
          { css: ".price em", attr: "text", cast: int }
          { nuxt_text: "^모델번호\\s+(.+)$" }      ← Nuxt 화면 문구에서 뽑기
        """
        if rule is None:
            return None
        if isinstance(rule, str):
            rule = {"css": rule}

        # ★ any: 여러 방법을 차례로 — 먼저 잡히는 것을 쓴다
        #   화면마다 값이 든 태그가 다르다. 무신사 랭킹은 <p>, 검색은 <span>.
        #   하나만 적어 두면 다른 화면에서 그 칸이 통째로 빈다 —
        #   실제로 이름 없는 상품 1,679건이 그렇게 쌓였다.
        if rule.get("any"):
            # reject 는 '이건 답이 아니다' 는 잣대다. 뒷줄 후보가 배지·할인율을
            # 집어 오는 것을 막고 **다음 후보로 넘어가게** 한다.
            #   무신사 브랜드관 카드에는 img[alt] 가 없어서 뒷줄인 <span> 두 번째가
            #   걸렸는데, 그게 'FW 26 신상'·'무배당발' 같은 배지였다.
            #   그렇게 1,482건 중 796건(54%)이 배지를 이름으로 갖게 됐다.
            deny = rule.get("reject")
            rx = re.compile(deny) if deny else None
            for sub in rule["any"]:
                got = self._pull(sub, soup, data, nx)
                if got in (None, "", [], {}):
                    continue
                if rx and isinstance(got, str) and rx.search(got.strip()):
                    continue          # 배지였다 — 없는 셈 치고 다음 후보로
                return got
            return None

        val = None

        # Nuxt 화면 문구 — '모델번호 K87-BLK' 처럼 라벨과 값이 붙어 있는 것들.
        # 레코드로는 안 실리고 이 형태로만 나오는 값이 있다.
        if nx is not None and rule.get("nuxt_text"):
            val = nx.find_text(rule["nuxt_text"], rule.get("group", 1))

        # 여러 값을 더해서 만드는 값.
        # 지그재그는 '정가' 칸이 아예 없고 판매가와 할인액만 준다.
        # 28,800 + 17,200 = 46,000 처럼 되짚어야 정가가 나온다.
        # 할인율로 나누는 방법도 있지만 반올림 때문에 어긋나므로 덧셈이 정확하다.
        if val is None and data is not None and rule.get("sum"):
            parts = [to_int(dig(data, p)) for p in rule["sum"]]
            got = [p for p in parts if p is not None]
            if len(got) == len(parts) and got:
                val = sum(got)

        if val is None and data is not None:
            # ★ 후보를 여러 개 적을 수 있다
            #   사이트가 키 이름을 안 알려 줄 때가 있다. 무신사 스타일 태그가
            #   styleTags 인지 goodsTag 인지 tags 인지 확인할 길이 없었다.
            #   하나씩 넣어 보고 잡히는 것을 쓴다 — 이름이 바뀌어도 버틴다.
            for path in _as_list(rule.get("json")):
                val = dig(data, path)
                if val not in (None, "", [], {}):
                    break
                val = None
            if val is None:
                for key in _as_list(rule.get("deep")):
                    hits = find_key_deep(data, key)
                    got = next((h for h in hits if h not in (None, "", [], {})), None)
                    if got is not None:
                        val = got
                        break

        # css_all + match — "여러 개 중 이 패턴에 맞는 것"을 고른다.
        # 크림처럼 브랜드·상품명·할인율·가격이 전부 같은 클래스를 쓰고
        # 순서마저 카드마다 다른 사이트에서는 nth-child 가 통하지 않는다.
        if val is None and soup is not None and rule.get("css_all"):
            els = soup.select(rule["css_all"])
            # ★ leaf — '글자를 직접 담고 있는 요소'만 센다.
            #   요즘 사이트는 div 를 겹겹이 쌓아서, 그냥 세면 앞쪽이 전부
            #   빈 껍데기다. 지그재그에서 nth:0 이 빈 div 를 집어 이름이
            #   통째로 비었다. 잎사귀만 세면 사람이 보는 순서와 맞는다.
            if rule.get("leaf"):
                els = [e for e in els
                       if not e.find(["div", "span", "p", "a", "li"])
                       and e.get_text(strip=True)]
            pat = rule.get("match")
            nth = rule.get("nth")
            picked = None
            if pat:
                rx = re.compile(pat)
                hits = [e for e in els if rx.search(e.get_text(" ", strip=True))]
                if hits:
                    picked = hits[rule.get("match_nth", 0)] if len(hits) > rule.get("match_nth", 0) else None
            elif nth is not None:
                # 음수면 뒤에서부터 센다 (-1 = 마지막).
                # 에이블리처럼 앞에 '브랜드' 배지가 붙었다 말았다 하는 카드에서는
                # 앞에서 세면 밀리고 뒤에서 세면 안 밀린다.
                if -len(els) <= nth < len(els):
                    picked = els[nth]
            if picked is not None:
                attr = rule.get("attr", "text")
                val = picked.get_text(" ", strip=True) if attr == "text" else picked.get(attr)

        # 자기 자신의 속성 — 카드 <div> 에 붙은 data-* 를 읽을 때 쓴다.
        # 무신사가 카드마다 data-item-id / data-original-price 를 달아 두는데,
        # 클래스명은 빌드마다 바뀌는 해시라 이쪽이 훨씬 오래 간다.
        if val is None and soup is not None and rule.get("attr_self"):
            getter = getattr(soup, "get", None)
            if callable(getter):
                val = soup.get(rule["attr_self"])

        if val is None and soup is not None and rule.get("css"):
            el = soup.select_one(rule["css"])
            if el is not None:
                attr = rule.get("attr", "text")
                if attr == "text":
                    val = el.get_text(" ", strip=True)
                else:
                    val = el.get(attr)

        if val is None:
            return rule.get("default")

        if rule.get("regex"):
            m = re.search(rule["regex"], str(val))
            val = m.group(1) if m and m.groups() else (m.group(0) if m else None)

        cast = rule.get("cast")
        if cast == "int":
            val = to_int(val)
        elif cast == "str" and val is not None:
            val = str(val).strip()
        elif cast == "strlist":
            val = to_strlist(val)
        return val

    # ── 목록 페이지 → 상세 URL 들 ────────────────────────────
    def parse_list(self, html: str) -> list[str]:
        cfg = self.cfg.list_page or {}
        data = self.embedded(html)
        urls: list[str] = []

        # 1순위: 박힌 JSON 에서 id 목록을 꺼내 URL 을 만든다.
        # json_items(정확한 경로)와 deep_items(키 이름으로 훑기)는 서로 독립이다 —
        # 둘 중 하나만 적어도 동작해야 한다.
        if data:
            items = None
            if cfg.get("json_items"):
                items = dig(data, cfg["json_items"])
            if items is None and cfg.get("deep_items"):
                hits = find_key_deep(data, cfg["deep_items"])
                items = hits[0] if hits else None
            if isinstance(items, list):
                tmpl = cfg.get("detail_url_template", "/product/{id}")
                key = cfg.get("item_id_key", "id")
                for it in items:
                    v = it.get(key) if isinstance(it, dict) else it
                    if v is not None:
                        urls.append(tmpl.format(id=v))

        # 2순위: 셀렉터로 링크 긁기
        if not urls and cfg.get("item_link"):
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.select(cfg["item_link"]):
                href = a.get("href")
                if href:
                    urls.append(href)

        # 중복 제거하되 순서는 유지 (재개했을 때 같은 순서로 돌아야 한다)
        seen, out = set(), []
        for u in urls:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    # ── 목록 페이지 → 카드 단위 레코드 ───────────────────────
    def parse_list_records(self, html: str) -> list[dict]:
        """목록 한 장에서 상품 정보까지 바로 뽑는다.

        상세 페이지를 50번 여는 대신 목록 1번으로 50개를 얻는다.
        서버 부담이 50분의 1이고 우리도 훨씬 빠르다.
        체결 이력이 꼭 필요한 상품만 나중에 상세로 들어가면 된다.
        """
        cfg = self.cfg.list_page or {}
        card_sel = cfg.get("card")
        fields = cfg.get("card_fields") or {}
        if not card_sel or not fields:
            return []

        soup = BeautifulSoup(html, "html.parser")

        # ★ 카드 셀렉터를 여러 개 적을 수 있다
        #   'div.gtm-view-item-list' 는 무신사 **랭킹** 화면에서 확인한 것이다.
        #   검색 결과는 구조가 달라서 한 건도 안 잡혔다 — 담아오기가 카드를
        #   모아 보내도 서버가 0건으로 버렸다.
        #   여러 개를 시도해 **가장 많이 잡히는 것**을 쓴다.
        #  ★ '가장 많이 잡는 것' 이 아니라 '순서대로 먼저 맞는 것'
        #    많이 잡는 쪽을 고르면 헐렁한 셀렉터가 이긴다. 실제로 카드 30개짜리
        #    화면에서 60건이 나왔고, 절반은 상품이 아닌 조각이었다.
        #    설정에는 **구체적인 것부터** 적어 두고, 둘 이상 잡히면 거기서 멈춘다.
        cards = []
        for sel in (card_sel if isinstance(card_sel, list) else [card_sel]):
            try:
                got = soup.select(sel)
            except Exception:
                continue
            if len(got) >= 2:
                cards = got
                break
            if len(got) > len(cards):
                cards = got

        out = []
        for card in cards:
            rec: dict[str, Any] = {}
            for name, rule in fields.items():
                rec[name] = self._pull(rule, card, None)
            # 링크에서 id 를 건져 둔다 — 상세로 들어갈 때 쓴다
            href = card.get("href") if card.name == "a" else None
            if not href:
                a = card.find("a")
                href = a.get("href") if a else None
            if href:
                rec["source_url"] = href
                if not rec.get("source_uid"):
                    rec["source_uid"] = self._uid_from(href, cfg)
            if rec.get("source_uid") or rec.get("name"):
                # ★ 이름을 못 읽었으면 그 카드의 HTML 을 남긴다
                #   화면 구조가 바뀌었을 때 '왜 못 읽었나' 를 짐작으로 고치면
                #   몇 번을 헛돈다. 실제 생김새를 봐야 한 번에 고친다.
                if not rec.get("name"):
                    rec["_card_html"] = str(card)[:3000]
                out.append(rec)
        return out

    # ── URL 에서 상품 ID 뽑기 ────────────────────────────────
    @staticmethod
    def _uid_from(href: str, cfg: dict) -> Optional[str]:
        """상품 ID 는 사이트마다 생김새가 다르다.

        크림   /products/12831              → 숫자
        후르츠 /product/68q7g/니들스-쇼츠     → 영숫자 + 뒤에 슬러그
        숫자만 가정하면 후르츠에서 통째로 실패한다.
        """
        # 설정에 정규식이 있으면 그게 우선
        if cfg.get("uid_regex"):
            m = re.search(cfg["uid_regex"], href)
            if m:
                return m.group(1) if m.groups() else m.group(0)
        # 설정에 적힌 상세 주소 모양에서 만들어 본다.
        #   '/goods/{id}' → '/goods/(...)'
        # 이게 없으면 /goods/ 처럼 product 가 안 들어간 사이트에서
        # 숫자 ID 일 때만 우연히 통하고, 영숫자 ID 면 조용히 실패한다.
        tmpl = cfg.get("detail_url_template") or ""
        if "{id}" in tmpl:
            head = re.escape(tmpl.split("{id}")[0].rstrip("/")) + r"/([^/?#]+)"
            m = re.search(head, href)
            if m:
                return m.group(1)

        # 기본: /product(s)/ 바로 다음 조각
        m = re.search(r"/products?/([^/?#]+)", href)
        if m:
            return m.group(1)
        # 마지막 수단: 경로 끝의 숫자
        m = re.search(r"/(\d+)/?(?:\?|#|$)", href)
        return m.group(1) if m else None

    # ── 상세 페이지 → 스키마 모양의 dict ─────────────────────
    @staticmethod
    def _needs_nuxt(cfg: dict) -> bool:
        """설정 어딘가에서 nuxt_text 를 쓰는지 본다. 안 쓰면 해독을 건너뛴다
        (1.5MB JSON 을 푸는 건 공짜가 아니다)."""
        for rule in (cfg.get("fields") or {}).values():
            if isinstance(rule, dict) and rule.get("nuxt_text"):
                return True
        return False

    def _next_root(self, data: Optional[dict], cfg: dict, url: str) -> Optional[dict]:
        """Next.js(React Query) 캐시에서 '이 상품' 항목만 골라낸다.

        무신사 상세에는 연관 상품·다른 색상 상품의 데이터가 함께 실린다.
        deep 탐색으로 'goodsNo' 를 찾으면 남의 상품 번호가 먼저 걸린다 —
        실제로 4923323 을 봐야 하는데 3847970(빈폴 키즈)이 나왔다.
        그래서 queryKey 로 정확히 집는다.
        """
        q = cfg.get("next_query")
        if not q or not data:
            return data
        queries = dig(data, q.get("queries_path",
                                 "props.pageProps.dehydratedState.queries"))
        if not isinstance(queries, list):
            return data

        prefix = [str(x) for x in (q.get("key_prefix") or [])]
        want = self._uid_from(url, self.cfg.list_page or {}) \
            if q.get("match_id", True) else None

        best = None
        for item in queries:
            key = item.get("queryKey") if isinstance(item, dict) else None
            if not isinstance(key, list):
                continue
            head = [str(x) for x in key[:len(prefix)]]
            if prefix and head != prefix:
                continue
            rest = [str(x) for x in key[len(prefix):]]
            if want is not None:
                if len(rest) == 1 and rest[0] == str(want):
                    best = item
                    break            # 상품번호까지 맞으면 확정
                continue
            best = best or item
        if best is None:
            return data
        root = dig(best, q.get("path", "state.data.data"))
        return root if isinstance(root, (dict, list)) else data

    def parse_detail(self, html: str, url: str = "") -> dict:
        cfg = self.cfg.detail_page or {}
        data = self.embedded(html)
        data = self._next_root(data, cfg, url)
        soup = BeautifulSoup(html, "html.parser")

        # ★ Nuxt 페이지(크림)는 서버가 화면을 안 그려 준다. DOM 은 비어 있고
        #   값은 __NUXT_DATA__ 안에만 있다. 브라우저로 저장한 파일에서는
        #   DOM 이 보이지만 크롤러는 그 상태를 절대 못 받는다 — 여기서 읽어야 한다.
        nx = parse_nuxt(html) if ("nuxt" in cfg or self._needs_nuxt(cfg)) else None

        rec: dict[str, Any] = {"source_url": url}
        for field_name, rule in (cfg.get("fields") or {}).items():
            rec[field_name] = self._pull(rule, soup, data, nx)

        # ── Nuxt 레코드에서 통째로 가져오기 ──
        #   화면 배치(SDUI) 사이에 제대로 된 객체가 섞여 있다.
        #   { brand_name, translated_name, category, image_url } 같은 것들이다.
        for block, spec in ((cfg.get("nuxt") or {}).items() if nx else ()):
            if block == "trades":
                continue                      # 아래에서 따로 다룬다
            recs = nx.records(spec.get("keys") or [])
            if not recs:
                continue
            src = recs[0]
            for out_name, path in (spec.get("map") or {}).items():
                if rec.get(out_name) in (None, ""):
                    rec[out_name] = ndig(src, path)

        # 체결 이력 — 리세일 지수의 핵심. 없으면 지수를 못 만든다.
        trades = []
        tcfg = cfg.get("trades") or {}

        # ① CSS 방식 — 체결 표가 DOM 에 그려져 있을 때 (크림이 이 경우)
        #    ★ 크림은 체결/판매입찰/구매입찰 세 탭을 DOM 에 전부 그려 둔다.
        #      row 셀렉터를 넓게 잡으면 호가가 체결가에 섞여 지수가 통째로 부푼다.
        #      scope 로 '체결' 탭만 정확히 집어야 한다.
        if tcfg.get("row"):
            scope_sel = tcfg.get("scope")
            scopes = soup.select(scope_sel) if scope_sel else [soup]
            # PC·모바일 레이아웃이 이중으로 그려지는 페이지가 있다. 첫 블록만 쓴다.
            if tcfg.get("first_scope_only", True) and scopes:
                scopes = scopes[:1]
            for sc in scopes:
                for row in sc.select(tcfg["row"])[: tcfg.get("limit", 300)]:
                    price = to_int(self._pull(tcfg.get("price"), row, None))
                    if not price:
                        continue
                    trades.append({
                        "price": price,
                        "size_name": self._pull(tcfg.get("size"), row, None),
                        "settled_at": self._pull(tcfg.get("date"), row, None),
                    })

        # ② Nuxt 레코드 방식 — 크림은 이제 이 길로 간다
        #    거래가 {product_id, product_option, price, date_created} 형태로 들어 있다.
        #    date_created 가 '36분 전' 이 아니라 ISO 시각이라 DOM 보다 정확하다.
        ncfg = (cfg.get("nuxt") or {}).get("trades") if nx else None
        if not trades and ncfg:
            recs = nx.records(ncfg.get("keys") or [])
            # 상세에는 연관 상품 거래도 함께 실린다. 그대로 쓰면 남의 시세가
            # 섞이므로 이 페이지의 주인공(가장 많이 나온 product_id)만 남긴다.
            owner = ncfg.get("owner_key", "product_id")
            if owner:
                recs = dominant(recs, owner)
            m = ncfg.get("map") or {}
            for r in recs[: ncfg.get("limit", 300)]:
                trades.append({
                    "price": to_int(ndig(r, m.get("price", "price"))),
                    "size_name": ndig(r, m.get("size_name", "product_option.name")),
                    "settled_at": ndig(r, m.get("settled_at", "date_created")),
                })

        # ③ JSON 방식
        if not trades and data and tcfg.get("deep"):
            hits = find_key_deep(data, tcfg["deep"])
            rows = hits[0] if hits else []
            if isinstance(rows, list):
                for r in rows[: tcfg.get("limit", 300)]:
                    if not isinstance(r, dict):
                        continue
                    trades.append({
                        "price": to_int(dig(r, tcfg.get("price_key", "price"))),
                        "size_name": dig(r, tcfg.get("size_key", "size")),
                        "settled_at": dig(r, tcfg.get("date_key", "date")),
                    })
        rec["trades"] = [t for t in trades if t.get("price")]

        # ── 실측 치수 ──
        #   후르츠패밀리가 총장·어깨너비·가슴단면을 cm 로 실어 준다.
        #   중고는 사이즈 표기가 제각각(OS, 32, M)이라 실측이 없으면 비교가 안 된다.
        #   가입 때 받은 키·몸무게와 맞춰 "내 체형에 맞는 사이즈"를 계산할 재료다.
        mcfg = cfg.get("measurements") or {}
        meas = []
        if mcfg and data is not None:
            items = dig(data, mcfg.get("json", "additionalProperty"))
            if isinstance(items, dict):
                items = [items]
            for it in (items or []):
                if not isinstance(it, dict):
                    continue
                name = it.get(mcfg.get("key", "propertyID")) or it.get("name")
                val = to_int(it.get(mcfg.get("value", "value")))
                if not name or val is None:
                    continue
                meas.append({"name": str(name),
                             "value": val,
                             "unit": it.get(mcfg.get("unit", "unitText")) or "cm"})
        rec["measurements"] = meas

        rec["listing_type"] = cfg.get("listing_type", self.cfg.listing_type_default)
        return rec

    # ── 시드 URL 만들기 ──────────────────────────────────────
    def iter_seed_urls(self) -> Iterator[str]:
        for s in self.cfg.seeds:
            if isinstance(s, str):
                yield s
                continue
            tmpl = s.get("template")
            if not tmpl:
                continue
            pages = s.get("pages", 1)
            for p in range(s.get("start", 1), s.get("start", 1) + pages):
                yield tmpl.format(page=p, **{k: v for k, v in s.items()
                                             if k not in ("template", "pages", "start")})
