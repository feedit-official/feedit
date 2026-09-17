/* 계정 API — 비밀번호와 세션 토큰은 저장하지 않는다.
 * Django의 HttpOnly 세션 쿠키가 로그인 상태를 담당한다. */
let csrfToken = '';
let sessionPromise = null;

async function request(path, { method='GET', body, bootstrap=true } = {}) {
  if (method !== 'GET' && bootstrap && !csrfToken) await session();
  const headers = { Accept:'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET' && csrfToken) headers['X-CSRFToken'] = csrfToken;
  let response;
  try {
    response = await fetch('/api/auth/' + path, {
      method,
      credentials:'same-origin',
      headers,
      body:body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (_) {
    throw new Error('로그인 서버에 연결하지 못했습니다. 백엔드가 실행 중인지 확인해 주세요.');
  }
  const text = await response.text();
  let payload;
  try { payload = JSON.parse(text); }
  catch (_) { throw new Error('로그인 서버가 올바른 JSON을 돌려주지 않았습니다.'); }
  if (payload && payload.data && payload.data.csrf_token) csrfToken = payload.data.csrf_token;
  if (!response.ok || !payload || payload.status !== 'ok') {
    throw new Error((payload && payload.reason) || `로그인 API 오류 (${response.status})`);
  }
  return payload.data;
}

export function session(force=false) {
  if (!force && sessionPromise) return sessionPromise;
  sessionPromise = request('me', { bootstrap:false }).catch(error => {
    sessionPromise = null;
    throw error;
  });
  return sessionPromise;
}

export const loginAccount = (username, password) =>
  request('login', { method:'POST', body:{ username, password } });

export const signupAccount = data =>
  request('signup', { method:'POST', body:data });

export const logoutAccount = () =>
  request('logout', { method:'POST', body:{} }).finally(() => { sessionPromise = null; });

export const saveAccount = data =>
  request('profile', { method:'POST', body:data });

export const weeklyVideos = () =>
  request('weekly-videos');
