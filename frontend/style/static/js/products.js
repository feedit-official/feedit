export const ST_ITEM_PAGE_SIZE=24;   /* '더 보기' 한 번에 채우는 카드 수 */

/* 정렬 — 페이지를 나눠 받으므로 정렬은 반드시 서버(API)에서 한다.
   스타일 상세에 들어가면 기본은 FEEDiT 추천순(recommend). */
export const ST_SORTS=[
  ['recommend','FEEDiT 추천순'],['latest','최신순'],
  ['price_desc','가격 높은 순'],['price_asc','가격 낮은 순'],['discount','할인율 높은 순'],
  ['reviews','리뷰 많은 순'],['rating','평점 높은 순'],['likes','좋아요 많은 순'],['sales','판매량 많은 순']
];
/* 드롭다운의 ⓘ 버튼이 펼쳐 보여 주는 FEEDiT 추천순 기준 설명 — 세 줄로 줄여 둔다 */
export const ST_RECOMMEND_NOTE=[
  '리뷰·좋아요·판매량, 평점, 할인율, 상품 정보 충실도를',
  '합쳐 점수가 높은 순으로 보여 줍니다.',
  '쇼핑몰이 주지 않은 값은 0점으로 둡니다.'
];
export const ST_PICK_COUNT=6;   /* FEEDiT 추천순 최상단 몇 개에 'FEEDiT Pick!' 라벨을 붙일지 */

export function styleProductsURL(style,offset=0,limit=ST_ITEM_PAGE_SIZE,sort='latest'){
  const p=new URLSearchParams({style:String(style||''),offset:String(offset),limit:String(limit)});
  if(sort&&sort!=='latest'&&ST_SORTS.some(([k])=>k===sort))p.set('sort',sort);
  return '/api/products?'+p.toString();
}

function priceText(price){
  const value=price&&(price.sale!=null?price.sale:price.list);
  if(value==null)return '가격 정보 없음';
  const n=Number(value);
  return Number.isFinite(n)?n.toLocaleString('ko-KR')+'원':'가격 정보 없음';
}

const numOr=v=>{ const n=Number(v); return v!=null&&Number.isFinite(n)?n:null };

export function styleProductCard(item,styleName){
  return {
    id:'db-'+String(item.product_source_id||item.id||''),
    img:item.image||'',
    br:item.brand||item.source||'브랜드 정보 없음',
    nm:item.name||'상품명 없음',
    pr:priceText(item.price),
    url:item.url||'',
    /* 찜한 키워드 화면이 쓰는 값 — 어느 스타일에서 찜했는지, 숫자 가격, 카테고리 */
    styleName:styleName||'',
    cat:item.category||'',
    price:numOr(item.price&&(item.price.sale!=null?item.price.sale:item.price.list)),
    listPrice:numOr(item.price&&item.price.list)
  };
}
