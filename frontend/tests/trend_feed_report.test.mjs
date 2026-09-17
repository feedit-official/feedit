/* 내 피드 · 금주의 리포트 — 실데이터 연결 확인.
 *
 * ★ 무엇을 보나
 *   · 내 피드 화제성 = /api/trend 트렌드 온도, 단계 = /api/lifecycle, 7일 언급량 = mention 합
 *   · 받기 전에는 숫자를 지어내지 않는다('–'), 지표가 없으면 사유를 적는다
 *   · 리포트 기간은 오늘 날짜로 계산, 찜·투표는 ME(saved_count·vote_count)
 *   · '같이 지켜볼 스타일'은 태동·확산 먼저, 그다음 온도 순
 *
 * 돌리는 법:  node tests/trend_feed_report.test.mjs      (jsdom 필요)
 */
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';
import fs from 'node:fs';

const W = new URL('..', import.meta.url).href.replace(/\/$/, '');
const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8')
  .replace(/<script[\s\S]*?<\/script>/g, '');
const dom = new JSDOM(html, { url: 'http://localhost:5173/', pretendToBeVisual: true });
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

/* 스타일별 가짜 RDS — 없는 스타일은 empty */
const LAST = '2026-09-10';
const series = (temp, m) => { const o = []; for (let i = 20; i >= 0; i--) {
  const d = new Date(LAST + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() - i);
  o.push({ date: d.toISOString().slice(0, 10), mention: i < 7 ? m : 2, temp: i >= 7 ? temp - 5 : temp, momentum: 60, level: 50 });
} return o; };
const DB = {
  '블록코어': { temp: 81, m: 10, stage: '확산' },
  '아메카지': { temp: 40, m: 3, stage: '쇠퇴' },
  '고프코어': { temp: 90, m: 5, stage: '정점' },
  '바이크코어': { temp: 55, m: 4, stage: '태동' },
  '클래식': { temp: 70, m: 4, stage: '확산' },
};
const ok = data => ({ ok: true, status: 200, text: async () => JSON.stringify({ status: 'ok', data }), json: async () => ({ status: 'ok', data }) });
const empty = { ok: true, status: 200, text: async () => JSON.stringify({ status: 'empty', reason: '측정된 자료가 없습니다.' }), json: async () => ({ status: 'empty' }) };
globalThis.fetch = async (url) => {
  const u = new URL(String(url), 'http://x');
  const term = u.searchParams.get('term') || '';
  const row = DB[term];
  if (u.pathname === '/api/trend' && term) return row ? ok({ term, facet: 'STYLE', series: series(row.temp, row.m) }) : empty;
  if (u.pathname === '/api/lifecycle') return row ? ok({ term, stage: row.stage, temp: row.temp }) : empty;
  return empty;
};

let pass = 0, fail = 0;
const t = async (n, f) => { try { await f(); console.log('✅', n); pass++; }
  catch (e) { console.log('❌', n, '\n   ', e.stack.split('\n').slice(0, 3).join('\n    ')); fail++; } };
const wait = () => new Promise(r => setTimeout(r, 30));

await import(`${W}/main.js`);
const { ME } = await import(`${W}/account/static/js/profile.js`);
const D = await import(`${W}/trend/static/js/dispatch.js`);
const body = () => document.getElementById('trBody');
ME.styles.clear(); ['block', 'ameka', 'street'].forEach(x => ME.styles.add(x));
ME.saved = 7; ME.votes = 3;

await t('내 피드 — 받기 전에는 숫자를 지어내지 않는다', () => {
  D.trRender('myfeed');
  assert.equal(body().querySelector('.tpBigDeg').textContent, '–');
  assert.match(body().querySelector('#tpHero').textContent, /불러오는 중/);
});

await t('내 피드 화제성 = 트렌드 온도 · 7일 전 대비 · 수명주기 단계', async () => {
  await wait();
  const h = body().querySelector('#tpHero').textContent;
  assert.match(body().querySelector('.tpBigDeg').textContent, /^81°$/);
  assert.match(h, /▲ 5° 지난주 대비/);
  assert.match(h, /확산/);
  assert.match(h, /최근 7일 언급 70건\(지난주 14건\)/);
});

await t('7일 언급량 카드 — 지표가 없는 스타일(스트릿웨어)은 – 로 남는다', () => {
  const g = body().querySelector('#tpSignal').textContent;
  assert.match(body().querySelector('.tpSignalNum').textContent, /^91/);   // 70 + 21
  assert.match(g, /블록코어 70건 \+56/);
  assert.match(g, /스트릿웨어 –/);
});

await t('브리핑 — 올라가는 구간(태동·확산) 수를 센다', () => {
  const b = body().querySelector('#tpBrief').textContent;
  assert.match(b, /블록코어는 온도 81°로 확산 구간/);
  assert.match(b, /스트릿웨어는 지표 없음/);
  assert.match(body().querySelector('.tpBriefScore').textContent, /^1/);
});

await t('리포트 — 기간 · 내 관심 스타일 · 찜/투표 실값', async () => {
  D.trRender('report');
  const r = body().querySelector('#wkReport').textContent;
  assert.match(r, /\d{4}\.\d{2} · W\d · \d+\/\d+ – \d+\/\d+/);
  assert.match(r, /내 관심 스타일 블록코어의 흐름/);
  const m = [...body().querySelectorAll('.wkMetric')].map(e => e.textContent);
  assert.match(m[1], /찜한 것7개누적/);
  assert.match(m[2], /살!말\? 투표3표누적/);
  await wait();
  const l = body().querySelector('#wkHeroLedger').textContent;
  assert.match(l, /트렌드 온도81°/);
  assert.match(l, /지난주 대비\+5°/);
  assert.match(l, /수명주기 단계확산/);
});

await t('같이 지켜볼 스타일 — 태동·확산 먼저, 그다음 온도 순 (지표 없는 스타일 제외)', () => {
  const names = [...body().querySelectorAll('#wkNextGrid .wkNextCard b')].map(b => b.textContent);
  assert.deepEqual(names, ['클래식', '바이크코어', '고프코어']);
  assert.match(body().querySelector('#wkNextGrid').textContent, /확산 · 70°/);
});

console.log(`\n${pass}개 통과 · ${fail}개 실패`);
process.exit(fail ? 1 : 0);
