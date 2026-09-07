import { JSDOM } from 'jsdom';
import fs from 'node:fs';

/* 팝업 마크업을 index.html 에서 쓰는 그대로 세운다 */
const POPUP = `
<div class="modalOverlay cpOverlay" id="cpOverlay"><div class="modalShell cpShell">
 <div class="cpBox" id="cpBox">
  <aside class="cpSide">
   <div class="cpProfile"><div class="cpAv" id="cpAv"></div>
    <div class="cpProfileText"><b id="cpName"></b><p id="cpDesc"></p></div></div>
   <button type="button" class="cpNewBtn" id="cpNewBtn"><i>+</i>새로운 대화</button>
   <div class="cpListLabel">대화 목록</div><div class="cpList" id="cpList"></div>
  </aside>
  <div class="cpMain">
   <div class="cpThreadWrap" id="cpThreadWrap">
    <div class="cpEmpty"><p id="cpEmptyText"></p></div>
    <div class="thread cpThread" id="cpThread"></div></div>
   <div class="cpInputRow"><textarea id="cpInput" rows="1"></textarea>
    <button class="cpSend" id="cpSend">→</button></div>
  </div></div>
 <button class="modalClose" id="cpClose">×</button></div></div>
<section class="view on" id="v-home"><div id="hotList"></div><div id="mChips"></div>
 <h1 id="mState"><span class="ln">a</span></h1><div class="heroL"><p>x</p></div>
 <div class="heroR"></div><div class="chatbar"><button id="smToggle"><span class="lbl">
 <i class="ic">◑</i><span class="tx">살!말?</span></span></button>
 <div class="ghostQ" id="ghostQ"><span class="spark">✧</span><span class="qline" id="qline"></span></div>
 <input id="mInput"></div><div class="thread" id="thread"></div></section>`;

const dom = new JSDOM('<!doctype html><body>'+POPUP+'</body>',
  {url:'http://localhost:5173/', pretendToBeVisual:true});
for (const k of ['location','requestAnimationFrame','cancelAnimationFrame','HTMLElement',
                 'Node','Event','CustomEvent','MouseEvent','getComputedStyle',
                 'TextDecoder','AbortController']) {
  try { global[k] = dom.window[k] ?? global[k]; } catch(e) { /* getter-only 는 건너뛴다 */ }
}
global.window = dom.window; global.document = dom.window.document;
/* setTimeout 은 노드 것을 그대로 쓴다 — jsdom 것으로 덮으면 재귀에 빠진다 */

const FX = JSON.parse(fs.readFileSync('_chat_fixtures.json','utf8'));

/* 서버 흉내 — 진짜 SSE 바이트를 흘린다 */
function sseBody(rep){
  const enc = new TextEncoder();
  const parts = [];
  const push=(ev,d)=>parts.push(enc.encode(`event: ${ev}\ndata: ${JSON.stringify(d)}\n\n`));
  push('status',{stage:'lexicon'});
  if(rep.ok===false){ push('error',rep); push('done',{ok:false}); }
  else{
    for(const seg of (rep.headline||'').match(/(<[^>]+>|.{1,3})/g)||[]) push('text',{delta:seg});
    push('report',rep);
    push('actions',[{label:'Style 탭에서 자세히',type:'view',view:'style',style:(rep.terms[0]||{}).canonical},
                    {label:'지표로 보기',type:'view',view:'trend'}]);
    push('done',{ok:true});
  }
  let i=0;
  return {getReader:()=>({read:async()=>i<parts.length?{done:false,value:parts[i++]}:{done:true}})};
}
let SERVE = FX.level, HEALTH = true, LEXREQ = null;
global.fetch = async (url, opt) => {
  const u = String(url);
  if(!HEALTH) throw new Error('서버 없음');   /* 죽으면 전부 실패한다 */
  if(u.endsWith('/v1/health'))
    return HEALTH ? {ok:true, json:async()=>({ok:true})} : Promise.reject(new Error('down'));
  if(u.endsWith('/v1/lexicon/requests')){
    LEXREQ = JSON.parse(opt.body);
    return {ok:true, json:async()=>({ok:true, surface:LEXREQ.surface, count:1})};
  }
  if(u.endsWith('/v1/chat')) return {ok:true, body:sseBody(SERVE)};
  throw new Error('unexpected '+u);
};

const cp = await import('./app/home/static/js/chat_popup.js');
const chat = await import('./app/home/static/js/chat.js');
const wait = ms => new Promise(r=>setTimeout(r,ms));

let fail=0;
const ok=(c,m)=>{ console.log((c?'  OK  ':'  X!! ')+m); if(!c) fail++; };
const thread = () => document.getElementById('cpThread');

console.log('=== 1. 서버가 살아 있을 때 — 실데이터 리포트가 뜨나 ===');
cp.openChatWith('발레코어 어때?');
await wait(2600);
let th = thread();
ok(th.querySelectorAll('.msg.me').length===1, '내 말풍선 1개');
ok(th.querySelectorAll('.msg.ai').length===1, 'AI 말풍선 1개');
ok(!!th.querySelector('.ansCard'), '.ansCard 렌더');
ok(th.querySelector('.say').textContent.includes('발레코어'), '한 줄 결론에 키워드');
ok(th.querySelectorAll('.rank .row').length>=2, `.rank 행 ${th.querySelectorAll('.rank .row').length}개`);
ok(th.querySelectorAll('.bars .b').length>0, `.bars 막대 ${th.querySelectorAll('.bars .b').length}개 (PRO)`);
ok(th.querySelectorAll('.act .pill').length===2, `행동 버튼 ${th.querySelectorAll('.act .pill').length}개`);
const sBtn = th.querySelector('[data-style]');
ok(sBtn && sBtn.dataset.style==='ballet',
   `스타일 버튼이 id 로 바뀜 (data-style="${sBtn&&sBtn.dataset.style}") — 이름 그대로면 라우터가 엉뚱한 데로 간다`);
ok(!th.querySelector('[data-style-name]:not([data-style])'), '해석 못 한 스타일 버튼은 남지 않는다');

console.log('\n=== 2. 사전에 없는 말 ===');
SERVE = FX.refusal;
cp.cpNewConvo(); cp.openChatWith('우리 랩실에서 회의했어요');
await wait(2200);
th = thread();
ok(!!th.querySelector('.kwReq'), '.kwReq 렌더');
ok(th.querySelectorAll('.kwReq .near button').length>0, `후보 ${th.querySelectorAll('.kwReq .near button').length}개`);
const rq = th.querySelector('[data-lexreq]');
ok(!!rq, '등록 요청 버튼');
rq.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
await wait(120);
ok(rq.disabled===true, '누른 즉시 잠긴다');
await wait(400);
ok(LEXREQ && LEXREQ.surface==='회의했어요',
   `서버로 실제 전송됨 surface="${LEXREQ&&LEXREQ.surface}"`);
ok(rq.textContent.includes('완료'), `끝나면 결과를 말한다 ("${rq.textContent}")`);

console.log('\n=== 3. 후보 칩을 누르면 그 말로 다시 묻는다 ===');
SERVE = FX.direction;
const before = thread().querySelectorAll('.msg.me').length;
thread().querySelector('.kwReq .near button').dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
await wait(2200);
ok(thread().querySelectorAll('.msg.me').length===before+1, '질문이 하나 더 쌓임');

console.log('\n=== 4. 서버가 도중에 죽었을 때 — 목업으로 떨어지나 ===');
/* isUp() 은 30초 캐시라 아직 "살아 있다"고 믿는다.
   그 상태에서 askStream 이 던져야 폴백이 도는지를 본다 — 실제로 일어나는 순서다. */
HEALTH = false;
cp.cpNewConvo(); cp.openChatWith('고프코어 꺾였어?','gorp');
await wait(2600);
th = thread();
ok(!!th.querySelector('.ansCard'), '그래도 카드가 뜬다 (목업)');
ok(th.querySelector('.say').textContent.includes('고프코어'), '목업 문구가 나온다');
ok(!th.querySelector('.kwReq'), '거절 화면이 아니다');
ok(th.querySelectorAll('.bars .b').length>0, '목업 카드의 막대도 채워진다');

console.log('\n=== 5. FREE 플랜 — 서버가 자른 대로 그린다 ===');
HEALTH = true; SERVE = FX.level_free;
cp.cpNewConvo(); cp.openChatWith('발레코어 어때?');
await wait(2600);
th = thread();
ok(!th.querySelector('.bars'), '플랫폼 막대 없음');
ok(!!th.querySelector('.kwReq .ask button[data-v="price"]'), '업셀 버튼이 요금제로 간다');

console.log(fail? `\n실패 ${fail}건` : '\n전부 통과');
process.exit(fail?1:0);
