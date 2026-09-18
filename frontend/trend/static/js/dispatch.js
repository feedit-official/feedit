import { $, $$, HAS_A, aAnimate, aSpring, aStagger, aUtils } from '../../../core/static/js/dom.js';
import { WK, feedSmPicks, feedSmLoad } from './my_feed.js';
import { STYLES } from '../../../home/static/js/chat.js';
import { SIMG } from '../../../style/static/js/style_page.js';
import { FS, FS_COLS, fsBuild, fsChipsPaint, fsDropDisallowed, fsHideSug, fsLoadDictionary, fsReset } from '../../../style/static/js/search.js';
import { G_CFG, KW, fsItem, fsItemFull, gMount, josa, trEmpty, trFillBars } from './render_helpers.js';
import { ME, bioPaint } from '../../../account/static/js/profile.js';
import { S_EDIT, S_FEED, TR_META } from './nav_meta.js';
import { assocClosePop, assocOpenPop } from './assoc_popover.js';
import { entryOf, prime, primeUrl, sentimentUrl, stateOf, stateOfUrl, summaryOf, unavailableHTML } from './live_data.js';
import { gChart, gDraw } from './chart_engine.js';
import { kwWire } from './saved_keywords.js';
import { rkChip, rkPaintAv } from '../../../account/static/js/rank.js';
import { jobPlanText } from '../../../account/static/js/job.js';
import { smBarFill, svRender } from './discount_resale.js';
import { trCountUp } from './count_up.js';
import { trDial, wkAnimate } from './weekly_report.js';
import { trSideOpen } from '../../../app_shell/static/js/router.js';
import { weeklyReport, weeklyVideos } from '../../../account/static/js/account_api.js';

/* 탭 자리 — 키워드 검색바 / 커머스 탭 / 없음 세 가지로 갈린다 */
function trTabsRender(id){
  const el=$('#trTabs'); if(!el)return;
  const kwMode=(id==='temp'||id==='assoc'||id==='sentiment');
  el.classList.toggle('kwmode',kwMode);
  if(kwMode){
    el.hidden=false;
    /* 할인률 파트의 챗바와 완전히 같은 골격(.fsWrap/.fsRow/.fsBar).
       세부 검색 버튼만 빼고, 안에서 굴러가는 예시 질문만 파트별로 다르다. */
    el.innerHTML=
      '<div class="fsWrap kwWrap">'+
        '<div class="fsRow">'+
          '<div class="fsBar'+(KW.q?' typing':'')+'" id="kwBar">'+
            '<span class="fsIc">◎</span>'+
            '<input type="text" id="kwInput" autocomplete="off" spellcheck="false" value="'+KW.q+'" '+
              'placeholder="소재 · 아이템 · 스타일 · 브랜드로 검색">'+
            '<span class="fsGhost"><span class="fsQ" id="kwQ"></span></span>'+
            '<button class="fsClear" id="kwClear" type="button"'+(KW.q?'':' hidden')+'>×</button>'+
            /* 엔터 말고 눌러서도 조회할 수 있게. 돌 때는 이 자리가 로딩 표시가 된다. */
            '<button class="kwGoBtn" id="kwGoBtn" type="button" aria-label="조회">'+
              '<span class="kwGoIc">⌕</span></button>'+
          '</div>'+
        '</div>'+
        '<div class="fsSug" id="kwSug" hidden></div>'+
      '</div>';
    return;
  }
  if(id==='stock'){
    el.hidden=false;
    const list=['통합','무신사','지그재그','에이블리'];
    if(list.indexOf(TR_TAB)<0)TR_TAB='통합';
    el.innerHTML=list.map(t=>'<button data-t="'+t+'"'+(t===TR_TAB?' class="on"':'')+'>'+t+'</button>').join('');
  }else{
    el.hidden=true; el.innerHTML=''; TR_TAB='통합';
  }
}
function trFillBarsV(){
  const fl=$$('#trBody .pbars i');
  if(HAS_A){ aUtils.set(fl,{height:'0%'});
    aAnimate(fl,{height:el=>el.dataset.h+'%',duration:1050,delay:aStagger(90),
      ease:aSpring({stiffness:64,damping:16})}); }
  else fl.forEach(x=>x.style.height=x.dataset.h+'%');
}

let TR_CUR=null;
const TR_TRIED={};   /* 용어 → 마지막으로 물어본 때 */

/* 조회를 이미 한 번 보냈다고 표시한다.
   kwGo 가 직접 prime 을 부른 뒤 이걸 찍어 두면, 이어서 도는 trRender 의
   선반입이 **같은 것을 또 묻지 않는다.** (한 번 눌렀는데 두 번 나가던 자리) */
export function markTried(kw){ if(kw) TR_TRIED[kw]=Date.now(); }

/* ── 내 피드 · 내 관심 코어의 시장 화제성 ──
   '즐겨입는 스타일'(ME.styles, 가입 팝업 · 마이페이지에서 고른 것)만 버튼으로 세우고,
   누른 한 개의 화제성만 보여 준다. 다른 스타일은 섞지 않는다.
   ★ 2026-09-17 · 시드 난수를 걷어내고 실데이터로 바꿨다.
     화제성 = /api/trend 의 트렌드 온도(term_metric_daily.trend_temperature)
     주간 변화 = 7일 전 대비 온도 차 · 단계 = /api/lifecycle 의 수명주기 판정
     값이 없으면 숫자를 지어내지 않고 '–' 와 사유를 적는다. */
let TP_PICK=null;
const TP_RISE=['태동','확산'];   /* /api/lifecycle 단계 중 '올라가는' 구간 */
/* 받침 조사 — 영문 이름(Y2K)은 끝 글자를 읽는 소리로 고른다 (L·M·N·R 은 받침) */
const tpJosa=(w,a,b)=>/[A-Za-z0-9]$/.test(w)?(/[LMNRlmnr1368]$/.test(w)?a:b):josa(w,a,b);
function tpMine(){ return STYLES.filter(s=>ME.styles.has(s.id)) }
const lcUrl=n=>'/api/lifecycle?term='+encodeURIComponent(n);

/* 스타일 하나의 실지표를 캐시에서 꺼낸다 (받는 건 tpLoad 가 한다).
   state: loading(아직 안 받음) · none(지표 없음) · ok */
function tpLive(s){
  const st=stateOf(s.n), L=stateOfUrl(lcUrl(s.n));
  if(st.status==='unknown'||L.status==='unknown')return {state:'loading'};
  const S=summaryOf(s.n);
  if(!S||S.temp==null)return {state:'none',reason:st.status==='ok'?'트렌드 온도가 아직 계산되지 않았습니다.':(st.reason||'측정된 자료가 없습니다.')};
  /* 최근 7일 · 그 전 7일 언급량 합 (마지막 적재일 기준) */
  const E=entryOf(s.n), rows=E&&E.byDate?[...E.byDate.values()]:[];
  const inWin=(r,lo,hi)=>{ const d=trDayDiff(r.date,S.asOf); return d>=lo&&d<hi };
  const m7=rows.filter(r=>inWin(r,0,7)).reduce((a,r)=>a+(+r.mention||0),0);
  const m7p=rows.filter(r=>inWin(r,7,14)).reduce((a,r)=>a+(+r.mention||0),0);
  return {state:'ok',temp:Math.round(S.temp),wk:S.tempWk==null?null:Math.round(S.tempWk),
    stage:L.status==='ok'&&L.data?L.data.stage:null,m7,m7p,asOf:S.asOf};
}
/* 고른 스타일들의 온도 · 수명주기를 한꺼번에 받아 두고, 다 받으면 done 을 부른다 */
function tpLoad(list,done){
  if(!list.length)return;
  Promise.allSettled(list.flatMap(s=>[prime(s.n),primeUrl(lcUrl(s.n))])).then(()=>done&&done());
}
function tpHeroHTML(){
  const mine=tpMine();
  if(!mine.length){
    return '<div class="tpPulseTop"><span class="tpTag">TREND ALIGNMENT</span></div>'+
      '<div class="tpPulseCopy"><strong>내 관심 코어의 시장 화제성</strong>'+
        '<p>아직 고른 즐겨입는 스타일이 없습니다.<br>마이페이지에서 스타일을 고르면 여기서 하나씩 확인할 수 있어요.</p>'+
        '<div class="tpTasteTags"><button type="button" data-v="mypage">스타일 고르러 가기 →</button></div>'+
      '</div>';
  }
  if(!mine.some(s=>s.id===TP_PICK))TP_PICK=mine[0].id;
  const cur=mine.find(s=>s.id===TP_PICK);
  const L=tpLive(cur);
  const tabs='<div class="tpTasteTags" role="tablist">'+mine.map(s=>
        '<button type="button" role="tab" data-tp-style="'+s.id+'" aria-selected="'+(s.id===TP_PICK)+'"'+
        (s.id===TP_PICK?' class="on"':'')+'>'+s.n+'</button>').join('')+'</div>';
  let delta='', deg='–', copy;
  if(L.state==='loading'){
    copy='<b>'+cur.n+'</b>의 트렌드 온도를 불러오는 중입니다…';
  } else if(L.state==='none'){
    copy='<b>'+cur.n+'</b>'+tpJosa(cur.n,'은','는')+' 아직 화제성을 잴 자료가 없습니다.<br>'+trEsc(L.reason);
  } else {
    deg=L.temp;
    delta=L.wk==null?'<span class="tpDelta">지난주 비교 불가</span>'
      :'<span class="tpDelta">'+(L.wk>0?'▲ ':L.wk<0?'▼ ':'– ')+Math.abs(L.wk)+'° 지난주 대비</span>';
    copy='<b>'+cur.n+'</b>'+tpJosa(cur.n,'은','는')+' '+
      (L.stage?'지금 <b>'+L.stage+'</b> 구간입니다. ':'수명주기 단계는 아직 판정할 자료가 부족합니다. ')+
      '최근 7일 언급 '+L.m7.toLocaleString()+'건(지난주 '+L.m7p.toLocaleString()+'건) · '+trEsc(L.asOf)+' 기준';
  }
  return '<div class="tpPulseTop"><span class="tpTag">TREND ALIGNMENT · '+cur.en.toUpperCase()+'</span>'+delta+'</div>'+
    '<div class="tpBigDeg">'+deg+(deg==='–'?'':'<em>°</em>')+'</div>'+
    '<div class="tpPulseCopy"><strong>내 관심 코어의 시장 화제성</strong>'+
      '<p>'+copy+'</p>'+tabs+
    '</div>';
}
/* ── 내 관심 스타일 최근 7일 언급량 ──
   화제성 카드와 같은 출처(ME.styles · /api/trend)를 쓴다. 지난주 같은 기간 대비 증감을 붙인다. */
function tpSignalHTML(){
  const mine=tpMine();
  const lives=mine.map(s=>[s,tpLive(s)]);
  const loading=lives.some(x=>x[1].state==='loading');
  const ok=lives.filter(x=>x[1].state==='ok');
  const total=ok.reduce((a,x)=>a+x[1].m7,0);
  const head='<div class="tpSignalHead"><span>LAST 7 DAYS · MENTIONS</span><i class="tpLiveDot"></i></div>';
  let num, p, list='';
  if(!mine.length){ num='–'; p='즐겨입는 스타일을 고르면 그 스타일의 최근 언급량을 모아 보여 드립니다.' }
  else if(loading){ num='–'; p='내 관심 스타일의 언급량을 불러오는 중입니다…' }
  else if(!ok.length){ num='–'; p='고른 스타일에 측정된 언급량이 아직 없습니다.' }
  else {
    num=total.toLocaleString();
    p='수집된 글·영상·리뷰에서 내 관심 스타일이 언급된 건수입니다. 옆 숫자는 지난주 같은 기간 대비 증감입니다.';
    list='<div class="tpSignalList">'+lives.map(([s,L])=>{
      if(L.state!=='ok')return '<span>'+s.n+' <b>–</b></span>';
      const d=L.m7-L.m7p;
      return '<span>'+s.n+' '+L.m7.toLocaleString()+'건 <b>'+(d>0?'+':'')+d.toLocaleString()+'</b></span>';
    }).join('')+'</div>';
  }
  return head+'<div class="tpSignalNum">'+num+'<em>mentions</em></div>'+
    '<div><h4>내 관심 스타일 최근 7일 언급량</h4><p>'+p+'</p>'+list+'</div>';
}
function tpBriefHTML(){
  const mine=tpMine();
  const lives=mine.map(s=>[s,tpLive(s)]);
  const ok=lives.filter(x=>x[1].state==='ok');
  const rise=ok.filter(x=>TP_RISE.includes(x[1].stage));
  let tx;
  if(!mine.length){
    tx='아직 고른 즐겨입는 스타일이 없습니다. 스타일을 고르면 매일 이 자리에서 취향 브리핑을 드립니다.';
  }else if(lives.some(x=>x[1].state==='loading')){
    tx='내 관심 스타일의 트렌드 지표를 불러오는 중입니다…';
  }else if(!ok.length){
    tx='고른 스타일에 측정된 트렌드 지표가 아직 없어 브리핑을 만들지 못했습니다.';
  }else{
    tx=lives.map(([s,L])=>L.state==='ok'
        ? s.n+tpJosa(s.n,'은','는')+' 온도 '+L.temp+'°'+(L.stage?'로 '+L.stage+' 구간':'')
        : s.n+tpJosa(s.n,'은','는')+' 지표 없음').join(', ')+'입니다. '+
      (rise.length
        ? '지금은 '+rise.map(x=>x[0].n).join(' · ')+' 쪽이 올라가는 구간이라 "완전 유행 전" 아이템을 고르기 좋은 타이밍이에요.'
        : '고른 스타일 중 올라가는(태동·확산) 구간은 없어, 새로 사기보다 가진 옷을 활용하기 좋은 시기예요.');
  }
  return '<div class="tpBriefNo">01</div>'+
    '<div class="tpBriefText"><b>오늘의 취향 브리핑</b><p>'+tx+'</p></div>'+
    '<div class="tpBriefScore"><b>'+rise.length+'</b> CORE RISING</div>';
}
/* 받아 온 뒤 카드 세 장 안만 갈아 끼운다 */
function tpRepaint(){
  const h=$('#tpHero'); if(h)h.innerHTML=tpHeroHTML();
  const g=$('#tpSignal'); if(g)g.innerHTML=tpSignalHTML();
  const b=$('#tpBrief'); if(b)b.innerHTML=tpBriefHTML();
}
/* 즐겨입는 스타일이 바뀌면(가입 팝업 · 마이페이지) 내 피드 카드 세 장을 다시 채운다 */
document.addEventListener('feedit:styles',()=>{
  /* 내 피드가 열려 있으면 맞춤 살!말? 카드까지 통째로 다시 고른다 */
  if($('#tpSalGrid')){ trRender('myfeed'); return }
  tpRepaint(); tpLoad(tpMine(),tpRepaint);
});

/* 버튼을 누르면 카드 안만 갈아 끼운다 — 본문 전체를 다시 그리면 등장 애니메이션이 또 돈다 */
document.addEventListener('click',e=>{
  const b=e.target.closest('#tpHero [data-tp-style]'); if(!b)return;
  TP_PICK=b.dataset.tpStyle;
  const h=$('#tpHero'); if(h)h.innerHTML=tpHeroHTML();
});

/* ══════════════════════════════════════════════════════
   실데이터 공용 도우미 — 할인률 · 리세일 · 수명주기 · 연관어
   ══════════════════════════════════════════════════════ */
/* DB 에서 온 글자는 반드시 이스케이프해서 넣는다 */
function trEsc(v){ return String(v==null?'':v).replace(/[&<>"']/g,m=>(
  {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])) }
const wkMetric = value => Number(value||0).toLocaleString('ko-KR');
async function wkLoadVideo(term){
  const host=$('#wkVideoRec');
  if(!host)return;
  const badge0=$('#wkVideoBadge'); if(badge0)badge0.textContent=term||'취향 기반';
  try{
    const data=await weeklyVideos(term);
    if(!host.isConnected)return;
    const video=(data.items||[])[0];
    if(!video)throw new Error('추천할 수 있는 영상이 아직 없습니다.');
    const metrics=video.metrics||{};
    host.innerHTML=
      '<div class="wkVideoFrame"><iframe src="'+trEsc(video.embed_url)+'" '+
        'title="'+trEsc(video.title)+'" loading="lazy" allow="accelerometer; autoplay; clipboard-write; '+
        'encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe></div>'+
      '<div class="wkVideoInfo"><span><b>'+trEsc(video.channel||'YouTube')+'</b>'+trEsc(video.title)+'</span>'+
        '<a href="'+trEsc(video.url)+'" target="_blank" rel="noopener">YouTube에서 보기 ↗</a></div>'+
      '<div class="wkNote"><i>◆</i><span><b>'+trEsc(video.reason)+'</b> 취향과 맞고, '+
        '조회 '+wkMetric(metrics.views)+'회 · 좋아요 '+wkMetric(metrics.likes)+'개 · 댓글 '+
        wkMetric(metrics.comments)+'개인 영상입니다.</span></div>';
    const badge=$('#wkVideoBadge');
    if(badge)badge.textContent=term||video.reason||'취향 기반';
  }catch(error){
    if(!host.isConnected)return;
    host.innerHTML='<div class="wkVideoEmpty"><b>추천 영상을 불러오지 못했습니다.</b><span>'+trEsc(error.message||'잠시 뒤 다시 확인해 주세요.')+'</span></div>';
  }
}
/* ── 금주의 리포트 · 활동 지표 (/api/auth/weekly-report) ──
   ★ 2026-09-17 · 검색 수 · 챗봇 시간 · 요일별 활동 · 취향 지분을 WK 목업에서 실기록으로 바꿨다.
     서버가 user_event(검색·투표·찜·챗봇)와 chat_session 으로 이번 주(월~일, KST)를 집계한다.
     받기 전에는 '…', 실패하면 사유를 적는다. 숫자를 지어내지 않는다. */
let WR={state:'loading',data:null,reason:''};
const WK_DAY=['월','화','수','목','금','토','일'];
const wkSign=n=>(n>0?'+':'')+n;
/* ── 이번 주 리포트의 축 = 가장 많이 검색한 키워드 ──
   ★ 2026-09-17 · 한 줄 요약 · 히어로 카드 · 추천 영상 · 추천 웹매거진이 모두 같은 키워드를 말한다.
     키워드는 스타일만이 아니다 — 브랜드 · 아이템 · 색상 · TPO 등 검색창에서 확정한 모든 말이 된다.
     이번 주 검색 기록이 없으면 내 첫 번째 관심 스타일(없으면 대표 스타일)로 대신하고, 그렇다고 적는다.
     (내 취향 지분은 같은 검색 기록 중 스타일만 따로 나눠 본다 — activity.py _taste_block) */
let WKEY=null;   /* {label, facet, style:STYLES 항목|null, from:'search'|'style'} */
function wkKeyword(fallback){
  const d=WR.data, top=d&&d.search&&d.search.top;
  const byName=n=>STYLES.find(s=>s.n===n)||null;
  if(top&&top.label)return {label:top.label,facet:top.facet||(byName(top.label)?'스타일':''),style:byName(top.label),from:'search'};
  return {label:fallback.n,facet:'스타일',style:fallback,from:'style'};
}
function wkLineHTML(K,rp){
  const h=!K?'<h2>이번 주 가장 관심 있었던 키워드를 확인하고 있습니다…</h2>'
    :K.from==='search'?'<h2>이번 주 가장 관심 있었던 키워드는 <em>'+trEsc(K.label)+'</em>입니다.</h2>'
    :'<h2>이번 주 검색 기록이 없어 관심 스타일 <em>'+trEsc(K.label)+'</em>의 흐름을 보여 드립니다.</h2>';
  return h+'<span>'+rp.join(' · ')+' · 매주 '+WK.updateDay+' 갱신</span>';
}
/* 히어로 카드 — 이미지 · 키워드 이름 · 트렌드 온도 3칸 · 더 보기 버튼 */
function wkHeroHTML(K){
  if(!K)return '<div class="wkHeroImg wkHeroType"><b>…</b></div>'+
    '<div class="wkCopy"><div class="wkState">THIS WEEK</div><h3>…</h3>'+
    '<div class="wkLedger c3">'+wkLedgerHTML(null)+'</div></div>';
  const sub=K.style?K.style.en:(K.facet||'KEYWORD');
  /* 스타일은 스타일 대표 사진, 그 밖의 키워드는 관련 상품 사진을 받아 온 뒤 채운다(wkHeroImage) */
  const img=K.style
    ? '<div class="wkHeroImg"><img src="'+SIMG(K.style)+'" alt="'+trEsc(K.label)+'" loading="lazy"></div>'
    : '<div class="wkHeroImg wkHeroType" id="wkHeroImg"><b>'+trEsc(K.label)+'</b></div>';
  const btn=K.style
    ? '<button type="button" class="pill sm" style="margin-top:20px" data-fit-style="'+K.style.id+'">→ 이 스타일 더 보기</button>'
    : '<button type="button" class="pill sm" style="margin-top:20px" data-tr="temp" data-wk-kw="'+trEsc(K.label)+'" data-wk-facet="'+trEsc(K.facet||'')+'">→ 언급량 · 온도에서 보기</button>';
  return img+
    '<div class="wkCopy">'+
      '<div class="wkState">THIS WEEK · '+(K.from==='search'?'가장 많이 검색한 키워드':'내 관심 스타일')+'</div>'+
      '<h3>'+trEsc(K.label)+' <em>'+trEsc(sub)+'</em></h3>'+
      '<div class="wkLedger c3" id="wkHeroLedger">'+wkLedgerHTML({n:K.label})+'</div>'+
      btn+
    '</div>';
}
/* 스타일이 아닌 키워드의 히어로 사진 — /api/products 의 첫 상품 사진. 없으면 글자 판을 그대로 둔다 */
async function wkHeroImage(K){
  if(!K||K.style)return;
  const p=new URLSearchParams({limit:'1'});
  p.set(K.facet==='브랜드'?'brand':'q',K.label);
  try{
    const r=await fetch('/api/products?'+p.toString(),{headers:{Accept:'application/json'}});
    const j=await r.json();
    const it=j&&j.status==='ok'&&j.data&&(j.data.items||j.data)[0];
    const src=it&&(it.image||it.thumbnail_url);
    const el=$('#wkHeroImg');
    if(src&&/^https?:\/\//.test(src)&&el&&WKEY===K){
      el.classList.remove('wkHeroType');
      el.innerHTML='<img src="'+trEsc(src)+'" alt="'+trEsc(K.label)+'" loading="lazy">';
    }
  }catch(e){ /* 사진이 없어도 카드는 글자 판으로 충분하다 */ }
}
/* '언급량 · 온도에서 보기' — 라우터가 화면을 바꾸기 전에(capture) 검색어를 넘겨 둔다 */
document.addEventListener('click',e=>{
  const b=e.target.closest&&e.target.closest('[data-wk-kw]'); if(!b)return;
  KW.q=b.dataset.wkKw; KW.f=b.dataset.wkFacet||''; KW.part='temp';
  setTimeout(()=>{ const it=$('.sItem[data-tr="temp"]'); if(it){ $$('.sItem').forEach(x=>x.classList.remove('on')); it.classList.add('on') } },0);
},true);
function wkMetricsHTML(){
  const d=WR.data, wait=WR.state!=='ok';
  const v=x=>wait?(WR.state==='loading'?'…':'–'):x;
  const rows=wait
    ? [['검색한 키워드','','개'],['새로 찜한 것','','개'],['살!말? 투표','','표'],['트렌드 분석','','분']]
        .map(r=>[r[0],v(),r[2],WR.state==='loading'?'불러오는 중':trEsc(WR.reason||'기록을 불러오지 못했습니다.'),0])
    : [['검색한 키워드',d.search.keywords,'개',wkSign(d.search.delta)+' · 지난주 대비',1],
       ['새로 찜한 것',d.saved.new,'개','총 '+d.saved.total+'개 추적 중',0],
       ['살!말? 투표',d.vote.count,'표',wkSign(d.vote.delta)+' · 지난주 대비',1],
       ['트렌드 분석',d.chat.minutes,'분',d.chat.sessions?'평균 사용 시간 '+d.chat.avg_minutes+'분':'이번 주 챗봇 사용 기록 없음',0]];
  return rows.map((m,i)=>'<div class="wkMetric'+(m[4]?' hot':'')+'">'+
    '<span class="idx">'+String(i+1).padStart(2,'0')+'</span>'+
    '<span class="lb">'+m[0]+'</span>'+
    '<strong>'+m[1]+'<small>'+m[2]+'</small></strong>'+
    '<em>'+m[3]+'</em></div>').join('');
}
/* 활동이 가장 몰린 2시간 구간 — '21시 – 23시' */
function wkPeakHours(hours){
  let best=-1,at=0;
  for(let h=0;h<24;h++){ const n=hours[h]+hours[(h+1)%24]; if(n>best){best=n;at=h} }
  return best>0?at+'시 – '+((at+2)%24)+'시':'–';
}
function wkDaysHTML(){
  const head=peak=>'<div class="wkCardHead"><h3>요일별 활동</h3><em>PEAK · '+peak+'</em></div>';
  if(WR.state!=='ok')return head('–')+'<div class="wkNote"><i>◆</i><span>'+
    (WR.state==='loading'?'이번 주 활동 기록을 불러오는 중입니다…':trEsc(WR.reason||'활동 기록을 불러오지 못했습니다.'))+'</span></div>';
  const days=WR.data.activity.days, max=Math.max(...days), total=days.reduce((a,b)=>a+b,0);
  const today=WK_DAY[(new Date().getDay()+6)%7];
  const best=max>0?WK_DAY[days.indexOf(max)]:null;
  return head(wkPeakHours(WR.data.activity.hours))+
    '<div class="wkDays"><div class="wkBarset">'+
    WK_DAY.map((d,i)=>{const n=days[i];
      return '<div class="wkDay'+(max>0&&n===max?' peak':'')+(d===today?' today':'')+'">'+
        '<span class="v">'+n+'</span>'+
        '<span class="t"><i data-h="'+(max?Math.round(n/max*100):0)+'"></i></span>'+
        '<span class="l">'+d+'</span></div>'}).join('')+
    '</div></div>'+
    '<div class="wkNote"><i>◆</i><span>'+(total
      ? '<b>'+best+'요일</b>에 가장 많이 활동하셨습니다. 검색 · 투표 · 찜 · 챗봇 기록 '+total+'건 기준입니다. '+
        '<em class="wkNoteSub">30초 안에 취소한 찜 · 투표는 세지 않습니다.</em>'
      : '이번 주 활동 기록이 아직 없습니다. 검색 · 투표 · 찜 · 챗봇을 이용하면 이곳에 쌓입니다.')+'</span></div>';
}
function wkTasteHTML(){
  const head='<div class="wkCardHead"><h3>내 취향 지분</h3><em>VS. LAST WEEK</em></div>';
  if(WR.state!=='ok')return head+'<div class="wkNote"><i>◆</i><span>'+
    (WR.state==='loading'?'취향 지분을 계산하는 중입니다…':trEsc(WR.reason||'취향 기록을 불러오지 못했습니다.'))+'</span></div>';
  const T=WR.data.taste;
  if(!T.items.length)return head+'<div class="wkNote"><i>◆</i><span>이번 주 검색한 키워드 중 스타일이 아직 없습니다. '+
    '스타일을 검색하면 비중이 계산됩니다.</span></div>';
  return head+'<div class="wkTasteList">'+T.items.map((t,i)=>
      '<div class="wkTaste'+(i===0?' primary':'')+'"><span>'+trEsc(t.label)+'</span>'+
      '<span class="rail"><i data-w="'+t.share+'"></i></span>'+
      '<b>'+t.share+'%</b>'+
      (t.delta==null?'<em>비교 전</em>':'<em class="'+(t.delta>=0?'up':'')+'">'+wkSign(t.delta)+'%p</em>')+'</div>').join('')+
    '</div>'+
    '<div class="wkNote"><i>◆</i><span>'+(T.new_style
      ? '이번 주 새로 유입된 축은 <b>'+trEsc(T.new_style)+'</b>입니다. '
      : '')+'이번 주 검색한 스타일 '+T.signals+'건'+(T.prev_signals?' · 지난주 '+T.prev_signals+'건':' · 지난주 기록이 없어 증감은 다음 주부터 표시됩니다')+'.</span></div>';
}
/* 받아 온 뒤 칸만 다시 채운다 — 본문 전체를 다시 그리면 등장 애니메이션이 또 돈다 */
function wkActivityPaint(K,rp){
  const put=(sel,html)=>{ const el=$(sel); if(el)el.innerHTML=html; return el };
  put('#wkLine',wkLineHTML(K,rp));
  put('#wkHero',wkHeroHTML(K));
  put('#wkMetrics',wkMetricsHTML());
  put('#wkDaysCard',wkDaysHTML());
  put('#wkTasteCard',wkTasteHTML());
  $$('#wkReport .wkDay .t i').forEach(e=>e.style.height=e.dataset.h+'%');
  $$('#wkReport .wkTaste .rail i').forEach(e=>e.style.width=e.dataset.w+'%');
  $$('#wkReport .wkMetric').forEach(e=>e.style.setProperty('--u',e.classList.contains('hot')?'38px':'22px'));
}
async function wkActivityLoad(fallback,rp){
  WR={state:'loading',data:null,reason:''};
  try{ WR={state:'ok',data:await weeklyReport(),reason:''} }
  catch(error){
    const msg=error&&error.message||'';
    /* 404 면 서버(Django)에 /api/auth/weekly-report 가 아직 배포되지 않은 것이다 */
    WR={state:'error',data:null,reason:/\(404\)/.test(msg)?'리포트 서버에 활동 기록 기능이 아직 배포되지 않았습니다 (404).':(msg||'활동 기록을 불러오지 못했습니다.')};
  }
  if(!$('#wkReport'))return;
  /* 키워드가 정해진 뒤에 한 줄 요약 · 히어로 · 영상 · 웹매거진을 같은 키워드로 채운다 */
  const K=WKEY=wkKeyword(fallback);
  wkActivityPaint(K,rp);
  wkHeroImage(K);
  tpLoad([{n:K.label}],()=>{ const l=$('#wkHeroLedger'); if(l&&WKEY===K)l.innerHTML=wkLedgerHTML({n:K.label}) });
  wkLoadVideo(K.label);
  wkMagLoad(K.label);
  const g=$('#wkNextGrid'); if(g)g.innerHTML=wkNextHTML(K.style||{id:null});
}
/* ── 추천 웹매거진 (/api/v1/magazines) ──
   ★ 2026-09-17 · 매체 사이트 검색 링크(google site:)를 걷어내고, 관심 키워드를 다룬
     매거진 **기사로 바로** 연결한다. DB 에 매거진 자료가 없어 챗봇 서버가 웹 검색으로 찾는다.
     기준 키워드 = 이번 주 가장 많이 검색한 키워드 → 없으면 히어로 스타일.
     웹 검색은 10~20초 걸리므로 먼저 '찾는 중'을 띄우고, 도착하면 이 카드만 갈아 끼운다. */
let WM={term:'',state:'loading',items:[],reason:''};
const WM_ARROW='<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8">'+
  '<path d="M7 17L17 7M9 7h8v8"/></svg>';
function wkMagHTML(term){
  const head='<div class="wkCardHead"><h3>추천 웹매거진</h3><em>'+trEsc(term||'…')+'</em></div>';
  if(!term||WM.state==='loading')return head+
    '<div class="wkMagLoading"><i></i><span>'+(term?'‘'+trEsc(term)+'’을 다룬<br>웹매거진 기사를 찾고 있습니다.':'관심 키워드를 확인하고 있습니다.')+'</span></div>';
  if(WM.state!=='ok'||!WM.items.length)return head+
    '<div class="wkMagEmpty"><b>추천할 웹매거진 기사를 찾지 못했습니다.</b>'+
      '<span>'+trEsc(WM.reason||'잠시 뒤 다시 확인해 주세요.')+'</span>'+
      /* 웹 검색이 잘려도 챗봇은 뒤늦게 끝내고 결과를 캐시해 둔다.
         그래서 한 번 더 부르면 바로 나오는 일이 많다 — 새로고침 대신 이 버튼을 준다. */
      '<button type="button" class="wkMagRetry" data-wk-mag="'+trEsc(term||'')+'">다시 찾기</button>'+
    '</div>';
  return head+'<div class="wkMagList">'+WM.items.map(a=>
    '<a class="wkMagRow" target="_blank" rel="noopener noreferrer" href="'+trEsc(a.url)+'">'+
    '<span class="tx"><b>'+trEsc(a.magazine)+'</b><span>'+trEsc(a.title)+'</span></span>'+WM_ARROW+'</a>').join('')+
  '</div>';
}
async function wkMagLoad(term){
  WM={term,state:'loading',items:[],reason:''};
  const paint=()=>{ const el=$('#wkMagCard'); if(el&&WM.term===term)el.innerHTML=wkMagHTML(term) };
  paint();
  let next;
  try{
    /* ★ 스스로도 시간을 끊는다. 이게 없으면 중계가 매달릴 때 카드가 '찾는 중'에서
         영영 멈춰 있다 — 사용자는 고장인지 기다리는 중인지 알 수 없다.
         버셀 함수 한도(60초)보다 조금 짧게 둔다. */
    const ctrl=new AbortController();
    const timer=setTimeout(()=>ctrl.abort(),58000);
    let r;
    try{ r=await fetch('/api/v1/magazines?term='+encodeURIComponent(term),
      {headers:{Accept:'application/json'},signal:ctrl.signal}) }
    finally{ clearTimeout(timer) }
    const j=await r.json().catch(()=>null);
    next=j&&Array.isArray(j.articles)&&j.articles.length
      ? {term,state:'ok',items:j.articles.filter(a=>/^https?:\/\//.test(String(a.url||''))),reason:''}
      : {term,state:'empty',items:[],reason:(j&&j.error==='NOT_FOUND')
          ? '웹 검색 서버(챗봇)에 웹매거진 기능이 아직 배포되지 않았습니다.'   /* 옛 챗봇 서버는 /v1/magazines 를 모른다 */
          : (j&&(j.reason||j.error))||'웹 검색 결과가 없습니다.'};
  }catch(e){
    next={term,state:'error',items:[],
      reason:(e&&e.name==='AbortError')
        ? '웹 검색이 오래 걸려 기다리기를 멈췄습니다. 다시 찾기를 누르면 찾아 둔 결과가 나옵니다.'
        : '웹 검색 서버에 연결하지 못했습니다.'};
  }
  if(WM.term!==term)return;   /* 그사이 다른 키워드로 다시 불렀다 */
  WM=next; paint();
}
/* '다시 찾기' — 같은 키워드로 한 번 더 부른다 */
document.addEventListener('click',e=>{
  const b=e.target.closest('.wkMagRetry'); if(!b)return;
  const term=b.dataset.wkMag; if(term)wkMagLoad(term);
});

/* ── 금주의 리포트 실데이터 도우미 ── */
/* 이번 주(월~일) — ['2026.09', 'W3 · 9/14 – 9/20'] 의 두 조각 */
function wkRange(now=new Date()){
  const mon=new Date(now); mon.setDate(now.getDate()-((now.getDay()+6)%7));
  const sun=new Date(mon); sun.setDate(mon.getDate()+6);
  const md=d=>(d.getMonth()+1)+'/'+d.getDate();
  const wn=Math.floor((mon.getDate()-1)/7)+1;
  return [mon.getFullYear()+'.'+String(mon.getMonth()+1).padStart(2,'0'),'W'+wn+' · '+md(mon)+' – '+md(sun)];
}
/* 히어로 3칸 — 트렌드 온도 · 지난주 대비 · 수명주기 단계 */
function wkLedgerHTML(s){
  const L=s?tpLive(s):{state:'loading'};
  const cell=(lb,v,ac)=>'<div'+(ac?' class="ac"':'')+'><span>'+lb+'</span><b>'+v+'</b></div>';
  if(L.state!=='ok'){
    const v=L.state==='loading'?'…':'–';
    return cell('트렌드 온도',v,1)+cell('지난주 대비',v)+cell('수명주기 단계',v);
  }
  return cell('트렌드 온도',L.temp+'°',1)+
    cell('지난주 대비',L.wk==null?'–':(L.wk>0?'+':'')+L.wk+'°')+
    cell('수명주기 단계',L.stage||'판정 전');
}
/* 같이 지켜볼 스타일 3개 — 올라가는(태동·확산) 구간 먼저, 그 안에서 온도 높은 순 */
function wkNextHTML(top){
  const lives=STYLES.filter(s=>s.id!==top.id).map(s=>[s,tpLive(s)]);
  if(lives.some(x=>x[1].state==='loading'))
    return '<div class="note" data-live="loading"><i>◆</i><span>스타일별 트렌드 온도를 불러오는 중입니다…</span></div>';
  const ok=lives.filter(x=>x[1].state==='ok')
    .sort((a,b)=>(TP_RISE.includes(b[1].stage)-TP_RISE.includes(a[1].stage))||(b[1].temp-a[1].temp)).slice(0,3);
  if(!ok.length)return unavailableHTML('스타일별 트렌드 지표가 아직 없습니다.','');
  return ok.map(([s,L])=>
    '<div class="wkNextCard" data-style="'+s.id+'" style="cursor:pointer">'+
    '<div class="wkNextHead"><i></i><b>'+s.n+'</b><span>'+(L.stage?L.stage+' · ':'')+L.temp+'°</span></div>'+
    '<p>'+s.ab+'</p></div>').join('');
}
function trWon(v){ return v==null?'–':Math.round(v).toLocaleString('ko-KR')+'원' }
function trDayDiff(a,b){ return Math.round((new Date(b)-new Date(a))/864e5) }
function trLoading(what){
  return '<div class="note" data-live="loading"><i>◆</i><span>'+what+' 불러오는 중입니다…</span></div>';
}
/* 날짜별 행 두 묶음을 날짜 기준으로 합친다 (차트에 두 계열을 겹칠 때) */
function trMergeRows(a,b){
  const m=new Map();
  (a||[]).concat(b||[]).forEach(r=>{ if(!r||!r.date)return;
    const k=String(r.date).slice(0,10); m.set(k,Object.assign(m.get(k)||{date:k},r)); });
  return [...m.values()].sort((x,y)=>x.date<y.date?-1:1);
}
/* 지표(온도)를 물을 대표 용어 — 상품명에는 지표가 없으므로 브랜드 › 종류 › 스타일 › 속성 순 */
function fsTerm(){
  const p=FS.pick||{};
  for(const ax of ['브랜드','종류','스타일','소재','색','디테일','TPO']){ const a=p[ax]; if(a&&a.length)return a[0]; }
  return '';
}
/* 세부 검색에서 고른 조건을 그대로 API 주소로 옮긴다 */
const EDIT_API={stock:'/api/discount',resale:'/api/resale',life:'/api/lifecycle'};
function editUrl(id){
  const p=new URLSearchParams();
  FS_COLS.forEach(c=>(FS.pick[c.ax]||[]).forEach(v=>p.append(c.param,v)));
  const t=fsTerm(); if(t)p.set('term',t);
  return EDIT_API[id]+'?'+p.toString();
}
/* 받아 둔 값이 있으면 data 를, 아니면 '불러오는 중' / '측정 불가' 를 그리고 null 을 준다 */
function editGate(body,url,what){
  const st=stateOfUrl(url);
  if(st.status==='unknown'){ body.innerHTML=trLoading(what); return null; }
  if(st.status!=='ok'){
    body.innerHTML=unavailableHTML(st.reason,
      st.detail || (st.status==='error'?'연결이 되면 자동으로 실제 값이 뜹니다.':''));
    return null;
  }
  return st.data;
}
/* 한 번만 묻고, 도착하면 그 탭이 아직 열려 있을 때만 다시 그린다 */
function primeOnce(id,url){
  const now=Date.now();
  if(stateOfUrl(url).status==='unknown' && now-(TR_TRIED[url]||0)>3000){
    TR_TRIED[url]=now;
    primeUrl(url).then(()=>{ if(TR_CUR===id) trRender(id); });
  }
}

export function trRender(id){
  TR_CUR=id;
  sFootPaint();   /* 가입·정보수정·인증 승인 뒤에 들어와도 이름·직위가 최신이게 */
  if(typeof assocClosePop==='function')assocClosePop();

  /* ★ 그리기 **전에** 지표를 받아 둔다.
     gChart 는 동기 함수라 그 안에서 기다릴 수가 없다. 그래서 여기서 미리
     받아 캐시에 넣고, 도착하면 그 탭만 다시 그린다.
     같은 용어를 여러 번 열어도 요청은 한 번만 나간다(live_data 가 막는다).

     받아 오기 전에는 stateOf() 가 'unknown' 이라 예전처럼 씨드 난수로 그린다.
     받아 온 뒤 다시 그리면서 실값 또는 '측정 불가'로 바뀐다. */
  if(id==='temp'||id==='assoc'){
    const kw=KW.q||fsItem();
    /* ★ 한 번 시도한 말은 잠깐 다시 안 묻는다.
       실패는 캐시하지 않기로 했는데(고친 뒤 재시도가 돼야 하니까),
       그러면 stateOf() 가 계속 'unknown' 이라
       prime → trRender → prime … 으로 **끝없이 돈다.**
       그래서 '방금 물어봤나'를 따로 기억한다. 사람이 다시 누르면
       3초는 지나므로 재시도는 그대로 된다. */
    const now=Date.now();
    if(kw && stateOf(kw).status==='unknown' && now-(TR_TRIED[kw]||0)>3000){
      TR_TRIED[kw]=now;
      prime(kw).then(()=>{
        /* 사용자가 그새 다른 탭으로 갔으면 다시 그리지 않는다 */
        if(TR_CUR===id) trRender(id);
      });
    }
  }
  /* 연관어 · 할인률 · 리세일 · 수명주기는 URL 단위로 받는다 */
  if(id==='assoc'&&KW.q) primeOnce(id,'/api/assoc?term='+encodeURIComponent(KW.q));
  if(id==='sentiment'&&KW.q) primeOnce(id,sentimentUrl(KW.q,KW.f));
  if(EDIT_API[id]&&fsItem()) primeOnce(id,editUrl(id));
  const m=TR_META[id]||TR_META.myfeed;
  $('#trTitle').textContent=m[0];
  $('#trDesc').textContent=m[1]; $('#trDesc').hidden=!m[1];
  /* 탭 자리는 파트마다 쓰임이 다르다.
     언급량·연관어·긍부정 → 자유 키워드 입력창
     할인률                → 커머스 탭
     그 외                 → 비워 둔다 */
  trTabsRender(id);
  /* ★ 검색창 배선은 **여기 한 곳에서** 붙인다.
     trTabsRender 가 챗바를 통째로 새로 그리므로 매번 다시 붙여야 하는데,
     예전엔 각 탭 블록 맨 끝에 있었다. 그래서 값이 없거나 못 붙어서
     중간에 return 하면 배선이 안 붙었고, **한 번 검색한 뒤로는
     두 번째 검색이 아예 안 먹었다.**
     여기 두면 어느 분기로 빠져나가도 검색은 살아 있다.
     (두 번 부르면 이벤트가 겹쳐 한 번에 두 번 조회된다 — 그래서 한 곳뿐이다.) */
  if (id === 'temp' || id === 'assoc' || id === 'sentiment') kwWire(id);
  /* 검색은 할인률 · 리세일 · 수명주기 세 파트에서만 쓴다 */
  /* 내 피드만 타이틀/설명 대신 프로필(아바타·이름·등급·소개)을 보여준다 */
  const isMyFeed=(id==='myfeed');
  const tw=$('#trTitleWrap'), tp=$('#trProfile');
  if(tw)tw.hidden=isMyFeed;
  if(tp)tp.hidden=!isMyFeed;
  const kk=$('#trKicker'); if(kk)kk.hidden=(id!=='report');
  const wkSpan=$('.trHead>span'); if(wkSpan)wkSpan.hidden=(id==='report');
  const sw=$('#trSearch');
  if(sw){
    const useSearch=['stock','resale','life'].indexOf(id)>=0;
    sw.hidden=!useSearch;
    /* 검색을 안 쓰는 탭으로 나가면 걸린 조건도 함께 푼다 —
       돌아왔을 때 안 보이는 조건이 결과에 남아 있으면 안 된다. */
    if(!useSearch){ fsReset(); fsHideSug();
      const cb=$('#fsChips'); if(cb){cb.hidden=true;cb.innerHTML=''} }
    FS.id=useSearch?id:null;
    /* 수명주기는 스타일 · 종류 · 브랜드까지만 — 다른 탭에서 걸어 온 아이템명 조건은 뗀다 */
    if(useSearch&&fsDropDisallowed())fsChipsPaint();
    const fi=$('#fsInput');
    if(fi)fi.placeholder=(id==='life')?'스타일 · 종류 · 브랜드로 검색':'소재 · 아이템 · 스타일 · 브랜드로 검색';
  }
  const body=$('#trBody'); if(!body)return;

  /* ★ 검색 전에는 아무 숫자도 그리지 않는다.
     전에는 '발레코어' 가 기본값이라, 들어오자마자 화면이 지표로 가득 찼다.
     묻지도 않았는데 답이 떠 있으면 그게 진짜 측정값인 줄 알기 쉽다.

     키워드 탭(언급량·연관어·긍부정)  → KW.q
     검색 탭(할인률·리세일·수명주기)  → fsItem()
     둘 다 비어 있으면 여기서 끝낸다. */
  const KW_TABS = ['temp', 'assoc', 'sentiment'];
  const SEARCH_TABS = ['stock', 'resale', 'life'];
  if (KW_TABS.indexOf(id) >= 0 && !KW.q) {
    body.innerHTML = trEmpty(
      '무엇의 ' + (TR_META[id] ? TR_META[id][0] : '지표') + '을(를) 볼까요?',
      '위 검색창에 스타일·소재·아이템·브랜드를 넣어 주세요.\n' +
      '예: 발레코어 · 새틴 · 엄브로');
    return;
  }
  if (SEARCH_TABS.indexOf(id) >= 0 && !fsItem()) {
    body.innerHTML = trEmpty(
      '먼저 볼 대상을 고르세요',
      '위 검색에서 카테고리나 브랜드를 좁혀 주세요.\n' +
      '고른 것에 맞춰 지표를 불러옵니다.');
    return;
  }

  const kpi=(l,v,u,d,up)=>'<div class="kpi"><span>'+l+'</span><b>'+v+(u?'<u>'+u+'</u>':'')+
    '</b><div class="dl '+(up?'up':'dn')+'">'+d+'</div></div>';

  /* ══════════════ 내 피드 — 취향 펄스 & 살!말? 큐레이션 ══════════════
     (feedit-my-feed.html 디자인 이식) 판정(리포트)과 역할을 분리 —
     여기는 ① 관심 코어의 시장 화제성 + 신규 신호 브리핑,
     ② 세그먼트(체형·스타일 태그)와 아이템 태그가 모두 맞는 살!말?만
     선별 노출한다. 큐레이션 카드는 실제 VOTES 데이터(투표율·마감·매치
     점수)를 그대로 쓰고, 게시자 페르소나만 표시용으로 얹었다. */
  if(id==='myfeed'){
    const won=n=>n.toLocaleString('ko-KR')+'원';
    const hoursTx=h=>h>=24?Math.round(h/24)+'일':h+'시간';
    /* 카드 구조와 상품 정보는 살!말? 본 화면과 같은 JSON 값을 쓴다.
       매칭 이유와 태그만 카드 바깥의 내 취향 전용 정보로 덧붙인다. */
    const salCard=p=>
      '<div class="tpPickWrap">'+
        '<article class="voteCard in" role="button" tabindex="0" data-v="salmal" data-sm="taste">'+
          '<div class="fig">'+
            '<div class="plate" style="background-image:url('+p.imgURL+');background-size:cover;background-position:center"></div>'+
            '<div class="vig"></div>'+
            '<span class="pricep">'+won(p.p)+'</span>'+
            '<span class="tagp"><b>'+p.b+'</b></span>'+
          '</div>'+
          '<div class="body">'+
            '<h4>'+p.title+'</h4>'+
            '<div class="cap">'+p.votes.toLocaleString('ko-KR')+'표 · 마감까지 '+hoursTx(p.hours)+'</div>'+
            '<div class="smBar">'+
              '<i class="buy" data-w="'+p.a+'" style="width:'+p.a+'%"><span>살 '+p.a+'%</span></i>'+
              '<i class="no" data-w="'+(100-p.a)+'" style="width:'+(100-p.a)+'%"><span>'+(100-p.a)+'% 말</span></i>'+
            '</div>'+
            '<div class="smBtns">'+
              '<button type="button" class="buy" data-v="salmal" data-sm="taste">살!</button>'+
              '<button type="button" data-v="salmal" data-sm="taste">말?</button>'+
            '</div>'+
          '</div>'+
        '</article>'+
        '<div class="tpReason">'+
          /* ★ 유사도 %를 지어내지 않는다. 실제로 이 카드에 투표한 사람 중
               나와 성별·체형·나이·취향이 겹치는 사람 수와 그들의 살 비율만 쓴다.
               표본이 없으면 그렇다고 말한다(API 의 reason 을 그대로). */
          (p.simHas
            ? '<div class="tpReasonLine"><span class="tpCheck">✓</span>'+
                '<span><strong>나와 비슷한 사용자 '+p.simUsers+'명</strong> · 이 중 살 '+p.simPct+'%</span></div>'
            : '<div class="tpReasonLine"><span class="tpCheck">·</span>'+
                '<span><strong>비슷한 사용자 표본 없음</strong> · '+trEsc(p.simReason||'아직 비슷한 사용자의 투표가 없습니다')+'</span></div>')+
          (p.matched
            ? '<div class="tpReasonLine"><span class="tpCheck">✓</span>'+
                '<span><strong>아이템 취향 일치</strong> · '+trEsc(p.itemTag)+'</span></div>'
            : '<div class="tpReasonLine"><span class="tpCheck">·</span>'+
                '<span><strong>인기 카드</strong> · 내 스타일과 겹치는 카드가 모자라 채웠습니다</span></div>')+
        '</div>'+
        '<div class="tpTags">'+p.tags.map(t=>'<span'+(t.hit?' class="hit"':'')+'>'+t.tx+'</span>').join('')+'</div>'+
      '</div>';
    body.innerHTML=
      '<div class="tpSection">'+
        '<div class="tpSecLabel"><h3>내 취향 브리핑</h3><span>TASTE PULSE / LIVE</span></div>'+
        '<div class="tpPulseGrid">'+
          '<article class="tpCard tpHero" id="tpHero">'+tpHeroHTML()+'</article>'+
          '<article class="tpCard tpSignal" id="tpSignal">'+tpSignalHTML()+'</article>'+
        '</div>'+
        '<article class="tpCard tpBrief" id="tpBrief">'+tpBriefHTML()+'</article>'+
      '</div>'+
      '<div class="tpSection" style="padding-top:0">'+
        '<div class="tpSalHead"><div><h3>내 취향 맞춤 <em>살!말?</em></h3>'+
          '<p>전체 살!말? 목록 중 나와 체형·스타일 세그먼트가 유사하고,'+
          '동시에 고민 중인 아이템도 내 취향 태그와 겹치는 글만 선별했습니다.</p></div>'+
          '<div class="tpFilterLogic"><span class="tpLogicChip">TOP 4</span></div>'+
        '</div>'+
        '<div class="tpSalGrid" id="tpSalGrid">'+
          '<div class="tpSalState">살!말? 카드를 불러오는 중입니다…</div></div>'+
        '<div class="tpEmptyMore" id="tpSalNote"></div>'+
      '</div>';
    /* ★ 살!말? 카드는 본 화면과 같은 API(/api/salmal/cards)에서 온다.
         목업 JSON을 쓰지 않으므로 여기서만 값이 다를 일이 없다.
         못 불러오면 카드를 그리지 않고 이유를 쓴다 — 빈 화면도, 가짜 카드도 아니다. */
    feedSmLoad().then(pool=>{
      const grid=$('#tpSalGrid'), note=$('#tpSalNote');
      if(!grid)return;
      const picks=feedSmPicks(ME.styles,pool);
      if(!picks.length){
        grid.innerHTML='<div class="tpSalState">지금 진행 중인 살!말? 고민이 없습니다.</div>';
        if(note)note.textContent='';
        return;
      }
      grid.innerHTML=picks.map(salCard).join('');
      if(note)note.textContent=ME.styles.size
        ? STYLES.filter(s=>ME.styles.has(s.id)).map(s=>s.n).join(' · ')+' 기준으로 고른 고민 '+picks.length+'건 표시 중'
        : '즐겨입는 스타일이 없어 인기 고민 '+picks.length+'건을 표시 중';
      if(HAS_A){
        aAnimate($$('#tpSalGrid .tpPickWrap'),
          {opacity:[0,1],translateY:[16,0],duration:620,delay:aStagger(52),ease:'out(3)'});
        smBarFill($$('#tpSalGrid .smBar i'),{duration:920,step:44,start:120});
      }
    }).catch(error=>{
      const grid=$('#tpSalGrid'), note=$('#tpSalNote');
      if(grid)grid.innerHTML='<div class="tpSalState">살!말? 카드를 불러오지 못했습니다.<br>'+
        trEsc(String(error&&error.message||error))+'</div>';
      if(note)note.textContent='';
    });
    /* 버튼을 눌러도 여기서 투표를 완결시키지 않는다 — 살!/말! 버튼은
       data-v="salmal" 을 달아 살!말? 페이지로 보내고, 실제 투표는
       거기서만 일어난다(문서 전역 [data-v] 클릭 위임을 그대로 탄다). */
    /* 프로필은 우리 계정(ME)과 뱃지 시스템을 따른다 */
    const pv=$('#trProfAv'), pn=$('#trProfNm'), pr=$('#trProfRk');
    if(pv){ pv.textContent=ME.initial; rkPaintAv(pv, ME.rank) }
    if(pn)pn.textContent=ME.name;
    if(pr)pr.outerHTML=rkChip(ME.rank).replace('class="rk','id="trProfRk" class="rk');
    bioPaint();
    tpLoad(tpMine(),tpRepaint);   /* 온도·수명주기를 받아 오면 카드 세 장만 다시 채운다 */
    if(HAS_A){
      aAnimate($$('#trBody .tpCard, #trBody .tpPickWrap'),
        {opacity:[0,1],translateY:[16,0],duration:720,delay:aStagger(52),ease:'out(3)'});
      /* 살/말 비율 막대 — 인라인 폭을 목표값으로 기억해 두고 0 에서 채운다 */
      /* 사이드바가 66→236px 로 열리는 동안에는 본문 폭이 매 프레임 바뀐다.
         그때 % 폭을 함께 굴리면 프레임마다 레이아웃이 다시 잡혀 뚝뚝 끊긴다.
         탭에 막 들어온 참이면 그 전환이 끝난 뒤에 채우기 시작한다. */
      const since=Date.now()-(window.__trEnterAt||0);
      smBarFill($$('#trBody .smBar i'),
        {duration:920,step:44,start:Math.max(300,780-since)});
      /* 취향 태그 · 로직 칩도 순서대로 */
      aAnimate($$('#trBody .tpTasteTags button, #trBody .tpSignalList span'),
        {opacity:[0,1],scale:[.9,1],duration:520,delay:aStagger(36,{start:420}),
         ease:aSpring({stiffness:120,damping:14})});
    }
  }

  else if(id==='report'){
    /* ★ 2026-09-17 실데이터로 바꾼 칸
         · 기간 — 오늘 날짜로 이번 주(월~일)를 계산
         · 한 줄 요약 · 히어로 · 추천 영상 · 웹매거진 — 이번 주 가장 많이 검색한 키워드(없으면 첫 관심 스타일)
         · 히어로 지표 — /api/lifecycle 의 트렌드 온도 · 7일 전 대비 · 수명주기 단계
         · 지표 4칸 · 요일별 활동 · 취향 지분(검색한 스타일만) — /api/auth/weekly-report
         · 같이 지켜볼 스타일 — 스타일 10종의 /api/lifecycle 단계 · 온도로 고른다
       WK 에서 아직 쓰는 것은 갱신 요일뿐이다. 추천 웹매거진은 /api/v1/magazines(웹 검색). */
    const mine=tpMine();
    const fallback=mine[0]||STYLES[0];   /* 이번 주 검색 기록이 없을 때만 쓴다 */
    const rp=wkRange();
    WR={state:'loading',data:null,reason:''}; WKEY=null;

    body.innerHTML='<div class="wkReport" id="wkReport">'+
      /* ── 한 줄 요약 — 이번 주 가장 많이 검색한 키워드가 리포트의 축이다 ── */
      '<div class="wkLine" id="wkLine">'+wkLineHTML(null,rp)+'</div>'+
      /* ── 키워드 히어로 (키워드가 정해지면 wkActivityLoad 가 채운다) ── */
      '<section class="wkHero" id="wkHero">'+wkHeroHTML(null)+'</section>'+
      /* ── 지표 4칸 — 실제로 셀 수 있는 로그만 (/api/auth/weekly-report) ── */
      '<section class="wkMetrics" id="wkMetrics">'+wkMetricsHTML()+'</section>'+
      /* ── 요일별 활동 · 취향 지분 ── */
      '<section class="wkG2">'+
        '<article class="wkCard" id="wkDaysCard">'+wkDaysHTML()+'</article>'+
        '<article class="wkCard" id="wkTasteCard">'+wkTasteHTML()+'</article>'+
      '</section>'+
      /* ── 추천 영상 · 웹매거진 — 지어낸 기사가 아니라, 실제 검색 결과로 바로 연결한다 ── */
      '<section class="wkG2 wkG2b">'+
        '<article class="wkCard">'+
          '<div class="wkCardHead"><h3>이번 주 추천 영상</h3><em id="wkVideoBadge">취향 분석 중</em></div>'+
          '<div id="wkVideoRec"><div class="wkVideoLoading"><i></i><span>이번 주 관심 키워드로<br>콘텐츠 DB를 찾고 있습니다.</span></div></div>'+
        '</article>'+
        '<article class="wkCard" id="wkMagCard">'+wkMagHTML(null)+'</article>'+
      '</section>'+
      /* ── 같이 지켜볼 만한 스타일 ── */
      '<section class="wkCard" style="margin-top:10px">'+
        '<div class="wkCardHead"><h3>같이 지켜볼 만한 스타일</h3><em>HOT NOW</em></div>'+
        '<div class="wkNextGrid" id="wkNextGrid">'+wkNextHTML({id:null})+'</div>'+
      '</section>'+
      '<div class="wkFoot">'+
        '<span>FEEDiT · FASHION TREND ANALYSIS &amp; RECOMMENDATION CONSULTING</span>'+
        '<span>PERSONAL REPORT · '+rp[1]+' / '+rp[0]+'</span>'+
      '</div>'+
    '</div>';
    wkAnimate();
    /* 활동 기록을 받으면 키워드를 정하고 한 줄 요약 · 히어로 · 지표 · 영상 · 웹매거진을 채운다 */
    wkActivityLoad(fallback,rp);
    /* 스타일 10종의 온도 · 수명주기를 받아 오면 '같이 지켜볼 스타일'만 다시 채운다 */
    tpLoad(STYLES,()=>{
      const g=$('#wkNextGrid'); if(g)g.innerHTML=wkNextHTML(WKEY&&WKEY.style||{id:null});
    });
  }
  else if(id==='saved'){ svRender(body) }
  /* ══════════════ 언급량 · 온도 ══════════════
     결론(지금 얼마나 뜨거운가)을 맨 위에 놓고 근거를 아래에 깐다.
     값: /api/trend → analysis.term_metric_daily (전체 합산 행 · 플랫폼별 행) */
  else if(id==='temp'){
    const kw=KW.q;

    /* ★ 실값만 그린다. 받아 오는 동안에는 숫자를 지어내지 않고 '불러오는 중'을 적는다. */
    const st=stateOf(kw), S=summaryOf(kw);
    if(st.status==='unknown'){ body.innerHTML=trLoading('‘'+trEsc(kw)+'’ 의 지표를'); return; }
    if(st.status==='empty'||st.status==='error'){
      body.innerHTML=unavailableHTML(st.reason,
        st.detail || (st.status==='error'?'연결이 되면 자동으로 실제 값이 뜹니다.':''));
      return;
    }
    if(st.status==='ok' && (!S || S.temp===null)){
      body.innerHTML=unavailableHTML(
        '‘'+kw+'’ 의 트렌드 온도가 아직 계산되지 않았습니다.',
        (S&&S.missing.length)?('비어 있는 값: '+S.missing.join('·')):'');
      return;
    }

    const E=entryOf(kw), ED=(E&&E.data)||{};
    const temp=S?Math.round(S.temp):0;
    const share=S&&S.share!=null?+S.share.toFixed(1):null;
    const yoy=S?(S.yoyPct===null?null:Math.round(S.yoyPct)):null;
    const wk=S?(S.tempWk===null?null:Math.round(S.tempWk)):null;
    const nOr=v=>v===null||v===undefined?'–':v;   /* 없는 값은 대시로 */
    const newKw=(ED.new_terms||[]).filter(x=>x.term!==kw)[0]||null;
    const plats=(ED.platforms||[]).filter(p=>p.temp!=null);
    const band=temp>=85?0:temp>=65?1:temp>=40?2:3;
    /* 색은 가장 낮은 구간에서 시작해 최종 구간까지 걸어 올라간다 */
    const RAMP=['#3d7fd6','#c98a1b','#1f9e6e','#b23b3b'].slice(0,4-band);
    const BAND=[['#b23b3b','과열','이미 정점을 지나는 신호가 섞여 있습니다. 지금부터는 식는 속도를 지켜볼 구간입니다.'],
                ['#1f9e6e','뜨거움','언급량이 꾸준히 오르는 중입니다. 지금 붙잡을 만한 온도입니다.'],
                ['#c98a1b','달아오르는 중','막 올라오기 시작한 단계입니다. 조금 더 지켜보면 방향이 뚜렷해집니다.'],
                ['#3d7fd6','아직 잠잠','절대 언급량이 적어 판단하기엔 이릅니다. 추적만 걸어두는 편이 안전합니다.']][band];
    body.innerHTML=
      '<div class="verdict" style="--sc:'+BAND[0]+'">'+
        '<div class="dial"><svg viewBox="0 0 120 120">'+
          '<circle class="trk" cx="60" cy="60" r="50"/>'+
          '<circle class="val" cx="60" cy="60" r="50" data-ramp="'+RAMP.join(',')+'" data-score="'+temp+'" '+
            'stroke-dasharray="314.16" stroke-dashoffset="314.16"/></svg>'+
          '<span class="num"><b data-count="'+temp+'">0</b><small>트렌드 온도 °</small></span></div>'+
        '<div class="vdTx">'+
          '<h4><b>'+trEsc(kw)+'</b>'+josa(kw,'은','는')+' 지금 <em>'+BAND[1]+'</em> 구간 — 온도 '+temp+'°</h4>'+
          '<p>'+BAND[2]+'</p>'+
          '<div class="vdBand">'+['차가움','미지근','따뜻함','과열'].map((s,i)=>'<div'+(i===(3-band)?' class="on"':'')+
            '><span>'+s+'</span></div>').join('')+'</div>'+
          '<div class="vdMeta">'+
            '<div><b>'+(wk===null?'–':(wk>0?'+':'')+wk)+(wk===null?'':'°')+'</b>'+
              '<span>이번 주 온도 변화'+(wk===null?' (자료 부족)':'')+'</span></div>'+
            '<div><b>'+(S.level==null?'–':Math.round(S.level))+'</b><span>화제성 레벨</span></div>'+
            '<div><b>'+(S.momentum==null?'–':Math.round(S.momentum))+'</b><span>성장 모멘텀 (50=보합)</span></div>'+
          '</div>'+
        '</div></div>'+
      '<div class="note" style="margin:0 0 12px"><i>◆</i>'+
          S.asOf+' 기준 · 관측 '+S.points+'일'+
          (S.thin?' — 자료가 짧아 변화값은 참고만 하세요':'')+'</div>'+
      '<div class="kpis" style="grid-template-columns:repeat(3,minmax(0,1fr))">'+kpi('플랫폼 점유율',nOr(share),share===null?'':'%',
              share===null?'아직 계산 전':'같은 날 전체 언급 중 비중',1)+
        kpi('전년 동기 대비',yoy===null?'–':(yoy>0?'+':'')+yoy,yoy===null?'':'%',
              yoy===null?'1년치가 모여야 나옵니다':'같은 날 언급량 차이',yoy===null||yoy>=0?1:0)+
        kpi('신규 진입 키워드',newKw?trEsc(newKw.term):'–','',newKw?'최근 7일 새로 감지 · '+Math.round(newKw.temp||0)+'°':'최근 7일 새로 잡힌 말 없음',1)+'</div>'+
      '<div class="trGrid">'+
        '<div class="panelC"><div class="gHead"><h3>언급량 · 온도 추이</h3></div>'+
          '<div data-chart="tempMain"></div>'+
          '<div class="note"><i>◆</i>언급량(최대=100 지수)과 트렌드 온도를 나란히 겹쳐 봅니다.</div></div>'+
        '<div class="panelC"><div class="ph"><h3>플랫폼별 온도</h3><em>0–100</em></div>'+
          (plats.length
            ? '<table class="mTable"><tr><th>플랫폼</th><th></th><th>온도</th></tr>'+
              plats.map(t=>{const v=Math.round(t.temp);
                return '<tr><td>'+(v>=85?'<b>'+trEsc(t.name)+'</b>':trEsc(t.name))+'</td>'+
                '<td><span class="bar" style="display:block"><i class="'+(v>=85?'c':'')+'" style="width:'+v+'%"></i></span></td>'+
                '<td class="n '+(v>=65?'up':'dn')+'">'+v+'°</td></tr>'}).join('')+
              '</table><div class="note"><i>◆</i>플랫폼마다 온도차가 있다면 아직 확산 초반 구간입니다.</div>'
            : unavailableHTML('플랫폼별 지표 행이 아직 없습니다.','전체 합산 행만 적재돼 있습니다.'))+
        '</div>'+
      '</div>';
    /* ★ term 을 넘겨야 실데이터를 본다. field 는 API 가 돌려주는 열 이름이다 — mention(언급량) · temp(온도). */
    G_CFG.tempMain={key:kw+'temp',term:kw,min:0,max:100,
      sets:[{id:'m',name:'언급량 지수',field:'mention',index:true,unit:''},
            {id:'t',name:'트렌드 온도 (°)',field:'temp',unit:'°',accent:1}]};
    gChart('[data-chart="tempMain"]',G_CFG.tempMain); trDial(); trFillBars();
  }
  /* ══════════════ 연관어 ══════════════
     값: /api/assoc → analysis.term_assoc_daily (lift · PMI · 백분위 · 순위) + 근거 문장 */
  else if (id === 'assoc') {
    const kw = KW.q;
    const A = editGate(body, '/api/assoc?term=' + encodeURIComponent(kw), '‘' + trEsc(kw) + '’ 의 연관어를');
    if (!A) return;
    const AX_ORDER = ['아이템', '소재', '색', '디테일', 'TPO', '스타일', '브랜드', '인물'];
    const groups = {};
    (A.items || []).forEach(it => { const c = it.facet_ko || it.facet; (groups[c] = groups[c] || []).push(it) });
    const cats = AX_ORDER.filter(c => groups[c]).concat(Object.keys(groups).filter(c => AX_ORDER.indexOf(c) < 0));
    /* PMI 상위 10개 + 동시출현 상위 10개의 합집합 → 두 정렬 모두에서 의미 있는 항목을 보존 */
    cats.forEach(c => {
      const all = groups[c];
      if (all.length <= 10) return;
      const byPmi = all.slice(0, 10);
      const byCooc = all.slice().sort((a, b) => (b.cooccurrence || 0) - (a.cooccurrence || 0)).slice(0, 10);
      const seen = new Set();
      const merged = [];
      byPmi.concat(byCooc).forEach(it => {
        const k = it.term;
        if (!seen.has(k)) { seen.add(k); merged.push(it); }
      });
      groups[c] = merged;
    });
    const ALL = cats.reduce((a, c) => a.concat(groups[c]), []);
    if (!ALL.length) {
      body.innerHTML = unavailableHTML('‘' + kw + '’ 의 연관어가 아직 없습니다.', '함께 언급된 문서가 모자랍니다.');
      return;
    }
    const MAX_TAGS = 50; /* 축 5개 × 축당 최대 10개 */
    const density = Math.min(100, Math.round(ALL.length / MAX_TAGS * 100));
    const strength = a => a.percentile != null ? a.percentile : (a.lift != null ? a.lift * 10 : a.cooccurrence);
    const topTag = ALL.slice().sort((a, b) => strength(b) - strength(a))[0];
    const catTotals = cats.map(c => [c, groups[c].reduce((s, a) => s + (a.cooccurrence || 0), 0)]);
    const topCat = catTotals.slice().sort((a, b) => b[1] - a[1])[0][0];
    const newCnt = ALL.filter(a => a.change === 'new').length;
    const band = ALL.length >= 38 ? 0 : ALL.length >= 25 ? 1 : ALL.length >= 13 ? 2 : 3;
    const RAMP = ['#b23b3b', '#c98a1b', '#3d7fd6', '#1f9e6e'].slice(0, 4 - band);
    const BAND = [['#1f9e6e', '폭발적 확산', '여러 축에 걸쳐 연관어가 최대치에 가깝게 쌓였습니다. 소비자 언어가 이미 풍부하게 형성된 상태입니다.'],
    ['#3d7fd6', '활발한 확산', '연관어가 절반 이상 채워졌습니다. 축마다 고르게 늘고 있는지 확인해볼 때입니다.'],
    ['#c98a1b', '완만한 확산', '연관어가 서서히 쌓이고 있지만 아직 절반에 못 미칩니다. 확산 초반 구간입니다.'],
    ['#b23b3b', '정체', '연관어 수가 아직 적어 판단하기엔 이릅니다. 소재가 한정적으로 소비되고 있을 가능성이 있습니다.']][band];
    const badgeHtml = ch => ch === 'new' ? '<span class="axChg up">NEW</span>' :
      ch == null ? '' : ch > 0 ? '<span class="axChg up">▲' + ch + '</span>' : ch < 0 ? '<span class="axChg">▼' + Math.abs(ch) + '</span>' :
        '<span class="axChg">–</span>';
    body.innerHTML =
      '<div class="verdict" style="--sc:' + BAND[0] + '">' +
      '<div class="dial"><svg viewBox="0 0 120 120">' +
      '<circle class="trk" cx="60" cy="60" r="50"/>' +
      '<circle class="val" cx="60" cy="60" r="50" data-ramp="' + RAMP.join(',') + '" data-score="' + density + '" ' +
      'stroke-dasharray="314.16" stroke-dashoffset="314.16"/></svg>' +
      '<span class="num"><b data-count="' + density + '">0</b><small>연관어 포화도 %</small></span></div>' +
      '<div class="vdTx">' +
      '<h4><b>' + trEsc(kw) + '</b>' + josa(kw, '은', '는') + ' 지금 <em>' + BAND[1] + '</em> 단계입니다.</h4>' +
      '<p>' + BAND[2] + '</p>' +
      '<div class="vdBand">' + ['정체', '완만', '활발', '폭발'].map((s, i) => '<div' + (i === (3 - band) ? ' class="on"' : '') +
        '><span>' + s + '</span></div>').join('') + '</div>' +
      '<div class="vdMeta">' +
      '<div><b>' + ALL.length + '건</b><span>연관어 총량</span></div>' +
      '<div><b>' + newCnt + '건</b><span>신규 연관어</span></div>' +
      '<div><b>' + trEsc(A.as_of) + '</b><span>기준일</span></div>' +
      '</div>' +
      '</div></div>' +
      '<div class="kpis" style="grid-template-columns:repeat(3,minmax(0,1fr))">' +
      kpi('최다 연관어', trEsc(topTag.term), '',
        topTag.lift != null ? 'lift ' + topTag.lift.toFixed(2) + (topTag.percentile != null ? ' · 상위 ' + Math.max(1, Math.round(100 - topTag.percentile)) + '%' : '') : '동시 언급 ' + topTag.cooccurrence + '건', 1) +
      kpi('가장 뜨거운 축', trEsc(topCat), '', '축별 동시 언급 문서 합산 1위', 1) +
      kpi('축당 평균 다양성', (ALL.length / cats.length).toFixed(1), '개', '핵심 연관어 수', 1) + '</div>' +
      '<div class="trGrid">' +
      '<div class="panelC"><div class="gHead"><h3>연관어 수 추이</h3></div>' +
      '<div data-chart="assocMain"></div>' +
      '<div class="note"><i>◆</i>연관어 수가 온도보다 먼저 꺾이면 화제성은 남았지만 다양성이 좁아지고 있다는 신호입니다.</div></div>' +
      '<div class="panelC"><div class="ph"><h3>축별 비중</h3><em>KEYWORDS</em></div>' +
      '<table class="mTable"><tr><th>축</th><th></th><th>키워드 수</th></tr>' +
      catTotals.map(c => {
        const cnt = groups[c[0]].length;
        const pct = Math.round(cnt / ALL.length * 100);
        return '<tr><td>' + (c[0] === topCat ? '<b>' + trEsc(c[0]) + '</b>' : trEsc(c[0])) + '</td>' +
          '<td><span class="bar" style="display:block"><i class="' + (c[0] === topCat ? 'c' : '') + '" style="width:' + Math.min(100, pct * 2) + '%"></i></span></td>' +
          '<td class="n">' + cnt + '개</td></tr>'
      }).join('') +
      '</table><div class="note"><i>◆</i>축 하나에 몰릴수록 유행이 아니라 단일 아이템 소비일 확률이 높습니다.</div></div>' +
      '</div>' +
      '<div class="assocGrid" style="margin-top:12px">' +
      cats.map((cat, ci) => {
        const arr = groups[cat];
        const max = Math.max.apply(null, arr.map(a => a.cooccurrence || 0)) || 1;
        return '<div class="panelC" data-cat="' + trEsc(cat) + '" data-ci="' + ci + '">' +
          '<div class="axHead">' +
          '<span class="dot"></span><h3>' + trEsc(cat) + '</h3>' +
          '<div class="axSortToggle">' +
          '<button class="axSortBtn on" data-sort="pmi" data-ci="' + ci + '">특징순</button>' +
          '<button class="axSortBtn" data-sort="cooc" data-ci="' + ci + '">언급량순</button>' +
          '</div>' +
          '</div>' +
          '<div class="axList" data-ci="' + ci + '">' + arr.map((a, ai) => {
            const pct = Math.round((a.cooccurrence || 0) / max * 100);
            return '<button class="axRow' + (ai === 0 ? ' top' : '') + '" data-ci="' + ci + '" data-ai="' + ai + '">' +
              '<span class="axNum">' + (ai + 1) + '</span>' +
              '<span class="axName">' + trEsc(a.term) + '</span>' +
              '<span class="axBar"><i class="' + (ai === 0 ? 'c' : '') + '" style="width:' + pct + '%"></i></span>' +
              badgeHtml(a.change) +
              '</button>'
          }).join('') +
          '</div></div>'
      }).join('') + '</div>';
    /* ── 클라이언트 사이드 정렬용 데이터 저장 ── */
    window._assocGroups = groups;
    window._assocCats = cats;
    window._assocBadgeHtml = badgeHtml;

    G_CFG.assocMain={key:kw+'assoc',term:kw,rows:A.history||[],
      emptyReason:'연관어 적재 이력이 아직 없습니다.',
      sets:[{id:'a',name:'연관어 수',field:'count',unit:'개'}]};
    gChart('[data-chart="assocMain"]', G_CFG.assocMain); trDial();

    /* ── 각 카테고리 토글 클릭 핸들러 ── */
    $$('#trBody .axSortBtn').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        const ci = +btn.dataset.ci;
        const sort = btn.dataset.sort;
        const cat = window._assocCats[ci];
        const grps = window._assocGroups;
        const badge = window._assocBadgeHtml;
        if (!cat || !grps[cat]) return;

        /* 토글 버튼 활성 상태 변경 (같은 카테고리 내에서만) */
        const panel = btn.closest('.panelC');
        panel.querySelectorAll('.axSortBtn').forEach(b => {
          b.classList.toggle('on', b === btn);
        });

        /* 정렬: pmi=기존 association_rank 순, cooc=동시출현 횟수 내림차순 */
        const arr = grps[cat].slice();
        if (sort === 'cooc') {
          arr.sort((a, b) => (b.cooccurrence || 0) - (a.cooccurrence || 0));
        } else {
          arr.sort((a, b) => {
            const ra = a.rank != null ? a.rank : 999999;
            const rb = b.rank != null ? b.rank : 999999;
            if (ra !== rb) return ra - rb;
            return (b.pmi || 0) - (a.pmi || 0);
          });
        }

        /* 해당 카테고리의 axList만 다시 그리기 (페이지 초기화 없음) */
        const list = panel.querySelector('.axList');

        const max = Math.max.apply(null, arr.map(a => a.cooccurrence || 0)) || 1;
        list.innerHTML = arr.map((a, ai) => {
          const pct = Math.round((a.cooccurrence || 0) / max * 100);
          return '<button class="axRow' + (ai === 0 ? ' top' : '') + '" data-ci="' + ci + '" data-ai="' + ai + '">' +
            '<span class="axNum">' + (ai + 1) + '</span>' +
            '<span class="axName">' + trEsc(a.term) + '</span>' +
            '<span class="axBar"><i class="' + (ai === 0 ? 'c' : '') + '" style="width:' + pct + '%"></i></span>' +
            (badge ? badge(a.change) : '') +
            '</button>';
        }).join('');

        /* 정렬된 데이터 기준으로 groups 업데이트 (팝업에서도 맞게) */
        grps[cat] = arr;

        /* 새로 그린 버튼에 팝업 핸들러 다시 연결 */
        list.querySelectorAll('.axRow').forEach(row => {
          row.addEventListener('click', ev => {
            ev.stopPropagation();
            const a2 = grps[cat][+row.dataset.ai];
            const stat2 = [a2.lift != null ? 'lift ' + a2.lift.toFixed(2) : '', a2.pmi != null ? 'PMI ' + a2.pmi.toFixed(2) : '',
            '동시 언급 ' + (a2.cooccurrence || 0) + '건'].filter(Boolean).join(' · ');
            assocOpenPop(row, cat, {
              n: a2.term, spark: null,
              src: [{ tag: '지표', text: stat2 }].concat(a2.evidence || [])
            });
          });
        });
      });
    });

    /* ── 기존 axRow 클릭 → 팝업 핸들러 ── */
    $$('#trBody .axList .axRow').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        const cat = cats[+btn.dataset.ci];
        const a = groups[cat][+btn.dataset.ai];
        const stat = [a.lift != null ? 'lift ' + a.lift.toFixed(2) : '', a.pmi != null ? 'PMI ' + a.pmi.toFixed(2) : '',
        '동시 언급 ' + (a.cooccurrence || 0) + '건'].filter(Boolean).join(' · ');
        assocOpenPop(btn, cat, {
          n: a.term, spark: null,
          src: [{ tag: '지표', text: stat }].concat(a.evidence || [])
        });
      });
    });
  }
  /* ══════════════ 긍부정 ══════════════
     "사려는 사람이 많은가 · 망설이게 하는 게 뭔가"를 결론 카드로 먼저 답한다.
     값: /api/trend 의 긍정·부정 비율, 반응 유형 건수, 구매의향 지수(purchase_intent_index) */
  else if(id==='sentiment'){
    const kw=KW.q;
    const sentUrl=sentimentUrl(kw,KW.f);
    const st=stateOfUrl(sentUrl);
    if(st.status==='unknown'){ body.innerHTML=trLoading('‘'+trEsc(kw)+'’ 의 긍부정 지표를'); return; }
    if(st.status==='empty'||st.status==='error'){
      body.innerHTML=unavailableHTML(st.reason,
        st.detail || (st.status==='error'?'연결이 되면 자동으로 실제 값이 뜹니다.':''));
      return;
    }
    const D=st.data||{}, rows=Array.isArray(D.series)?D.series:[];
    const last=rows[rows.length-1]||{};
    /* '계산이 안 됐다'와 '계산했는데 분류된 반응이 0건이다'는 다른 말이다.
       행은 있는데 긍정·중립·부정·의도 건수가 전부 0 이면 그렇게 적는다. */
    const CNT=['pos_n','neu_n','neg_n','question_n','purchase_n','experience_n','praise_n','critique_n','chitchat_n'];
    const anyCount=rows.some(r=>CNT.some(f=>(+r[f]||0)>0));
    if(last.intent==null && last.pos_rate==null && !anyCount){
      const counted=rows.some(r=>CNT.some(f=>r[f]!=null));
      body.innerHTML=counted
        ? unavailableHTML('‘'+kw+'’ 에 분류된 반응이 아직 0건입니다.',
            '지표 행('+trEsc(last.date)+' 기준)은 있지만 긍정·중립·부정, 질문·구매·경험·호평·비판·잡담이 모두 0 입니다.<br>'+
            '댓글·리뷰 반응 분류가 이 용어에 붙으면 채워집니다.')
        : unavailableHTML('‘'+kw+'’ 의 긍부정·구매의향 지표가 아직 계산되지 않았습니다.',
            '반응 분류(긍정·부정·의도) 적재가 돌면 채워집니다.');
      return;
    }
    const recent=rows.filter(r=>trDayDiff(r.date,last.date)<28);
    const sum=f=>recent.reduce((a,r)=>a+(+r[f]||0),0);
    /* 신호 유형 = analysis.term_metric_daily 의 의도(intent) 칸 6개 그대로.
         question_count · purchase_count · experience_count · praise_count · critique_count · chitchat_count
       순서는 DB 칸 순서로 고정한다(건수로 줄 세우면 날마다 자리가 바뀌어 비교가 안 된다).
       0건도 지우지 않고 0 으로 보여 준다 — '없었다'도 결과다.
       [이름, 최근 28일 건수, 극성(1 긍정 계열 · 0 중립 · -1 부정 계열)] */
    const SIG_ALL=[['질문',sum('question_n'),0],['구매',sum('purchase_n'),1],['경험',sum('experience_n'),1],
                   ['호평',sum('praise_n'),1],['비판',sum('critique_n'),-1],['잡담',sum('chitchat_n'),0]];
    /* 응답에 의도 칸이 아예 없으면(예전 API) 0 으로 채워 보여 주지 않는다 */
    const hasIntent=recent.some(r=>['question_n','purchase_n','experience_n','praise_n','critique_n','chitchat_n']
      .some(f=>r[f]!=null));
    const SIG=hasIntent&&SIG_ALL.some(x=>x[1]>0)?SIG_ALL:[];
    const total=sum('pos_n')+sum('neu_n')+sum('neg_n');
    const byCount=SIG.filter(x=>x[1]>0).slice().sort((a,b)=>b[1]-a[1]);
    const topPos=byCount.find(x=>x[2]>0), topNeg=byCount.find(x=>x[2]<0);
    /* ── 판정 기준 ──
       ① 구매의향 지수(purchase_intent_index)가 있으면 그 값을 그대로 쓴다.
       ② 없으면 '긍정 비율'로 대신하지 않는다.
          긍정 비율은 중립까지 분모에 들어가서, 긍정 3 · 중립 3 · 부정 0 이 50% → '팽팽'으로 잘못 판정됐다.
          대신 긍정과 부정만 맞대 본 '긍정 우위' = 긍정 ÷ (긍정+부정) × 100 (최근 28일 합)을 쓴다.
       ③ 최근 28일 반응이 SENT_MIN_N 건 미만이면 판정하지 않는다. 몇 건으로 '강한 신호'라 말하지 않는다. */
    const SENT_MIN_N=20;
    const posS=sum('pos_n'), neuS=sum('neu_n'), negS=sum('neg_n');
    const pct=(v)=>total>0?Math.round(v/total*100):null;
    const posPct=total>0?pct(posS):(last.pos_rate!=null?Math.round(last.pos_rate):null);
    const negPct=total>0?pct(negS):(last.neg_rate!=null?Math.round(last.neg_rate):null);
    const score=last.intent!=null?Math.round(last.intent):null;
    const lead=(posS+negS)>0?Math.round(posS/(posS+negS)*100):null;
    const thin=score==null&&(total<SENT_MIN_N||lead==null);
    const dialV=score!=null?score:(lead!=null?lead:0);
    const band=thin?-1:dialV>=75?0:dialV>=55?1:dialV>=35?2:3;
    const RAMP=thin?['#9a968f']:['#b23b3b','#c98a1b','#3d7fd6','#1f9e6e'].slice(0,4-band);
    const BAND=thin
      ? ['#9a968f','판단 보류',
         '최근 28일 반응이 '+total.toLocaleString()+'건뿐이라 판정하기엔 자료가 적습니다.<br>'+
         '긍정 '+posS+' · 중립 '+neuS+' · 부정 '+negS+'건입니다. '+SENT_MIN_N+'건 이상 모이면 판정합니다.']
      : [['#1f9e6e','강한 구매 신호','긍정 신호가 압도적입니다. 지금 재고·물량을 걱정할 시점입니다.'],
         ['#3d7fd6','구매 신호 우세','긍정 쪽이 앞서 있습니다. 부정 신호가 늘지 않는지만 함께 지켜보세요.'],
         ['#c98a1b','팽팽한 신호','긍정과 부정이 비슷하게 맞섭니다. 부정 신호의 종류를 먼저 확인해야 합니다.'],
         ['#b23b3b','구매 저해 신호 우세','부정 신호가 앞섭니다. 가격·실물 관련 이슈부터 해소돼야 반등합니다.']][band];
    const dialLabel=score!=null?'구매의향 지수':'긍정 우위 %';
    const maxSig=Math.max(1,...SIG.map(x=>x[1]));
    body.innerHTML=
      '<div class="verdict" style="--sc:'+BAND[0]+'">'+
        '<div class="dial"><svg viewBox="0 0 120 120">'+
          '<circle class="trk" cx="60" cy="60" r="50"/>'+
          '<circle class="val" cx="60" cy="60" r="50" data-ramp="'+RAMP.join(',')+'" data-score="'+dialV+'" '+
            'stroke-dasharray="314.16" stroke-dashoffset="314.16"/></svg>'+
          '<span class="num"><b data-count="'+dialV+'">0</b><small>'+(dialV===0&&lead==null&&score==null?'–':dialLabel)+'</small></span></div>'+
        '<div class="vdTx">'+
          (thin
            ? '<h4><b>'+trEsc(kw)+'</b>'+josa(kw,'은','는')+' 아직 <em>'+BAND[1]+'</em>입니다.</h4>'
            : '<h4><b>'+trEsc(kw)+'</b>'+josa(kw,'은','는')+' 지금 <em>'+BAND[1]+'</em>입니다.</h4>')+
          '<p>'+BAND[2]+'</p>'+
          '<div class="vdBand">'+['저해우세','팽팽','우세','강한신호'].map((s,i)=>'<div'+(!thin&&i===(3-band)?' class="on"':'')+
            '><span>'+s+'</span></div>').join('')+'</div>'+
          '<div class="vdMeta">'+
            '<div><b>'+(posPct==null?'–':posPct+'%')+'</b><span>긍정 반응 비율 · 28일</span></div>'+
            '<div><b>'+(negPct==null?'–':negPct+'%')+'</b><span>부정 반응 비율 · 28일</span></div>'+
            '<div><b>'+trEsc(last.date)+'</b><span>기준일</span></div>'+
          '</div>'+
        '</div></div>'+
      '<div class="kpis" style="grid-template-columns:repeat(3,minmax(0,1fr))">'+
        kpi('총 반응 수',total.toLocaleString(),'건','최근 28일 · '+trEsc(D.scope_label||'용어 직접 언급'),1)+
        kpi('최다 긍정 신호',topPos?topPos[0]:'–','',topPos?topPos[1].toLocaleString()+'건':'아직 없음',1)+
        kpi('최다 부정 신호',topNeg?topNeg[0]:'–','',topNeg?topNeg[1].toLocaleString()+'건':'아직 없음',0)+'</div>'+
      '<div class="trGrid" style="align-items:start">'+
        '<div class="panelC" id="sentChartCard"><div class="gHead"><h3>긍정 · 중립 · 부정 반응 비중</h3></div>'+
          '<div data-chart="sentMain"></div>'+
          '<div class="note"><i>◆</i>기준일로부터 최근 7일(주별) · 30일(월별) 반응을 합쳐 긍정·중립·부정 비중으로 나눈 값입니다.</div></div>'+
        '<div class="panelC" id="sentSigCard"><div class="ph"><h3>신호 유형별 건수</h3><em>최근 28일</em></div>'+
          '<div class="sigWrap" id="sigWrap">'+(SIG.length
          ? '<table class="mTable"><tr><th>신호</th><th></th><th>건수</th></tr>'+
            SIG.map(p=>'<tr data-sig="'+p[0]+'" style="cursor:pointer"><td>'+p[0]+'</td>'+
              '<td><span class="bar" style="display:block"><i class="'+(p[2]>0?'c':'')+'" style="width:'+Math.round(p[1]/maxSig*100)+'%"></i></span></td>'+
              '<td class="n '+(p[2]>0?'up':p[2]<0?'dn':'')+'">'+p[1].toLocaleString()+'</td></tr>').join('')+'</table>'
          : unavailableHTML('반응 유형(질문·구매·경험·호평·비판·잡담) 건수가 아직 없습니다.',''))+'</div>'+
          '<button class="sigMore" id="sigMoreBtn" type="button" hidden>+ 더보기</button>'+
          '<div class="note"><i>◆</i>주황이 긍정 계열(구매·경험·호평), 검정이 중립(질문·잡담)·부정(비판) 계열입니다.</div></div>'+
      '</div>';
    /* 날짜별 막대 → 기간 통합 원형(파이) 차트. 주별 = 최근 7일 합, 월별 = 최근 30일 합 (기준일 포함) */
    /* G_CFG 에 올리지 않는다 — gMount 가 선·막대 엔진(gChart)으로 다시 그리면 원형이 사라진다 */
    sentPie($('[data-chart="sentMain"]'),{key:kw+'sent',rows:rows,lastDate:last.date}); trDial(); trFillBars();
    sentFitSignals();   /* 왼쪽 차트 카드 높이에 맞춰 넘치는 신호 목록을 접고 '+더보기' 로 연다 */
    /* 신호 행 클릭 → 해당 유형의 실제 근거 문장 */
    const intentMap={'질문':'QUESTION','구매':'PURCHASE','경험':'EXPERIENCE',
      '호평':'PRAISE','비판':'CRITIQUE','잡담':'CHITCHAT'};
    $$('#sigWrap tr[data-sig]').forEach(row=>{
      row.addEventListener('click',e=>{
        e.stopPropagation();
        const intent=intentMap[row.dataset.sig];
        const evList=(D.evidence||{})[intent]||[];
        assocOpenPop(row,'긍부정 신호',{
          n:row.dataset.sig,spark:null,
          src:evList.length?evList:[{tag:'안내',text:'해당 신호로 분류된 최근 근거 문장이 없습니다.'}]
        });
      });
    });
  }
  /* ══════════════ 할인률 변화 ══════════════
     값: /api/discount → snapshot.product_source_snapshot (세부 검색 조건에 걸린 상품) + 대표 용어 온도 */
  else if(id==='stock'){
    const D=editGate(body,editUrl('stock'),'할인률 지표를'); if(!D)return;
    const full=D.label||fsItemFull();
    const O=D.overall||{}, TB=D.temperature||{}, TL=TB.latest||{};
    const disc=O.avg_discount!=null?Math.round(O.avg_discount):null;
    const temp=TL.temp!=null?Math.round(TL.temp):null;
    const dUp=D.change_2w;
    const rising=(dUp||0)>0;
    /* 점수 = 싸게 사는 정도(할인률) − 식어가는 정도(온도 낮음). 할인이 커도 온도가 죽었으면 좋은 매수가 아니다.
       두 값 중 하나라도 없으면 점수를 만들지 않는다. */
    const score=(disc==null||temp==null)?null:
      Math.max(4,Math.min(98,Math.round(disc*0.9+temp*0.45-(rising?dUp*1.1:0))));
    const dialV=score!=null?score:(disc||0);
    const band=dialV>=75?0:dialV>=55?1:dialV>=35?2:3;
    const RAMP=['#b23b3b','#e0642f','#c98a1b','#1f9e6e'].slice(0,4-band);
    const BAND=[['#1f9e6e','지금이 적기','할인이 충분히 붙었는데 트렌드 온도는 아직 살아 있습니다. 가격과 수요가 겹치는 구간입니다.'],
                ['#c98a1b','사도 괜찮음','나쁘지 않은 시점입니다. 다만 조금 더 기다리면 할인폭이 커질 여지가 남아 있습니다.'],
                ['#e0642f','조금 더 대기','할인은 시작됐지만 아직 초반입니다. 2~3주 뒤 재확인을 권합니다.'],
                ['#b23b3b','지금은 비추천','트렌드가 이미 식은 뒤에 붙는 할인입니다. 싸 보여도 오래 입지 못할 확률이 높습니다.']][band];
    const C=D.cheapest;
    const tempRows=(TB.series||[]).map(p=>({date:p.date,temp:p.temp}));
    const PCODE={'무신사':'musinsa','지그재그':'zigzag','에이블리':'ably'};

    if(TR_TAB==='통합'){
      body.innerHTML=
        (C?'<p class="cheapest"><b>'+trEsc(full)+'</b>'+josa(full,'은','는')+' 지금 <u>'+trEsc(C.name)+'</u>'+josa(C.name,'이','가')+' 가장 저렴합니다 '+
          '<s>'+trWon(C.min_list_price)+' → '+trWon(C.min_sale_price)+(C.min_discount!=null?' · '+C.min_discount+'% 할인':'')+'</s></p>':'')+
        '<div class="verdict" style="--sc:'+BAND[0]+'">'+
          '<div class="dial"><svg viewBox="0 0 120 120">'+
            '<circle class="trk" cx="60" cy="60" r="50"/>'+
            '<circle class="val" cx="60" cy="60" r="50" data-ramp="'+RAMP.join(',')+'" data-score="'+dialV+'" '+
              'stroke-dasharray="314.16" stroke-dashoffset="314.16"/></svg>'+
            '<span class="num"><b data-count="'+dialV+'">0</b><small>'+(score!=null?'구매 점수':'평균 할인률 %')+'</small></span></div>'+
          '<div class="vdTx">'+
            '<h4><b>'+trEsc(full)+'</b>'+josa(full,'은','는')+' 현재 <em>'+(dUp==null?'할인 추이 확인 중':rising?'할인 상승세':'할인 하락세')+'</em>입니다.<br>'+
              (score!=null?'트렌드 온도 '+temp+'°와 비교하면 — <em>'+BAND[1]+'</em>.':'대표 용어의 트렌드 온도가 없어 구매 점수는 계산하지 않았습니다.')+'</h4>'+
            '<p>'+(score!=null?BAND[2]:trEsc(TB.reason||''))+'</p>'+
            (score!=null?'<div class="vdBand">'+[0,1,2,3].map(i=>'<div'+(i===band?' class="on"':'')+'>'+
              '<span>'+['적기','양호','대기','비추천'][i]+'</span></div>').join('')+'</div>':'')+
            '<div class="vdMeta">'+
              '<div><b>'+(disc==null?'–':disc+'%')+'</b><span>현재 평균 할인률</span></div>'+
              '<div><b>'+(temp==null?'–':temp+'°')+'</b><span>트렌드 온도'+(TB.term?' · '+trEsc(TB.term):'')+'</span></div>'+
              '<div><b>'+(dUp==null?'–':(dUp>0?'+':'')+dUp+'%p')+'</b><span>최근 2주</span></div>'+
              '<div><b>'+trWon(O.min_sale_price)+'</b><span>최저가</span></div>'+
            '</div>'+
          '</div></div>'+
        '<div class="note" style="margin:0 0 12px"><i>◆</i>'+trEsc(String(D.as_of).slice(0,10))+' 기준 · 상품 '+O.products+'개 · 최근 '+D.days+'일 스냅샷</div>'+
        '<div class="kpis">'+kpi('할인 시작',D.first_discount_days==null?'–':'D+'+D.first_discount_days,'',
              D.first_discount_at?D.first_discount_at+' 처음 감지':'기간 내 할인 없음',0)+
          kpi('정가 유지 비율',O.full_price_pct==null?'–':Math.round(O.full_price_pct),O.full_price_pct==null?'':'%','할인 없이 파는 상품 비중',0)+
          kpi('최대 할인폭',D.max_discount_period==null?'–':Math.round(D.max_discount_period),D.max_discount_period==null?'':'%','최근 '+D.days+'일 최고',0)+
          kpi('재입고 횟수',D.restock_count,'회','품절 → 판매 전환 · 최근 '+D.days+'일',1)+'</div>'+
        '<div class="trGrid">'+
          '<div class="panelC"><div class="gHead"><h3>할인률 · 트렌드 온도</h3></div>'+
            '<div data-chart="stockMain"></div>'+
            '<div class="note"><i>◆</i>두 선이 벌어질수록 "식은 뒤 붙는 할인"입니다. '+
              '겹쳐 움직이면 아직 수요가 남아 있는 정상 세일입니다.</div></div>'+
          '<div class="panelC"><div class="ph"><h3>판매처별 최저가</h3><em>최신 스냅샷</em></div>'+
            '<table class="mTable xl"><tr><th>판매처</th><th>평균 할인률</th><th>최저가</th></tr>'+
            D.platforms.map((s,i)=>{const top=Math.max.apply(null,D.platforms.map(x=>x.avg_discount||0))||1;
              const bw=Math.round((s.avg_discount||0)/top*100);
              return '<tr><td>'+(i===0?'<b>'+trEsc(s.name)+'</b>':trEsc(s.name))+'</td>'+
                '<td class="n '+(i===0?'up':'dn')+'">'+(s.avg_discount==null?'–':s.avg_discount+'%')+
                  '<span class="bar" style="display:block;margin-top:7px"><i class="'+(i===0?'c':'')+'" style="width:'+bw+'%"></i></span></td>'+
                '<td class="n">'+trWon(s.min_sale_price)+'</td></tr>'}).join('')+'</table>'+
            '<div class="note"><i>◆</i>판매처마다 수집된 상품 수가 달라 평균 할인률은 참고용입니다.</div></div>'+
        '</div>';
      const rows=trMergeRows(D.series,tempRows);
      G_CFG.stockMain={key:full+'stock',rows,min:0,max:100,
        emptyReason:'할인률 또는 온도 시계열이 비어 있습니다.',
        sets:[{id:'d',name:'평균 할인률 (%)',field:'discount',unit:'%'}].concat(tempRows.length
          ?[{id:'t',name:'트렌드 온도 (°)',field:'temp',unit:'°',accent:1}]:[])};
    } else {
      /* ── 플랫폼별 세부 분석 ── */
      const P=D.platforms.find(p=>p.code===PCODE[TR_TAB]||p.name===TR_TAB);
      if(!P){
        body.innerHTML=unavailableHTML(TR_TAB+' 에서 이 조건의 상품이 수집되지 않았습니다.',
          '수집된 판매처: '+(D.platforms.map(p=>p.name).join(' · ')||'없음'));
        return;
      }
      const stock=Object.entries(P.stock||{});
      const stockMax=Math.max.apply(null,stock.map(x=>x[1]))||1;
      body.innerHTML=
        '<div class="kpis">'+kpi(TR_TAB+' 평균 할인률',P.avg_discount==null?'–':P.avg_discount,P.avg_discount==null?'':'%',
              (P.avg_discount!=null&&O.avg_discount!=null)?(P.avg_discount>O.avg_discount?'통합 평균보다 높음':'통합 평균보다 낮음'):'비교 불가',
              (P.avg_discount||0)>(O.avg_discount||0)?1:0)+
          kpi('판매 상품 수',P.products.toLocaleString(),'개','이 조건 기준',1)+
          kpi('품절 상품',P.sold_out,'개','최신 스냅샷 기준',0)+
          kpi('평균 평점',P.rating==null?'–':P.rating.toFixed(1),P.rating==null?'':'/5','리뷰 '+(P.reviews||0).toLocaleString()+'건',1)+'</div>'+
        '<div class="trGrid">'+
          '<div class="panelC"><div class="gHead"><h3>'+TR_TAB+' 할인률 추이</h3></div>'+
            '<div data-chart="stockPlat"></div>'+
            '<div class="note"><i>◆</i>주황 선이 '+TR_TAB+', 검정 선이 전체 평균입니다.</div></div>'+
          '<div class="panelC"><div class="ph"><h3>재고 상태</h3><em>'+TR_TAB+'</em></div>'+
            '<table class="mTable"><tr><th>상태</th><th>상품 수</th><th></th></tr>'+
            stock.map(z=>'<tr><td><b>'+trEsc(z[0])+'</b></td>'+
              '<td><span class="bar" style="display:block"><i class="'+(/SOLD/i.test(z[0])?'c':'')+'" style="width:'+Math.round(z[1]/stockMax*100)+'%"></i></span></td>'+
              '<td class="n">'+z[1]+'개</td></tr>').join('')+
            '</table>'+
            '<div class="note"><i>◆</i>품절이 늘수록 할인이 멈출 확률이 올라갑니다.</div></div>'+
        '</div>'+
        '<div class="panelC" style="margin-top:12px"><div class="ph"><h3>'+TR_TAB+' 세부 지표</h3>'+
          '<em>최신 스냅샷</em></div><div class="statRow">'+
          [['최대 할인률',(P.max_discount==null?'–':P.max_discount)+'<u>%</u>','상품 중 최고'],
           ['최저가',trWon(P.min_sale_price),'정가 '+trWon(P.min_list_price)],
           ['좋아요',(P.likes||0).toLocaleString()+'<u>개</u>','상품 합계']]
          .map(x=>'<div class="bigStat"><b>'+x[1]+'</b><span>'+x[0]+' — '+x[2]+'</span></div>').join('')+
        '</div></div>';
      const ps=(D.platform_series||{})[P.code]||[];
      const rows=trMergeRows(D.series,ps.map(p=>({date:p.date,plat:p.discount})));
      G_CFG.stockPlat={key:full+TR_TAB,rows,min:0,max:100,
        emptyReason:TR_TAB+' 할인률 시계열이 비어 있습니다.',
        sets:[{id:'a',name:'전체 평균 (%)',field:'discount',unit:'%'},
              {id:'p',name:TR_TAB+' (%)',field:'plat',unit:'%',accent:1}]};
    }
    gMount(); trDial();
  }

  /* ══════════════ 리세일 시세 지수 ══════════════
     "지금 팔면 얼마 받나 · 사면 손해인가"를 먼저 답한다.
     값: /api/resale → snapshot.resale_snapshot (중고·리셀 매물) ÷ 정가 */
  else if(id==='resale'){
    const D=editGate(body,editUrl('resale'),'리세일 시세를'); if(!D)return;
    const full=D.label||fsItemFull();
    if(D.keep_pct==null){
      body.innerHTML=unavailableHTML('‘'+full+'’ 매물 '+D.listings+'건은 있지만 정가를 알 수 없어 가치 유지율을 계산하지 못했습니다.',
        '매물의 정가(market_metrics.regular_price) 또는 같은 상품의 판매가 스냅샷이 필요합니다.');
      return;
    }
    const TB=D.temperature||{};
    const keep=Math.round(D.keep_pct), idx=keep/100, prem=!!D.premium;
    const RAMP=['#b23b3b','#c98a1b','#1f9e6e'].slice(0,(prem?3:idx>=.7?2:1));
    const volLabel=D.volume_basis==='observed_listings'?'관측 매물':'거래량';
    body.innerHTML=
      '<div class="verdict" style="--sc:'+(prem?'#1f9e6e':idx>=.7?'#c98a1b':'#b23b3b')+'">'+
        '<div class="dial"><svg viewBox="0 0 120 120">'+
          '<circle class="trk" cx="60" cy="60" r="50"/>'+
          '<circle class="val" cx="60" cy="60" r="50" data-ramp="'+RAMP.join(',')+'" data-score="'+Math.min(100,keep)+'" '+
            'stroke-dasharray="314.16" stroke-dashoffset="314.16"/></svg>'+
          '<span class="num"><b data-count="'+keep+'">0</b><small>가치 유지율 %</small></span></div>'+
        '<div class="vdTx">'+
          '<h4><b>'+trEsc(full)+'</b>'+josa(full,'을','를')+' 지금 되팔면 <em>정가의 '+keep+'%</em>'+
            (prem?' — <em>프리미엄</em>이 붙어 있습니다.':'를 받습니다.')+'</h4>'+
          '<p>'+(prem
            ? '발매가보다 비싸게 거래되는 상태입니다. 지금 사면 정가 이상을 지불하게 되고, 갖고 있다면 파는 쪽이 유리합니다.'
            : idx>=.7
              ? '중고 가치가 잘 버티고 있습니다. 몇 시즌 입고 되팔아도 손실이 크지 않은 구간입니다.'
              : '가치 하락이 빠른 구간입니다. 되팔 생각이라면 지금이 마지노선에 가깝습니다.')+'</p>'+
          '<div class="vdMeta">'+
            '<div><b>'+trWon(D.regular_price)+'</b><span>정가 (중앙값)</span></div>'+
            '<div><b>'+trWon(D.used_price)+'</b><span>중고 시세 (중앙값)</span></div>'+
            '<div><b>'+(D.keep_change_pp==null?'–':(D.keep_change_pp>0?'+':'')+D.keep_change_pp+'%p')+'</b><span>전주 대비</span></div>'+
            '<div><b>'+D.listings+'건</b><span>관측 매물</span></div>'+
          '</div>'+
        '</div></div>'+
      '<div class="note" style="margin:0 0 12px"><i>◆</i>'+trEsc(String(D.as_of).slice(0,10))+' 기준 · 최근 '+D.days+'일 · '+
        (D.platforms||[]).map(p=>trEsc(p.label)).join(' · ')+'</div>'+
      '<div class="kpis">'+
        kpi(volLabel,D.volume_4w==null?'–':D.volume_4w.toLocaleString(),'건','최근 4주',1)+
        kpi(volLabel+' 증감률',D.volume_change_pct==null?'–':(D.volume_change_pct>0?'+':'')+Math.round(D.volume_change_pct),
            D.volume_change_pct==null?'':'%','직전 4주 대비',(D.volume_change_pct||0)>=0?1:0)+
        kpi('프리미엄 지속 기간',D.premium_days,'일',prem?('정가 이상 연속 유지'):'프리미엄 미형성',prem?1:0)+
        kpi('리셀 지수',D.resale_index==null?'–':D.resale_index,'',D.resale_index==null?'적재된 값 없음':'최근 1주 중앙값',1)+'</div>'+
      '<div class="trGrid">'+
        '<div class="panelC"><div class="gHead"><h3>가치 유지율 vs 트렌드 온도</h3></div>'+
          '<div data-chart="resMain"></div>'+
          '<div class="note"><i>◆</i>유지율(검정)이 온도(주황)보다 먼저 꺾이면, 되팔 계획이라면 온도가 아니라 이 선을 보세요.</div></div>'+
        '<div class="panelC"><div class="ph"><h3>사이즈별 시세 배수</h3><em>정가=1.00</em></div>'+
          ((D.sizes||[]).length
          ? '<table class="mTable lg"><tr><th>사이즈</th><th>배수</th><th>시세</th></tr>'+
            D.sizes.map((z,i)=>'<tr><td>'+(i===0?'<b>'+trEsc(z.label)+'</b>':trEsc(z.label))+'</td>'+
              '<td class="n '+((z.ratio||0)>=1?'up':'dn')+'">'+(z.ratio==null?'–':'×'+z.ratio.toFixed(2))+'</td>'+
              '<td class="n">'+trWon(z.price)+'</td></tr>').join('')+
            '</table><div class="note"><i>◆</i>매물이 많은 사이즈부터 보여 줍니다.</div>'
          : unavailableHTML('매물에 사이즈 정보가 없습니다.',''))+'</div>'+
      '</div>'+
      '<div class="trGrid" style="margin-top:12px;align-items:start">'+
        '<div class="panelC"><div class="gHead"><h3>상태별 가격대</h3></div>'+
          ((D.grades||[]).length
          ? '<table class="mTable"><tr><th>상태</th><th>비중</th><th>시세</th></tr>'+
            D.grades.map(r=>'<tr><td>'+trEsc(r.label)+'</td>'+
              '<td><span class="bar" style="display:block"><i style="width:'+Math.round(r.share_pct)+'%"></i></span></td>'+
              '<td class="n">'+trWon(r.price)+'</td></tr>').join('')+'</table>'
          : unavailableHTML('매물에 상태 등급 정보가 없습니다.',''))+'</div>'+
        (D.spread
          ? '<div class="panelC svSpread"><div class="svSpreadLabel">호가-체결가 스프레드</div>'+
              '<div class="svSpreadHead">간격 <b>'+(D.spread.gap_pct==null?'–':D.spread.gap_pct+'%')+'</b></div>'+
              '<div class="svSpreadRow"><span>최저 호가 (중앙값)</span><b>'+Math.round(D.spread.ask).toLocaleString()+'<u>원</u></b></div>'+
              '<div class="svSpreadBar"><i style="width:100%"></i></div>'+
              '<div class="svSpreadRow"><span>실제 체결가 (중앙값)</span><b>'+Math.round(D.spread.trade).toLocaleString()+'<u>원</u></b></div>'+
              '<div class="svSpreadBar"><i style="width:'+Math.min(100,Math.round(D.spread.trade/D.spread.ask*100))+'%"></i></div>'+
              '<div class="note"><i>◆</i>간격이 클수록 표면 시세 대비 실제 수요가 약할 수 있습니다.</div></div>'
          : '<div class="panelC">'+unavailableHTML('호가·체결가가 함께 적재된 매물이 없어 스프레드를 계산하지 못했습니다.','')+'</div>')+
      '</div>';
    const tempRows=(TB.series||[]).map(p=>({date:p.date,temp:p.temp}));
    G_CFG.resMain={key:full+'res',rows:trMergeRows(D.series,tempRows),
      emptyReason:'유지율 또는 온도 시계열이 비어 있습니다.',
      sets:[{id:'r',name:'가치 유지율 (%)',field:'keep_pct',unit:'%'}].concat(tempRows.length
        ?[{id:'t',name:'트렌드 온도 (°)',field:'temp',unit:'°',accent:1}]:[])};
    gMount(); trDial();
  }

  /* ══════════════ 수명주기 ══════════════
     "지금 사도 되나" 로만 답한다.
     값: /api/lifecycle → 대표 용어의 level·ma28·momentum 으로 단계를 판정(규칙은 응답의 rule) */
  else{
    const D=editGate(body,editUrl('life'),'수명주기 지표를'); if(!D)return;
    const full=D.label||fsItemFull();
    const stages=['태동','확산','정점','쇠퇴'];
    const si=stages.indexOf(D.stage);
    if(si<0){
      body.innerHTML=unavailableHTML('‘'+full+'’ 은 관측이 모자라 수명주기를 판정하지 않았습니다 (관측 '+D.points+'일).',D.rule);
      return;
    }
    const SC=['#3d7fd6','#1f9e6e','#c98a1b','#b23b3b'][si];
    const RAMP=['#3d7fd6','#1f9e6e','#c98a1b','#b23b3b'].slice(0,si+1);
    const pct=D.progress==null?0:D.progress;
    const timing=['적기','적기','주의','비추천'][si];
    const mom=D.momentum==null?null:Math.round(D.momentum-50);
    const MSG=[
      ['아직 아무도 모릅니다','지금 사면 남들보다 먼저 입는 구간입니다. 다만 물량이 적어 선택지가 좁고, 그대로 사라질 위험도 함께 있습니다.'],
      ['가장 안전한 구간입니다','화제성이 올라가는 중입니다. 물량도 충분해 고르기 좋습니다.'],
      ['지금이 마지막입니다','정점 부근입니다. 사도 되지만 오래 못 갑니다. 오래 입을 옷이라면 다음 것을 보세요.'],
      ['이미 지났습니다','최고점에서 내려오는 중입니다. 싸게 나와도 올해 안에 안 입게 될 확률이 높습니다.']][si];
    const wkRows=(D.weekly_temp||[]).slice(0,8);
    body.innerHTML=
      '<div class="verdict" style="--sc:'+SC+'">'+
        '<div class="dial"><svg viewBox="0 0 120 120">'+
          '<circle class="trk" cx="60" cy="60" r="50"/>'+
          '<circle class="val" cx="60" cy="60" r="50" data-ramp="'+RAMP.join(',')+'" data-score="'+pct+'" '+
            'stroke-dasharray="314.16" stroke-dashoffset="314.16"/></svg>'+
          '<span class="num"><b data-count="'+pct+'">0</b><small>유행 진행도 %</small></span></div>'+
        '<div class="vdTx">'+
          '<h4><b>'+trEsc(full)+'</b>'+josa(full,'은','는')+' <em>'+stages[si]+'</em> 단계 — '+MSG[0]+'</h4>'+
          '<p>'+MSG[1]+'</p>'+
          '<div class="vdBand">'+stages.map((s,i)=>'<div'+(i===si?' class="on"':'')+
            '><span>'+s+'</span></div>').join('')+'</div>'+
          '<div class="vdMeta">'+
            '<div><b>'+D.age_weeks+'주</b><span>화제성 시작 후</span></div>'+
            '<div><b>'+trEsc(D.peak_date||'–')+'</b><span>최고점 (28일 평균)</span></div>'+
            '<div><b>'+(D.temp==null?'–':Math.round(D.temp)+'°')+'</b><span>현재 온도</span></div>'+
            '<div><b>'+(mom==null?'–':mom>=0?'상승':'하강')+'</b><span>현재 방향</span></div>'+
          '</div>'+
        '</div></div>'+
      '<div class="note" style="margin:0 0 12px"><i>◆</i>'+trEsc(D.as_of)+' 기준 · ‘'+trEsc(D.term)+'’ 관측 '+D.points+'일</div>'+
      '<div class="kpis">'+
        kpi('구매 타이밍',timing,'',MSG[0],si<2?1:0)+
        kpi('신규 유입률',D.inflow_pct==null?'–':(D.inflow_pct>0?'+':'')+Math.round(D.inflow_pct),D.inflow_pct==null?'':'%','최근 4주 언급 · 직전 4주 대비',(D.inflow_pct||0)>0?1:0)+
        kpi('성장 모멘텀',mom==null?'–':(mom>0?'+':'')+mom,'','모멘텀 지수 50 = 보합',(mom||0)>0?1:0)+
        kpi('시장 포화도',D.level==null?'–':Math.round(D.level),D.level==null?'':'%','화제성 레벨 기준',(D.level||0)>=60?1:0)+'</div>'+
      '<div class="trGrid">'+
        '<div class="panelC"><div class="gHead"><h3>유행 곡선 · 지금 위치</h3></div>'+
          '<div data-chart="lifeMain"></div>'+
          '<div class="note"><i>◆</i>화제성 레벨의 흐름입니다. 오른쪽 끝 음영이 <b>지금</b>입니다. '+
            (si<2?'아직 올라가는 중이라 여유가 있습니다.':'꼭짓점을 지나면 회복하지 않는 경우가 많습니다.')+'</div></div>'+
        '<div class="panelC"><div class="ph"><h3>주별 온도</h3><em>최근 8주</em></div>'+
          (wkRows.length
          ? '<table class="mTable lg"><tr><th>시기</th><th>온도</th><th></th></tr>'+
            wkRows.map(r=>'<tr><td>'+(r.weeks_ago===0?'이번 주':r.weeks_ago+'주 전')+'</td>'+
              '<td><span class="bar" style="display:block"><i class="'+(r.temp>=60?'c':'')+'" style="width:'+Math.round(r.temp)+'%"></i></span></td>'+
              '<td class="n">'+Math.round(r.temp)+'°</td></tr>').join('')+
            '</table>'
          : unavailableHTML('최근 8주 온도 값이 없습니다.',''))+
          '<div class="note"><i>◆</i>'+trEsc(D.rule)+'</div></div>'+
      '</div>'+
      '<div class="trGrid one" style="margin-top:12px">'+
        '<div class="panelC"><div class="gHead"><h3>언급량 · 판매량</h3></div>'+
          '<div data-chart="lifeGap"></div>'+
          '<div class="note"><i>◆</i>언급량만 많고 실제로 구매하지 않는 구간은 거품입니다. '+
            '두 선이 붙어 갈수록 진짜 유행입니다. (둘 다 최대=100 지수)</div></div>'+
      '</div>';
    G_CFG.lifeMain={key:full+'life',rows:D.series,band:[.88,1],min:0,max:100,
      emptyReason:'화제성 레벨 시계열이 비어 있습니다.',
      sets:[{id:'l',name:'화제성 레벨',field:'level',unit:''}]};
    const sales=D.sales_series||[];
    G_CFG.lifeGap={key:full+'gap',wide:true,min:0,max:100,
      rows:trMergeRows(D.series.map(p=>({date:p.date,mention:p.mention})),sales),
      emptyReason:sales.length?'언급량 시계열이 비어 있습니다.':'선택한 조건 상품의 판매수 스냅샷(sales_count)이 없어 판매량을 그리지 못했습니다.',
      sets:[{id:'m',name:'언급량',field:'mention',index:true,unit:''},
            {id:'w',name:'판매량',field:'sales',index:true,unit:'',accent:1,rows:sales}]};
    gMount(); trFillBars(); trDial();
  }
  if(HAS_A)aAnimate($$('#trBody .kpi, #trBody .panelC, #trBody .concl, #trBody .verdict, #trBody .cheapest, #trBody .svAlso'),
    {opacity:[0,1],translateY:[16,0],duration:760,delay:aStagger(60),ease:'out(3)'});
  trCountUp();   /* 카드가 올라오는 동안 숫자도 같이 굴러 올라간다 */
}
/* 긍부정 - 반응 비중 원형(파이) 차트.
   날짜별로 나누지 않고 선택한 기간(주별 7일 · 월별 30일)의 긍정·중립·부정 건수를 합쳐 한 원에 보여 준다.
   건수 칸(pos_n·neu_n·neg_n)이 없는 응답이면 조각을 지어내지 않는다. */
const SENT_PIE_G=[['w','주별',7],['m','월별',30]];
function sentPie(el,cfg){
  if(!el)return;
  const g=SENT_PIE_G.some(x=>x[0]===el.dataset.g)?el.dataset.g:'w';
  el.dataset.g=g;
  const days=SENT_PIE_G.find(x=>x[0]===g)[2];
  const rows=(cfg.rows||[]).filter(r=>r&&r.date&&trDayDiff(r.date,cfg.lastDate)<days&&trDayDiff(r.date,cfg.lastDate)>=0);
  const hasCnt=rows.some(r=>['pos_n','neu_n','neg_n'].some(f=>r[f]!=null));
  const sum=f=>rows.reduce((a,r)=>a+(+r[f]||0),0);
  const parts=[['p','긍정',sum('pos_n'),'var(--coral)'],['u','중립',sum('neu_n'),'#c9c7c2'],['n','부정',sum('neg_n'),'var(--pink-0)']];
  const total=parts.reduce((a,x)=>a+x[2],0);
  const sel='<div class="gSel">'+SENT_PIE_G.map(x=>'<button type="button" data-g="'+x[0]+'"'+
    (x[0]===g?' class="on"':'')+'>'+x[1]+'</button>').join('')+'</div>';
  if(!hasCnt||total===0){
    el.dataset.live=hasCnt?'zero':'none';
    el.innerHTML=sel+unavailableHTML(hasCnt?'최근 '+days+'일 동안 분류된 반응이 0건입니다.':'긍정·중립·부정 건수가 아직 없습니다.','');
  } else {
    el.dataset.live='ok';
    /* 채워진 원형(파이) 차트 — 조각 사이는 흰 틈으로 가르고, 가장 큰 조각을 바깥으로 살짝 띄워 강조한다.
       12시 방향에서 시계 방향으로 긍정 → 중립 → 부정 순서로 그린다. */
    const CX=100, CY=100, R=86, POP=7;
    const pct=v=>Math.round(v/total*100);
    const live=parts.filter(x=>x[2]>0);
    const big=live.reduce((m,x)=>x[2]>m[2]?x:m,live[0]);
    const pt=(ang,r)=>[CX+r*Math.sin(ang),CY-r*Math.cos(ang)];
    let a0=0;
    const segs=live.map(x=>{
      const sweep=x[2]/total*Math.PI*2, a1=a0+sweep, mid=a0+sweep/2;
      const off=(x===big&&live.length>1)?POP:0;
      const dx=off*Math.sin(mid), dy=-off*Math.cos(mid);
      const tip='<title>'+x[1]+' '+x[2].toLocaleString()+'건 · '+pct(x[2])+'%</title>';
      let shape;
      if(live.length===1){
        shape='<circle class="pieSeg" data-s="'+x[0]+'" cx="'+CX+'" cy="'+CY+'" r="'+R+'" fill="'+x[3]+'">'+tip+'</circle>';
      } else {
        const [x0,y0]=pt(a0,R), [x1,y1]=pt(a1,R);
        shape='<path class="pieSeg" data-s="'+x[0]+'" transform="translate('+dx.toFixed(2)+' '+dy.toFixed(2)+')" '+
          'd="M'+CX+' '+CY+' L'+x0.toFixed(2)+' '+y0.toFixed(2)+' A'+R+' '+R+' 0 '+(sweep>Math.PI?1:0)+' 1 '+
          x1.toFixed(2)+' '+y1.toFixed(2)+' Z" fill="'+x[3]+'">'+tip+'</path>';
      }
      /* 조각 안 퍼센트 — 큰 조각일수록 글자도 크게, 너무 얇은 조각(5% 미만)은 범례에만 둔다 */
      const p=pct(x[2]);
      let label='';
      if(p>=5){
        const lr=live.length===1?0:R*(p>=40?.5:.62);
        const [lx,ly]=pt(mid,lr);
        const fs=p>=40?22:p>=15?15:11;
        label='<text class="pieTx" x="'+(lx+dx).toFixed(2)+'" y="'+(ly+dy).toFixed(2)+'" font-size="'+fs+'" '+
          'fill="'+(x[0]==='u'?'#0a0a0a':'#fff')+'" text-anchor="middle" dominant-baseline="central">'+p+'%</text>';
      }
      a0=a1; return shape+label;
    }).join('');
    el.innerHTML=sel+
      '<div class="sentPie">'+
        '<div class="pieBox"><svg viewBox="-8 -8 216 216">'+segs+'</svg></div>'+
        '<div class="pieSide"><div class="pieSum"><b>'+total.toLocaleString()+'</b><small>건 · 최근 '+days+'일 반응</small></div>'+
        '<ul class="pieLg">'+parts.map(x=>'<li data-s="'+x[0]+'"><i style="background:'+x[3]+'"></i>'+
          '<span>'+x[1]+'</span><b>'+pct(x[2])+'%</b><em>'+x[2].toLocaleString()+'건</em></li>').join('')+'</ul></div>'+
      '</div>';
    if(HAS_A)aAnimate(el.querySelectorAll('.pieSeg,.pieTx'),{opacity:[0,1],duration:520,delay:aStagger(90),ease:'out(3)'});
  }
  el.querySelector('.gSel').addEventListener('click',ev=>{
    const b=ev.target.closest('button'); if(!b)return;
    el.dataset.g=b.dataset.g; sentPie(el,cfg); sentFitSignals();
  });
}
function trAnimateSvg(){ gDraw($$('#trBody .lifeSvg path'),1250,320) }
/* 긍부정 - '신호 유형별 건수' 카드는 왼쪽 '구매의향 지수 추이' 차트 카드 높이에 '정확히' 맞아야 한다.
   신호가 8개(POS 4 + NEG 4)라 표가 차트보다 자연 높이가 더 큰 경우가 있는데, 이걸 grid stretch 에
   맡기면 반대로 차트 카드가 늘어나며 차트 쪽에 빈 공백이 생긴다(오른쪽이 원인 제공, 왼쪽이 피해).
   그래서 이 trGrid 는 align-items:start 로 두고(둘 다 각자 내용 높이로 따로 계산), 왼쪽 차트 카드의
   '있는 그대로'(공백 없는) 높이를 잰 뒤 그 값을 오른쪽 카드 height 로 직접 강제한다.
   오른쪽 목록이 그 높이에 안 들어가면 잘라내고 '+더보기' 로 나머지를 연다(펼치면 카드도 같이 자란다).
   차트 높이는 자기 칼럼 너비에 따라 바뀌므로(뷰포트 리사이즈) 창 크기 변경 시에도 다시 잰다. */
function sentFitSignals(){
  const chart=$('#sentChartCard'), card=$('#sentSigCard'), wrap=$('#sigWrap'), btn=$('#sigMoreBtn');
  if(!chart||!card||!wrap||!btn)return;
  const wasOpen=btn.dataset.state==='open';   /* 리사이즈로 다시 잴 때 펼친 상태는 유지한다 */
  card.style.height='';wrap.style.maxHeight='';wrap.style.overflow='';btn.hidden=true;btn.onclick=null;
  const targetH=chart.offsetHeight;   /* 차트 카드 자체의 공백 없는 높이 */
  const cs=getComputedStyle(card);
  const padV=parseFloat(cs.paddingTop)+parseFloat(cs.paddingBottom);
  let used=padV;
  card.querySelectorAll(':scope > *').forEach(ch=>{ if(ch===wrap)return;
    const m=getComputedStyle(ch); used+=ch.offsetHeight+parseFloat(m.marginTop)+parseFloat(m.marginBottom); });
  const full=wrap.scrollHeight;
  if(full+used<=targetH){ card.style.height=targetH+'px'; return; }

  const btnH=btn.offsetHeight||34, gap=12;   /* .sigMore 의 margin-top 과 맞춘 값 */
  const avail=Math.max(40,targetH-used-btnH-gap);
  const openH=used+full+btnH+gap;            /* 펼쳤을 때 카드가 필요로 하는 자연 높이 */

  /* 접힘·펼침 전환을 anime.js 로 부드럽게 잇는다 — 그냥 값만 바꾸면 뚝뚝 끊겨서 정적으로 보인다 */
  const setTo=(wrapH,cardH,animated)=>{
    wrap.style.overflow='hidden';
    const curW=parseFloat(wrap.style.maxHeight)||wrap.getBoundingClientRect().height;
    const curC=parseFloat(card.style.height)||card.getBoundingClientRect().height;
    if(HAS_A&&animated){
      aAnimate(wrap,{maxHeight:[curW,wrapH],duration:380,ease:'out(3)'});
      aAnimate(card,{height:[curC,cardH],duration:380,ease:'out(3)',
        onComplete:()=>{ if(cardH>targetH+2)wrap.style.overflow='visible'; }});
      aAnimate(btn,{opacity:[.35,1],duration:320,ease:'out(2)'});
    } else {
      wrap.style.maxHeight=wrapH+'px'; card.style.height=cardH+'px';
      if(cardH>targetH+2)wrap.style.overflow='visible';
    }
  };
  const collapse=animated=>{ btn.textContent='+ 더보기'; btn.dataset.state='closed'; setTo(avail,targetH,animated); };
  const expand  =animated=>{ btn.textContent='- 줄이기'; btn.dataset.state='open';   setTo(full,openH,animated); };

  btn.hidden=false;
  btn.onclick=()=>{ if(btn.dataset.state==='open') collapse(true); else expand(true); };
  if(wasOpen) expand(false); else collapse(false);
}
var __sentFitT=null;
window.addEventListener('resize',()=>{
  clearTimeout(__sentFitT);
  __sentFitT=setTimeout(sentFitSignals,140);
});
var TR_TAB='통합';

/* 사이드바 하단 프로필 — [아바타] [닉네임 / 직위] [등급 뱃지]
   직위 줄: 운영자 계정은 'ADMIN · 서울' 그대로, 일반 가입자는 승인된 직업(없으면 Basic).
   승인 대기 중이면 ' · 인증 대기' 가 붙는다 (account/static/js/job.js). */
function sFootPaint(){
  const sf=$('#sFoot'); if(!sf)return;
  const sav=sf.querySelector('.av');
  if(sav){ sav.textContent=ME.initial; rkPaintAv(sav, ME.rank) }   /* 링은 rkPaintAv 가 다시 얹는다 */
  const nb=sf.querySelector('.who b'); if(nb)nb.textContent=ME.name;
  const plan=$('#sFootPlan'); if(plan)plan.textContent=jobPlanText(ME);
  const rk=$('#sFootRk');   if(rk)rk.innerHTML=rkChip(ME.rank);   /* 뱃지는 오른쪽 끝에 따로 선다 */
}
document.addEventListener('feedit:job',()=>sFootPaint());

export function trBuild(){
  /* ★ 진짜 사전을 받아 둔다.
     이게 없으면 검색이 이 파일에 박힌 146개로만 돌아서, RDS 에 있는 말도
     "사전에서 찾지 못했습니다" 가 된다(스투시·키르시·엄브로가 그랬다).
     못 받아도 그냥 넘어간다 — 박아 둔 목록으로 화면은 계속 돈다. */
  fsLoadDictionary().catch(()=>{});
  const mk=(a,host)=>{ const el=$(host); if(!el)return;
    el.innerHTML=a.map(s=>'<button class="sItem" data-tr="'+s.id+'">'+
      '<span class="ic">'+s.ic+'</span><span class="tx">'+s.t+'</span></button>').join('') };
  mk(S_FEED,'#sFeed'); mk(S_EDIT,'#sEdit');
  const first=$('.sItem'); if(first)first.classList.add('on');
  $('#sToggle').addEventListener('click',()=>{
    trSideOpen(!$('#side').classList.contains('open'));
  });
  /* 커머스 탭만 여기서 받는다. 같은 자리에 뜨는 키워드 검색 버튼(.kwGo)은
     자기 핸들러가 따로 있으므로 여기서 가로채면 안 된다. */
  $('#trTabs').addEventListener('click',e=>{
    const b=e.target.closest('button[data-t]'); if(!b)return;
    $$('#trTabs button[data-t]').forEach(x=>x.classList.remove('on')); b.classList.add('on');
    TR_TAB=b.dataset.t; trRender('stock');   /* 탭이 바뀌면 본문을 다시 짠다 */
  });
  fsBuild();
  sFootPaint();
  /* 본문은 여기서 그리지 않는다. 숨어 있는 동안 그리면 등장 애니메이션이
     아무도 안 볼 때 다 끝나버려서, 탭을 열었을 땐 이미 정지 화면이 된다.
     실제로 여는 순간(goView) 에 처음 한 번 그린다. */
}
