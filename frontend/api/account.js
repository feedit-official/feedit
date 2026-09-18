/* 브라우저 세션을 유지하는 Vercel → Django 계정 프록시.
 * 서비스 토큰은 서버끼리만 공유하고, Django의 Set-Cookie는 같은 출처인
 * Vercel 응답으로 그대로 전달한다. 사용자 데이터는 Vercel에 저장하지 않는다.
 */
import { backendBase, backendToken } from './_lib/db.js';

export default async function handler(req, res) {
  const base = backendBase();
  if (!base) {
    return res.status(503).json({ status: 'error', reason: 'BACKEND_API_URL이 설정되지 않았습니다.', data: null });
  }
  const action = String(req.query?.action || 'me').slice(0, 40);
  const headers = { Accept: 'application/json' };
  const token = backendToken();
  if (token) headers['X-FEEDiT-Token'] = token;
  if (req.headers.cookie) headers.Cookie = req.headers.cookie;
  let body;
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    headers['Content-Type'] = 'application/json';
    body = typeof req.body === 'string' ? req.body : JSON.stringify(req.body || {});
  }
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    const upstream = await fetch(`${base}/account?action=${encodeURIComponent(action)}`, {
      method: req.method, headers, body, signal: controller.signal,
    });
    clearTimeout(timer);
    const cookie = upstream.headers.get('set-cookie');
    if (cookie) res.setHeader('Set-Cookie', cookie);
    const text = await upstream.text();
    res.status(upstream.status);
    res.setHeader('Content-Type', upstream.headers.get('content-type') || 'application/json; charset=utf-8');
    return res.send(text);
  } catch (error) {
    return res.status(502).json({
      status: 'error', reason: `계정 서버에 연결하지 못했습니다: ${String(error?.message || error).slice(0, 120)}`, data: null,
    });
  }
}
