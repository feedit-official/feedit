"""모델과 실제 DB 가 어긋나도 API 가 죽지 않는지.

★ 2026-09-07 에 실제로 난 일
    GET /api/trend?term=발레코어  →  500
    ProgrammingError: column dictionary_term.normalized_name does not exist

  모델·마이그레이션에는 있는데 RDS 표에는 없었다. Django 는
  "No migrations to apply" 라고 하니 아무도 모른 채 지나간다.
  게다가 우리 API 는 그 칸을 **쓰지도 않는다** — select_related 가
  DictionaryTerm 의 모든 칸을 SELECT 해서 딸려 들어간 것뿐이다.

  그래서 두 가지를 지킨다:
    ① 쓰는 칸만 집어 온다(values). 남의 칸 때문에 죽지 않는다.
    ② health 가 어긋남을 미리 짚어 준다. 500 을 만나기 전에 안다.

여기서는 **실제로 컬럼을 지운 DB** 로 확인한다. 흉내가 아니다.

돌리는 법:  python3 backend/apps/api/tests_mismatch.py   (SQLite 로도 된다)
"""
import os, sqlite3, django, json
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sqlite_settings")
django.setup()
from django.test import Client
from apps.core.models import DictionaryTerm, TermMetricDaily

from django.conf import settings
DB = settings.DATABASES["default"]["NAME"]
tm = DictionaryTerm.objects.create(term_type="STYLE", canonical_name="발레코어",
                                   normalized_name="발레코어", status="ACTIVE")
TermMetricDaily.objects.create(term=tm, source=None, metric_date="2026-09-01",
                               mention_count=12, document_count=3, source_count=2,
                               temp=61.2, momentum=1.4, level=55, ma7=9, ma28=6,
                               metric_version="v2", metrics={"share_pct": 7.4})

# 컬럼을 실제로 지운다 (SQLite 3.35+ DROP COLUMN)
c = sqlite3.connect(DB)
# SQLite 는 UNIQUE 제약이 걸린 칸을 DROP 못 한다. 표를 다시 만들어 빼낸다.
cols = [r[1] for r in c.execute('PRAGMA table_info(dictionary_dictionary_term)')]
keep = [x for x in cols if x != 'normalized_name']
c.executescript(f'''
  PRAGMA foreign_keys=off;
  CREATE TABLE _t AS SELECT {",".join(keep)} FROM dictionary_dictionary_term;
  DROP TABLE dictionary_dictionary_term;
  ALTER TABLE _t RENAME TO dictionary_dictionary_term;
  PRAGMA foreign_keys=on;
''')
c.commit(); c.close()
cols = [r[1] for r in sqlite3.connect(DB).execute('PRAGMA table_info(dictionary_dictionary_term)')]
print("normalized_name 이 표에 있나:", 'normalized_name' in cols, "(없어야 재현된다)")

def _a(c, m=""):
    if not c: raise AssertionError(m)

cl = Client()
ok = bad = 0
def t(n, f):
    global ok, bad
    try: f(); print("✅", n); ok += 1
    except Exception as e: print("❌", n, "\n   ", type(e).__name__, str(e)[:160]); bad += 1

def get(u):
    r = cl.get(u); assert r.status_code == 200, f"HTTP {r.status_code}"
    return json.loads(r.content)

t("★ 컬럼이 없어도 trend 가 500 이 아니다", lambda: (
    (d := get("/api/trend?term=발레코어&days=400")),
    _a(d["status"] == "ok", d),
    _a(d["data"]["series"][-1]["temp"] == 61.2, "온도가 실려야 한다"),
    _a(d["data"]["series"][-1].get("share_pct") == 7.4, "metrics JSON 도 꺼내야 한다")))

t("★ health 가 어긋남을 짚어 준다", lambda: (
    (d := get("/api/health")),
    _a(d["column_mismatch"], "어긋남을 못 잡았다"),
    _a(any("normalized_name" in (v.get("missing") or [])
           for v in d["column_mismatch"].values()), d["column_mismatch"]),
    _a("모델과 실제 DB 가 어긋납니다" in d["verdict"], d["verdict"]),
    _a("migrate" in d["verdict"], "무엇을 하면 되는지 말해야 한다")))

t("assoc 도 안 죽는다", lambda: (
    (d := get("/api/assoc?term=발레코어")), _a(d["status"] == "empty", d)))

t("products 도 안 죽는다", lambda: (
    (d := get("/api/products")), _a(d["status"] == "empty", d)))

t("terms 도 안 죽는다", lambda: (
    (d := get("/api/trend")), _a(d["status"] in ("ok", "empty"), d)))


print(f"\n{ok}개 통과 · {bad}개 실패")
raise SystemExit(1 if bad else 0)
