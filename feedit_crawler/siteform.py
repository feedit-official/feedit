"""
설정 폼 — YAML 을 안 만지고 값만 고친다.

지금까지 설정을 바꾸려면 YAML 을 직접 고쳐야 했다. 비전공자에게
"들여쓰기를 두 칸 맞추고 콜론 뒤에 공백을 넣으세요"는 말이 안 통한다.
한 칸만 어긋나도 통째로 안 읽힌다.

여기서는 **자주 바꾸는 값만** 폼으로 꺼낸다.
    이름 · 주소 · 수집할 페이지 · 목표 개수 · 주기 · 예의(요청 간격)
셀렉터처럼 화면 구조에 매인 값은 [고급] 뒤에 둔다 — 자주 바꿀 일이 없고,
바꿔야 할 땐 어차피 [탐색기] 를 거쳐야 한다.

★ 파일을 통째로 다시 쓰지 않는다
  YAML 을 파싱해서 다시 덤프하면 **주석이 전부 날아간다.**
  이 설정 파일들은 주석이 자산이다 — "이 셀렉터를 왜 이렇게 잡았는지",
  "이 사이트가 어떤 함정을 갖고 있는지"가 다 거기 적혀 있다.
  그래서 바꾸는 줄만 찾아서 그 줄만 갈아 끼운다.

★ 저장 전에 반드시 읽어 본다
  고친 YAML 이 실제로 파싱되고 SiteConfig 로 만들어지는지 확인한 뒤에만
  파일에 쓴다. 깨진 설정이 저장되면 그 사이트는 조용히 안 돌기 시작한다.
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

UTC = timezone.utc


# ── 폼에 꺼낼 값들 ────────────────────────────────────────────
#  path: YAML 안의 위치. 점으로 잇는다.
#  kind: 화면이 무슨 입력칸을 그릴지
FIELDS = [
    {"path": "name", "label": "표시 이름", "kind": "text",
     "hint": "화면에 나올 이름입니다 (예: 무신사)", "required": True},
    {"path": "base_url", "label": "사이트 주소", "kind": "url",
     "hint": "맨 앞 주소만. 예: https://www.musinsa.com", "required": True},
    {"path": "schedule.every_hours", "label": "수집 주기", "kind": "hours",
     "hint": "몇 시간마다 돌지. 0 이면 자동으로 안 돕니다.",
     "choices": [[0, "자동 안 함"], [6, "6시간"], [12, "12시간"], [24, "하루"],
                 [48, "이틀"], [168, "일주일"]]},
    {"path": "render.target", "label": "페이지당 목표 개수", "kind": "int",
     "hint": "한 페이지에서 몇 개까지 주울지. 많을수록 오래 걸립니다."},
    {"path": "pace.base_delay", "label": "요청 간격", "kind": "float",
     "hint": "한 번 부르고 몇 초 쉴지. 짧으면 차단당할 수 있습니다.",
     "unit": "초"},
    {"path": "listing_type_default", "label": "가격의 성격", "kind": "choice",
     "hint": "리세일이면 호가/체결가, 커머스면 정가입니다.",
     "choices": [["retail", "정가 판매 (커머스)"], ["ask", "호가 (리세일)"],
                 ["settled", "체결가 (리세일)"]]},
]

# 수집할 페이지 목록 — 따로 다룬다. 줄을 더하고 빼야 해서 모양이 다르다.
PAGES_PATH = "render.pages"


def dig(d: dict, path: str):
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


class SiteForm:
    def __init__(self, config_dir: Path):
        self.dir = Path(config_dir)
        self.backup = self.dir / ".backup"
        self.backup.mkdir(parents=True, exist_ok=True)

    def _path(self, code: str) -> Path:
        if not re.fullmatch(r"[a-z0-9_]{2,30}", code or ""):
            raise ValueError("사이트 코드가 올바르지 않습니다.")
        p = (self.dir / f"{code}.yaml").resolve()
        if self.dir.resolve() not in p.parents:
            raise ValueError("경로가 올바르지 않습니다.")
        return p

    # ── 읽기 ─────────────────────────────────────────────────
    def read(self, code: str) -> dict:
        p = self._path(code)
        if not p.exists():
            return {"ok": False, "error": "그런 사이트가 없습니다."}
        raw = p.read_text(encoding="utf-8")
        try:
            d = yaml.safe_load(raw) or {}
        except yaml.YAMLError as e:
            return {"ok": False, "error": f"설정 파일을 읽지 못했습니다: {e}",
                    "yaml": raw}

        fields = []
        for f in FIELDS:
            v = dig(d, f["path"])
            fields.append({**f, "value": v})

        pages = []
        for pg in (dig(d, PAGES_PATH) or []):
            if isinstance(pg, dict):
                steps = pg.get("steps") or []
                tabs = [s.get("click_text") for s in steps
                        if isinstance(s, dict) and s.get("click_text")]
                pages.append({"label": pg.get("label", ""), "url": pg.get("url", ""),
                              "target": pg.get("target"), "tabs": tabs})

        return {"ok": True, "code": code, "fields": fields, "pages": pages,
                "yaml": raw, "notes": (d.get("notes") or "").strip()[:600],
                "render_on": bool(dig(d, "render.enabled")),
                "seeds": d.get("seeds") or []}

    # ── 쓰기 ─────────────────────────────────────────────────
    def write(self, code: str, values: dict, pages: list | None = None,
              by: str = "") -> dict:
        """폼에서 온 값으로 YAML 의 해당 줄만 갈아 끼운다."""
        p = self._path(code)
        if not p.exists():
            return {"ok": False, "error": "그런 사이트가 없습니다."}
        raw = p.read_text(encoding="utf-8")
        out = raw

        for f in FIELDS:
            if f["path"] not in values:
                continue
            v = values[f["path"]]
            if v is None or v == "":
                continue
            out, changed = _set_scalar(out, f["path"], v)
            if not changed:
                return {"ok": False,
                        "error": f"'{f['label']}' 을 넣을 자리를 못 찾았습니다. "
                                 f"[고급] 에서 직접 고쳐 주세요."}

        if pages is not None:
            out, ok = _set_pages(out, pages)
            if not ok:
                return {"ok": False,
                        "error": "수집할 페이지 목록을 바꾸지 못했습니다. "
                                 "[고급] 에서 직접 고쳐 주세요."}

        # ★ 저장 전에 실제로 읽히는지 본다
        check = validate(out)
        if not check["ok"]:
            return check

        # 직전 것을 남긴다 — 되돌릴 길이 있어야 사람이 겁 없이 고친다
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        shutil.copy(p, self.backup / f"{code}.{stamp}.yaml")
        p.write_text(out, encoding="utf-8")
        return {"ok": True, "code": code, "backup": f"{code}.{stamp}.yaml"}


# ── YAML 한 줄만 갈아 끼우기 ──────────────────────────────────
def _set_scalar(text: str, path: str, value) -> tuple[str, bool]:
    """'render.target: 100' 처럼 한 값만 바꾼다.

    주석을 지키려고 파싱-덤프 대신 줄 단위로 손댄다.
    들여쓰기를 보고 부모 밑에 있는 줄인지 확인한다 —
    같은 이름의 칸이 여러 곳에 있을 수 있어서(예: target) 그냥 찾으면 안 된다.
    """
    parts = path.split(".")
    lines = text.split("\n")
    depth = 0          # 지금 몇 칸 들여쓰기 안을 보고 있나
    idx = 0

    for level, key in enumerate(parts):
        want_last = (level == len(parts) - 1)
        found = -1
        for i in range(idx, len(lines)):
            ln = lines[i]
            if not ln.strip() or ln.lstrip().startswith("#"):
                continue
            ind = len(ln) - len(ln.lstrip())
            if level > 0 and ind <= depth - 2 and i > idx:
                break                      # 부모 블록을 벗어났다
            m = re.match(r"^(\s*)" + re.escape(key) + r"\s*:(.*)$", ln)
            if m and (level == 0 or ind > depth - 2):
                found = i
                if want_last:
                    keep = ""
                    # 줄 끝 주석은 살린다
                    cm = re.search(r"\s+#\s.*$", m.group(2))
                    if cm:
                        keep = cm.group(0)
                    lines[i] = f"{m.group(1)}{key}: {_fmt(value)}{keep}"
                    return "\n".join(lines), True
                depth = ind + 2
                idx = i + 1
                break
        if found < 0:
            return text, False
    return text, False


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    # 특수문자가 있으면 따옴표로 감싼다
    if re.search(r"[:#{}\[\],&*?|<>=!%@`\"']", s) or not s.strip():
        return '"' + s.replace('"', '\\"') + '"'
    return s


def _set_pages(text: str, pages: list) -> tuple[str, bool]:
    """render.pages 목록을 새로 쓴다.

    ★ 두 번 크게 틀렸던 곳이라 고친 이유를 적어 둔다.

    ① 폼에 없는 칸을 날려 먹었다
       처음엔 label·url·steps·target 만 다시 썼더니 `scroll: 40` 이 사라졌다.
       폼은 설정의 일부만 보여 주는 것이지 전부가 아니다.
       **모르는 칸은 건드리지 않고 그대로 옮긴다.**

    ② 뒤따르는 주석 블록을 먹었다
       블록의 끝을 찾을 때 주석 줄을 '내용 없음'으로 보고 건너뛰었더니,
       목록 아래에 있던 설명 주석 20여 줄이 목록의 일부로 잡혀 지워졌다.
       주석도 들여쓰기가 있다. **칸 밖에 있는 주석은 블록의 끝이다.**
    """
    lines = text.split("\n")
    start = -1
    indent = 2
    for i, ln in enumerate(lines):
        m = re.match(r"^(\s*)pages\s*:\s*$", ln)
        if m:
            start = i
            indent = len(m.group(1))
            break
    if start < 0:
        return text, False

    end = len(lines)
    for i in range(start + 1, len(lines)):
        ln = lines[i]
        if not ln.strip():
            continue                       # 빈 줄은 판단 보류
        ind = len(ln) - len(ln.lstrip())
        # ★ 주석도 들여쓰기를 본다. 칸 밖으로 나온 주석은 목록이 끝났다는 뜻이다.
        if ind <= indent:
            end = i
            break

    # 원래 있던 항목들을 읽어 둔다 — 폼이 모르는 칸을 지키려고
    block = "\n".join(lines[start + 1:end])
    try:
        old = yaml.safe_load(block) or []
    except yaml.YAMLError:
        old = []
    old_by_label = {}
    for o in old:
        if isinstance(o, dict) and o.get("label"):
            old_by_label[str(o["label"])] = o

    FORM_KEYS = {"label", "url", "steps", "target"}
    body = []
    pad = " " * (indent + 2)
    for pg in pages:
        label = str(pg.get("label") or "").strip()
        url = str(pg.get("url") or "").strip()
        if not label or not url:
            continue
        body.append(f'{pad}- label: {_fmt(label)}')
        body.append(f'{pad}  url: {_fmt(url)}')
        tabs = [t for t in (pg.get("tabs") or []) if str(t).strip()]
        if tabs:
            steps = ", ".join("{ click_text: %s }" % _fmt(t) for t in tabs)
            body.append(f'{pad}  steps: [{steps}]')
        if pg.get("target"):
            body.append(f'{pad}  target: {int(pg["target"])}')
        # ★ 폼이 모르는 칸을 그대로 옮긴다 (scroll, wait_ms 같은 것들)
        for k, v in (old_by_label.get(label) or {}).items():
            if k in FORM_KEYS:
                continue
            body.append(f'{pad}  {k}: {_fmt(v)}')
    if not body:
        body = [f"{pad}[]"]

    return "\n".join(lines[:start + 1] + body + lines[end:]), True


def validate(text: str) -> dict:
    """저장해도 되는 설정인가.

    YAML 문법만 보는 게 아니라 SiteConfig 로 만들어지는지까지 본다 —
    문법은 맞는데 필수 칸이 빠진 경우가 훨씬 흔하다.
    """
    try:
        d = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" ({mark.line + 1}번째 줄)" if mark else ""
        return {"ok": False,
                "error": f"설정 형식이 맞지 않습니다{where}. "
                         f"들여쓰기나 따옴표를 확인해 주세요."}
    if not isinstance(d, dict):
        return {"ok": False, "error": "설정이 비어 있습니다."}
    for need in ("code", "name", "base_url"):
        if not d.get(need):
            return {"ok": False, "error": f"'{need}' 가 비어 있습니다."}
    if not str(d["base_url"]).startswith(("http://", "https://")):
        return {"ok": False,
                "error": "사이트 주소는 http:// 또는 https:// 로 시작해야 합니다."}
    return {"ok": True}


def set_plan_cell(path, index: int, code: str) -> dict:
    """manual_plan.cells 의 index 번째 칸에서 code 만 갈아 끼운다.

    ★ 파싱해서 다시 쓰면 안 된다
      yaml.safe_load → yaml.dump 를 하면 주석이 통째로 사라진다.
      이 파일은 주석이 본문만큼 중요하다 (왜 자동수집을 안 하는지,
      어떤 값이 확인된 것인지가 전부 주석에 있다).
      그래서 **그 한 줄만** 찾아서 바꾼다.
    """
    from pathlib import Path
    p = Path(path)
    lines = p.read_text(encoding="utf-8").split("\n")

    # cells: 아래의 '- {' 로 시작하는 줄들을 순서대로 센다
    start = None
    for i, ln in enumerate(lines):
        if re.match(r"^\s*cells:\s*$", ln):
            start = i
            break
    if start is None:
        return {"ok": False, "error": "설정에서 cells 를 못 찾았습니다."}

    n, target = -1, None
    for i in range(start + 1, len(lines)):
        ln = lines[i]
        if ln.strip() and not ln.startswith((" ", "\t")):
            break                                  # 블록이 끝났다
        if re.match(r"^\s*-\s", ln):
            n += 1
            if n == index:
                target = i
                break
    if target is None:
        return {"ok": False, "error": f"{index}번째 칸이 없습니다."}

    ln = lines[target]
    if "code:" not in ln:
        return {"ok": False, "error": "그 줄에 code 가 없습니다."}
    new = re.sub(r'code:\s*"?[^,}"\s]*"?', f'code: "{code}"', ln, count=1)
    # 고쳤으면 '확인됨' 으로 올린다 — 사람이 실제 주소를 보고 넣은 값이다
    if "verified:" in new:
        new = re.sub(r"verified:\s*\w+", "verified: true", new, count=1)
    lines[target] = new

    body = "\n".join(lines)
    try:
        got = yaml.safe_load(body)                  # 망가뜨리지 않았는지 확인
        cells = ((got or {}).get("manual_plan") or {}).get("cells") or []
        if str(cells[index]["code"]) != str(code):
            return {"ok": False, "error": "고친 값이 안 맞습니다. 되돌립니다."}
    except Exception as e:
        return {"ok": False, "error": f"설정이 깨질 뻔했습니다: {e}"}

    p.write_text(body, encoding="utf-8")
    return {"ok": True}
