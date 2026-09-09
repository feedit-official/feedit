import { $, $$, HAS_A, aAnimate, aSpring, aStagger, aTimeline, aUtils } from '../../../core/static/js/dom.js';
import { AUTH, acctBoot, likeClick, myRender, requireAuth, resetSignupForm } from '../../../account/static/js/profile.js';
import { M_CHIPS, SM_ON, hotBuild, newChat, qRoll, sendChat, smSwitch } from '../../../home/static/js/chat.js';
import { closeChatPopup, cpEditTitle, cpNewConvo, cpRenderList, cpRenderThread, cpSend, cpStore, cpToggleMode, openChatWith } from '../../../home/static/js/chat_popup.js';
import { mPaintVote, mVote, smBuild } from '../../../salmal/static/js/nav_widget.js';
import { prBuild } from '../../../pricing/static/js/pricing.js';
import { renderDeck } from '../../../intro/static/js/deck.js';
import { salmalBoot } from '../../../salmal/static/js/vote_app.js';
import { stBuild, stItemPage, stMoreItems, stOpen, stOpenFit } from '../../../style/static/js/style_page.js';
import { trBuild, trRender } from '../../../trend/static/js/dispatch.js';

/* ============================================================
   메인 랜딩 페이지
   레퍼런스: https://pamidordesign.com — 오프화이트 지면, 큰 선언문,
   스크롤을 따라 한 단어씩 물드는 문단, 검정 알약 버튼.
   ============================================================ */
export var mainMode=false, mainReady=false, curView='home';

/* ── 브라우저 뒤로가기 ─────────────────────────────────
   화면이 바뀔 때마다 히스토리 항목을 쌓아 두고(pushNav), popstate 로 그
   항목을 다시 읽어 같은 화면 · 같은 탭 · 같은 스타일로 복원한다.
   navSkip 은 popstate 로 인한 복원 자체가 새 히스토리 항목을 또 쌓는 걸
   막는 플래그다. */
let curTr='myfeed', curStyleId=null, navSkip=false;
function navState(){
  return { view:curView, tr:curView==='trend'?curTr:null, style:curView==='style'?curStyleId:null };
}
function pushNav(){
  if(navSkip){ navSkip=false; return }
  if(!mainMode)return;   /* 랜딩(인트로) 단계에서는 기록하지 않는다 */
  history.pushState(navState(), '', location.href);
}

/* ── 히어로 등장 ────────────────────────────────────── */
function mHeroIn(){
  const wds=$$('#mState .wd'); if(!HAS_A||!wds.length)return;
  aUtils.set(wds,{opacity:0,translateY:'104%'});
  aUtils.set(['.mKicker','.heroL p','.hot','.chatWrap','.chips'],{opacity:0});
  const t=aTimeline();
  t.add('.mKicker', {opacity:[0,1],translateY:[12,0],duration:700,ease:'out(3)'},0)
   .add(wds,{opacity:[0,1],translateY:['104%','0%'],duration:1080,delay:aStagger(70),
      ease:aSpring({stiffness:72,damping:16})},110)
   .add('.hot',      {opacity:[0,1],translateY:[-14,0],duration:860,
      ease:aSpring({stiffness:80,damping:16})},520)
   .add('.heroL p',  {opacity:[0,1],translateY:[16,0],duration:820,ease:'out(3)'},640)
   .add('.chatWrap', {opacity:[0,1],translateY:[18,0],duration:900,
      ease:aSpring({stiffness:78,damping:16})},680)
   .add('.chips',    {opacity:[0,1],translateY:[14,0],duration:800,ease:'out(3)'},860);
  setTimeout(()=>{ const em=$('#mState em'); if(em)em.classList.add('ul') },1050);
}

/* ── 트렌드 분석 사이드바 ────────────────────────────
   토글 버튼과 뷰 진입이 같은 함수를 쓴다. 상태가 갈리지 않게. */
export function trSideOpen(on){
  const sd=$('#side'), wr=$('.trWrap');
  if(!sd)return;
  sd.classList.toggle('open',on);
  if(wr)wr.classList.toggle('open',on);
}
/* 접힌 상태로 되돌리되 폭이 줄어드는 장면은 보이지 않게 — 전환을 한 프레임 끈다 */
function trSideReset(){
  const sd=$('#side'), wr=$('.trWrap');
  if(!sd)return;
  sd.classList.add('noTr'); if(wr)wr.classList.add('noTr');
  trSideOpen(false);
  void sd.offsetWidth;
  sd.classList.remove('noTr'); if(wr)wr.classList.remove('noTr');
}

/* ── 뷰 라우터 ──────────────────────────────────────── */
export function goView(v){
  if(!v)return;
  /* ★ 없는 화면으로는 가지 않는다.
     아래 `$$('.view').forEach(s=>s.classList.toggle('on', s.id==='v-'+v))` 는
     맞는 게 없으면 **모든 화면을 끔다** — 그게 공백 페이지였다.
     예전에 세부 검색 팝업의 필터 버튼이 data-v="스트릿" 을 달고 있어
     아래 전역 클릭 위임이 goView('스트릿') 을 불렀고, 그 순간
     화면이 통째로 비었다. 버튼 손 data-v 는 data-fv 로 바꿨지만,
     같은 사고가 다시 나지 않게 여기서도 막는다. */
  if(!document.getElementById('v-'+v)){
    if(window.console&&console.warn)console.warn('[router] 없는 화면입니다:',v);
    return;
  }
  if(v===curView){
    /* 스타일 탭에서 상세 화면에 들어가 있을 때 스타일 탭을 다시 누르면
       그 자리에 머무르지 않고 스타일 목록 처음 화면으로 되돌아간다 —
       이때도 처음 진입할 때와 똑같이 네비 아이콘이 튀고 화면이 살짝
       떠오르며 나타나는 모션을 그대로 태운다 (정적으로 뚝 끊기지 않게) */
    if(v==='style'){
      $('#styleDetail').style.display='none'; $('#styleHome').style.display='';
      const nb=$$('#mNav button').filter(b=>b.dataset.v===v)[0];
      if(HAS_A&&nb)aAnimate($('span',nb),{translateY:[-3,0],duration:560,
        ease:aSpring({stiffness:150,damping:12})});
      const el=$('#v-style');
      if(HAS_A&&el){
        el.style.transform='';
        aAnimate(el,{opacity:[0,1],translateY:[14,0],duration:640,ease:'out(3)',
          onComplete:()=>{ el.style.transform='' }});
      }
    }
    scrollTo(0,0);
    return;
  }
  if(curView==='signup'&&v!=='signup')resetSignupForm();   /* 완료 안 하고 나가면 다음엔 처음 상태로 */
  curView=v;
  $$('#mNav button').forEach(b=>b.classList.toggle('on',b.dataset.v===v));
  document.body.classList.toggle('acctmode',v==='login'||v==='signup'||v==='mypage');
  $$('.view').forEach(s=>s.classList.toggle('on',s.id==='v-'+v));
  scrollTo(0,0);
  const nb=$$('#mNav button').filter(b=>b.dataset.v===v)[0];
  if(HAS_A&&nb)aAnimate($('span',nb),{translateY:[-3,0],duration:560,
    ease:aSpring({stiffness:150,damping:12})});
  const el=$('#v-'+v);
  /* 끝나면 transform 을 지운다 — 남겨두면 안쪽 position:fixed 가 뷰 기준이 된다.
     트렌드 분석은 고정 사이드바가 있어 transform 을 아예 쓰지 않는다. */
  if(HAS_A&&el){
    if(v==='trend')aAnimate(el,{opacity:[0,1],duration:520,ease:'out(3)'});
    else aAnimate(el,{opacity:[0,1],translateY:[14,0],duration:640,ease:'out(3)',
      onComplete:()=>{ el.style.transform='' }});
  }
  document.body.classList.toggle('athome',v==='home');
  document.body.dataset.view=v;
  if(v==='home'&&!$('#v-home').classList.contains('asking'))mHeroIn();
  if(v==='style'){ $('#styleDetail').style.display='none'; $('#styleHome').style.display='' }
  if(v==='salmal'){
    const first=!window.__smOn;
    if(first){ window.__smOn=1; try{ salmalBoot() }catch(e){} }
    /* 어느 탭에서 시작할지 지정돼 있으면 그쪽에서 다시 그리며 모션까지 태운다.
       첫 진입이든 아니든 반드시 반영한다 — 예전엔 첫 진입일 때 흘려버려서
       내 피드에서 넘어와도 '내 취향' 표시가 안 붙었다.
       탭 이동과 재생을 둘 다 돌리면 같은 막대에 애니메이션이 두 번 걸리므로 하나만 돌린다. */
    if(window.__smWant&&window.smGoTab){
      const want=window.__smWant; window.__smWant=null;
      setTimeout(()=>{ try{ window.smGoTab(want) }catch(e){} },first?280:90);
    }
    else if(!first&&window.smReplay)setTimeout(()=>{ try{ window.smReplay() }catch(e){} },90);
  }
  if(v==='mypage'){
    if(!AUTH.in){ setTimeout(()=>goView('login'),0); return }
    myRender();
  }
  /* 트렌드 분석 — 들어올 때마다 내 피드에서 다시 시작하고,
     사이드바는 접힌 상태에서 스르륵 열리며 화면이 전개된다.
     로그인 전에는 곧장 로그인 화면으로 튕기지 않는다 — 내 피드 화면은 뒤에
     그대로 두고 흐릿하게 가린 뒤 그 위에 로그인 안내 팝업만 띄운다. */
  if(v==='trend'){
    const trGate=$('#trendGateModal');
    if(trGate)trGate.classList.toggle('on',!AUTH.in);
    window.__trOn=1;
    window.__trEnterAt=Date.now();     /* 사이드바 전환과 겹치지 않게 재는 기준점 */
    trSideReset();                       /* 전환 없이 접어 둔다 — 열리는 장면을 보여 주려고 */
    const startTr=window.__trWant||'myfeed'; window.__trWant=null; curTr=startTr;
    $$('.sItem').forEach(x=>x.classList.toggle('on',x.dataset.tr===startTr));
    setTimeout(()=>trRender(startTr),130);
    setTimeout(()=>trSideOpen(true),240); /* 본문이 올라오기 시작할 때 같이 열린다 */
  }
  pushNav();
}
function goStyle(id){
  curView='style'; curStyleId=id;
  document.body.classList.remove('athome');
  $$('#mNav button').forEach(b=>b.classList.toggle('on',b.dataset.v==='style'));
  $$('.view').forEach(s=>s.classList.toggle('on',s.id==='v-style'));
  stOpen(id);
  pushNav();
}

/* ── 조립 ───────────────────────────────────────────── */
(function buildMain(){
  const ch=$('#mChips');
  if(ch) ch.innerHTML=M_CHIPS.map((c,i)=>
    '<button class="chip'+(i?'':' on')+'" data-ans="'+c[1]+'">'+c[0]+'</button>').join('');
  $$('#mState .ln').forEach(ln=>{
    const parts=[...ln.childNodes]; ln.innerHTML='';
    parts.forEach(node=>{
      if(node.nodeType===3){
        node.textContent.split(/(\s+)/).forEach(tk=>{
          if(!tk)return;
          if(/^\s+$/.test(tk)){ ln.appendChild(document.createTextNode(' ')); return }
          const s=document.createElement('span'); s.className='wd'; s.textContent=tk; ln.appendChild(s);
        });
      }else{ const s=document.createElement('span'); s.className='wd'; s.appendChild(node); ln.appendChild(s) }
    });
  });
  hotBuild(); trBuild(); smBuild(); stBuild(); prBuild(); mPaintVote(); acctBoot();
})();

/* ── 상호작용 ───────────────────────────────────────── */
document.addEventListener('click',e=>{
  const like=e.target.closest('[data-like-id]');
  if(like)return likeClick(like);
  const fit=e.target.closest('[data-fit-style]');
  if(fit)return stOpenFit(fit.dataset.fitStyle);
  const nav=e.target.closest('#mNav button'); if(nav)return goView(nav.dataset.v);
  const st=e.target.closest('[data-style]');
  if(st&&st.dataset.style)return goStyle(st.dataset.style);
  const v=e.target.closest('[data-v]');
  /* data-sm 이 붙어 있으면 살!말? 로 갈 때 그 탭에서 시작한다 —
     내 피드에서 넘어온 건 언제나 '내 취향' 이어야 하니까. */
  if(v){ if(v.dataset.sm)window.__smWant=v.dataset.sm; return goView(v.dataset.v) }
  const tr=e.target.closest('[data-tr]');
  if(tr){ $$('.sItem').forEach(x=>x.classList.remove('on')); tr.classList.add('on');
          curTr=tr.dataset.tr; pushNav();
          return trRender(tr.dataset.tr) }
  const chip=e.target.closest('.chip[data-ans]');
  if(chip){
    $$('#mChips .chip').forEach(c=>c.classList.remove('on')); chip.classList.add('on');
    return openChatWith(chip.textContent,chip.dataset.ans);
  }
  const vt=e.target.closest('[data-vote]'); if(vt)return mVote(vt.dataset.vote);
});
$('#mHome')&&$('#mHome').addEventListener('click',()=>goView('home'));
$('#chatFab')&&$('#chatFab').addEventListener('click',()=>openChatWith('',null));
$('#mSend')&&$('#mSend').addEventListener('click',sendChat);
/* 살!말? 버튼은 이제 뷰 이동이 아니라 모드 전환이다 */
$('#smToggle')&&$('#smToggle').addEventListener('click',e=>{ e.stopPropagation(); smSwitch(!SM_ON,e) });
$('#newChat')&&$('#newChat').addEventListener('click',newChat);
$('#mInput')&&$('#mInput').addEventListener('input',e=>{
  $('#ghostQ').classList.toggle('hide',!!e.target.value) });
$('#mInput')&&$('#mInput').addEventListener('keydown',e=>{
  if(e.isComposing||e.keyCode===229)return;
  if(e.key==='Enter')sendChat();
});

/* ── 챗봇 팝업 바인딩 ──────────────────────────────────
   salmalBoot() 은 살!말? 탭에 처음 들어갈 때까지 미뤄지는 지연 함수라,
   홈에서 곧장 여는 이 팝업의 바인딩은 반드시 여기(항상 실행되는 조립부)에
   있어야 한다. salmalBoot 안에 두면 살!말? 탭을 한 번도 안 들어간 채로
   홈에서 팝업을 열었을 때 닫기·전송·새 대화가 전부 먹통이 된다. */
$('#cpAv')&&$('#cpAv').addEventListener('click',cpToggleMode);
$('#cpNewBtn')&&$('#cpNewBtn').addEventListener('click',()=>{
  cpNewConvo(); cpRenderList(); cpRenderThread();
  const ta=$('#cpInput'); if(ta)ta.focus();
});
$('#cpList')&&$('#cpList').addEventListener('click',e=>{
  const edit=e.target.closest('.cpEdit[data-edit]');
  if(edit){ cpEditTitle(+edit.dataset.edit); return; }
  const item=e.target.closest('.cpItem[data-cid]'); if(!item)return;
  cpStore().activeId=+item.dataset.cid;
  cpRenderList(); cpRenderThread();
});
$('#cpSend')&&$('#cpSend').addEventListener('click',cpSend);
$('#cpInput')&&$('#cpInput').addEventListener('keydown',e=>{
  /* 한글 등 조합 입력 중에 눌리는 Enter(조합 확정용)까지 전송으로 잡으면
     마지막 자모가 따로 떨어져 나가 메시지가 두 번 나뉘어 찍힌다 —
     조합 중일 땐(e.isComposing / 구형 브라우저의 keyCode 229) 무시한다. */
  if(e.isComposing||e.keyCode===229)return;
  if(e.key==='Enter'&&!e.shiftKey){ e.preventDefault(); cpSend(); }
});
$('#cpInput')&&$('#cpInput').addEventListener('input',e=>{
  const el=e.target; el.style.height=''; el.style.height=Math.min(el.scrollHeight,120)+'px';
});
$('#cpClose')&&$('#cpClose').addEventListener('click',closeChatPopup);
$('#cpOverlay')&&$('#cpOverlay').addEventListener('click',e=>{ if(e.target.id==='cpOverlay')closeChatPopup(); });
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'&&$('#cpOverlay').classList.contains('on'))closeChatPopup();
});

/* ── 모드 전환 — 버튼으로만 ─────────────────────────── */
function enterMain(){
  if(mainMode)return; mainMode=true;
  document.body.classList.add('mainmode');
  scrollTo(0,0);
  if(!mainReady){ mainReady=true; qRoll() }
  curView=''; goView('home');
}
export function exitMain(){
  if(!mainMode)return; mainMode=false;
  scrollTo(0,0);
  document.body.classList.remove('mainmode');
  renderDeck();
}
$('#startBtn')&&$('#startBtn').addEventListener('click',enterMain);
/* 설명이 지루한 사람은 여기서 바로 넘어간다 */
$('#jumpBtn')&&$('#jumpBtn').addEventListener('click',enterMain);

/* 뒤로가기(및 앞으로가기) — pushNav 로 쌓아 둔 항목을 그대로 복원한다.
   랜딩(인트로) 단계로 완전히 나가 있었다면 다시 들어올 땐 홈에서 시작하고,
   기록이 없는(=우리가 처음 pushState 하기 전) 항목으로 돌아가면 인트로로 나간다. */
addEventListener('popstate', e=>{
  const st=e.state;
  navSkip=true;
  if(!mainMode){
    if(st&&st.view)enterMain(); else navSkip=false;
    return;
  }
  if(!st||!st.view){ exitMain(); return }
  if(st.view==='style'&&st.style){ goStyle(st.style); return }
  if(st.view==='trend')window.__trWant=st.tr||'myfeed';
  goView(st.view);
});

/* 아이템 무한 스크롤 */
addEventListener('scroll',()=>{
  if(!mainMode)return;
  if(curView==='style'&&$('#styleDetail').style.display!=='none'){
    const m=$('#stMore');
    if(m&&m.getBoundingClientRect().top<innerHeight+240&&stItemPage<9)stMoreItems();
  }
},{passive:true});
