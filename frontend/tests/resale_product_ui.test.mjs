/* 리세일: 표준상품 검색 → product_id 분석, 연결된 플랫폼 카드만 표시. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { JSDOM } from 'jsdom';

const root=new URL('..',import.meta.url).href.replace(/\/$/,'');
const dom=new JSDOM(fs.readFileSync(new URL('../index.html',import.meta.url),'utf8'),{url:'http://localhost:5173/'});
for(const key of ['window','document','Element','SVGElement','getComputedStyle','Node','HTMLElement',
  'KeyboardEvent','MouseEvent','CustomEvent','MutationObserver'])
  globalThis[key]=key==='window'?dom.window:dom.window[key];
globalThis.requestAnimationFrame=fn=>setTimeout(fn,0);
globalThis.cancelAnimationFrame=id=>clearTimeout(id);
globalThis.addEventListener=dom.window.addEventListener.bind(dom.window);
globalThis.localStorage=dom.window.localStorage;
globalThis.location=dom.window.location;
globalThis.innerWidth=1440; globalThis.innerHeight=900;
globalThis.matchMedia=()=>({matches:false,addEventListener(){},addListener(){}});
globalThis.scrollTo=()=>{};
globalThis.IntersectionObserver=class{observe(){} unobserve(){} disconnect(){}};
globalThis.ResizeObserver=class{observe(){} unobserve(){} disconnect(){}};
globalThis.anime={animate(){return {pause(){},cancel(){},play(){}}},
  createTimeline(){return {add(){return this},call(){return this}}},stagger(){return ()=>0},
  spring(){return 'linear'},utils:{set(){},remove(){}},createDrawable(){return []},splitText(){return {}}};

const reply=value=>({ok:true,status:200,text:async()=>JSON.stringify(value),json:async()=>value});
const asked=[];
globalThis.fetch=async url=>{
  url=String(url); asked.push(url);
  if(url.includes('/api/resale/products'))return reply({status:'ok',data:{items:[{
    id:42,type:'product',name:'나이키 에어포스 1 07 화이트',brand:'나이키',code:'CW2288-111',
    image:'https://img.example/42.jpg',source_count:9,
    platforms:[{name:'무신사',count:1},{name:'무신사 USED',count:8}],
  }]}});
  if(url.includes('/api/resale?product_id=42'))return reply({status:'ok',data:{
    label:'나이키 에어포스 1 07 화이트',analysis_scope:'product',
    product:{id:42,name:'나이키 에어포스 1 07 화이트',brand:'나이키',code:'CW2288-111',
      image:'https://img.example/42.jpg',mapped:true},
    as_of:'2026-09-29T12:00:00+09:00',days:90,observed_days:8,listings:8,
    confidence:{code:'medium',label:'보통'},mapping:{platform_count:2,platforms:['무신사','무신사 USED'],source_count:9},
    keep_pct:61,keep_change_pp:-3,regular_price:135000,used_price:50000,
    volume_4w:8,volume_change_pct:null,volume_basis:'observed_listings',sizes:[],grades:[],spread:null,
    series:[{date:'2026-09-22',keep_pct:64},{date:'2026-09-29',keep_pct:61}],temperature:{series:[]},
    platform_cards:[
      {name:'무신사',market:'retail',product_sources:1,list_price:135000,sale_price:99000,discount_rate:26.7,as_of:'2026-09-29'},
      {name:'무신사 USED',market:'resale',product_sources:8,listing_count:8,median_price:50000,min_price:42000,max_price:68000,as_of:'2026-09-29'},
    ],
  }});
  return reply({status:'empty',reason:'테스트 데이터 없음',data:null});
};

await import(`${root}/main.js`);
const search=await import(`${root}/style/static/js/search.js`);
const dispatch=await import(`${root}/trend/static/js/dispatch.js`);
dispatch.trRender('resale');
const input=document.getElementById('fsInput');
input.value='에어포스';
input.dispatchEvent(new dom.window.Event('input',{bubbles:true}));
await new Promise(resolve=>setTimeout(resolve,280));
const candidate=document.querySelector('#fsSug .resaleProduct');
assert.ok(candidate,'표준상품 후보를 보여 준다');
assert.match(candidate.textContent,/표준상품/);
assert.match(candidate.textContent,/무신사 USED 8건/);
candidate.click();
await new Promise(resolve=>setTimeout(resolve,80));

assert.equal(search.FS.resaleItem.id,42,'선택한 표준상품 ID를 보관한다');
assert.ok(asked.some(url=>url.includes('/api/resale?product_id=42')),'분석은 이름이 아니라 product_id로 요청한다');
assert.equal(document.querySelectorAll('.resalePlatformCard').length,2,'응답에 있는 플랫폼만 카드로 그린다');
assert.doesNotMatch(document.getElementById('trBody').textContent,/크림/,'없는 플랫폼 카드를 만들지 않는다');
assert.match(document.getElementById('trBody').textContent,/정가보다 39% 저렴/,'구매 목적의 언어로 번역한다');
assert.equal(document.querySelectorAll('.resaleEvidence .panelC').length,1,'자료 없는 상태·사이즈 카드는 숨긴다');

document.querySelector('[data-resale-mode="sell"]').click();
assert.match(document.getElementById('trBody').textContent,/정가의 61%를 회수/,'판매 목적 문구로 즉시 바꾼다');

document.getElementById('fsMore').click();
assert.match(document.querySelector('.fsPopHead h3').textContent,/시장 전체 분석/);
assert.match(document.getElementById('fsPopLead').textContent,/개별 상품은 위 검색창/);
assert.match(document.getElementById('fsApply').textContent,/이 시장 분석/);
const facetUrl=asked.filter(url=>url.includes('/api/facets?')).at(-1);
assert.ok(facetUrl&&!facetUrl.includes('item='),'시장 분석 후보를 개별 상품명으로 잠그지 않는다');

console.log('✅ 표준상품 리세일 검색·부분 매핑 카드·구매/판매 모드·시장 분석 모달 통과');
process.exit(0);
