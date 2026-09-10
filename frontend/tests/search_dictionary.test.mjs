/* 진짜 사전(RDS)이 화면 검색과 **세부 검색 팝업**에 반영되는지 실제로 눌러 본다.
 *
 * 왜 이 시험이 필요한가
 *   화면은 search.js 에 박아 둔 146개만 보고 있었다. 그래서 RDS 사전에
 *   있는 말도 "찾지 못했습니다" 가 됐다 — 키르시·엄브로가 그랬다.
 *   그리고 할인률·리세일·수명주기의 세부 검색 팝업은 박아 둔 계층(FTREE)
 *   만 그렸다. 사전에서 온 말을 고르면 아래 칸이 텅 비면서
 *   "STYLE 을 먼저 고르세요" 라는 **틀린 안내**가 떴다.
 *
 * 여기서 지키려는 것
 *   ① 사전에만 있는 말이 검색된다
 *   ② 박아 둔 계층은 사전에 덮이지 않는다 (팝업이 계속 단계를 좁힌다)
 *   ③ 팝업 칸에 사전 항목이 실제로 그려진다
 *   ④ 계층이 없는 말을 골랐을 때 안내 문구가 사실을 말한다
 *   ⑤ 색·디테일·TPO 는 단계가 아니라 속성으로 걸린다 (골라도 안 사라진다)
 *
 * 돌리는 법:  node tests/search_dictionary.test.mjs      (jsdom 필요)
 */
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';
import fs from 'node:fs';

const F = new URL('..', import.meta.url).href.replace(/\/$/, '');
const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const dom = new JSDOM(html, { url: 'http://localhost:5173/' });
for (const k of ['window','document','Element','SVGElement','getComputedStyle','Node',
                 'HTMLElement','CustomEvent','KeyboardEvent','MouseEvent'])
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

/* ── 서버 흉내 ──────────────────────────────────────────────
   진짜 /api/dictionary 가 주는 모양 그대로다.
   ★ '발레코어' 는 일부러 넣었다 — 박아 둔 것과 겹칠 때 덮이면 안 된다.
   ★ '블랙' 은 색이다 — 단계가 아니라 속성으로 가야 한다.               */
const DICT = [
  { label: '키르시',   facet: '브랜드', kind: 'brand', en: 'KIRSH'  },
  { label: '엄브로',   facet: '브랜드', kind: 'brand', en: 'UMBRO'  },
  { label: '미니멀',   facet: '스타일', kind: 'term',  en: 'minimal'},
  { label: '발레코어', facet: '스타일', kind: 'term',  en: 'balletcore' },
  { label: '블랙',     facet: '색',     kind: 'term',  en: 'black'  },
  { label: '롱 슬리브', facet: '아이템', kind: 'term',  en: ''       },
  { label: '레이온',   facet: '소재',   kind: 'term',  en: 'rayon'  },
];
let dictCalls = 0;
globalThis.fetch = async (u) => {
  const url = String(u);
  if (url.includes('/api/dictionary')) {
    dictCalls++;
    const body = JSON.stringify({
      status: 'ok', data: DICT, total: DICT.length,
      counts: { 브랜드: 2, 스타일: 2, 색: 1, 아이템: 1, 소재: 1 },
    });
    return { ok: true, text: async () => body, json: async () => JSON.parse(body) };
  }
  const body = JSON.stringify({ status: 'empty', reason: '적재 전입니다.' });
  return { ok: true, text: async () => body, json: async () => JSON.parse(body) };
};

let pass = 0, fail = 0;
const t = async (n, f) => {
  try { await f(); console.log('✅', n); pass++; }
  catch (e) { console.log('❌', n, '\n   ', e.message); fail++; }
};

/* ★ 진짜 진입점부터 — 모듈 평가 순서를 실제 브라우저와 같게 맞춘다 */
await import(`${F}/main.js`);
const S = await import(`${F}/style/static/js/search.js`);

const idx = (f, label) => S.FIDX.find((o) => o.f === f && o.label === label);
const btns = (lv) => Array.from(document.querySelectorAll('#fsC' + lv + ' button[data-lv]'));
const labelOf = (b) => b.textContent.replace(/\d+$/, '').trim();
const hintOf = (lv) => (document.querySelector('#fsC' + lv + ' .hint') || {}).textContent || '';
const click = (el) => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));

/* main.js 를 부르는 순간 trBuild() 가 fsLoadDictionary() 를 이미 태운다.
   실제 화면과 같은 길이므로 그대로 두고, 그 결과를 확인한다. */
await new Promise((r) => setTimeout(r, 30));

/* ══ ① 박아 둔 목록에는 없던 말이다 ══════════════════════════ */
await t('키르시·미니멀은 박아 둔 목록에 없다 (이게 그 버그였다)', () => {
  for (const q of ['키르시', '엄브로', '미니멀', '롱 슬리브', '레이온', '블랙']) {
    const hard = S.FIDX.filter((o) => o.label === q && o.src !== 'db');
    assert.equal(hard.length, 0, q + ' 이 원래부터 박혀 있으면 이 시험은 무의미하다');
  }
});

/* ══ ② 사전이 얹혔다 ═════════════════════════════════════════ */
await t('★ 사전을 한 번만 받아서 없던 말만 더한다', () => {
  assert.equal(dictCalls, 1, '사전을 ' + dictCalls + '번 불렀다');
  for (const row of DICT) {
    const got = S.FIDX.filter((o) => o.f === row.facet && o.label === row.label);
    assert.equal(got.length, 1, row.label + ' 이 ' + got.length + '줄이다');
  }
});

await t('★ 사전에만 있던 말이 이제 검색된다 (키르시·엄브로·미니멀)', () => {
  for (const [q, f] of [['키르시','브랜드'], ['엄브로','브랜드'], ['미니멀','스타일']]) {
    const hit = S.fsMatch(q);
    assert.ok(hit.length, q + ' 이 안 걸린다');
    assert.equal(hit[0].f, f, q + ' 축이 ' + hit[0].f);
  }
});

await t('어디서 온 말인지 남는다 (src=db)', () => {
  assert.equal(idx('브랜드', '키르시').src, 'db');
  assert.equal(idx('소재', '레이온').src, 'db');
});

await t('★ 박아 둔 계층이 사전에 덮이지 않는다', () => {
  const b = idx('스타일', '발레코어');
  assert.equal(b.src, undefined, '박아 둔 것이 남아 있어야 한다');
  assert.deepEqual(b.path, ['발레코어'], '계층 정보가 살아 있어야 팝업이 좁힌다');
  /* 같은 축·같은 이름이 두 줄로 늘어나면 후보 목록이 지저분해진다 */
  assert.equal(S.FIDX.filter((o) => o.f === '스타일' && o.label === '발레코어').length, 1);
});

await t('다시 불러도 서버를 또 부르지 않는다', async () => {
  const before = S.FIDX.length;
  const r2 = await S.fsLoadDictionary();
  assert.equal(r2.cached, true, JSON.stringify(r2));
  assert.equal(dictCalls, 1, '서버를 또 부르면 안 된다');
  assert.equal(S.FIDX.length, before, '항목이 늘어나면 중복이다');
});

/* ══ ③ 세부 검색 팝업 — 실제로 눌러 본다 ═════════════════════ */
S.fsBuild();

await t('★ 팝업 STYLE 칸에 사전 스타일이 함께 뜬다', () => {
  const names = btns(0).map(labelOf);
  assert.ok(names.includes('스트릿'), '박아 둔 것이 먼저: ' + names.join(','));
  assert.ok(names.includes('미니멀'), '사전 것도 있어야: ' + names.join(','));
  assert.ok(names.indexOf('스트릿') < names.indexOf('미니멀'), '박아 둔 것이 위에 온다');
});

await t('사전에서 온 것은 눈으로 구분된다 (개수 뱃지 없음 + 표시)', () => {
  const tree = btns(0).find((b) => labelOf(b) === '스트릿');
  const dict = btns(0).find((b) => labelOf(b) === '미니멀');
  assert.ok(tree.querySelector('i'), '계층 항목엔 하위 개수가 붙는다');
  assert.equal(dict.querySelector('i'), null, '사전 항목엔 하위가 없다');
  assert.ok(dict.classList.contains('fromDict'));
  assert.equal(tree.classList.contains('fromDict'), false);
});

await t('★ 계층 있는 스타일을 고르면 예전처럼 종류로 좁혀진다', () => {
  click(btns(0).find((b) => labelOf(b) === '발레코어'));
  const kinds = btns(1).map(labelOf);
  assert.deepEqual(kinds, ['크롭티', '랩 스커트', '플랫 슈즈', '가디건'], kinds.join(','));
  click(btns(1).find((b) => labelOf(b) === '플랫 슈즈'));
  assert.deepEqual(btns(2).map(labelOf), ['미우미우', '레페토']);
  click(btns(2).find((b) => labelOf(b) === '레페토'));
  assert.deepEqual(btns(3).map(labelOf), ['상드리용']);
});

await t('★ 사전 스타일을 고르면 "STYLE 을 먼저 고르세요" 라고 안 한다', () => {
  document.getElementById('fsReset').dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
  click(btns(0).find((b) => labelOf(b) === '미니멀'));
  const h = hintOf(1);
  assert.ok(!/먼저 고르세요/.test(h), '방금 골랐는데 또 고르라 하면 안 된다: ' + h);
  assert.ok(h.includes('미니멀'), '무엇이 문제인지 이름을 대야 한다: ' + h);
  assert.ok(/하위 종류가 아직 없습니다/.test(h), h);
});

await t('★ 계층이 없으면 브랜드·아이템 칸은 사전으로 채운다', () => {
  const br = btns(2).map(labelOf);
  assert.ok(br.includes('키르시') && br.includes('엄브로'), br.join(','));
  assert.ok(btns(2).every((b) => b.classList.contains('fromDict')));
  assert.deepEqual(btns(3).map(labelOf), ['롱 슬리브']);
});

await t('사전 브랜드를 골라도 칩으로 남는다', () => {
  click(btns(2).find((b) => labelOf(b) === '키르시'));
  const picked = document.getElementById('fsPicked').textContent;
  assert.ok(picked.includes('키르시'), picked);
  assert.ok(picked.includes('브랜드'), picked);
});

/* ══ ④ 색·디테일·TPO — 단계가 아니라 속성 ════════════════════ */
await t('★ 색을 골라도 조건에서 사라지지 않는다', () => {
  const hit = S.fsMatch('블랙');
  assert.ok(hit.length && hit[0].f === '색', JSON.stringify(hit[0]));
  /* 예전엔 이 항목의 path 가 [] 라서 FS.sel 이 빈 배열이 되고 칩이 통째로 날아갔다 */
  S.FS.sel = [null, null, null, null]; S.FS.mat = null; S.FS.attr = [];
  const inp = document.getElementById('fsInput');
  inp.value = '블랙';
  inp.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  assert.equal(S.FS.sel.length, 4, 'FS.sel 은 언제나 네 칸이다: ' + JSON.stringify(S.FS.sel));
  assert.deepEqual(S.FS.attr, [['색', '블랙']], JSON.stringify(S.FS.attr));
  const chips = document.getElementById('fsChips').textContent;
  assert.ok(chips.includes('블랙'), '고른 게 화면에 남아야 한다: ' + chips);
});

await t('속성은 겹쳐 걸리고, 하나만 뗄 수 있다', () => {
  S.FS.attr = [['색', '블랙'], ['TPO', '데일리']];
  S.fsBuild.name;                                   // (아무 것도 안 함 — 상태만 다시 그린다)
  document.getElementById('fsMore').dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
  const picked = document.getElementById('fsPicked');
  assert.ok(picked.textContent.includes('블랙') && picked.textContent.includes('데일리'),
            picked.textContent);
  const x = picked.querySelector('[data-drop="a0"]');
  assert.ok(x, '뗄 단추가 있어야 한다');
  click(x);
  assert.deepEqual(S.FS.attr, [['TPO', '데일리']], JSON.stringify(S.FS.attr));
});

/* ══ ⑤ 할인률·리세일·수명주기 — 고른 게 조회 대상이 되는가 ══════ */
const RH = await import(`${F}/trend/static/js/render_helpers.js`);
const D  = await import(`${F}/trend/static/js/dispatch.js`);

await t('★ 아무 필터도 고르지 않으면 조회 대상은 실제로 빈 문자열이다', () => {
  S.FS.pick = {};
  assert.equal(RH.fsItem(), '');
});

await t('★ 속성만 골라도 조회 대상이 된다 (빈 화면으로 안 떨어진다)', () => {
  S.FS.sel = [null, null, null, null]; S.FS.mat = null; S.FS.attr = [['색', '블랙']];
  assert.equal(RH.fsItem(), '블랙');
  /* 더 구체적인 게 있으면 그쪽이 이긴다 */
  S.FS.sel = [null, null, '키르시', null];
  assert.equal(RH.fsItem(), '키르시');
});

for (const [id, name] of [['stock', '할인률'], ['resale', '리세일'], ['life', '수명주기']]) {
  await t(`★ ${name} — 사전에서 온 브랜드를 고르면 빈 화면이 아니다`, () => {
    S.FS.sel = [null, null, null, null]; S.FS.mat = null; S.FS.attr = [];
    D.trRender(id);
    const empty = document.getElementById('trBody').textContent;
    assert.ok(/먼저 볼 대상을 고르세요/.test(empty), '고르기 전엔 빈 화면이어야: ' + empty.slice(0, 60));

    S.FS.sel = [null, null, '키르시', null];      // 사전에만 있는 브랜드
    D.trRender(id);
    const body = document.getElementById('trBody').textContent;
    assert.ok(!/먼저 볼 대상을 고르세요/.test(body), '고른 뒤에도 빈 화면이다');
    assert.ok(body.includes('키르시'), '고른 이름이 본문에 나와야: ' + body.slice(0, 80));
  });
}

console.log(`\n${pass}개 통과 · ${fail}개 실패`);
process.exit(fail ? 1 : 0);
