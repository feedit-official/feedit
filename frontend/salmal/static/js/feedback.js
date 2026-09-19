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
const SAT_Q={BOUGHT:'사길 잘했나요?',SKIPPED:'안 사길 잘했나요?'};
const SAT_L=['','전혀 아니에요','아쉬워요','보통이에요','잘했어요','아주 잘했어요'];

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
export function fbClose(){ const m=$('#fbModal'); if(m)m.classList.remove('on'); }

/* 카드 한 장의 피드백 창. row = {card_id, title, image_url, vote_summary, feedback} */
export function fbOpen(row, { onSaved, askLater=true } = {}){
  const m=modalRoot(), card=m.querySelector('.fbCard');
  const fb=row.feedback||{};
  const st={purchase:fb.purchase||'', satisfaction:fb.satisfaction||null,
            helpful:fb.helpful??null, comment:fb.comment||''};
  const vs=row.vote_summary||{};
  const paint=()=>{
    const q=SAT_Q[st.purchase];
    card.innerHTML=
      '<button type="button" class="fbX" data-fb="close" aria-label="닫기">×</button>'+
      '<div class="fbHead">'+(row.image_url?'<img src="'+esc(row.image_url)+'" alt="">':'')+
        '<div><em>투표 마감 · 결과를 알려 주세요</em><h3 id="fbTitle">'+esc(row.title)+'</h3>'+
        '<span>살 '+(vs.buy_pct??'–')+'% · 말 '+(vs.pass_pct??'–')+'% · '+(vs.total||0)+'표</span></div></div>'+
      '<div class="fbQ"><b>결국 어떻게 하셨나요?</b><div class="fbOpts">'+
        PURCHASE.map(([k,l])=>'<button type="button" data-p="'+k+'" class="'+(st.purchase===k?'on':'')+'">'+l+'</button>').join('')+
      '</div></div>'+
      (q?'<div class="fbQ"><b>'+q+'</b><div class="fbStars">'+
        [1,2,3,4,5].map(n=>'<button type="button" data-s="'+n+'" class="'+(st.satisfaction>=n?'on':'')+'" aria-label="'+n+'점">★</button>').join('')+
        '<span>'+(st.satisfaction?SAT_L[st.satisfaction]:'')+'</span></div></div>':'')+
      '<div class="fbQ"><b>모두의 투표가 결정에 도움이 됐나요?</b><div class="fbOpts">'+
        '<button type="button" data-h="1" class="'+(st.helpful===true?'on':'')+'">도움이 됐어요</button>'+
        '<button type="button" data-h="0" class="'+(st.helpful===false?'on':'')+'">별로요</button></div></div>'+
      '<div class="fbQ"><b>한 줄 후기 <small>선택</small></b>'+
        '<input type="text" maxlength="300" placeholder="예) 실물 색이 더 예뻐요, 사이즈는 한 치수 크게" value="'+esc(st.comment)+'"></div>'+
      '<div class="fbErr" hidden></div>'+
      '<div class="fbActs">'+(askLater?'<button type="button" class="pill ghost" data-fb="later">나중에</button>':'')+
        '<button type="button" class="pill" data-fb="save">'+(row.feedback?'수정하기':'남기기')+'</button></div>';
  };
  paint();
  card.oninput=e=>{ if(e.target.matches('input'))st.comment=e.target.value; };
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
      b.disabled=true;
      try{
        await saveFeedback({cardId:row.card_id, purchase:st.purchase, satisfaction:st.satisfaction,
                            helpful:st.helpful, comment:st.comment});
        fbClose();
        await fbLoad();
        if(onSaved)onSaved();
      }catch(ex){ fail(ex.message||'저장하지 못했습니다.'); b.disabled=false; }
    }
  };
  m.classList.add('on');
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
export function fbReset(){ fbState={loaded:false,pending:[],done:[],error:''}; }
