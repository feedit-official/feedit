/* 트렌드 화면이 실제로 실데이터를 보는지 — 호출부까지 이어졌는지 본다.
 *
 * ★ 왜 필요한가
 *   chart_engine 에 실데이터 경로를 냈지만, dispatch.js 가 `term` 을 안 넘기면
 *   그 경로가 한 번도 안 탄다. 배선을 해 놓고 연결을 빼먹은 것을 잡는 시험이다.
 *   실제로 처음엔 그 상태였다 — 화면이 계속 씨드 난수였다.
 *
 * 돌리는 법:  node tests/trend_wiring.test.mjs      (jsdom 필요)
 */
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';
import fs from 'node:fs';

const W = new URL('..', import.meta.url).href.replace(/\/$/, '');  // 이 파일 기준 프론트 뿌리
const dom = new JSDOM('<!doctype html><div id="c"></div>', { url: 'http://localhost:5173/' });
for (const k of ['window','document','Element','SVGElement','getComputedStyle','Node'])
  globalThis[k] = k === 'window' ? dom.window : dom.window[k];

let reply = null, calls = [];
globalThis.fetch = async (u) => { calls.push(u);
  return { ok: true, status: 200,
    text: async () => JSON.stringify(reply), json: async () => reply }; };

const live = await import(`${W}/trend/static/js/live_data.js`);
const { gChart } = await import(`${W}/trend/static/js/chart_engine.js`);

let pass = 0, fail = 0;
const t = async (n, f) => { try { await f(); console.log('✅', n); pass++; }
  catch (e) { console.log('❌', n, '\n   ', e.message); fail++; } };
const host = () => { document.body.innerHTML = '<div id="c"></div>'; return document.getElementById('c'); };
const days = (n) => { const o=[]; for(let i=n-1;i>=0;i--){ const d=new Date(); d.setDate(d.getDate()-i);
  o.push({date:d.toISOString().slice(0,10),mention:10+(i%7),temp:50+(i%20),document:3,sentiment:0.2}); } return o; };

// ── dispatch.js 가 term·field 를 넘기는지 (소스 대조) ──
const src = fs.readFileSync(new URL('../trend/static/js/dispatch.js', import.meta.url), 'utf8');
await t('★ 온도 차트가 term 을 넘긴다', () => {
  assert.match(src, /G_CFG\.tempMain=\{key:kw\+'temp',term:kw/);
  assert.match(src, /field:'mention'/);
  assert.match(src, /field:'temp'/);
});
await t('★ 연관어·긍부정도 term 을 넘긴다', () => {
  assert.match(src, /G_CFG\.assocMain=\{key:kw\+'assoc',term:kw/);
  assert.match(src, /G_CFG\.sentMain=\{key:kw\+'sent',term:kw/);
});
await t('그리기 전에 prime 을 부른다', () => {
  assert.match(src, /prime\(kw\)\.then/);
  assert.match(src, /stateOf\(kw\)\.status==='unknown'/);
});
await t('★ 늦게 온 응답이 딴 탭을 덮지 않는다', () => {
  assert.match(src, /if\(TR_CUR===id\) trRender\(id\)/);
});

// ── 실제로 그려 본다 ──
await t('값이 있으면 두 계열 다 실값으로 그린다', async () => {
  reply = { status:'ok', data:{ term:'발레코어', facet:'STYLE', series: days(90) } };
  await live.prime('발레코어');
  const el = host();
  gChart(el, { key:'k', term:'발레코어', min:0, max:100,
    sets:[{id:'m',field:'mention'},{id:'t',field:'temp'}] });
  assert.equal(el.dataset.live, 'ok');
  assert.ok(el.querySelector('svg'));
});

await t('★ 한 계열만 없어도 반쪽짜리로 안 그린다', async () => {
  const s = days(90).map(p => ({ ...p, temp: null }));   // 온도가 아직 안 들어옴
  reply = { status:'ok', data:{ term:'새틴', facet:'MATERIAL', series: s },
            unavailable:{ fields:['temp'], reason:'temp 가 아직 비어 있습니다.' } };
  await live.prime('새틴');
  const el = host();
  gChart(el, { key:'k', term:'새틴', sets:[{id:'m',field:'mention'},{id:'t',field:'temp'}] });
  assert.equal(el.dataset.live, 'partial');
  assert.ok(/측정 불가/.test(el.textContent));
  assert.ok(/temp 가 아직 비어/.test(el.textContent));
});

await t('지표가 0행이면 그 사실을 화면에 적는다', async () => {
  reply = { status:'empty', reason:'적재가 아직 안 돌았습니다.' };
  await live.prime('키르시');
  const el = host();
  gChart(el, { key:'k', term:'키르시', sets:[{id:'m',field:'mention'}] });
  assert.equal(el.dataset.live, 'unavailable');
  assert.ok(/적재가 아직/.test(el.textContent));
});

await t('같은 용어를 여러 번 열어도 요청은 한 번', async () => {
  calls = [];
  await live.prime('발레코어'); await live.prime('발레코어');
  assert.equal(calls.length, 0, '캐시에 있으면 다시 안 부른다');
});

console.log(`\n${pass}개 통과 · ${fail}개 실패`);
process.exit(fail ? 1 : 0);
