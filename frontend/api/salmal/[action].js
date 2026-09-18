/* 살!말? 조회·카드 생성을 Django로 중계한다. */
import { backendBase, backendToken } from '../_lib/db.js';

const ALLOWED = new Set(['cards']);

export default async function handler(req, res) {
  const url = new URL(req.url, 'http://x');
  const action = url.pathname.replace(/^\/api\/salmal\//, '').split('/')[0];
  const method = String(req.method || 'GET').toUpperCase();
  if (!ALLOWED.has(action) || !['GET', 'POST', 'DELETE'].includes(method)) {
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
  if (req.headers['x-csrftoken']) headers['X-CSRFToken'] = req.headers['x-csrftoken'];
  if (req.headers.origin) headers.Origin = req.headers.origin;
  if (req.headers.referer) headers.Referer = req.headers.referer;
  let body;
  if (method === 'POST') {
    headers['Content-Type'] = 'application/json';
    body = typeof req.body === 'string' ? req.body : JSON.stringify(req.body || {});
  }
  const query = url.searchParams.toString();
  const upstreamPath = url.pathname.replace(/^\/api/, '');
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    const upstream = await fetch(`${base}${upstreamPath}${query ? `?${query}` : ''}`, {
      method, headers, body, signal:controller.signal, redirect:'manual',
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
