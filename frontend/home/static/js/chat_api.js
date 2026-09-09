/* ══════════════════════════════════════════════════════
   챗봇 API — feedit-chat 과 이야기하고, 받은 리포트를 카드로 그린다.

   ★ 없는 클래스를 쓰지 않는다.
     여기서 쓰는 것은 전부 이미 CSS 에 있는 것들이다 —
       .ansCard .ansBar .ansBody .ansH .rank .bars   (home/static/css/chat.css)
       .kwReq .kwReq .near .kwReq .ask               (trend/static/css/dispatch.css)
       .note                                          (trend/static/css/weekly_report.css)
       .pill .pill.ghost                              (app_shell/static/css/layout.css)
     main.css 가 전부 한 문서로 @import 하므로 챗봇 팝업 안에서도 그대로 걸린다.

   ★ 서버가 없으면 조용히 실패한다.
     목업 데모가 깨지면 안 된다. isUp() 이 false 면 부르는 쪽이 기존 응답으로 떨어진다.
   ══════════════════════════════════════════════════════ */

/* ★ 배포된 곳에서는 같은 도메인의 /api 를 쓴다.
 *
 *   전에는 5173·4173(로컬 vite) 이 아니면 무조건 `http://127.0.0.1:8770` 을
 *   불렀다. 그래서 **버셀에 올리면 방문자의 자기 컴퓨터**를 부르게 되고,
 *   당연히 실패해서 isUp() 이 false → 화면은 조용히 목업 답변으로 떨어졌다.
 *   서버가 멀쩡히 떠 있어도 그랬다.
 *
 *   이제 규칙은 하나다 — **로컬 파일로 열었을 때만** 직접 부른다.
 *   그 외에는 전부 같은 도메인의 /api (버셀 함수 또는 vite 프록시).
 *   CORS 도 안 생기고, 주소를 코드에 박아 둘 이유도 없다. */
const DIRECT = 'http://127.0.0.1:8770';
/* location 이 없는 자리(시험 환경 등)에서도 import 만으로 터지지 않게 감싼다.
   모듈이 불러오는 순간 죽으면, 이걸 import 하는 화면 전체가 같이 죽는다. */
const LOCAL_FILE = typeof location !== 'undefined' && location.protocol === 'file:';
export const API_BASE = LOCAL_FILE ? DIRECT : '/api';

let _up = null;          /* null = 아직 모름, true/false = 확인됨 */
let _upAt = 0;

export function esc(s){
  return String(s==null?'':s).replace(/[&<>"']/g,m=>(
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

/* 서버가 떠 있나. 30초 동안은 결과를 재사용한다 — 매 질문마다 물으면 느려진다. */
export async function isUp(){
  const now = Date.now();
  if(_up !== null && now - _upAt < 30000) return _up;
  try{
    const c = new AbortController();
    const t = setTimeout(()=>c.abort(), 1500);
    const r = await fetch(API_BASE + '/v1/health', {signal:c.signal});
    clearTimeout(t);
    _up = r.ok;
  }catch(e){ _up = false }
  _upAt = now;
  return _up;
}

/* ── SSE 스트림 읽기 ──────────────────────────────────
   EventSource 는 POST 를 못 보낸다. fetch + ReadableStream 으로 직접 판다. */
export async function askStream(payload, on){
  const res = await fetch(API_BASE + '/v1/chat', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(payload)
  });
  if(!res.ok || !res.body) throw new Error('HTTP ' + res.status);

  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  for(;;){
    const {done, value} = await reader.read();
    if(done) break;
    buf += dec.decode(value, {stream:true});
    let i;
    /* 이벤트 하나는 빈 줄로 끝난다 */
    while((i = buf.indexOf('\n\n')) >= 0){
      const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
      let ev = 'message', data = '';
      chunk.split('\n').forEach(ln=>{
        if(ln.startsWith('event: ')) ev = ln.slice(7).trim();
        else if(ln.startsWith('data: ')) data += ln.slice(6);
      });
      if(!data) continue;
      let parsed; try{ parsed = JSON.parse(data) }catch(e){ continue }
      if(on[ev]) on[ev](parsed);
    }
  }
}

/* ── 리포트 → 카드 ────────────────────────────────────
   서버가 질문 유형에 맞는 **블록 배열**을 준다. 여기서는 그걸 그리기만 한다.
   구조를 여기서 정하지 않는다 — 정하는 곳은 서버의 templates.py 하나다.

   슬롯
     full   카드 위 전체 폭
     left   카드 왼쪽 (1.15fr)
     right  카드 오른쪽 (1fr)

   ★ 모르는 블록 타입은 조용히 건너뛴다.
     서버가 먼저 새 블록을 내보내도 화면이 깨지지 않게. */

const H = (title, meta) => (title || meta)
  ? '<div class="ansH">' + (title ? '<h3>' + esc(title) + '</h3>' : '') +
    (meta ? '<em>' + esc(meta) + '</em>' : '') + '</div>' : '';

const BLOCK = {
  rank: b => H(b.title, b.meta) + '<div class="rank">' + (b.rows || []).map((r, i) =>
    '<div class="row"' + (r.href ? ' data-href="' + esc(r.href) + '"' : '') + '>' +
    '<span class="n">' + String(i + 1).padStart(2, '0') + '</span>' +
    '<span class="k">' + esc(r.k) + (r.small ? '<small>' + esc(r.small) + '</small>' : '') + '</span>' +
    '<span class="d ' + (r.up ? 'up' : 'dn') + '">' + esc(r.v) + '</span></div>').join('') + '</div>',

  bars: b => H(b.title, b.meta) + '<div class="bars">' + (b.items || []).map(x =>
    '<div class="b"><span>' + esc(x.k) + '</span>' +
    '<u><i data-w="' + (x.w | 0) + '"></i></u>' +
    '<em>' + esc(x.v) + '</em></div>').join('') + '</div>',

  table: b => H(b.title, b.meta) +
    '<table class="mTable"><tr>' + (b.head || []).map(h => '<th>' + esc(h) + '</th>').join('') + '</tr>' +
    (b.rows || []).map(r =>
      '<tr><td>' + esc(r.k) + '</td>' +
      '<td><span class="bar" style="display:block"><i data-w="' + (r.w | 0) + '"' +
      (r.up ? ' class="c"' : '') + '></i></span></td>' +
      '<td class="n ' + (r.up ? 'up' : 'dn') + '">' + esc(r.v) + '</td></tr>').join('') + '</table>',

  kpis: b => '<div class="kpis">' + (b.items || []).map(x =>
    '<div class="kpi"><span>' + esc(x.k) + '</span>' +
    '<b>' + esc(x.v) + (x.unit ? '<u>' + esc(x.unit) + '</u>' : '') + '</b>' +
    (x.note ? '<div class="dl ' + (x.up ? 'up' : 'dn') + '">' + esc(x.note) + '</div>' : '') +
    '</div>').join('') + '</div>',

  quotes: b => H(b.title, b.meta) + (b.items || []).map(x =>
    /* .note 는 flex 다. 인용과 출처를 형제로 두면 옆으로 붙는다 —
       한 칸에 넣고 안에서 줄을 나눈다. */
    '<div class="note"><i>◆</i><span>' +
    '<b>' + esc(x.body) + '</b>' +
    '<em>' + esc(x.src) + (x.kind ? ' · ' + esc(x.kind) : '') +
    (x.tone ? ' · ' + esc(x.tone) : '') + '</em>' +
    '</span></div>').join(''),

  /* 문단은 문단으로, 글머리표는 글머리표로 그린다.
     <br> 로만 이으면 문단 사이 간격이 없어 한 덩어리로 읽힌다.
     서버가 마크다운을 이미 걷어냈으므로(mdclean.py) 여기서는 줄만 본다. */
  prose: b => H(b.title, b.meta) + '<div class="rpProse">' +
    String(b.text || '').split(/\n\s*\n/).map(para => {
      const lines = para.split('\n').map(l => l.trim()).filter(Boolean);
      if(!lines.length) return '';
      if(lines.every(l => l.startsWith('· ')))
        return '<ul>' + lines.map(l => '<li>' + esc(l.slice(2)) + '</li>').join('') + '</ul>';
      return '<p>' + lines.map(esc).join(' ') + '</p>';
    }).join('') + '</div>',

  /* 출처. 제목이 없거나 주소 그대로면 호스트만 남긴다 —
     본문에 주소가 통째로 붙어 나오던 것을 여기로 옮겼다 (서버 mdclean.py). */
  links: b => '<div class="rank" style="margin-top:14px">' + (b.items || []).map((o, i) => {
    let host = '', url = String(o.url || '');
    try{ host = new URL(url).hostname.replace(/^www\./, '') }catch(e){}
    let title = String(o.title || '').replace(/\s+/g, ' ').trim();
    if(!title || title === url || /^https?:\/\//.test(title)) title = host || url;
    if(title.length > 46) title = title.slice(0, 45).trim() + '…';
    return '<div class="row" data-href="' + esc(url) + '">' +
      '<span class="n">' + String(i + 1).padStart(2, '0') + '</span>' +
      '<span class="k">' + esc(title) + '</span>' +
      '<span class="d dn">' + esc(host) + '</span></div>';
  }).join('') + '</div>',

  note: b => '<div class="note"><i>◆</i>' + esc(b.text) + '</div>',

  upsell: b => H(b.title, b.meta) +
    '<div class="kwReq"><p>' + esc(b.why || '') + '</p>' +
    '<div class="ask"><span>프로 플랜에서 ' + esc((b.unlocks || []).join(' · ')) +
    ' 을 볼 수 있습니다.</span>' +
    '<button type="button" data-v="price">요금제 보기</button></div></div>',
};

export function reportHTML(rep){
  const asOf = (rep.as_of && rep.as_of.metric) || '';
  const bar = '<div class="ansBar"><u></u><u></u><u></u><span>' +
    esc('feedit.ai / ' + (rep.intent || 'chat') + ' / ' + asOf) + '</span></div>';

  const blocks = rep.blocks || [];
  /* 그릴 게 없으면 아무것도 그리지 않는다.
     예전엔 제목줄만 있는 빈 카드를 돌려줬다 — 답은 말풍선에 멀쩡히 있는데
     그 아래 빈 상자가 붙어 "뭔가 실패했나" 로 읽혔다. (새 경로는 블록 없이
     문장만 내는 답이 흔하다.) report 이벤트 자체는 계속 받는다 —
     chat_popup.js 가 거기서 aiMsg.turn(후속 질문 맥락)을 챙기기 때문이다. */
  if(!blocks.length) return '';

  const draw = b => {
    const fn = BLOCK[b.type];
    return fn ? fn(b) : '';          /* 모르는 타입은 건너뛴다 */
  };
  const full  = blocks.filter(b => b.slot === 'full').map(draw).filter(Boolean).join('');
  const left  = blocks.filter(b => b.slot === 'left').map(draw).filter(Boolean).join('');
  const right = blocks.filter(b => b.slot === 'right').map(draw).filter(Boolean).join('');

  /* .ansBody 는 2단 그리드다. 자식이 셋이면 다음 줄로 흘러 레이아웃이 깨진다.
     항상 정확히 두 칸만 넣는다. */
  const body = (left || right)
    ? '<div class="ansBody"><div>' + left + '</div><div>' + right + '</div></div>'
    : '';
  const card = body ? '<div class="ansCard">' + bar + body + '</div>' : '';
  return (full ? '<div class="rpFull">' + full + '</div>' : '') + card;
}

/* ── 사전에 없는 말 ───────────────────────────────────
   실패로 끝내지 않는다. 가까운 말과 등록 요청을 같이 준다.
   찜한 키워드 화면(saved_keywords.js)이 쓰는 것과 같은 마크업이다. */
export function refusalHTML(err){
  const near = err.near || [];
  return '<div class="kwReq">' +
    '<p>' + esc(err.message || '답을 만들 수 없습니다.').replace(/\n/g, '<br>') + '</p>' +
    (near.length
      ? '<div class="near"><em>' + esc(err.near_label || '혹시 이건가요') + '</em>' +
        near.map(o => '<button type="button" data-kw="' + esc(o.canonical) + '">' +
          esc(o.canonical) + '</button>').join('') + '</div>'
      : '') +
    /* JS 훅은 클래스가 아니라 data 속성으로 단다.
       CSS 에 없는 클래스를 붙이면 "이건 스타일이 있나" 를 매번 확인해야 한다.
       버튼 모양은 .kwReq .ask button 이 이미 갖고 있다. */
    '<div class="ask"><span>패션 용어가 맞다면 등록을 요청해 주세요. 검토 후 사전에 추가됩니다.</span>' +
    '<button type="button" data-lexreq="1" data-surface="' + esc(err.surface_guess || '') +
    '" data-question="' + esc(err.question || '') + '">등록 요청</button></div></div>';
}

/* 등록 요청 버튼 하나를 실제로 서버에 보낸다.
   호출 쪽(chat_popup.js)이 누른 즉시 버튼을 잠그고, 끝나면 이 함수가 돌려준
   결과로 문구를 바꿔 단다 — "누르면 되는 척" 이 되지 않게(server.py 주석 참고). */
export async function requestLexicon(surface, question){
  const res = await fetch(API_BASE + '/v1/lexicon/requests', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({surface, question})
  });
  if(!res.ok) throw new Error('HTTP ' + res.status);
  return res.json();
}

/* ── 다음 행동 버튼 ──────────────────────────────────
   .msg.ai .act 안에서만 스타일이 걸린다. AI 말풍선 안에 넣어야 한다. */
export function actionsHTML(acts){
  if(!acts || !acts.length) return '';
  return '<div class="act">' + acts.map(a => {
    const d = ['<button class="pill ghost"'];
    if(a.view) d.push('data-v="' + esc(a.view) + '"');
    /* 스타일은 **이름** 으로 보낸다. 라우터는 id 를 기대하므로
       chat_popup 의 cpFixStyleLinks() 가 이름 → id 로 바꿔 단다.
       여기서 data-style 을 직접 달면 조용히 첫 번째 스타일로 떨어진다. */
    if(a.style) d.push('data-style-name="' + esc(a.style) + '"');
    if(a.keyword) d.push('data-kw="' + esc(a.keyword) + '"');
    if(a.type === 'switch_mode') d.push('data-mode="' + esc(a.to) + '"');
    return d.join(' ') + '>' + esc(a.label) + ' <i>→</i></button>';
  }).join('') + '</div>';
}

/* 막대는 0에서 시작해 채운다 — 카드가 뜨는 순간 함께 자란다 */
export function fillBars(root){
  root.querySelectorAll('i[data-w]').forEach(i => {
    i.style.width = '0%';
    requestAnimationFrame(() => requestAnimationFrame(() => {
      i.style.transition = 'width .9s cubic-bezier(.19,1,.22,1)';
      i.style.width = i.dataset.w + '%';
    }));
  });
}
