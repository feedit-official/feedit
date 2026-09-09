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
const FTREE={
  '스트릿':{
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
  '아메토라':'아메카지','ametora':'아메카지','스트릿웨어':'스트릿','스트리트':'스트릿',
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
export const FS_COLS=[
  {ax:'스타일',   param:'style', head:'STYLE'},
  {ax:'종류',     param:'kind',  head:'종류'},
  {ax:'브랜드',   param:'brand', head:'브랜드'},
  {ax:'아이템명', param:'item',  head:'아이템명'}
];
/* 칸으로는 안 서지만 칩으로는 걸리는 축 — 좁히는 축이 아니라 속성이다.
   검색칸에서만 걸린다(사전에 색·디테일·TPO 가 잔뜩 들어 있다). */
const FS_ATTR=['소재','색','디테일','TPO'];
/* 구체적인 것부터 — 지표를 물을 때 무엇을 대표로 삼을지의 순서다 */
export const FS_ORDER=['아이템명','브랜드','종류','스타일'].concat(FS_ATTR);
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
export var FS={pick:{},opts:null,narrowed:false,note:'',err:'',matched:null,
               loading:false,colq:{},sug:[],cur:-1,open:false,id:null};

export function fsReset(){ FS.pick={}; FS.colq={} }
export function fsPickedOf(ax){ return FS.pick[ax]||[] }
export function fsHas(ax,v){ return fsPickedOf(ax).indexOf(v)>=0 }
/* 있으면 빼고 없으면 넣는다 — 칩을 뺐다 꼈다 하는 그 동작 그대로 */
export function fsToggle(ax,v){
  const a=FS.pick[ax]||(FS.pick[ax]=[]);
  const i=a.indexOf(v);
  if(i>=0)a.splice(i,1); else a.push(v);
  if(!a.length)delete FS.pick[ax];
  return i<0;
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
  const q=FS_Q[fsQI%FS_Q.length]; fsQI++;
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
    const near=FIDX.filter(o=>o.key[0]===fsNorm(q)[0]).slice(0,3);
    box.innerHTML='<div class="none">패션 어휘로 인식하지 못했습니다.<br>'+
      '이 검색은 소재 · 아이템 · 스타일 · 브랜드만 다룹니다.'+
      (near.length?'<br><br>혹시 <b>'+near.map(o=>fsEsc(o.label)).join('</b>, <b>')+'</b> 인가요?':'')+'</div>';
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
    return '<button class="sg'+(k===0?' on':'')+(on?' picked':'')+'" data-k="'+k+'" type="button">'+
      '<span class="fc">'+fsEsc(o.f)+'</span><span class="lb">'+lb+'</span>'+
      (on?'<span class="pt">걸려 있음 · 누르면 빠짐</span>':'')+'</button>';
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
   칩으로 걸고 바로 분석한다. 더 좁히고 싶으면 세부 검색을 열면 된다. */
function fsPick(o){
  if(!o)return;
  fsToggle(o.f,o.label);
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

  if(ax==='스타일')
    return fsUniq(Object.keys(FTREE).concat(fsDictOf('스타일')));
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
const FS_PARAM=FS_COLS.reduce((m,c)=>{ m[c.ax]=c.param; return m },{});
function fsOptsFor(ax){
  const key=FS_PARAM[ax];
  if(FS.opts&&key&&Array.isArray(FS.opts[key]))return {list:FS.opts[key],from:'db'};
  return {list:fsLocalOpts(ax).map(l=>({label:l,count:null})),from:'local'};
}

/* ── /api/facets ────────────────────────────────────────
   고른 조건을 그대로 넘기고, 축별 후보를 받아 온다.
   늦게 온 응답이 최신 상태를 덮지 않게 표(seq)를 단다. */
let fsSeq=0, fsFacetT=null;
function fsFacetURL(){
  const p=new URLSearchParams();
  FS_COLS.forEach(c=>fsPickedOf(c.ax).forEach(v=>p.append(c.param,v)));
  p.set('limit',String(FS_POP_CAP));
  return '/api/facets?'+p.toString();
}
/* ★ 실패를 한 문장으로 뭉개지 않는다.
   예전엔 어떤 실패든 "닿지 못했습니다" 하나였다. 그런데 실제로 나온 것은
   **vite 프록시가 Django(:8000)에 못 붙어서 낸 500** 이었고, 그 문장만
   보고는 서버를 안 켠 건지 코드가 깨진 건지 알 수가 없었다.
   HTTP 상태 / JSON 아님 / 아예 못 닿음 을 갈라서 그대로 적는다. */
async function fsFetchFacets(){
  let r;
  try{
    r=await fetch(fsFacetURL());
  }catch(e){
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

export function fsLoadFacets(){
  const my=++fsSeq;
  FS.loading=true; FS.err='';
  fsPaintPop();
  return fsFetchFacets()
    .then(j=>{
      if(my!==fsSeq)return;                    /* 그새 조건이 바뀌었다 */
      FS.loading=false;
      if(j&&j.__fail){
        FS.opts=null; FS.narrowed=false; FS.matched=null;
        FS.err=j.__fail+' 아래는 화면에 박아 둔 목록입니다.';
        if(window.console&&console.warn)console.warn('[facets]',j.__fail);
        fsPaintPop();
        return;
      }
      if(!j||j.status==='error'){
        FS.opts=null; FS.narrowed=false; FS.matched=null;
        FS.err=(j&&j.reason)||'후보를 받지 못했습니다.';
      }else if(j.status==='empty'){
        /* 붙었는데 걸리는 게 없다 — 지어내지 않고 그대로 말한다.
           ★ 빈 객체를 넣으면 안 된다. fsOptsFor 가 '축이 없네' 하고
             로컬 목록으로 떨어져서, 없는 후보를 있는 것처럼 보여 준다.
             축마다 빈 배열을 명시해 '여긴 없다'가 그대로 그려지게 한다. */
        FS.opts={}; FS_COLS.forEach(c=>{ FS.opts[c.param]=[] });
        FS.narrowed=!!j.narrowed; FS.matched=(j.matched==null?0:j.matched);
        FS.err=''; FS.note=j.reason||'';
      }else{
        FS.opts=j.data||{}; FS.narrowed=!!j.narrowed;
        FS.matched=(j.matched==null?null:j.matched);
        FS.note=j.note||''; FS.err='';
      }
      fsPaintPop();
    })
    .catch(e=>{
      if(my!==fsSeq)return;
      FS.loading=false; FS.opts=null; FS.narrowed=false; FS.matched=null;
      FS.err='후보를 그리다 문제가 생겼습니다 ('+(e&&e.message||e)+').';
      if(window.console&&console.warn)console.warn('[facets]',e);
      fsPaintPop();
    });
}
function fsLoadFacetsSoon(){
  clearTimeout(fsFacetT);
  fsFacetT=setTimeout(fsLoadFacets,180);      /* 연달아 누를 때 한 번만 나가게 */
}

/* ── 세부 검색 팝업 ── */
function fsOpenPop(){
  FS.open=true; $('#fsPopBg').classList.add('on'); $('#fsMore').classList.add('on');
  fsPaintPop(); fsLoadFacets();
}
function fsClosePop(){ FS.open=false; $('#fsPopBg').classList.remove('on'); $('#fsMore').classList.remove('on') }

function fsColHTML(col){
  const ax=col.ax;
  const {list,from}=fsOptsFor(ax);
  const q=fsNorm(FS.colq[ax]||'');
  const hit=q?list.filter(o=>fsNorm(o.label).indexOf(q)>=0):list;
  const picked=fsPickedOf(ax);

  if(!hit.length){
    const why=q
      ? '‘'+fsEsc(FS.colq[ax])+'’ 로 찾은 것이 없습니다.'
      : (from==='db'
          ? '이 조건에서는 남는 것이 없습니다.\n칩을 하나 빼 보세요.'
          : '아직 후보가 없습니다.');
    return '<div class="hint">'+why.replace(/\n/g,'<br>')+'</div>';
  }
  const shown=hit.slice(0,FS_POP_CAP);
  return shown.map(o=>{
    const on=picked.indexOf(o.label)>=0;
    return '<button type="button" data-ax="'+fsEsc(ax)+'" data-fv="'+fsEsc(o.label)+'"'+
      ' class="fsOpt'+(on?' on':'')+(o.count===0?' zero':'')+'"'+
      ' aria-pressed="'+(on?'true':'false')+'">'+
      '<span class="fsOptTx">'+fsEsc(o.label)+'</span>'+
      (o.count==null?'':'<i>'+o.count+'</i>')+'</button>';
  }).join('')
  + (hit.length>shown.length
      ? '<div class="hint">'+FS_POP_CAP+'개만 보입니다 ('+hit.length+'개 중).<br>'+
        '위 칸에 쳐서 좁히세요.</div>'
      : '');
}

function fsPaintPop(){
  FS_COLS.forEach((c,lv)=>{
    const host=$('#fsC'+lv); if(!host)return;
    host.innerHTML=fsColHTML(c);
    host.classList.toggle('isLoading',!!FS.loading);
  });
  const chips=fsChipList();
  const picked=$('#fsPicked');
  if(picked)picked.innerHTML=chips.length
    ? chips.map(fsChipHTML).join('')
    : '<span class="ph2">아직 고른 조건이 없습니다. 아무 칸이나 눌러 보세요.</span>';
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
    el.textContent=(FS.matched==null?'':'조건에 걸리는 상품 '+FS.matched.toLocaleString()+'개 · ')+
      '숫자는 그 항목까지 걸었을 때 남는 상품 수입니다.';
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
  fsToggle(String(key).slice(0,i),String(key).slice(i+1));
}
function fsChipsPaint(){
  const box=$('#fsChips'); if(!box)return;
  const chips=fsChipList();
  if(!chips.length){ box.hidden=true; box.innerHTML=''; return }
  box.innerHTML=chips.map(fsChipHTML).join('');
  box.hidden=false;
}

/* 조건을 화면에 반영 — 목업이므로 헤더 문구와 칩으로 결과를 보여준다 */
function fsApply(){
  fsClosePop(); fsChipsPaint();
  const chips=fsChipList();
  trRender(FS.id||'life');
  fsChipsPaint();                    /* trRender 가 본문을 갈아치운 뒤 다시 */
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
    fsPaintSug();
  });
  inp.addEventListener('keydown',e=>{
    if(e.key==='ArrowDown'){ e.preventDefault(); fsMoveSug(1) }
    else if(e.key==='ArrowUp'){ e.preventDefault(); fsMoveSug(-1) }
    else if(e.key==='Escape'){ fsHideSug() }
    else if(e.key==='Enter'){
      e.preventDefault();
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
      fsToggle(b.dataset.ax,b.dataset.fv);
      fsPaintPop();                 /* 누른 티는 즉시 */
      fsLoadFacetsSoon();           /* 다른 칸은 잠시 뒤 서버가 좁혀 준다 */
    });
    /* 칸마다의 찾기 — 브랜드가 수천 개라 칸 안에서도 찾아야 한다 */
    cols.addEventListener('input',e=>{
      const q=e.target.closest('input[data-ax]'); if(!q)return;
      FS.colq[q.dataset.ax]=q.value;
      const lv=FS_COLS.findIndex(c=>c.ax===q.dataset.ax);
      if(lv<0)return;
      const host=$('#fsC'+lv); if(host)host.innerHTML=fsColHTML(FS_COLS[lv]);
    });
  }
  $('#fsPicked').addEventListener('click',e=>{
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
  fsPaintPop();
}
