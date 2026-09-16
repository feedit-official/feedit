export const ST_ITEM_PAGE_SIZE=16;

export function styleProductsURL(style,offset=0,limit=ST_ITEM_PAGE_SIZE){
  const p=new URLSearchParams({style:String(style||''),offset:String(offset),limit:String(limit)});
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
