/* GET /api/assoc?term=발레코어&limit=20
 *
 * 연관어 — `analysis.term_assoc_daily` 를 읽는다.
 * 같은 날 함께 나온 정도(cooccurrence_count)와 연관 점수(association_score),
 * 신뢰도(confidence) 가 들어 있다.
 *
 * ★ 여기서도 점수를 새로 만들지 않는다.
 *   설계서 §2 는 동시출현이 아니라 **리프트(lift)** 를 쓰라고 정해 뒀는데,
 *   그 계산은 크롤러가 한다. 이 함수는 저장된 값을 그대로 옮긴다.
 *   화면과 챗봇이 같은 숫자를 말하게 하려면 계산은 한 곳에만 있어야 한다.
 */

import { q, viaBackend } from './_lib/db.js';
import { ok, empty, failed } from './_lib/reply.js';

export default async function handler(req, res) {
  // Django API 가 설정돼 있으면 그쪽이 먼저다 (RDS 를 열지 않아도 된다).
  const relayed = await viaBackend('/assoc' + (req.url.includes('?') ? '?' + req.url.split('?')[1] : ''));
  if (relayed) {
    res.statusCode = 200;
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.setHeader('Cache-Control', 's-maxage=300, stale-while-revalidate=600');
    return res.end(JSON.stringify(relayed));
  }

  const url = new URL(req.url, 'http://x');
  const term = (url.searchParams.get('term') || '').trim();
  const limit = Math.min(100, Math.max(5, Number(url.searchParams.get('limit') || 20)));

  if (!term) return empty(res, 'term 을 지정해 주세요. 예: /api/assoc?term=발레코어');

  const r = await q(
    `SELECT tgt.canonical_name AS term, tgt.term_type AS facet,
            a.cooccurrence_count, a.association_score, a.confidence, a.metric_date
       FROM analysis.term_assoc_daily a
       JOIN dictionary.dictionary_term src ON src.id = a.source_term_id
       JOIN dictionary.dictionary_term tgt ON tgt.id = a.target_term_id
      WHERE (src.canonical_name = $1 OR src.normalized_name = lower($1))
        AND a.metric_date = (
              SELECT max(metric_date) FROM analysis.term_assoc_daily a2
               WHERE a2.source_term_id = a.source_term_id)
      ORDER BY a.association_score DESC NULLS LAST, a.cooccurrence_count DESC
      LIMIT $2`,
    [term, limit],
  );

  if (!r.ok) return failed(res, `AWS RDS 에 연결하지 못했습니다 (${r.code}).`, { detail: r.error });
  if (!r.rows.length) {
    const any = await q('SELECT count(*) n FROM analysis.term_assoc_daily');
    const 전체 = any.ok ? Number(any.rows[0].n) : null;
    return empty(
      res,
      전체 === 0
        ? 'AWS RDS 의 연관어 표(analysis.term_assoc_daily)가 통째로 비어 있습니다. ' +
            '크롤러가 아직 이 표로 보내지 않습니다.'
        : `‘${term}’ 의 연관어가 아직 없습니다. 함께 나온 글이 모자랍니다.`,
      { term, total_rows: 전체 },
    );
  }

  return ok(res, {
    term,
    as_of: String(r.rows[0].metric_date).slice(0, 10),
    items: r.rows.map((x) => ({
      term: x.term,
      facet: x.facet,
      cooccurrence: Number(x.cooccurrence_count ?? 0),
      score: x.association_score === null ? null : Number(x.association_score),
      confidence: x.confidence === null ? null : Number(x.confidence),
    })),
  });
}
