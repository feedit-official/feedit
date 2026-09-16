import { $, $$, HAS_A, aAnimate, aStagger } from '../../../core/static/js/dom.js';
import { IMG, STYLES } from '../../../home/static/js/chat.js';

/* ── 금주의 리포트 데이터 ──
   실제로 셀 수 없는 것(판단 적중률 · 아낀 돈 · 재고 변화 · 내 결정이 옳았는지)은
   전부 뺐다. 대신 이 사람이 사이트에서 실제로 한 행동 — 무엇을 검색했고,
   무엇에 투표했고, 어떤 스타일을 오래 봤는지 — 그 로그만으로 채운다. */
export const WK={
  range:'2026.08 · W2 · 8/13 – 8/19',
  updateDay:'금요일',                 /* 지표는 매주 이 요일에 갱신된다 */
  /* 이번 주 가장 많이 검색·투표한 스타일 — 리포트 전체가 이 스타일을 중심으로 짜인다 */
  topStyle:'block',
  topSearchN:14, topVoteN:5,
  search:34, searchD:11, fav:5, favTotal:23, vote:12, voteD:4,
  /* 트렌드 분석 — 이번 주 챗봇 사용 시간(분) 합계와 1회 평균(분) */
  chatMin:76, chatAvgMin:4.2,
  days:[6,11,9,14,21,17,8], today:'수', bestDay:'금', peak:'21시 – 23시',
  taste:[['발레코어',42,6],['아메카지',28,-3],['워크웨어',18,2],['고프코어',12,5]],
  newTaste:'고프코어',
  /* 추천 웹매거진 — 특정 기사를 지어내는 대신, 실제 매체 사이트에서
     이번 주 관심 스타일을 바로 검색해 보여주는 링크로 연결한다 */
  webzine:[
    {src:'무신사 매거진', domain:'magazine.musinsa.com'},
    {src:'하입비스트 코리아', domain:'hypebeast.kr'},
    {src:'W Korea', domain:'www.wkorea.com'}
  ]
};

/* ── 내 피드 · 살!말? 취향 매칭 큐레이션 ────────────────────────
   살!말? 페이지의 VOTES는 salmalBoot() 함수 안에 갇힌 지역 변수라 다른
   곳에서 참조할 수 없다 — 진행 중(마감 전)인 카드의 값을 여기에 옮겨 적었다.
   VOTES 쪽 데이터가 바뀌면 이 배열도 같이 맞춰야 한다.

   ★ 2026-09-16 · 고정 4장(블록코어 · 아메카지 · 워크웨어 태그)을 걷어냈다.
     카드마다 어울리는 스타일(st, 스타일 페이지 10종 id)을 달아 두고,
     사용자가 고른 즐겨입는 스타일(최대 3개)에 맞는 카드만 골라 4장을 채운다. */
const FEED_SM_POOL=[
  {t:'삼바 OG',                  b:'ADIDAS',            p:139000, votes:2210, hours:3,  a:88, tone:['#2f2b2b','#726358'], st:['block','street'],  cat:'스니커'},
  {t:'셀비지 와이드 데님',        b:'MUSINSA STANDARD',  p:89000,  votes:1930, hours:48, a:64, tone:['#2f3336','#5a6166'], st:['ameka','street'],  cat:'데님'},
  {t:'스퀘어 토 로퍼',            b:'RANDOM IDENTITIES', p:268000, votes:1104, hours:24, a:73, tone:['#2b2b2b','#585858'], st:['classic','ameka'], cat:'로퍼'},
  {t:'스웨이드 블루종 (버건디)',  b:'ANDERSSON BELL',    p:329000, votes:842,  hours:6,  a:81, tone:['#3a332f','#6b5c52'], st:['classic','bike'],  cat:'아우터'},
  {t:'니트 집업 카디건',          b:'INSILENCE',         p:119000, votes:764,  hours:8,  a:69, tone:['#302d2b','#6e6660'], st:['norm','classic'],  cat:'니트'},
  {t:'베이직 옥스포드 셔츠',      b:'MUSINSA STANDARD',  p:39900,  votes:733,  hours:14, a:62, tone:['#302f2c','#6a655c'], st:['norm','ameka'],    cat:'셔츠'},
  {t:'캐시미어 머플러',           b:'LE 17 SEPTEMBRE',   p:98000,  votes:602,  hours:5,  a:71, tone:['#2e2a2c','#5c5459'], st:['classic','norm'],  cat:'머플러'},
  {t:'원턱 와이드 슬랙스',        b:'UNIFORM BRIDGE',    p:79000,  votes:521,  hours:9,  a:66, tone:['#2b2c2d','#585d60'], st:['norm','classic'],  cat:'슬랙스'},
  {t:'퀼팅 다운 베스트',          b:'NAUTICA',           p:149000, votes:512,  hours:11, a:47, tone:['#33302c','#7a7267'], st:['gorp','ath'],      cat:'아우터'},
  {t:'오버핏 울 블레이저',        b:'AMOMENTO',          p:298000, votes:410,  hours:20, a:55, tone:['#332f2b','#6f6255'], st:['classic','grunge'],cat:'아우터'},
  {t:'와이드 코듀로이 팬츠',      b:'SOLEW',             p:139000, votes:391,  hours:15, a:58, tone:['#332e2a','#75695c'], st:['ameka','grunge'],  cat:'팬츠'},
  {t:'레더 크로스 백',            b:'MATIN KIM',         p:168000, votes:305,  hours:30, a:44, tone:['#2c2c2e','#5f5f63'], st:['bike','y2k'],      cat:'가방'},
  {t:'워시드 후드 집업',          b:'THISISNEVERTHAT',   p:129000, votes:288,  hours:40, a:49, tone:['#2b2d2e','#565b5d'], st:['street','ath'],    cat:'후디'},
  {t:'울 발마칸 코트',            b:'SOLEW',             p:398000, votes:226,  hours:40, a:38, tone:['#37312c','#8c7f6e'], st:['classic'],         cat:'코트'},
  {t:'헤비 코튼 크루넥',          b:'COS',               p:59000,  votes:190,  hours:36, a:35, tone:['#2c2b29','#6b665e'], st:['norm','ath'],      cat:'티셔츠'},
  {t:'레이어드 체인 목걸이',      b:'CENTIME',           p:68000,  votes:167,  hours:45, a:41, tone:['#2d2d2f','#5e6165'], st:['y2k','grunge'],    cat:'액세서리'}
];
/* 고른 스타일 순서대로 한 장씩 돌아가며 뽑는다 — 한 스타일이 4장을 독차지하지 않게.
   각 스타일 안에서는 투표가 많은 카드부터. 맞는 카드가 모자라면 인기순으로 채우되
   그 카드에는 '일치' 표시를 붙이지 않는다(맞지 않는 것을 맞는다고 쓰지 않는다). */
export function feedSmPicks(styleIds){
  const ids=STYLES.map(s=>s.id).filter(id=>styleIds.has(id)).slice(0,3);
  const nameOf=id=>(STYLES.find(s=>s.id===id)||{}).n||id;
  const byVotes=FEED_SM_POOL.slice().sort((x,y)=>y.votes-x.votes);
  const used=new Set(), out=[];
  for(let round=0; out.length<4 && round<FEED_SM_POOL.length; round++){
    let added=false;
    for(const id of ids){
      if(out.length>=4)break;
      const c=byVotes.find(o=>!used.has(o)&&o.st.indexOf(id)>=0);
      if(c){ used.add(c); out.push({o:c,hit:c.st.filter(x=>ids.indexOf(x)>=0)}); added=true }
    }
    if(!added)break;
  }
  for(const o of byVotes){ if(out.length>=4)break; if(!used.has(o)){ used.add(o); out.push({o,hit:[]}) } }
  return out.map((x,i)=>{
    const o=x.o, main=x.hit[0]||o.st[0];
    const tags=[
      {tx:'#'+nameOf(main), hit:!!x.hit.length},
      {tx:'#'+o.cat, hit:!!x.hit.length},
      {tx:'#'+nameOf(x.hit[1]||o.st.find(s=>s!==main)||o.b), hit:x.hit.length>1}
    ];
    return Object.assign({},o,{
      title:o.t,
      seg:x.hit.length?Math.max(70,94-i*2-(x.hit.length>1?0:3)):62,
      itemTag:nameOf(main)+' · '+o.cat,
      matched:!!x.hit.length,
      tags
    });
  });
}

/* ── 내 피드 추천 풀 ──
   태그는 필터 칩과 같은 말을 쓴다. risk 는 0(무난) ~ 100(실험). */
const MF_TAGS=['발레코어','아메카지','캐주얼','포멀','고프코어','워크웨어',
               'Y2K','미니멀','스트릿','프레피','시티보이','올드머니'];
const MF_POOL=[
  {b:'ANDERSSON BELL', n:'스웨이드 블루종 자켓', p:329000, img:1,  t:['워크웨어','올드머니'],  r:72, m:96},
  {b:'INSILENCE',      n:'램스울 라운드 니트',   p:118000, img:14, t:['미니멀','프레피'],      r:18, m:93},
  {b:'SOLEW',          n:'와이드 코듀로이 팬츠', p:139000, img:7,  t:['아메카지','캐주얼'],    r:34, m:91},
  {b:'RANDOM IDENT.',  n:'스퀘어 토 페니 로퍼',  p:268000, img:19, t:['포멀','프레피'],        r:44, m:88},
  {b:'MUSINSA STANDARD',n:'옥스퍼드 셔츠',       p:39900,  img:11, t:['미니멀','포멀'],        r:8,  m:86},
  {b:'DE PAUL',        n:'헤비 스웻 후디',       p:89000,  img:8,  t:['스트릿','캐주얼'],      r:26, m:84},
  {b:'MIU MIU',        n:'리본 크롭 캐미솔',     p:790000, img:2,  t:['발레코어','Y2K'],       r:92, m:83},
  {b:'ARC\'TERYX',     n:'감마 SL 셸 자켓',      p:412000, img:23, t:['고프코어'],             r:66, m:81},
  {b:'CARHARTT WIP',   n:'디트로이트 자켓',      p:298000, img:5,  t:['워크웨어','아메카지'],  r:38, m:79},
  {b:'THISISNEVERTHAT',n:'나일론 카고 팬츠',     p:129000, img:27, t:['스트릿','고프코어'],    r:58, m:77},
  {b:'POLO RALPH L.',  n:'클래식 피케 셔츠',     p:149000, img:19, t:['프레피','시티보이'],    r:14, m:75},
  {b:'LEMAIRE',        n:'크로아상 백',          p:1290000,img:30, t:['미니멀','올드머니'],    r:88, m:74},
  {b:'ADIDAS',         n:'삼바 OG',              p:139000, img:12, t:['블록코어','스트릿'],    r:30, m:73},
  {b:'UNIQLO',         n:'와이드 치노',          p:49900,  img:16, t:['캐주얼','시티보이'],    r:6,  m:71},
  {b:'LEVI\'S',        n:'501 오리지널',         p:118000, img:21, t:['아메카지','캐주얼'],    r:12, m:70},
  {b:'ADER ERROR',     n:'디스트로이드 니트',    p:259000, img:25, t:['스트릿','Y2K'],         r:80, m:68}
];
var MF={tags:['발레코어','아메카지','워크웨어'],risk:22};

/* 필터를 반영해 오른쪽 두 칸만 다시 짠다 */
function mfPick(){
  const t=MF.tags;
  const scored=MF_POOL.map(o=>{
    const tagHit=t.length?o.t.filter(x=>t.indexOf(x)>=0).length:0;
    /* 태그가 맞을수록, 성향 슬라이더와 가까울수록 위로 */
    const near=1-Math.abs(o.r-MF.risk)/100;
    return {o,s:tagHit*2.2+near*1.6+o.m/100};
  }).sort((a,b)=>b.s-a.s);
  const top=scored.filter(x=>!t.length||x.o.t.some(y=>t.indexOf(y)>=0));
  const pick=(top.length?top:scored).slice(0,4);
  /* 매칭도는 고정값이 아니라 지금 조건에서의 점수다 — 항상 내림차순으로 읽힌다 */
  const hi=pick.length?pick[0].s:1;
  return {
    rec:pick.map((x,i)=>Object.assign({},x.o,
      {mm:Math.max(64,Math.min(98,Math.round(96-(hi-x.s)*4.6-i*0.8)))})),
    safe:MF_POOL.slice().sort((a,b)=>a.r-b.r).slice(0,4)      /* 성향과 무관한 기본템 */
  };
}
function mfCard(o,tag,accent){
  const st=MF_TAGS.filter(x=>o.t.indexOf(x)>=0)[0]||o.t[0];
  return '<div class="pItem">'+
    '<span class="tg'+(accent?' c':'')+'">'+tag+'</span>'+
    '<span class="im"><img src="'+IMG(o.img)+'" alt="" loading="lazy"></span>'+
    '<span class="tx"><u>'+o.b+'</u><b>'+o.n+'</b>'+
      '<s>'+o.p.toLocaleString()+'원</s>'+
      '<span class="why">'+(accent?'저장하신 '+st+'와 같은 흐름':'실패 확률이 낮은 기본 아이템')+'</span>'+
    '</span></div>';
}
function mfPaint(){
  const host=$('#mfRight'); if(!host)return;
  const {rec,safe}=mfPick();
  const tagTx=MF.tags.length?MF.tags.join(' · '):'전체';
  host.innerHTML=
    '<div class="mfSec"><div class="ph"><h3>오늘의 추천</h3>'+
      '<em>'+tagTx+' · 매칭도 순</em></div>'+
      (rec.length?'<div class="mfGrid">'+rec.map(o=>mfCard(o,'매칭 '+o.mm+'%',1)).join('')+'</div>'
        :'<div class="mfEmpty">고른 조건에 맞는 것이 없습니다.<br>스타일을 하나 더 풀어보세요.</div>')+
    '</div>'+
    '<div class="mfSec"><div class="ph"><h3>무난템 · 국밥템</h3>'+
      '<em>실패 확률이 낮은 기본 아이템</em></div>'+
      '<div class="mfGrid">'+safe.map((o,i)=>mfCard(o,i%3?'국밥템':'무난템',0)).join('')+'</div>'+
    '</div>';
  if(HAS_A)aAnimate($$('#mfRight .pItem'),{opacity:[0,1],translateY:[14,0],
    duration:620,delay:aStagger(46),ease:'out(3)'});
}
