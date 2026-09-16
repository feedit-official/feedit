"""
저장소 — 긁은 걸 schema.sql 모양 그대로 담는다.

로컬은 SQLite 로 돌린다. 세컨 PC에서 며칠 돌릴 때 DB 서버까지 띄우게 하면
진입 장벽만 올라가고 얻는 게 없다. 파일 하나면 백업도 복사 한 번이다.

대신 **테이블 이름과 컬럼을 schema.sql 과 똑같이** 맞춰 뒀다.
플랫폼 Postgres 로 옮기는 일은 export_pg.py 가 맡는다.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

UTC = timezone.utc


def _now() -> str:
    return datetime.now(UTC).isoformat()


def sha256(obj: Any) -> str:
    s = obj if isinstance(obj, str) else json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _tag_list(value: Any) -> list[str]:
    """site_tags의 list/JSON/쉼표 문자열을 순서가 보존된 목록으로 바꾼다."""
    if not value:
        return []
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            value = decoded if isinstance(decoded, list) else [decoded]
        except (TypeError, ValueError):
            value = value.split(",")
    if not isinstance(value, (list, tuple, set)):
        value = [value]
    out = []
    noise_exact = {"무배당발", "무신사단독", "단독", "mdpick", "timesale",
                   "brandday", "라이브", "스테디셀러", "캐리오버", "컬렉션",
                   "패키지", "데일리", "패션"}
    noise_pattern = re.compile(
        r"^(?:\d{2,4}(?:ss|fw|hs|spring|summer|f/w|s/s)|fw\d{2}|ss\d{2}|"
        r"무료배송|무배|당일발송|당일출고|예약배송|신상|new)$", re.I)
    for item in value:
        tag = str(item or "").strip()
        compact = re.sub(r"[\s_\-]+", "", tag).lower()
        if (tag and compact not in noise_exact and not noise_pattern.match(compact)
                and not re.search(r"(?:pick|추천)$", compact, re.I)
                and tag not in out):
            out.append(tag)
    return out


# schema.sql 의 해당 테이블들을 SQLite 방언으로 옮긴 것.
# 컬럼명은 한 글자도 바꾸지 않았다 — 이름이 어긋나면 이관할 때 전부 손봐야 한다.
DDL = """
PRAGMA journal_mode=WAL;          -- 긴 크롤링 중 읽기/쓰기가 안 막히게
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS raw_document (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  source_code   TEXT NOT NULL,
  doc_type      TEXT NOT NULL,
  source_uid    TEXT NOT NULL,
  url           TEXT,
  payload       TEXT NOT NULL,          -- JSONB → TEXT(json)
  content_hash  TEXT NOT NULL,
  http_status   INTEGER,
  crawler_ver   TEXT,
  fetched_at    TEXT NOT NULL,
  UNIQUE (source_code, doc_type, source_uid, content_hash)
);
CREATE INDEX IF NOT EXISTS ix_raw_src ON raw_document (source_code, doc_type, fetched_at DESC);

CREATE TABLE IF NOT EXISTS crawl_run (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  source_code   TEXT NOT NULL,
  target        TEXT,
  started_at    TEXT NOT NULL,
  ended_at      TEXT,
  status        TEXT NOT NULL DEFAULT 'running',
  fetched_count INTEGER DEFAULT 0,
  error_count   INTEGER DEFAULT 0,
  blocked       INTEGER DEFAULT 0,
  note          TEXT
);

-- 리세일 매물/체결. listing_type 이 이 테이블의 핵심 컬럼이다.
CREATE TABLE IF NOT EXISTS resale_listing (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id    INTEGER,
  source_code   TEXT NOT NULL,
  source_uid    TEXT NOT NULL,
  size_name     TEXT,
  price         INTEGER NOT NULL,
  listing_type  TEXT NOT NULL,          -- settled | ask | bid
  condition     TEXT,
  listed_at     TEXT,
  settled_at    TEXT,
  collected_at  TEXT DEFAULT (datetime('now')),
  UNIQUE (source_code, source_uid)
);
CREATE INDEX IF NOT EXISTS ix_resale_pid ON resale_listing (product_id, listing_type, settled_at DESC);

-- 리세일 대상 상품. product 마스터로 승격하기 전의 임시 신원.
CREATE TABLE IF NOT EXISTS staging_product (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  source_code   TEXT NOT NULL,
  source_uid    TEXT NOT NULL,
  source_url    TEXT,
  name          TEXT,
  name_en       TEXT,
  brand_name    TEXT,
  category_path TEXT,
  retail_price  INTEGER,                -- 크림의 '발매가'
  release_date  TEXT,
  image_url     TEXT,
  color_names   TEXT,                   -- json array
  size_names    TEXT,                   -- json array
  model_code    TEXT,                   -- ★ 스타일코드. 플랫폼 간 상품 매칭의 열쇠
  measurements  TEXT,                   -- json: [{name,value,unit}] 실측 치수(cm)
  -- ★ 사이트가 붙여 준 태그 (#발레코어 …). 사람이 분류한 것이라
  --   상품명에서 짐작하는 것보다 훨씬 믿을 만하다. json 배열로 담는다.
  site_tags     TEXT,
  detail_seen_at TEXT,
  first_seen_at TEXT DEFAULT (datetime('now')),
  last_seen_at  TEXT DEFAULT (datetime('now')),
  UNIQUE (source_code, source_uid)
);

-- 텍스트(후기·스타일 설명). text_document 와 같은 모양.
CREATE TABLE IF NOT EXISTS text_document (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  raw_id        INTEGER,
  source_code   TEXT NOT NULL,
  doc_kind      TEXT NOT NULL,
  parent_id     INTEGER,
  product_uid   TEXT,
  body          TEXT NOT NULL,
  lang          TEXT DEFAULT 'ko',
  published_at  TEXT,
  like_count    INTEGER DEFAULT 0,
  reply_count   INTEGER DEFAULT 0,
  rating        INTEGER,
  author_height_cm INTEGER,
  author_weight_kg INTEGER,
  author_size   TEXT,
  author_hash   TEXT,
  quality_status TEXT DEFAULT 'active', -- active | quarantined
  quality_reason TEXT,
  collected_at  TEXT DEFAULT (datetime('now')),
  UNIQUE (source_code, doc_kind, product_uid, author_hash, published_at)
);

-- 문맥을 읽는 LLM 분석. 규칙 기반 text_intent와 섞지 않아 비교·교체가 가능하다.
CREATE TABLE IF NOT EXISTS text_llm_analysis (
  text_document_id INTEGER NOT NULL,
  model             TEXT NOT NULL,
  prompt_version    TEXT NOT NULL,
  fashion_relevance REAL NOT NULL,
  sentiment         TEXT NOT NULL,
  sentiment_score   REAL NOT NULL,
  purchase_intents  TEXT NOT NULL,
  related_terms     TEXT NOT NULL,
  evidence          TEXT NOT NULL,
  confidence        REAL NOT NULL,
  response_id       TEXT,
  input_tokens      INTEGER DEFAULT 0,
  output_tokens     INTEGER DEFAULT 0,
  analyzed_at       TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (text_document_id, model, prompt_version),
  FOREIGN KEY (text_document_id) REFERENCES text_document(id) ON DELETE CASCADE
);

-- 문서 전체가 해결됐는지. 엔티티가 없는 문장도 no_signal로 명시해 재과금을 막는다.
CREATE TABLE IF NOT EXISTS text_entity_resolution (
  text_document_id INTEGER NOT NULL,
  model             TEXT NOT NULL,
  prompt_version    TEXT NOT NULL,
  status            TEXT NOT NULL, -- confirmed | candidate | unresolved | no_signal
  no_signal_reason  TEXT,
  unresolved_terms  TEXT NOT NULL DEFAULT '[]',
  resolved_at       TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (text_document_id, model, prompt_version)
);

-- 한 문장이 어느 검색축의 무엇을 말하는지. 지표는 confirmed와 가중 candidate만 쓴다.
CREATE TABLE IF NOT EXISTS text_entity_mention (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  text_document_id  INTEGER NOT NULL,
  term_key          TEXT NOT NULL,
  canonical         TEXT NOT NULL,
  facet             TEXT NOT NULL,
  surface           TEXT,
  mention_role      TEXT NOT NULL, -- target | context
  status            TEXT NOT NULL,
  confidence        REAL NOT NULL,
  evidence          TEXT,
  extraction_method TEXT NOT NULL, -- dictionary | product_metadata | llm
  model             TEXT NOT NULL,
  prompt_version    TEXT NOT NULL,
  created_at        TEXT DEFAULT (datetime('now')),
  UNIQUE (text_document_id, term_key, mention_role, extraction_method, model, prompt_version)
);
CREATE INDEX IF NOT EXISTS ix_entity_mention_term ON text_entity_mention(facet, canonical, status);

-- 문서 전체가 아니라 특정 검색축 대상을 향한 감성·구매 의향.
CREATE TABLE IF NOT EXISTS text_entity_opinion (
  text_document_id INTEGER NOT NULL,
  term_key TEXT NOT NULL, canonical TEXT NOT NULL, facet TEXT NOT NULL,
  sentiment TEXT NOT NULL, sentiment_score REAL NOT NULL,
  purchase_intents TEXT NOT NULL DEFAULT '[]', evidence TEXT NOT NULL DEFAULT '[]',
  confidence REAL NOT NULL, model TEXT NOT NULL, prompt_version TEXT NOT NULL,
  analyzed_at TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (text_document_id, term_key, model, prompt_version)
);

-- L2 계산 결과의 로컬 스냅샷. PostgreSQL term_id는 export 때 대표어+축으로 찾는다.
CREATE TABLE IF NOT EXISTS metric_term_daily (
  term_key TEXT NOT NULL, canonical TEXT NOT NULL, facet TEXT NOT NULL,
  source_code TEXT NOT NULL, observed_on TEXT NOT NULL,
  raw_count INTEGER NOT NULL DEFAULT 0, log_value REAL, pct_rank REAL,
  level REAL, ma7 REAL, ma28 REAL, momentum REAL, temp INTEGER, share_pct REAL,
  metric_version TEXT NOT NULL,
  PRIMARY KEY (term_key, source_code, observed_on, metric_version)
);
CREATE TABLE IF NOT EXISTS metric_term_assoc_daily (
  base_term_key TEXT NOT NULL, base_canonical TEXT NOT NULL, base_facet TEXT NOT NULL,
  assoc_term_key TEXT NOT NULL, assoc_canonical TEXT NOT NULL, assoc_facet TEXT NOT NULL,
  observed_on TEXT NOT NULL, co_count INTEGER NOT NULL, lift REAL, pmi REAL,
  score_v INTEGER, rank_in_facet INTEGER, is_new INTEGER DEFAULT 0,
  metric_version TEXT NOT NULL,
  PRIMARY KEY (base_term_key, assoc_term_key, observed_on, metric_version)
);
CREATE TABLE IF NOT EXISTS metric_term_sentiment_daily (
  term_key TEXT NOT NULL, canonical TEXT NOT NULL, facet TEXT NOT NULL,
  observed_on TEXT NOT NULL, n_total INTEGER NOT NULL, weighted_sum REAL,
  pos_count INTEGER, neg_count INTEGER, index_value INTEGER, pos_pct REAL, neg_pct REAL,
  top_pos_intent TEXT, top_pos_count INTEGER, top_neg_intent TEXT, top_neg_count INTEGER,
  metric_version TEXT NOT NULL,
  PRIMARY KEY (term_key, observed_on, metric_version)
);

-- ★ 인기 지표 스냅샷 — 순위·후기 수·관심 수·거래 수.
--
--   staging_product 에 칸을 더하지 않고 따로 둔 이유:
--   이 값들은 '지금 이 상품이 어떤 상태인지'가 아니라 **시간에 따라 변하는 값**이다.
--   후기 수는 쌓이고, 순위는 매일 오르내린다. 상품 표에 넣고 덮어쓰면
--   "지난주보다 얼마나 늘었나"를 영영 못 본다. 그런데 FEEDiT 가 보려는 게
--   바로 그 변화량이다. 그래서 가격처럼 잴 때마다 한 줄씩 남긴다.
--
--   하루에 두 번 돌아도 한 줄만 남게 (날짜, 상품) 로 묶는다.
--   같은 날 다시 재면 최신 값으로 갱신된다.
CREATE TABLE IF NOT EXISTS product_stat (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  source_code   TEXT NOT NULL,
  source_uid    TEXT NOT NULL,
  stat_date     TEXT NOT NULL,          -- YYYY-MM-DD
  captured_at   TEXT NOT NULL,
  rank          INTEGER,                -- 랭킹 순위 (1 등이 제일 좋음)
  rank_scope    TEXT,                   -- 어느 랭킹인지 '여성 상의' 등
  review_count  INTEGER,                -- 후기 수
  review_score  REAL,                   -- 평점 (5점 만점으로 통일)
  wish_count    INTEGER,                -- 관심·찜
  trade_count   INTEGER,                -- 거래 수 (크림)
  buy_count     INTEGER,                -- 구매 수 (에이블리)
  style_count   INTEGER,                -- 스타일 게시물 수 (크림)
  discount      INTEGER,                -- 할인율 %
  price         INTEGER,                -- 그때 가격
  review_dist   TEXT,                   -- json {'1'..'5': 비율} 별점 분포 (크림)
  fit_note      TEXT,                   -- '오버핏이에요'
  thickness_note TEXT,                  -- '두께감이 보통이에요'
  quality_note  TEXT,
  UNIQUE (source_code, source_uid, stat_date)
);
CREATE INDEX IF NOT EXISTS ix_stat_uid ON product_stat (source_code, source_uid, stat_date DESC);

-- 12시간 수집에서도 가격 변화가 사라지지 않는 원본 스냅샷.
-- product_stat은 일 단위 집계라 같은 날 두 번의 가격을 보존하지 못한다.
CREATE TABLE IF NOT EXISTS product_price_snapshot (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  source_code        TEXT NOT NULL,
  source_uid         TEXT NOT NULL,
  captured_at        TEXT NOT NULL,
  price              INTEGER NOT NULL,
  initial_ask_price  INTEGER,
  discount           INTEGER,
  condition_grade    TEXT,
  availability_state TEXT,
  UNIQUE (source_code, source_uid, captured_at)
);
CREATE INDEX IF NOT EXISTS ix_price_snapshot_uid
  ON product_price_snapshot (source_code, source_uid, captured_at DESC);

-- 어디까지 긁었는지. 이게 있어야 껐다 켜도 이어서 돈다.
CREATE TABLE IF NOT EXISTS checkpoint (
  job_key       TEXT PRIMARY KEY,
  cursor        TEXT,
  done_count    INTEGER DEFAULT 0,
  total_hint    INTEGER,
  updated_at    TEXT
);

-- 이미 본 URL. 중복 요청은 서버에도 우리에게도 낭비다.
CREATE TABLE IF NOT EXISTS seen_url (
  url           TEXT PRIMARY KEY,
  source_code   TEXT,
  seen_at       TEXT DEFAULT (datetime('now')),
  http_status   INTEGER
);
"""


class Store:
    """SQLite 저장소. 스레드에서 같이 써도 되게 락을 건다."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # 서버가 사전을 준비한 뒤 주입한다. 없는 CLI/테스트 환경은 기존처럼 저장만 한다.
        self.text_entity_linker = None
        # 발표 집중 수집은 운영 서버가 명시적으로 켠다. 라이브러리/테스트에서
        # Store를 쓰는 것만으로 정책이 몰래 바뀌면 안 된다.
        self.target_scope_enabled = False
        self.repaired: list[str] = []
        with self._lock:
            self._selfcheck()
            self._conn.executescript(DDL)
            self._migrate()
            self._conn.commit()
        # 환율기 — 달러로 적힌 발매가를 '수집한 날짜의' 환율로 원화로 바꾼다.
        # 저장소에 붙여 두면 러너·가져오기가 따로 만들 필요가 없다.
        from .fx import FX
        self.fx = FX(self)

    # 다시 만들어도 되는 표 — 안에 든 게 '지금 상태'뿐이라 버려도 그만이다.
    #   admin_session  다시 로그인하면 된다
    #   seen_url       다시 받으면 된다 (좀 더 받을 뿐)
    #   login_attempt  실패 기록
    DISPOSABLE = ("admin_session", "seen_url", "login_attempt")

    @classmethod
    def blame(cls, rows) -> set:
        """integrity_check 가 뱉은 줄들 → 다친 표 이름.

        색인 이름은 표 이름과 다르다. 'ix_sess_user' 와
        'sqlite_autoindex_admin_session_1' 둘 다 admin_session 의 것이다.
        표 이름으로 되돌려야 '버려도 되는 표인가'를 판단할 수 있다.
        """
        hurt = set()
        for m in rows:
            got = (re.search(r"index (\w+)", m) or re.search(r"table (\w+)", m)
                   or re.search(r"in (\w+) after", m))
            if not got:
                if m != "ok":
                    hurt.add("(알 수 없음)")
                continue
            nm = got.group(1)
            hit = next((t for t in cls.INDEX_OWNER.get(nm, ()) if t), None)
            hurt.add(hit or nm)
        return hurt

    # 색인 → 어느 표의 것인가. 이름만으로는 못 알아보는 것들.
    INDEX_OWNER = {
        "ix_sess_user": ("admin_session",),
        "sqlite_autoindex_admin_session_1": ("admin_session",),
        "sqlite_autoindex_seen_url_1": ("seen_url",),
        "sqlite_autoindex_login_attempt_1": ("login_attempt",),
    }

    def _selfcheck(self):
        """켤 때 한 번 훑는다. 고칠 수 있는 것만 조용히 고친다.

        ★ 왜 필요한가
          DB 가 깨지면 지금까지는 첫 쿼리에서 그냥 터졌다.

              sqlite3.DatabaseError: database disk image is malformed

          비전공자에게 이건 아무 말도 아니다. 실제로 서버가 안 열려서
          손을 못 대는 상황이 났다. 정작 그때 깨진 건 세션 표 하나였고
          상품 3,259개는 멀쩡했다.

          그래서 여기서 미리 본다. 다시 만들어도 되는 표만 깨졌으면
          말없이 새로 만들고 넘어간다. 진짜 데이터가 깨졌으면
          **덮어쓰지 않고** 무엇이 문제인지 사람 말로 알려 준다.
        """
        try:
            rows = [r[0] for r in self._conn.execute("PRAGMA integrity_check(200)")]
        except sqlite3.DatabaseError as e:
            raise RuntimeError(
                f"데이터베이스 파일이 열리지 않습니다 ({self.path}).\n"
                f"  원인: {e}\n"
                f"  · 백업이 있으면 그 파일로 바꿔 주세요.\n"
                f"  · 없으면 `python tools/db_check.py` 를 돌려 주세요."
            ) from e
        if rows == ["ok"]:
            return

        hurt = self.blame(rows)
        fixable = {t for t in hurt if t in self.DISPOSABLE}
        rest = hurt - fixable
        for t in fixable:
            try:
                self._conn.execute(f"DROP TABLE IF EXISTS {t}")
                self._conn.commit()
                self.repaired.append(t)
            except sqlite3.DatabaseError:
                rest.add(t)
        if fixable and not rest:
            self._conn.execute("REINDEX")
            self._conn.commit()

        if rest:
            raise RuntimeError(
                f"데이터베이스가 손상됐습니다 ({self.path}).\n"
                f"  다친 곳: {', '.join(sorted(rest))}\n"
                f"  문제 {len(rows)}건. 자동으로 고치면 데이터가 날아갈 수 있어\n"
                f"  손대지 않았습니다. `python tools/db_check.py` 를 돌려 주세요."
            )

    def _migrate(self):
        """이미 만들어진 DB 에 새 컬럼을 더한다.

        CREATE TABLE IF NOT EXISTS 는 이미 있는 표를 고쳐 주지 않는다.
        그대로 두면 옛 DB 로 돌릴 때 'no such column' 으로 죽으므로,
        모자란 컬럼만 조용히 채워 넣는다. 데이터는 건드리지 않는다.
        """
        want = {
            "staging_product": [("measurements", "TEXT"), ("category_path", "TEXT"),
                                # ★ 원화 값 하나만 두면 환율이 틀렸을 때 되돌릴 수 없다.
                                #   원본 금액·통화·쓴 환율을 셋 다 남긴다.
                                ("retail_price_orig", "REAL"),
                                ("retail_currency", "TEXT"),
                                ("retail_fx_rate", "REAL"),
                                ("retail_fx_date", "TEXT"),
                                # 사이트가 붙여 준 태그 (#발레코어 …)
                                ("site_tags", "TEXT"),
                                # ★ 이 상품의 **상세**를 마지막으로 받은 때.
                                #   last_seen_at 은 목록에서 스쳐도 갱신되므로
                                #   '상세를 받아 봤나'를 구별할 수 없었다. 그래서
                                #   렌더링으로 담은 상품이 영원히 상세를 못 받았다
                                #   (2026-09-01 실측: 재방문 후보가 1,459건 중 29건).
                                ("detail_seen_at", "TEXT")],
            # 인기 지표에 뒤늦게 더한 것들 — 이미 표를 만든 DB 에도 붙여 준다
            "product_stat": [("review_dist", "TEXT"), ("fit_note", "TEXT"),
                             ("thickness_note", "TEXT"), ("quality_note", "TEXT")],
            # 삭제하지 않고 품질 격리한다. 필터가 좋아지면 다시 active로 돌릴 수 있다.
            "text_document": [("quality_status", "TEXT DEFAULT 'active'"),
                              ("quality_reason", "TEXT")],
        }
        for table, cols in want.items():
            try:
                have = {r[1] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            except sqlite3.Error:
                continue
            if not have:
                continue
            for name, typ in cols:
                if name not in have:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")

    @contextmanager
    def tx(self):
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def text_for_analysis(self, text_document_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, source_code, doc_kind, body FROM text_document WHERE id=?",
                (text_document_id,)).fetchone()
            return dict(row) if row else None

    def put_llm_analysis(self, text_document_id: int, result: dict) -> None:
        with self.tx() as c:
            c.execute("""INSERT INTO text_llm_analysis
                (text_document_id, model, prompt_version, fashion_relevance, sentiment,
                 sentiment_score, purchase_intents, related_terms, evidence, confidence,
                 response_id, input_tokens, output_tokens, analyzed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                ON CONFLICT(text_document_id, model, prompt_version) DO UPDATE SET
                 fashion_relevance=excluded.fashion_relevance, sentiment=excluded.sentiment,
                 sentiment_score=excluded.sentiment_score, purchase_intents=excluded.purchase_intents,
                 related_terms=excluded.related_terms, evidence=excluded.evidence,
                 confidence=excluded.confidence, response_id=excluded.response_id,
                 input_tokens=excluded.input_tokens, output_tokens=excluded.output_tokens,
                 analyzed_at=excluded.analyzed_at""", (
                text_document_id, result["model"], result["prompt_version"],
                result["fashion_relevance"], result["sentiment"], result["sentiment_score"],
                json.dumps(result["purchase_intents"], ensure_ascii=False),
                json.dumps(result["related_terms"], ensure_ascii=False),
                json.dumps(result["evidence"], ensure_ascii=False), result["confidence"],
                result.get("response_id"), result.get("input_tokens", 0),
                result.get("output_tokens", 0)))

    def put_entity_resolution(self, text_document_id: int, result: dict,
                              mentions: list[dict]) -> None:
        model, version = result["model"], result["prompt_version"]
        with self.tx() as c:
            c.execute("""INSERT INTO text_entity_resolution
                (text_document_id,model,prompt_version,status,no_signal_reason,
                 unresolved_terms,resolved_at) VALUES (?,?,?,?,?,?,datetime('now'))
                ON CONFLICT(text_document_id,model,prompt_version) DO UPDATE SET
                 status=excluded.status,no_signal_reason=excluded.no_signal_reason,
                 unresolved_terms=excluded.unresolved_terms,resolved_at=excluded.resolved_at""",
                (text_document_id, model, version, result.get("resolution_status") or "unresolved",
                 result.get("no_signal_reason"),
                 json.dumps(result.get("unresolved_terms") or [], ensure_ascii=False)))
            c.execute("DELETE FROM text_entity_mention WHERE text_document_id=? "
                      "AND model=? AND prompt_version=?", (text_document_id, model, version))
            for m in mentions:
                c.execute("""INSERT OR IGNORE INTO text_entity_mention
                    (text_document_id,term_key,canonical,facet,surface,mention_role,status,
                     confidence,evidence,extraction_method,model,prompt_version)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    text_document_id, m["term_key"], m["canonical"], m["facet"],
                    m.get("surface"), m.get("role") or "context",
                    m.get("status") or "candidate", m.get("confidence") or 0,
                    m.get("evidence"), m.get("method") or "llm", model, version))
            c.execute("DELETE FROM text_entity_opinion WHERE text_document_id=? "
                      "AND model=? AND prompt_version=?", (text_document_id, model, version))
            linked = {(m["facet"], norm): m for m in mentions
                      for norm in [re.sub(r"[\s\-_·/&,.()\[\]]+", "", m["canonical"]).lower()]}
            for opinion in result.get("entity_opinions") or []:
                canonical = str(opinion.get("canonical") or "").strip()
                facet = str(opinion.get("facet") or "")
                key = re.sub(r"[\s\-_·/&,.()\[\]]+", "", canonical).lower()
                mention = linked.get((facet, key))
                if not mention or mention.get("status") != "confirmed":
                    continue
                confidence = max(0.0, min(float(opinion.get("confidence") or 0), 1.0))
                c.execute("""INSERT INTO text_entity_opinion
                    (text_document_id,term_key,canonical,facet,sentiment,sentiment_score,
                     purchase_intents,evidence,confidence,model,prompt_version,analyzed_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""", (
                    text_document_id, mention["term_key"], mention["canonical"], facet,
                    opinion.get("sentiment") or "neutral",
                    max(-1.0, min(float(opinion.get("sentiment_score") or 0), 1.0)),
                    json.dumps(list(dict.fromkeys(opinion.get("purchase_intents") or [])), ensure_ascii=False),
                    json.dumps(list(dict.fromkeys(opinion.get("evidence") or [])), ensure_ascii=False),
                    confidence, model, version))

    def llm_candidates(self, model: str, prompt_version: str, limit: int = 20,
                       source: str = "all", target_keys: list[str] | None = None) -> list[dict]:
        """후보 → 패션 문맥 미해결 → 구매의도 규칙 적중 순으로 고른다."""
        from .entity_linker import RULE_MODEL, RULE_VERSION
        from .intent import classify
        from . import naver
        where = ["COALESCE(t.quality_status,'active')='active'",
                 "length(trim(t.body)) BETWEEN 6 AND 12000",
                 "a.text_document_id IS NULL", "dr.status IS NOT NULL"]
        args: list[Any] = [model, prompt_version, RULE_MODEL, RULE_VERSION]
        if source not in ("all", "demo"):
            where.append("t.source_code=?")
            args.append(source)
        target_keys = list(dict.fromkeys(target_keys or []))
        if target_keys:
            marks = ",".join("?" for _ in target_keys)
            where.append("EXISTS (SELECT 1 FROM text_entity_mention tm WHERE "
                         "tm.text_document_id=t.id AND tm.term_key IN (" + marks + ") "
                         "AND tm.status='confirmed')")
            args.extend(target_keys)
        wanted = max(1, min(int(limit), 50000))
        # 필터 대상이 아닌 unresolved가 앞을 막아 뒤의 구매의도 문서를 굶기지 않도록
        # active 전체를 읽어 우선순위를 매긴 뒤 wanted만 자른다.
        args.append(50000)
        with self._lock:
            rows = self._conn.execute(
                "SELECT t.id,t.source_code,t.doc_kind,t.body,t.collected_at,"
                "p.name AS product_name,p.brand_name,p.category_path,p.site_tags,"
                "dr.status AS resolution_status "
                "FROM text_document t LEFT JOIN text_llm_analysis a "
                "ON a.text_document_id=t.id AND a.model=? AND a.prompt_version=? "
                "LEFT JOIN text_entity_resolution dr ON dr.text_document_id=t.id "
                "AND dr.model=? AND dr.prompt_version=? "
                "LEFT JOIN staging_product p ON p.source_code=t.source_code "
                "AND p.source_uid=t.product_uid "
                f"WHERE {' AND '.join(where)} "
                "ORDER BY CASE dr.status WHEN 'candidate' THEN 0 WHEN 'unresolved' THEN 1 "
                "WHEN 'confirmed' THEN 2 ELSE 3 END,t.collected_at DESC,t.id DESC LIMIT ?",
                args).fetchall()
        fashion_context = re.compile(
            r"패션|코디|착용|스타일|옷|의류|상의|하의|신발|가방|핏|소재|사이즈|"
            r"원피스|셔츠|팬츠|스커트|자켓|재킷|니트|브랜드|룩\b", re.I)
        selected = []
        seen_bodies = set()
        for raw in rows:
            row = dict(raw)
            body = row.get("body") or ""
            if row.get("source_code") == "naver" and (
                    naver._is_ad(body) or naver._is_listing(body)):
                continue
            body_key = re.sub(r"\s+", " ", body).strip().lower()
            if body_key in seen_bodies:
                continue
            seen_bodies.add(body_key)
            status = row.get("resolution_status")
            # 상품 리뷰는 그 자체가 상품 문맥이다. "좋아요", "사이즈가 작아요"
            # 같은 짧은 리뷰에 패션 명사가 없다는 이유로 Luna 큐에서 버리면
            # 리뷰 원문은 저장돼도 긍부정·구매의향 분석에 영영 들어오지 않는다.
            if row.get("doc_kind") == "product_review":
                row["queue_reason"] = "상품 리뷰 감성 판정"
                row["queue_priority"] = 0
            elif status == "candidate":
                row["queue_reason"] = "사전 후보 문맥 확정"
                row["queue_priority"] = 1
            elif status == "unresolved" and fashion_context.search(body):
                row["queue_reason"] = "패션 문맥이 있는 미해결 표현"
                row["queue_priority"] = 2
            elif status == "confirmed" and classify(body)["labels"]:
                row["queue_reason"] = "구매 의향 대상 연결"
                row["queue_priority"] = 3
            elif target_keys and status == "confirmed":
                # 발표 타깃은 하드코딩된 의향 단어가 없어도 Luna가 문맥을 판정한다.
                row["queue_reason"] = "발표 타깃 감성 판정"
                row["queue_priority"] = 4
            else:
                continue
            selected.append(row)
            if not target_keys and len(selected) >= wanted:
                break
        if target_keys and selected:
            by_id = {int(r["id"]): r for r in selected}
            ids = list(by_id)
            for offset in range(0, len(ids), 700):
                batch_ids = ids[offset:offset + 700]
                id_marks = ",".join("?" for _ in batch_ids)
                key_marks = ",".join("?" for _ in target_keys)
                with self._lock:
                    hits = self._conn.execute(
                        "SELECT DISTINCT text_document_id,term_key FROM text_entity_mention "
                        f"WHERE text_document_id IN ({id_marks}) AND term_key IN ({key_marks}) "
                        "AND status='confirmed'", (*batch_ids, *target_keys)).fetchall()
                for text_id, term_key in hits:
                    by_id[int(text_id)].setdefault("demo_target_keys", []).append(term_key)
            # 한 소재의 대량 문서가 100칸을 독점하지 않게 타깃별로 한 건씩 순환한다.
            queues = {key: [] for key in target_keys}
            for row in selected:
                for key in row.get("demo_target_keys", []):
                    queues[key].append(row)
            balanced, used = [], set()
            source_counts = defaultdict(Counter)
            while len(balanced) < wanted:
                progressed = False
                for key in target_keys:
                    queues[key] = [r for r in queues[key] if r["id"] not in used]
                    if queues[key]:
                        # 같은 타깃 안에서도 네이버만 먼저 소비하지 않고 출처를 순환한다.
                        pick = min(range(len(queues[key])), key=lambda i: (
                            source_counts[key][queues[key][i]["source_code"]], i))
                        row = queues[key].pop(pick)
                        used.add(row["id"])
                        source_counts[key][row["source_code"]] += 1
                        balanced.append(row)
                        progressed = True
                        if len(balanced) >= wanted:
                            break
                if not progressed:
                    break
            selected = balanced
        return selected

    def demo_sentiment_status(self, targets: list[dict], model: str,
                              prompt_version: str, goal: int = 30) -> dict:
        """발표 타깃별 원문·LLM 의견·미분석 후보를 한 표로 반환한다."""
        rows = []
        with self._lock:
            for target in targets:
                key = f"{target['facet']}:{target['canonical']}"
                source_rows = self._conn.execute(
                    "SELECT d.source_code,count(DISTINCT d.id) n FROM text_entity_mention m "
                    "JOIN text_document d ON d.id=m.text_document_id WHERE m.term_key=? "
                    "AND m.status='confirmed' AND COALESCE(d.quality_status,'active')='active' "
                    "GROUP BY d.source_code", (key,)).fetchall()
                sources = {r[0]: int(r[1]) for r in source_rows}
                opinions = int(self._conn.execute(
                    "SELECT count(DISTINCT o.text_document_id) FROM text_entity_opinion o "
                    "JOIN text_document d ON d.id=o.text_document_id WHERE o.term_key=? "
                    "AND o.model=? AND o.prompt_version=? AND o.confidence>=.8 "
                    "AND COALESCE(d.quality_status,'active')='active'",
                    (key, model, prompt_version)).fetchone()[0])
                pending = int(self._conn.execute(
                    "SELECT count(DISTINCT d.id) FROM text_entity_mention m "
                    "JOIN text_document d ON d.id=m.text_document_id "
                    "LEFT JOIN text_llm_analysis a ON a.text_document_id=d.id "
                    "AND a.model=? AND a.prompt_version=? WHERE m.term_key=? "
                    "AND m.status='confirmed' AND COALESCE(d.quality_status,'active')='active' "
                    "AND length(trim(d.body)) BETWEEN 6 AND 12000 AND a.text_document_id IS NULL",
                    (model, prompt_version, key)).fetchone()[0])
                documents = sum(sources.values())
                rows.append({**target, "term_key": key, "documents": documents,
                             "sources": sources, "opinions": opinions, "pending": pending,
                             "goal": goal, "missing": max(0, goal - opinions),
                             "analyzed_without_opinion": max(0, documents - pending - opinions),
                             "collection_needed": documents == 0})
        return {"targets": rows, "goal_per_target": goal,
                "ready": sum(1 for r in rows if r["opinions"] >= goal),
                "total": len(rows), "missing_total": sum(r["missing"] for r in rows)}

    def entity_backfill_candidates(self, limit: int = 1000, source: str = "all") -> list[dict]:
        from .entity_linker import RULE_MODEL, RULE_VERSION
        where = ["COALESCE(t.quality_status,'active')='active'", "r.text_document_id IS NULL"]
        args: list[Any] = [RULE_MODEL, RULE_VERSION]
        if source != "all":
            where.append("t.source_code=?")
            args.append(source)
        args.append(max(1, min(int(limit), 50000)))
        with self._lock:
            rows = self._conn.execute(
                "SELECT t.id,t.source_code,t.doc_kind,t.body,t.collected_at,"
                "p.name AS product_name,p.brand_name,p.category_path,p.site_tags "
                "FROM text_document t LEFT JOIN text_entity_resolution r "
                "ON r.text_document_id=t.id AND r.model=? AND r.prompt_version=? "
                "LEFT JOIN staging_product p ON p.source_code=t.source_code "
                "AND p.source_uid=t.product_uid "
                f"WHERE {' AND '.join(where)} ORDER BY t.id LIMIT ?", args).fetchall()
            return [dict(r) for r in rows]

    def entity_backfill_stats(self) -> dict:
        from .entity_linker import RULE_MODEL, RULE_VERSION
        with self._lock:
            total = self._conn.execute(
                "SELECT count(*) FROM text_document WHERE "
                "COALESCE(quality_status,'active')='active'").fetchone()[0]
            statuses = {r[0]: r[1] for r in self._conn.execute(
                "SELECT status,count(*) FROM text_entity_resolution WHERE model=? "
                "AND prompt_version=? GROUP BY status", (RULE_MODEL, RULE_VERSION))}
            pending = self._conn.execute(
                "SELECT count(*) FROM text_document t LEFT JOIN text_entity_resolution r "
                "ON r.text_document_id=t.id AND r.model=? AND r.prompt_version=? WHERE "
                "COALESCE(t.quality_status,'active')='active' AND r.text_document_id IS NULL",
                (RULE_MODEL, RULE_VERSION)).fetchone()[0]
        return {"eligible": total, "done": sum(statuses.values()), "pending": pending,
                "statuses": statuses}

    def llm_stats(self, model: str, prompt_version: str) -> dict:
        with self._lock:
            eligible = self._conn.execute(
                "SELECT count(*) FROM text_document t WHERE "
                "COALESCE(t.quality_status,'active')='active' "
                "AND length(trim(t.body)) BETWEEN 6 AND 12000").fetchone()[0]
            done = self._conn.execute(
                "SELECT count(*),COALESCE(sum(input_tokens),0),COALESCE(sum(output_tokens),0),"
                "COALESCE(sum(CASE WHEN fashion_relevance < 0.5 THEN 1 ELSE 0 END),0) "
                "FROM text_llm_analysis WHERE model=? AND prompt_version=?",
                (model, prompt_version)).fetchone()
            remaining = self._conn.execute(
                "SELECT count(*) FROM text_document t LEFT JOIN text_llm_analysis a "
                "ON a.text_document_id=t.id AND a.model=? AND a.prompt_version=? WHERE "
                "COALESCE(t.quality_status,'active')='active' "
                "AND length(trim(t.body)) BETWEEN 6 AND 12000 "
                "AND a.text_document_id IS NULL", (model, prompt_version)).fetchone()[0]
            resolution = {r[0]: r[1] for r in self._conn.execute(
                "SELECT status,count(*) FROM text_entity_resolution "
                "WHERE model=? AND prompt_version=? GROUP BY status",
                (model, prompt_version)).fetchall()}
        return {"eligible": eligible, "done": done[0],
                "remaining": remaining,
                "input_tokens": done[1], "output_tokens": done[2],
                "low_relevance": done[3], "resolutions": resolution}

    def recent_llm_results(self, model: str, prompt_version: str, limit: int = 50,
                           source: str = "all") -> list[dict]:
        """Return review-friendly recent analyses without exposing raw model payloads."""
        limit = max(1, min(int(limit), 200))
        where = ["a.model=?", "a.prompt_version=?"]
        args: list[Any] = [model, prompt_version]
        if source != "all":
            where.append("t.source_code=?")
            args.append(source)
        with self._lock:
            rows = [dict(r) for r in self._conn.execute(
                "SELECT a.text_document_id,t.source_code,t.doc_kind,t.body,"
                "a.fashion_relevance,a.sentiment,a.sentiment_score,a.purchase_intents,"
                "a.related_terms,a.evidence,a.confidence,a.input_tokens,a.output_tokens,"
                "a.analyzed_at,r.status,r.unresolved_terms,r.no_signal_reason "
                "FROM text_llm_analysis a JOIN text_document t ON t.id=a.text_document_id "
                "LEFT JOIN text_entity_resolution r ON r.text_document_id=a.text_document_id "
                "AND r.model=a.model AND r.prompt_version=a.prompt_version "
                f"WHERE {' AND '.join(where)} ORDER BY a.analyzed_at DESC,a.text_document_id DESC LIMIT ?",
                (*args, limit)).fetchall()]
            if not rows:
                return []
            ids = [r["text_document_id"] for r in rows]
            marks = ",".join("?" for _ in ids)
            opinion_rows = [dict(r) for r in self._conn.execute(
                "SELECT text_document_id,canonical,facet,sentiment,sentiment_score,"
                "purchase_intents,evidence,confidence FROM text_entity_opinion "
                f"WHERE model=? AND prompt_version=? AND text_document_id IN ({marks}) "
                "ORDER BY text_document_id,confidence DESC", (model, prompt_version, *ids))]
        opinions: dict[int, list[dict]] = defaultdict(list)
        for opinion in opinion_rows:
            for field in ("purchase_intents", "evidence"):
                try:
                    opinion[field] = json.loads(opinion.get(field) or "[]")
                except (TypeError, ValueError):
                    opinion[field] = []
            opinions[opinion.pop("text_document_id")].append(opinion)
        for row in rows:
            for field in ("purchase_intents", "related_terms", "evidence",
                          "unresolved_terms"):
                try:
                    row[field] = json.loads(row.get(field) or "[]")
                except (TypeError, ValueError):
                    row[field] = []
            row["body"] = (row.get("body") or "")[:800]
            row["entity_opinions"] = opinions.get(row["text_document_id"], [])
        return rows

    def metric_results(self, version: str, kind: str = "trend", limit: int = 50,
                       query: str = "") -> list[dict]:
        """Return the latest derived metric rows for the admin review screen."""
        limit = max(1, min(int(limit), 200))
        like = f"%{str(query).strip()}%"
        specs = {
            "trend": ("metric_term_daily", "source_code='__all__'",
                      "temp DESC,raw_count DESC", "canonical"),
            "sentiment": ("metric_term_sentiment_daily", "1=1",
                          "n_total DESC,index_value DESC", "canonical"),
            "association": ("metric_term_assoc_daily", "1=1",
                            "score_v DESC,co_count DESC", "base_canonical||' '||assoc_canonical"),
        }
        if kind not in specs:
            kind = "trend"
        table, extra, order, search_col = specs[kind]
        with self._lock:
            latest = self._conn.execute(
                f"SELECT max(observed_on) FROM {table} WHERE metric_version=?", (version,)
            ).fetchone()[0]
            if not latest:
                return []
            return [dict(r) for r in self._conn.execute(
                f"SELECT * FROM {table} WHERE metric_version=? AND observed_on=? AND {extra} "
                f"AND ({search_col}) LIKE ? ORDER BY {order} LIMIT ?",
                (version, latest, like, limit)).fetchall()]

    # ── L0 원본 ────────────────────────────────────────────────
    def put_raw(
        self,
        source_code: str,
        doc_type: str,
        source_uid: str,
        payload: Any,
        url: str = "",
        http_status: int = 200,
        crawler_ver: str = "v1",
    ) -> Optional[int]:
        """원본을 넣는다. 내용이 그대로면 조용히 건너뛴다(중복 방지)."""
        h = sha256(payload)
        with self.tx() as c:
            cur = c.execute(
                """INSERT OR IGNORE INTO raw_document
                   (source_code, doc_type, source_uid, url, payload,
                    content_hash, http_status, crawler_ver, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (source_code, doc_type, source_uid, url,
                 json.dumps(payload, ensure_ascii=False), h,
                 http_status, crawler_ver, _now()),
            )
            return cur.lastrowid if cur.rowcount else None

    # ── 상품 ───────────────────────────────────────────────────

    # ── 수집 범위 ────────────────────────────────────────────
    #  악세서리·화장품을 담지 않는다. 판단 규칙은 scope.py 에 있다.
    #  버린 건수는 세어 두고, 처음 몇 건은 왜 버렸는지 problem 에 남긴다
    #  — 조용히 사라지면 나중에 "왜 이 브랜드가 비었지" 를 못 푼다.
    SCOPE_REPORT_MAX = 0

    def _in_scope(self, source_code: str, source_uid: str, f: dict) -> bool:
        from . import scope, target_scope
        with self.tx() as c:
            row = c.execute(
                "SELECT 1 FROM staging_product WHERE source_code=? AND source_uid=?",
                (source_code, source_uid)).fetchone()
        if row:
            return True          # 이미 아는 상품은 다시 재지 않는다

        ok, why = scope.judge(f.get("name") or "",
                              f.get("category_path") or "",
                              site_tags=f.get("site_tags"))
        if ok and self.target_scope_enabled:
            ok, why = target_scope.judge(source_code, source_uid, f)
        if ok:
            return True

        self._scope_dropped = getattr(self, "_scope_dropped", 0) + 1
        if self._scope_dropped <= self.SCOPE_REPORT_MAX:
            try:
                from .problems import Problems
                Problems(self).add(
                    title="수집 범위 밖이라 담지 않았습니다",
                    detail=f"{source_code}/{source_uid} · "
                           f"{(f.get('name') or '')[:60]}\n{why}",
                    source_code=source_code, where="수집 범위",
                    url=f.get("source_url") or "")
            except Exception:      # noqa: BLE001 - 기록 실패로 수집을 멈추지 않는다
                pass
        return False

    def scope_dropped(self) -> int:
        """이번 실행에서 옷이 아니라 돌려보낸 건수."""
        return getattr(self, "_scope_dropped", 0)

    def upsert_product(self, source_code: str, source_uid: str, **f) -> None:
        # ── 옷이 아닌 것은 여기서 돌려보낸다 ──
        #   목록·상세·저장본 담아오기가 전부 이 문을 지나므로 한 곳만 막으면 된다.
        #   ★ 이미 담긴 상품은 다시 판단하지 않는다. 목록에서는 분류가 안 와서
        #     '모른다'가 되는데, 그걸 새로 온 정보로 착각해 지우면 안 된다.
        if not self._in_scope(source_code, source_uid, f):
            return

        # ★ COALESCE 로 덮어쓴다. 새 값이 비었으면 기존 값을 지키기 위해서다.
        #   목록에서 브랜드를 채운 뒤 상세를 저장하면, 상세 설정에 brand 칸이 없어
        #   None 이 들어오면서 멀쩡한 브랜드를 지워 버렸다. 빈 값은 '모른다'는 뜻이지
        #   '없다'는 뜻이 아니므로, 모른다고 해서 알던 것을 버릴 이유가 없다.
        with self.tx() as c:
            # 같은 상품은 여러 스타일 검색 결과에 동시에 나올 수 있다.
            # site_tags를 마지막 검색 결과로 덮어쓰면 멀티라벨 정답이 사라지므로
            # 기존 태그와 새 태그를 합친 뒤 저장한다.
            if f.get("site_tags"):
                old = c.execute(
                    "SELECT site_tags FROM staging_product "
                    "WHERE source_code=? AND source_uid=?",
                    (source_code, source_uid),
                ).fetchone()
                merged = _tag_list(old[0] if old else None)
                for tag in _tag_list(f["site_tags"]):
                    if tag not in merged:
                        merged.append(tag)
                f["site_tags"] = merged or None

            cols = ["source_code", "source_uid"] + list(f.keys())
            vals = [source_code, source_uid] + [
                json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                for v in f.values()
            ]
            upd = ", ".join(
                f"{k}=COALESCE(excluded.{k}, staging_product.{k})" for k in f.keys())
            c.execute(
                f"""INSERT INTO staging_product ({', '.join(cols)})
                    VALUES ({', '.join('?' * len(cols))})
                    ON CONFLICT(source_code, source_uid) DO UPDATE SET
                      {upd}, last_seen_at = datetime('now')""",
                vals,
            )

    # ── 인기 지표 ───────────────────────────────────────────────
    def put_stat(self, source_code: str, source_uid: str, **f) -> bool:
        """순위·후기·관심·거래 수를 하루 한 줄로 남긴다.

        값이 하나도 없으면 빈 줄을 만들지 않는다 — 사이트마다 주는 게 달라서
        전부 None 인 경우가 흔한데, 그걸 다 적으면 표만 부풀고 읽기 어려워진다.
        """
        f = {k: v for k, v in f.items() if v is not None}
        if not f:
            return False
        f = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
             for k, v in f.items()}
        now = datetime.now(timezone.utc)
        base = {"source_code": source_code, "source_uid": source_uid,
                "stat_date": now.strftime("%Y-%m-%d"), "captured_at": now.isoformat()}
        cols = list(base) + list(f)
        # 같은 날 다시 재면 새 값으로 바꾼다. 단 이번에 못 잰 칸은 지키기.
        upd = ", ".join(f"{k}=COALESCE(excluded.{k}, product_stat.{k})" for k in f)
        with self.tx() as c:
            c.execute(
                f"""INSERT INTO product_stat ({', '.join(cols)})
                    VALUES ({', '.join('?' * len(cols))})
                    ON CONFLICT(source_code, source_uid, stat_date) DO UPDATE SET
                      {upd}, captured_at = excluded.captured_at""",
                list(base.values()) + list(f.values()))
        return True

    def put_price_snapshot(self, source_code: str, source_uid: str, price: int,
                           **f) -> bool:
        """가격·등급·판매 상태를 관측 시각별로 보존한다."""
        if price is None:
            return False
        allowed = {"initial_ask_price", "discount", "condition_grade",
                   "availability_state"}
        vals = {k: v for k, v in f.items() if k in allowed and v is not None}
        captured_at = datetime.now(timezone.utc).isoformat()
        cols = ["source_code", "source_uid", "captured_at", "price"] + list(vals)
        with self.tx() as c:
            c.execute(
                f"INSERT OR IGNORE INTO product_price_snapshot ({', '.join(cols)}) "
                f"VALUES ({', '.join('?' * len(cols))})",
                [source_code, source_uid, captured_at, int(price)] + list(vals.values()))
        return True

    def latest_stats(self, source_code: str, uids: Iterable[str]) -> dict[str, dict]:
        """상품별 가장 최근 지표 한 줄씩."""
        uids = list(uids)
        if not uids:
            return {}
        q = ",".join("?" * len(uids))
        with self._lock:
            rs = self._conn.execute(
                f"""SELECT s.* FROM product_stat s
                    JOIN (SELECT source_uid, max(stat_date) d FROM product_stat
                          WHERE source_code=? AND source_uid IN ({q})
                          GROUP BY source_uid) m
                      ON s.source_uid=m.source_uid AND s.stat_date=m.d
                    WHERE s.source_code=?""",
                [source_code] + uids + [source_code]).fetchall()
        return {r["source_uid"]: dict(r) for r in rs}

    # ── 리세일 ─────────────────────────────────────────────────
    def put_listing(self, source_code: str, source_uid: str, price: int,
                    listing_type: str, **f) -> None:
        """체결가인지 호가인지를 반드시 받는다.

        listing_type 을 기본값 있는 인자로 두지 않은 건 의도적이다 —
        섞이면 리세일 지수가 통째로 망가지므로 매번 명시하게 만든다.
        """
        # settled 체결가 · ask 판매호가 · bid 구매호가 · retail 커머스 정상판매가
        # retail 은 무신사·지그재그·에이블리처럼 '팔려고 내놓은 새 상품 가격'이다.
        # 리세일 시세와 성격이 완전히 달라서 반드시 구분해 담는다 —
        # 섞으면 중고 시세에 신품 정가가 끼어들어 지수가 엉뚱해진다.
        if listing_type not in ("settled", "ask", "bid", "retail"):
            raise ValueError(
                f"listing_type 은 settled/ask/bid/retail 중 하나여야 합니다: {listing_type!r}"
            )
        cols = ["source_code", "source_uid", "price", "listing_type"] + list(f.keys())
        vals = [source_code, source_uid, price, listing_type] + list(f.values())
        with self.tx() as c:
            c.execute(
                f"""INSERT OR REPLACE INTO resale_listing ({', '.join(cols)})
                    VALUES ({', '.join('?' * len(cols))})""",
                vals,
            )

    # ── 텍스트 ─────────────────────────────────────────────────
    def put_text(self, source_code: str, doc_kind: str, body: str, **f) -> int | None:
        # 작성자 식별정보는 받지 않는다. 해시만 남긴다.
        if "author_name" in f:
            f["author_hash"] = sha256(f.pop("author_name"))[:16]
        cols = ["source_code", "doc_kind", "body"] + list(f.keys())
        vals = [source_code, doc_kind, body] + list(f.values())
        text_id = None
        with self.tx() as c:
            cur = c.execute(
                f"""INSERT OR IGNORE INTO text_document ({', '.join(cols)})
                    VALUES ({', '.join('?' * len(cols))})""",
                vals,
            )
            if cur.rowcount:
                text_id = cur.lastrowid
        # 신규 글은 저장 직후 무료 사전 연결까지 끝낸다. 실패해도 원문 저장은 지킨다.
        linker = self.text_entity_linker
        if text_id and linker is not None:
            try:
                row = {"id": text_id, "source_code": source_code,
                       "doc_kind": doc_kind, "body": body, **f}
                result, mentions = linker.rules_only(row)
                self.put_entity_resolution(text_id, result, mentions)
            except Exception:
                pass
        return text_id

    def dedupe_social_texts(self) -> dict:
        """동일 플랫폼·영상/검색어에 반복 저장된 완전 동일 본문을 한 건만 남긴다.

        서로 다른 사용자가 쓴 짧은 같은 문장은 합치지 않도록 작성자/게시시각이
        모두 다른 행은 보존한다. API 재호출로 생긴 동일 행만 제거한다.
        """
        with self.tx() as c:
            rows = c.execute(
                "SELECT id,source_code,COALESCE(product_uid,''),"
                "lower(trim(replace(replace(body,char(13),' '),char(10),' '))) body_key,"
                "COALESCE(author_hash,'') "
                "FROM text_document WHERE source_code IN ('youtube','naver') ORDER BY id"
            ).fetchall()
            keep, duplicates = {}, []
            for row in rows:
                key = tuple(row[1:])
                if key in keep:
                    duplicates.append((int(row[0]), keep[key]))
                else:
                    keep[key] = int(row[0])
            for text_id, keep_id in duplicates:
                c.execute("UPDATE text_document SET parent_id=? WHERE parent_id=?",
                          (keep_id, text_id))
                c.execute("DELETE FROM text_entity_opinion WHERE text_document_id=?", (text_id,))
                c.execute("DELETE FROM text_entity_mention WHERE text_document_id=?", (text_id,))
                c.execute("DELETE FROM text_entity_resolution WHERE text_document_id=?", (text_id,))
                c.execute("DELETE FROM text_llm_analysis WHERE text_document_id=?", (text_id,))
                c.execute("DELETE FROM text_document WHERE id=?", (text_id,))
        return {"removed": len(duplicates), "scanned": len(rows)}

    # ── 체크포인트 ─────────────────────────────────────────────
    def save_cursor(self, job_key: str, cursor: str, done: int, total: Optional[int] = None):
        with self.tx() as c:
            c.execute(
                """INSERT INTO checkpoint (job_key, cursor, done_count, total_hint, updated_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(job_key) DO UPDATE SET
                     cursor=excluded.cursor, done_count=excluded.done_count,
                     total_hint=COALESCE(excluded.total_hint, checkpoint.total_hint),
                     updated_at=excluded.updated_at""",
                (job_key, cursor, done, total, _now()),
            )

    def load_cursor(self, job_key: str) -> Optional[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM checkpoint WHERE job_key=?", (job_key,)
            ).fetchone()

    def seen(self, url: str) -> bool:
        with self._lock:
            return self._conn.execute(
                "SELECT 1 FROM seen_url WHERE url=?", (url,)
            ).fetchone() is not None

    def mark_seen(self, url: str, source_code: str, status: int):
        with self.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO seen_url (url, source_code, http_status) VALUES (?,?,?)",
                (url, source_code, status),
            )

    # ── 실행 기록 ──────────────────────────────────────────────
    def start_run(self, source_code: str, target: str) -> int:
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO crawl_run (source_code, target, started_at) VALUES (?,?,?)",
                (source_code, target, _now()),
            )
            return cur.lastrowid

    def end_run(self, run_id: int, status: str, fetched: int, errors: int,
                blocked: bool = False, note: str = ""):
        with self.tx() as c:
            c.execute(
                """UPDATE crawl_run SET ended_at=?, status=?, fetched_count=?,
                   error_count=?, blocked=?, note=? WHERE id=?""",
                (_now(), status, fetched, errors, int(blocked), note, run_id),
            )

    # ── 현황 ───────────────────────────────────────────────────
    def stats(self) -> dict:
        def q(sql):
            return self._conn.execute(sql).fetchone()[0]

        with self._lock:
            sources = {r[0]: r[1] for r in self._conn.execute(
                "SELECT source_code,count(*) FROM staging_product GROUP BY source_code")}
            return {
                "raw": q("SELECT count(*) FROM raw_document"),
                "products": q("SELECT count(*) FROM staging_product"),
                "listings": q("SELECT count(*) FROM resale_listing"),
                "settled": q("SELECT count(*) FROM resale_listing WHERE listing_type='settled'"),
                "asks": q("SELECT count(*) FROM resale_listing WHERE listing_type='ask'"),
                "texts": q("SELECT count(*) FROM text_document"),
                "seen_urls": q("SELECT count(*) FROM seen_url"),
                "sources": sources,
            }

    def last_seen_by_source(self) -> dict:
        """사이트마다 '언제 마지막으로 뭔가 들어왔나'.

        수집 탭이 지금까지 '다음 수집 3시간 뒤'만 보여 줬다. 그런데 정작
        궁금한 건 그 반대다 — **마지막으로 들어온 게 언제냐**. 하루 전에
        멈춰 있어도 화면은 똑같이 '3시간 뒤'라고만 적혀서 알 길이 없었다.
        (무신사가 실제로 그랬다. 8/24 이후로 한 건도 안 들어왔다.)

        두 가지를 같이 준다. 실행이 돌았어도 0건이면 소용없기 때문이다.
          run   — 마지막으로 수집을 돌린 시각
          data  — 마지막으로 상품이 실제로 갱신된 시각
        """
        out: dict[str, dict] = {}
        with self._lock:
            for r in self._conn.execute(
                    "SELECT source_code, max(started_at) t, count(*) n "
                    "FROM crawl_run GROUP BY source_code"):
                out.setdefault(r["source_code"], {})["run"] = r["t"]
                out[r["source_code"]]["runs"] = r["n"]
            for r in self._conn.execute(
                    "SELECT source_code, max(last_seen_at) t, count(*) n "
                    "FROM staging_product GROUP BY source_code"):
                d = out.setdefault(r["source_code"], {})
                d["data"] = r["t"]
                d["products"] = r["n"]
        return out

    def recent_runs(self, limit: int = 12) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM crawl_run ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ── 조회 · 관리 (대시보드 '데이터' 탭) ─────────────────────
    #
    # 리세일 행의 source_uid 는 '<상품uid>:list' / ':now' / ':t0' 형태다.
    # 상품 기준으로 묶으려면 콜론 앞부분을 잘라내야 한다.
    _PUID = ("CASE WHEN instr(source_uid, ':') > 0 "
             "THEN substr(source_uid, 1, instr(source_uid, ':') - 1) "
             "ELSE source_uid END")

    _AGG_CTE = f"""
    WITH lz AS (
      SELECT source_code, {_PUID} AS puid, listing_type, price, settled_at
      FROM resale_listing
    ),
    agg AS (
      SELECT source_code, puid,
        sum(listing_type = 'settled')                          AS settled_n,
        sum(listing_type = 'ask')                              AS ask_n,
        min(CASE WHEN listing_type='settled' THEN price END)   AS settled_min,
        max(CASE WHEN listing_type='settled' THEN price END)   AS settled_max,
        avg(CASE WHEN listing_type='settled' THEN price END)   AS settled_avg,
        max(CASE WHEN listing_type='ask'     THEN price END)   AS ask_price,
        -- ★ retail(커머스 정상판매가)을 빼먹으면 무신사·지그재그·에이블리가
        --   전부 '가격 없음'으로 잡혀 점검이 매번 거짓 경보를 낸다.
        --   거짓 경보가 반복되면 사람이 경고를 안 믿게 되는 게 더 큰 문제다.
        max(CASE WHEN listing_type='retail'  THEN price END)   AS retail_now,
        sum(listing_type = 'retail')                           AS retail_n
      FROM lz GROUP BY source_code, puid
    )
    """

    # 품질 필터 — 1차 실측에서 정말 보고 싶은 건 "무엇이 비었나"다
    ISSUE_SQL = {
        "all":       "1=1",
        "noname":    "(p.name IS NULL OR trim(p.name) = '')",
        "noprice":   "COALESCE(a.ask_price, a.retail_now, a.settled_avg) IS NULL",
        "nomodel":   "(p.model_code IS NULL OR trim(p.model_code) = '')",
        "nosettled": "COALESCE(a.settled_n, 0) = 0",
        # ★ 오래된 것 — 파서를 고친 뒤 옛 수집분을 골라 다시 받으려고 만들었다.
        #   크림 상세 153장이 8/24 에 들어왔는데 그때 리뷰가 1% 밖에 안 잡혔다.
        #   8/25 에 고친 뒤로는 93% 다. 이 필터로 옛 것만 골라 [다시 받기] 하면 된다.
        "stale":     "p.last_seen_at < datetime('now', '-1 day')",
        "nobrand":   "(p.brand_name IS NULL OR trim(p.brand_name) = '')",
        "issues":    ("((p.name IS NULL OR trim(p.name)='') "
                      " OR COALESCE(a.ask_price, a.retail_now, a.settled_avg) IS NULL "
                      " OR (p.brand_name IS NULL OR trim(p.brand_name)=''))"),
    }

    # 상품마다 '가장 최근 잰 지표' 한 줄. 날짜가 여러 개라 max 로 고른다.
    _STAT_CTE = """
    , st AS (
      SELECT s.* FROM product_stat s
      JOIN (SELECT source_code, source_uid, max(stat_date) d FROM product_stat
            GROUP BY source_code, source_uid) m
        ON s.source_code=m.source_code AND s.source_uid=m.source_uid AND s.stat_date=m.d
    )
    """

    SORT_SQL = {
        "recent":   "p.last_seen_at DESC, p.id DESC",
        # ★ 인기순 — 사이트마다 있는 지표가 달라서 하나로 못 세운다.
        #   있는 것 중 가장 큰 신호를 쓴다. 거래 > 후기 > 관심 > 구매 순으로
        #   '실제 돈이 오간 정도'에 가까운 것을 앞에 둔다.
        "popular":  ("COALESCE(st.trade_count, st.review_count, st.wish_count, "
                     "st.buy_count, 0) DESC, p.id DESC"),
        "rank":     "st.rank IS NULL, st.rank ASC",
        "oldest":   "p.last_seen_at ASC, p.id ASC",
        "settled":  "COALESCE(a.settled_n,0) DESC, p.id DESC",
        "pricehi":  "COALESCE(a.ask_price, a.retail_now, a.settled_avg) DESC",
        "pricelo":  "COALESCE(a.ask_price, a.retail_now, a.settled_avg) ASC",
        "name":     "p.name ASC",
    }

    def browse_products(self, source_code: Optional[str] = None, q: str = "",
                        issue: str = "all", sort: str = "recent",
                        limit: int = 50, offset: int = 0) -> dict:
        where, args = ["1=1"], []
        if source_code and source_code != "all":
            where.append("p.source_code = ?")
            args.append(source_code)
        if q:
            where.append("(p.name LIKE ? OR p.brand_name LIKE ? OR p.model_code LIKE ? "
                         "OR p.source_uid LIKE ?)")
            args += [f"%{q}%"] * 4
        where.append(self.ISSUE_SQL.get(issue, "1=1"))
        w = " AND ".join(where)
        order = self.SORT_SQL.get(sort, self.SORT_SQL["recent"])

        base = f"""{self._AGG_CTE}{self._STAT_CTE}
          SELECT p.*, a.settled_n, a.ask_n, a.settled_min, a.settled_max,
                 a.settled_avg, a.ask_price, a.retail_now, a.retail_n,
                 st.rank, st.review_count, st.review_score, st.wish_count,
                 st.trade_count, st.buy_count, st.style_count, st.discount,
                 st.review_dist, st.fit_note, st.thickness_note, st.quality_note
          FROM staging_product p
          LEFT JOIN agg a ON a.source_code = p.source_code AND a.puid = p.source_uid
          LEFT JOIN st ON st.source_code = p.source_code AND st.source_uid = p.source_uid
          WHERE {w}"""

        with self._lock:
            total = self._conn.execute(
                f"""{self._AGG_CTE}{self._STAT_CTE}
                    SELECT count(*) FROM staging_product p
                    LEFT JOIN agg a ON a.source_code=p.source_code AND a.puid=p.source_uid
                    LEFT JOIN st ON st.source_code=p.source_code AND st.source_uid=p.source_uid
                    WHERE {w}""", args).fetchone()[0]
            rows = self._conn.execute(
                f"{base} ORDER BY {order} LIMIT ? OFFSET ?", args + [limit, offset]
            ).fetchall()
        return {"total": total, "rows": [dict(r) for r in rows],
                "limit": limit, "offset": offset}

    def product_detail(self, source_code: str, source_uid: str) -> dict:
        with self._lock:
            p = self._conn.execute(
                "SELECT * FROM staging_product WHERE source_code=? AND source_uid=?",
                (source_code, source_uid)).fetchone()
            if not p:
                return {}
            listings = self._conn.execute(
                f"""SELECT * FROM resale_listing
                    WHERE source_code=? AND {self._PUID} = ?
                    ORDER BY (listing_type='settled') DESC, settled_at DESC, id DESC
                    LIMIT 400""", (source_code, source_uid)).fetchall()
            raws = self._conn.execute(
                """SELECT id, doc_type, url, http_status, fetched_at, payload
                   FROM raw_document WHERE source_code=? AND source_uid=?
                   ORDER BY id DESC LIMIT 5""", (source_code, source_uid)).fetchall()
            texts = self._conn.execute(
                """SELECT id, doc_kind, substr(body,1,600) AS body, rating, published_at
                   FROM text_document WHERE source_code=? AND product_uid=?
                   ORDER BY id DESC LIMIT 20""", (source_code, source_uid)).fetchall()
            # 지표 추이 — 후기가 며칠 새 얼마나 늘었는지 보려면 여러 날이 필요하다
            statrows = self._conn.execute(
                """SELECT * FROM product_stat WHERE source_code=? AND source_uid=?
                   ORDER BY stat_date DESC LIMIT 60""",
                (source_code, source_uid)).fetchall()
        return {
            "product": dict(p),
            "stats": [dict(r) for r in statrows],
            "listings": [dict(r) for r in listings],
            "raws": [dict(r) for r in raws],
            "texts": [dict(r) for r in texts],
        }

    def delete_products(self, keys: Iterable[tuple[str, str]], forget_url: bool = True) -> dict:
        """상품과 딸린 기록을 지운다.

        forget_url 을 켜면 seen_url 에서도 지워, 다음 실행 때 다시 받아온다.
        이걸 안 하면 '지웠는데 영영 다시 안 받아지는' 상태가 된다 —
        잘못 긁힌 걸 지우는 게 목적일 텐데 그러면 목적을 못 이룬다.
        """
        n = {"products": 0, "listings": 0, "raw": 0, "texts": 0, "urls": 0}
        with self.tx() as c:
            for code, uid in keys:
                row = c.execute("SELECT source_url FROM staging_product "
                                "WHERE source_code=? AND source_uid=?",
                                (code, uid)).fetchone()
                n["listings"] += c.execute(
                    f"DELETE FROM resale_listing WHERE source_code=? AND {self._PUID}=?",
                    (code, uid)).rowcount
                n["raw"] += c.execute(
                    "DELETE FROM raw_document WHERE source_code=? AND source_uid=?",
                    (code, uid)).rowcount
                n["texts"] += c.execute(
                    "DELETE FROM text_document WHERE source_code=? AND product_uid=?",
                    (code, uid)).rowcount
                n["products"] += c.execute(
                    "DELETE FROM staging_product WHERE source_code=? AND source_uid=?",
                    (code, uid)).rowcount
                if forget_url and row and row["source_url"]:
                    n["urls"] += c.execute(
                        "DELETE FROM seen_url WHERE url=?", (row["source_url"],)).rowcount
        return n

    def forget_urls(self, keys: Iterable[tuple[str, str]]) -> int:
        """데이터는 두고 '본 적 없음'으로만 되돌린다 → 다음 실행 때 다시 받아 덮어쓴다."""
        n = 0
        with self.tx() as c:
            for code, uid in keys:
                row = c.execute("SELECT source_url FROM staging_product "
                                "WHERE source_code=? AND source_uid=?",
                                (code, uid)).fetchone()
                if row and row["source_url"]:
                    n += c.execute("DELETE FROM seen_url WHERE url=?",
                                   (row["source_url"],)).rowcount
        return n

    def data_summary(self, source_code: Optional[str] = None) -> dict:
        """품질 요약 — 어느 칸이 얼마나 비었는지. 설정을 고칠 근거가 된다."""
        cond, args = ("p.source_code = ?", [source_code]) \
            if source_code and source_code != "all" else ("1=1", [])
        with self._lock:
            r = self._conn.execute(f"""{self._AGG_CTE}
              SELECT count(*) AS total,
                sum(p.name IS NULL OR trim(p.name)='')                 AS noname,
                sum(p.brand_name IS NULL OR trim(p.brand_name)='')     AS nobrand,
                sum(p.model_code IS NULL OR trim(p.model_code)='')     AS nomodel,
                sum(COALESCE(a.ask_price, a.retail_now, a.settled_avg) IS NULL) AS noprice,
                sum(COALESCE(a.settled_n,0) = 0)                       AS nosettled,
                sum(p.image_url IS NULL OR trim(p.image_url)='')       AS noimage
              FROM staging_product p
              LEFT JOIN agg a ON a.source_code=p.source_code AND a.puid=p.source_uid
              WHERE {cond}""", args).fetchone()
            by_src = self._conn.execute(
                "SELECT source_code, count(*) n FROM staging_product GROUP BY source_code"
            ).fetchall()
        d = dict(r)
        d["by_source"] = [dict(x) for x in by_src]
        return d

    # ── Postgres 이관 ──────────────────────────────────────────
