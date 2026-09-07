/* POST /api/v1/chat — 챗봇 질문을 뒤 서버로 넘기고 SSE 를 그대로 흘려보낸다.
 *
 * ── 왜 그대로 넘기기만 하나 ───────────────────────────────
 * 챗봇의 머리는 `Final/feedit-chat` 에 있다. 질문 이해(nlu)·어휘 추출·
 * 블록 조립(templates.py)이 전부 거기 있고, 응답 구조의 원본도 거기다.
 * 그걸 여기 자바스크립트로 옮겨 적으면 **같은 규칙이 두 곳에 살게 된다.**
 * 한쪽만 고치는 날 화면과 챗봇이 다른 말을 한다.
 *
 * 그래서 이 함수는 판단을 하지 않는다. 길만 낸다:
 *
 *     브라우저 ──/api/v1/chat──▶ 버셀 함수 ──▶ CHAT_BACKEND_URL (feedit-chat)
 *
 * 같은 도메인이라 CORS 도 없고, 뒤 서버 주소가 브라우저에 안 드러난다.
 *
 * ── 뒤 서버가 없을 때 ─────────────────────────────────────
 * 500 을 던지지 않는다. 화면이 읽는 것과 **같은 SSE 모양**으로
 * "지금은 답할 수 없다"고 말한다. 그래야 팝업이 깨지지 않고,
 * 사용자도 무엇이 빠졌는지 안다. 조용히 그럴듯한 답을 지어내지 않는다.
 */

export const config = { runtime: 'nodejs' };

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    res.statusCode = 405;
    return res.end('POST 만 받습니다.');
  }

  const backend = (process.env.CHAT_BACKEND_URL || '').replace(/\/+$/, '');
  res.setHeader('Content-Type', 'text/event-stream; charset=utf-8');
  res.setHeader('Cache-Control', 'no-cache, no-transform');
  res.setHeader('Connection', 'keep-alive');

  if (!backend) return sayUnavailable(res);

  let body = '';
  try {
    body = await readBody(req);
  } catch {
    return sayUnavailable(res, '질문을 읽지 못했습니다.');
  }

  try {
    const upstream = await fetch(backend + '/v1/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
    });
    if (!upstream.ok || !upstream.body) {
      return sayUnavailable(res, `챗봇 서버가 ${upstream.status} 를 돌려줬습니다.`);
    }
    // 조각을 모으지 않고 오는 대로 흘린다 — 글자가 한 번에 쏟아지면
    // '생각하는 중' 느낌이 사라지고, 긴 답은 시간 초과에 걸린다.
    const reader = upstream.body.getReader();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      res.write(Buffer.from(value));
    }
    res.end();
  } catch (e) {
    sayUnavailable(res, `챗봇 서버에 닿지 못했습니다: ${String(e.message || e).slice(0, 120)}`);
  }
}

/** 화면이 읽는 것과 같은 순서로 — status → text → done. */
function sayUnavailable(res, detail) {
  const 말 =
    '지금은 챗봇 서버가 연결돼 있지 않아 답할 수 없습니다.\n\n' +
    '없는 값을 지어내는 대신 이렇게 알려 드립니다.\n' +
    (detail ? `\n사유: ${detail}\n` : '');
  res.write(sse('status', { text: '연결 확인' }));
  res.write(sse('text', { text: 말 }));
  res.write(sse('done', { ok: false, reason: detail || 'CHAT_BACKEND_URL 미설정' }));
  res.end();
}

function sse(event, data) {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let s = '';
    req.on('data', (c) => {
      s += c;
      if (s.length > 200000) reject(new Error('질문이 너무 깁니다.'));
    });
    req.on('end', () => resolve(s || '{}'));
    req.on('error', reject);
  });
}
