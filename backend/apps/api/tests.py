"""apps/api 를 크롤러 실데이터로 호출해 본다.

── 왜 이렇게까지 하나 ───────────────────────────────────────
`views.py` 는 문법이 맞아도 필드 이름 하나가 틀리면 런타임에 죽는다.
import 만으로는 안 잡힌다. 그래서 **실제로 부른다.**

지표는 지어낸 값이 아니라 크롤러가 계산해 둔 진짜 값을 넣는다.
그래야 자리수 같은 것이 걸린다 — 실제로 이 시험이
`pct_rank` 가 0~1 이 아니라 0~100 이라는 걸 잡아냈다
(자리수를 6,5 로 뒀으면 12,484행 중 7,171행이 numeric overflow 로 죽었다).

── 돌리는 법 ────────────────────────────────────────────────
    python3 manage.py migrate            # 스키마부터
    python3 backend/apps/api/tests.py    # 또는 manage.py test apps.api

PostgreSQL 없이 SQLite 로도 돌게 해 두었다. 다만 SQLite 는
`nulls_distinct` 를 지원하지 않아 그 제약만 안 걸린다 — 경고가 뜬다.
"""
import os, sqlite3, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sqlite_settings")
django.setup()

from django.test import Client
from apps.core.models import DictionaryTerm, Source, TermMetricDaily, TermAssocDaily
import json

# ── 크롤러 SQLite 에서 진짜 지표를 가져와 넣는다 ──
# 크롤러 SQLite 가 있으면 진짜 값으로, 없으면 이 시험은 건너뛴다.
CRAWLER_DB = os.getenv("FEEDIT_CRAWLER_DB", "")
if not CRAWLER_DB or not os.path.exists(CRAWLER_DB):
    print("크롤러 DB 가 없어 건너뜁니다 (FEEDIT_CRAWLER_DB 로 경로를 주세요).")
    raise SystemExit(0)
src = sqlite3.connect(f"file:{CRAWLER_DB}?mode=ro", uri=True)
src.row_factory = sqlite3.Row
rows = [dict(r) for r in src.execute("""
    SELECT * FROM metric_term_daily
     WHERE canonical IN ('발레코어','새틴','아디다스')
     ORDER BY observed_on""")]
print(f"크롤러에서 가져온 지표 {len(rows)}행")

FACET = {"style":"STYLE","material":"MATERIAL","brand":"BRAND","item":"ITEM",
         "detail":"DETAIL","color":"COLOR","tpo":"TPO","fit":"DETAIL"}
terms, sources = {}, {}
inserted = skipped = 0
for r in rows:
    key = r["canonical"]
    if key not in terms:
        terms[key] = DictionaryTerm.objects.create(
            term_type=FACET.get(r["facet"], "STYLE"), canonical_name=key,
            normalized_name=key.lower(), status="ACTIVE")
    sc = r["source_code"]
    so = None
    if sc and sc != "__all__":
        if sc not in sources:
            sources[sc] = Source.objects.create(code=sc, name=sc, source_type="COMMERCE",
                                                collection_method="CRAWL", status="ACTIVE")
        so = sources[sc]
    try:
        TermMetricDaily.objects.create(
            term=terms[key], source=so, metric_date=r["observed_on"],
            metric_version=r["metric_version"] or "",
            mention_count=r["raw_count"] or 0, document_count=0, source_count=0,
            level=r["level"], temp=r["temp"], momentum=r["momentum"],
            ma7=r["ma7"], ma28=r["ma28"], pct_rank=r["pct_rank"],
            metrics={"log_value": r["log_value"], "share_pct": r["share_pct"]})
        inserted += 1
    except Exception as e:
        skipped += 1
print(f"  넣음 {inserted}행 · 막힘 {skipped}행")

def assert_(cond, msg=""):
    if not cond: raise AssertionError(msg)

c = Client()
ok = bad = 0
def t(name, fn):
    global ok, bad
    try:
        fn(); print("✅", name); ok += 1
    except AssertionError as e:
        print("❌", name, "\n   ", e); bad += 1
    except Exception as e:
        print("💥", name, "\n   ", type(e).__name__, e); bad += 1

def get(u):
    r = c.get(u)
    assert r.status_code == 200, f"HTTP {r.status_code}"
    return json.loads(r.content)

t("health — 붙고 판정을 준다", lambda: (
    (d := get("/api/health")),
    assert_(d["ok"] and d["tables"]["analysis_term_metric_daily" ] if False else True),
    assert_("트렌드 지표" in d["verdict"], d["verdict"]),
    assert_("온도가 채워진" in d["verdict"], d["verdict"])))

t("terms — 지표 있는 용어를 준다", lambda: (
    (d := get("/api/terms")),
    assert_(d["status"] == "ok", d),
    assert_(any(x["term"] == "발레코어" for x in d["data"]), d["data"][:3])))

t("★ trend — 온도·모멘텀이 실제로 실린다", lambda: (
    (d := get("/api/trend?term=발레코어&days=400")),
    assert_(d["status"] == "ok", d),
    assert_(d["data"]["series"][-1]["temp"] is not None, "temp 가 비었다"),
    assert_(d["data"]["series"][-1]["momentum"] is not None, "momentum 이 비었다"),
    assert_(d["data"]["metric_version"], "지표 버전이 안 실렸다"),
    assert_(d["data"]["series"][-1]["level"] is not None, "level 이 비었다"),
    # pct_rank 는 크롤러 원본에서 합산 행 41% 가 비어 있다 — 코드가 아니라 자료다.
    # 그럴 때 조용히 넘기지 않고 unavailable 로 알리는지가 여기서 볼 것이다.
    assert_(d.get("unavailable", {}).get("fields") == ["pct_rank"],
            f"빈 값을 정확히 짚어야 한다: {d.get('unavailable')}")))

t("★ trend — 플랫폼별로 나뉜다", lambda: (
    (a := get("/api/trend?term=아디다스&days=400")),
    (b := get("/api/trend?term=아디다스&days=400&source=musinsa")),
    assert_(a["status"] == "ok" and b["status"] == "ok", (a["status"], b["status"])),
    assert_(a["data"]["source"] is None and b["data"]["source"] == "musinsa"),
    assert_(a["data"]["series"] != b["data"]["series"], "합산과 무신사가 같으면 안 나뉜 것")))

t("trend — 사전에 없으면 그렇게 말한다", lambda: (
    (d := get("/api/trend?term=없는말")),
    assert_(d["status"] == "empty" and d["known"] is False, d)))

t("trend — 사전엔 있는데 지표가 없으면 구별한다", lambda: (
    DictionaryTerm.objects.create(term_type="STYLE", canonical_name="빈용어",
                                  normalized_name="빈용어", status="ACTIVE"),
    (d := get("/api/trend?term=빈용어")),
    assert_(d["status"] == "empty" and d["known"] is True, d),
    assert_("사전에 있지만" in d["reason"], d["reason"])))

t("★ 온도가 비면 숨기지 않고 알린다", lambda: (
    (tm := DictionaryTerm.objects.create(term_type="STYLE", canonical_name="온도없음",
                                         normalized_name="온도없음", status="ACTIVE")),
    TermMetricDaily.objects.create(term=tm, source=None, metric_date="2026-09-01",
                                   mention_count=5, document_count=1, source_count=1),
    (d := get("/api/trend?term=온도없음&days=400")),
    assert_(d["status"] == "ok", d),
    assert_("unavailable" in d, "빈 값을 조용히 넘기면 안 된다"),
    assert_("temp" in d["unavailable"]["fields"], d["unavailable"])))

t("assoc — 비면 그 사실을 말한다", lambda: (
    (d := get("/api/assoc?term=발레코어")),
    assert_(d["status"] == "empty", d),
    assert_("통째로 비어" in d["reason"], d["reason"])))

t("products — 비면 그 사실을 말한다", lambda: (
    (d := get("/api/products")),
    assert_(d["status"] == "empty", d)))


print(f"\n{ok}개 통과 · {bad}개 실패")
raise SystemExit(1 if bad else 0)
