import { $ } from '../../../core/static/js/dom.js';
import { feedbackList, saveFeedback } from '../../../account/static/js/account_api.js';

/* ══════════════════════════════════════════════════════════════
   살!말? 사후 피드백 (2026-09-19)
   --------------------------------------------------------------
   내가 올린 카드의 투표가 마감되면 글쓴이에게 결과를 묻는다.
     구매 여부 · 만족도(1~5) · 투표가 도움이 됐나 · 한 줄 후기
   · 살말 페이지에 들어오면 아직 안 쓴 피드백이 있을 때 팝업을 띄운다(fbPromptOnce).
     '나중에'를 누르면 이번 접속(sessionStorage) 동안은 같은 카드로 다시 묻지 않는다.
   · 마이페이지 '살말 피드백' 패널이 작성 현황을 보여 준다(fbPanelRender).
   · 알림(팀원 작업)은 서버의 pending_feedback_cards() / GET /api/salmal/feedback 을 쓰면 된다.
   저장한 결과는 투표자들의 '적중'(연속 적중 · 여론 조력자 배지)에 쓰인다.
   ══════════════════════════════════════════════════════════════ */

const esc=v=>String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const SNOOZE_KEY='feedit.fb.snooze';
const PURCHASE=[['BOUGHT','샀어요'],['SKIPPED','안 샀어요'],['UNDECIDED','아직 고민 중']];

function snoozed(){ try{ return JSON.parse(sessionStorage.getItem(SNOOZE_KEY)||'[]') }catch(e){ return [] } }
function snooze(id){ try{ sessionStorage.setItem(SNOOZE_KEY, JSON.stringify([...new Set([...snoozed(), id])])) }catch(e){} }

let fbState={loaded:false, pending:[], done:[], error:''};
export const fbPendingCount=()=>fbState.pending.length;

export async function fbLoad(){
  try{
    const d=await feedbackList();
    fbState={loaded:true, pending:d.pending||[], done:d.done||[], error:''};
  }catch(e){
    fbState={loaded:true, pending:[], done:[], error:e.message||'피드백 현황을 불러오지 못했습니다.'};
  }
  document.dispatchEvent(new CustomEvent('feedit:feedback'));
  return fbState;
}

function modalRoot(){
  let m=$('#fbModal');
  if(m)return m;
  document.body.insertAdjacentHTML('beforeend','<div class="fbModal" id="fbModal" role="dialog" aria-modal="true" aria-labelledby="fbTitle"><div class="fbCard"></div></div>');
  m=$('#fbModal');
  m.addEventListener('click',e=>{ if(e.target===m)fbClose(); });
  return m;
}
export function fbClose(){ const m=$('#fbModal'); if(m)m.classList.remove('on','in'); }

/* 카드 한 장의 피드백 창. row = {card_id, title, image_url, vote_summary, feedback}
   ★ 2026-09-19 디자인 개편 — 한 번에 한 질문씩 드러나는 단계형(구매 여부 → 만족도 → 도움 여부 → 후기).
     제목·질문을 h3/b 같은 맨 태그로 두지 않는다 — 전역 스타일·등장 모션에 먹혀 글자가 사라졌다. */
const SCALE_Q={BOUGHT:'사길 잘했나요?',SKIPPED:'안 사길 잘했나요?'};
const SCALE_ENDS={BOUGHT:['후회해요','아주 만족'],SKIPPED:['사는 게 나았어요','안 사길 잘했어요']};
export function fbOpen(row, { onSaved, askLater=true } = {}){
  const m=modalRoot(), card=m.querySelector('.fbCard');
  const fb=row.feedback||{};
  const st={purchase:fb.purchase||'', satisfaction:fb.satisfaction||null,
            helpful:fb.helpful??null, comment:fb.comment||''};
  const vs=row.vote_summary||{};
  const buy=Number.isFinite(+vs.buy_pct)?Math.round(+vs.buy_pct):null;
  const paint=()=>{
    const scaleOn=st.purchase==='BOUGHT'||st.purchase==='SKIPPED';
    const helpOn=st.purchase&&(st.purchase==='UNDECIDED'||st.satisfaction);
    const ends=SCALE_ENDS[st.purchase]||['',''];
    card.innerHTML=
      '<button type="button" class="fbX" data-fb="close" aria-label="닫기">'+
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button>'+
      '<div class="fbTop">'+
        '<div class="fbThumb">'+(row.image_url?'<img src="'+esc(row.image_url)+'" alt="">':'')+'</div>'+
        '<div class="fbTopTx">'+
          '<span class="fbEyebrow">투표 마감 · 결과 공유</span>'+
          '<span class="fbTitle" id="fbTitle">'+esc(row.title||'내 카드')+'</span>'+
          (buy!=null
            ? '<div class="fbBar"><i style="width:'+buy+'%"></i></div>'+
              '<span class="fbBarTx"><em>살 '+buy+'%</em><em>말 '+(100-buy)+'%</em><em class="n">'+(vs.total||0)+'표</em></span>'
            : '')+
        '</div>'+
      '</div>'+
      '<div class="fbStep">'+
        '<span class="fbLabel">결국 어떻게 하셨나요?</span>'+
        '<div class="fbSeg c3">'+PURCHASE.map(([k,l])=>'<button type="button" data-p="'+k+'" class="'+(st.purchase===k?'on':'')+'">'+l+'</button>').join('')+'</div>'+
      '</div>'+
      (scaleOn
        ? '<div class="fbStep">'+
            '<span class="fbLabel">'+SCALE_Q[st.purchase]+'</span>'+
            '<div class="fbScale">'+[1,2,3,4,5].map(n=>'<button type="button" data-s="'+n+'" class="'+(st.satisfaction===n?'on':'')+'" aria-label="'+n+'점">'+n+'</button>').join('')+'</div>'+
            '<div class="fbEnds"><span>'+ends[0]+'</span><span>'+ends[1]+'</span></div>'+
          '</div>'
        : '')+
      (helpOn
        ? '<div class="fbStep">'+
            '<span class="fbLabel">모두의 투표가 도움이 됐나요?</span>'+
            '<div class="fbSeg c2">'+
              '<button type="button" data-h="1" class="'+(st.helpful===true?'on':'')+'">도움이 됐어요</button>'+
              '<button type="button" data-h="0" class="'+(st.helpful===false?'on':'')+'">별로였어요</button></div>'+
          '</div>'+
          '<div class="fbStep">'+
            '<span class="fbLabel">한 줄 후기 <small>선택</small></span>'+
            '<div class="fbInput"><input type="text" maxlength="100" placeholder="실물 색이 더 예뻐요, 한 치수 크게 추천해요" value="'+esc(st.comment)+'">'+
              '<span class="fbCount">'+st.comment.length+'/100</span></div>'+
          '</div>'
        : '')+
      '<div class="fbErr" hidden></div>'+
      '<div class="fbActs">'+
        (askLater?'<button type="button" class="fbLater" data-fb="later">나중에 할게요</button>':'<span></span>')+
        '<button type="button" class="fbSave" data-fb="save"'+(st.purchase?'':' disabled')+'>'+(row.feedback?'수정하기':'결과 남기기')+'</button>'+
      '</div>';
  };
  paint();
  card.oninput=e=>{
    if(!e.target.matches('input'))return;
    st.comment=e.target.value;
    const c=card.querySelector('.fbCount'); if(c)c.textContent=st.comment.length+'/100';
  };
  card.onclick=async e=>{
    const b=e.target.closest('button'); if(!b)return;
    if(b.dataset.p){ st.purchase=b.dataset.p; if(st.purchase==='UNDECIDED')st.satisfaction=null; paint(); return; }
    if(b.dataset.s){ st.satisfaction=+b.dataset.s; paint(); return; }
    if(b.dataset.h){ st.helpful=b.dataset.h==='1'; paint(); return; }
    if(b.dataset.fb==='close'){ fbClose(); return; }
    if(b.dataset.fb==='later'){ snooze(row.card_id); fbClose(); return; }
    if(b.dataset.fb==='save'){
      const err=card.querySelector('.fbErr');
      const fail=msg=>{ err.textContent=msg; err.hidden=false; };
      if(!st.purchase)return fail('구매 여부를 골라 주세요.');
      if(st.purchase!=='UNDECIDED'&&!st.satisfaction)return fail('만족도를 골라 주세요.');
      b.disabled=true; b.textContent='저장 중…';
      try{
        const saved=await saveFeedback({cardId:row.card_id, purchase:st.purchase, satisfaction:st.satisfaction,
                            helpful:st.helpful, comment:st.comment});
        fbApplyLocal(row, saved&&saved.feedback);   /* 목록을 서버 응답 전에 바로 바꾼다 */
        fbClose();
        if(onSaved)onSaved();
        fbLoad();                                   /* 뒤에서 서버 값으로 한 번 더 맞춘다 */
      }catch(ex){ fail(ex.message||'저장하지 못했습니다.'); b.disabled=false; b.textContent=row.feedback?'수정하기':'결과 남기기'; }
    }
  };
  m.classList.add('on');
  requestAnimationFrame(()=>m.classList.add('in'));
}
/* 저장 직후 — 작성 전 → 작성 완료로 바로 옮기고 화면에 알린다 */
function fbApplyLocal(row, feedback){
  if(!feedback)return;
  const id=row.card_id;
  const base=[...fbState.pending,...fbState.done].find(r=>r.card_id===id)||row;
  const done={...base, feedback};
  fbState={...fbState, loaded:true,
    pending:fbState.pending.filter(r=>r.card_id!==id),
    done:[done,...fbState.done.filter(r=>r.card_id!==id)]};
  document.dispatchEvent(new CustomEvent('feedit:feedback'));
}

/* 살말 페이지 진입 시 — 아직 안 쓴 피드백이 있으면 하나만 묻는다 */
export async function fbPromptOnce(){
  const s=await fbLoad();
  const skip=new Set(snoozed());
  const next=s.pending.find(r=>!skip.has(r.card_id));
  if(next)fbOpen(next,{askLater:true, onSaved:()=>window.smReloadVotes&&window.smReloadVotes()});
}

/* 마이페이지 패널 */
export function fbPanelRender(host){
  if(!host)return;
  const s=fbState;
  if(!s.loaded){ host.innerHTML='<div class="fbEmpty">불러오는 중입니다.</div>'; return; }
  if(s.error){ host.innerHTML='<div class="fbEmpty">'+esc(s.error)+'</div>'; return; }
  if(!s.pending.length&&!s.done.length){
    host.innerHTML='<div class="fbEmpty">아직 마감된 내 카드가 없습니다.<br>살!말?에 고민을 올리면 마감 뒤 여기서 결과를 남길 수 있어요.</div>';
    return;
  }
  const row=(r,pending)=>{
    const f=r.feedback;
    const sub=pending?'작성 전':(f.purchase_label+(f.satisfaction?' · 만족 '+f.satisfaction+'/5':'')+
      (f.helpful===true?' · 투표 도움됨':f.helpful===false?' · 투표 도움 안 됨':''));
    return '<div class="fbRow'+(pending?' pending':'')+'">'+
      (r.image_url?'<img src="'+esc(r.image_url)+'" alt="">':'<i></i>')+
      '<div class="fbRowT"><b>'+esc(r.title)+'</b><span>'+esc(sub)+'</span>'+
        (f&&f.comment?'<q>'+esc(f.comment)+'</q>':'')+'</div>'+
      '<button type="button" class="pill'+(pending?'':' ghost')+'" data-fb-open="'+r.card_id+'">'+(pending?'작성하기':'수정')+'</button></div>';
  };
  host.innerHTML=
    '<div class="fbSum"><span>작성 전 <b>'+s.pending.length+'</b></span><span>작성 완료 <b>'+s.done.length+'</b></span></div>'+
    s.pending.map(r=>row(r,true)).join('')+s.done.map(r=>row(r,false)).join('');
  host.onclick=e=>{
    const b=e.target.closest('[data-fb-open]'); if(!b)return;
    const id=+b.dataset.fbOpen;
    const r=[...s.pending,...s.done].find(x=>x.card_id===id);
    if(r)fbOpen(r,{askLater:false});
  };
}
/* 저장·재조회가 끝나면 마이페이지 패널이 떠 있을 때 바로 다시 그린다 (새로고침 없이) */
document.addEventListener('feedit:feedback',()=>{ const h=document.getElementById('fbPanelBody'); if(h)fbPanelRender(h); });

export function fbReset(){ fbState={loaded:false,pending:[],done:[],error:''}; }
