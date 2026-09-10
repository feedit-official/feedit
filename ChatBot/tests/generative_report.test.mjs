/* 생성형 UI 스펙이 고정 variant 없이 안전한 HTML 캔버스로 조립되는지 확인한다. */
import { JSDOM } from 'jsdom';
import fs from 'node:fs';

const dom=new JSDOM('<!doctype html><body></body>',{url:'http://localhost:5173/'});
global.window=dom.window; global.document=dom.window.document; global.location=dom.window.location;
const api=await import('./chat_api.js');
const cssText=fs.readdirSync('css').map(f=>fs.readFileSync('css/'+f,'utf8')).join('\n');

let fail=0;
const ok=(cond,msg)=>{ console.log((cond?'  OK  ':'  X!! ')+msg); if(!cond)fail++; };
const block={type:'rank',slot:'full',title:'고프코어',rows:[{k:'트렌드 온도',v:'82점',up:true}]};
const report={
  ok:true,intent:'agent',as_of:{metric:'2026-09-10'},
  blocks:[{type:'generative_report',slot:'full',title:'고프코어 흐름',accent:'violet',
    surface:'soft',density:'airy',fingerprint:'abc123',modules:[
      {id:'metric:고프코어',kind:'metric',presentation:'hero',span:8,emphasis:'strong',block},
      {id:'evidence:고프코어',kind:'evidence',presentation:'editorial',span:4,
       emphasis:'quiet',block:{type:'note',text:'실제 결과만 사용합니다.'}},
    ]}],
};

console.log('=== 생성형 캔버스 ===');
const box=document.createElement('div'); box.innerHTML=api.reportHTML(report);
ok(!!box.querySelector('.skillReport--violet.skillReport--soft.skillReport--airy'), '디자인 토큰을 조합한다');
ok(box.querySelectorAll('.skillModule').length===2, '모델이 고른 모듈 수만큼 그린다');
ok(box.querySelector('.skillModule--hero').getAttribute('style').includes('span 8'), '12열 폭을 반영한다');
ok(!!box.querySelector('.skillModule--block-rank'), '블록 종류를 모듈 스타일 훅으로 남긴다');
ok(box.textContent.includes('82점'), '기존 데이터 블록을 재사용한다');
ok(!box.innerHTML.includes('variant'), '이름 붙은 레이아웃 variant 가 없다');
ok(box.textContent.includes('LIVE REPORT') && box.textContent.includes('SIGNALS'), '편집형 메타 헤더를 표시한다');

console.log('\n=== 근거 인용 카드 ===');
const evidence=structuredClone(report);
evidence.blocks[0].modules=[{id:'evidence:고프코어',kind:'evidence',presentation:'editorial',
  span:5,emphasis:'quiet',block:{type:'quotes',title:'근거가 된 대목',meta:'1건',
  items:[{body:'테크웨어 고프코어',src:'네이버',kind:'카페 글',tone:'긍정'}]}}];
const evidenceBox=document.createElement('div'); evidenceBox.innerHTML=api.reportHTML(evidence);
ok(!!evidenceBox.querySelector('blockquote.evidenceQuote'), '근거를 전용 인용 요소로 그린다');
ok(evidenceBox.querySelector('.evidenceMeta').textContent.includes('네이버 · 카페 글'), '출처 메타를 본문과 분리한다');
ok(!evidenceBox.querySelector('.skillModule--evidence .note'), '공용 안내문 스타일을 중첩하지 않는다');

console.log('\n=== 카드 개수 기반 KPI 배치 ===');
const sentiment=structuredClone(report);
sentiment.blocks[0].modules=[{id:'sentiment:고프코어',kind:'sentiment',presentation:'card',
  span:4,emphasis:'normal',columns:3,block:{type:'kpis',items:[
    {k:'구매의향 지수',v:'50',unit:'점',note:'표본 1건'},
    {k:'긍정 신호',v:'100.0',unit:'%',note:'구매고민'},
    {k:'부정 신호',v:'0.0',unit:'%',note:''},
  ]}}];
const sentimentBox=document.createElement('div'); sentimentBox.innerHTML=api.reportHTML(sentiment);
const sentimentModule=sentimentBox.querySelector('.skillModule--sentiment');
ok(sentimentModule.dataset.items==='3', '세 지표의 실제 카드 수를 렌더러에 전달한다');
ok(sentimentModule.getAttribute('style').includes('--skill-kpi-cols:3'), '세 지표를 한 줄 3칸으로 배치한다');
ok(/data-items="3"/.test(cssText) && /grid-template-columns:1fr/.test(cssText), '좁은 화면에서는 한 열로 안전하게 접는다');
ok(/skillModule--block-rank\.skillModule--editorial/.test(cssText), '이전 rank 스펙도 통일된 데이터 카드로 보정한다');

console.log('\n=== 안전한 토큰 폴백 ===');
const unsafe=structuredClone(report);
unsafe.blocks[0].accent='"><script>bad()</script>';
unsafe.blocks[0].modules[0].span='12;position:fixed';
const safe=document.createElement('div'); safe.innerHTML=api.reportHTML(unsafe);
ok(!!safe.querySelector('.skillReport--coral'), '허용하지 않은 색은 안전한 토큰으로 돌아간다');
ok(!safe.innerHTML.includes('<script>'), '문자열이 HTML 로 삽입되지 않는다');
ok(safe.querySelector('.skillModule').getAttribute('style')==='grid-column:span 12', '폭은 정수로 제한된다');
ok(/\.skillReport\b/.test(cssText) && /\.skillCanvas\b/.test(cssText), '새 캔버스 클래스가 CSS 에 있다');
ok(/container:skill-module/.test(cssText) && /@container skill-module/.test(cssText), 'KPI 열 수를 모듈 폭으로 결정한다');

console.log(fail?`\n실패 ${fail}건`:'\n전부 통과');
process.exit(fail?1:0);
