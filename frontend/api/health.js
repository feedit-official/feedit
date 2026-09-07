/* GET /api/health — 배포된 곳에서 AWS RDS 가 실제로 어떤 상태인지 그대로 본다.
 *
 * ── 왜 제일 먼저 이걸 만드나 ──────────────────────────────
 * 지금까지 RDS 상태는 사용자 맥에서 SSM 굴을 뚫고 확인해 왔다.
 * 그래서 "버셀에서도 되나"는 아무도 몰랐다. 이 엔드포인트를 배포하면
 * 브라우저로 주소 한 번 열어서 **추측 없이** 알 수 있다:
 *
 *   · 버셀 함수가 RDS 에 닿는가
 *   · 어느 표에 몇 행이 있는가
 *   · 지표에 필요한 컬럼(temp·momentum·ma7·ma28)이 있는가
 *
 * 2026-09-02 사용자 맥에서 잰 값은 이랬다 — 다르면 그새 바뀐 것이다:
 *   commerce.product 3,375 · dictionary.brand 2,775 · dictionary_term 394
 *   analysis.term_metric_daily **0** · term_assoc_daily **0** · text_document **0**
 */

import { q, isConfigured } from './_lib/db.js';

// 화면이 쓰는 표만 본다. 47개를 다 세면 느리고, 볼 이유도 없다.
const TABLES = [
  ['commerce.product', '상품'],
  ['commerce.product_source', '상품-출처'],
  ['commerce.product_term', '상품-용어'],
  ['dictionary.brand', '브랜드'],
  ['dictionary.dictionary_term', '용어 사전'],
  ['dictionary.term_alias', '용어 별칭'],
  ['snapshot.product_source_snapshot', '가격 스냅샷'],
  ['snapshot.resale_snapshot', '리세일 스냅샷'],
  ['analysis.term_metric_daily', '★ 트렌드 지표'],
  ['analysis.term_assoc_daily', '★ 연관어'],
  ['analysis.text_document', '텍스트 원문'],
  ['collection.source', '수집 출처'],
];

export default async function handler(req, res) {
  const out = {
    checked_at: new Date().toISOString(),
    configured: isConfigured(),
    connected: false,
    server: null,
    tables: {},
    metric_columns: null,
    verdict: '',
  };

  if (!out.configured) {
    out.verdict =
      'AWS RDS 접속 정보가 없습니다. 버셀 Settings → Environment Variables 에 ' +
      'DATABASE_URL 을 넣고 다시 배포하세요.';
    return json(res, out);
  }

  const ver = await q('SELECT version() AS v, current_database() AS db');
  if (!ver.ok) {
    out.verdict =
      `RDS 에 못 붙었습니다 (${ver.code}). ` +
      'RDS 가 밖에서 보이는지(공개 접근 · 보안 그룹)를 DB 팀과 확인하세요.';
    out.detail = ver.error;
    return json(res, out);
  }
  out.connected = true;
  out.server = { version: String(ver.rows[0].v).split(',')[0], database: ver.rows[0].db };

  // 표별 행 수 — 한 번의 질의로 끝낸다.
  const union = TABLES.map(([t], i) => `SELECT ${i} i, count(*) n FROM ${t}`).join(' UNION ALL ');
  const counts = await q(union);
  if (counts.ok) {
    for (const row of counts.rows) {
      const [name, label] = TABLES[Number(row.i)];
      out.tables[name] = { label, rows: Number(row.n) };
    }
  } else {
    out.tables_error = counts.error;
  }

  // ★ 지표 컬럼이 있는지 — 없으면 온도·모멘텀을 아예 못 보낸다.
  //   RDS(Django) 쪽에는 mention_count·trend_score 만 있고
  //   temp·momentum·ma7·ma28 이 없다는 게 2026-09-02 확인이었다.
  const cols = await q(
    `SELECT column_name FROM information_schema.columns
      WHERE table_schema='analysis' AND table_name='term_metric_daily'
      ORDER BY ordinal_position`,
  );
  if (cols.ok) {
    const have = cols.rows.map((r) => r.column_name);
    const want = ['temp', 'momentum', 'ma7', 'ma28', 'level', 'pct_rank'];
    out.metric_columns = {
      all: have,
      needed_present: want.filter((c) => have.includes(c)),
      needed_missing: want.filter((c) => !have.includes(c)),
    };
  }

  out.verdict = verdict(out);
  return json(res, out);
}

function verdict(o) {
  const metric = o.tables['analysis.term_metric_daily'];
  const product = o.tables['commerce.product'];
  const bits = [];

  if (metric && metric.rows > 0) {
    bits.push(`트렌드 지표 ${metric.rows.toLocaleString()}행 — 화면에 실값을 띄울 수 있습니다.`);
  } else if (metric) {
    bits.push(
      '트렌드 지표가 0행입니다. 크롤러의 rds_sync 는 commerce·dictionary·snapshot 8개 표에만 ' +
        '쓰고 analysis.* 에는 쓰지 않습니다 — 보내는 코드가 아직 없는 것이지 연결이 끊긴 게 아닙니다.',
    );
  }
  if (product && product.rows > 0) {
    bits.push(`상품은 ${product.rows.toLocaleString()}건 있어 목록·가격은 실값으로 보여 줄 수 있습니다.`);
  }
  if (o.metric_columns && o.metric_columns.needed_missing.length) {
    bits.push(
      `지표 표에 ${o.metric_columns.needed_missing.join('·')} 컬럼이 없습니다. ` +
        '온도·모멘텀을 보내려면 metrics(JSON) 에 담거나 스키마를 고쳐야 합니다 — DB 팀과 정할 일입니다.',
    );
  }
  return bits.join(' ');
}

function json(res, body) {
  res.statusCode = 200;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store'); // 진단은 늘 지금 값이어야 한다
  res.end(JSON.stringify(body, null, 1));
}
