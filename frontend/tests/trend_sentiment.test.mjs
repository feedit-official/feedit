/* 긍부정 탭 — 반응 건수 막대 · DB 의도 6종 신호표.
 *
 * ★ 무엇을 보나
 *   · '지수 추이' 차트가 긍정·중립·부정 **건수**(pos_n·neu_n·neg_n)를 막대로 그린다.
 *     비율(%) 선이 아니다.
 *   · 주별·월별은 구간 **합계**다. 평균이 아니다.
 *   · 적재가 없던 날은 막대를 세우지 않는다(옆 값을 복사해 채우지 않는다).
 *   · '신호 유형별 건수' 가 analysis.term_metric_daily 의 6칸
 *     (질문·구매·경험·호평·비판·잡담) 그대로다. 0건도 0 으로 남는다.
 *
 * 돌리는 법:  node tests/trend_sentiment.test.mjs      (jsdom 필요)
 */
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';
import fs from 'node:fs';

const W = new URL('..', import.meta.url).href.replace(/\/$/, '');
/* dispatch.js 는 앱 전체 모듈을 끌고 온다 — 빈 문서로는 import 가 안 된다. 실제 index.html 을 쓴다. */
const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8')
  .replace(/<script[\s\S]*?<\/script>/g, '');
const dom = new JSDOM(html, { url: 'http://localhost:5173/', pretendToBeVisual: true });
/* 브라우저 전역을 통째로 올린다 (addEventListener·HTMLElement 등). Node 가 이미 가진 것은 건드리지 않는다. */
globalThis.window = dom.window;
const winKeys = new Set();
for (let o = dom.window; o && o !== Object.prototype; o = Object.getPrototypeOf(o))
  Object.getOwnPropertyNames(o).forEach(k => winKeys.add(k));
for (const k of winKeys) {
  if (k in globalThis) continue;
  try { const v = dom.window[k]; globalThis[k] = typeof v === 'function' && !/^[A-Z]/.test(k) ? v.bind(dom.window) : v; } catch (e) {}
}
for (const k of ['navigator','localStorage','sessionStorage','location','history','Event','CustomEvent','EventTarget'])
  try { Object.defineProperty(globalThis, k, { value: dom.window[k], configurable: true, writable: true }); } catch (e) {}
globalThis.matchMedia ||= () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} });
dom.window.matchMedia ||= globalThis.matchMedia;

let reply = null;
globalThis.fetch = async () => ({ ok: true, status: 200,
  text: async () => JSON.stringify(reply), json: async () => reply });

let pass = 0, fail = 0;
const t = async (n, f) => { try { await f(); console.log('✅', n); pass++; }
  catch (e) { console.log('❌', n, '\n   ', e.stack.split('\n').slice(0, 3).join('\n    ')); fail++; } };

/* Django /api/trend 의 _metric_point 와 같은 이름으로 만든 60일치 */
const LAST = '2026-09-10';
const rows = (n, f) => { const o = []; for (let i = n - 1; i >= 0; i--) {
  const d = new Date(LAST + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() - i);
  o.push(f(d.toISOString().slice(0, 10), i)); } return o; };
const base = (date, i) => ({ date, mention: 20, temp: 50, pos_n: 10 + (i % 3), neu_n: 5, neg_n: 2,
  pos_rate: 58, neu_rate: 29, neg_rate: 13, question_n: 3, purchase_n: 4, experience_n: 2,
  praise_n: 5, critique_n: 1, chitchat_n: 0, intent: 62 });

/* 앱과 같은 순서로 올린다 — 모듈끼리 서로 물고 있어 dispatch.js 만 따로 부르면 초기화 순서가 꼬인다 */
await import(`${W}/main.js`);
const live = await import(`${W}/trend/static/js/live_data.js`);
const { KW } = await import(`${W}/trend/static/js/render_helpers.js`);
const D = await import(`${W}/trend/static/js/dispatch.js`);
const body = () => document.getElementById('trBody');
const click = (c, g) => c.querySelector(`.gSel button[data-g="${g}"]`)
  .dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
/* 차트 기본 단위는 주별이다. 일별로 보려면 버튼을 누른다. */
const render = async (term, series, g = 'd') => {
  reply = { status: 'ok', data: { term, facet: 'STYLE', series } };
  await live.prime(term);
  KW.q = term;
  D.trRender('sentiment');
  const c = body().querySelector('[data-chart="sentMain"]');
  if (g && c.querySelector('.gSel')) click(c, g);
};

await t('차트가 막대(건수)로 그려진다 — 비율 선이 아니다', async () => {
  await render('발레코어', rows(60, base));
  const c = body().querySelector('[data-chart="sentMain"]');
  assert.equal(c.dataset.live, 'ok');
  assert.equal(c.querySelectorAll('path.ln,path.ln2').length, 0, '선이 남아 있다');
  const bars = c.querySelectorAll('rect.gBar');
  assert.equal(bars.length, 30 * 3, '일별 30칸 × 3계열');
  assert.match(body().textContent, /긍정 · 중립 · 부정 반응 건수 추이/);
  assert.deepEqual([...c.querySelectorAll('.gLegend span')].map(s => s.textContent), ['긍정', '중립', '부정']);
});

await t('막대 높이가 건수에 비례한다 (마지막 날 긍정 10 · 중립 5 · 부정 2)', async () => {
  const c = body().querySelector('[data-chart="sentMain"]');
  const h = id => [...c.querySelectorAll(`rect.gBar[data-s="${id}"]`)].map(r => +r.getAttribute('height'));
  const [p, u, n] = [h('p').at(-1), h('u').at(-1), h('n').at(-1)];
  assert.ok(Math.abs(p / u - 10 / 5) < 0.05, `긍정/중립 ${p}/${u}`);
  assert.ok(Math.abs(u / n - 5 / 2) < 0.05, `중립/부정 ${u}/${n}`);
});

await t('주별은 7일 합계다 (평균이 아니다)', () => {
  const s = live.seriesOf('발레코어', { points: 4, step: 'w', field: 'neu_n', raw: true, agg: 'sum', fill: false });
  assert.deepEqual(s, [35, 35, 35, 35]);
  const avg = live.seriesOf('발레코어', { points: 4, step: 'w', field: 'neu_n', raw: true });
  assert.deepEqual(avg, [5, 5, 5, 5], '기존 평균 경로는 그대로');
});

await t('주별 · 월별 전환이 막대로 다시 그려진다', async () => {
  const c = body().querySelector('[data-chart="sentMain"]');
  click(c, 'w');
  /* 26주 칸 중 자료가 있는 건 60일치 → 9주. 나머지 칸은 비워 둔다 */
  assert.equal(c.querySelectorAll('rect.gBar').length, 9 * 3);
  const wk = [...c.querySelectorAll('rect.gBar[data-s="u"]')].map(r => +r.getAttribute('height'));
  assert.ok(wk.length === 9 && wk.every(h => h > 0));
  click(c, 'm');
  assert.ok(c.querySelectorAll('rect.gBar').length > 0);
  assert.equal(c.querySelectorAll('path.ln,path.ln2').length, 0);
});

await t('적재가 없던 날은 막대를 세우지 않는다 (옆 값 복사 금지)', async () => {
  const s = rows(60, base).filter((r, i) => i !== 59 - 3);   // 끝에서 4번째 날 빠짐
  await render('새틴', s);
  const c = body().querySelector('[data-chart="sentMain"]');
  assert.equal(c.querySelectorAll('rect.gBar').length, 29 * 3);
});

await t('신호 유형이 DB 6칸 그대로 · 이 순서 · 0건도 남는다', async () => {
  await render('발레코어2', rows(60, base));
  const tr = [...body().querySelectorAll('#sigWrap tr[data-sig]')];
  assert.deepEqual(tr.map(r => r.dataset.sig), ['질문', '구매', '경험', '호평', '비판', '잡담']);
  const n = tr.map(r => r.querySelector('td.n').textContent);
  assert.deepEqual(n, ['84', '112', '56', '140', '28', '0'], '최근 28일 합계');
  assert.doesNotMatch(body().querySelector('#sigWrap').textContent, /부정 반응|구매 반응|경험 공유/);
});

await t('KPI 최다 긍정·부정 신호가 6칸에서 뽑힌다', () => {
  const txt = body().querySelector('.kpis').textContent;
  assert.match(txt, /최다 긍정 신호\s*호평/);
  assert.match(txt, /최다 부정 신호\s*비판/);
});

await t('의도 6칸이 전부 0 이면 표 대신 "아직 없음" 을 적는다', async () => {
  const z = rows(60, (d, i) => ({ ...base(d, i), question_n: 0, purchase_n: 0, experience_n: 0, praise_n: 0, critique_n: 0, chitchat_n: 0 }));
  await render('키르시', z);
  assert.equal(body().querySelectorAll('#sigWrap tr[data-sig]').length, 0);
  assert.match(body().querySelector('#sigWrap').textContent, /질문·구매·경험·호평·비판·잡담/);
});

await t('건수 칸이 없는 응답(예전 API)이면 막대를 지어내지 않는다', async () => {
  const old = rows(60, (d) => ({ date: d, mention: 20, pos_rate: 50, neg_rate: 20, intent: 40 }));
  await render('옛응답', old);
  const c = body().querySelector('[data-chart="sentMain"]');
  assert.notEqual(c.dataset.live, 'ok');
  assert.equal(c.querySelectorAll('rect.gBar').length, 0);
  assert.equal(body().querySelectorAll('#sigWrap tr[data-sig]').length, 0);
});

await t('행은 있는데 반응이 전부 0건이면 "0건" 이라고 적는다 (계산 안 됨과 구별)', async () => {
  const z = [{ date: '2026-09-08', mention: 0, temp: 37, pos_n: 0, neu_n: 0, neg_n: 0, pos_rate: null, neg_rate: null,
    question_n: 0, purchase_n: 0, experience_n: 0, praise_n: 0, critique_n: 0, chitchat_n: 0, intent: null }];
  await render('블록코어', z, null);
  assert.match(body().textContent, /분류된 반응이 아직 0건/);
  assert.doesNotMatch(body().textContent, /계산되지 않았습니다/);
});

await t('비율·지수는 비었어도 건수가 있으면 탭을 그린다', async () => {
  const one = [{ date: '2026-09-08', mention: 3, temp: 40, pos_n: 5, neu_n: 3, neg_n: 2, pos_rate: null, neg_rate: null,
    question_n: 1, purchase_n: 2, experience_n: 0, praise_n: 4, critique_n: 1, chitchat_n: 2, intent: null }];
  await render('가방', one, null);
  assert.equal(body().querySelectorAll('#sigWrap tr[data-sig]').length, 6);
  assert.match(body().querySelector('[data-chart="sentMain"]').textContent, /하루뿐/);
});

/* ── 판정 카드 ── 실제 사고: '가을' 긍정 3·중립 3·부정 0 (6건)이 긍정 비율 50% 라 '팽팽한 신호'로 떴다 */
const day1 = (o) => [{ date: '2026-09-08', mention: 1, temp: 40, pos_rate: null, neg_rate: null, intent: null,
  question_n: 0, purchase_n: 0, experience_n: 0, praise_n: 1, critique_n: 0, chitchat_n: 0, ...o }];
const verdict = () => body().querySelector('.verdict h4').textContent;

await t('★ 반응이 적으면(6건) 판정하지 않는다 — 팽팽이라 하지 않는다', async () => {
  await render('가을', day1({ pos_n: 3, neu_n: 3, neg_n: 0, pos_rate: 50, neg_rate: 0 }), null);
  assert.match(verdict(), /판단 보류/);
  assert.doesNotMatch(body().querySelector('.verdict').textContent, /팽팽한 신호|맞섭니다/);
  assert.equal(body().querySelectorAll('.vdBand .on').length, 0);
  assert.match(body().querySelector('.verdict').textContent, /긍정 3 · 중립 3 · 부정 0건/);
});

await t('★ 중립이 많아도 부정이 0 이면 구매 쪽이다 (긍정 우위로 판정)', async () => {
  await render('가을2', day1({ pos_n: 30, neu_n: 30, neg_n: 0, pos_rate: 50, neg_rate: 0 }), null);
  assert.match(verdict(), /강한 구매 신호/);
  assert.match(body().querySelector('.dial').textContent, /긍정 우위/);
});

await t('긍정·부정이 비슷하면 그때 팽팽이다', async () => {
  await render('가을3', day1({ pos_n: 20, neu_n: 10, neg_n: 20 }), null);
  assert.match(verdict(), /팽팽한 신호/);
});

await t('구매의향 지수가 있으면 그 값이 먼저다 (건수가 적어도)', async () => {
  await render('가을4', day1({ pos_n: 3, neu_n: 3, neg_n: 0, intent: 30 }), null);
  assert.match(verdict(), /구매 저해 신호 우세/);
  assert.match(body().querySelector('.dial').textContent, /구매의향 지수/);
});

await t('다른 선 차트(온도)는 그대로 선이다', async () => {
  const { gChart } = await import(`${W}/trend/static/js/chart_engine.js`);
  const el = document.createElement('div'); document.body.appendChild(el);
  gChart(el, { key: 'k', term: '발레코어', min: 0, max: 100, sets: [{ id: 'm', field: 'mention' }, { id: 't', field: 'temp', accent: 1 }] });
  assert.equal(el.querySelectorAll('path.ln,path.ln2').length, 2);
  assert.equal(el.querySelectorAll('rect.gBar').length, 0);
});

console.log(`\n${pass}개 통과 · ${fail}개 실패`);
process.exit(fail ? 1 : 0);
