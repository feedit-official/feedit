import { HAS_A, aAnimate, aSpring, aStagger, aUtils } from '../../../core/static/js/dom.js';
import { AUTH, ME, requireAuth } from '../../../account/static/js/profile.js';
import { rkClamp, rkRingHTML } from '../../../account/static/js/rank.js';
import { jobBadgeHTML, jobShown } from '../../../account/static/js/job.js';
import { smBarFill, smBarLabels } from '../../../trend/static/js/discount_resale.js';
import { STYLES } from '../../../home/static/js/chat.js';
import { createVoteCard, deleteVoteCard, deleteVoteComment, reportVoteTarget, saveVote, saveVoteComment } from '../../../account/static/js/account_api.js';

/* ══════════════ 살!말? (feedit-salmal_2 이식) ══════════════
   이름 충돌을 막기 위해 통째로 자기 범위 안에서 돌린다. */
export function salmalBoot(){

/* 카드·투표·댓글의 단일 원본은 Django API와 PostgreSQL이다. */
let VOTES=[];
let BRAND_LIST=[];
function cardFromApi(card,i){
  const summary=card.vote_summary||{};
  const similar=card.similar_user_summary||summary;
  const source=card.source||{};
  return {
    id:card.id, cardKey:String(card.id), t:card.title,
    b:card.brand||'브랜드 미확인', p:card.price,
    base:summary.buy_pct??50, baseSal:summary.buy||0, baseMal:summary.pass||0,
    a:summary.buy_pct??50, votes:summary.total||0,
    hours:card.closed?0:card.hours_remaining,
    createdAt:Date.parse(card.created_at)||0,
    closesAt:Date.parse(card.closes_at)||Number.POSITIVE_INFINITY,
    /* 나와 비슷한 사용자들 — 표본이 0명이면 has_sample:false 이고 비율은 null 이다.
       예전에는 이때 전체 투표 비율이 그대로 내려와 "비슷한 사용자"라는 말이
       거짓이 됐다. 이제 없으면 없다고 쓴다. */
    simHas:Boolean(similar.has_sample),
    simPct:similar.has_sample?similar.buy_pct:null,
    simUsers:similar.sample_users||0,
    simReason:similar.reason||'',
    taste:similar.has_sample?similar.buy_pct:(summary.buy_pct??50),
    tasteMatch:card.taste_match_count||0,
    tasteTags:Array.isArray(card.taste_match_tags)?card.taste_match_tags:[],
    tone:['#302d2b','#6e6660'], imgURL:card.image_url,
    youtubeId:source.video_id||'', upload_date:source.upload_date||'',
    productSourceId:card.product_source_id,
    closed:Boolean(card.closed), st:Array.isArray(card.style_tags)?card.style_tags:[],
    mine:Boolean(card.mine),
    deletable:Boolean(card.deletable),
    authorNote:{name:card.author?.name||'FEEDiT 사용자',text:card.author?.story||card.description||''},
    voted:card.my_choice==='BUY'?0:card.my_choice==='PASS'?1:null,
    comments:(card.comments||[]).map(comment=>({
      id:comment.id, name:comment.name,
      tag:comment.choice==='BUY'?0:comment.choice==='PASS'?1:null,
      rk:comment.rank, job:comment.job, text:comment.text, time:comment.time,
      me:Boolean(comment.mine)
    })),
    seq:i
  };
}
async function loadVotes(){
  const groups=await Promise.all(['latest','result'].map(tab=>
    fetch('/api/salmal/cards?tab='+tab,{credentials:'same-origin',headers:{Accept:'application/json'}})
      .then(async response=>{
        const payload=await response.json();
        if(!response.ok||payload.status!=='ok') throw new Error(payload.reason||'살말 데이터를 불러오지 못했습니다.');
        return payload.data.items||[];
      })));
  const unique=new Map([...groups[0],...groups[1]].map(card=>[card.id,card]));
  VOTES=[...unique.values()].map(cardFromApi);
  BRAND_LIST=[...new Set(VOTES.map(v=>v.b))].sort();
}

/* 페이지를 계속 열어 둔 상태에서도 마감 시간이 지나면 즉시 종료 영역으로 옮긴다. */
function syncExpiredCards(){
  const now=Date.now();
  let changed=false;
  VOTES.forEach(v=>{
    if(v.closed||!Number.isFinite(v.closesAt))return;
    const remaining=v.closesAt-now;
    if(remaining<=0){
      v.closed=true;
      v.hours=0;
      changed=true;
      return;
    }
    const hours=Math.max(1,Math.ceil(remaining/3600000));
    if(v.hours!==hours){ v.hours=hours; changed=true; }
  });
  if(changed){
    if(modalState.i!==null) updateModalVote();
    renderGrid();
    renderClosedGrid();
  }
}
const TONE_PALETTE=[['#332e2a','#75695c'],['#2c2c2e','#5f5f63'],['#302f2c','#6a655c'],
  ['#2b2c2d','#585d60'],['#33322d','#736c5e'],['#2e2a2c','#5c5459']];
const randomTone=()=>TONE_PALETTE[Math.floor(Math.random()*TONE_PALETTE.length)];

const $=(s,el=document)=>el.querySelector(s);
const $$=(s,el=document)=>[...el.querySelectorAll(s)];
const fmtWon=n=>Number.isFinite(n)?n.toLocaleString('ko-KR')+'원':'가격 정보 없음';
const fmtHours=h=>Number.isFinite(h)?(h>=24?Math.round(h/24)+'일':h+'시간'):'기간 정보 없음';
const fmtNum=n=>n.toLocaleString('ko-KR');
/* 등록할 때 고른 스타일 이름 — 고르지 않았으면 빈 문자열 */
const styleNameOf=v=>(v&&Array.isArray(v.st)?v.st:[])
  .map(id=>STYLES.find(x=>x.id===id)?.n||id).find(Boolean)||'';
const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
/* 비슷한 사용자들의 살 비율. 표본이 없으면 null — 숫자를 만들어 내지 않는다. */
const simA=v=>v.simHas?v.simPct:null;
const satisfaction=v=>clamp(v.taste+Math.round((v.base-70)/5),30,99);
/* ── 댓글 시드 데이터 ─────────────────────────────────── */
/* rk: 작성자 등급(0~4) — 아바타 링(rkPaintAv)이 여기서 색을 가져온다
   job: 관리자 승인이 끝난 직업 — 닉네임 오른쪽 배지. 없으면 Basic(검정) */
const COMMENT_SEED=[
 {name:'민지', tag:0, rk:1, job:'Basic', text:'실물이 훨씬 예뻐요, 색감도 안 뜨고 좋았어요.', time:'2시간 전'},
 {name:'현우', tag:1, rk:3, job:'MD', text:'핏이 생각보다 커요. 한 사이즈 다운 추천드려요.', time:'4시간 전'},
 {name:'소은', tag:0, rk:0, job:'Student', text:'가격 대비 소재가 꽤 괜찮은 편이에요.', time:'6시간 전'},
 {name:'재훈', tag:null, rk:2, job:'Basic', text:'구매 전에 후기 더 보고 싶어요, 다들 어떠세요?', time:'9시간 전'},
 {name:'다인', tag:0, rk:4, job:'Stylist', text:'재구매 의사 있어요! 세탁 후에도 변형 없었어요.', time:'11시간 전'},
 {name:'유진', tag:1, rk:1, job:'Creator', text:'다음 시즌엔 색상이 더 다양하게 나왔으면 좋겠어요.', time:'24시간 전'},
 {name:'태윤', tag:0, rk:2, job:'Buyer', text:'매장에서 직접 보고 왔는데 사진보다 훨씬 낫습니다.', time:'27시간 전'},
 {name:'하은', tag:1, rk:0, job:'Basic', text:'배송이 좀 느렸어요, 아이템 자체는 무난해요.', time:'48시간 전'}
];
function seedComments(i){
  const out=[];
  for(let k=0;k<3;k++) out.push(COMMENT_SEED[(i*3+k)%COMMENT_SEED.length]);
  return out;
}
let COMMENT_UID=1;
const nextCommentId=()=>COMMENT_UID++;
/* 시드 댓글을 각 아이템의 실제 comments 배열로 한 번만 옮겨 담아서
   (신고/삭제 등) 개별 조작이 가능하게 만든다. 이후 새로 만든 게시글은
   비어있는 comments 배열을 그대로 유지한다. */
VOTES.forEach((v,i)=>{
  if(v.comments.length===0&&!v.youtubeId){
    v.comments=seedComments(i).map(c=>({...c, id:nextCommentId()}));
  }else{
    v.comments=v.comments.map(c=>({...c, id:c.id||nextCommentId()}));
  }
});

/* ── 작성자 사연 시드 ─────────────────────────────────── */
const NOTE_POOL=[
 {name:'benni_92', text:'평소에는 심플한 스타일을 입는데 이런 스타일에 도전해보고 싶어서 올려봅니다.'},
 {name:'ju_da', text:'제 눈에는 예쁜데 다른 분들 의견은 어떨지 궁금해서 올려봅니다.'},
 {name:'minsu.k', text:'이 가격에 구매하는 거 어떻게 생각하시는지 궁금해서 올려봅니다.'},
 {name:'hyeree', text:'친구가 추천해준 아이템인데 저한테 어울릴지 감이 안 잡혀서 올려봅니다.'},
 {name:'wonjin_c', text:'세일 마지막 날이라 고민 중인데, 사도 후회 안 할지 봐주세요.'}
];
function noteFor(i){ return NOTE_POOL[i%NOTE_POOL.length]; }

function orderFor(tab){
  let idx=VOTES.map((_,i)=>i).filter(i=>!VOTES[i].deleted);
  if(tab==='result'){
    /* 결과보기: 마감된(투표 종료) 게시글만 */
    return idx.filter(i=>VOTES[i].closed).sort((a,b)=>VOTES[b].votes-VOTES[a].votes);
  }
  /* 그 외 탭은 진행 중인 게시글만 노출 */
  idx=idx.filter(i=>!VOTES[i].closed);
  if(tab==='closing'){
    /* 마감임박: 진행 중인 게시글을 실제 마감 시각이 가까운 순서로 */
    return idx.sort((a,b)=>VOTES[a].closesAt-VOTES[b].closesAt||VOTES[b].createdAt-VOTES[a].createdAt);
  }
  if(tab==='popular'){
    /* 인기순: 참여수(투표수) 많은 순 */
    return idx.sort((a,b)=>VOTES[b].votes-VOTES[a].votes);
  }
  if(tab==='taste'){
    /* 내 취향: 취향 매칭도 높은 순 */
    const matched=idx.filter(i=>VOTES[i].tasteMatch>0);
    return (matched.length?matched:idx).sort((a,b)=>
      VOTES[b].tasteMatch-VOTES[a].tasteMatch||VOTES[b].taste-VOTES[a].taste);
  }
  /* 최신순: 가장 최근에 등록된 게시글 먼저 */
  return idx.sort((a,b)=>VOTES[b].createdAt-VOTES[a].createdAt||VOTES[b].seq-VOTES[a].seq);
}

function plateStyle(v){
  return v.imgURL
    ? `background-image:url('${v.imgURL}');background-size:cover;background-position:center`
    : `background:linear-gradient(150deg,${v.tone[0]},${v.tone[1]})`;
}

function cardHTML(i){
  const v=VOTES[i];
  const buyOn=v.voted===0, noOn=v.voted===1;
  const votesShown=v.votes;
  const capText=v.closed
    ? `${fmtNum(votesShown)}표 · 투표 종료`
    : `${fmtNum(votesShown)}표 · 마감까지 ${fmtHours(v.hours)}${v.voted!==null?' · <em>투표함</em>':''}`;
  const btnsHTML=v.closed
    ? `<div class="closedNote">투표가 종료됐어요</div>`
    : `<div class="smBtns">
        <button class="buy${buyOn?' picked':''}" data-vote="0">살!</button>
        <button class="${noOn?'picked':''}" data-vote="1">말?</button>
      </div>`;
  return `
  <div class="voteCard" data-i="${i}">
    <div class="fig">
      <div class="plate" style="${plateStyle(v)}"></div>
      <div class="vig"></div>
      <span class="pricep">${fmtWon(v.p)}</span>
      <span class="tagp"><b>${escapeHtml(v.b)}</b></span>
    </div>
    <div class="body">
      <h4>${escapeHtml(v.t)}</h4>
      <div class="cap">${capText}</div>
      <div class="smBar"><i class="buy" data-w="${v.a}" style="width:${v.a}%"><span>살 ${v.a}%</span></i><i class="no" data-w="${100-v.a}" style="width:${100-v.a}%"><span>${100-v.a}% 말</span></i></div>
      ${btnsHTML}
    </div>
  </div>`;
}

const PAGE_SIZE=8;
const state={tab:'popular', page:1};

function renderGrid(){
  /* ★ '내 취향'은 로그인해야 고를 수 있다.
       예전에는 비로그인일 때 tasteMatch 가 전부 0 이라 orderFor 의
       `matched.length?matched:idx` 가 **전체 카드로 떨어져**, 로그아웃 상태에서도
       내 취향 추천이 있는 것처럼 보였다. 맞지 않는 것을 맞는다고 쓰지 않는다. */
  const gate=$('#smGate'), grid0=$('#voteGrid'), pager0=$('#pager');
  const locked=state.tab==='taste'&&!AUTH.in;
  if(gate)gate.hidden=!locked;
  if(locked){
    if(grid0)grid0.innerHTML='';
    if(pager0)pager0.innerHTML='';
    return;
  }
  const order=orderFor(state.tab);
  const totalPages=Math.max(1,Math.ceil(order.length/PAGE_SIZE));
  if(state.page>totalPages) state.page=totalPages;
  const start=(state.page-1)*PAGE_SIZE;
  const pageItems=order.slice(start,start+PAGE_SIZE);

  const grid=$('#voteGrid');
  grid.innerHTML=pageItems.map(cardHTML).join('');
  attachCardHandlers(grid);
  smCardsIn(grid);
  renderPager(totalPages);
}

/* ══════════════════════════════════════════════════════════
   살!말? 모션
   ----------------------------------------------------------
   카드가 한 장씩 올라오고, 그 뒤를 살/말 막대가 따라 찬다.
   투표하면 막대가 스프링으로 밀려가고 누른 버튼이 한 번 눌린다.
   마감이 임박한 카드만 시간 표시가 조용히 뛴다 — 나머진 가만히 둔다.
   ══════════════════════════════════════════════════════════ */
function smCardsIn(root){
  const cards=$$('.voteCard',root||document);
  if(!cards.length)return;
  const bars=$$('.smBar i',root||document);
  if(!HAS_A){
    cards.forEach(c=>c.classList.add('in'));
    smBarFill(bars);
    smUrgent(root); return;
  }
  aUtils.remove(cards);
  cards.forEach(c=>{ c.classList.add('in'); c.style.transform=''; c.style.opacity='' });
  aUtils.set(cards,{opacity:0,translateY:16,scale:.985});
  aAnimate(cards,{opacity:[0,1],translateY:[16,0],scale:[.985,1],
    duration:760,delay:aStagger(52),ease:aSpring({stiffness:88,damping:16}),
    /* 끝나면 인라인 transform 을 지운다 — 남겨두면 :hover 의 들어올림이 먹히지 않는다 */
    onComplete:()=>cards.forEach(c=>{c.style.transform='';c.style.opacity=''})});
  smBarFill(bars,{start:180,step:26});
  smUrgent(root);
}
/* 마감 6시간 안쪽인 카드에만 표시를 남긴다 */
function smUrgent(root){
  $$('.voteCard',root||document).forEach(c=>{
    const v=VOTES[+c.dataset.i];
    c.classList.toggle('urgent', !!v && !v.closed && v.hours>0 && v.hours<=6);
  });
}
/* 투표 순간 — 막대가 밀려가고 누른 버튼이 한 번 들어갔다 나온다 */
function smVoteBeat(card,side){
  if(!HAS_A||!card)return;
  const btn=$$('.smBtns button',card)[side];
  if(btn)aAnimate(btn,{keyframes:[{scale:.94,duration:120,ease:'out(2)'},
    {scale:1,duration:480,ease:aSpring({stiffness:170,damping:11})}]});
  const fig=$('.fig',card);
  if(fig)aAnimate(fig,{keyframes:[{scale:1.015,duration:180,ease:'out(2)'},
    {scale:1,duration:560,ease:aSpring({stiffness:90,damping:14})}]});
}

function renderPager(totalPages){
  const pager=$('#pager');
  if(totalPages<=1){ pager.innerHTML=''; return; }
  let nums='';
  for(let p=1;p<=totalPages;p++){
    nums+=`<button data-page="${p}" class="${p===state.page?'on':''}">${p}</button>`;
  }
  pager.innerHTML=`
    <button class="pagerBtn" id="pagerPrev" ${state.page===1?'disabled':''} aria-label="이전 페이지">←</button>
    <div class="pagerNums">${nums}</div>
    <button class="pagerBtn" id="pagerNext" ${state.page===totalPages?'disabled':''} aria-label="다음 페이지">→</button>`;
  $('#pagerPrev').onclick=()=>{ state.page--; renderGrid(); scrollToGrid(); };
  $('#pagerNext').onclick=()=>{ state.page++; renderGrid(); scrollToGrid(); };
  $$('.pagerNums button',pager).forEach(btn=>{
    btn.onclick=()=>{ state.page=+btn.dataset.page; renderGrid(); scrollToGrid(); };
  });
}

function scrollToGrid(){
  $('.voteSection').scrollIntoView({behavior:'smooth',block:'start'});
}

/* ── 마감된 투표 — 4개씩, 점 3개를 눌러 직접 이동하는 정적 섹션 ── */
const CLOSED_PAGE_SIZE=4;
const closedState={page:0};

function closedItems(){
  return VOTES.map((_,i)=>i).filter(i=>VOTES[i].closed&&!VOTES[i].deleted);
}

function renderClosedGrid(){
  const items=closedItems();
  const totalPages=Math.max(1,Math.ceil(items.length/CLOSED_PAGE_SIZE));
  if(closedState.page>=totalPages) closedState.page=0;
  const start=closedState.page*CLOSED_PAGE_SIZE;
  const pageItems=items.slice(start,start+CLOSED_PAGE_SIZE);

  const grid=$('#closedGrid');
  grid.innerHTML=pageItems.map(cardHTML).join('');
  attachCardHandlers(grid);
  requestAnimationFrame(()=>{
    $$('.voteCard',grid).forEach((c,k)=>setTimeout(()=>c.classList.add('in'),k*55));
  });
  renderClosedDots(totalPages);
}

function renderClosedDots(totalPages){
  const dots=$('#closedDots');
  if(totalPages<=1){ dots.innerHTML=''; return; }
  dots.innerHTML=Array.from({length:totalPages},(_,p)=>
    `<span class="dot${p===closedState.page?' on':''}" data-page="${p}"></span>`).join('');
  $$('.dot',dots).forEach(d=>{
    d.addEventListener('click',()=>{
      closedState.page=+d.dataset.page;
      renderClosedGrid();
    });
  });
}

function updateCard(i){
  const card=$(`.voteCard[data-i="${i}"]`);
  if(!card)return;
  const v=VOTES[i];
  const bar=$('.smBar',card), buyBar=$('.buy',bar), noBar=$('.no',bar);
  buyBar.innerHTML='<span>살 '+v.a+'%</span>'; noBar.innerHTML='<span>'+(100-v.a)+'% 말</span>';
  buyBar.dataset.w=v.a; noBar.dataset.w=100-v.a;   /* 다시 그릴 때의 목표값도 같이 옮긴다 */
  buyBar.classList.remove('tight'); noBar.classList.remove('tight');
  if(HAS_A){
    aUtils.remove(buyBar);
    aAnimate(buyBar,{width:v.a+'%',duration:820,ease:aSpring({stiffness:104,damping:15}),
      onComplete:()=>smBarLabels([buyBar,noBar])});
  }else{ buyBar.style.width=v.a+'%'; smBarLabels([buyBar,noBar]) }
  noBar.style.removeProperty('width');
  $$('.smBtns button',card).forEach(btn=>{
    const side=+btn.dataset.vote;
    btn.classList.toggle('picked', v.voted===side);
  });
  const votesShown=v.votes;
  $('.cap',card).innerHTML=`${fmtNum(votesShown)}표 · 마감까지 ${fmtHours(v.hours)}${v.voted!==null?' · <em>투표함</em>':''}`;
}

function castVote(i,side){
  if(!requireAuth())return;
  const v=VOTES[i];
  const before=v.voted;
  const after=before===side?null:side;
  if(before===0)v.baseSal=Math.max(0,v.baseSal-1);
  if(before===1)v.baseMal=Math.max(0,v.baseMal-1);
  if(after===0)v.baseSal++;
  if(after===1)v.baseMal++;
  v.voted=after;
  v.votes=v.baseSal+v.baseMal;
  v.a=v.votes?Math.round(v.baseSal*100/v.votes):50;
  updateCard(i);
  smVoteBeat($(`.voteCard[data-i="${i}"]`), side);
  saveVote({ cardKey:v.cardKey, title:v.t, brand:v.b,
    style:styleNameOf(v), choice:v.voted===null?null:(v.voted===0?'BUY':'PASS') })
    .then(r=>{ if(r&&Number.isFinite(+r.vote_count))ME.votes=+r.vote_count; });
}

function attachCardHandlers(root=document){
  $$('.voteCard',root).forEach(card=>{
    const i=+card.dataset.i;
    $$('.smBtns button',card).forEach(btn=>{
      btn.onclick=(e)=>{ e.stopPropagation(); castVote(i,+btn.dataset.vote); };
    });
    card.addEventListener('click',(e)=>{
      if(e.target.closest('.smBtns'))return;
      openModal(i);
    });
  });
}

/* ============================================================
   신고 / 삭제 컨텍스트 메뉴 — 카드와 댓글에서 공용으로 사용
   ============================================================ */
let ctxTarget=null; /* {type:'card', i} | {type:'comment', i, commentId} */

function openCtxMenu(triggerEl, target){
  ctxTarget=target;
  const menu=$('#ctxMenu');
  const deleteButton=$('[data-action="delete"]',menu);
  const reportButton=$('[data-action="report"]',menu);
  if(target.type==='card'){
    const mine=Boolean(VOTES[target.i]?.mine);
    deleteButton.hidden=!VOTES[target.i]?.deletable;
    reportButton.hidden=mine;
  }else{
    const comment=VOTES[target.i]?.comments.find(item=>item.id===target.commentId);
    const mine=Boolean(comment?.me);
    deleteButton.hidden=!mine;
    reportButton.hidden=mine;
  }
  const r=triggerEl.getBoundingClientRect();
  const mw=menu.offsetWidth||150, mh=menu.offsetHeight||90;
  const vw=window.innerWidth, vh=window.innerHeight, pad=10;
  let left=r.right-mw, top=r.bottom+6;
  if(left<pad) left=pad;
  if(left+mw>vw-pad) left=vw-pad-mw;
  if(top+mh>vh-pad) top=r.top-mh-6;
  menu.style.left=left+'px';
  menu.style.top=top+'px';
  menu.classList.add('on');
}
function closeCtxMenu(){
  $('#ctxMenu').classList.remove('on');
  ctxTarget=null;
}
async function deleteCard(i){
  if(!VOTES[i]?.deletable){ showToast('직접 등록한 내 카드만 삭제할 수 있어요.'); return; }
  try{
    await deleteVoteCard(VOTES[i].id);
    VOTES[i].deleted=true;
    if(modalState.i===i) closeModal();
    if(VOTES[i].closed){ renderClosedGrid(); }
    else renderGrid();
    showToast('게시글이 삭제됐어요.');
  }catch(error){ showToast(error.message||'카드를 삭제하지 못했습니다.'); }
}
async function deleteComment(i,commentId){
  if(i===null)return;
  const comment=VOTES[i]?.comments.find(c=>c.id===commentId);
  if(!comment?.me){ showToast('내가 작성한 댓글만 삭제할 수 있어요.'); return; }
  try{
    await deleteVoteComment(commentId);
    VOTES[i].comments=VOTES[i].comments.filter(c=>c.id!==commentId);
    if(modalState.i===i)renderComments();
    showToast('댓글이 삭제됐어요.');
  }catch(error){ showToast(error.message||'댓글을 삭제하지 못했습니다.'); }
}
$$('#ctxMenu button').forEach(btn=>{
  btn.addEventListener('click',async()=>{
    const action=btn.dataset.action;
    const target=ctxTarget;
    closeCtxMenu();
    if(!target)return;
    if(action==='report'){
      const targetType=target.type==='card'?'CARD':'COMMENT';
      const targetId=target.type==='card'?VOTES[target.i]?.id:target.commentId;
      try{
        const saved=await reportVoteTarget({targetType,targetId});
        showToast(saved?.created
          ? (targetType==='CARD'?'카드 신고가 접수됐어요.':'댓글 신고가 접수됐어요.')
          : '이미 접수한 신고예요.');
      }catch(error){ showToast(error.message||'신고를 접수하지 못했습니다.'); }
      return;
    }
    if(action==='delete'){
      if(target.type==='card') deleteCard(target.i);
      else deleteComment(target.i,target.commentId);
    }
  });
});
document.addEventListener('click',e=>{
  const menu=$('#ctxMenu');
  if(!menu.classList.contains('on'))return;
  if(e.target.closest('#ctxMenu')||e.target.closest('.cardMenuBtn')||e.target.closest('.cMenuBtn'))return;
  closeCtxMenu();
});
window.addEventListener('resize',()=>{ if($('#ctxMenu').classList.contains('on')) closeCtxMenu(); });
$('#commentsList').addEventListener('click',e=>{
  const btn=e.target.closest('.cMenuBtn');
  if(!btn)return;
  e.stopPropagation();
  const commentId=+btn.dataset.commentId;
  const already=$('#ctxMenu').classList.contains('on') && ctxTarget && ctxTarget.type==='comment' && ctxTarget.commentId===commentId;
  already ? closeCtxMenu() : openCtxMenu(btn,{type:'comment', i:modalState.i, commentId});
});
$('#modalMenuBtn').addEventListener('click',e=>{
  e.stopPropagation();
  if(modalState.i===null)return;
  const i=modalState.i;
  const btn=e.currentTarget;
  const already=$('#ctxMenu').classList.contains('on') && ctxTarget && ctxTarget.type==='card' && ctxTarget.i===i;
  already ? closeCtxMenu() : openCtxMenu(btn,{type:'card', i});
});

/* ============================================================
   상세 모달 — 이미지 · 투표현황(전체/유사세그먼트) · 댓글 · AI 리포트
   ============================================================ */
const modalState={i:null,version:0};
const pendingCommentCards=new Set();

function escapeHtml(s){
  return s.replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

function resetCommentComposer(card=null){
  const input=$('#commentInput');
  const sendButton=$('#commentSend');
  const isClosed=Boolean(card?.closed);
  const isPending=Boolean(card&&pendingCommentCards.has(card.id));
  input.value='';
  input.disabled=isClosed||isPending;
  sendButton.disabled=isClosed||isPending;
  input.placeholder=isClosed?'마감된 투표에는 댓글을 달 수 없어요':'댓글을 남겨보세요';
}

function openModal(i){
  if(!requireAuth())return;
  modalState.version+=1;
  modalState.i=i;
  const v=VOTES[i];
  resetCommentComposer(v);
  const plate=$('#modalPlate');
  if(v.imgURL){
    plate.style.background='';
    plate.style.backgroundImage=`url('${v.imgURL}')`;
    plate.style.backgroundSize='cover';
    plate.style.backgroundPosition='center';
  }else{
    plate.style.backgroundImage='';
    plate.style.background=`linear-gradient(150deg,${v.tone[0]},${v.tone[1]})`;
  }
  $('#modalTitle').textContent=v.t;
  $('#modalBrand').textContent=v.b;
  $('#modalPrice').textContent=fmtWon(v.p);
  { const sn=styleNameOf(v); $('#modalStyleName').textContent=sn; $('#modalStyle').hidden=!sn; }
  const segmentTitle=$('#modalSegLabel').parentElement;
  segmentTitle.firstChild.textContent='나와 비슷한 사용자들';
  $('#modalSegLabel').textContent=' (체형 · 스타일 · 나이)';
  const note=v.authorNote||noteFor(i);
  $('#modalNoteName').textContent=note.name;
  $('#modalNote').textContent=note.text;
  closeAiModal();
  updateModalVote();
  renderComments();
  $('#modalOverlay').classList.add('on');
  document.body.style.overflow='hidden';
}
function closeModal(){
  $('#modalOverlay').classList.remove('on');
  document.body.style.overflow='';
  modalState.version+=1;
  modalState.i=null;
  resetCommentComposer();
  closeAiModal();
}

function updateModalVote(){
  const i=modalState.i; if(i===null)return;
  const v=VOTES[i];
  const votesShown=v.votes;
  $('#modalCntAll').textContent=v.closed
    ? `${fmtNum(votesShown)}표 · 투표 종료`
    : `${fmtNum(votesShown)}표 · 마감까지 ${fmtHours(v.hours)}`;
  /* 한쪽이 크게 이겨도 진 쪽 %가 잘려 사라지지 않게 tight 를 같이 걸어 둔다 */
  const setPair=(bar,a)=>{
    const b=$('.buy',bar), n=$('.no',bar);
    b.style.background='';
    b.style.width=a+'%';       b.innerHTML='<span>살 '+a+'%</span>';
    n.style.removeProperty('width'); n.innerHTML='<span>'+(100-a)+'% 말</span>';
    b.classList.toggle('tight',a<28); n.classList.toggle('tight',(100-a)<28);
  };
  setPair($('#modalBarAll'), v.a);
  /* 표본이 있을 때만 막대를 그린다. 없으면 막대를 감추고 이유를 쓴다. */
  const sim=simA(v), simBar=$('#modalBarSim'), simNote=$('#modalSimNote');
  if(sim==null){
    simBar.hidden=true;
    if(simNote){
      simNote.hidden=false;
      simNote.textContent=v.simReason||'아직 나와 비슷한 사용자가 이 카드에 투표하지 않았습니다.';
    }
  }else{
    simBar.hidden=false;
    if(simNote)simNote.hidden=true;
    setPair(simBar, sim);
  }

  if($('#aiChatBubble').classList.contains('on')) buildAIReport(i);
}

function buildAIReport(i){
  const v=VOTES[i], sim=simA(v), sat=satisfaction(v);
  const simTx=sim==null
    ? '나와 비슷한 사용자의 투표가 아직 없어 이 부분은 비교하지 못했습니다.'
    : `성별·체형·나이·취향이 겹치는 사용자 ${v.simUsers}명 중 ${sim}%가 구매에 동의했습니다.`;
  const verdictBuy=v.a>=55;
  const el=$('#aiVerdict');
  el.textContent=verdictBuy?'지금 사도 좋아요':'조금 더 지켜보세요';
  el.classList.toggle('buy',verdictBuy);
  $('#aiWhy').textContent=
    `전체 투표에서는 ${v.a>=50?'살':'말'} 의견이 우세합니다. `+
    `${simTx} `+
    `구매자 만족도는 ${sat}%로 ${sat>=80?'높은 편':sat>=60?'무난한 편':'다소 낮은 편'}입니다. `+
    (v.closed?'투표가 종료되어 최종 결과를 보여드립니다.':`마감까지 ${fmtHours(v.hours)} 남았습니다.`);
  $('#aiStats').innerHTML=`
    <div><div class="k">전체 살 비율</div><div class="v">${v.a}%</div></div>
    <div><div class="k">유사 세그먼트</div><div class="v">${sim==null?'–':sim+'%'}</div></div>
    <div><div class="k">구매자 만족도</div><div class="v">${sat}%</div></div>`;
}

function renderComments(){
  const i=modalState.i; if(i===null)return;
  const list=VOTES[i].comments;
  $('#commentCount').textContent=list.length;
  $('#commentsList').innerHTML=list.map(c=>{
    const rk=rkClamp(c.rk!=null?c.rk:0);
    return `
    <div class="cItem">
      <div class="cAvatar rkAv rk${rk+1}">${rkRingHTML(rk)}${rk>=3?'<b class="rkGloss"></b>':''}<span>${c.name[0]}</span></div>
      <div class="cBody">
        <div class="cHead">
          <b>${c.name}</b>${c.me ? (jobShown(ME) ? jobBadgeHTML(jobShown(ME)) : '') : jobBadgeHTML(c.job)}
          <span class="cTime">${c.time}</span>
          <button class="cMenuBtn" data-comment-id="${c.id}" aria-label="더보기">⋯</button>
        </div>
        <div class="cText">${escapeHtml(c.text)}</div>
      </div>
    </div>`;
  }).join('');
}

async function sendComment(){
  const i=modalState.i; if(i===null)return;
  const modalVersion=modalState.version;
  if(!requireAuth())return;
  const card=VOTES[i];
  if(card.closed){ showToast('마감된 투표에는 댓글을 달 수 없어요.'); return; }
  const ta=$('#commentInput');
  const sendButton=$('#commentSend');
  const text=ta.value.trim();
  if(!text)return;
  const cardId=card.id;
  if(pendingCommentCards.has(cardId))return;
  pendingCommentCards.add(cardId);
  ta.disabled=true;
  sendButton.disabled=true;
  try{
    const saved=await saveVoteComment({cardId,content:text});
    card.comments.unshift({
      name:'나',rk:ME.rank,job:jobShown(ME)||'Basic',me:true,text,time:'1시간 전',
      tag:saved?.choice==='BUY'?0:saved?.choice==='PASS'?1:null,id:saved?.id||nextCommentId()
    });
    if(modalState.i!==null && VOTES[modalState.i].id===cardId){
      if(modalState.version===modalVersion)ta.value='';
      renderComments();
      $('#commentsList').scrollTop=0;
    }
  }catch(error){ showToast(error.message||'댓글을 저장하지 못했습니다.'); }
  finally{
    pendingCommentCards.delete(cardId);
    if(modalState.i!==null && VOTES[modalState.i].id===cardId){
      ta.disabled=false;
      sendButton.disabled=false;
      ta.focus();
    }
  }
}

/* 모달 내 정적 요소 바인딩 (한 번만) */
$('#modalClose').addEventListener('click',closeModal);
$('#modalOverlay').addEventListener('click',e=>{ if(e.target.id==='modalOverlay') closeModal(); });
document.addEventListener('keydown',e=>{
  if(e.key!=='Escape')return;
  if($('#aiChatBubble').classList.contains('on')){ closeAiModal(); return; }
  if($('#createOverlay').classList.contains('on')){ closeCreateModal(); return; }
  if($('#modalOverlay').classList.contains('on')){ closeModal(); return; }
});

/* AI 살!말? 리포트 — 버튼 옆에 나란히 뜨는 말풍선 팝오버
   position:fixed 로 두고 버튼 위치를 기준으로 좌표를 계산해서
   모달 크기가 줄어도 항상 화면 안에서 버튼 옆(공간이 없으면 아래)에 붙는다 */
function positionAiBubble(){
  const btn=$('#aiBtn'), bubble=$('#aiChatBubble');
  const r=btn.getBoundingClientRect();
  const bw=bubble.offsetWidth||272, bh=bubble.offsetHeight||220;
  const vw=window.innerWidth, vh=window.innerHeight, pad=12;
  let left=r.right+10, top=r.top;
  if(left+bw>vw-pad){ left=Math.max(pad, r.left); top=r.bottom+10; }
  if(top+bh>vh-pad) top=Math.max(pad, vh-pad-bh);
  if(left+bw>vw-pad) left=Math.max(pad, vw-pad-bw);
  bubble.style.left=left+'px';
  bubble.style.top=top+'px';
}
function openAiModal(){
  if(modalState.i===null)return;
  buildAIReport(modalState.i);
  positionAiBubble();
  $('#aiChatBubble').classList.add('on');
}
function closeAiModal(){ $('#aiChatBubble').classList.remove('on'); }
$('#aiBtn').addEventListener('click',(e)=>{
  e.stopPropagation();
  $('#aiChatBubble').classList.contains('on') ? closeAiModal() : openAiModal();
});
$('#aiChatClose').addEventListener('click',(e)=>{ e.stopPropagation(); closeAiModal(); });
document.addEventListener('click',(e)=>{
  const bubble=$('#aiChatBubble');
  if(!bubble.classList.contains('on'))return;
  if(e.target.closest('#aiChatBubble')||e.target.closest('#aiBtn'))return;
  closeAiModal();
});
/* 왼쪽 컬럼을 스크롤하면 버튼 위치가 바뀌므로 팝오버는 닫는다 */
$('.modalLeft').addEventListener('scroll',()=>closeAiModal());
window.addEventListener('resize',()=>{ if($('#aiChatBubble').classList.contains('on')) closeAiModal(); });

$('#commentSend').addEventListener('click',sendComment);
$('#commentInput').addEventListener('keydown',e=>{
  if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){ e.preventDefault(); sendComment(); }
});

/* ── 탭 전환 ─────────────────────────────────────────── */
$$('#smTabs button').forEach(btn=>{
  btn.addEventListener('click',()=>{
    $$('#smTabs button').forEach(b=>b.classList.remove('on'));
    btn.classList.add('on');
    state.tab=btn.dataset.tab;
    state.page=1;
    renderGrid();
  });
});

/* ── 아이템 등록 토스트 ──────────────────────────────── */
let toastT;
function showToast(msg){
  const t=$('#toast');
  t.textContent=msg;
  t.classList.add('on');
  clearTimeout(toastT);
  toastT=setTimeout(()=>t.classList.remove('on'),2200);
}

/* ============================================================
   글쓰기 모달 — "살까말까 물어보기"
   ============================================================ */
/* ── 브랜드 검색 ──────────────────────────────────────
   치는 동안 맞는 브랜드를 아래 목록으로 보여 준다.
   목록에 없는 브랜드는 그대로 적어서 낼 수 있다 — 우리가 아는 브랜드만
   물어볼 수 있는 것이 아니기 때문이다.
   ↑↓ 로 옮기고 Enter 로 고르며 Esc 로 닫는다. */
const brandCombo=(function(){
  const input=$('#cBrand'), list=$('#cBrandList');
  let open=false, cursor=-1, shown=[];

  const norm=s=>String(s||'').toLowerCase().replace(/[\s'’·\-_.]+/g,'');
  function match(q){
    const n=norm(q);
    if(!n) return BRAND_LIST.slice(0,8);
    const starts=[], has=[];
    BRAND_LIST.forEach(b=>{
      const nb=norm(b);
      if(nb.startsWith(n)) starts.push(b);
      else if(nb.includes(n)) has.push(b);
    });
    return [...starts,...has].slice(0,8);
  }
  function paint(){
    list.innerHTML=shown.map((b,i)=>
      '<li role="option" class="cComboItem'+(i===cursor?' on':'')+'" data-brand="'+escapeHtml(b)+'"'+
      ' aria-selected="'+(i===cursor)+'">'+escapeHtml(b)+'</li>').join('');
  }
  function show(q){
    shown=match(q);
    if(!shown.length){ hide(); return; }
    cursor=-1; paint();
    list.hidden=false; open=true;
    input.setAttribute('aria-expanded','true');
  }
  function hide(){
    list.hidden=true; open=false; cursor=-1;
    input.setAttribute('aria-expanded','false');
  }
  function pick(b){ input.value=b; hide(); }
  function move(step){
    if(!open){ show(input.value); return; }
    if(!shown.length)return;
    cursor=(cursor+step+shown.length)%shown.length;
    paint();
    const on=list.querySelector('.cComboItem.on');
    if(on&&on.scrollIntoView)on.scrollIntoView({block:'nearest'});
  }

  input.addEventListener('input',()=>show(input.value));
  input.addEventListener('focus',()=>show(input.value));
  input.addEventListener('keydown',e=>{
    if(e.key==='ArrowDown'){ e.preventDefault(); move(1); return; }
    if(e.key==='ArrowUp'){ e.preventDefault(); move(-1); return; }
    if(e.key==='Enter'&&open&&cursor>=0){ e.preventDefault(); pick(shown[cursor]); return; }
    if(e.key==='Escape'&&open){ e.preventDefault(); e.stopPropagation(); hide(); }
  });
  /* mousedown 으로 잡는다 — click 은 input 의 blur 뒤라 목록이 이미 닫혀 있다 */
  list.addEventListener('mousedown',e=>{
    const li=e.target.closest('.cComboItem'); if(!li)return;
    e.preventDefault(); pick(li.dataset.brand);
  });
  document.addEventListener('click',e=>{
    if(!open)return;
    if(e.target.closest('#cBrandCombo'))return;
    hide();
  });
  return {hide};
})();

let createImgURL=null;
let createImgFile=null;
/* 스타일 드롭다운 — 스타일 페이지와 같은 핵심 스타일 10종을 그대로 쓴다 */
(function fillStyleSelect(){
  const sel=$('#cStyle'); if(!sel)return;
  sel.insertAdjacentHTML('beforeend',STYLES.map(s=>`<option value="${s.id}">${s.n}</option>`).join(''));
})();
function resetCreateForm(){
  $('#cTitle').value='';
  $('#cBrand').value='';
  brandCombo.hide();
  $('#cPrice').value='';
  if($('#cStyle')) $('#cStyle').value='';
  $('#cNote').value='';
  $('#imgInput').value='';
  if(createImgURL){ URL.revokeObjectURL(createImgURL); createImgURL=null; }
  createImgFile=null;
  $('#imgPreview').hidden=true;
  $('#imgPreview').src='';
  $('#imgDropInner').style.display='';
  $('#imgDrop').classList.remove('has-img');
}
function openCreateModal(draft){
  if(!requireAuth())return;
  resetCreateForm();
  if(draft&&typeof draft==='object'){
    $('#cTitle').value=String(draft.title||'').replace(/\s+/g,' ').trim().slice(0,120);
    /* 챗봇이 확인한 것만 채운다 — 확인하지 못한 칸은 비워 두고 사용자가 적는다 */
    if(draft.brand) $('#cBrand').value=String(draft.brand).replace(/\s+/g,' ').trim().slice(0,60);
    if(draft.price!=null&&String(draft.price).trim()!==''){
      const digits=String(draft.price).replace(/[^0-9]/g,'');
      if(digits) $('#cPrice').value=digits;
    }
    if(draft.image){
      createImgURL=String(draft.image);
      createImgFile=null;
      $('#imgPreview').src=createImgURL;
      $('#imgPreview').hidden=false;
      $('#imgDropInner').style.display='none';
      $('#imgDrop').classList.add('has-img');
    }
  }
  $('#createOverlay').classList.add('on');
  document.body.style.overflow='hidden';
}
function closeCreateModal(){
  $('#createOverlay').classList.remove('on');
  document.body.style.overflow='';
}
$('#addItemBtn').addEventListener('click',()=>openCreateModal());
$('#createClose').addEventListener('click',closeCreateModal);
$('#createOverlay').addEventListener('click',e=>{ if(e.target.id==='createOverlay') closeCreateModal(); });

$('#imgDrop').addEventListener('click',()=>$('#imgInput').click());
$('#imgInput').addEventListener('change',e=>{
  const file=e.target.files[0];
  if(!file)return;
  if(!['image/jpeg','image/png','image/webp'].includes(file.type)){
    e.target.value='';
    showToast('JPEG, PNG, WebP 이미지만 등록할 수 있어요.');
    return;
  }
  if(file.size>1024*1024){
    e.target.value='';
    showToast('이미지는 1MB 이하만 등록할 수 있어요.');
    return;
  }
  if(createImgURL) URL.revokeObjectURL(createImgURL);
  createImgFile=file;
  createImgURL=URL.createObjectURL(file);
  const img=$('#imgPreview');
  img.src=createImgURL;
  img.hidden=false;
  $('#imgDropInner').style.display='none';
  $('#imgDrop').classList.add('has-img');
});

$('#cPrice').addEventListener('input',()=>{
  $('#cPrice').value=$('#cPrice').value.replace(/[^0-9]/g,'');
});

const fileDataUrl=file=>new Promise((resolve,reject)=>{
  const reader=new FileReader();
  reader.onload=()=>resolve(String(reader.result||''));
  reader.onerror=()=>reject(new Error('이미지 파일을 읽지 못했습니다.'));
  reader.readAsDataURL(file);
});

$('#createSubmit').addEventListener('click',async()=>{
  const title=$('#cTitle').value.trim();
  const brand=$('#cBrand').value.replace(/\s+/g,' ').trim();
  const priceRaw=$('#cPrice').value.trim();
  const note=$('#cNote').value.trim();
  const style=$('#cStyle')?$('#cStyle').value:'';

  if(!title){ showToast('상품명을 입력해주세요'); return; }
  if(!brand){ showToast('브랜드를 입력해주세요'); return; }
  if(!priceRaw){ showToast('가격을 입력해주세요'); return; }

  const submit=$('#createSubmit');
  submit.disabled=true;
  const originalText=submit.textContent;
  submit.textContent='등록 중...';
  try{
    const styleName=STYLES.find(item=>item.id===style)?.n||'';
    const imageData=createImgFile?await fileDataUrl(createImgFile):'';
    const externalImage=!createImgFile&&createImgURL&&!createImgURL.startsWith('blob:')?createImgURL:'';
    const saved=await createVoteCard({
      title,brand,price:parseInt(priceRaw,10),description:note,
      tags:styleName?[styleName]:[],image_data_url:imageData,image_url:externalImage
    });
    VOTES.push(cardFromApi(saved,VOTES.length));
    if(!BRAND_LIST.includes(brand)) BRAND_LIST.push(brand);
    BRAND_LIST.sort();
    closeCreateModal();
    resetCreateForm();
    showToast('살까말까 물어보기 등록 완료!');
    state.tab='latest'; state.page=1;
    $$('#smTabs button').forEach(b=>b.classList.toggle('on',b.dataset.tab==='latest'));
    renderGrid();
  }catch(error){
    showToast(error.message||'카드를 저장하지 못했습니다.');
  }finally{
    submit.disabled=false;
    submit.textContent=originalText;
  }
});

/* ── 실시간 인원 카운터 미세 변동 ────────────────────── */
setInterval(()=>{
  const el=$('#liveCount');
  const cur=+el.textContent;
  const next=Math.max(96, cur+(Math.random()>0.5?1:-1));
  if(HAS_A){
    const o={v:cur};
    aAnimate(o,{v:next,duration:520,ease:'out(2)',
      onUpdate:()=>{ el.textContent=Math.round(o.v) }});
    aAnimate(el,{keyframes:[{translateY:-2,duration:150,ease:'out(2)'},
      {translateY:0,duration:420,ease:aSpring({stiffness:150,damping:12})}]});
  }else el.textContent=next;
},2600);

/* ── 초기 렌더 ───────────────────────────────────────── */
$('#voteGrid').innerHTML='<div class="smDataState">살!말? 데이터를 불러오는 중이에요.</div>';
loadVotes().then(()=>{
  syncExpiredCards();
  renderGrid();
  renderClosedGrid();
  setInterval(syncExpiredCards,30000);
}).catch(error=>{
  $('#voteGrid').innerHTML=`<div class="smDataState">${escapeHtml(error.message||'살!말? 데이터를 불러오지 못했습니다.')}</div>`;
  $('#closedGrid').innerHTML='';
});

/* 이 화면을 다시 열 때 등장 모션만 되돌려 준다.
   salmalBoot 은 한 번만 도니까, 바깥에서 부를 손잡이를 남긴다.
   다시 그리지 않고 모션만 태워서 이미 누른 투표는 그대로 남는다. */
window.smReplay=()=>{ smCardsIn($('#voteGrid')); smCardsIn($('#closedGrid')) };
/* 바깥(내 피드 등)에서 특정 탭으로 열어 달라고 할 때 쓴다 */
window.smGoTab=(tab)=>{
  const b=$$('#smTabs button').filter(x=>x.dataset.tab===tab)[0];
  if(!b)return;
  $$('#smTabs button').forEach(x=>x.classList.remove('on'));
  b.classList.add('on');
  state.tab=tab; state.page=1; renderGrid();
};
/* 챗봇의 '물어보기' 버튼에서 상품명·첨부 사진을 그대로 이어받는다. */
window.smOpenCreate=(draft)=>{
  window.__salmalDraft=null;
  openCreateModal(draft||{});
};

}
