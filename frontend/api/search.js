/* GET /api/search?term=팬츠&days=90
 *
 * ── 무엇을 돌려주나 ───────────────────────────────────────
 * 검색 기반 지표만 돌려준다 — 네이버 검색광고·데이터랩, 구글 트렌즈·키워드플래너.
 *
 * ★ /api/trend 와 **일부러 나눈 주소**다.
 *   trend 는 '사람이 뭐라고 말했나'(유튜브 댓글·커머스 리뷰)를 센다.
 *   여기는 '사람이 뭘 찾아봤나'를 센다. 둘은 다른 현상이라
 *   한 응답에 섞으면 같은 '온도'라는 말이 두 가지 뜻을 갖게 되고,
 *   화면에서 비교 불가능한 숫자가 나란히 서게 된다.
 *
 * ── 왜 pg 대체 경로가 없나 ────────────────────────────────
 * trend.js 는 백엔드가 없으면 RDS 를 직접 연다. 여기는 안 그런다.
 * 검색 지표는 표가 네 개(monthly·trend·region·segment)라 SQL 을 두 벌 두면
 * 두 곳이 서로 어긋나기 시작한다. 백엔드가 없으면 그렇다고 말하고 만다.
 */

import { viaBackend } from './_lib/db.js';
import { empty } from './_lib/reply.js';

export default async function handler(req, res) {
  const qs = req.url.includes('?') ? '?' + req.url.split('?')[1] : '';
  const relayed = await viaBackend('/search' + qs);

  if (!relayed) {
    return empty(
      res,
      '검색 지표는 Django API 를 통해서만 읽습니다.',
      { detail: '버셀 환경변수 BACKEND_API_URL 이 비어 있습니다.' },
    );
  }

  res.statusCode = 200;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  /* 검색량은 하루 단위로만 바뀐다 — 길게 캐시해도 된다. */
  res.setHeader('Cache-Control', 's-maxage=1800, stale-while-revalidate=3600');
  return res.end(JSON.stringify(relayed));
}
