/* GET /api/v1/magazines?term=발레코어 — 금주의 리포트 '추천 웹매거진'.
 *
 * FEEDiT DB 에는 웹매거진 자료가 없어서, 챗봇 서버(ChatBot/app/magazine.py)가
 * 웹 검색으로 그 키워드를 다룬 매거진 기사를 찾는다. 여기서는 그대로 중계만 한다.
 * 브라우저가 챗봇 서버 주소나 공유 토큰을 알지 않도록 chat.js 와 같은 경계를 쓴다.
 */
export default async function handler(req, res) {
  if (req.method !== 'GET') return json(res, 405, { ok:false, reason:'GET 요청만 지원합니다.' });
  const backend = (process.env.CHAT_BACKEND_URL || '').replace(/\/+$/, '');
  if (!backend) return json(res, 503, { ok:false, reason:'웹 검색 서버 주소(CHAT_BACKEND_URL)가 설정되지 않았습니다.' });

  const term = String(new URL(req.url, 'http://x').searchParams.get('term') || '').trim().slice(0, 40);
  if (!term) return json(res, 400, { ok:false, reason:'term 을 지정해 주세요.' });

  try {
    const headers = { Accept:'application/json' };
    if (process.env.CHAT_BACKEND_TOKEN) headers['X-FEEDiT-Token'] = process.env.CHAT_BACKEND_TOKEN;
    const c = new AbortController();
    const t = setTimeout(() => c.abort(), 28000);   /* 웹 검색은 10~20초 걸린다 */
    const upstream = await fetch(backend + '/v1/magazines?term=' + encodeURIComponent(term), { headers, signal:c.signal });
    clearTimeout(t);
    const text = await upstream.text();
    let payload;
    try { payload = JSON.parse(text); }
    catch { return json(res, 502, { ok:false, reason:`웹 검색 서버가 올바른 응답을 보내지 않았습니다 (HTTP ${upstream.status}).` }); }
    /* 찾은 결과만 버셀 가장자리에서 6시간 캐시한다 — 실패는 캐시하지 않는다 */
    if (upstream.ok && payload.found) res.setHeader('Cache-Control', 's-maxage=21600, stale-while-revalidate=3600');
    return json(res, upstream.status, payload);
  } catch (e) {
    return json(res, 504, { ok:false, reason:'웹 검색 서버에 닿지 못했습니다.' });
  }
}

function json(res, status, body) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  if (!res.getHeader('Cache-Control')) res.setHeader('Cache-Control', 'no-store');
  res.end(JSON.stringify(body));
}
