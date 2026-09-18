/* 할인률: DB 찜 → 드래그, 세부 검색 → 상품 ID/썸네일/가격 지표. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { JSDOM } from 'jsdom';

const root=new URL('..',import.meta.url).href.replace(/\/$/,'');
const html=fs.readFileSync(new URL('../index.html',import.meta.url),'utf8');
const dom=new JSDOM(html,{url:'http://localhost:5173/'});
for(const key of ['window','document','Element','SVGElement','getComputedStyle','Node','HTMLElement','KeyboardEvent','MouseEvent','CustomEvent'])
  globalThis[key]=key==='window'?dom.window:dom.window[key];
globalThis.requestAnimationFrame=fn=>setTimeout(fn,0);
globalThis.cancelAnimationFrame=id=>clearTimeout(id);
globalThis.addEventListener=dom.window.addEventListener.bind(dom.window);
globalThis.localStorage=dom.window.localStorage;
globalThis.innerWidth=1440;
globalThis.innerHeight=900;
globalThis.matchMedia=()=>({matches:false,addEventListener(){},addListener(){}});
globalThis.scrollTo=()=>{};
globalThis.IntersectionObserver=class{observe(){} unobserve(){} disconnect(){}};
globalThis.ResizeObserver=class{observe(){} unobserve(){} disconnect(){}};
globalThis.anime={
  animate(){return {pause(){},cancel(){},play(){}}},
  createTimeline(){return {add(){return this},call(){return this}}},
  stagger(){return ()=>0},spring(){return 'linear'},
  utils:{set(){},remove(){}},createDrawable(){return []},splitText(){return {}},
};

const saved={id:17,name:'데님 셔츠',brand:'브랜드A',source:'무신사',image:'https://img.example/17.jpg',
  list_price:100000,sale_price:75000,discount_rate:25};
let savedItems=[saved,...Array.from({length:5},(_,i)=>({
  ...saved,id:30+i,name:`찜 상품 ${i+2}`,image:`https://img.example/${30+i}.jpg`,
}))];
const longName='[고퀄/가을무드] 토이즈 스웨이드 자켓 가을아우터 블레이저 재킷 오버핏 출근룩';
const product=id=>({
  id,name:id===17?longName:'코튼 셔츠',brand:'브랜드A',source:'무신사',
  image:`https://img.example/${id}.jpg`,list_price:100000,sale_price:id===17?75000:60000,
  discount_rate:id===17?25:40,observed_at:'2026-09-18T10:00:00+09:00',
  history_min_price:id===17?75000:60000,observed_days:2,
});
const reply=value=>({ok:true,status:200,text:async()=>JSON.stringify(value),json:async()=>value});
const asked=[];
let failSave=false;
globalThis.fetch=async (url,options={})=>{
  url=String(url); asked.push(url);
  if(url.includes('/api/auth/me'))return reply({status:'ok',data:{csrf_token:'test',user:null}});
  if(url.includes('/api/auth/saved')){
    if(options.method==='POST'){
      if(failSave)return reply({status:'error',reason:'저장 실패 테스트'});
      const body=JSON.parse(options.body);
      const id=Number(body.item_id.replace('db-',''));
      savedItems=body.liked?[product(id),...savedItems]:savedItems.filter(item=>item.id!==id);
      return reply({status:'ok',data:{item_id:body.item_id,liked:body.liked,saved_count:savedItems.length}});
    }
    return reply({status:'ok',data:{items:savedItems,count:savedItems.length}});
  }
  if(url.includes('/api/discount/facets')){
    const params=new URL(url,'http://localhost').searchParams;
    if(params.get('q')==='원피스'){
      const offset=Number(params.get('item_offset')||0);
      const limit=Number(params.get('item_limit')||24);
      const all=Array.from({length:55},(_,i)=>({id:1000+i,label:`원피스 ${i+1}`,
        brand:'브랜드A',source:'무신사',thumb:`https://img.example/${1000+i}.jpg`}));
      const item=all.slice(offset,offset+limit);
      return reply(params.get('items_only')==='1'
        ? {status:'ok',items_only:true,item_has_more:offset+limit<all.length,item_offset:offset,data:{item}}
        : {status:'ok',narrowed:true,matched:55,item_has_more:offset+limit<all.length,
            item_offset:offset,data:{style:[],brand:[],kind:[],item}});
    }
    const item=[
      {id:17,label:'데님 셔츠',brand:'브랜드A',source:'무신사',thumb:'https://img.example/17.jpg'},
      {id:24,label:'코튼 셔츠',brand:'브랜드A',source:'무신사',thumb:'https://img.example/24.jpg'},
    ];
    return reply(url.includes('items_only=1')
      ? {status:'ok',items_only:true,data:{item}}
      : {status:'ok',narrowed:true,matched:2,data:{style:[],brand:[],kind:[],item}});
  }
  if(url.includes('/api/discount?source_id=')){
    const id=Number(new URL(url,'http://localhost').searchParams.get('source_id'));
    return reply({status:'ok',data:{product:product(id),as_of:'2026-09-18',days:90,
      first_discount_at:'2026-09-17',max_discount_period:40,change_2w:null,
      series:[{date:'2026-09-17',discount:20},{date:'2026-09-18',discount:id===17?25:40}],
      price_series:[
        {date:'2026-09-17',list_price:100000,sale_price:id===17?80000:65000},
        {date:'2026-09-18',list_price:100000,sale_price:id===17?75000:60000},
      ],
      matched_platforms:id===17?[
        {source_id:19,name:'에이블리',sale_price:73000,discount_rate:27,observed_at:'2026-09-18'},
        {source_id:17,name:'무신사',sale_price:75000,discount_rate:25,observed_at:'2026-09-18'},
      ]:[{source_id:24,name:'무신사',sale_price:60000,discount_rate:40,observed_at:'2026-09-18'}],
    }});
  }
  return reply({status:'empty',reason:'테스트 데이터 없음',data:null});
};

await import(`${root}/main.js`);
const search=await import(`${root}/style/static/js/search.js`);
const dispatch=await import(`${root}/trend/static/js/dispatch.js`);
const {paintStockPriceChart}=await import(`${root}/trend/static/js/stock_price_chart.js`);
dispatch.trRender('stock');
await new Promise(resolve=>setTimeout(resolve,50));
assert.equal(document.getElementById('dzImageFallback'),null,
  '빈 사진 영역에 별도의 이미지 없음 문구를 두지 않는다');
assert.equal(document.getElementById('dzPlaceholder').hidden,false,
  '선택 전에는 상품 선택 안내를 보여 준다');
assert.match(document.getElementById('stockPickerSummary').textContent,/상품을 고르면/,
  '상품 선택 전에는 요약 자리에 안내를 보여 준다');
assert.equal(document.querySelectorAll('#dzWishListBody .wlItem').length,6,'DB 찜목록을 상품 카드로 보여 준다');
assert.ok(asked.some(url=>url.includes('/api/auth/saved')),'찜목록을 DB에서 요청한다');
assert.equal(document.querySelectorAll('#dzWishListBody .wlPic img').length,6,'카드마다 실제 상품 이미지를 보여 준다');
assert.equal(document.querySelector('#dzWishListBody .wlPrice em').textContent,'25%');
const css=fs.readFileSync(new URL('../trend/static/css/my_feed.css',import.meta.url),'utf8');
assert.match(css,/\.stockPicker \.wlBody\{[^}]*grid-template-columns:repeat\(3,minmax\(0,1fr\)\)/s,
  '넓은 화면에서는 한 줄에 세 장을 배치한다');
assert.match(css,/\.stockPicker \.wlBody\{[^}]*overflow-y:auto/s,'기존 세로 스크롤을 유지한다');
assert.match(css,/\.stockPicker \.dropZone\{[^}]*aspect-ratio:1;max-height:296px/s,
  '큰 사진의 너비는 유지하되 높이를 조금 줄여 상품명과 찜 버튼을 올린다');
assert.match(css,/\.stockPicker \.dzWrap\{[^}]*gap:8px/s,
  '큰 사진과 아래 상품 정보 사이에 여백을 둔다');
assert.match(css,/\.stockPicker \.dzSelection b\{font-size:11px/s,
  '큰 사진 아래 상품명만 조금 작게 보여 준다');
assert.match(css,/\.stockPicker \.dzPlaceholder\{[^}]*align-items:center;justify-content:center;[^}]*text-align:center/s,
  '더하기 버튼과 안내 문구를 사진 영역 중앙에 정렬한다');
assert.match(css,/\.stockPicker \.dropZone img\{[^}]*object-fit:cover;object-position:center center/s,
  '큰 이미지는 중앙을 기준으로 위아래를 균형 있게 잘라 프레임을 채운다');
assert.match(css,/\.stockPicker \.wlPic img\{[^}]*object-fit:cover;object-position:center top/s,
  '찜목록 이미지는 위쪽을 보존하며 카드 사진을 채운다');
assert.match(css,/\.stockPicker \.dzWishlist\{height:320px/s,
  '큰 사진을 줄여도 찜목록 높이와 스크롤 영역은 유지한다');
assert.match(css,/\.fsPop\.is-discount \.fsOpt\.has-thumb \{[^}]*justify-content: flex-start/s,
  '세부검색 상품명은 썸네일 바로 옆에 배치한다');
assert.match(css,/\.stockPickerGrid\{[^}]*grid-template-columns:[^}]*minmax\(0,1fr\)/s,
  '할인율·큰 이미지·가격 요약·찜목록을 한 줄에 배치한다');
assert.match(css,/\.stockPickerRate \.dial,\.stockPickerDialEmpty\{width:min\(100%,165px\)/s,
  '선택 전후 원형 박스에 같은 크기를 적용한다');
assert.match(css,/\.stockPickerDial \.trk,\.stockPickerDial \.val\{stroke-width:8\}/s,
  '선택 후 원형의 선 두께를 선택 전 테두리 크기에 맞춘다');
assert.match(css,/\.stockPickerSummary\{[^}]*padding:0 0 0 78px/s,
  '원형 그래프는 그대로 두고 가격 설명만 오른쪽으로 20px 더 옮긴다');
assert.match(css,/\.stockPickerSummary h4\{[^}]*-webkit-line-clamp:2/s,
  '긴 상품명은 두 줄까지만 표시한다');
const wishlist=document.getElementById('dzWishListBody');
wishlist.scrollTop=73;
dispatch.trRender('stock');
assert.equal(wishlist.scrollTop,73,'지표 갱신 후에도 찜목록 스크롤 위치를 유지한다');

const transfer=new Map();
const dataTransfer={setData:(key,value)=>transfer.set(key,value),getData:key=>transfer.get(key)||'',effectAllowed:'',dropEffect:''};
const row=document.querySelector('#dzWishListBody .wlItem');
const drag=new dom.window.Event('dragstart',{bubbles:true});
Object.defineProperty(drag,'dataTransfer',{value:dataTransfer});
row.dispatchEvent(drag);
const drop=new dom.window.Event('drop',{bubbles:true,cancelable:true});
Object.defineProperty(drop,'dataTransfer',{value:dataTransfer});
document.getElementById('dzDropZone').dispatchEvent(drop);
await new Promise(resolve=>setTimeout(resolve,50));
assert.equal(search.FS.stockItem.id,17);
assert.ok(document.querySelector('#dzWishListBody .wlItem[data-source-id="17"]').classList.contains('on'));
assert.ok(document.querySelector('#stockDiscountSlot .dial'),'할인율 원형을 큰 이미지 옆에 보여 준다');
assert.equal(document.querySelector('#stockDiscountSlot .dial .trk').getAttribute('r'),'56',
  '선택 후 원형도 선택 전처럼 박스 가장자리까지 채운다');
assert.equal(document.querySelector('#dzDashboard .ph em'),null,'불필요한 일반 판매 상품 문구를 제거한다');
assert.equal(document.querySelector('#stockAnalyticsBody .dial'),null,'아래 가격 요약에 원형을 중복 배치하지 않는다');
assert.ok(document.querySelector('#dzDashboard #stockPickerSummary'),'가격 요약을 같은 상품 박스 안에 둔다');
assert.ok(document.getElementById('stockPickerSummary').compareDocumentPosition(document.querySelector('.stockPicker .dzWrap'))&Node.DOCUMENT_POSITION_FOLLOWING,
  '상품 설명·가격이 큰 상품 이미지보다 먼저 나온다');
assert.equal(document.querySelector('#stockAnalyticsBody .stockVerdict'),null,'아래에 별도 가격 요약 박스를 만들지 않는다');
assert.ok(asked.some(url=>url.includes('/api/discount?source_id=17')),'상품 ID로 할인률을 조회한다');
assert.match(document.getElementById('dzImage').src,/17\.jpg/);
assert.match(document.getElementById('stockPickerSummary').textContent,/100,000원/);
assert.match(document.getElementById('stockPickerSummary').textContent,/75,000원/);
assert.match(document.getElementById('stockPickerSummary').textContent,/관측 기간 최저가/);
assert.equal(document.querySelector('#stockPickerSummary h4').title,longName,
  '화면에서 잘린 상품명은 마우스를 올리면 전체를 확인할 수 있다');
assert.match(document.querySelector('#stockPriceChart svg').getAttribute('aria-label'),/정가와 판매가/);
assert.match(document.getElementById('stockAnalyticsBody').textContent,/관측 최고가|판매처별 가격 비교/);
assert.equal(document.querySelectorAll('.stockCompareTable tr').length,3,'매칭된 두 판매처를 가격 옆에 보여 준다');
assert.match(document.querySelector('.stockPriceGrid').className,/trGrid/,'기존 1.5:1 그리드 비율을 유지한다');
const saveButton=document.getElementById('dzSaveBtn');
assert.equal(saveButton.textContent,'♥ 찜 해제','DB 찜 상품은 같은 버튼으로 해제할 수 있다');
saveButton.click();
await new Promise(resolve=>setTimeout(resolve,50));
assert.equal(document.querySelectorAll('#dzWishListBody .wlItem').length,5,'찜 해제가 DB 목록에 반영된다');
assert.equal(saveButton.textContent,'♡ 찜 추가');
saveButton.click();
await new Promise(resolve=>setTimeout(resolve,50));
assert.equal(document.querySelectorAll('#dzWishListBody .wlItem').length,6,'같은 버튼으로 다시 찜할 수 있다');
assert.equal(saveButton.textContent,'♥ 찜 해제');

const searchInput=document.getElementById('fsInput');
searchInput.value='코튼';
searchInput.dispatchEvent(new dom.window.Event('input',{bubbles:true}));
assert.equal(document.getElementById('fsSug').hidden,true,'할인률 상품 검색에는 사전 용어 추천을 띄우지 않는다');
searchInput.dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
await new Promise(resolve=>setTimeout(resolve,50));
const itemSearch=document.querySelector('.fsCol[data-lv="3"] input[data-ax="상품명"]');
const beforeTyping=asked.length;
itemSearch.value='데'; itemSearch.dispatchEvent(new dom.window.Event('input',{bubbles:true}));
itemSearch.value='코튼'; itemSearch.dispatchEvent(new dom.window.Event('input',{bubbles:true}));
await new Promise(resolve=>setTimeout(resolve,450));
assert.equal(asked.slice(beforeTyping).filter(url=>url.includes('items_only=1')).length,1,
  '연속 상품명 입력은 한 번만 상품 후보 조회를 보낸다');
assert.ok(asked.slice(beforeTyping).some(url=>url.includes('items_only=1')&&url.includes('q=%EC%BD%94%ED%8A%BC')));
assert.ok(asked.some(url=>url.includes('/api/discount/facets?')&&url.includes('q=%EC%BD%94%ED%8A%BC')),
  '상품명을 서버에서 검색한다');
document.querySelector('#fsPopBg button[data-source-id="24"]').click();
document.getElementById('fsApply').click();
await new Promise(resolve=>setTimeout(resolve,50));
assert.equal(search.FS.stockItem.id,24,'세부검색이 다른 상품 ID를 선택한다');
assert.ok(asked.some(url=>url.includes('/api/discount?source_id=24')));
assert.match(document.getElementById('dzImage').src,/24\.jpg/,'세부검색 썸네일이 선택 카드에 뜬다');
assert.match(document.getElementById('stockPickerSummary').textContent,/60,000원/);
assert.equal(document.getElementById('dzSaveBtn').textContent,'♡ 찜 추가');
document.getElementById('dzSaveBtn').click();
await new Promise(resolve=>setTimeout(resolve,50));
assert.equal(document.getElementById('dzSaveBtn').textContent,'♥ 찜 해제','세부검색 상품도 DB에 찜할 수 있다');
assert.ok(document.querySelector('#dzWishListBody .wlItem[data-source-id="24"]'));
failSave=true;
document.getElementById('dzSaveBtn').click();
await new Promise(resolve=>setTimeout(resolve,50));
assert.equal(document.getElementById('dzSaveBtn').textContent,'♥ 찜 해제','저장 실패 시 찜 상태를 잘못 뒤집지 않는다');
assert.match(document.getElementById('dzSaveError').textContent,/저장 실패 테스트/);
failSave=false;
assert.equal(document.querySelectorAll('.stockCompareTable tr').length,2,'매칭이 없으면 다른 상품을 끼워 넣지 않는다');
assert.match(document.querySelector('.stockComparePanel .note').textContent,/다른 판매처가 없습니다/);

const beforePagedSearch=asked.length;
searchInput.value='원피스';
searchInput.dispatchEvent(new dom.window.Event('input',{bubbles:true}));
searchInput.dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
await new Promise(resolve=>setTimeout(resolve,50));
const productList=document.getElementById('fsC3');
assert.ok(asked.slice(beforePagedSearch).some(url=>url.includes('item_limit=24')&&url.includes('item_offset=0')),
  '할인률 상품은 첫 24개만 요청한다');
assert.equal(productList.querySelectorAll('.fsOpt.has-thumb img').length,24,
  '첫 화면에 상품 이미지 URL 24개만 렌더링한다');
productList.querySelector('[data-stock-page="24"]').click();
await new Promise(resolve=>setTimeout(resolve,50));
assert.ok(asked.some(url=>url.includes('items_only=1')&&url.includes('item_offset=24')),
  '다음 페이지는 상품 후보만 별도로 요청한다');
assert.equal(productList.querySelectorAll('.fsOpt.has-thumb img').length,24);
assert.ok(productList.querySelector('[data-source-id="1024"]'));
productList.querySelector('[data-stock-page="48"]').click();
await new Promise(resolve=>setTimeout(resolve,50));
assert.equal(productList.querySelectorAll('.fsOpt.has-thumb img').length,7);
assert.equal(productList.querySelector('[data-stock-page="72"]'),null,
  '마지막 페이지에서는 다음 버튼을 보이지 않는다');
productList.querySelector('[data-stock-page="24"]').click();
await new Promise(resolve=>setTimeout(resolve,50));
assert.ok(productList.querySelector('[data-source-id="1024"]'),
  '이전 페이지로 돌아갈 수 있다');

const thin=document.createElement('div');
paintStockPriceChart(thin,[{date:'2026-09-18',sale_price:60000,list_price:100000}]);
assert.equal(thin.querySelector('svg'),null,'하루 관측값을 긴 가격 추이로 꾸미지 않는다');
assert.match(thin.textContent,/하루뿐/);

dispatch.trRender('life');
assert.equal(search.FS.stockItem,null,'다른 지표 탭으로 넘어가면 할인률 상품 선택을 격리한다');
assert.ok(search.getFsCols().some(col=>col.ax==='아이템명'),'수명주기 모달의 기존 축을 유지한다');
assert.ok(!search.getFsCols().some(col=>col.ax==='상품명'));
console.log('✅ DB 찜 추가·해제·실패, 드래그, 빠른 상품 검색, 다른 탭 격리 통과');
process.exit(0);
