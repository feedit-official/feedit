import { $, $$, HAS_A, aAnimate, aSpring, aStagger, aTimeline } from '../../../core/static/js/dom.js';
import { kwHideSug } from '../../../trend/static/js/saved_keywords.js';
import { trRender } from '../../../trend/static/js/dispatch.js';

/* ══════════════════════════════════════════════════════
   패션 특화 검색 — 종합 검색이 아니다.
   어휘 트리에 걸리는 말만 통과시키고, 나머지는 실패시킨다.
   색인(태깅)과 질의가 같은 어휘를 쓰기 때문에 별도 차단 목록이 필요 없다.

   ── 2026-09-09 · 단계식을 걷어냈다 ───────────────────────
   세부 검색은 스타일 › 종류 › 브랜드 › 아이템명 을 **위에서부터 차례로**
   좁히는 방식이었다. 브랜드만 알고 있어도 스타일부터 골라야 했고,
   그 계층은 이 파일에 손으로 박아 둔 것이라 RDS 와 아무 상관이 없었다.

   이제 네 칸은 **서로 독립된 필터**다. 겹쳐 고르면 교집합이다 —
   스타일만 고르면 그 스타일 전부, 브랜드까지 고르면 그 스타일의 그 브랜드만.
   고른 것은 칩으로 쌓이고, 칩을 지우면 **그 조건만** 빠진다
   (예전엔 위 단계를 지우면 아래가 통째로 풀렸다).

   후보는 `/api/facets` 가 준다 — commerce.product · product_term 을 세서
   "이 스타일에 실제로 있는 브랜드" 만 남긴다. 서버에 못 닿으면 아래
   FTREE 로 떨어지고, 그 사실을 화면에 적는다(숫자를 지어내지 않는다).
   ══════════════════════════════════════════════════════ */
/* ★ 팀이 정한 핵심 스타일 10종 (2026-09-16).
   세부 검색 STYLE 칸은 이 10개만 보여 준다 — 서버 후보(/api/facets)도 같은 목록을 준다.
   (백엔드 backend/apps/api/views.py 의 DEFAULT_CORE_STYLES 와 같아야 한다.)
   검색창으로 치는 말은 막지 않는다 — 발레코어처럼 핵심이 아닌 말도 지표는 볼 수 있다. */
export const FS_CORE_STYLES=['고프코어','블록코어','바이크코어','놈코어','애슬레저',
                            '클래식','아메카지','그런지','페미닌','스트릿웨어'];
const FTREE={
  '스트릿웨어':{
    '후디'    :{'스투시':['베이직 아치 로고 후디','8볼 후디'],
                '디스이즈네버댓':['아크 로고 후디'],'슈프림':['박스 로고 후디']},
    '크롭티'  :{'아더에러':['크롭 저지 탑'],'널디':['시그니처 크롭 티']},
    '카고 팬츠':{'디스이즈네버댓':['나일론 카고 팬츠'],'스투시':['빈티지 카고']},
    '스니커'  :{'나이키':['덩크 로우','에어포스 1'],'아디다스':['삼바 OG','가젤']}
  },
  '아메카지':{
    '워크 자켓':{'칼하트':['디트로이트 자켓','액티브 자켓'],'폴로 랄프로렌':['치노 워크 자켓']},
    '치노'    :{'폴로 랄프로렌':['클래식 핏 치노'],'유니클로':['와이드 치노']},
    '카라티'  :{'폴로 랄프로렌':['클래식 피케 셔츠'],'유니클로':['드라이 피케 폴로']},
    '데님'    :{'리바이스':['501 오리지널','505 레귤러'],'오어슬로우':['107 아이비 핏']}
  },
  '그런지':{
    '플란넬 셔츠':{'유니클로':['플란넬 체크 셔츠'],'아더에러':['오버사이즈 플란넬']},
    '니트'    :{'아더에러':['디스트로이드 니트'],'무신사 스탠다드':['루즈핏 크루넥']},
    '와이드 데님':{'리바이스':['배기 데드스탁'],'오어슬로우':['1950 와이드']},
    '부츠'    :{'닥터마틴':['1460 8홀','제이든 첼시']}
  },
  '포멀':{
    '셔츠'    :{'무신사 스탠다드':['옥스퍼드 셔츠'],'폴로 랄프로렌':['커스텀 핏 포플린']},
    '테일러드 자켓':{'무신사 스탠다드':['셋업 블레이저'],'아더에러':['언스트럭처드 블레이저']},
    '슬랙스'  :{'무신사 스탠다드':['테이퍼드 슬랙스'],'유니클로':['스마트 앵클 팬츠']},
    '로퍼'    :{'닥터마틴':['에이드리언 태슬'],'폴로 랄프로렌':['페니 로퍼']}
  },
  '발레코어':{
    '크롭티'  :{'미우미우':['리본 크롭 캐미솔'],'널디':['새틴 크롭 탑']},
    '랩 스커트':{'미우미우':['새틴 랩 스커트'],'아더에러':['튤 레이어 스커트']},
    '플랫 슈즈':{'미우미우':['발레 플랫'],'레페토':['상드리용']},
    '가디건'  :{'유니클로':['크롭 볼레로'],'미우미우':['리본 크롭 가디건']}
  },
  '고프코어':{
    '테크 셸' :{'아크테릭스':['베타 LT','감마 SL'],'노스페이스':['마운틴 자켓']},
    '플리스'  :{'파타고니아':['레트로-X'],'노스페이스':['데날리']},
    '트레일 러너':{'살로몬':['XT-6','스피드크로스'],'호카':['스피드고트']},
    '카고 팬츠':{'아크테릭스':['감마 팬츠'],'파타고니아':['백컨트리 팬츠']}
  },
  '블록코어':{
    '저지'    :{'아디다스':['빈티지 트레포일 저지'],'나이키':['레트로 풋볼 저지']},
    '트랙 자켓':{'아디다스':['비컨스 트랙탑'],'나이키':['윈드러너']},
    '스니커'  :{'아디다스':['삼바 OG','스페자'],'뉴발란스':['550']}
  },
  '놈코어':{
    '무지 티' :{'무신사 스탠다드':['베이직 크루넥'],'유니클로':['에어리즘 코튼 T']},
    '치노'    :{'유니클로':['슬림핏 치노'],'무신사 스탠다드':['와이드 치노']},
    '스니커'  :{'뉴발란스':['992','990v6'],'아디다스':['스탠스미스']},
    '플리스 집업':{'파타고니아':['신칠라 스냅-T'],'유니클로':['플러피 플리스']}
  }
};
/* 소재는 트리와 직교한다 — 어느 가지에서도 붙을 수 있어 별도 축으로 둔다 */
const FMAT=['새틴','튤','데님','코튼','린넨','캐시미어','울','플리스','고어텍스','나일론',
            '코듀로이','스웨이드','가죽','메쉬','저지','벨벳','트위드','시어서커'];
/* 오타·다른 이름으로 치는 경우가 실패의 대부분이다 */
const FALIAS={
  '아메토라':'아메카지','ametora':'아메카지','스트릿':'스트릿웨어','스트리트':'스트릿웨어',
  '발레코':'발레코어','고프':'고프코어','블로크코어':'블록코어','블로크':'블록코어',
  '노멀코어':'놈코어','비즈니스캐주얼':'포멀','오피스룩':'포멀',
  '맨투맨':'후디','스웨트셔츠':'후디','후드티':'후디','후드':'후디',
  '반팔':'무지 티','폴로티':'카라티','피케셔츠':'카라티','카라 티셔츠':'카라티',
  '조거':'카고 팬츠','청바지':'데님','진':'데님',
  '스투시':'스투시','stussy':'스투시','carhartt':'칼하트','arcteryx':'아크테릭스',
  'salomon':'살로몬','nike':'나이키','adidas':'아디다스','miumiu':'미우미우',
  '뉴발':'뉴발란스','뉴발란스':'뉴발란스','노페':'노스페이스','파타':'파타고니아'
};

/* ══════════════════════════════════════════════════════
   축 이름 — 이 여덟 개만 화면의 네 칸과 칩에 쓴다.

   ★ '종류' 와 '아이템명' 은 다른 것이다.
     종류    = 사전의 ITEM 용어 (후디 · 스니커 · 카고 팬츠) — 지표가 붙는 말
     아이템명 = 실제 상품 이름 (베이직 아치 로고 후디) — commerce.product
     서버 사전은 앞의 것을 '아이템' 이라 부른다. 내려온 것은 ITEM 용어이므로
     여기서 '종류' 로 받는다. 안 그러면 두 칸에 같은 말이 섞인다.
   ══════════════════════════════════════════════════════ */
export const FS_COLS_DEFAULT=[
  {ax:'스타일',   param:'style', head:'STYLE'},
  {ax:'브랜드',   param:'brand', head:'브랜드'},
  {ax:'종류',     param:'kind',  head:'카테고리'},
  {ax:'아이템명', param:'item',  head:'상품명'}
];
export const FS_COLS_DISCOUNT=[
  {ax:'스타일', param:'style', head:'STYLE'},
  {ax:'브랜드', param:'brand', head:'브랜드'},
  {ax:'카테고리', param:'kind', head:'카테고리'},
  {ax:'상품명', param:'item', head:'상품명'}
];
export function getFsCols() {
  return (FS.id === 'stock') ? FS_COLS_DISCOUNT : FS_COLS_DEFAULT;
}
export const FS_COLS = FS_COLS_DEFAULT;
/* 칸으로는 안 서지만 칩으로는 걸리는 축 — 좁히는 축이 아니라 속성이다.
   검색칸에서만 걸린다(사전에 색·디테일·TPO 가 잔뜩 들어 있다). */
const FS_ATTR=['소재','색','디테일','TPO'];
/* 구체적인 것부터 — 지표를 물을 때 무엇을 대표로 삼을지의 순서다 */
export const FS_ORDER=['상품명','아이템명','브랜드','카테고리','종류','스타일'].concat(FS_ATTR);
/* 세 지표 모두 같은 네 축을 쓴다.
   수명주기의 유행 곡선은 아래 조건 중 지표가 붙는 대표 용어를 기준으로 계산하고,
   실제로 고른 전체 조건은 상품 집합과 화면 제목에 그대로 남긴다. */
const FS_TAB_AXES={};
export function fsAxesFor(id){ return FS_TAB_AXES[id]||null }
export function fsAxOk(ax){ const a=fsAxesFor(FS.id); return !a||a.indexOf(ax)>=0 }
/* 탭을 옮겼을 때 그 탭에서 못 쓰는 조건은 뗀다 — 보이지 않는 조건이 결과에 남으면 안 된다 */
export function fsDropDisallowed(){
  let n=0;
  for(const ax of Object.keys(FS.pick)){ if(!fsAxOk(ax)){ n+=FS.pick[ax].length; delete FS.pick[ax] } }
  return n;
}
/* 서버 사전(facet) → 화면 축 */
const FS_FACET_MAP={'아이템':'종류'};
const fsAxisOf=f=>FS_FACET_MAP[f]||f;

/* 트리를 한 줄짜리 항목들로 펼쳐 둔다. 검색은 전부 이 배열 위에서 일어난다. */
export const FIDX=(function(){
  const out=[], push=(f,label)=>out.push({f,label,key:label.replace(/\s/g,'').toLowerCase()});
  FMAT.forEach(m=>push('소재',m));
  Object.keys(FTREE).forEach(st=>{
    push('스타일',st);
    Object.keys(FTREE[st]).forEach(kd=>{
      if(!out.some(o=>o.f==='종류'&&o.label===kd))push('종류',kd);
      Object.keys(FTREE[st][kd]).forEach(br=>{
        if(!out.some(o=>o.f==='브랜드'&&o.label===br))push('브랜드',br);
        FTREE[st][kd][br].forEach(it=>push('아이템명',it));
      });
    });
  });
  return out;
})();

/* ══════════════════════════════════════════════════════════
   ★ 진짜 사전을 얹는다 — RDS 의 dictionary_term + brand
   ══════════════════════════════════════════════════════════
   FIDX 는 이 파일에 박아 둔 목록이다(146개). 그것만 보고 있어서
   **RDS 에 있는 말도 "사전에서 찾지 못했습니다"** 가 됐다.
   실제로 스투시·키르시·엄브로가 그랬다 — 브랜드는 dictionary_term 이 아니라
   brand 표에 살고, 프론트는 그 표를 아예 몰랐다.

   갈아치우지 않고 '얹는' 이유는 이제 하나다 — 서버가 안 떠 있어도
   검색이 돌아야 하기 때문이다. 계층 때문이 아니다(계층은 걷어냈다). */
let FDICT_LOADED = false;

export async function fsLoadDictionary() {
  if (FDICT_LOADED) return { added: 0, cached: true };
  try {
    const r = await fetch('/api/dictionary');
    const j = await r.json();
    if (!j || j.status !== 'ok' || !Array.isArray(j.data)) {
      return { added: 0, reason: (j && j.reason) || '사전을 못 받았습니다.' };
    }
    const seen = new Set(FIDX.map((o) => o.f + '|' + o.label));
    let added = 0;
    for (const row of j.data) {
      const label = String(row.label || '').trim();
      if (!label) continue;
      const f = fsAxisOf(row.facet);
      const k = f + '|' + label;
      if (seen.has(k)) continue;
      seen.add(k);
      FIDX.push({ f, label, key: label.replace(/\s/g, '').toLowerCase(), src: 'db' });
      added++;
    }
    FDICT_LOADED = added > 0 || j.data.length > 0;
    return { added, total: j.data.length, counts: j.counts };
  } catch (e) {
    /* 서버가 없어도 화면은 돌아야 한다. 박아 둔 목록으로 계속 간다.
       다만 **조용히** 삼키지는 않는다 — 왜 RDS 어휘가 안 잡히는지
       콘솔만 봐도 알 수 있어야 한다. */
    const why = '사전 서버에 닿지 못했습니다 (' + (e && e.message || e) + ').';
    if (window.console && console.warn) console.warn('[dictionary]', why);
    return { added: 0, reason: why };
  }
}

export function fsNorm(s){ return String(s||'').replace(/\s/g,'').toLowerCase() }
/* 어휘 해석 — 별칭까지 본다. 여기서 못 걸리면 그 말은 패션어가 아니다. */
export function fsMatch(q,limit){
  const n=fsNorm(q); if(!n)return [];
  const al=FALIAS[q.trim()]||FALIAS[n]; const an=al?fsNorm(al):null;
  const hit=[];
  FIDX.forEach(o=>{
    if(!fsAxOk(o.f))return;           /* 이 탭에서 못 거는 축은 후보에도 안 띄운다 */
    let i=o.key.indexOf(n);
    if(i<0&&an)i=o.key.indexOf(fsNorm(an));
    if(i<0)return;
    /* 앞에서 걸릴수록, 짧을수록 위로 */
    hit.push({o,rank:i*100+o.label.length+(o.f==='아이템명'?20:0)});
  });
  if(!hit.length&&/\s/.test(q.trim())){
    /* "스투시 후디" 같은 조합어 — 통째로는 없어도 토큰은 사전에 있다 */
    const seen={};
    q.trim().split(/\s+/).forEach((tk,ti)=>{
      if(fsNorm(tk).length<2)return;
      fsMatch(tk,4).forEach((o,k)=>{
        if(seen[o.label])return; seen[o.label]=1;
        hit.push({o,rank:1000+ti*100+k});
      });
    });
  }
  hit.sort((a,b)=>a.rank-b.rank);
  /* 같은 말이 두 번 나올 수 있다 — 한 번만 보여준다 */
  const seenLb={}, out=[];
  for(const h of hit){
    if(seenLb[h.o.f+'|'+h.o.label])continue;
    seenLb[h.o.f+'|'+h.o.label]=1; out.push(h.o);
    if(out.length>=(limit||8))break;
  }
  return out;
}

/* ══════════════════════════════════════════════════════
   ── 상태 ──
   pick  : 축 → 고른 값들. 축끼리는 AND, 한 축 안에서는 OR.
   opts  : /api/facets 가 준 축별 후보 (없으면 로컬 FTREE 로 떨어진다)
   colq  : 칸마다의 찾기 입력 (브랜드가 수천 개라 칸 안에서도 찾아야 한다)
   ══════════════════════════════════════════════════════ */
export var FS={pick:{},stockItem:null,opts:null,narrowed:false,note:'',err:'',matched:null,
               loading:false,colq:{},sug:[],cur:-1,open:false,id:null};

export function fsReset(){ FS.pick={}; FS.stockItem=null; FS.colq={} }
export function fsPickedOf(ax){ return FS.pick[ax]||[] }
export function fsHas(ax,v){ return fsPickedOf(ax).indexOf(v)>=0 }
export function fsStockSelect(item){
  const id=Number(item&&item.id);
  if(!Number.isSafeInteger(id)||id<=0)return false;
  FS.stockItem={id,label:item.label||item.name||'',brand:item.brand||'',
    source:item.source||'',thumb:item.thumb||item.image||''};
  FS.pick['상품명']=[FS.stockItem.label];
  return true;
}
export function fsStockClear(){
  FS.stockItem=null;
  delete FS.pick['상품명'];
}
/* ★ 2026-09-22 — 한 축에는 하나만 건다. 칸 하나가 곧 칩 하나다.
   예전엔 스타일만 갈아 끼우고 브랜드·종류·아이템명은 **쌓였다**(push).
   그래서 브랜드를 두 번 고르면 칩이 두 개가 됐고, 세부 검색에서 네 칸을
   골랐는데 칩은 다섯·여섯 개가 되는 일이 생겼다.
   같은 값을 다시 누르면 그 축이 풀리고, 다른 값을 누르면 갈아 끼운다. */
export function fsToggle(ax,v){
  if(FS.id==='stock'&&ax==='상품명'){ fsStockClear(); return false; }
  if(FS.id==='stock')fsStockClear();
  if(fsHas(ax,v)){ delete FS.pick[ax]; return false }
  FS.pick[ax]=[v];
  return true;
}
/* 칩의 × — 그 조건만 뗀다.
   토글로 지우면 '없으면 도로 넣는' 쪽으로 새기 때문에 지우기는 따로 둔다. */
export function fsRemove(ax,v){
  if(FS.id==='stock'&&ax==='상품명'){ fsStockClear(); return }
  const a=FS.pick[ax]; if(!a)return;
  const i=a.indexOf(v); if(i>=0)a.splice(i,1);
  if(!a.length)delete FS.pick[ax];
}
export function fsCount(){ let n=0; for(const k in FS.pick)n+=FS.pick[k].length; return n }

const FS_Q=[
  ['고프코어 테크 셸','할인률 언제부터 올랐어?'],
  ['살로몬 XT-6','리세일 시세 아직 버텨?'],
  ['새틴','수명주기 어디쯤이야?'],
  ['스투시 후디','지금 사도 되는 시점이야?'],
  ['삼바','정점 지났어?']
];
var fsQI=0, fsQBooked=false;

function fsQStep(){
  const line=$('#fsQ'); if(!line)return;
  const q=FS.id==='stock'?['상품명','할인률을 확인해 보세요']:FS_Q[fsQI%FS_Q.length]; fsQI++;
  const paint=()=>{ line.innerHTML='<i>“<b>'+q[0]+'</b>&nbsp;'+q[1]+'”</i>' };
  if(!HAS_A){ paint(); return }
  if(!line.firstElementChild){ paint();
    aAnimate(line,{opacity:[0,1],translateY:[8,0],duration:520,ease:'out(3)'}); return }
  const t=aTimeline();
  t.add(line,{opacity:[1,0],translateY:[0,-8],duration:260,ease:'in(2)',onComplete:paint},0)
   .add(line,{opacity:[0,1],translateY:[8,0],duration:520,
      ease:aSpring({stiffness:94,damping:16})},260);
}
function fsQTick(){
  try{ const i=$('#fsInput'), w=$('#trSearch');
    if(i&&!i.value&&w&&!w.hidden)fsQStep(); }catch(e){}
  setTimeout(fsQTick,3200);
}

/* 사전 값은 우리가 만든 글자가 아니다. 속성 안에 넣으니 따옴표까지 막는다. */
const fsEsc=s=>String(s==null?'':s).replace(/[&<>"']/g,
  c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

/* ── 연관 검색어 ── */
function fsPaintSug(){
  const box=$('#fsSug'), q=$('#fsInput').value.trim();
  if(!box)return;
  if(!q){ box.hidden=true; box.innerHTML=''; FS.sug=[]; FS.cur=-1; return }
  FS.sug=fsMatch(q,8); FS.cur=FS.sug.length?0:-1;
  if(!FS.sug.length){
    const near=FIDX.filter(o=>fsAxOk(o.f)&&o.key[0]===fsNorm(q)[0]).slice(0,3);
    const axes=fsAxesFor(FS.id);
    box.innerHTML='<div class="none">'+(axes?'이 탭에서 찾을 수 있는 키워드가 아닙니다.':'패션 어휘로 인식하지 못했습니다.')+'<br>'+
      (axes?'수명주기는 사전에 있는 '+axes.join(' · ')+'만 다룹니다.<br>아이템명은 검색할 수 없습니다.'
           :'이 검색은 소재 · 아이템 · 스타일 · 브랜드만 다룹니다.')+
      (near.length?'<br><br>혹시 <b>'+near.map(o=>fsEsc(o.label)).join('</b>, <b>')+'</b> 인가요?':'')+
      /* 사전에 없는 말이면 등재를 요청할 수 있다. 등재되면 알림이 간다
         (account/static/js/notify.js 가 이 버튼을 받는다). */
      '<br><br><button type="button" class="termReqBtn" data-term-req="'+fsEsc(q)+'">'+
        '\u2018'+fsEsc(q)+'\u2019 사전 등재 요청'+
      '</button>'+'</div>';
    box.hidden=false; return;
  }
  const n=fsNorm(q);
  box.innerHTML=FS.sug.map((o,k)=>{
    /* 친 글자만 코랄로 — 어디가 걸렸는지 보이게 */
    let lb=fsEsc(o.label); const i=fsNorm(o.label).indexOf(n);
    if(i>=0){ let c=0,s=-1,e=-1;
      for(let p=0;p<o.label.length;p++){ if(!/\s/.test(o.label[p])){ if(c===i)s=p; if(c===i+n.length-1)e=p; c++ } }
      if(s>=0&&e>=s)lb=fsEsc(o.label.slice(0,s))+'<em>'+fsEsc(o.label.slice(s,e+1))+'</em>'+fsEsc(o.label.slice(e+1));
    }
    const on=fsHas(o.f,o.label);
    /* 검색창은 조건 하나를 새로 건다 — 이미 걸린 말이면 '빼기',
       다른 조건이 함께 걸려 있으면 '이것만 남기기' 가 된다. */
    const pt=on?(fsCount()===1?'걸려 있음 · 누르면 빠짐':'이 조건 하나만 남깁니다'):'';
    return '<button class="sg'+(k===0?' on':'')+(on?' picked':'')+'" data-k="'+k+'" type="button">'+
      '<span class="fc">'+fsEsc(o.f)+'</span><span class="lb">'+lb+'</span>'+
      (pt?'<span class="pt">'+pt+'</span>':'')+'</button>';
  }).join('');
  box.hidden=false;
}
function fsMoveSug(d){
  if(!FS.sug.length)return;
  FS.cur=(FS.cur+d+FS.sug.length)%FS.sug.length;
  $$('#fsSug .sg').forEach((b,i)=>b.classList.toggle('on',i===FS.cur));
  const el=$$('#fsSug .sg')[FS.cur]; if(el&&el.scrollIntoView)el.scrollIntoView({block:'nearest'});
}
export function fsHideSug(){ const b=$('#fsSug'); if(b){b.hidden=true;b.innerHTML=''} FS.sug=[]; FS.cur=-1 }

/* 어휘 하나를 확정. 단계가 없으므로 팝업으로 넘길 일도 없다 —
   칩으로 걸고 바로 분석한다. 더 좁히고 싶으면 세부 검색을 열면 된다.

   ★ 2026-09-22 — 검색창으로 치는 것은 **새 조건 하나**다.
     예전엔 앞서 걸린 조건 위에 얹기만 했다. 그래서 '가디건' 을 쳤는데
     지난 검색(또는 옆 탭)에서 남은 브랜드 칩이 같이 붙어,
     고르지도 않은 브랜드가 결과와 제목에 섞였다.
     이제 치는 순간 앞 조건은 모두 풀고 그 말 하나만 건다 —
     여러 축을 겹쳐 보려면 세부 검색을 쓴다. */
function fsPick(o){
  if(!o)return;
  /* 지금 걸린 것이 그 말 하나뿐이면, 다시 치는 것은 '빼기'로 본다
     (연관 검색어의 '걸려 있음 · 누르면 빠짐' 과 같은 동작) */
  const onlyThis=fsCount()===1&&fsHas(o.f,o.label);
  fsReset();
  if(!onlyThis)fsToggle(o.f,o.label);
  $('#fsInput').value=''; $('#fsBar').classList.remove('typing');
  $('#fsClear').hidden=true; fsHideSug();
  fsApply();
}

/* ══════════════════════════════════════════════════════
   ── 후보 목록 ──
   ① /api/facets 가 준 것 (진짜 — 상품을 세서 교차로 좁힌 것)
   ② 못 받으면 이 파일의 FTREE + 사전 (계층은 FTREE 것만)
   ══════════════════════════════════════════════════════ */
const FS_POP_CAP=200;          /* 브랜드가 2,775개다 — 다 그리면 팝업이 멎는다 */
const FS_STOCK_PAGE=24;        /* 할인률 상품 이미지 URL은 한 번에 이만큼만 받는다 */

function fsDictOf(ax){
  const out=[];
  for(const o of FIDX){ if(o.src==='db'&&o.f===ax)out.push(o.label) }
  return out;
}
function fsUniq(a){ const s=new Set(),o=[]; for(const x of a){ if(x&&!s.has(x)){s.add(x);o.push(x)} } return o }

/* 로컬 폴백. 고른 조건 안에서만 훑어 교차를 흉내 낸다 —
   서버가 세 준 것이 아니므로 개수는 붙이지 않는다(없는 숫자를 만들지 않는다). */
function fsLocalOpts(ax){
  const st=fsPickedOf('스타일'), kd=fsPickedOf('종류'), br=fsPickedOf('브랜드');
  const styles=st.length?st.filter(s=>FTREE[s]):Object.keys(FTREE);

  /* STYLE 칸은 핵심 10종만 — 서버를 못 봐도 같은 목록이어야 화면이 흔들리지 않는다 */
  if(ax==='스타일')
    return FS_CORE_STYLES.slice();
  if(ax==='종류'){
    const a=[];
    styles.forEach(s=>a.push.apply(a,Object.keys(FTREE[s]||{})));
    /* 스타일을 안 고른 상태에서만 사전을 얹는다 — 사전엔 계층이 없어서
       스타일을 고른 뒤에도 얹으면 '좁혀졌다'는 거짓말이 된다. */
    return fsUniq(st.length?a:a.concat(fsDictOf('종류')));
  }
  if(ax==='브랜드'){
    const a=[];
    styles.forEach(s=>Object.keys(FTREE[s]||{}).forEach(k=>{
      if(kd.length&&kd.indexOf(k)<0)return;
      a.push.apply(a,Object.keys(FTREE[s][k]||{}));
    }));
    return fsUniq((st.length||kd.length)?a:a.concat(fsDictOf('브랜드')));
  }
  const a=[];
  styles.forEach(s=>Object.keys(FTREE[s]||{}).forEach(k=>{
    if(kd.length&&kd.indexOf(k)<0)return;
    Object.keys(FTREE[s][k]||{}).forEach(b=>{
      if(br.length&&br.indexOf(b)<0)return;
      a.push.apply(a,FTREE[s][k][b]||[]);
    });
  }));
  return fsUniq(a);
}

/* 서버가 준 것이 있으면 그것, 없으면 로컬. 형태는 [{label,count}] 로 통일한다.

   ★ 서버는 축을 영문 이름(style·kind·brand·item)으로 준다. 화면의 축 이름은
     한글이다. 여기서 바꿔 주지 않으면 FS.opts['스타일'] 이 늘 undefined 라
     **서버가 잘 왔는데도 조용히 로컬 목록으로 떨어진다.** */
function fsOptsFor(ax){
  const col = getFsCols().find(c => c.ax === ax);
  const key = col ? col.param : null;
  if(FS.opts&&key&&Array.isArray(FS.opts[key]))return {list:FS.opts[key],from:'db'};
  if(FS.id === 'stock') return {list:[], from:'db'};
  return {list:fsLocalOpts(ax).map(l=>({label:l,count:null})),from:'local'};
}

/* ── /api/facets ────────────────────────────────────────
   고른 조건을 그대로 넘기고, 축별 후보를 받아 온다.
   늦게 온 응답이 최신 상태를 덮지 않게 표(seq)를 단다. */
let fsSeq=0, fsFacetT=null, fsFacetAbort=null, fsStockFullReady=false;
/* 상품명 후보가 '지금 이 조건'의 것인가 — 깃발 대신 조건 지문(signature)을 쓴다.
   깃발은 호출 순서(누른 티를 먼저 그리고 나중에 다시 세는)에 따라 한 박자
   늦게 내려가서 옛 목록이 찰나에 비쳤다. 지문은 그릴 때마다 비교하므로
   조건이 바뀐 그 프레임부터 바로 안 맞는다. */
let fsItemSig=null;
function fsPickSig(){
  return ['스타일','종류','브랜드'].map(a=>(FS.pick[a]||[]).slice().sort().join('|')).join('//');
}
let fsStockOffset=0, fsStockHasMore=false;
function fsFacetURL(itemsOnly=false, itemOffset=0){
  const p=new URLSearchParams();
  getFsCols().forEach(c=>{ if(fsAxOk(c.ax))fsPickedOf(c.ax).forEach(v=>p.append(c.param,v)) });
  if(FS.id==='stock'&&FS.colq['상품명'])p.set('q',FS.colq['상품명'].trim());
  if(itemsOnly)p.set('items_only','1');
  p.set('limit',String(FS_POP_CAP));
  if(FS.id==='stock'){
    p.set('item_limit',String(FS_STOCK_PAGE));
    p.set('item_offset',String(itemOffset));
  }
  const base = (FS.id === 'stock') ? '/api/discount/facets?' : '/api/facets?';
  return base + p.toString();
}
/* ★ 실패를 한 문장으로 뭉개지 않는다.
   예전엔 어떤 실패든 "닿지 못했습니다" 하나였다. 그런데 실제로 나온 것은
   **vite 프록시가 Django(:8000)에 못 붙어서 낸 500** 이었고, 그 문장만
   보고는 서버를 안 켠 건지 코드가 깨진 건지 알 수가 없었다.
   HTTP 상태 / JSON 아님 / 아예 못 닿음 을 갈라서 그대로 적는다. */
async function fsFetchFacets(url, signal){
  let r;
  try{
    r=await fetch(url,{signal});
  }catch(e){
    if(e&&e.name==='AbortError')return {__cancel:true};
    return {__fail:'후보 서버에 닿지 못했습니다 ('+(e&&e.message||e)+').'};
  }
  const body=await r.text().catch(()=>'');
  if(!r.ok){
    /* dev 에서 이 500 은 거의 항상 "Django 를 안 켰다" 이다.
       vite.config.js 가 /api 를 127.0.0.1:8000 으로 넘기는데 받는 쪽이 없으면
       프록시가 빈 500 을 낸다. */
    return {__fail:'후보 서버가 HTTP '+r.status+' 를 돌려줬습니다 — '+
      'Django API(:8000)가 떠 있는지 확인하세요.'+
      (body?' 응답: '+body.slice(0,120):' (응답 본문이 비어 있습니다 — 프록시가 붙지 못한 모양입니다.)')};
  }
  try{
    return JSON.parse(body);
  }catch(e){
    return {__fail:'후보 서버가 JSON 이 아닌 것을 돌려줬습니다 (HTTP '+r.status+'). '+
      '응답: '+body.slice(0,120)};
  }
}

export function fsLoadFacets(itemsOnly=false, itemOffset=0){
  const fast=itemsOnly&&FS.id==='stock'&&fsStockFullReady&&!!FS.opts;
  if(FS.id==='stock'&&!fast){
    fsStockFullReady=false; fsStockOffset=0; fsStockHasMore=false;
  }
  const my=++fsSeq;
  if(fsFacetAbort)fsFacetAbort.abort();
  fsFacetAbort=new AbortController();
  const controller=fsFacetAbort;
  FS.loading=true; FS.err='';
  if(fast){ $('#fsC3')?.classList.add('isLoading'); fsPaintState(); }
  else fsPaintPop();
  return fsFetchFacets(fsFacetURL(fast,fast?itemOffset:0),controller.signal)
    .then(j=>{
      if(my!==fsSeq)return;                    /* 그새 조건이 바뀌었다 */
      FS.loading=false;
      if(j&&j.__cancel)return;
      if(j&&j.__fail){
        if(!fast)fsStockFullReady=false;
        if(!fast){ FS.opts=null; FS.narrowed=false; FS.matched=null; }
        FS.err=j.__fail+(FS.id === 'stock'
          ? ' 할인률 상품 후보는 서버가 복구되면 다시 표시됩니다.'
          : ' 아래는 화면에 박아 둔 목록입니다.');
        if(window.console&&console.warn)console.warn('[facets]',j.__fail);
        fsPaintPop();
        return;
      }
      if(fast&&j&&j.status==='ok'&&j.items_only){
        const got=Array.isArray(j.data?.item)?j.data.item:[];
        /* 첫 묶음이면 갈아 끼우고, 이어 받은 묶음이면 뒤에 붙인다 (중복 id 는 버린다) */
        let merged=got;
        if(itemOffset>0){
          const prev=Array.isArray(FS.opts?.item)?FS.opts.item:[];
          const seen=new Set(prev.map(o=>String(o.id)));
          merged=[...prev,...got.filter(o=>!seen.has(String(o.id)))];
        }
        FS.opts={...FS.opts,item:merged};
        fsStockOffset=itemOffset;
        fsStockHasMore=!!j.item_has_more;
        FS.err='';
        const host=$('#fsC3');
        if(host){
          const keep=host.scrollTop;
          host.innerHTML=fsColHTML(getFsCols()[3]);
          host.classList.remove('isLoading');
          host.scrollTop=keep;          /* 이어 받아도 보던 자리를 지킨다 */
        }
        fsPaintState();
        return;
      }
      if(!j||j.status==='error'){
        if(!fast){ FS.opts=null; FS.narrowed=false; FS.matched=null; fsStockFullReady=false; }
        FS.err=(j&&j.reason)||'후보를 받지 못했습니다.';
      }else if(j.status==='empty'){
        /* 붙었는데 걸리는 게 없다 — 지어내지 않고 그대로 말한다.
           ★ 빈 객체를 넣으면 안 된다. fsOptsFor 가 '축이 없네' 하고
             로컬 목록으로 떨어져서, 없는 후보를 있는 것처럼 보여 준다.
             축마다 빈 배열을 명시해 '여긴 없다'가 그대로 그려지게 한다. */
        FS.opts={}; getFsCols().forEach(c=>{ FS.opts[c.param]=[] });
        if(FS.id!=='stock')fsItemSig=fsPickSig();
        FS.narrowed=!!j.narrowed; FS.matched=(j.matched==null?0:j.matched);
        FS.err=''; FS.note=j.reason||'';
        if(FS.id==='stock'){
          fsStockFullReady=true; fsStockOffset=0; fsStockHasMore=false;
        }
      }else{
        FS.opts=j.data||{}; FS.narrowed=!!j.narrowed;
        if(FS.id!=='stock')fsItemSig=fsPickSig();
        FS.matched=(j.matched==null?null:j.matched);
        FS.note=j.note||''; FS.err='';
        if(FS.id==='stock'){
          fsStockFullReady=true; fsStockOffset=0; fsStockHasMore=!!j.item_has_more;
        }
      }
      fsPaintPop();
    })
    .catch(e=>{
      if(my!==fsSeq)return;
      FS.loading=false;
      if(!fast){ FS.opts=null; FS.narrowed=false; FS.matched=null; fsStockFullReady=false; }
      FS.err='후보를 그리다 문제가 생겼습니다 ('+(e&&e.message||e)+').';
      if(window.console&&console.warn)console.warn('[facets]',e);
      fsPaintPop();
    }).finally(()=>{
      if(fsFacetAbort===controller)fsFacetAbort=null;
    });
}
function fsLoadFacetsSoon(itemsOnly=false){
  clearTimeout(fsFacetT);
  if(FS.id==='stock'&&!itemsOnly)fsStockFullReady=false;
  fsFacetT=setTimeout(()=>fsLoadFacets(itemsOnly),itemsOnly&&FS.id==='stock'?350:180);
}

/* ── 세부 검색 팝업 ── */
function fsOpenPop(){
  const pop=$('.fsPop'); if(pop){ pop.style.transform=''; pop.style.transition=''; }
  if(FS.id==='stock'){
    FS.colq['상품명']=$('#fsInput')?.value.trim()||'';
    fsStockFullReady=false;
  }
  if(FS.id!=='stock')fsItemSig=null;
  FS.open=true; $('#fsPopBg').classList.add('on'); $('#fsMore').classList.add('on');
  fsPaintPop(); fsLoadFacets();
}
function fsClosePop(){
  FS.open=false;
  clearTimeout(fsFacetT); fsFacetT=null;
  if(fsFacetAbort){ fsFacetAbort.abort(); fsFacetAbort=null; fsSeq++; FS.loading=false; }
  $('#fsPopBg').classList.remove('on'); $('#fsMore').classList.remove('on');
}

/* ★ 2026-09-19 — '이전 24개 / 다음 24개' 를 걷어냈다. 칸을 끝까지 내리면
   다음 묶음을 이어 붙인다 — 상품명은 스크롤로만 본다. */
function fsStockPageHTML(ax){
  if(FS.id!=='stock'||ax!=='상품명'||!fsStockHasMore)return '';
  return '<div class="fsPageNav" data-stock-tail>'+
    (FS.loading?'상품을 더 불러오는 중입니다…':'스크롤하면 더 불러옵니다')+'</div>';
}
/* 칸을 끝까지 내렸을 때 다음 묶음을 이어 받는다 */
export function fsStockScrollMore(host){
  if(FS.id!=='stock'||!fsStockHasMore||FS.loading||!host)return;
  if(host.scrollTop+host.clientHeight < host.scrollHeight-120)return;
  fsLoadFacets(true,fsStockOffset+FS_STOCK_PAGE);
}

/* 상품명 칸의 잠금 — 앞 세 칸 중 하나도 안 골랐으면 후보를 내지 않는다.
   조건 없이 내려오는 이름은 상품의 대표 이름(canonical_name)이라
   실제 상품명으로 읽히지 않는다(‘청’ · ‘반소매 티셔츠 M’). */
function fsItemLocked(ax){
  if(FS.id==='stock'||ax!=='아이템명')return false;
  return !['스타일','종류','브랜드'].some(a=>(FS.pick[a]||[]).length);
}
function fsColHTML(col){
  const ax=col.ax;
  if(fsItemLocked(ax))
    return '<div class="hint">스타일 · 종류 · 브랜드 중 하나를 먼저 고르면<br>'+
      '그 조건에 실제로 있는 상품명이 나옵니다.</div>';
  /* 조건이 바뀌어 다시 세는 동안에는 지난 목록을 그대로 두지 않는다 —
     새 조건과 상관없는 이름이 잠깐 비친다. */
  if(FS.id!=='stock'&&ax==='아이템명'&&(FS.loading||fsItemSig!==fsPickSig()))
    return '<div class="hint">상품명을 불러오는 중입니다...</div>';
  const {list,from}=fsOptsFor(ax);
  const q=fsNorm(FS.colq[ax]||'');
  const hit=q?list.filter(o=>fsNorm(o.label).indexOf(q)>=0):[...list];
  if(FS.id === 'stock') hit.sort((a,b) => a.label.localeCompare(b.label, 'ko-KR'));
  const picked=fsPickedOf(ax);

  if(!hit.length){
    let why = '';
    if (FS.loading && (!FS.opts || !Object.keys(FS.opts).length)) {
      why = '정보를 불러오는 중입니다...';
    } else {
      why=q
        ? '‘'+fsEsc(FS.colq[ax])+'’ 로 찾은 것이 없습니다.'
        : (from==='db'
            ? '이 조건에서는 남는 것이 없습니다.\n칩을 하나 빼 보세요.'
            : '아직 후보가 없습니다.');
    }
    return '<div class="hint">'+why.replace(/\n/g,'<br>')+'</div>'+fsStockPageHTML(ax);
  }
  const cap=(FS.id==='stock'&&ax==='상품명')?hit.length:FS_POP_CAP;   /* 상품명은 스크롤로 이어 본다 */
  const shown=hit.slice(0,cap);
  return shown.map(o=>{
    const on=FS.id==='stock'&&ax==='상품명'
      ? !!(FS.stockItem&&FS.stockItem.id===o.id) : picked.indexOf(o.label)>=0;
    return '<button type="button" data-ax="'+fsEsc(ax)+'" data-fv="'+fsEsc(o.label)+'" title="'+fsEsc(o.label)+'"'+
      (o.id?' data-source-id="'+fsEsc(o.id)+'"':'')+
      ' class="fsOpt'+(on?' on':'')+(o.count===0?' zero':'')+(o.thumb?' has-thumb':'')+'"'+
      ' aria-pressed="'+(on?'true':'false')+'">'+
      (o.thumb?'<img src="'+fsEsc(o.thumb)+'" loading="lazy" alt="">':'')+
      '<span class="fsOptTx">'+fsEsc(o.label)+
        (o.brand||o.source?'<small>'+fsEsc([o.brand,o.source].filter(Boolean).join(' · '))+'</small>':'')+'</span>'+
      (o.count==null?'':'<i>'+o.count+'</i>')+'</button>';
  }).join('')+fsStockPageHTML(ax)
  + (hit.length>shown.length
      ? '<div class="hint">'+FS_POP_CAP+'개만 보입니다 ('+hit.length+'개 중).<br>'+
        '위 칸에 쳐서 좁히세요.</div>'
      : '');
}

export function fsPaintPop(){
  /* 못 쓰는 축의 칸은 접는다 — 남은 칸이 가로를 나눠 갖는다 */
  const cols=$('.fsCols'); let shown=0;
  const pop=$('.fsPop');
  if(pop) {
    if(FS.id === 'stock') pop.classList.add('is-discount');
    else pop.classList.remove('is-discount');
    pop.dataset.fs = FS.id||'';
  }
  $$('.fsCol').forEach(col => col.hidden = true);
  getFsCols().forEach((c,lv)=>{
    const col=$('.fsCol[data-lv="'+lv+'"]'), ok=fsAxOk(c.ax);
    if(col){
      col.hidden=!ok;
      const hd = c.head||c.ax;          /* 화면에 적는 이름 — 내부 축 이름과 다를 수 있다 */
      const ch = col.querySelector('.fsColH'); if(ch) ch.textContent = hd;
      const inp = col.querySelector('input');
      if(inp) {
        inp.dataset.ax = c.ax;
        inp.value = FS.colq[c.ax]||'';
        inp.placeholder = hd + ' 찾기';
        inp.setAttribute('aria-label', hd + ' 찾기');
      }
    }
    if(ok)shown++;
  });
  if(cols)cols.style.setProperty('--fsN',shown);
  getFsCols().forEach((c,lv)=>{
    const host=$('#fsC'+lv); if(!host||!fsAxOk(c.ax))return;
    host.innerHTML=fsColHTML(c);
    host.classList.toggle('isLoading',!!FS.loading);
  });
  const picked=$('#fsPicked');
  if(picked){
    if(FS.id==='stock'){
      /* 할인률은 상품 하나만 본다 — 위 세 칸은 그 상품을 찾기 위한 체다.
         고른 상품 이름만 적고, 조건 칩은 세우지 않는다. */
      picked.innerHTML=FS.stockItem
        ? fsStockNameHTML()
        : '<span class="ph2">상품명 칸에서 볼 상품을 고르세요. 위 세 칸은 후보를 좁히는 데만 쓰입니다.</span>';
    }else{
      const chips=fsChipList();
      picked.innerHTML=chips.length
        ? chips.map(fsChipHTML).join('')
        : '<span class="ph2">아직 고른 조건이 없습니다. 아무 칸이나 눌러 보세요.</span>';
    }
  }
  fsPaintState();
}

/* 지금 무엇을 보고 있는지 한 줄로 — 여기서 거짓말을 하지 않는 것이 중요하다.
   진짜로 좁혀진 건지, 서버를 못 봐서 박아 둔 목록인지 그대로 적는다. */
function fsPaintState(){
  const el=$('#fsState'); if(!el)return;
  if(FS.loading){ el.className='fsState load'; el.textContent='후보를 세는 중…'; return }
  if(FS.err){ el.className='fsState warn'; el.textContent=FS.err; return }
  if(FS.opts&&FS.narrowed){
    el.className='fsState';
    if(FS.id==='stock'&&FS.colq['상품명']){
      el.textContent='입력한 상품명의 후보를 표시합니다. 다른 조건은 그대로 유지됩니다.';
      return;
    }
    /* ★ 2026-09-19 — '조건에 걸리는 상품 N개 · 숫자는 …' 안내문은 뺀다.
       칸마다 붙은 숫자만으로 충분하고, 문구가 길어 검색창 위가 시끄러웠다. */
    el.textContent='';
    return;
  }
  if(FS.opts&&!FS.narrowed){
    el.className='fsState warn';
    el.textContent=FS.note||'상품 자료가 없어 축끼리 좁히지 못했습니다 — 사전 목록만 보입니다.';
    return;
  }
  el.className='fsState warn';
  el.textContent='서버 후보를 못 받아 화면에 박아 둔 목록을 보고 있습니다.';
}

/* 지금 걸린 조건을 [축, 값, 뗄 때 쓸 열쇠] 로 만든다.
   칩을 그리는 곳이 두 군데라 여기 한 곳에서만 만든다 — 어긋나지 않게. */
function fsChipList(){
  const out=[];
  FS_ORDER.forEach(ax=>fsPickedOf(ax).forEach(v=>out.push([ax,v,ax+'|'+v])));
  return out;
}
function fsChipHTML(c){
  return '<span class="fsChip"><small>'+fsEsc(c[0])+'</small>'+fsEsc(c[1])+
    '<button type="button" data-drop="'+fsEsc(c[2])+'" aria-label="'+fsEsc(c[1])+' 조건 빼기">×</button></span>';
}
/* 열쇠는 '축|값' 이다. 값에 | 가 들어와도 첫 칸만 축으로 읽는다. */
function fsDrop(key){
  const i=String(key).indexOf('|'); if(i<0)return;
  fsRemove(String(key).slice(0,i),String(key).slice(i+1));
}
/* 할인률 변화가 실제로 보는 것 — 고른 상품 하나.
   세부 검색의 스타일·브랜드·카테고리는 그 상품을 찾기 위한 **체** 일 뿐이라
   조건 칩으로 세우지 않는다(분석은 이 상품의 가격 기록이다). */
function fsStockNameHTML(){
  const it=FS.stockItem; if(!it)return '';
  const sub=[it.brand,it.source].filter(Boolean).join(' · ');
  return '<span class="fsPickName">'+(sub?'<small>'+fsEsc(sub)+'</small>':'')+
    fsEsc(it.label)+
    '<button type="button" data-stock-drop aria-label="고른 상품 빼기">\u00d7</button></span>';
}
export function fsChipsPaint(){
  const box=$('#fsChips'); if(!box)return;
  /* ★ 2026-09-22 — 할인률 변화 탭은 칩을 쓰지 않는다. 아이템 이름만 적는다. */
  if(FS.id==='stock'){
    box.classList.add('isName');
    const html=fsStockNameHTML();
    box.innerHTML=html;
    box.hidden=!html;
    return;
  }
  box.classList.remove('isName');
  const chips=fsChipList();
  if(!chips.length){ box.hidden=true; box.innerHTML=''; return }
  box.innerHTML=chips.map(fsChipHTML).join('');
  box.hidden=false;
}

/* 조건을 화면에 반영 — 목업이므로 헤더 문구와 칩으로 결과를 보여준다 */
function fsApply(){
  const wasStock=FS.id==='stock';
  fsClosePop(); fsChipsPaint();
  const chips=fsChipList();
  trRender(FS.id||'life');
  fsChipsPaint();                    /* trRender 가 본문을 갈아치운 뒤 다시 */
  /* 할인률은 조건으로 좁히는 화면이 아니다 — 탭 설명을 조건 나열로 덮지 않는다 */
  if(wasStock)return;
  const d=$('#trDesc');
  if(!d||!chips.length)return;
  d.textContent=chips.map(c=>c[1]).join(' · ')+' 조건으로 좁혀 분석했습니다. '+
    '칩을 빼면 그 조건만 풀립니다.';
  if(HAS_A)aAnimate('#fsChips .fsChip',{opacity:[0,1],translateY:[8,0],
    duration:520,delay:aStagger(60),ease:'out(3)'});
}

/* 배선은 한 번만 한다.
   두 번 걸면 한 번의 클릭이 핸들러를 두 번 태운다 — 첫 번째가 값을 넣고
   두 번째가 "이미 있네" 하고 다시 빼서, **눌러도 아무 일이 안 난다.** */
let fsWired=false;

export function fsBuild(){
  const inp=$('#fsInput'), bar=$('#fsBar'); if(!inp)return;
  if(fsWired){ fsPaintPop(); return }   /* 다시 부르면 그리기만 한다 */
  fsWired=true;
  inp.addEventListener('input',()=>{
    bar.classList.toggle('typing',!!inp.value);
    $('#fsClear').hidden=!inp.value;
    if(FS.id==='stock'){ fsHideSug(); return; }
    fsPaintSug();
  });
  inp.addEventListener('keydown',e=>{
    if(e.key==='ArrowDown'){ e.preventDefault(); fsMoveSug(1) }
    else if(e.key==='ArrowUp'){ e.preventDefault(); fsMoveSug(-1) }
    else if(e.key==='Escape'){ fsHideSug() }
    else if(e.key==='Enter'){
      e.preventDefault();
      if(FS.id==='stock'){ fsOpenPop(); return; }
      if(FS.cur>=0&&FS.sug[FS.cur]){ fsPick(FS.sug[FS.cur]); return }
      const m=fsMatch(inp.value,1)[0];
      if(m)fsPick(m); else fsPaintSug();
    }
  });
  $('#fsSug').addEventListener('click',e=>{
    const b=e.target.closest('.sg'); if(!b)return;
    fsPick(FS.sug[+b.dataset.k]);
  });
  $('#fsClear').addEventListener('click',()=>{
    inp.value=''; bar.classList.remove('typing'); $('#fsClear').hidden=true; fsHideSug(); inp.focus();
  });
  $('#fsMore').addEventListener('click',()=>{ FS.open?fsClosePop():fsOpenPop() });
  $('#fsChips').addEventListener('click',e=>{
    if(e.target.closest('[data-stock-drop]')){ fsStockClear(); fsApply(); return }
    const b=e.target.closest('[data-drop]'); if(!b)return;
    fsDrop(b.dataset.drop); fsApply();
  });

  /* ★ 칸 안의 항목은 data-fv 다. data-v 가 아니다.
     예전엔 data-v 였는데, 전역 클릭 위임(app_shell/static/js/router.js)이
     `[data-v]` 를 **화면 전환**으로 읽는다. 그래서 필터를 하나 누르면
     goView('스트릿') 이 돌고, 그런 화면이 없으니 모든 .view 가 꺼져
     **공백 페이지**가 됐다. 팝업이 그 위를 덮고 있어 안 보이다가,
     '이 조건으로 분석' 으로 팝업이 닫히는 순간 공백이 드러났다.
     이름을 바꿔 그 충돌을 끊었다(라우터에도 방어를 하나 더 뒀다). */
  const cols=$('.fsCols');
  if(cols){
    cols.addEventListener('click',e=>{
      const b=e.target.closest('button[data-fv]'); if(!b)return;
      e.stopPropagation();
      if(FS.id==='stock'&&b.dataset.ax==='상품명'){
        const item=(FS.opts&&FS.opts.item||[]).find(o=>String(o.id)===b.dataset.sourceId);
        if(FS.stockItem&&FS.stockItem.id===Number(b.dataset.sourceId))fsStockClear();
        else fsStockSelect(item);
      }else fsToggle(b.dataset.ax,b.dataset.fv);
      fsPaintPop();                 /* 누른 티는 즉시 */
      fsLoadFacetsSoon();           /* 다른 칸은 잠시 뒤 서버가 좁혀 준다 */
    });
    /* 상품명 칸을 끝까지 내리면 다음 묶음을 이어 받는다 (더보기 버튼 대신) */
    cols.addEventListener('scroll',e=>{
      const host=e.target.closest&&e.target.closest('#fsC3');
      if(host)fsStockScrollMore(host);
    },true);
    /* 칸마다의 찾기 — 브랜드가 수천 개라 칸 안에서도 찾아야 한다 */
    cols.addEventListener('input',e=>{
      const q=e.target.closest('input[data-ax]'); if(!q)return;
      FS.colq[q.dataset.ax]=q.value;
      const lv=getFsCols().findIndex(c=>c.ax===q.dataset.ax);
      if(lv<0)return;
      const host=$('#fsC'+lv); if(host)host.innerHTML=fsColHTML(getFsCols()[lv]);
      if(FS.id==='stock'&&q.dataset.ax==='상품명'&&!e.isComposing)fsLoadFacetsSoon(true);
    });
    cols.addEventListener('compositionend',e=>{
      const q=e.target.closest('input[data-ax="상품명"]');
      if(FS.id==='stock'&&q)fsLoadFacetsSoon(true);
    });
  }
  $('#fsPicked').addEventListener('click',e=>{
    if(e.target.closest('[data-stock-drop]')){ fsStockClear(); fsPaintPop(); return }
    const b=e.target.closest('[data-drop]'); if(!b)return;
    fsDrop(b.dataset.drop); fsPaintPop(); fsLoadFacetsSoon();
  });
  $('#fsReset').addEventListener('click',()=>{
    fsReset();
    $$('.fsCols input[data-ax]').forEach(i=>{ i.value='' });
    fsPaintPop(); fsLoadFacets();
  });
  $('#fsApply').addEventListener('click',fsApply);
  $('#fsPopX').addEventListener('click',fsClosePop);
  $('#fsPopBg').addEventListener('click',e=>{ if(e.target===$('#fsPopBg'))fsClosePop() });
  document.addEventListener('keydown',e=>{ if(e.key==='Escape'&&FS.open)fsClosePop() });
  document.addEventListener('click',e=>{ if(!e.target.closest('.fsWrap'))fsHideSug();
    if(!e.target.closest('.kwWrap'))kwHideSug(); });
  if(!fsQBooked){ fsQBooked=true; fsQStep(); setTimeout(fsQTick,3200) }

  const head = $('.fsPopHead');
  const pop = $('.fsPop');
  if(head && pop) {
    let isDragging = false;
    let startX = 0, startY = 0, initialX = 0, initialY = 0;
    head.style.cursor = 'grab';
    head.addEventListener('mousedown', e => {
      if(e.target.closest('button')) return;
      if(!pop.style.transform) { initialX = 0; initialY = 0; }
      isDragging = true;
      head.style.cursor = 'grabbing';
      pop.style.transition = 'none';
      startX = e.clientX - initialX;
      startY = e.clientY - initialY;
      e.preventDefault();
    });
    window.addEventListener('mousemove', e => {
      if(!isDragging) return;
      initialX = e.clientX - startX;
      initialY = e.clientY - startY;
      pop.style.transform = `translate(${initialX}px, ${initialY}px)`;
    });
    window.addEventListener('mouseup', () => {
      if(isDragging) {
        isDragging = false;
        head.style.cursor = 'grab';
      }
    });
  }
  fsPaintPop();
}
