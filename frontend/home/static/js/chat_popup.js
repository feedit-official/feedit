import { $, $$, HAS_A, aAnimate } from '../../../core/static/js/dom.js';
import { SAY, SM_ON, SM_SAY, STYLES, ansCardHTML, smSwitch } from './chat.js';
import { isUp, askStream, reportHTML, notesHTML, followupHTML, actionsHTML, refusalHTML, requestLexicon, fillBars } from './chat_api.js';
import { requireAuth } from '../../../account/static/js/profile.js';

/* ══════════════════════════════════════════════════════
   챗봇 팝업 — 일반 모드 · 살말 모드
   ------------------------------------------------------
   두 모드는 대화창 자체가 다르다. 각자 자기 대화 목록(CP_STORE)을
   따로 들고 있어서, 모드를 오가도 서로의 대화에 섞이지 않는다.
   홈의 입력창·칩 버튼은 이제 인라인으로 답을 펼치지 않고
   전부 이 팝업 하나로 모인다.
   ══════════════════════════════════════════════════════ */
const CP_STORE={ general:{convos:[],activeId:null}, salmal:{convos:[],activeId:null} };
let CP_UID=1;
/* 사이드바 프로필(이름·소개)은 모드별로 다르게 남겨 둔다 — 팝업 자체가 둘이라는 것을
   보여주는 자리라서다. 대화 안의 답변 라벨은 별개로 항상 FEEDiT 하나로 묶는다(아래). */
const CP_PROFILE={
  general:{name:'일반 모드', desc:'요즘 뜨는 트렌드를 알려드려요.',
    empty:'요즘 뜨는 트렌드가 궁금하다면 물어보세요.', ph:'궁금한 트렌드를 질문해 주세요.'},
  salmal :{name:'살말 모드', desc:'사도 되는지, 대신 판단해 드려요.',
    empty:'살까 말까 고민되는 아이템을 물어보세요.', ph:'고민되는 아이템을 질문해 주세요.'}
};
/* 답변 중엔 이 하나로 통일 — 별이 돌고 글자가 옅어졌다 밝아지며 "생각 중"을 표현한다 */
let cpTypeTimer=null;
/* escapeHtml 은 salmalBoot() 지역 함수라 팝업(전역 스코프)에서는 안 보인다 — 따로 하나 둔다 */
function cpEsc(s){
  return String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}
const cpMode =()=>SM_ON?'salmal':'general';
export const cpStore=()=>CP_STORE[cpMode()];
function cpActiveConvo(){
  const s=cpStore();
  return s.convos.find(c=>c.id===s.activeId)||null;
}
function cpTitleFrom(text){
  const t=text.replace(/\s+/g,' ').trim();
  return t.length>24 ? t.slice(0,24)+'…' : t;
}
function cpNowLabel(){
  const d=new Date();
  return (d.getMonth()+1)+'월 '+d.getDate()+'일';
}
export function cpNewConvo(){
  const s=cpStore();
  const c={id:CP_UID++, title:'', time:cpNowLabel(), messages:[]};
  s.convos.unshift(c);
  s.activeId=c.id;
  return c;
}
/* 질문 문장에서 어떤 카드를 보여줄지 고른다 — sendChat() 이 쓰던 것과 같은 규칙 */
export function cpKeyFor(v){
  if(SM_ON){
    if(/최저가|가격|싸|비싸|할인/.test(v))return 'smPrice';
    if(/내년|오래|수명|계속/.test(v))return 'smLife';
    if(/대신|비슷|대안|다른/.test(v))return 'smAlt';
    if(/투표|다들|사람들|반응/.test(v))return 'smVote';
    return 'smBuy';
  }
  if(/고프/.test(v))return 'gorp';
  if(/발레/.test(v))return 'ballet';
  if(/29CM|무신사|비교|온도/.test(v))return 'plat';
  if(/체형|코트|추천/.test(v))return 'body';
  return 'rise';
}
function cpPaintProfile(){
  const p=CP_PROFILE[cpMode()];
  $('#cpAv').textContent=SM_ON?'◑':'✧';
  $('#cpName').textContent=p.name;
  $('#cpDesc').textContent=p.desc;
  const empty=$('#cpEmptyText'); if(empty)empty.textContent=p.empty;
  const ta=$('#cpInput'); if(ta)ta.placeholder=p.ph;
}
export function cpRenderList(){
  const list=$('#cpList'); if(!list)return;
  const s=cpStore();
  if(!s.convos.length){
    list.innerHTML='<p class="cpListEmpty">최근 대화가 없습니다.</p>';
    return;
  }
  /* 연필은 .cpItem 밖에 둔다 — 버튼 안에 버튼을 넣을 수 없고,
     라우터가 잡는 .cpItem[data-cid] 도 그대로 살아야 한다. 마우스를 올리면
     .cpItemRow:hover 로 연필이 드러난다(chat_popup.css). */
  list.innerHTML=s.convos.map(c=>
      '<div class="cpItemRow">'+
        '<button type="button" class="cpItem'+(c.id===s.activeId?' on':'')+'" data-cid="'+c.id+'">'+
          '<em>'+c.time+'</em><span>'+cpEsc(c.title||'새 대화')+'</span>'+
        '</button>'+
        '<button type="button" class="cpEdit" data-edit="'+c.id+'" '+
          'title="제목 수정" aria-label="제목 수정"><i>✎</i></button>'+
      '</div>').join('');
}

/* 대화 목록 제목을 그 자리에서 고친다.
   span 을 input 으로 바꿔치고, Enter 로 저장 · Esc 로 되돌린다.
   저장할 때 앞뒤 공백과 중복 공백을 정리한다 — 빈 제목이면 "새 대화" 로 보인다. */
export function cpEditTitle(id){
  const row=document.querySelector('.cpItem[data-cid="'+id+'"]'); if(!row)return;
  if(row.querySelector('.cpTitleIn'))return;
  const s=cpStore();
  const c=s.convos.find(x=>x.id===id); if(!c)return;
  const span=row.querySelector('span'); if(!span)return;
  const input=document.createElement('input');
  input.type='text'; input.className='cpTitleIn'; input.maxLength=60;
  input.value=c.title||'';
  span.replaceWith(input);
  input.focus(); input.select();
  let done=false;
  const commit=(save)=>{
    if(done)return; done=true;
    if(save)c.title=input.value.replace(/\s+/g,' ').trim();
    cpRenderList();
  };
  input.addEventListener('keydown',e=>{
    if(e.key==='Enter'){ e.preventDefault(); commit(true) }
    else if(e.key==='Escape'){ e.preventDefault(); commit(false) }
  });
  input.addEventListener('blur',()=>commit(true));
}
/* AI 말풍선 한 줄 — 별 아이콘 + FEEDiT. 답을 기다리는 동안(pending)엔
   말풍선 대신 이 헤더만 돌고 옅어졌다 밝아지며 "생각 중"을 표현한다 */
function cpWhoHTML(stage){
  /* ★ stage — 서버가 도구를 부를 때마다 보내는 한 줄("온도 보는 중").
     기다리는 동안 무엇을 보고 있는지 알면 같은 시간도 기다림이 된다. */
  return '<div class="who"><i class="cpStar">✧</i>FEEDiT' +
         '<span class="cpStage">' + (stage ? cpEsc(stage) : '') + '</span></div>';
}
export function cpRenderThread(opts){
  const wrap=$('#cpThreadWrap'), th=$('#cpThread'); if(!wrap||!th)return;
  const c=cpActiveConvo();
  if(cpTypeTimer){ clearTimeout(cpTypeTimer); cpTypeTimer=null; }
  if(!c||!c.messages.length){ wrap.classList.remove('hasMsg'); th.innerHTML=''; return; }
  wrap.classList.add('hasMsg');
  const typeIdx=(opts&&opts.typeLast)?c.messages.length-1:-1;
  th.innerHTML=c.messages.map((m,idx)=>{
    if(m.role==='me') return '<div class="msg me"><div class="bub">'+cpEsc(m.text)+'</div></div>';
    if(m.pending) return '<div class="msg ai thinking">'+cpWhoHTML(m.stage)+'</div>';
    if(idx===typeIdx) return '<div class="msg ai" data-type-target="1">'+cpWhoHTML()+'<div class="say"></div></div>';
    { const card=(m.cardHtml!=null)?m.cardHtml:(m.key?ansCardHTML(m.key):'');
      return '<div class="msg ai">'+cpWhoHTML()+'<div class="say">'+(m.html||'')+'</div>'+
        card+(m.followHtml||'')+(m.cueHtml||'')+(m.actionsHtml||'')+'</div>'; }
  }).join('');
  $$('i[data-w]',th).forEach(f=>f.style.width=f.dataset.w+'%');
  wrap.scrollTop=wrap.scrollHeight;
  if(typeIdx>=0){
    const m=c.messages[typeIdx];
    const target=th.querySelector('[data-type-target="1"] .say');
    if(target&&m)cpTypeHTML(target,m.html,()=>{
      if(m.key){
        const holder=document.createElement('div');
        holder.innerHTML=ansCardHTML(m.key);
        const cardEl=holder.firstElementChild;
        cardEl.classList.add('reveal');
        target.parentElement.appendChild(cardEl);
        $$('i[data-w]',cardEl).forEach(f=>f.style.width=f.dataset.w+'%');
        requestAnimationFrame(()=>{ requestAnimationFrame(()=>cardEl.classList.add('in')); });
      }
      wrap.scrollTop=wrap.scrollHeight;
    });
  }
}
/* 답 텍스트를 한 글자씩 밀어 넣는다. html 안의 태그(<b>…</b>)는 한 번에
   통째로 소비해서, 어느 순간에 잘라도 항상 닫힌 HTML만 그려지게 한다. */
function cpTypeHTML(el,html,done){
  el.innerHTML='';
  let i=0;
  const wrap=$('#cpThreadWrap');
  function step(){
    if(i>=html.length){ done&&done(); return; }
    if(html[i]==='<'){
      const end=html.indexOf('>',i);
      i=end===-1?html.length:end+1;
      el.innerHTML=html.slice(0,i);
      step();
      return;
    }
    i++;
    el.innerHTML=html.slice(0,i);
    if(wrap)wrap.scrollTop=wrap.scrollHeight;
    const prev=html[i-1];
    const delay=/[.,!?]/.test(prev)?110:14+Math.random()*16;
    cpTypeTimer=setTimeout(step,delay);
  }
  step();
}
/* 질문 하나를 대화에 밀어 넣는다 — 답은 곧장 나오지 않고, 잠깐 "생각 중" 상태로
   있다가 텍스트가 타이핑되듯 채워진 뒤 카드가 뒤따라 떠오른다 */
/* 서버는 스타일을 **이름**으로 보낸다(chat_api.js actionsHTML 주석).
   라우터(goStyle)는 id 를 기대하므로 여기서 이름 → id 로 바꿔 단다.
   못 찾으면 조용히 첫 번째 스타일로 떨어지면 안 되니 — 버튼 자체를 지운다. */
function cpFixStyleLinks(host){
  if(!host)return;
  host.querySelectorAll('[data-style-name]').forEach(btn=>{
    const name=btn.dataset.styleName;
    const hit=STYLES.find(x=>x.n===name);
    if(hit){ btn.dataset.style=hit.id; btn.removeAttribute('data-style-name'); }
    else{ btn.remove(); }
  });
}
/* 최근 턴 몇 개 — server.py history 형식({q,intent,terms})으로.
   답이 아직 안 온 턴(진행 중)은 넣지 않는다 — intent 가 아직 없다. */
function cpHistoryFor(c){
  const out=[];
  for(const m of c.messages) if(m.role==='ai'&&m.turn) out.push(m.turn);
  return out.slice(-8);
}
function cpAskMock(c,aiMsg,key){
  /* 이 시점엔 이미 서버 연결을 한 번 시도해 본 뒤다(isUp() 또는 askStream 실패) —
     그 위에 예전처럼 650~1200ms + 타이핑 애니메이션을 더 얹지 않는다.
     즉시 채우고, 카드도 이 함수가 직접 붙인다 — cardHtml 이 ''(비어 있음, 아직
     스트리밍 전)으로 잠겨 있는 채로 남으면 목업인데 카드가 안 뜬다. */
  aiMsg.html=(SM_ON?SM_SAY[key]:SAY[key])||SAY.rise;
  aiMsg.cardHtml=ansCardHTML(key);
  aiMsg.pending=false;
  if(cpActiveConvo()===c)cpRenderThread();
}
/* feedit-chat(:8770)에 실제로 묻는다. 서버가 없으면(isUp() false) 또는
   도중에 끊기면 cpAskMock 의 데모 답으로 조용히 떨어진다 — 서버가 없어도
   데모가 깨지면 안 된다(AGENTS.md). 대화 id 에 모드를 붙여 보낸다 —
   두 모드가 따로 1,2,3… 으로 세므로 안 붙이면 섞인다. */
async function cpAskLive(c,aiMsg,text){
  const conv='cp-'+cpMode()+'-'+c.id;
  const history=cpHistoryFor(c);
  /* pending 은 아직 true 로 남겨둔다 — 첫 실제 응답(text/report/error)이
     오기 전까지는 별 아이콘이 돌아가는 "생각 중" 헤더를 그대로 보여준다.
     cardHtml 만 미리 비워서 m.key 목업 카드가 새지 않게 잠근다. */
  aiMsg.html='';
  aiMsg.cardHtml='';           /* 아직 스트리밍 전 — m.key 목업 카드로 떨어지지 않게 잠근다 */
  const sayEl=()=>{
    if(cpActiveConvo()!==c)return null;
    const wrap=$('#cpThreadWrap'); if(!wrap)return null;
    const nodes=wrap.querySelectorAll('.msg.ai');
    return nodes.length?nodes[nodes.length-1].querySelector('.say'):null;
  };
  /* pending 상태를 풀고 "생각 중" 헤더 대신 실제 말풍선(.say)을 그린다 —
     text/report/error 중 뭐가 먼저 오든 한 번만 호출된다. */
  const settle=()=>{
    if(!aiMsg.pending)return;
    aiMsg.pending=false;
    if(cpActiveConvo()===c)cpRenderThread();
  };
  let acc='';
  await askStream({question:text, mode:cpMode(), plan:'FREE',
                    conversation_id:conv, history},{
    /* ★ 진행 상황 (server.py 의 push("status", {stage:"tool", message})).
       예전에는 이 핸들러가 아예 없어서 서버가 보낸 이벤트가 **조용히
       버려졌다** — askStream 은 on[ev] 가 없으면 그냥 넘어간다.
       그래서 답이 올 때까지 헤더만 돌았다. 예산이 14초라 그 침묵이 길다. */
    status:(d)=>{
      if(!d || d.stage!=='tool' || !d.message) return;
      aiMsg.stage=d.message;
      if(!aiMsg.pending) return;                 /* 이미 말풍선이 떴으면 끝 */
      const th=$('#cpThread');
      const node=th&&th.querySelector('.msg.ai.thinking .cpStage');
      /* 한 글자만 바꾼다 — 전체를 다시 그리면 회전 애니메이션이 끊긴다 */
      if(node) node.textContent=d.message;
      else if(cpActiveConvo()===c) cpRenderThread();
    },
    text:(d)=>{
      settle();
      acc+=d.delta||''; aiMsg.html=acc;
      const el=sayEl(); const wrap=$('#cpThreadWrap');
      if(el){ el.innerHTML=acc; if(wrap)wrap.scrollTop=wrap.scrollHeight; }
    },
    report:(rep)=>{
      settle();
      aiMsg.turn={q:text, intent:rep.intent,
        terms:(rep.terms||[]).map(t=>({canonical:t.canonical,facet:t.facet,term_key:t.term_key}))};
      aiMsg.cardHtml=reportHTML(rep);
      const el=sayEl(); const host=el&&el.parentElement;
      if(host){
        const holder=document.createElement('div'); holder.innerHTML=aiMsg.cardHtml;
        while(holder.firstChild)host.appendChild(holder.firstChild);
        fillBars(host);
      }
      /* 카드 다음 순서는 셋이다 — 이어 갈 질문 · 못 한 것 · 버튼.
         라이브로 붙이는 순서와 다시 그릴 때의 순서가 같아야 한다
         (cpRenderThread 가 card 다음에 followHtml → cueHtml 을 끼운다). */
      aiMsg.followHtml=followupHTML(rep.followup);
      if(host&&aiMsg.followHtml)host.insertAdjacentHTML('beforeend',aiMsg.followHtml);
      aiMsg.cueHtml=notesHTML(rep.notes);
      if(host&&aiMsg.cueHtml)host.insertAdjacentHTML('beforeend',aiMsg.cueHtml);
    },
    actions:(acts)=>{
      aiMsg.actionsHtml=actionsHTML(acts);
      const el=sayEl(); const host=el&&el.parentElement;
      if(host&&aiMsg.actionsHtml){
        host.insertAdjacentHTML('beforeend',aiMsg.actionsHtml);
        cpFixStyleLinks(host);
        aiMsg.actionsHtml=host.querySelector('.act')?host.querySelector('.act').outerHTML:'';
      }
    },
    error:(err)=>{
      settle();
      aiMsg.html=''; aiMsg.cardHtml=refusalHTML(err); aiMsg.turn=null;
      const el=sayEl(); const host=el&&el.parentElement;
      if(el)el.innerHTML='';
      if(host)host.insertAdjacentHTML('beforeend',aiMsg.cardHtml);
    },
    done:()=>{ settle(); const wrap=$('#cpThreadWrap'); if(wrap&&cpActiveConvo()===c)wrap.scrollTop=wrap.scrollHeight; }
  });
}
/* 질문 하나를 대화에 밀어 넣는다. 서버가 떠 있으면 실제 답(마크다운·근거가
   전부 정리된 리포트 카드)을, 아니면 데모용 캔 답을 "생각 중" 뒤에 채운다. */
function cpAsk(text,key,opts){
  if(!text)return;
  let c=(opts&&opts.forceNew)?cpNewConvo():cpActiveConvo(); if(!c)c=cpNewConvo();
  c.messages.push({role:'me', text});
  if(!c.title)c.title=cpTitleFrom(text);
  const aiMsg={role:'ai', html:'', key, pending:true};
  c.messages.push(aiMsg);
  cpRenderList();
  cpRenderThread();
  (async()=>{
    let live=false;
    try{ live=await isUp() }catch(e){ live=false }
    if(!live) return cpAskMock(c,aiMsg,key);
    try{ await cpAskLive(c,aiMsg,text) }
    catch(e){
      const last=c.messages[c.messages.length-1];
      if(last===aiMsg) cpAskMock(c,aiMsg,key);
    }
  })();
}
export function cpSend(){
  if(!requireAuth())return;
  const ta=$('#cpInput'); const v=(ta&&ta.value.trim())||'';
  if(!v)return;
  cpAsk(v,cpKeyFor(v));
  if(ta){ ta.value=''; ta.style.height=''; }
}
export function openChatPopup(){
  const ov=$('#cpOverlay'); if(!ov)return;
  ov.classList.toggle('sm',SM_ON);
  ov.classList.add('on');
  document.body.style.overflow='hidden';
  cpPaintProfile(); cpRenderList(); cpRenderThread();
  setTimeout(()=>{ const ta=$('#cpInput'); if(ta)ta.focus(); },260);
}
export function closeChatPopup(){
  const ov=$('#cpOverlay'); if(!ov)return;
  ov.classList.remove('on');
  document.body.style.overflow='';
}
/* 홈 하단 예시 버튼("이거 사도 될까?" 등)에서 바로 넘어올 때 쓰는 진입점.
   {fresh:true} 면 무조건 새 대화 — 홈에서 한 줄 치는 건 새로 묻는 동작이지
   마지막 대화를 잇는 동작이 아니다. 없으면 열려 있던(또는 마지막) 대화에 잇는다. */
export function openChatWith(text,key,opts){
  if(!requireAuth())return;
  openChatPopup();
  if(opts&&opts.fresh) cpNewConvo();
  cpAsk(text, key||cpKeyFor(text), opts);
}

/* 팝업 상단 좌측 마크 — 눌리면 동전이 뒤집히듯 한 바퀴 돌며 일반/살말 모드를 바꾼다.
   실제 모드 값은 SM_ON 하나뿐이라 홈 챗바의 토글과 같은 smSwitch() 를 그대로 쓰고,
   팝업 쪽 화면(프로필·목록·대화)만 이 자리에서 다시 그려 준다. */
function cpAvFlip(){
  const av=$('#cpAv'); if(!av||!HAS_A)return;
  aAnimate(av,{rotateY:[0,360],duration:640,ease:'inOut(2)'});
}
export function cpToggleMode(){
  cpAvFlip();
  smSwitch(!SM_ON);
  const ov=$('#cpOverlay'); if(ov)ov.classList.toggle('sm',SM_ON);
  cpPaintProfile(); cpRenderList(); cpRenderThread();
}
/* 리포트 안 버튼 — 근접 키워드 재질문 · 모드 전환 힌트 · 외부 링크.
   actionsHTML/refusalHTML 이 만드는 data-kw·data-mode·data-href 를 여기서 받는다. */
document.addEventListener('click', e=>{
  const kw=e.target.closest('#cpThread [data-kw]');
  if(kw){ cpAsk(kw.dataset.kw, cpKeyFor(kw.dataset.kw)); return; }
  const md=e.target.closest('#cpThread [data-mode]');
  if(md){ smSwitch(md.dataset.mode==='salmal'); return; }
  const hr=e.target.closest('#cpThread [data-href]');
  if(hr){ window.open(hr.dataset.href, '_blank', 'noopener'); return; }
  const rq=e.target.closest('#cpThread [data-lexreq]');
  if(rq){ cpSendLexiconRequest(rq); return; }
});
/* 등록 요청 버튼 — 누른 즉시 잠그고(중복 전송 방지), 서버가 답하면 결과를 말한다.
   "누르면 되는 척" 을 하지 않는다(server.py 주석) — 실패해도 실패라고 말한다. */
async function cpSendLexiconRequest(btn){
  if(btn.disabled)return;
  const surface=btn.dataset.surface||'', question=btn.dataset.question||'';
  btn.disabled=true; btn.textContent='요청하는 중…';
  try{
    const r=await requestLexicon(surface, question);
    btn.textContent=(r&&r.surface?'"'+r.surface+'" ':'')+'등록 요청 완료';
  }catch(e){
    btn.textContent='요청 실패 — 잠시 후 다시 시도해 주세요';
    btn.disabled=false;
  }
}
