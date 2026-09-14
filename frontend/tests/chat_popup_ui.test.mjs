/* 챗봇 팝업 화면 — 말풍선 아이콘 줄 · 착장 위젯 (2026-09-14)
 *
 * 왜 있나
 *   서버가 보내는 것과 화면이 그리는 것은 다르다(AGENTS.md §5). 착장 칸을
 *   아홉으로 늘리고 옵션 서랍을 붙였는데, 그 둘은 서버 테스트로는 한 줄도
 *   지켜지지 않는다 — 여기서 실제 DOM 을 그려 확인한다.
 *
 * 실행:  node tests/chat_popup_ui.test.mjs
 */
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';
import fs from 'node:fs';

const F = new URL('..', import.meta.url).href.replace(/\/$/, '');
const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const dom = new JSDOM(html, { url: 'http://localhost:5173/' });
for (const k of ['window','document','Element','SVGElement','getComputedStyle','Node',
                 'HTMLElement','CustomEvent','KeyboardEvent','MouseEvent','File','Blob'])
  globalThis[k] = k === 'window' ? dom.window : dom.window[k];
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

await t('수정은 질문을 입력창으로 되돌린다', () => {
  document.querySelector('#cpInput').value = '';
  click(thread().querySelector('.msg.me [data-again]'));
  assert.equal(document.querySelector('#cpInput').value, '트렌드 TOP 10 알려줘');
});

await t('재전송은 같은 질문을 한 턴 더 쌓는다', async () => {
  const before = thread().querySelectorAll('.msg.me').length;
  click(thread().querySelector('.msg.me [data-resend]'));
  await wait(30);
  const after = [...thread().querySelectorAll('.msg.me')];
  assert.equal(after.length, before + 1, '턴이 늘지 않았다');
  assert.match(after[after.length - 1].textContent, /트렌드 TOP 10 알려줘/);
});

/* ── 착장 위젯 ──────────────────────────────────────────── */
CP.openChatWith('이거 입혀줘', null, { fresh: true, images: [FAKE_PNG] });
await wait(60);

await t('칸은 아홉이고 모자·벨트·안경까지 드롭다운으로 고를 수 있다', () => {
  const slots = thread().querySelectorAll('.cpFit .cpFitSlot');
  assert.equal(slots.length, 9, `칸이 ${slots.length}개다`);
  const opts = [...thread().querySelectorAll('.cpFitCat')[0].options].map(o => o.value);
  for (const c of ['상의','하의','아우터','원피스(셋업)','신발','양말','모자','벨트','안경','자동 분류'])
    assert.ok(opts.includes(c), `${c} 가 목록에 없다`);
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

await t('옵션 서랍은 접혀 있다가 눌러야 열린다', async () => {
  assert.equal(thread().querySelectorAll('.cpFitOpt').length, 0, '처음부터 펼쳐져 있다');
  click(thread().querySelector('[data-vf-opts]'));
  await wait(10);
  assert.equal(thread().querySelectorAll('.cpFitOpt').length, 5);
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

console.log(`\n${pass}개 통과 · ${fail}개 실패`);
process.exit(fail ? 1 : 0);
