"""LLM 이 뱉은 마크다운을 화면이 쓰는 형태로 바꾼다.

문제
  화면은 받은 글자를 전부 이스케이프해서 그린다 (chat_api.js esc()).
  안전하지만, 모델이 `**발레코어**` 나 `[출처](https://…)` 를 쓰면
  사용자 눈에는 별표와 대괄호가 그대로 보인다. 실제로 그렇게 보였다.

두 가지 길이 있었다.
  (가) 화면에서 마크다운을 렌더한다 → HTML 을 다시 허용해야 한다. 주입 경로가 열린다.
  (나) 서버에서 마크다운을 없앤다 → 화면은 계속 글자만 그린다.
  (나)를 택했다. 링크는 지우지 않고 **links 블록으로 옮긴다** —
  본문에 붙어 있던 주소가 사라지는 게 아니라 제자리를 찾는 것이다.

돌려주는 것
  {"text": 문단 사이 빈 줄 하나로 정리된 순수 텍스트,
   "links": [{"title","url"}]}
"""
from __future__ import annotations

import re

_FENCE = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_MD_LINK = re.compile(r"\[([^\]\n]{0,120})\]\((https?://[^\s)]+)\)")
_AUTOLINK = re.compile(r"<(https?://[^\s>]+)>")
_BARE_URL = re.compile(r"(?<![\w(])(https?://[^\s<>()\[\]]+)")
_BOLD = re.compile(r"(\*\*|__)(.+?)\1", re.S)
_ITALIC = re.compile(r"(?<![\w*_])([*_])([^\s*_][^*_]*?)\1(?![\w*_])")
_STRIKE = re.compile(r"~~(.+?)~~", re.S)
_HEADING_LINE = re.compile(r"^\s{0,3}#{1,6}[^\n]*$", re.M)   # 제목은 통째로 뺀다 — 블록에 title 이 따로 있다
_QUOTE = re.compile(r"^\s{0,3}>\s?", re.M)
_BULLET = re.compile(r"^\s{0,3}[-*+]\s+", re.M)
_ORDERED = re.compile(r"^\s{0,3}(\d{1,2})[.)]\s+", re.M)
_RULE = re.compile(r"^\s{0,3}([-*_])\s*(?:\1\s*){2,}$", re.M)
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.M)          # 표는 3~5문장 답변에 들어올 자리가 아니다
_FOOTNOTE = re.compile(r"\[\^?\d{1,2}\]")
_BLANKS = re.compile(r"\n{3,}")
_TRAIL = re.compile(r"[ \t]+$", re.M)


def convert(md: str | None) -> dict:
    if not md:
        return {"text": "", "links": []}
    s = str(md)
    links: list[dict] = []
    seen: set[str] = set()

    def _take(title: str, url: str) -> None:
        u = url.rstrip(".,)”\"'")
        if u in seen:
            return
        seen.add(u)
        links.append({"title": (title or "").strip() or u, "url": u})

    s = _FENCE.sub(" ", s)
    s = _INLINE_CODE.sub(r"\1", s)

    def _link(m):
        _take(m.group(1), m.group(2))
        return m.group(1).strip()                 # 글에는 말만 남기고 주소는 옮긴다
    s = _MD_LINK.sub(_link, s)

    def _auto(m):
        _take("", m.group(1))
        return ""
    s = _AUTOLINK.sub(_auto, s)
    s = _BARE_URL.sub(_auto, s)

    s = _BOLD.sub(r"\2", s)
    s = _STRIKE.sub(r"\1", s)
    s = _ITALIC.sub(r"\2", s)
    s = _RULE.sub("", s)
    s = _TABLE_ROW.sub("", s)
    s = _HEADING_LINE.sub("", s)
    s = _QUOTE.sub("", s)
    s = _BULLET.sub("· ", s)
    s = _ORDERED.sub(r"\1. ", s)
    s = _FOOTNOTE.sub("", s)
    s = _TRAIL.sub("", s)
    # 주소를 걷어내고 나면 "· 참고:" 처럼 껍데기만 남는 줄이 생긴다
    s = "\n".join(ln for ln in s.split("\n")
                  if len(ln.strip().lstrip("·").strip(" :·-")) >= 4 or not ln.strip())
    s = _BLANKS.sub("\n\n", s)
    # 문장 사이에 끼어든 홑줄바꿈은 붙인다 — 모델이 넣은 줄바꿈은 문단이 아니라 습관이다
    s = re.sub(r"(?<![.\n!?…:·])\n(?!\n)(?![·\d])", " ", s)
    s = re.sub(r"[ \t]{2,}", " ", s).strip()
    return {"text": s, "links": links}


def first_sentence(text: str, limit: int = 140) -> str:
    """한 줄 결론으로 쓸 첫 문장. 문단 나눔·글머리표는 빼고 본다."""
    for line in (text or "").split("\n"):
        line = line.strip().lstrip("· ").strip()
        if len(line) < 8:
            continue
        m = re.search(r"^(.{8,}?[.!?…]|.{8,}?(?:입니다|습니다|이다|한다)\.)", line)
        out = (m.group(1) if m else line).strip()
        return out if len(out) <= limit else out[:limit].rstrip() + "…"
    return (text or "").strip()[:limit]
