/* 알림 — 헤더 종 아이콘 · 알림 패널 · 알림 설정 · 용어 등재 요청.
   원본은 서버다 (backend/apps/api/notification_views.py).
   화면은 받아서 그리기만 한다 — 여기서 알림을 만들지 않는다.

   종류 (2026-09-19)
     PRICE_DROP     찜한 상품 가격 하락 — 하루 한 번 묶어서
     VOTE_RESULT    살!말? 투표가 10표를 넘었을 때
     WEEKLY_REPORT  주간 트렌드 리포트 — 주 1회
     BADGE          뱃지 달성
     TERM_ADDED     요청한 용어가 사전에 올라갔을 때

   내 취향 스타일의 단계 변화 · FEEDiT Pick 갱신은 아직 없다.
   판정 규칙과 Pick 의 정의가 확정되면 그때 더한다 — 지금 칸만 만들어 두면
   켜 놓고 기다려도 아무것도 오지 않는다. */
import { $, $$ } from '../../../core/static/js/dom.js';
import { AUTH } from './profile.js';
import { goView } from '../../../app_shell/static/js/router.js';
import {
  deleteAllNotifications, deleteNotification, notifications, notificationSettings,
  readAllNotifications, readNotification, requestTerm, saveNotificationSettings, session,
} from './account_api.js';

/* 설정 모달에 그릴 종류. 서버(notifications.SETTING_FIELD)와 같은 값이어야 한다. */
const KINDS = [
  { id:'PRICE_DROP',    n:'찜한 상품 가격 하락', d:'하루 한 번, 내려간 찜 상품을 묶어서 알려 드려요.' },
  { id:'VOTE_RESULT',   n:'살!말? 투표 결과',    d:'내가 올린 상품에 표가 10개 모이거나 투표가 마감되면 알려 드려요.' },
  { id:'WEEKLY_REPORT', n:'주간 트렌드 리포트',  d:'매주 월요일, 지난 한 주 리포트가 도착해요.' },
  { id:'BADGE',         n:'뱃지 달성',           d:'새 뱃지를 딴 날 알려 드려요.' },
  { id:'TERM_ADDED',    n:'용어 사전 등재',      d:'요청한 용어가 사전에 올라가면 알려 드려요.' },
  { id:'JOB_REVIEW',    n:'직업 인증 결과',      d:'신청한 직업 인증이 승인되거나 반려되면 알려 드려요.' },
];
const KIND_NAME = Object.fromEntries(KINDS.map(k => [k.id, k.n]));

const POLL_MS = 60000;          /* 1분마다 다시 센다 — 알림은 실시간일 필요가 없다 */
const LIST_MAX = 6;             /* 한 화면에 보이는 알림 수. 넘으면 스크롤 */
const NT = { items:[], unread:0, setting:null, timer:0, loading:false, open:false };

const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g,
  c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));

/* "방금 · 12분 전 · 3시간 전 · 2일 전 · 2026.09.01" */
function ago(iso){
  const t = Date.parse(iso);
  if(!Number.isFinite(t)) return '';
  const m = Math.floor((Date.now() - t) / 60000);
  if(m < 1) return '방금';
  if(m < 60) return m + '분 전';
  if(m < 60 * 24) return Math.floor(m / 60) + '시간 전';
  if(m < 60 * 24 * 7) return Math.floor(m / 1440) + '일 전';
  const d = new Date(t);
  return d.getFullYear() + '.' + String(d.getMonth() + 1).padStart(2, '0') + '.' +
    String(d.getDate()).padStart(2, '0');
}

/* ── 그리기 ───────────────────────────────────────────── */
function paintDot(){
  const dot = $('#notiDot'), btn = $('#notiBtn');
  if(dot) dot.hidden = !NT.unread;
  if(btn) btn.setAttribute('aria-label', NT.unread ? `알림 ${NT.unread}건 안 읽음` : '알림');
}

/* 휴지통 — 이모지가 아니라 아이콘 */
const TRASH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" ' +
  'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M4 7h16M10 7V5h4v2M6 7l1 12h10l1-12"/><path d="M10.5 10.5v5M13.5 10.5v5"/></svg>';

function paintList(note){
  const box = $('#notiList');
  if(!box) return;
  if(note){ box.innerHTML = '<p class="notiEmpty">' + esc(note) + '</p>'; fitList(); return }
  if(!NT.items.length){
    box.innerHTML = '<p class="notiEmpty">아직 온 알림이 없어요.</p>';
    fitList();
    return;
  }
  box.innerHTML = NT.items.map(it =>
    '<div class="notiItem' + (it.read ? '' : ' unread') + '" data-id="' + it.id + '">' +
      '<button type="button" class="notiOpen" data-link="' + esc(it.link || '') + '">' +
        '<span class="notiKind">' + esc(KIND_NAME[it.kind] || it.kind) + '</span>' +
        '<span class="notiTitle">' + esc(it.title) + '</span>' +
        (it.body ? '<span class="notiBody">' + esc(it.body) + '</span>' : '') +
        '<span class="notiAgo">' + esc(ago(it.created_at)) + '</span>' +
      '</button>' +
      '<button type="button" class="notiDel" aria-label="이 알림 삭제">' + TRASH + '</button>' +
    '</div>').join('');
  fitList();
}

/* 한 화면에 LIST_MAX 개까지만 보이게 높이를 맞춘다.
   알림마다 본문이 있고 없고라 높이가 달라서, 글자 수로 어림하지 않고
   실제로 그려진 여섯 번째 알림의 위치를 잰다. */
function fitList(){
  const box = $('#notiList');
  if(!box) return;
  const rows = box.querySelectorAll('.notiItem');
  box.classList.toggle('scrolls', rows.length > LIST_MAX);
  box.style.maxHeight = '';
  if(rows.length > LIST_MAX){
    const h = rows[LIST_MAX].offsetTop - rows[0].offsetTop;
    /* 아직 화면에 없어 재지 못하면(0) CSS 의 기본 최대 높이가 대신 막는다 */
    if(h > 0) box.style.maxHeight = h + 'px';
  }
}

/* ── 서버에서 받아 오기 ───────────────────────────────── */
export function notiRefresh(){
  if(!AUTH.in || NT.loading) return Promise.resolve();
  NT.loading = true;
  return notifications().then(data => {
    NT.items = Array.isArray(data.items) ? data.items : [];
    NT.unread = Number(data.unread || 0);
    if(data.setting) NT.setting = data.setting;
    paintDot();
    if(NT.open) paintList();
  }).catch(e => {
    if(NT.open) paintList('알림을 받아오지 못했습니다 — ' + (e.message || e));
  }).finally(() => { NT.loading = false });
}

function start(){
  const wrap = $('#notiWrap');
  if(wrap) wrap.hidden = false;
  notiRefresh();
  clearInterval(NT.timer);
  NT.timer = setInterval(() => {
    if(document.hidden || !AUTH.in) return;   /* 보이지 않는 탭에서는 세지 않는다 */
    notiRefresh();
  }, POLL_MS);
}

function stop(){
  clearInterval(NT.timer); NT.timer = 0;
  NT.items = []; NT.unread = 0; NT.setting = null;
  panel(false);
  const wrap = $('#notiWrap');
  if(wrap) wrap.hidden = true;
  paintDot();
}

/* ── 패널 여닫기 ──────────────────────────────────────── */
function panel(on){
  const p = $('#notiPanel'), b = $('#notiBtn');
  if(!p) return;
  NT.open = on === undefined ? !p.classList.contains('on') : !!on;
  p.classList.toggle('on', NT.open);
  if(b) b.setAttribute('aria-expanded', NT.open ? 'true' : 'false');
  if(NT.open){ paintList(); notiRefresh() }
}

function openItem(row){
  const id = Number(row.dataset.id);
  const open = row.querySelector('.notiOpen');
  const link = (open && open.dataset.link) || '';
  const it = NT.items.find(i => i.id === id);
  if(it && !it.read){
    it.read = true;
    NT.unread = Math.max(0, NT.unread - 1);
    row.classList.remove('unread');
    paintDot();
    readNotification(id);
  }
  if(link){ panel(false); goView(link) }
}

function delItem(row){
  const id = Number(row.dataset.id);
  const at = NT.items.findIndex(i => i.id === id);
  if(at < 0) return;
  const was = NT.items[at];
  NT.items.splice(at, 1);
  if(!was.read) NT.unread = Math.max(0, NT.unread - 1);
  paintDot(); paintList();
  deleteNotification(id).catch(e => {
    /* 못 지웠으면 되돌린다 — 지운 줄 알았는데 다음 새로고침에 살아 있으면 안 된다 */
    NT.items.splice(at, 0, was);
    if(!was.read) NT.unread += 1;
    paintDot(); paintList('지우지 못했습니다 — ' + (e.message || e));
    setTimeout(() => { if(NT.open) paintList() }, 1600);
  });
}

function delAll(){
  if(!NT.items.length) return;
  const before = NT.items.slice(), unread = NT.unread;
  NT.items = []; NT.unread = 0;
  paintDot(); paintList();
  deleteAllNotifications().catch(e => {
    NT.items = before; NT.unread = unread;
    paintDot(); paintList('지우지 못했습니다 — ' + (e.message || e));
    setTimeout(() => { if(NT.open) paintList() }, 1600);
  });
}

/* ── 알림 설정 ────────────────────────────────────────── */
function setMsg(text, bad){
  const p = $('#notiSetMsg');
  if(!p) return;
  p.textContent = text || '';
  p.classList.toggle('err', !!bad);
  p.style.display = text ? 'block' : 'none';
}

function setPaint(setting){
  const all = $('#notiSetAll'), box = $('#notiSetKinds');
  if(!all || !box) return;
  const on = setting ? setting.enabled !== false : true;
  const kinds = (setting && setting.kinds) || {};
  all.checked = on;
  box.innerHTML = KINDS.map(k =>
    '<label class="notiSetRow"><span class="notiSetName"><b>' + esc(k.n) + '</b>' +
    '<em>' + esc(k.d) + '</em></span>' +
    '<input type="checkbox" class="notiSw" data-kind="' + k.id + '"' +
    (kinds[k.id] === false ? '' : ' checked') + '>' +
    '<i class="notiSwUi" aria-hidden="true"></i></label>').join('');
  box.classList.toggle('off', !on);     /* 전체가 꺼지면 아래가 흐려진다 */
}

export function openNotiSetting(){
  const m = $('#notiSetModal');
  if(!m) return;
  setMsg('');
  setPaint(NT.setting);
  m.classList.add('on');
  /* 화면에 뜬 값은 서버 값이어야 한다 — 캐시로 먼저 그리고, 받으면 다시 그린다 */
  notificationSettings().then(s => { NT.setting = s; setPaint(s) })
    .catch(e => setMsg('설정을 받아오지 못했습니다 — ' + (e.message || e), true));
}

function saveSetting(){
  const all = $('#notiSetAll'), btn = $('#notiSetSave');
  if(!all || !btn) return;
  const kinds = {};
  $$('#notiSetKinds .notiSw').forEach(el => { kinds[el.dataset.kind] = el.checked });
  btn.disabled = true;
  const before = btn.textContent;
  btn.textContent = '저장 중…';
  setMsg('');
  saveNotificationSettings({ enabled: all.checked, kinds })
    .then(s => {
      NT.setting = s;
      setMsg('✓ 저장했습니다.');
      setTimeout(() => { const m = $('#notiSetModal'); if(m) m.classList.remove('on') }, 700);
    })
    .catch(e => setMsg('✕ ' + (e.message || e), true))
    .finally(() => { btn.disabled = false; btn.textContent = before });
}

/* ── 용어 사전 등재 요청 ──────────────────────────────────
   검색창이 "사전에 없다"고 말하는 자리(style/static/js/search.js)의 버튼이
   여기로 온다. 요청이 받아들여지면 등재된 날 TERM_ADDED 알림이 간다. */
function termReq(btn){
  const term = btn.dataset.termReq || '';
  if(!term) return;
  if(!AUTH.in){ goView('login'); return }
  btn.disabled = true;
  const before = btn.textContent;
  btn.textContent = '요청 중…';
  requestTerm(term)
    .then(d => {
      if(d.already){
        btn.textContent = '이미 사전에 있어요 — ' + d.canonical_name;
        return;
      }
      btn.textContent = d.created ? '✓ 요청했어요 — 등재되면 알림으로 알려 드려요'
                                  : '이미 요청한 용어예요';
    })
    .catch(e => {
      btn.disabled = false;
      btn.textContent = '✕ ' + (e.message || e || before);
    });
}

/* ── 묶기 ─────────────────────────────────────────────── */
function bind(){
  const btn = $('#notiBtn');
  if(btn) btn.addEventListener('click', e => { e.stopPropagation(); panel() });

  const list = $('#notiList');
  if(list) list.addEventListener('click', e => {
    const row = e.target.closest('.notiItem');
    if(!row) return;
    if(e.target.closest('.notiDel')){ delItem(row); return }
    if(e.target.closest('.notiOpen')) openItem(row);
  });

  const all = $('#notiReadAll');
  if(all) all.addEventListener('click', () => {
    if(!NT.unread) return;
    NT.items.forEach(i => { i.read = true });
    NT.unread = 0;
    paintDot(); paintList();
    readAllNotifications();
  });

  const delAllBtn = $('#notiDelAll');
  if(delAllBtn) delAllBtn.addEventListener('click', delAll);

  const link = $('#notiSetLink');
  if(link) link.addEventListener('click', () => { panel(false); openNotiSetting() });

  const save = $('#notiSetSave');
  if(save) save.addEventListener('click', saveSetting);
  [['#notiSetClose'], ['#notiSetCancel']].forEach(([sel]) => {
    const el = $(sel);
    if(el) el.addEventListener('click', () => { const m = $('#notiSetModal'); if(m) m.classList.remove('on') });
  });
  const allSw = $('#notiSetAll');
  if(allSw) allSw.addEventListener('change', () => {
    const box = $('#notiSetKinds');
    if(box) box.classList.toggle('off', !allSw.checked);
  });

  /* 패널 밖을 누르면 닫는다 (모달 오버레이는 profile.js 가 이미 처리한다) */
  document.addEventListener('click', e => {
    if(!e.target.closest('#notiWrap')) panel(false);
  });
  addEventListener('keydown', e => { if(e.key === 'Escape') panel(false) });

  /* 검색창의 '사전 등재 요청' 버튼 — 그리는 쪽은 search.js 다 */
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-term-req]');
    if(b) { e.stopPropagation(); termReq(b) }
  });

  document.addEventListener('feedit:auth', () => { AUTH.in ? start() : stop() });
}

bind();
/* 새로고침해도 세션이 살아 있으면 알림을 켠다.
   profile.js 의 세션 복구는 feedit:auth 를 쏘지 않으므로 여기서 직접 확인한다. */
session().then(d => { if(d && d.authenticated) start() }).catch(() => {});
