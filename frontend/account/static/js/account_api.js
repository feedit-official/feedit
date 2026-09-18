const endpoint = action => `/api/account?action=${encodeURIComponent(action)}`;

async function request(action, method = 'GET', data = null) {
  const options = { method, credentials: 'same-origin', headers: { Accept: 'application/json' } };
  if (data !== null) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(data);
  }
  let response;
  try {
    response = await fetch(endpoint(action), options);
  } catch (error) {
    throw new Error('서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.');
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.status === 'error') {
    const error = new Error(payload.reason || `요청에 실패했습니다 (${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return payload.data;
}

export const accountMe = () => request('me');
export const accountLogin = data => request('login', 'POST', data);
export const accountSignup = data => request('signup', 'POST', data);
export const accountLogout = () => request('logout', 'POST', {});
export const accountProfile = data => request('profile', 'PATCH', data);
export const accountDelete = () => request('delete', 'DELETE', {});
export const accountChat = data => request('chat', 'POST', data);
export const accountConversations = () => request('conversations');
export const accountEvent = data => request('event', 'POST', data);
export const accountSaved = (data = null) => data ? request('saved', 'POST', data) : request('saved');
export const accountVote = data => request('vote', 'POST', data);
export const accountCard = data => request('card', 'POST', data);
export const accountCards = () => request('cards');
