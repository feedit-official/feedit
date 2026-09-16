/* GET /api/discount · /api/resale · /api/lifecycle
 *
 * 트렌드 분석의 할인률 변화 · 리세일 시세 지수 · 수명주기 탭이 부르는 창구.
 * 세 주소를 **함수 하나**로 받는다 — 버셀 Hobby 요금제는 함수 개수가 12개로 묶여 있어
 * 탭마다 파일을 따로 두면 배포가 막힌다.
 *
 * ★ 계산은 Django(backend/apps/api/views.py)가 한다. 여기서는 그대로 넘기기만 한다.
 *   RDS 의 스냅샷 표를 여러 번 훑어 집계해야 해서, pg 직결로 똑같이 짜 두면
 *   화면과 백엔드가 서로 다른 숫자를 말하게 된다. 그래서 BACKEND_API_URL 이 필수다.
 *
 * 필요한 버셀 환경변수:
 *   BACKEND_API_URL    Django 주소 (예: https://feedit-official.duckdns.org/api)
 *   BACKEND_API_TOKEN  서버 .env 의 FEEDIT_API_TOKEN 과 같은 값
 */

import { viaBackend } from './_lib/db.js';
import { failed } from './_lib/reply.js';

const ALLOWED = new Set(['discount', 'resale', 'lifecycle']);

export default async function handler(req, res) {
  const url = new URL(req.url, 'http://x');
  // 파일 이름 [kind] 로 들어온 값 — 쿼리에도 kind 로 붙어 오므로 경로에서 직접 읽는다.
  const kind = url.pathname.replace(/^\/api\//, '').split('/')[0];
  if (!ALLOWED.has(kind)) {
    res.statusCode = 404;
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    return res.end(JSON.stringify({ status: 'error', reason: `없는 주소입니다: /api/${kind}`, data: null }));
  }

  const qs = new URLSearchParams(url.search);
  qs.delete('kind');
  const q = qs.toString();
  const relayed = await viaBackend(`/${kind}` + (q ? `?${q}` : ''));
  if (!relayed) {
    return failed(
      res,
      'BACKEND_API_URL 이 설정돼 있지 않습니다. 이 지표는 Django API 를 거쳐야 계산됩니다 (버셀 환경변수).',
    );
  }
  res.statusCode = 200;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 's-maxage=300, stale-while-revalidate=600');
  return res.end(JSON.stringify(relayed));
}
