/* ══════════════════════════════════════════════════════
   챗봇 API — feedit-chat 과 이야기하고, 받은 리포트를 카드로 그린다.

   ★ 없는 클래스를 쓰지 않는다.
     여기서 쓰는 것은 전부 이미 CSS 에 있는 것들이다 —
       .ansBody .ansH .rank .bars                    (home/static/css/chat.css)
       .skillReport .skillCanvas .skillModule             (home/static/css/chat_report.css)
       .rpReport .rpReportGrid .rpReportSection            (이전 응답 호환용)
       .tabreport .rpTabs .rpTabBtn .rpTabPanel          (이전 응답 호환용)
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

/* ── 이미지 첨부 ──────────────────────────────────────
   서버로는 JSON 본문에 data URL(base64) 문자열로 실어 보낸다.
   원본 그대로 올리면 사진 한 장에도 챗바 요청이 몇 MB씩 나오므로,
   캔버스로 긴 변을 줄이고 JPEG로 다시 압축한 뒤에 보낸다. */
export const MAX_IMAGES = 6;
const IMG_MAX_DIM = 1280;
const IMG_QUALITY = 0.82;

export function wantsVirtualFit(text, images){
  return Boolean(images&&images.length&&/(입혀\s*(줘|주세요|봐|보기)?|착용\s*(시켜|해|해줘|해주세요)|가상\s*피팅|코디\s*입혀)/i.test(String(text||'')));
}

export function responseCardHTML(message, mockRenderer){
  if(message&&message.cardHtml!=null)return message.cardHtml;
  /* 착장 전용 메시지는 일반 답변이 아니다. key는 질문 예시를 고르기 위한 값이라
     여기서 목업 카드로 해석하면 발레코어 데모가 합성 카드 위에 끼어든다. */
  if(message&&message.fit)return '';
  return message&&message.key&&mockRenderer?mockRenderer(message.key):'';
}

function loadImage(file){
  return new Promise((resolve, reject) => {
    if(!file || !/^image\//.test(file.type)){ reject(new Error('not_image')); return; }
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('load_failed')); };
    img.src = url;
  });
}

export async function imageFileToDataURL(file){
  const img = await loadImage(file);
  const scale = Math.min(1, IMG_MAX_DIM / Math.max(img.naturalWidth || img.width, img.naturalHeight || img.height));
  const w = Math.max(1, Math.round((img.naturalWidth || img.width) * scale));
  const h = Math.max(1, Math.round((img.naturalHeight || img.height) * scale));
  const cv = document.createElement('canvas');
  cv.width = w; cv.height = h;
  const ctx = cv.getContext('2d');
  ctx.drawImage(img, 0, 0, w, h);
  return cv.toDataURL('image/jpeg', IMG_QUALITY);
}

/* 드래그 앤 드롭 — 챗바 위에 사진을 끌어다 놓아도 + 버튼과 같은 자리로 들어간다.
   홈 챗바(.chatbar)와 팝업 입력줄(.cpInputWrap) 양쪽에서 그대로 재사용한다. */
export function bindImageDrop(el, onFiles){
  if(!el)return;
  const hasFiles = e => e.dataTransfer && Array.from(e.dataTransfer.types||[]).includes('Files');
  ['dragenter','dragover'].forEach(ev=>el.addEventListener(ev, e=>{
    if(!hasFiles(e))return;
    e.preventDefault(); e.dataTransfer.dropEffect='copy';
    el.classList.add('dragOver');
  }));
  ['dragleave','dragend'].forEach(ev=>el.addEventListener(ev, e=>{
    if(e.relatedTarget && el.contains(e.relatedTarget))return;   /* 안쪽 자식 사이 이동은 무시 */
    el.classList.remove('dragOver');
  }));
  el.addEventListener('drop', e=>{
    el.classList.remove('dragOver');
    if(!e.dataTransfer)return;
    const files=[...(e.dataTransfer.files||[])].filter(f=>/^image\//.test(f.type));
    if(!files.length)return;
    e.preventDefault();
    onFiles(files);
  });
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
export async function askStream(payload, on, options={}){
  const res = await fetch(API_BASE + '/v1/chat', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(payload), signal:options.signal
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
   구조를 여기서 정하지 않는다 — 기존 경로는 templates.py, 새 도구 경로는
   compose_report 도구와 report_skill.py 가 만든 UI 스펙을 그린다.

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

  kpis: b => H(b.title, b.meta) + '<div class="kpis">' + (b.items || []).map(x =>
    '<div class="kpi"><span>' + esc(x.k) + '</span>' +
    '<b>' + esc(x.v) + (x.unit ? '<u>' + esc(x.unit) + '</u>' : '') + '</b>' +
    (x.note ? '<div class="dl ' + (x.up ? 'up' : 'dn') + '">' + esc(x.note) + '</div>' : '') +
    '</div>').join('') + '</div>',

  quotes: b => H(b.title, b.meta) + '<div class="evidenceList">' +
    (b.items || []).map((x, i) => {
      const source = [x.src, x.kind].filter(Boolean).map(esc).join(' · ');
      return '<blockquote class="evidenceQuote">' +
        '<span class="evidenceNo" aria-hidden="true">' + String(i + 1).padStart(2, '0') + '</span>' +
        '<div class="evidenceCopy"><p>' + esc(x.body) + '</p>' +
        '<footer class="evidenceMeta">' +
        (source ? '<span>' + source + '</span>' : '') +
        (x.tone ? '<em>' + esc(x.tone) + '</em>' : '') +
        '</footer></div></blockquote>';
    }).join('') + '</div>',

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

  /* 생성형 리포트 스킬 — 완성 양식 이름이 없다.
     모델이 실제 결과 모듈을 12열 캔버스에 배치한 스펙을 받아 조립한다.
     HTML 자체는 모델에게 받지 않고 허용된 디자인 토큰과 기존 BLOCK 만 써서,
     질문마다 다른 구조를 만들면서도 스크립트·가짜 값이 들어올 길을 막는다. */
  generative_report: b => {
    const accents = new Set(['coral','ink','violet','blue','lime']);
    const surfaces = new Set(['paper','soft','contrast','glass']);
    const densities = new Set(['airy','balanced','compact']);
    const kinds = new Set(['ranking','comparison','metric','direction','sources','associations',
      'sentiment','recommendations','taste','context','salmal','evidence','links','missing']);
    const presentations = new Set(['hero','card','chart','list','editorial','compact']);
    const emphasis = new Set(['strong','normal','quiet']);
    const accent = accents.has(b.accent) ? b.accent : 'coral';
    const surface = surfaces.has(b.surface) ? b.surface : 'paper';
    const density = densities.has(b.density) ? b.density : 'balanced';
    const modules = (b.modules || []).map(m => {
      const block = m && m.block;
      const fn = block && BLOCK[block.type];
      if(!fn || block.type === 'generative_report' || block.type === 'reportset' || block.type === 'tabreport') return '';
      const kind = kinds.has(m.kind) ? m.kind : 'metric';
      const presentation = presentations.has(m.presentation) ? m.presentation : 'card';
      const weight = emphasis.has(m.emphasis) ? m.emphasis : 'normal';
      const span = Math.max(4, Math.min(12, Number.parseInt(m.span, 10) || 6));
      const itemCount = Array.isArray(block.items) ? Math.min(9, block.items.length) : 0;
      const defaultCols = itemCount === 3 ? 3 : Math.max(1, Math.min(2, itemCount || 2));
      const columns = Math.max(1, Math.min(4, Number.parseInt(m.columns, 10) || defaultCols));
      return '<section class="skillModule skillModule--' + kind +
        ' skillModule--' + presentation + ' skillModule--' + weight +
        ' skillModule--block-' + esc(block.type) +
        '" style="grid-column:span ' + span + (block.type === 'kpis'
          ? ';--skill-kpi-cols:' + columns : '') + '"' +
        (itemCount ? ' data-items="' + itemCount + '"' : '') + '>' + fn(block) + '</section>';
    }).filter(Boolean).join('');
    if(!modules) return '';
    return '<div class="skillReport skillReport--' + surface + ' skillReport--' + accent +
      ' skillReport--' + density + '" data-layout="' + esc(b.fingerprint || '') + '">' +
      '<div class="skillReportHead"><span>FEEDiT / LIVE REPORT</span><em>' +
      String((b.modules || []).length).padStart(2,'0') + ' SIGNALS</em></div>' +
      '<div class="skillReportTitle">' + esc(b.title || 'FEEDiT 트렌드 브리프') + '</div>' +
      '<div class="skillCanvas">' + modules + '</div></div>';
  },

  /* 이전 적응형 응답 호환용. 새 응답은 generative_report 를 쓴다. */
  reportset: b => {
    const allowed = new Set(['ranking','pulse','compare','recommend','personal','evidence','context','mixed']);
    const variant = allowed.has(b.variant) ? b.variant : 'mixed';
    const sections = b.sections || [];
    if(!sections.length) return '';
    const nested = sb => {
      const fn = sb && BLOCK[sb.type];
      if(!fn || sb.type === 'reportset' || sb.type === 'tabreport') return '';
      const slot = ['full','left','right'].includes(sb.slot) ? sb.slot : 'full';
      return '<div class="rpNested rpNested--' + slot + ' rpNested--' + esc(sb.type) + '">' + fn(sb) + '</div>';
    };
    const section = s => {
      const key = ['trend','taste','recommendation','evidence','context'].includes(s.key) ? s.key : 'evidence';
      const body = s.state === 'ready'
        ? (s.blocks || []).map(nested).filter(Boolean).join('')
        : '<div class="rpTabEmpty">' + esc(s.message || '아직 연결되어 있지 않습니다.') + '</div>';
      if(!body) return '';
      return '<section class="rpReportSection rpReportSection--' + key + '">' +
        '<div class="rpReportSectionHead"><span>' + esc(s.label || '') + '</span>' +
        '<em>' + (s.state === 'ready' ? 'READY' : 'NOT CONNECTED') + '</em></div>' +
        '<div class="rpReportSectionBody">' + body + '</div></section>';
    };
    const body = sections.map(section).filter(Boolean).join('');
    if(!body) return '';
    return '<div class="rpReport rpReport--' + variant + '">' +
      '<div class="rpReportHead"><span>' + esc(b.label || 'FEEDIT BRIEF') + '</span>' +
      '<em>' + String(sections.length).padStart(2,'0') + ' SIGNALS</em></div>' +
      '<div class="rpReportGrid">' + body + '</div></div>';
  },

  /* 탭 리포트 (구조안 02) — 취향분석·트렌드지표·상품추천을 탭 3개로 묶는다.
     ★ 트렌드 탭 안의 blocks 는 위에 이미 있는 렌더러(rank/kpis/bars/quotes…)를
       그대로 재사용한다 — 탭은 그릇일 뿐, 값을 그리는 규칙을 새로 만들지 않는다.
     ★ state !== 'ready' 인 탭(취향분석·상품추천, 서버가 아직 데이터가 없다고
       한 것)은 빈 칸을 숨기지 않고 message 를 그대로 보여준다(rpTabEmpty) —
       서버 쪽 "값은 도구에서만 나온다" 원칙과 같은 자세다. */
  tabreport: b => {
    const tabs = b.tabs || [];
    if(!tabs.length) return '';
    const body = t => (t.state === 'ready')
      ? (t.blocks || []).map(sb => { const fn = BLOCK[sb.type]; return fn ? fn(sb) : ''; }).filter(Boolean).join('')
      : '<div class="rpTabEmpty">' + esc(t.message || '아직 연결되어 있지 않습니다.') + '</div>';
    const nav = tabs.map((t, i) =>
      '<button type="button" class="rpTabBtn' + (i === 0 ? ' on' : '') + '" data-tab="' + esc(t.key) + '">' +
      esc(t.label) + '</button>').join('');
    const panels = tabs.map((t, i) =>
      '<div class="rpTabPanel' + (i === 0 ? ' on' : '') + '" data-panel="' + esc(t.key) + '">' + body(t) + '</div>').join('');
    return '<div class="tabreport"><div class="rpTabs">' + nav + '</div>' + panels + '</div>';
  },
};

export function reportHTML(rep){
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
  const content = (full ? '<div class="rpFull">' + full + '</div>' : '') + body;
  if(!content) return '';

  /* 생성형 리포트는 이미 LIVE REPORT 프레임까지 완성된 블록이다. 그 밖의
     이전/호환 지표만 같은 외곽 프레임으로 감싸 브라우저 창 모양(ansBar)이
     다시 나타나지 않게 한다. */
  if(blocks.length === 1 && blocks[0].type === 'generative_report') return full;
  return '<div class="skillReport skillReport--legacy">' +
    '<div class="skillReportHead"><span>FEEDiT / LIVE REPORT</span><em>' +
    String(blocks.length).padStart(2,'0') + ' SIGNALS</em></div>' +
    '<div class="skillLegacyCanvas">' + content + '</div></div>';
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
/* 이 답변에서 무엇을 못 했는지 — 말풍선 아래 작은 한 줄. (2026-09-10)
   ★ 서버(agent_path._notes)는 다섯 가지를 보낸다:
       NO_DATA · VERIFIED · VERIFY_FAILED · WEB_SOURCED · PARTIAL
     지금까지 화면은 이 목록을 **한 번도 읽지 않았다.** reportHTML 이 보는 것은
     as_of · intent · blocks 뿐이라, "웹에서 찾은 값입니다" 도 "측정 자료에 없는
     내용을 덜어냈습니다" 도 사용자에게 도달하지 못했다. 못 한 것을 숨기지
     않는다는 원칙이 서버에서 끝나고 화면 앞에서 멈춰 있던 자리다.
   ★ NO_DATA 만 뺀다 — agent_blocks 가 이미 카드 안에 note 블록으로 그린다.
     여기서 또 그리면 같은 문장이 카드 안과 카드 아래에 두 번 뜬다.
   ★ 카드가 아니라 말풍선 옆에 붙인다. 블록이 없는 답(웹으로만 답한 날씨 같은)은
     카드를 아예 안 그리는데(reportHTML 의 규칙 — 빈 카드가 "뭔가 실패했나" 로
     읽혔던 자리), 안내 한 줄 때문에 그 빈 카드를 되살릴 수는 없다. */
/* 이어 갈 질문 — 리포트 카드 **아래** 한 줄. (2026-09-10)
   ★ 서버(agent_path._split_followup)가 답변 본문에서 떼어 보낸다. 본문에 남겨
     두면 말풍선에 그려져 카드 **위**에 뜨고, 사용자는 근거를 보기도 전에 질문부터
     받는다. 순서가 뒤집혀 있었다.
   ★ 여기 오는 내용은 서버가 만든 안전한 HTML 이다(mdclean.to_html — 이스케이프를
     먼저 하고 아는 표시만 태그로 바꾼다). 그래서 다시 이스케이프하지 않는다.
     하면 <b> 가 글자로 보인다. */
export function followupHTML(html){
  const s = String(html || '').trim().replace(/^<p>([\s\S]*)<\/p>$/, '$1');
  if(!s) return '';
  /* ★ 표식(✧)을 붙이지 않는다. 이 줄은 주석이나 안내가 아니라 **말**이라서,
     앞에 기호가 붙으면 시스템 메시지처럼 읽힌다. 본문과 같은 크기·같은 모양으로
     그냥 이어지는 것이 맞다. (2026-09-10) */
  return '<div class="nextQ">' + s + '</div>';
}

const CUE_SKIP = new Set(['NO_DATA']);

export function notesHTML(notes){
  const rows = (notes || []).filter(n => n && n.message && !CUE_SKIP.has(n.code));
  if(!rows.length) return '';
  return '<div class="cue">' + rows.map(n =>
    '<div class="cueRow"><i>◆</i><span>' + esc(n.message) + '</span></div>'
  ).join('') + '</div>';
}

export function actionsHTML(acts){
  if(!acts || !acts.length) return '';
  return '<div class="act">' + acts.map(a => {
    const kind=String(a.type||(a.view?'view':'action')).replace(/[^a-z_-]/gi,'');
    const icon=a.type==='community'?'◌':a.type==='virtual_fit'?'✦':a.type==='switch_mode'?'⇄':'↗';
    const d = ['<button class="pill ghost actBtn act-'+esc(kind)+'"'];
    if(a.view) d.push('data-v="' + esc(a.view) + '"');
    /* 스타일은 **이름** 으로 보낸다. 라우터는 id 를 기대하므로
       chat_popup 의 cpFixStyleLinks() 가 이름 → id 로 바꿔 단다.
       여기서 data-style 을 직접 달면 조용히 첫 번째 스타일로 떨어진다. */
    if(a.style) d.push('data-style-name="' + esc(a.style) + '"');
    if(a.keyword) d.push('data-kw="' + esc(a.keyword) + '"');
    if(a.type === 'switch_mode') d.push('data-mode="' + esc(a.to) + '"');
    /* 물어보기는 서버가 확인한 상품 초안을 함께 들고 간다 —
       없으면 예전처럼 사용자가 친 문장으로 떨어진다(chat_popup.js). */
    if(a.type === 'community'){
      d.push('data-community="1"');
      if(a.draft) d.push('data-draft="' + esc(JSON.stringify(a.draft)) + '"');
    }
    if(a.type === 'virtual_fit') d.push('data-virtual-fit="1"');
    return d.join(' ') + '><i class="actIcon" aria-hidden="true">'+icon+'</i><span>'+
      esc(a.label)+'</span><i class="actArrow" aria-hidden="true">→</i></button>';
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
