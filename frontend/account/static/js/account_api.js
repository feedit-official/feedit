/* 계정 API — 비밀번호와 세션 토큰은 저장하지 않는다.
 * Django의 HttpOnly 세션 쿠키가 로그인 상태를 담당한다. */
let csrfToken = '';
let sessionPromise = null;

async function request(path, { method='GET', body, bootstrap=true, base='/api/auth/' } = {}) {
  if (method !== 'GET' && bootstrap && !csrfToken) await session();
  const headers = { Accept:'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET' && csrfToken) headers['X-CSRFToken'] = csrfToken;
  let response;
  try {
    response = await fetch(base + path, {
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
  catch (_) {
    // 상태 숫자를 같이 보여 준다 — 404는 서버에 인증 주소가 없음, 403은 CSRF 거부, 502/504는 서버 꺼짐
    throw new Error(`로그인 서버가 올바른 JSON을 돌려주지 않았습니다 (${response.status}).`);
  }
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

/* term 을 주면 그 키워드 태그가 붙은 영상만 찾는다 (금주의 리포트 · 가장 많이 검색한 키워드) */
export const weeklyVideos = (term = '') =>
  request('weekly-videos' + (term ? '?term=' + encodeURIComponent(term) : ''));

/* ── 활동 기록 ─────────────────────────────────────────────
 * 검색 · 살!말? 투표 · 찜 · 챗봇 사용을 서버(user_event · chat_session)에 남긴다.
 * 금주의 리포트가 이 기록으로 채워진다.
 * ★ 기록은 화면 동작을 막으면 안 된다 — 실패(비로그인 401 · 서버 꺼짐)는 조용히 넘긴다. */
const quiet = promise => promise.catch(() => null);

export const logSearch = (q, facet = '', style = '') =>
  quiet(request('event', { method:'POST', body:{ type:'SEARCH', q, facet, style } }));

export const logChat = (conversationId, title = '') =>
  quiet(request('event', { method:'POST', body:{ type:'CHAT', conversation_id:conversationId, title } }));

/* choice: 'BUY' | 'PASS' | null(투표 취소) */
export const saveVote = ({ cardKey, title = '', brand = '', style = '', choice = null }) =>
  quiet(request('vote', { method:'POST', body:{ card_key:cardKey, title, brand, style, choice } }));

export const saveVoteComment = ({ cardId, content }) =>
  request('vote-comment', { method:'POST', body:{ card_id:cardId, content } });

export const deleteVoteComment = commentId =>
  request('vote-comment', { method:'DELETE', body:{ comment_id:commentId } });

export const reportVoteTarget = ({ targetType, targetId, reason='' }) =>
  request('vote-report', {
    method:'POST',
    body:{ target_type:targetType, target_id:targetId, reason },
  });

export const createVoteCard = data =>
  request('cards', { method:'POST', body:data, base:'/api/salmal/' });

export const deleteVoteCard = cardId =>
  request(`cards/${cardId}`, { method:'DELETE', body:{}, base:'/api/salmal/' });

export const saveLiked = ({ itemId, liked, name = '', brand = '', style = '' }) =>
  quiet(request('saved', { method:'POST', body:{ item_id:itemId, liked, name, brand, style } }));

/* 금주의 리포트 — 실패하면 예외를 그대로 올려 화면이 사유를 적게 한다 */
export const weeklyReport = () =>
  request('weekly-report');

/* ── Google 로그인 ──────────────────────────────────────────
 * Google Identity Services(GIS)의 코드 팝업으로 '인가 코드'만 받아 서버로 넘긴다.
 * 코드→토큰 교환과 신원 확인은 Django가 client_secret으로 한다.
 * 클라이언트 ID는 공개 값이라 /api/auth/me 응답에서 받아 쓴다. */
const GSI_SRC = 'https://accounts.google.com/gsi/client';
let gsiPromise = null;

function loadGsi() {
  if (globalThis.google && globalThis.google.accounts && globalThis.google.accounts.oauth2) {
    return Promise.resolve(globalThis.google);
  }
  if (gsiPromise) return gsiPromise;
  gsiPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = GSI_SRC;
    script.async = true;
    script.onload = () => resolve(globalThis.google);
    script.onerror = () => {
      gsiPromise = null;
      reject(new Error('Google 로그인 스크립트를 불러오지 못했습니다. 네트워크를 확인해 주세요.'));
    };
    document.head.appendChild(script);
  });
  return gsiPromise;
}

/* 코드 클라이언트는 미리 만들어 둔다.
 * ★ 클릭 뒤에 fetch·스크립트 로딩을 기다렸다가 팝업을 열면, 사파리 등은
 *   '사용자 동작이 아니다'라며 팝업을 막는다. 그래서 화면이 뜰 때 준비하고,
 *   클릭 순간에는 requestCode() 만 동기로 부른다. */
let codeClient = null;
let codeWaiter = null;
let preparePromise = null;

export function prepareGoogle() {
  if (preparePromise) return preparePromise;
  preparePromise = (async () => {
    const me = await session();
    if (!me.google_client_id) return false;
    const google = await loadGsi();
    codeClient = google.accounts.oauth2.initCodeClient({
      client_id: me.google_client_id,
      scope: 'openid email profile',
      ux_mode: 'popup',
      select_account: true,
      callback: resp => {
        const w = codeWaiter; codeWaiter = null;
        if (!w) return;
        if (resp && resp.code) w.resolve(resp.code);
        else w.reject(new Error((resp && resp.error_description) || 'Google 인증을 완료하지 못했습니다.'));
      },
      error_callback: err => {
        const w = codeWaiter; codeWaiter = null;
        if (!w) return;
        const closed = Boolean(err && err.type === 'popup_closed');
        const e = new Error(closed ? 'Google 로그인 창이 닫혔습니다.'
          : '팝업이 차단됐는지 확인한 뒤 다시 시도해 주세요.');
        e.cancelled = closed;
        w.reject(e);
      },
    });
    return true;
  })().catch(error => { preparePromise = null; throw error; });
  return preparePromise;
}

/* 클릭 핸들러 안에서 await 없이 바로 부를 것.
 * 결과: { authenticated:true, user } 이면 로그인 끝,
 *       { authenticated:false, needs_signup:true, google:{email,name} } 이면 가입 폼으로 */
export function googleLogin() {
  if (!codeClient) {
    return prepareGoogle().then(ready => {
      throw new Error(ready
        ? 'Google 로그인 준비가 끝났습니다. 버튼을 한 번 더 눌러 주세요.'
        : 'Google 로그인이 아직 설정되지 않았습니다. 서버의 GOOGLE_CLIENT_ID 를 확인해 주세요.');
    });
  }
  const codePromise = new Promise((resolve, reject) => { codeWaiter = { resolve, reject }; });
  codeClient.requestCode();   // 동기 호출 — 팝업이 사용자 클릭에 묶인다
  return codePromise
    .then(code => request('google', { method:'POST', body:{ code } }))
    .then(data => { if (data.authenticated) sessionPromise = null; return data; });
}

export const googleSignupAccount = data =>
  request('google-signup', { method:'POST', body:data }).finally(() => { sessionPromise = null; });

/* ── 챗봇 대화 기록 (RDS app.chat_session · app.chat_message) ──────────
 * 원본은 서버다. 브라우저 localStorage 는 화면을 빨리 그리는 사본일 뿐이다.
 * 목록/본문 조회는 실패를 그대로 올린다(화면이 다시 시도). 쓰기는 조용히 실패한다 —
 * 저장이 안 된다고 대화가 막히면 안 된다. */
export const chatList = (mode = '') =>
  request('chats' + (mode ? '?mode=' + encodeURIComponent(mode) : ''));

export const chatLoad = sessionId =>
  request('chats?id=' + encodeURIComponent(sessionId));

export const chatSaveTurn = data =>
  quiet(request('chats', { method:'POST', body:{ op:'turn', ...data } }));

export const chatImport = data =>
  quiet(request('chats', { method:'POST', body:{ op:'import', ...data } }));

export const chatUpdate = data =>
  quiet(request('chats', { method:'POST', body:{ op:'update', ...data } }));

export const chatTruncate = data =>
  quiet(request('chats', { method:'POST', body:{ op:'truncate', ...data } }));

export const chatDelete = ({ mode, key }) =>
  quiet(request('chats', { method:'DELETE', body:{ mode, key } }));
