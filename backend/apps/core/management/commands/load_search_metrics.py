"""검색량·검색 트렌드 CSV → RDS 적재 (2026-09-21)

팀원이 만든 navergoogle 파이프라인의 **전처리 결과**를 FEEDiT 스키마로 넣는다.

── 왜 팀원 로더(storage/rds_loader.py)를 안 쓰나 ──────────────
그 로더는 스키마 없는 `keyword_monthly_volume` · `keyword_trend` 표를
제 손으로 CREATE 해서 넣는다. term_id 도 없이 keyword 문자열로만 키를 잡는다.
그러면 FEEDiT 의 dictionary_term 과 영영 못 붙어 사전·연관어·온도와 따로 논다.
여기서는 analysis 스키마의 표에 **term_id 를 붙여** 넣는다.

── 어느 파일이 어디로 가나 ────────────────────────────────────
  term_volume_wide.csv                → term_search_metric_monthly  (N1·K1 절대 검색량)
  processed_naver_monthly_absolute.csv→ term_search_metric_monthly  (+ PC/모바일/경쟁도 N4)
  term_monthly_trend.csv              → term_search_metric_monthly  (K2 구글 12개월)
  processed_google_trend_absolute.csv → term_search_trend           (G1 주간 상대+추정절대)
  raw_google_region.csv               → term_search_region          (G5 시·도별)

── 쓰는 법 ────────────────────────────────────────────────────
  python manage.py load_search_metrics --dir backend/collection/search_volume/samples --dry-run
  python manage.py load_search_metrics --dir backend/collection/search_volume/samples
  python manage.py load_search_metrics --dir backend/collection/search_volume/output/processed/20260914_180050

--dry-run 은 DB 를 건드리지 않고 '몇 줄이 붙고 몇 줄이 사전에서 떨어지는지'만 센다.
먼저 이걸로 매칭률을 보고 넣는 걸 권한다 — 매칭이 낮으면 사전 쪽을 먼저 고쳐야 한다.
"""

from __future__ import annotations

import csv
import os
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import (
    DictionaryTerm,
    Source,
    TermAlias,
    TermSearchMetricMonthly,
    TermSearchRegion,
    TermSearchTrend,
)

METRIC_VERSION = "feedit-search-v1"

# 검색 플랫폼 — 언급(커머스·유튜브)과 섞이지 않게 SEARCH 타입으로 따로 둔다.
SOURCE_SPECS = {
    "naver": ("NAVER_SEARCH", "네이버 검색"),
    "google": ("GOOGLE_SEARCH", "구글 검색"),
}


def _norm(value) -> str:
    """사전 매칭용 정규화 — 공백 제거 + 소문자."""
    return str(value or "").replace(" ", "").strip().lower()


def _int(value):
    try:
        if value in ("", None):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _dec(value):
    try:
        if value in ("", None):
            return None
        return Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        return None


def _read(path):
    """BOM 붙은 CSV 대응 (팀원 산출물이 utf-8-sig 로 저장된다)."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        yield from csv.DictReader(fh)


class Command(BaseCommand):
    help = "검색량·검색 트렌드 CSV 를 analysis 스키마에 적재한다"

    def add_arguments(self, parser):
        parser.add_argument("--dir", required=True,
                            help="전처리 결과 폴더 (processed/<타임스탬프> 또는 samples)")
        parser.add_argument("--month", default=None,
                            help="월 단위 표의 기준 월 (YYYY-MM). 없으면 이번 달 1일")
        parser.add_argument("--dry-run", action="store_true",
                            help="DB 를 건드리지 않고 매칭률만 센다")
        parser.add_argument("--metric-version", default=METRIC_VERSION)

    # ──────────────────────────────────────────────────────────
    #  사전 매칭
    # ──────────────────────────────────────────────────────────

    def _build_term_map(self, base_dir) -> dict:
        """검색 키워드 → term_id.

        CSV 에 term_id 가 이미 있는 파일도 있지만(무신사 전처리 산출물),
        term_monthly_trend 처럼 keyword 문자열만 있는 것도 있어 표를 만들어 둔다.
        사전(canonical·normalized·영문) + 별칭 + keywords/ CSV 의
        search_keyword 전개("코트|여성코트|롱코트")까지 전부 받는다.
        """
        mapping = {}
        for tid, canonical, normalized, english in DictionaryTerm.objects.values_list(
            "id", "canonical_name", "normalized_name", "english_name"
        ):
            for name in (canonical, normalized, english):
                key = _norm(name)
                if key:
                    mapping.setdefault(key, tid)

        for tid, alias in TermAlias.objects.values_list("term_id", "alias"):
            key = _norm(alias)
            if key:
                mapping.setdefault(key, tid)

        # keywords/*.csv 의 search_keyword 전개 — "롱코트" 같은 변형을 코트로 붙인다
        kw_dir = os.path.join(os.path.dirname(base_dir.rstrip("/")), "keywords")
        if not os.path.isdir(kw_dir):
            kw_dir = os.path.join(base_dir, "..", "keywords")
        if os.path.isdir(kw_dir):
            for name in sorted(os.listdir(kw_dir)):
                if not name.endswith(".csv"):
                    continue
                try:
                    for row in _read(os.path.join(kw_dir, name)):
                        tid = _int(row.get("id"))
                        raw = row.get("search_keyword") or row.get("canonical_name") or ""
                        if not tid:
                            continue
                        for piece in str(raw).split("|"):
                            key = _norm(piece)
                            if key:
                                mapping.setdefault(key, tid)
                except Exception as exc:      # noqa: BLE001
                    self.stderr.write(f"  (경고) {name} 읽기 실패: {exc}")
        return mapping

    def _sources(self, dry_run):
        out = {}
        for platform, (code, label) in SOURCE_SPECS.items():
            if dry_run:
                row = Source.objects.filter(code=code).first()
                out[platform] = row
                continue
            row, created = Source.objects.get_or_create(
                code=code,
                defaults={
                    "name": label,
                    "source_type": Source.SourceType.SEARCH,
                    "collection_method": Source.CollectionMethod.API,
                    "status": Source.Status.ACTIVE,
                },
            )
            if created:
                self.stdout.write(f"  + Source 생성: {code} ({label})")
            out[platform] = row
        return out

    # ──────────────────────────────────────────────────────────
    #  적재
    # ──────────────────────────────────────────────────────────

    def handle(self, *args, **opts):
        base = os.path.abspath(opts["dir"])
        if not os.path.isdir(base):
            raise CommandError(f"폴더가 없습니다: {base}")

        dry = opts["dry_run"]
        version = opts["metric_version"]
        if opts["month"]:
            try:
                month = datetime.strptime(opts["month"] + "-01", "%Y-%m-%d").date()
            except ValueError:
                raise CommandError("--month 은 YYYY-MM 형식입니다.")
        else:
            today = date.today()
            month = date(today.year, today.month, 1)

        self.stdout.write(f"📂 {base}")
        self.stdout.write(f"   기준 월 {month} · 버전 {version}"
                          + ("  [DRY-RUN — 쓰지 않습니다]" if dry else ""))

        terms = self._build_term_map(base)
        self.stdout.write(f"🔎 사전 매칭표 {len(terms):,}개 키")
        sources = self._sources(dry)

        self.miss = defaultdict(int)     # 사전에서 떨어진 키워드
        summary = []

        def run(filename, fn):
            path = os.path.join(base, filename)
            if not os.path.exists(path):
                self.stdout.write(f"   – {filename} 없음, 건너뜀")
                return
            hit, missed, rows = fn(path, terms, sources, month, version, dry)
            summary.append((filename, rows, hit, missed))
            rate = (hit / rows * 100) if rows else 0
            self.stdout.write(
                f"   ✓ {filename}: {rows:,}행 → 매칭 {hit:,} ({rate:.1f}%) · 미매칭 {missed:,}")

        run("term_volume_wide.csv", self.load_volume_wide)
        run("processed_naver_monthly_absolute.csv", self.load_naver_monthly)
        run("term_monthly_trend.csv", self.load_monthly_trend)
        run("processed_google_trend_absolute.csv", self.load_google_trend)
        run("raw_google_region.csv", self.load_region)

        self.stdout.write("\n" + "─" * 56)
        for name, rows, hit, missed in summary:
            self.stdout.write(f"  {name:<40} {hit:>7,} / {rows:,}")
        if self.miss:
            top = sorted(self.miss.items(), key=lambda kv: -kv[1])[:15]
            self.stdout.write("\n  사전에서 못 찾은 키워드 상위 15개 "
                              f"(총 {len(self.miss)}종):")
            self.stdout.write("    " + ", ".join(f"{k}({v})" for k, v in top))
            self.stdout.write("    → 사전에 없는 말이면 term_discovery 후보로 돌리고,")
            self.stdout.write("      있는데 못 붙은 거면 TermAlias 에 별칭을 넣어 주세요.")
        if dry:
            self.stdout.write("\n  [DRY-RUN] 아무것도 쓰지 않았습니다.")
        self.stdout.write("─" * 56)

    # ── 공용 업서트 ───────────────────────────────────────────

    def _upsert(self, model, objects, unique_fields, update_fields, dry):
        if dry or not objects:
            return len(objects)
        written = 0
        with transaction.atomic():
            for i in range(0, len(objects), 1000):
                chunk = objects[i:i + 1000]
                model.objects.bulk_create(
                    chunk,
                    update_conflicts=True,
                    unique_fields=unique_fields,
                    update_fields=update_fields,
                )
                written += len(chunk)
        return written

    def _term_id(self, row, terms, *keys):
        """행에서 term_id 를 찾는다. 칼럼에 있으면 그걸 쓰고, 없으면 키워드로 붙인다."""
        direct = _int(row.get("term_id"))
        if direct:
            return direct
        for key in keys:
            tid = terms.get(_norm(row.get(key)))
            if tid:
                return tid
        return None

    # ── ① term_volume_wide.csv → 월간 절대 검색량 ─────────────

    def load_volume_wide(self, path, terms, sources, month, version, dry):
        hit, missed, rows = 0, 0, 0
        agg = {}                     # (term, platform) → 합계. term 당 1행이 보장 안 돼도 안 터지게.
        for row in _read(path):
            rows += 1
            tid = self._term_id(row, terms, "keyword", "english_name")
            if not tid:
                missed += 1
                self.miss[row.get("keyword", "?")] += 1
                continue
            hit += 1
            for platform, column in (("naver", "naver_volume"), ("google", "google_volume")):
                volume = _int(row.get(column))
                if volume is None or sources.get(platform) is None:
                    continue
                key = (tid, platform)
                agg[key] = agg.get(key, 0) + volume

        objs = [
            TermSearchMetricMonthly(
                term_id=tid, source=sources[platform], metric_month=month,
                search_volume=volume, data_type="monthly_absolute",
                metric_version=version,
            )
            for (tid, platform), volume in agg.items()
        ]
        self._upsert(
            TermSearchMetricMonthly, objs,
            ["term", "source", "metric_month", "metric_version"],
            ["search_volume", "data_type"], dry)
        return hit, missed, rows

    # ── ② 네이버 월간 (PC/모바일/경쟁도 포함) ─────────────────

    def load_naver_monthly(self, path, terms, sources, month, version, dry):
        src = sources.get("naver")
        objs, hit, missed, rows = [], 0, 0, 0
        # 같은 term 에 변형 키워드가 여러 줄이면 합산한다 (코트 ← 롱코트 + 여성코트)
        agg = {}
        for row in _read(path):
            rows += 1
            tid = self._term_id(row, terms, "matched_keyword", "keyword")
            if not tid or src is None:
                missed += 1
                self.miss[row.get("matched_keyword") or row.get("keyword", "?")] += 1
                continue
            hit += 1
            cur = agg.setdefault(tid, {"total": 0, "pc": 0, "mo": 0, "comp": None})
            cur["total"] += _int(row.get("total_search_volume")) or 0
            cur["pc"] += _int(row.get("pc_search_volume")) or 0
            cur["mo"] += _int(row.get("mobile_search_volume")) or 0
            # 경쟁도는 대표 키워드(1순위)의 것을 쓴다
            if cur["comp"] is None and str(row.get("keyword_rank") or "1") == "1":
                cur["comp"] = (row.get("competition") or "").strip() or None

        for tid, v in agg.items():
            objs.append(TermSearchMetricMonthly(
                term_id=tid, source=src, metric_month=month,
                search_volume=v["total"], pc_volume=v["pc"], mobile_volume=v["mo"],
                competition=v["comp"], data_type="monthly_absolute",
                metric_version=version,
            ))
        self._upsert(
            TermSearchMetricMonthly, objs,
            ["term", "source", "metric_month", "metric_version"],
            ["search_volume", "pc_volume", "mobile_volume", "competition", "data_type"], dry)
        return hit, missed, rows

    # ── ③ 구글 12개월 시계열 → 월간 표 (K2) ───────────────────

    def load_monthly_trend(self, path, terms, sources, month, version, dry):
        """★ 반드시 (term, 월)로 합쳐서 넣는다.

        이 CSV 는 term 이 아니라 **검색 키워드** 단위다. 코트·롱코트·여성코트가
        전부 term 157(코트) 로 붙으므로 같은 (term, 월) 이 여러 줄 나온다.
        실측: 5,724행 → 고유 (term, 월) 3,216개.
        그대로 bulk_create(update_conflicts=True) 하면 포스트그레스가
        "ON CONFLICT DO UPDATE command cannot affect row a second time" 로 죽는다
        — 한 INSERT 안에 같은 충돌키가 두 번 들어가기 때문이다.
        검색량은 절대값이라 변형 키워드끼리 **더하는 게** 맞다.
        (상대지수인 ratio 는 더하면 안 된다 — 그쪽은 대표 하나만 남긴다.)
        """
        src = sources.get("google")
        hit, missed, rows = 0, 0, 0
        agg = {}
        for row in _read(path):
            rows += 1
            tid = self._term_id(row, terms, "keyword")
            ym = str(row.get("year_month") or "").strip()
            if not tid or src is None or len(ym) != 7:
                missed += 1
                self.miss[row.get("keyword", "?")] += 1
                continue
            try:
                metric_month = datetime.strptime(ym + "-01", "%Y-%m-%d").date()
            except ValueError:
                missed += 1
                continue
            hit += 1
            key = (tid, metric_month)
            agg[key] = agg.get(key, 0) + (_int(row.get("volume")) or 0)

        objs = [
            TermSearchMetricMonthly(
                term_id=tid, source=src, metric_month=metric_month,
                search_volume=volume, data_type="monthly_absolute",
                metric_version=version,
            )
            for (tid, metric_month), volume in agg.items()
        ]
        self._upsert(
            TermSearchMetricMonthly, objs,
            ["term", "source", "metric_month", "metric_version"],
            ["search_volume", "data_type"], dry)
        return hit, missed, rows

    # ── ④ 구글 주간 상대지수 → 검색 시계열 (G1) ───────────────

    def load_google_trend(self, path, terms, sources, month, version, dry):
        src = sources.get("google")
        objs, hit, missed, rows = [], 0, 0, 0
        seen = set()
        for row in _read(path):
            rows += 1
            tid = self._term_id(row, terms, "keyword")
            period = str(row.get("period") or "").strip()[:10]
            if not tid or src is None or not period:
                missed += 1
                self.miss[row.get("keyword", "?")] += 1
                continue
            try:
                metric_date = datetime.strptime(period, "%Y-%m-%d").date()
            except ValueError:
                missed += 1
                continue
            # 한 term 에 변형 키워드가 여러 개면 같은 (term, 날짜)가 겹친다 →
            # 먼저 온 것(대표 키워드)만 남긴다. 상대지수는 합산하면 안 되는 값이다.
            key = (tid, metric_date)
            if key in seen:
                continue
            seen.add(key)
            hit += 1
            objs.append(TermSearchTrend(
                term_id=tid, source=src, metric_date=metric_date,
                time_unit=TermSearchTrend.TimeUnit.WEEK, segment="all",
                ratio=_dec(row.get("ratio")),
                estimated_volume=_int(row.get("estimated_absolute_volume")),
                metric_version=version,
            ))
        self._upsert(
            TermSearchTrend, objs,
            ["term", "source", "metric_date", "time_unit", "segment", "metric_version"],
            ["ratio", "estimated_volume"], dry)
        return hit, missed, rows

    # ── ⑤ 시·도별 관심도 (G5) ─────────────────────────────────

    def load_region(self, path, terms, sources, month, version, dry):
        src = sources.get("google")
        objs, hit, missed, rows = [], 0, 0, 0
        today = date.today()
        seen = set()
        for row in _read(path):
            rows += 1
            tid = self._term_id(row, terms, "keyword")
            region = str(row.get("region") or "").strip()
            if not tid or src is None or not region:
                missed += 1
                self.miss[row.get("keyword", "?")] += 1
                continue
            key = (tid, region)
            if key in seen:
                continue
            seen.add(key)
            hit += 1
            objs.append(TermSearchRegion(
                term_id=tid, source=src, metric_date=today,
                region=region, value=_int(row.get("value")) or 0,
                metric_version=version,
            ))
        self._upsert(
            TermSearchRegion, objs,
            ["term", "source", "metric_date", "region", "metric_version"],
            ["value"], dry)
        return hit, missed, rows
