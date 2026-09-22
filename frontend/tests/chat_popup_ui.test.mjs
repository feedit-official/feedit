/* 챗봇 팝업 화면 — 말풍선 아이콘 줄 · 착장 위젯 · 대화 줄 메뉴 (2026-09-14)
 *
 * 왜 있나
 *   서버가 보내는 것과 화면이 그리는 것은 다르다(AGENTS.md §5). 착장 칸을
 *   가변으로 바꾸고 옵션을 스위치로 세웠는데, 그 둘은 서버 테스트로는 한 줄도
 *   지켜지지 않는다 — 여기서 실제 DOM 을 그려 확인한다.
 *
 * 실행:  node tests/chat_popup_ui.test.mjs
 */
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';
import fs from 'node:fs';

const F = new URL('..', import.meta.url).href.replace(/\/$/, '');
const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const popupCss = fs.readFileSync(new URL('../home/static/css/chat_popup.css', import.meta.url), 'utf8');
const dom = new JSDOM(html, { url: 'http://localhost:5173/' });
for (const k of ['window','document','Element','SVGElement','getComputedStyle','Node',
                 'HTMLElement','CustomEvent','KeyboardEvent','MouseEvent','File','Blob'])
  globalThis[k] = k === 'window' ? dom.window : dom.window[k];
/* notify.js 가 본문 진입을 기다릴 때 쓴다 — 전역에 없으면 import 단계에서 통째로 죽는다 */
globalThis.MutationObserver=dom.window.MutationObserver||class{observe(){} disconnect(){} takeRecords(){return []}};
globalThis.requestAnimationFrame = (f) => setTimeout(f, 0);
globalThis.cancelAnimationFrame = (h) => clearTimeout(h);
globalThis.addEventListener = dom.window.addEventListener.bind(dom.window);
globalThis.removeEventListener = dom.window.removeEventListener.bind(dom.window);
globalThis.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });
globalThis.scrollTo = () => {};
globalThis.IntersectionObserver = class { observe(){} unobserve(){} disconnect(){} };
globalThis.ResizeObserver = class { observe(){} unobserve(){} disconnect(){} };
globalThis.location = dom.window.location;
globalThis.localStorage = dom.window.localStorage;

/* 서버는 없는 셈 친다 — /v1/health 가 실패하면 팝업은 데모 답으로 떨어진다.
   착장 생성만 성공으로 흉내 내어 결과 이미지가 들어온 화면을 본다. */
const FAKE_PNG = 'data:image/png;base64,iVBORw0KGgo=';
let fitBody = null;
globalThis.fetch = async (u, opt) => {
  const url = String(u);
  if (url.includes('/v1/virtual-fitting')) {
    fitBody = JSON.parse((opt && opt.body) || '{}');
    const body = JSON.stringify({ ok: true, image: FAKE_PNG });
    return { ok: true, text: async () => body, json: async () => JSON.parse(body) };
  }
  if (url.includes('/v1/fit-classify')) {
    const body = JSON.stringify({ ok: true, categories: [] });
    return { ok: true, text: async () => body, json: async () => JSON.parse(body) };
  }
  throw new Error('offline');            /* isUp() 실패 → 데모 답 */
};

let pass = 0, fail = 0;
const t = async (n, f) => {
  try { await f(); console.log('✅', n); pass++; }
  catch (e) { console.log('❌', n, '\n   ', e.message); fail++; }
};
const wait = (ms = 0) => new Promise(r => setTimeout(r, ms));

await import(`${F}/main.js`);
const CP = await import(`${F}/home/static/js/chat_popup.js`);
const P  = await import(`${F}/account/static/js/profile.js`);
P.AUTH.in = true;                        /* 로그인 관문을 지난 상태로 둔다 */

const thread = () => document.querySelector('#cpThread');
const click = (el) => el.dispatchEvent(new dom.window.MouseEvent('click', {bubbles:true}));

await t('사진 관찰값이 다음 요청의 history에 그대로 남는다', () => {
  const visual = {
    item: '미디 스커트', colors: ['블랙'], materials: ['광택 있는 직물로 보임'],
    silhouette: ['미디 길이'], details: ['밑단 레이스'], uncertainties: ['혼용률 미확인']
  };
  const got = CP.cpHistoryFor({messages: [
    {role: 'me', text: '이거 어때?'},
    {role: 'ai', turn: {q: '이거 어때?', intent: 'vision.salmal', terms: [], visual}},
    {role: 'ai', pending: true},
  ]});
  assert.equal(got.length, 1, '완료된 사진 턴 하나만 보내야 한다');
  assert.deepEqual(got[0].visual, visual);
});

/* ── 내 말풍선 아래 아이콘 줄 ───────────────────────────── */
CP.openChatWith('트렌드 TOP 10 알려줘', null, { fresh: true });
await wait(30);

await t('내 말풍선에 재전송·수정·복사 아이콘이 함께 붙는다', () => {
  const acts = thread().querySelector('.msg.me .cpMeActs');
  assert.ok(acts, '아이콘 줄이 없다');
  assert.ok(acts.querySelector('[data-resend]'), '재전송이 없다');
  assert.ok(acts.querySelector('[data-again]'), '수정이 없다');
  assert.ok(acts.querySelector('[data-copy]'), '복사가 없다');
  assert.equal(acts.querySelectorAll('svg').length, 3, '아이콘은 셋이다');
});

await t('재전송은 같은 질문을 한 턴 더 쌓는다', async () => {
  const before = thread().querySelectorAll('.msg.me').length;
  click(thread().querySelector('.msg.me [data-resend]'));
  await wait(30);
  const after = [...thread().querySelectorAll('.msg.me')];
  assert.equal(after.length, before + 1, '턴이 늘지 않았다');
  assert.match(after[after.length - 1].textContent, /트렌드 TOP 10 알려줘/);
});

/* ── 마지막 질문 그 자리에서 고치기 (2026-09-14) ───────────
   예전에는 연필이 글을 입력창으로 되돌렸다 — 눈이 화면 아래로 내려가고,
   무엇을 고치는 중인지 말풍선 쪽에는 표시가 없었다. */
await t('수정 연필은 마지막 질문에만 붙는다', () => {
  const mine = [...thread().querySelectorAll('.msg.me')];
  assert.ok(mine.length >= 2, '질문이 둘 이상 있어야 본다');
  assert.equal(mine[0].querySelector('[data-again]'), null,
               '중간 질문에도 연필이 붙었다 — 고치면 뒤 대화가 날아간다');
  assert.ok(mine[mine.length - 1].querySelector('[data-again]'), '마지막에 연필이 없다');
  assert.ok(mine[0].querySelector('[data-resend]'), '재전송은 모든 질문에 남아야 한다');
  assert.ok(mine[0].querySelector('[data-copy]'), '복사는 모든 질문에 남아야 한다');
});

await t('연필을 누르면 말풍선이 그 자리에서 입력칸이 된다', async () => {
  document.querySelector('#cpInput').value = '';
  const mine = [...thread().querySelectorAll('.msg.me')];
  click(mine[mine.length - 1].querySelector('[data-again]'));
  await wait(20);
  const box = thread().querySelector('.msg.me.editing .cpEditIn');
  assert.ok(box, '고치는 칸이 안 열렸다');
  assert.equal(box.value, '트렌드 TOP 10 알려줘');
  assert.ok(thread().querySelector('[data-edit-save]'), '저장이 없다');
  assert.ok(thread().querySelector('[data-edit-cancel]'), '취소가 없다');
  assert.equal(document.querySelector('#cpInput').value, '', '입력창으로 샜다');
});

await t('수정 입력칸은 원문 말풍선 크기를 잡는 복제 문장을 사용한다', () => {
  const edit = thread().querySelector('.msg.me.editing');
  const box = edit&&edit.querySelector('.cpEditIn');
  const sizer = edit&&edit.querySelector('.cpEditSizer');
  assert.ok(box&&sizer, '말풍선 크기를 유지할 sizer가 없다');
  assert.equal(sizer.textContent, box.value, 'sizer와 수정 원문이 다르다');
  assert.match(popupCss, /\.cpEditBox\{[\s\S]*?width:max-content;max-width:62%/,
               '수정 상자가 원래 말풍선처럼 내용 폭을 따르지 않는다');
  assert.match(popupCss, /\.cpEditSizer,\.cpEditIn\{[\s\S]*?padding:12px 17px[\s\S]*?font-size:14px/,
               '수정 글꼴·여백이 팝업 말풍선과 다르다');
});

await t('취소하면 원래 말풍선으로 돌아온다', async () => {
  click(thread().querySelector('[data-edit-cancel]'));
  await wait(20);
  assert.equal(thread().querySelector('.msg.me.editing'), null, '고치는 칸이 남아 있다');
  const mine = [...thread().querySelectorAll('.msg.me')];
  assert.match(mine[mine.length - 1].textContent, /트렌드 TOP 10 알려줘/);
});

await t('저장하면 고친 질문으로 다시 묻고 그 뒤 답변은 지워진다', async () => {
  const store = () => CP.cpStore().convos.find(c => c.id === CP.cpStore().activeId);
  const mine = [...thread().querySelectorAll('.msg.me')];
  click(mine[mine.length - 1].querySelector('[data-again]'));
  await wait(20);
  const before = store().messages.length;
  thread().querySelector('.cpEditIn').value = '발레코어 지금 사도 될까?';
  click(thread().querySelector('[data-edit-save]'));
  await wait(80);
  /* 고친 질문과 새 답이 옛 자리를 그대로 쓴다 — 턴 수가 늘지 않는다 */
  assert.equal(store().messages.length, before, `턴 수가 ${store().messages.length} 로 어긋났다`);
  const last = [...thread().querySelectorAll('.msg.me')].pop();
  assert.match(last.textContent, /발레코어 지금 사도 될까\?/);
  assert.equal(thread().querySelector('.msg.me.editing'), null);
});

await t('고치는 칸에서 Esc 는 팝업까지 닫지 않는다', async () => {
  const mine = [...thread().querySelectorAll('.msg.me')];
  click(mine[mine.length - 1].querySelector('[data-again]'));
  await wait(20);
  thread().querySelector('.cpEditIn')
    .dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  await wait(20);
  assert.equal(thread().querySelector('.msg.me.editing'), null, 'Esc 로 안 닫혔다');
  assert.ok(document.querySelector('#cpOverlay').classList.contains('on'),
            '팝업까지 같이 닫혔다');
});

/* ── 착장 위젯 ──────────────────────────────────────────── */
CP.openChatWith('이거 입혀줘', null, { fresh: true, images: [FAKE_PNG] });
await wait(60);

await t('칸은 넣은 사진 수만큼만 열린다 (2026-09-14)', () => {
  const slots = thread().querySelectorAll('.cpFit .cpFitSlot:not(.addSlot)');
  assert.equal(slots.length, 1, `사진 한 장인데 칸이 ${slots.length}개다`);
  assert.ok(thread().querySelector('.cpFit [data-vf-add]'), '칸 늘리기 ＋ 가 없다');
  const opts = [...thread().querySelectorAll('.cpFitCat')[0].options].map(o => o.value);
  for (const c of ['상의','하의','아우터','원피스(셋업)','신발','양말','모자','벨트','안경','자동 분류'])
    assert.ok(opts.includes(c), `${c} 가 목록에 없다`);
});

await t('모델 고르기가 칸보다 위에 선다', () => {
  const setup = thread().querySelector('.cpFitSetup');
  const kids = [...setup.children];
  assert.ok(kids.indexOf(setup.querySelector('.cpFitModels')) <
            kids.indexOf(setup.querySelector('.cpFitItems')), '모델이 칸 아래에 있다');
});

await t('＋ 는 칸을 한 개씩 늘리고, × 는 칸째로 뺀다', async () => {
  const n = () => thread().querySelectorAll('.cpFit .cpFitSlot:not(.addSlot)').length;
  click(thread().querySelector('[data-vf-add]')); await wait(10);
  assert.equal(n(), 2, '＋ 를 눌러도 칸이 늘지 않았다');
  click(thread().querySelector('[data-vf-add]')); await wait(10);
  assert.equal(n(), 3);
  const del = thread().querySelectorAll('[data-vf-remove]');
  click(del[del.length - 1]); await wait(10);
  assert.equal(n(), 2, '× 를 눌러도 칸이 줄지 않았다');
});

await t('칸은 아홉(서버 MAX_ITEMS)에서 멈추고 ＋ 가 사라진다', async () => {
  for (let i = 0; i < 12; i++) {
    const add = thread().querySelector('[data-vf-add]');
    if (!add) break;
    click(add); await wait(5);
  }
  assert.equal(thread().querySelectorAll('.cpFit .cpFitSlot:not(.addSlot)').length, 9);
  assert.equal(thread().querySelector('[data-vf-add]'), null, '아홉 칸인데 ＋ 가 남아 있다');
  /* 뒤 시험이 한 칸짜리를 기대하므로 되돌린다 */
  for (let i = 0; i < 8; i++) {
    const del = thread().querySelectorAll('[data-vf-remove]');
    click(del[del.length - 1]); await wait(5);
  }
  assert.equal(thread().querySelectorAll('.cpFit .cpFitSlot:not(.addSlot)').length, 1);
});

await t('드롭다운으로 칸의 축을 바꾸면 그 값이 생성 요청에 실린다', async () => {
  const sel = thread().querySelectorAll('.cpFitCat')[0];
  sel.value = '모자';
  sel.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  await wait(10);
  click(thread().querySelector('[data-vf-generate]'));
  await wait(60);
  assert.equal(fitBody.items[0].category, '모자');
});

await t('옵션 서랍은 접혀 있다가 눌러야 열리고, 스위치 다섯이 선다', async () => {
  assert.equal(thread().querySelectorAll('.cpVfSw').length, 0, '처음부터 펼쳐져 있다');
  click(thread().querySelector('[data-vf-opts]'));
  await wait(10);
  const sw = thread().querySelectorAll('.cpVfSw');
  assert.equal(sw.length, 5);
  for (const b of sw) assert.equal(b.getAttribute('role'), 'switch', '스위치가 아니다');
  const titles = [...thread().querySelectorAll('.cpVfGroupTitle')].map(x => x.textContent);
  assert.deepEqual(titles, ['아우터 레이어드', '아우터 열기/닫기', '상의 열기/닫기']);
});

await t('옵션을 눌러도 대화가 맨 아래로 튀지 않는다 (2026-09-14)', async () => {
  const wrap = document.querySelector('#cpThreadWrap');
  /* jsdom 에는 레이아웃이 없어 scrollHeight 가 0이다 — 값을 세워 두고 본다 */
  Object.defineProperty(wrap, 'scrollHeight', { value: 4000, configurable: true });
  wrap.scrollTop = 1200;
  click(thread().querySelector('[data-vf-opt="outer_layered"]'));
  await wait(10);
  assert.equal(wrap.scrollTop, 1200, `보던 자리가 ${wrap.scrollTop} 로 튀었다`);
  click(thread().querySelector('[data-vf-opt="outer_layered"]'));  /* 되돌린다 */
  await wait(10);
});

await t('아무 옵션도 켜지 않으면 전부 false 로 나간다 (예전 동작)', async () => {
  click(thread().querySelector('[data-vf-generate]'));
  await wait(60);
  assert.deepEqual(fitBody.options,
    {outer_layered:false, outer_open:false, outer_closed:false, top_open:false, top_closed:false});
});

await t('열기와 닫기는 같이 켜지지 않는다', async () => {
  const opt = (k) => thread().querySelector('[data-vf-opt="' + k + '"]');
  click(opt('outer_layered')); await wait(10);
  click(opt('outer_open'));    await wait(10);
  click(opt('outer_closed'));  await wait(10);
  click(thread().querySelector('[data-vf-generate]'));
  await wait(60);
  assert.equal(fitBody.options.outer_layered, true);
  assert.equal(fitBody.options.outer_closed, true);
  assert.equal(fitBody.options.outer_open, false, '열기와 닫기가 같이 켜졌다');
});

await t('결과가 나오면 이미지 저장 버튼이 붙는다', () => {
  const a = thread().querySelector('.cpFitDl');
  assert.ok(a, '저장 버튼이 없다');
  assert.equal(a.getAttribute('href'), FAKE_PNG);
  assert.match(a.getAttribute('download'), /\.png$/);
});

/* 4K 로 올리면서 결과를 webp 로 받게 됐다(vton.OUTPUT_FORMAT). 저장 이름만
   .png 로 박혀 있으면 내려받은 파일이 이름과 속이 다르다. (2026-09-14) */
await t('저장 파일 확장자는 서버가 보낸 형식을 따른다', async () => {
  const m = CP.cpStore().convos.find(c => c.messages.some(x => x.fit))
    .messages.filter(x => x.fit).pop();
  const was = { result: m.fit.result, format: m.fit.format };
  m.fit.result = 'data:image/webp;base64,UklGRg=='; m.fit.format = 'webp';
  CP.cpRenderThread({ keepScroll: true });
  await wait(10);
  assert.match(thread().querySelector('.cpFitDl').getAttribute('download'), /\.webp$/);
  /* format 을 안 보내던 옛 대화는 data URL 에서 읽어 낸다 */
  m.fit.format = '';
  CP.cpRenderThread({ keepScroll: true });
  await wait(10);
  assert.match(thread().querySelector('.cpFitDl').getAttribute('download'), /\.webp$/);
  Object.assign(m.fit, was);
  CP.cpRenderThread({ keepScroll: true });
  await wait(10);
});

/* ── 리포트 저장 · 공유 ─────────────────────────────────────
   진짜 리포트는 서버가 붙여 준다. 여기서는 카드 마크업만 스레드에 넣고
   버튼이 실제로 배선돼 있는지(눌렀을 때 아무 일도 안 일어나지 않는지)를 본다.
   jsdom 에는 canvas 가 없어 이미지 저장까지는 갈 수 없다 — 그래서 공유 쪽의
   '마지막 수단'(클립보드)이 실패했을 때 사용자에게 말하는지를 확인한다. */
const API = await import(`${F}/home/static/js/chat_api.js`);

await t('리포트 카드 머리줄에 공유·저장 버튼이 붙는다', () => {
  const card = API.reportHTML({ blocks: [{ type: 'rank', slot: 'full', title: 'TOP',
    rows: [{ k: '자켓', v: '86', up: true }] }] });
  assert.match(card, /data-rp-share/);
  assert.match(card, /data-rp-save/);
  const say = thread().querySelector('.msg.ai .say');
  say.parentElement.insertAdjacentHTML('beforeend', card);
});

await t('공유를 누르면 결과를 말한다 (조용히 끝나지 않는다)', async () => {
  click(thread().querySelector('[data-rp-share]'));
  await wait(60);
  const toast = document.querySelector('#cpToast');
  assert.ok(toast, '알림 한 줄이 없다');
  assert.ok(toast.textContent.trim().length > 0, '알림이 비어 있다');
});

/* ── 칸이 늘어도 결과 칸은 안 늘어난다 (2026-09-14) ────────
   jsdom 에는 레이아웃이 없어 실제 높이는 잴 수 없다. 대신 (1) 높이를 정하는
   쪽이 살아 있는지와 (2) 레이아웃이 없을 때 0 을 물고 칸을 접어 버리지
   않는지를 본다. 이 둘이 깨지면 아홉 칸까지 늘렸을 때 왼쪽이 길어지고
   .cpFitGrid(align-items:stretch) 때문에 오른쪽 검은 칸까지 같이 늘어난다. */
await t('칸 목록은 스크롤이 걸려 있고 타일은 정사각형이다', () => {
  const css = fs.readFileSync(new URL('../home/static/css/chat_popup.css', import.meta.url), 'utf8');
  const rule = css.match(/\.cpFitItems\{[^}]*\}/s);
  assert.ok(rule, '.cpFitItems 규칙이 없다');
  assert.match(rule[0], /overflow-y:\s*auto/, '스크롤이 걸려 있지 않다');
  const tile = css.match(/\.cpFitItem\{[^}]*\}/s);
  assert.match(tile[0], /aspect-ratio:\s*1/, '타일이 정사각형이 아니다');
});

await t('두 줄 상한은 실제로 잰 한 줄 높이로 잡는다', () => {
  const box = thread().querySelector('.cpFitItems');
  assert.ok(box, '칸 목록이 없다');
  /* 레이아웃이 없으면(offsetHeight 0) 손대지 않는다 — 0 을 쓰면 칸이 접힌다 */
  assert.equal(box.style.maxHeight, '', '높이를 못 쟀는데 값을 박았다');
  /* 한 줄이 100px 인 척하고 다시 재게 한다: 2줄 + 간격 10 + 비침 18 = 228 */
  const slot = box.querySelector('.cpFitSlot:not(.addSlot)');
  Object.defineProperty(slot, 'offsetHeight', { value: 100, configurable: true });
  CP.cpFitSizeItems(thread());
  assert.equal(box.style.maxHeight, '228px', `상한이 ${box.style.maxHeight} 로 잡혔다`);
  box.style.maxHeight = '';
});

/* ── 대화 목록 줄 메뉴 (2026-09-14) ───────────────────────
   연필·휴지통 두 버튼을 ⋮ 하나로 모았다. 고정·이름 변경·삭제가 거기서 나온다. */
const list = () => document.querySelector('#cpList');
const menu = () => document.querySelector('#cpMenu');

await t('대화 줄에는 ⋮ 하나만 있고 연필·휴지통은 없다', () => {
  CP.cpRenderList();
  assert.ok(list().querySelector('.cpKebab[data-menu]'), '⋮ 가 없다');
  assert.equal(list().querySelector('.cpEdit'), null, '연필이 남아 있다');
  assert.equal(list().querySelector('.cpDel'), null, '휴지통이 남아 있다');
});

await t('⋮ 를 누르면 고정·이름 변경·삭제가 뜬다', () => {
  CP.cpOpenMenu(list().querySelector('.cpKebab[data-menu]'));
  const items = [...menu().querySelectorAll('[data-mi]')].map(b => b.dataset.mi);
  assert.deepEqual(items, ['pin', 'rename', 'del']);
  assert.equal(menu().hidden, false);
});

await t('삭제는 한 번 더 묻는다 — 바로 지우지 않는다', async () => {
  const before = CP.cpStore().convos.length;
  click(menu().querySelector('[data-mi="del"]'));
  await wait(10);
  assert.equal(CP.cpStore().convos.length, before, '묻지도 않고 지웠다');
  assert.ok(menu().querySelector('[data-mi="del-yes"]'), '확인 줄이 없다');
  click(menu().querySelector('[data-mi="cancel"]'));
  await wait(10);
  assert.equal(CP.cpStore().convos.length, before);
});

await t('고정한 대화는 목록 맨 위로 올라간다', async () => {
  const s = CP.cpStore();
  assert.ok(s.convos.length >= 2, '대화가 둘 이상 있어야 본다');
  const last = s.convos[s.convos.length - 1];
  CP.cpOpenMenu(list().querySelector('.cpKebab[data-menu="' + last.id + '"]'));
  click(menu().querySelector('[data-mi="pin"]'));
  await wait(10);
  assert.equal(CP.cpStore().convos[0].id, last.id, '고정했는데 위로 안 갔다');
  assert.ok(list().querySelector('.cpItemRow.pinned'), '고정 표시가 없다');
});

await t('메뉴에 적어 둔 글쇠(P·R·D)가 실제로 먹는다', async () => {
  const s = CP.cpStore();
  const target = s.convos.find(c => !c.pinned) || s.convos[0];
  CP.cpOpenMenu(list().querySelector('.cpKebab[data-menu="' + target.id + '"]'));
  const was = !!target.pinned;
  document.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'p', bubbles: true }));
  await wait(10);
  assert.equal(!!CP.cpStore().convos.find(c => c.id === target.id).pinned, !was, 'P 가 안 먹는다');
  /* D 는 바로 지우지 않고 확인 줄을 연다 */
  CP.cpOpenMenu(list().querySelector('.cpKebab[data-menu="' + target.id + '"]'));
  const before = CP.cpStore().convos.length;
  document.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'd', bubbles: true }));
  await wait(10);
  assert.equal(CP.cpStore().convos.length, before, 'D 가 묻지도 않고 지웠다');
  assert.ok(menu().querySelector('[data-mi="del-yes"]'), 'D 로 확인 줄이 안 열렸다');
  click(menu().querySelector('[data-mi="cancel"]'));
  await wait(10);
});

await t('바깥을 누르면 메뉴가 닫힌다', async () => {
  CP.cpOpenMenu(list().querySelector('.cpKebab[data-menu]'));
  assert.equal(menu().hidden, false);
  click(document.body);
  await wait(10);
  assert.equal(menu().hidden, true, '메뉴가 떠 있다');
});

/* ── Virtual Try On 단독 진입 (2026-09-18) ──────────────
   질문을 먼저 보내지 않아도 팝업 버튼이 빈 착장을 연다. */
await t('팝업 왼쪽 하단에만 Virtual Try On 버튼이 있다', () => {
  assert.equal(document.querySelector('#homeVtonQuick'), null, '홈 챗바 위 버튼이 남아 있다');
  assert.ok(document.querySelector('#cpVtonQuick'), '팝업 버튼이 없다');
  assert.match(popupCss, /\.cpOverlay\.sm \.cpVtonQuick\{display:flex/,
               '팝업 버튼이 살말 모드에서 보이지 않는다');
});

await t('질문 없이 바로 빈 착장 위젯을 연다', async () => {
  CP.openVirtualTryOn();
  await wait(340);
  const c = CP.cpStore().convos.find(x => x.id === CP.cpStore().activeId);
  assert.equal(c.title, 'Virtual Try On');
  assert.equal(c.transient, true, '저장될 수 없는 착장 상태가 대화 기록으로 남는다');
  assert.equal(c.messages.some(m => m.role === 'me'), false, '질문 메시지가 자동으로 생겼다');
  assert.ok(thread().querySelector('.cpFit'), '착장 위젯이 없다');
  assert.equal(thread().querySelectorAll('.cpFitSlot:not(.addSlot)').length, 1,
               '첫 사진을 넣을 빈 칸이 하나여야 한다');
  assert.equal(document.querySelector('#cpOverlay').classList.contains('sm'), true,
               '살말 팝업으로 열리지 않았다');
});

await t('팝업 버튼이 독립 착장을 연다', async () => {
  const count = () => CP.cpStore().convos.length;
  const before = count();
  click(document.querySelector('#cpVtonQuick'));
  await wait(40);
  assert.equal(count(), before + 1, '팝업 버튼이 새 착장을 열지 않았다');
});

console.log(`\n${pass}개 통과 · ${fail}개 실패`);
process.exit(fail ? 1 : 0);
