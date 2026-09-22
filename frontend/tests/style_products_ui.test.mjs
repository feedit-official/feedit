/* 진짜 앱 진입점을 로드한 뒤 스타일 상세에 API 상품이 그려지는지 본다. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { JSDOM } from 'jsdom';

const F=new URL('..',import.meta.url).href.replace(/\/$/,'');
const html=fs.readFileSync(new URL('../index.html',import.meta.url),'utf8');
const dom=new JSDOM(html,{url:'http://localhost:5173/'});
for(const k of ['window','document','Element','SVGElement','getComputedStyle','Node','HTMLElement','CustomEvent'])
  globalThis[k]=k==='window'?dom.window:dom.window[k];
/* notify.js 가 본문 진입을 기다릴 때 쓴다 — 전역에 없으면 import 단계에서 통째로 죽는다 */
globalThis.MutationObserver=dom.window.MutationObserver||class{observe(){} disconnect(){} takeRecords(){return []}};
globalThis.requestAnimationFrame=f=>setTimeout(f,0);
globalThis.cancelAnimationFrame=h=>clearTimeout(h);
globalThis.addEventListener=dom.window.addEventListener.bind(dom.window);
globalThis.removeEventListener=dom.window.removeEventListener.bind(dom.window);
globalThis.matchMedia=()=>({matches:false,addEventListener(){},addListener(){}});
globalThis.scrollTo=()=>{};
globalThis.IntersectionObserver=class{observe(){}unobserve(){}disconnect(){}};
globalThis.ResizeObserver=class{observe(){}unobserve(){}disconnect(){}};
globalThis.location=dom.window.location;
globalThis.localStorage=dom.window.localStorage;

const productReply={status:'ok',data:{
  count:1,offset:0,next_offset:1,has_more:false,style:['고프코어'],
  items:[{
    id:5,product_source_id:51,name:'실데이터 셋 자켓',brand:'FEEDIT TEST',
    image:'https://img.example/51.jpg',url:'https://shop.example/51',
    source:'musinsa',price:{list:219000,sale:159000,as_of:'2026-09-16'}
  }]
}};

globalThis.fetch=async url=>{
  const body=String(url).startsWith('/api/products')?productReply:{status:'empty',reason:'테스트'};
  return {ok:true,status:200,text:async()=>JSON.stringify(body),json:async()=>body};
};

await import(`${F}/main.js`);
const {stOpen}=await import(`${F}/style/static/js/style_page.js`);
stOpen('gorp');
await new Promise(r=>setTimeout(r,40));

const cards=document.querySelectorAll('#stItems .itemCard');
assert.equal(cards.length,1);
assert.match(cards[0].textContent,/실데이터 셋 자켓/);
assert.match(cards[0].textContent,/159,000원/);
assert.equal(cards[0].dataset.productUrl,'https://shop.example/51');
assert.equal(document.getElementById('stItemCount').textContent,'1 ITEMS');
assert.match(document.getElementById('stMore').textContent,/모든 상품/);
assert.equal(document.getElementById('stMore').disabled,true);
/* 기본 정렬은 FEEDiT 추천순이고, 추천순 최상단 상품에는 'FEEDiT Pick!' 라벨이 붙는다 */
assert.equal(document.getElementById('stSort').dataset.sort,'recommend');
assert.equal(document.getElementById('stSortLabel').textContent,'FEEDiT 추천순');
assert.ok(document.getElementById('stSortInfoBtn'),'추천순 기준 설명 버튼이 있다');
assert.match(cards[0].querySelector('.pickTag').textContent,/FEEDiT Pick!/);

console.log('✅ 스타일 상세에 API 실상품 카드가 그려진다');
process.exit(0);
