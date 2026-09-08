"""사전(용어 + 브랜드)이 화면까지 제대로 건너가는지.

★ 2026-09-08 에 실제로 난 일
    검색창에 "스투시" → "스투시를 사전에서 찾지 못했습니다"
  그런데 스투시는 **사전에 있다.** RDS 기준으로 2,775개 브랜드 중 하나다.

  왜 그랬나 — 브랜드가 다른 표에 살기 때문이다.
    dictionary_term  : 스타일·아이템·소재·색·디테일·TPO   (395행)
    dictionary.brand : 브랜드                              (2,775행)
  API 는 `DictionaryTerm` 만 보고 "없다"고 단정했다. 거짓말이었다.

  거짓말과 사실은 사용자가 할 일이 다르다.
    "사전에 없다"       → 다른 말로 다시 쳐야 한다
    "사전엔 있는데 지표가 없다" → 기다리거나 수집을 켜야 한다
  두 번째를 첫 번째로 말하면 사용자는 되지도 않을 일을 계속 한다.

★ 여기서 함께 잡힌 것
    Brand 에는 `canonical_name` 이 없다. `name` 이다 (0014 가 지웠다).
    그걸 모르고 쓴 자리가 세 군데 있었고, 그중 하나가 상품 브랜드 필터였다.
    표마다 이름 붙이는 규칙이 다르면 이런 게 조용히 숨는다 — 그래서
    상품을 한글·영문 브랜드명으로 거르는 것까지 여기서 확인한다.

돌리는 법:  python3 backend/apps/api/tests_dictionary.py   (SQLite 로도 된다)
"""
import os, json, django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sqlite_settings")
django.setup()

from django.test import Client
from apps.core.models import Brand, DictionaryTerm, Product

# 여러 번 돌려도 같은 결과가 나오게 — 먼저 비우고 넣는다.
DictionaryTerm.objects.all().delete()
Brand.objects.all().delete()
Product.objects.all().delete()

DictionaryTerm.objects.create(term_type="STYLE", canonical_name="발레코어",
                              normalized_name="발레코어", status="ACTIVE")
DictionaryTerm.objects.create(term_type="MATERIAL", canonical_name="새틴",
                              normalized_name="새틴", status="ACTIVE")
st = Brand.objects.create(name="스투시", english_name="Stussy",
                          brand_code="BRAND_STUSSY", status="ACTIVE")
Brand.objects.create(name="키르시", english_name="KIRSH",
                     brand_code="BRAND_KIRSH", status="ACTIVE")
Product.objects.create(brand=st, canonical_name="스투시 8볼 후드",
                       normalized_name="스투시8볼후드", status="ACTIVE")

c = Client()
ok = bad = 0


def _a(x, m=""):
    if not x:
        raise AssertionError(m)


def t(n, f):
    global ok, bad
    try:
        f()
        print("✅", n)
        ok += 1
    except Exception as e:
        print("❌", n, "\n   ", type(e).__name__, str(e)[:200])
        bad += 1


def get(u):
    r = c.get(u)
    _a(r.status_code == 200, f"HTTP {r.status_code}")
    return json.loads(r.content)


t("★ 사전에 용어와 브랜드가 함께 나온다", lambda: (
    (d := get("/api/dictionary")), _a(d["status"] == "ok", d),
    (lb := {x["label"] for x in d["data"]}),
    _a("발레코어" in lb and "스투시" in lb, sorted(lb)),
    _a(d["counts"].get("브랜드") == 2, d["counts"])))

t("어디서 온 말인지 표시한다", lambda: (
    (d := get("/api/dictionary")), (m := {x["label"]: x for x in d["data"]}),
    _a(m["스투시"]["kind"] == "brand"), _a(m["발레코어"]["kind"] == "term"),
    _a(m["새틴"]["facet"] == "소재", m["새틴"])))

t("★ 브랜드는 '사전에 없다'고 하지 않는다", lambda: (
    (d := get("/api/trend?term=스투시")), _a(d["status"] == "empty", d),
    _a(d["known"] is True, "브랜드 사전에 있으니 known"),
    _a(d["found_in"] == "brand", d),
    _a("브랜드 사전에는 있지만" in d["reason"], d["reason"]),
    _a("찾지 못했습니다" not in d["reason"], "거짓말하면 안 된다")))

t("용어인데 지표만 없으면 그렇게 말한다", lambda: (
    (d := get("/api/trend?term=발레코어")), _a(d["found_in"] == "term", d),
    _a("측정된 지표가 없습니다" in d["reason"], d["reason"])))

t("정말 없는 말은 없다고 한다", lambda: (
    (d := get("/api/trend?term=zzz없는말")),
    _a(d["known"] is False and d["found_in"] is None, d),
    _a("찾지 못했습니다" in d["reason"], d["reason"])))

t("영문 이름도 함께 준다", lambda: (
    (d := get("/api/dictionary")), (m := {x["label"]: x for x in d["data"]}),
    _a(m["스투시"]["en"] == "Stussy", m["스투시"])))

# ── Brand.name / Brand.english_name — canonical_name 이 아니다 ──
t("★ 상품을 한글 브랜드명으로 거를 수 있다", lambda: (
    (d := get("/api/products?brand=스투시")), _a(d["status"] == "ok", d),
    _a(d["data"]["count"] == 1, d),
    _a(d["data"]["items"][0]["brand"] == "스투시", d["data"]["items"][0])))

t("★ 영문 브랜드명으로도 거를 수 있다", lambda: (
    (d := get("/api/products?brand=Stussy")), _a(d["status"] == "ok", d),
    _a(d["data"]["count"] == 1, d)))

print(f"\n{ok}개 통과 · {bad}개 실패")
raise SystemExit(1 if bad else 0)
