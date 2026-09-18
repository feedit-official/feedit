/* 살!말? 읽기 API를 Django로 중계한다. 세션 쿠키도 전달해 취향 태그를 적용한다. */
import { backendBase, backendToken } from '../_lib/db.js';

const ALLOWED = new Set(['cards']);

export default async function handler(req, res) {
  const url = new URL(req.url, 'http://x');
  const action = url.pathname.replace(/^\/api\/salmal\//, '').split('/')[0];
  if (!ALLOWED.has(action) || String(req.method || 'GET').toUpperCase() !== 'GET') {
    return send(res, 404, { status:'error', reason:'없는 살말 주소입니다.', data:null });
  }
  const base = backendBase();
  if (!base) return send(res, 503, {
    status:'error', reason:'BACKEND_API_URL이 설정되지 않아 살말 데이터를 불러올 수 없습니다.', data:null,
  });
  const headers = { Accept:'application/json' };
  const token = backendToken();
  if (token) headers['X-FEEDiT-Token'] = token;
  if (req.headers.cookie) headers.Cookie = req.headers.cookie;
  const query = url.searchParams.toString();
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    const upstream = await fetch(`${base}/salmal/cards${query ? `?${query}` : ''}`, {
      headers, signal:controller.signal,
    });
    clearTimeout(timer);
    return sendText(res, upstream.status, await upstream.text());
  } catch (error) {
    return send(res, 502, {
      status:'error', reason:'살말 서버에 연결하지 못했습니다.',
      detail:String(error && error.message || error).slice(0, 140), data:null,
    });
  }
}

function send(res, status, body) {
  return sendText(res, status, JSON.stringify(body));
}

function sendText(res, status, body) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  return res.end(body);
}
