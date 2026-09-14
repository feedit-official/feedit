import { $, $$, HAS_A, aAnimate } from '../../../core/static/js/dom.js';
import { SAY, SM_ON, SM_SAY, STYLES, LIKED, M_QUESTIONS, SM_QUESTIONS, ansCardHTML, smSwitch } from './chat.js';
import { API_BASE, classifyFitImages, sendAnswerFeedback, isUp, askStream, reportHTML, notesHTML, followupHTML, actionsHTML, refusalHTML, requestLexicon, fillBars, MAX_IMAGES, imageFileToDataURL, bindImageDrop, wantsVirtualFit, responseCardHTML } from './chat_api.js';
import { AUTH, ME, openStyleSelect, requireAuth } from '../../../account/static/js/profile.js';

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

/* ── 대화 보관 (2026-09-13) ────────────────────────────
   예전에는 대화가 이 파일의 변수에만 있었다. 새로고침 한 번에 어제 물어본 답이
   통째로 사라졌고, 사용자는 같은 질문을 다시 쳐야 했다.
   서버에 계정별로 쌓는 것이 옳지만 그 전까지는 브라우저에 남긴다 —
   같은 기기에서는 새로고침·재방문을 견딘다.
   ★ 용량이 문제다. 첨부 사진이 data URL 이라 대화 몇 개로도 한도를 넘긴다.
     넘치면 (1) 오래된 대화의 사진부터 버리고 (2) 그래도 넘치면 오래된 대화를
     버린다. 사진을 버린 대화는 글은 그대로 남는다 — 다시 열었을 때 무엇을
     물었는지는 읽을 수 있어야 한다. */
const CP_KEY='feedit.chat.v1';
const CP_KEEP=20;                    /* 모드별로 보관할 대화 수 */
let cpSaveT=0;
function cpPackMsg(m,keepImages){
  const out={role:m.role,text:m.text||'',html:m.html||'',key:m.key||null,
             cardHtml:m.cardHtml||'',followHtml:m.followHtml||'',cueHtml:m.cueHtml||'',
             actionsHtml:m.actionsHtml||'',turn:m.turn||null,
             feedback:m.feedback||null,imagesDropped:!!m.imagesDropped};
  if(m.images&&m.images.length){
    if(keepImages)out.images=m.images; else out.imagesDropped=true;
  }
  return out;   /* run·fit 은 일부러 뺀다 — 진행 중 상태와 약속(Promise)은 저장할 것이 아니다 */
}
function cpPack(keepImagesFor){
  const out={};
  for(const mode of ['general','salmal']){
    const s=CP_STORE[mode];
    out[mode]={activeId:s.activeId,
      convos:s.convos.slice(0,CP_KEEP).map((c,i)=>({
        id:c.id,title:c.title||'',time:c.time||'',
        messages:(c.messages||[]).filter(m=>!m.pending).map(m=>cpPackMsg(m,i<keepImagesFor))}))};
  }
  return out;
}
export function cpSave(){
  if(typeof localStorage==='undefined')return;
  clearTimeout(cpSaveT);
  /* 연달아 바뀌는 동안 매번 쓰지 않는다 — 타이핑 중 저장이 겹치면 버벅인다 */
  cpSaveT=setTimeout(()=>{
    for(const keep of [CP_KEEP,3,1,0]){
      try{ localStorage.setItem(CP_KEY,JSON.stringify({v:1,uid:CP_UID,store:cpPack(keep)})); return }
      catch(e){ /* 한도 초과 — 사진을 더 버리고 다시 */ }
    }
    try{ localStorage.removeItem(CP_KEY) }catch(e){ /* 지우지도 못하면 포기한다 */ }
  },400);
}
function cpRestore(){
  if(typeof localStorage==='undefined')return;
  let saved=null;
  try{ saved=JSON.parse(localStorage.getItem(CP_KEY)||'null') }catch(e){ saved=null }
  if(!saved||saved.v!==1||!saved.store)return;
  let max=0;
  for(const mode of ['general','salmal']){
    const from=saved.store[mode];
    if(!from||!Array.isArray(from.convos))continue;
    CP_STORE[mode].convos=from.convos.filter(c=>c&&Array.isArray(c.messages)).map(c=>{
      max=Math.max(max,Number(c.id)||0);
      return {id:Number(c.id)||0,title:String(c.title||''),time:String(c.time||''),
              messages:c.messages.map(m=>Object.assign({},m,{pending:false}))};
    });
    CP_STORE[mode].activeId=from.activeId||null;
  }
  CP_UID=Math.max(CP_UID,max+1,Number(saved.uid)||1);
}
cpRestore();
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
let cpActiveRun=null;
/* escapeHtml 은 salmalBoot() 지역 함수라 팝업(전역 스코프)에서는 안 보인다 — 따로 하나 둔다 */
function cpEsc(s){
  return String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}
const cpMode =()=>SM_ON?'salmal':'general';

/* ── 팝업 챗바 이미지 첨부 ─────────────────────────────
   홈 챗바(chat.js의 mImages)와 별개로 팝업 자체에서도 사진을 올릴 수 있다 —
   팝업이 떠 있는 동안 이어 묻는 질문에도 새 사진을 붙일 수 있어야 하므로. */
let cpImages=[];
function cpImgPaint(){
  const box=$('#cpImgAttach'); if(!box)return;
  box.hidden = cpImages.length===0;
  box.innerHTML = cpImages.map((im,i)=>
    '<span class="imgChip"><img src="'+im.url+'" alt=""><button type="button" data-rm="'+i+'" aria-label="사진 삭제">×</button></span>').join('');
}
async function cpImgPick(files){
  for(const f of files){
    if(cpImages.length>=MAX_IMAGES)break;
    try{ const url=await imageFileToDataURL(f); cpImages.push({url}); }catch(e){ /* 이미지가 아니면 조용히 건너뛴다 */ }
  }
  cpImgPaint();
}
/* 보낼 때만 비운다 — 그 전까지는 대화창을 닫았다 열어도 그대로 남아 있는다 */
function cpImgTake(){ const out=cpImages.map(im=>im.url); cpImages=[]; cpImgPaint(); return out; }
export function cpImgInit(){
  const add=$('#cpImgAdd'), input=$('#cpImgFile'), box=$('#cpImgAttach');
  if(add&&input){
    add.addEventListener('click', ()=>input.click());
    input.addEventListener('change', ()=>{
      if(input.files&&input.files.length)cpImgPick([...input.files]);
      input.value='';
    });
  }
  if(box)box.addEventListener('click', e=>{
    const rm=e.target.closest('[data-rm]'); if(!rm)return;
    cpImages.splice(+rm.dataset.rm,1); cpImgPaint();
  });
  /* 팝업 입력줄에 사진을 끌어다 놓아도 + 버튼과 같은 경로로 들어간다 */
  bindImageDrop($('.cpInputWrap'), files=>cpImgPick(files));
}
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
  cpSave();
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
  cpEmptyPaint();
  cpTastePaint();
  const ta=$('#cpInput'); if(ta)ta.placeholder=p.ph;
}
/* 대화 삭제 아이콘 — 선 하나 굵기로 그린 휴지통. 이모지(🗑)는 기기마다
   컬러·굵기가 달라 옆의 연필과 톤이 맞지 않았다. (2026-09-13) */
const CP_TRASH='<svg viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.4 3.6h9.2M5.5 3.6V2.5h3v1.1M3.6 3.6l.5 8h5.8l.5-8M5.9 5.9v3.6M8.1 5.9v3.6"/></svg>';

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
        /* 삭제는 두 번 눌러야 지워진다 — 한 번 누르면 '삭제?' 로 바뀌고,
           3초 안에 다시 누르지 않으면 되돌아간다. 브라우저 confirm 창은
           팝업 위에 또 창을 띄우게 되고, 실수로 지운 대화는 되돌릴 수 없다. */
        '<button type="button" class="cpDel" data-del="'+c.id+'" '+
          'title="대화 삭제" aria-label="대화 삭제">'+CP_TRASH+'</button>'+
      '</div>').join('');
}

/* 대화 하나를 지운다. 지운 것이 보고 있던 대화면 다음 대화로 옮겨 간다.
   목록이 비면 빈 화면(예시 질문)으로 돌아간다. (2026-09-13) */
export function cpDeleteConvo(id){
  const s=cpStore();
  const at=s.convos.findIndex(c=>c.id===id);
  if(at<0)return;
  /* 답변을 만드는 중인 대화를 지우면 그 응답부터 멈춘다 */
  if(cpActiveRun&&cpActiveRun.c&&cpActiveRun.c.id===id)cpStop();
  s.convos.splice(at,1);
  if(s.activeId===id)s.activeId=s.convos.length?s.convos[Math.min(at,s.convos.length-1)].id:null;
  cpRenderList(); cpRenderThread(); cpSave();
}
let cpDelArmed=0, cpDelT=0;
export function cpDelClick(btn){
  const id=Number(btn.dataset.del);
  if(cpDelArmed===id){ clearTimeout(cpDelT); cpDelArmed=0; cpDeleteConvo(id); return }
  clearTimeout(cpDelT);
  cpDelArmed=id;
  btn.classList.add('armed');
  btn.setAttribute('title','한 번 더 누르면 삭제됩니다');
  btn.innerHTML='<i>삭제</i>';
  cpDelT=setTimeout(()=>{ cpDelArmed=0; cpRenderList() },3000);
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
    cpRenderList(); cpSave();
  };
  input.addEventListener('keydown',e=>{
    if(e.key==='Enter'){ e.preventDefault(); commit(true) }
    else if(e.key==='Escape'){ e.preventDefault(); commit(false) }
  });
  input.addEventListener('blur',()=>commit(true));
}
/* AI 말풍선 한 줄 — 별 아이콘 + FEEDiT. 답을 기다리는 동안(pending)엔
   말풍선 대신 이 헤더만 돌고 옅어졌다 밝아지며 "생각 중"을 표현한다 */
/* ── 답변 피드백 (2026-09-13) ──────────────────────────
   틀린 답을 봐도 알릴 곳이 없었다. 한 줄로 묻고, '아쉬움' 이면 사유를 고르게 한다.
   사유는 실제로 자주 나는 실패 네 가지다 — 무엇을 고쳐야 하는지가 바로 읽힌다. */
const CP_FB_REASONS=['사실이 틀렸어요','엉뚱한 걸 답했어요','자료가 부족해요','원하는 내용이 아니에요'];
function cpFeedbackHTML(m,idx){
  if(!m||m.pending)return '';
  if(!m.html&&!m.cardHtml&&!m.key)return '';
  if(m.feedback==='up')return '<div class="cpFb done">의견 고맙습니다.</div>';
  if(m.feedback==='down')return '<div class="cpFb done">알려 주셔서 고맙습니다. 답변 품질을 고치는 데 씁니다.</div>';
  if(m.fbOpen){
    return '<div class="cpFb open"><span>무엇이 아쉬웠나요?</span>'+
      CP_FB_REASONS.map(r=>'<button type="button" data-fb-reason="'+idx+'" data-reason="'+cpEsc(r)+'">'+
        cpEsc(r)+'</button>').join('')+
      '<button type="button" class="cpFbSkip" data-fb-close="'+idx+'">닫기</button></div>';
  }
  return '<div class="cpFb"><span>이 답변이 도움이 되었나요?</span>'+
    '<button type="button" data-fb="up" data-fb-idx="'+idx+'">도움됨</button>'+
    '<button type="button" data-fb="down" data-fb-idx="'+idx+'">아쉬움</button></div>';
}
/* 살말 모드에서 즐겨입는 스타일이 비어 있으면 판단의 가장 무거운 축(취향 35%)이
   통째로 빠진다. 마이페이지까지 가야 고를 수 있던 것을, 여기서 바로 고르게 한다. */
function cpTastePaint(){
  const box=$('#cpTaste'); if(!box)return;
  const need=SM_ON&&AUTH.in&&ME.styles&&ME.styles.size===0;
  box.hidden=!need;
  if(need&&!box.dataset.built){
    box.dataset.built='1';
    box.innerHTML='<span>즐겨입는 스타일을 고르면 살말 판단이 정확해집니다 '+
      '(취향이 판단의 35%입니다).</span>'+
      '<button type="button" id="cpTasteBtn">스타일 고르기</button>';
    box.addEventListener('click',e=>{
      if(e.target.closest('#cpTasteBtn'))openStyleSelect();
    });
  }
}
/* 빈 화면 — 무엇을 물어야 할지 알려 준다. 모드 차이와 전환 단축키도 여기서 한 번
   보여 준다. 예시는 홈 챗바가 돌리는 것과 같은 목록을 쓴다. */
function cpEmptyPaint(){
  const box=$('#cpEmpty'); if(!box)return;
  const p=CP_PROFILE[cpMode()];
  const set=(SM_ON?SM_QUESTIONS:M_QUESTIONS).slice(0,4);
  box.innerHTML='<p id="cpEmptyText">'+cpEsc(p.empty)+'</p>'+
    '<div class="cpEmptyChips">'+set.map(q=>{
      const text=q[0]+' '+q[1];
      return '<button type="button" data-ask="'+cpEsc(text)+'">'+
        '<b>'+cpEsc(q[0])+'</b> '+cpEsc(q[1])+'</button>';
    }).join('')+'</div>'+
    '<p class="cpEmptyHint">'+(SM_ON
      ? '살!말? 모드는 <b>살지 말지</b>를 판단합니다. 트렌드 흐름이 궁금하면'
      : '일반 모드는 <b>트렌드 흐름</b>을 알려드립니다. 살지 말지 고민이라면')+
    ' <b>Tab</b> 키로 모드를 바꾸세요.</p>';
}

document.addEventListener('feedit:styles',()=>cpTastePaint());

function cpWhoHTML(stage){
  /* ★ stage — 서버가 도구를 부를 때마다 보내는 한 줄("온도 보는 중").
     기다리는 동안 무엇을 보고 있는지 알면 같은 시간도 기다림이 된다. */
  return '<div class="who"><i class="cpStar">✧</i>FEEDiT' +
         '<span class="cpStage">' + (stage ? cpEsc(stage) : '') + '</span></div>';
}
/* 착장 칸 (2026-09-14: 모자·벨트·안경 추가).
   ★ 서버 vton.SLOT_ORDER 와 같은 순서·같은 이름이어야 한다 — 한쪽만 늘리면
     화면의 드롭다운과 서버가 아는 칸이 어긋난다. */
const VF_CATEGORIES=['상의','하의','아우터','원피스(셋업)','신발','양말','모자','벨트','안경'];
const VF_AUTO='자동 분류';
/* 착장 옵션 — 켠 것만 프롬프트에 문장이 붙는다(서버 vton.OPTION_LINES).
   전부 꺼 두면 예전 동작 그대로다. pair 가 같은 것끼리는 하나만 켜진다 —
   "열어 입기" 와 "여며 입기" 를 동시에 보내면 모델에게 모순된 지시가 된다. */
const VF_OPTIONS=[
  {key:'outer_layered', label:'아우터 레이어드', pair:''},
  {key:'outer_open',    label:'아우터 열기',     pair:'outer'},
  {key:'outer_closed',  label:'아우터 닫기',     pair:'outer'},
  {key:'top_open',      label:'상의 열기',       pair:'top'},
  {key:'top_closed',    label:'상의 닫기',       pair:'top'},
];
/* 내 말풍선 아래 아이콘 줄에 쓰는 그림 (2026-09-14).
   글자 버튼('다시 묻기') 하나로는 되돌리기밖에 못 했다 — 같은 질문을 그대로
   다시 보내거나 문장만 복사할 방법이 없었다. */
const CP_SVG=(d)=>'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '+
  'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+d+'</svg>';
const CP_IC_RESEND=CP_SVG('<path d="M3.5 9.5h10a5.5 5.5 0 1 1 0 11H8"/><polyline points="7.5 5.5 3.5 9.5 7.5 13.5"/>');
const CP_IC_EDIT=CP_SVG('<path d="M4.5 19.5h4L19.6 8.4a2.05 2.05 0 0 0-2.9-2.9L5.5 16.6z"/><path d="M15.2 7l2.8 2.8"/>');
const CP_IC_COPY=CP_SVG('<rect x="9.5" y="9.5" width="10.5" height="10.5" rx="2.2"/><path d="M5.5 14.5V6a2 2 0 0 1 2-2h7"/>');
const CP_IC_DOWN=CP_SVG('<path d="M12 4v11"/><polyline points="7.5 10.5 12 15 16.5 10.5"/><path d="M5 19.5h14"/>');
function cpFitModel(text){
  return /(남자|남성|맨즈|male)/i.test(String(text||''))?'man':'woman';
}
function cpNewFit(images,text){
  const attached=images||[];
  return {key:String(Date.now()),
    items:VF_CATEGORIES.map((category,index)=>({category,image:attached[index]||'',auto:Boolean(attached[index])})),
    model:cpFitModel(text),status:'',result:'',loading:false,
    /* 옵션은 전부 꺼진 채로 시작한다 — 끈 상태가 예전 동작이다. 켜지 않은
       연출이 프롬프트에 실리면 사용자가 고르지 않은 사진이 나온다. */
    options:cpFitOptions(null),optsOpen:false,
    /* 붙인 사진이 있으면 곧바로 종류를 확인한다(cpFitAutoSort). 그 전까지는
       예전처럼 순서대로 놓아 둔다 — 기다리는 동안 빈 화면을 보여주지 않는다. */
    sorting:attached.length>0};
}
/* ★ 첨부 사진을 알맞은 칸으로 옮긴다 (2026-09-13).
   스커트를 올렸는데 '상의' 칸이 차 버려서, 상의를 넣으려면 사용자가 지우고 다시
   넣어야 했다. 어떤 옷인지는 사진을 볼 수 있는 서버만 안다 — 물어보고 옮긴다.
   같은 칸이 겹치면 뒤엣것은 빈 칸으로 흘려보내고, 판별을 못 한 사진은 예전처럼
   남은 칸에 순서대로 놓는다. 실패해도 화면은 그대로다(칸만 안 바뀐다). */
function cpFitAutoSort(m){
  const f=m&&m.fit; if(!f||!f.sorting)return Promise.resolve();
  /* 생성 버튼이 분류를 기다릴 수 있게 약속을 남겨 둔다 — 분류 도중에 만들면
     칸이 바뀌기 전 순서로 프롬프트가 나간다. */
  f._sort=cpFitSortNow(m,f);
  return f._sort;
}
async function cpFitSortNow(m,f){
  const shots=cpFitItems(f).map(item=>item.image).filter(Boolean);
  if(!shots.length){ f.sorting=false; return }
  let cats=[];
  try{ cats=await classifyFitImages(shots); }catch(e){ cats=[] }
  f.sorting=false;
  if(cats.length){
    const slots=VF_CATEGORIES.map(category=>({category,image:'',auto:false}));
    const leftover=[];
    shots.forEach((image,i)=>{
      const at=VF_CATEGORIES.indexOf(String(cats[i]||''));
      if(at>=0&&!slots[at].image)slots[at].image=image;
      else leftover.push(image);
    });
    /* 판별 못 했거나 칸이 겹친 사진 — 남은 칸에 순서대로. 여기서 버리면
       사용자가 올린 사진이 조용히 사라진다. */
    leftover.forEach(image=>{
      const slot=slots.find(x=>!x.image);
      if(slot){ slot.image=image; slot.auto=true }
    });
    f.items=slots;
  }
  if(cpActiveConvo()&&cpActiveConvo().messages.includes(m))cpRenderThread();
}
/* 칸 목록을 항상 같은 길이·같은 모양으로 되돌린다.
   ★ 같은 축이 둘 있어도 막지 않는다 (2026-09-14). 아우터 두 벌을 겹쳐 입히려면
     '아우터' 칸이 둘 필요하다 — 축마다 하나씩으로 강제하면 레이어드를 만들 수
     없다. 칸 수(=VF_CATEGORIES.length)만 서버 MAX_ITEMS 와 맞춰 둔다. */
function cpFitItems(f){
  const had=Array.isArray(f.items);
  const rows=had?f.items:[];
  f.items=VF_CATEGORIES.map((category,i)=>{
    const row=(rows[i]&&typeof rows[i]==='object')?rows[i]:{};
    return {category:VF_CATEGORIES.includes(row.category)?row.category:category,
            image:String(row.image||''),auto:Boolean(row.auto)};
  });
  if(!had&&f.image)f.items[0].image=f.image;
  return f.items;
}
/* 옵션 상태 — 모르는 이름은 버리고 없는 것은 false 로 채운다. */
function cpFitOptions(saved){
  const out={};
  VF_OPTIONS.forEach(o=>{ out[o.key]=Boolean(saved&&saved[o.key]) });
  return out;
}
function cpFitOptionsOf(f){
  if(!f.options)f.options=cpFitOptions(null);
  return f.options;
}
/* 합성 화면 왼쪽 위 옵션 서랍 (2026-09-14).
   ★ 접을 수 있게 둔다 — 결과 이미지를 가리는 자리라, 펼친 채로 두면 정작
     봐야 할 사진이 반쯤 덮인다. 켠 개수는 접혀 있을 때도 보여 준다. */
function cpFitOptsHTML(f){
  const on=cpFitOptionsOf(f);
  const count=VF_OPTIONS.filter(o=>on[o.key]).length;
  const body=f.optsOpen
    ?'<div class="cpFitOptsBody">'+VF_OPTIONS.map(o=>
        '<button type="button" class="cpFitOpt'+(on[o.key]?' on':'')+'" data-vf-opt="'+cpEsc(o.key)+'"'+
        ' aria-pressed="'+(on[o.key]?'true':'false')+'">'+cpEsc(o.label)+'</button>').join('')+
      '<p class="cpFitOptsHint">켠 것만 합성에 반영됩니다.</p></div>':'';
  return '<div class="cpFitOpts'+(f.optsOpen?' on':'')+'">'+
    '<button type="button" class="cpFitOptsBtn" data-vf-opts="1" aria-expanded="'+(f.optsOpen?'true':'false')+'">'+
    '옵션'+(count?'<b>'+count+'</b>':'')+'</button>'+body+'</div>';
}
function cpFitHTML(m){
  const f=m.fit; if(!f)return '';
  const items=cpFitItems(f);
  const result=f.loading?'<div class="cpFitLoader" aria-label="착용 이미지 생성 중"><i class="cpStar">✧</i></div>':
    f.result?'<img class="cpFitResult" src="'+cpEsc(f.result)+'" alt="AI 모델 착용 결과">':
    '<div class="cpFitResultEmpty">완성된 착용 이미지가 여기에 나타납니다.</div>';
  const state=(!f.loading&&f.stateKind==='error')
    ?'<p class="cpFitState error">'+cpEsc(f.status||'')+
     '<button type="button" class="cpFitRetry" data-vf-retry="1">다시 시도</button></p>':'';
  /* 결과 저장 — data URL 을 그대로 내려받는다. 서버를 한 번 더 부르지 않는다. */
  const save=(f.result&&!f.loading)
    ?'<a class="cpFitDl" href="'+cpEsc(f.result)+'" download="feedit-fitting-'+cpEsc(f.key)+'.png"'+
     ' title="이미지 저장" aria-label="착용 이미지 저장">'+CP_IC_DOWN+'</a>':'';
  return '<section class="cpFit" data-fit-key="'+cpEsc(f.key)+'">'+
    '<div class="cpFitHead"><span>GPT IMAGE 2.5 SUNBURST</span><b>코디 입혀보기</b></div>'+
    '<div class="cpFitGrid"><div class="cpFitSetup">'+
      '<p class="cpFitGuide">'+(f.sorting?'사진이 어느 칸인지 확인하는 중입니다…'
        :'종류별 사진을 넣으면 선택한 옷을 한 장의 코디로 합칩니다.')+'</p>'+
      '<div class="cpFitItems">'+items.map((item,index)=>{
        /* 축은 드롭다운으로 직접 고른다 (2026-09-14). 자동 분류가 틀렸을 때
           사진을 지웠다 다시 넣는 것 말고는 고칠 방법이 없었다. */
        const picked=item.auto?VF_AUTO:item.category;
        const select='<select class="cpFitCat" data-vf-cat="'+index+'" aria-label="'+(index+1)+'번 칸 종류">'+
          VF_CATEGORIES.concat([VF_AUTO]).map(c=>
            '<option value="'+cpEsc(c)+'"'+(c===picked?' selected':'')+'>'+cpEsc(c)+'</option>').join('')+
          '</select>';
        return '<div class="cpFitSlot">'+(item.image?'<button type="button" class="cpFitRemove" data-vf-remove="'+index+'" aria-label="'+cpEsc(item.category)+' 이미지 삭제">×</button>':'')+
        '<button type="button" class="cpFitItem" data-vf-pick="'+index+'">'+
        (item.image?'<img class="cpFitItemImg" src="'+cpEsc(item.image)+'" alt="'+cpEsc(item.category)+'">':
          '<span class="cpFitPlus">＋</span>')+'</button>'+select+
        '<input type="file" data-vf-file="'+index+'" accept="image/png,image/jpeg,image/webp" hidden></div>';
      }).join('')+
      '</div>'+
      '<div class="cpFitModels">'+
        '<label><input type="radio" data-vf-model value="woman" name="vf-'+cpEsc(f.key)+'"'+(f.model==='woman'?' checked':'')+'><img src="/assets/vton-models/woman.png" alt="여성 AI 모델"><span>여성 모델</span></label>'+
        '<label><input type="radio" data-vf-model value="man" name="vf-'+cpEsc(f.key)+'"'+(f.model==='man'?' checked':'')+'><img src="/assets/vton-models/man.png" alt="남성 AI 모델"><span>남성 모델</span></label>'+
      '</div><div class="cpFitAction"><button type="button" class="pill cpFitGo" data-vf-generate'+(f.loading?' disabled':'')+'>입혀보기</button></div>'+
    '</div><div class="cpFitOutput">'+cpFitOptsHTML(f)+save+result+state+'</div></div></section>';
}
/* 사용자가 친 문장을 상품명 자리에 쓸 수 있는지. 주소가 섞여 있으면 쓰지 않는다 —
   "https://… 이거 사도 될까?" 에서 주소를 떼어 내도 남는 말은 상품명이 아니다. */
function cpTitleFromText(text){
  const t=String(text||'').trim();
  if(!t)return '';
  return /https?:\/\/|www\.[^\s]+/i.test(t) ? '' : t;
}
function cpAIMessageFor(el){
  const node=el&&el.closest('.msg.ai'), c=cpActiveConvo();
  if(!node||!c)return null;
  return c.messages[Number(node.dataset.msgIndex)]||null;
}
export function cpRenderThread(opts){
  const wrap=$('#cpThreadWrap'), th=$('#cpThread'); if(!wrap||!th)return;
  const c=cpActiveConvo();
  if(cpTypeTimer){ clearTimeout(cpTypeTimer); cpTypeTimer=null; }
  if(!c||!c.messages.length){ wrap.classList.remove('hasMsg'); th.innerHTML=''; return; }
  wrap.classList.add('hasMsg');
  const typeIdx=(opts&&opts.typeLast)?c.messages.length-1:-1;
  th.innerHTML=c.messages.map((m,idx)=>{
    if(m.role==='me'){
      const imgs=(m.images&&m.images.length)
        ?'<div class="bubImgs">'+m.images.map(u=>'<img src="'+u+'" alt="">').join('')+'</div>':'';
      const bub=m.text?('<div class="bub">'+cpEsc(m.text)+'</div>'):'';
      /* 말풍선 아래 아이콘 줄 (2026-09-14) — 재전송 · 수정 · 복사.
         재전송: 같은 질문과 사진을 그대로 한 번 더 보낸다.
         수정  : 입력창으로 되돌려 고쳐서 다시 묻는다(예전 '다시 묻기').
         복사  : 질문 문장만 클립보드로.
         사진이 저장 한도 때문에 빠진 대화는 글만 되돌린다(2026-09-13). */
      const again=(m.text||(m.images&&m.images.length))
        ?'<div class="cpMeActs">'+
          '<button type="button" class="cpMeAct" data-resend="'+idx+'" title="재전송" aria-label="같은 질문 다시 보내기">'+CP_IC_RESEND+'</button>'+
          '<button type="button" class="cpMeAct" data-again="'+idx+'" title="수정" aria-label="질문 고쳐서 다시 묻기">'+CP_IC_EDIT+'</button>'+
          (m.text?'<button type="button" class="cpMeAct" data-copy="'+idx+'" title="복사" aria-label="질문 복사">'+CP_IC_COPY+'</button>':'')+
        '</div>':'';
      const dropped=m.imagesDropped&&!(m.images&&m.images.length)
        ?'<div class="cpDropped">첨부 사진은 저장 한도로 남기지 못했습니다.</div>':'';
      return '<div class="msg me">'+imgs+dropped+bub+again+'</div>';
    }
    if(m.pending) return '<div class="msg ai thinking" data-msg-index="'+idx+'">'+cpWhoHTML(m.stage)+'</div>';
    if(idx===typeIdx) return '<div class="msg ai" data-msg-index="'+idx+'" data-type-target="1">'+cpWhoHTML()+'<div class="say"></div></div>';
    { const card=responseCardHTML(m,ansCardHTML);
      return '<div class="msg ai" data-msg-index="'+idx+'">'+cpWhoHTML()+'<div class="say">'+(m.html||'')+'</div>'+
        card+(m.followHtml||'')+(m.cueHtml||'')+(m.actionsHtml||'')+cpFitHTML(m)+
        cpFeedbackHTML(m,idx)+'</div>'; }
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
/* 살말 지수의 '취향' 축이 보는 것 — 가입할 때 고른 즐겨입는 스타일이다.
   이름만 보내면 서버에서 "블록코어" 와 "벌룬 카고 미디 스커트" 를 맞대게 되어
   겹치는 일이 거의 없다. 그래서 스타일의 대표 어휘(STYLES.kw)도 같이 보낸다 —
   표는 STYLES 에 드러나 있고, 고치면 판단이 바뀐다. */
function cpTasteContext(c){
  const byId=new Map(STYLES.map(s=>[s.id,s]));
  const picked=[...ME.styles].map(id=>byId.get(id)).filter(Boolean);
  const favorite=picked.map(s=>s.n);
  const profiles=picked.map(s=>({name:s.n, keywords:[s.en, ...(s.kw||[])].filter(Boolean).slice(0,8)}));
  const saved=[];
  LIKED.forEach(v=>{
    if(v&&v.nm)saved.push(v.nm);
    if(v&&v.br)saved.push(v.br);
  });
  const searched=[];
  for(const turn of cpHistoryFor(c)) for(const term of (turn.terms||[])){
    if(term&&term.canonical)searched.push(term.canonical);
  }
  return {favorite_styles:favorite.slice(0,10),
          favorite_style_profiles:profiles.slice(0,10),
          searched_terms:[...new Set(searched)].slice(-20),
          saved_terms:[...new Set(saved)].slice(0,30)};
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
async function cpAskLive(c,aiMsg,text,images){
  const run=aiMsg.run;
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
  await askStream({question:text, mode:cpMode(), plan:'FREE', request_id:run.requestId,
                    conversation_id:conv, history,
                    taste_context:cpTasteContext(c),
                    images:(images&&images.length)?images:undefined},{
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
  },{signal:run.controller.signal});
}
function cpRunButton(running){
  const btn=$('#cpSend'); if(!btn)return;
  btn.classList.toggle('stop',running);
  btn.textContent=running?'■':'→';
  btn.setAttribute('aria-label',running?'답변 중단':'보내기');
  btn.title=running?'답변 생성을 중단합니다':'';
}
export function cpStop(){
  const run=cpActiveRun; if(!run)return;
  run.controller.abort();
  fetch(API_BASE+'/v1/chat/cancel',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({request_id:run.requestId})}).catch(()=>{});
}
/* 질문 하나를 대화에 밀어 넣는다. 서버가 떠 있으면 실제 답(마크다운·근거가
   전부 정리된 리포트 카드)을, 아니면 데모용 캔 답을 "생각 중" 뒤에 채운다. */
function cpAsk(text,key,opts){
  const images=(opts&&opts.images)||[];
  if(!text && !images.length)return;
  let c=(opts&&opts.forceNew)?cpNewConvo():cpActiveConvo(); if(!c)c=cpNewConvo();
  c.messages.push({role:'me', text, images});
  if(!c.title)c.title=cpTitleFrom(text||'사진 문의');
  const directFit=wantsVirtualFit(text,images);
  const aiMsg={role:'ai', html:'', key, pending:!directFit};
  if(directFit)aiMsg.fit=cpNewFit(images,text);
  c.messages.push(aiMsg);
  cpRenderList();
  cpRenderThread();
  cpSave();
  if(directFit){ cpFitAutoSort(aiMsg); cpGenerateFitMessage(aiMsg); return; }
  const requestId='cp-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,10);
  const run={controller:new AbortController(),requestId,c,aiMsg};
  aiMsg.run=run;
  cpActiveRun=run; cpRunButton(true);
  (async()=>{
    try{
      let live=false;
      try{ live=await isUp() }catch(e){ live=false }
      if(run.controller.signal.aborted)throw new DOMException('Aborted','AbortError');
      if(!live){cpAskMock(c,aiMsg,key);return}
      await cpAskLive(c,aiMsg,text,images);
    }
    catch(e){
      if(run.controller.signal.aborted){
        aiMsg.pending=false; aiMsg.html='<p>답변 생성을 중단했습니다.</p>';
        aiMsg.cardHtml=''; aiMsg.followHtml=''; aiMsg.cueHtml=''; aiMsg.actionsHtml='';
        if(cpActiveConvo()===c)cpRenderThread();
      }else{
        const last=c.messages[c.messages.length-1];
        if(last===aiMsg) cpAskMock(c,aiMsg,key);
      }
    }finally{
      delete aiMsg.run;
      if(cpActiveRun===run){cpActiveRun=null;cpRunButton(false)}
      cpSave();          /* 답이 끝난 상태 그대로 남긴다 */
    }
  })();
}
export function cpSend(){
  if(cpActiveRun){cpStop();return}
  const ta=$('#cpInput'); const v=(ta&&ta.value.trim())||'';
  if(!v && !cpImages.length)return;
  /* ★ 로그인 관문 (2026-09-13). 예전에는 여기서 그냥 돌아섰다 —
     "발레코어 요즘 어때?" 를 치다 로그인 화면으로 넘어가면 로그인을 마쳐도
     그 질문이 사라져 사용자가 다시 쳐야 했다. 이제는 지금 친 문장과 사진을
     그대로 들고 갔다가, 로그인이 끝나면 팝업을 다시 열어 그대로 보낸다.
     입력창은 여기서 비우지 않는다 — 로그인을 그만두고 돌아왔을 때
     쳐 둔 문장이 남아 있어야 한다. */
  if(!AUTH.in){
    const images=cpImages.map(im=>im.url);
    requireAuth(()=>{
      openChatPopup();
      const box=$('#cpInput');
      if(box && box.value.trim()===v){ box.value=''; box.style.height=''; }
      if(images.length)cpImgTake();
      cpAsk(v,cpKeyFor(v),{images});
    });
    return;
  }
  cpAsk(v,cpKeyFor(v),{images:cpImgTake()});
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
  /* 로그인 전이면 이 질문을 들고 로그인 화면으로 간다. 끝나면 그대로 이어 묻는다. */
  if(!AUTH.in){
    requireAuth(()=>openChatWith(text,key,opts));
    return;
  }
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
  /* ★ force=true — 홈 쪽 연출 잠금(smBusy, 0.9초)에 막히면 한 번 눌러선 안 바뀐다.
     사용자가 직접 누른 전환은 언제나 즉시 먹힌다.
     try/finally 로 감싼 이유: 홈 화면 연출이 실패해도 팝업 화면은 반드시 새로
     그린다 — 예전에는 그 예외 탓에 팝업만 옛 모드로 남아 두 번 눌러야 했다.
     (2026-09-13) */
  try{ smSwitch(!SM_ON,null,true); }
  finally{
    const ov=$('#cpOverlay'); if(ov)ov.classList.toggle('sm',SM_ON);
    cpPaintProfile(); cpRenderList(); cpRenderThread();
  }
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
  const community=e.target.closest('#cpThread [data-community]');
  if(community){
    const c=cpActiveConvo();
    const ai=cpAIMessageFor(community), aiIndex=c&&c.messages.indexOf(ai);
    const user=(c&&aiIndex>=0)?c.messages.slice(0,aiIndex).reverse().find(m=>m.role==='me'):null;
    /* 서버가 확인한 상품명·브랜드·가격이 있으면 그것을 쓴다.
       없을 때만 사용자가 친 문장으로 떨어지되, **링크는 상품명이 아니다** —
       주소가 섞여 있으면 상품명 칸을 비워 두고 사용자가 직접 적게 한다
       (2026-09-11: 카드 상품명에 무신사 주소가 그대로 들어갔다). */
    let served=null;
    try{ served=community.dataset.draft?JSON.parse(community.dataset.draft):null; }
    catch(_e){ served=null; }
    window.__salmalDraft={
      title:(served&&served.title)||cpTitleFromText(user&&user.text),
      brand:(served&&served.brand)||'',
      price:(served&&served.price!=null)?served.price:'',
      image:(user&&user.images&&user.images[0])||''};
    closeChatPopup();
    const nav=document.querySelector('#mNav [data-v="salmal"]');
    if(nav)nav.click();
    setTimeout(()=>{ if(window.smOpenCreate)window.smOpenCreate(window.__salmalDraft) },320);
    return;
  }
  /* '바로 입혀보기' — 누르면 펼치고, 한 번 더 누르면 접는다 (2026-09-13).
     접을 때 만들어 둔 것을 버리지 않는다(m.fitSaved). 사진을 넣고 결과까지 뽑은
     뒤 실수로 닫았다가 다시 열었을 때 처음부터 다시 하게 되면 안 된다.
     ★ 만드는 중에는 닫지 않는다 — 화면에서 사라진 채로 요청만 도는 꼴이 된다. */
  /* 예시 질문 칩 — 빈 화면에서 바로 묻는다 */
  const ask=e.target.closest('#cpEmpty [data-ask]');
  if(ask){ cpAsk(ask.dataset.ask, cpKeyFor(ask.dataset.ask)); return; }
  /* 재전송 — 같은 질문과 사진을 그대로 한 번 더 보낸다 (2026-09-14).
     답이 중간에 끊기거나 마음에 안 들 때, 같은 문장을 다시 치게 하지 않는다. */
  const resend=e.target.closest('#cpThread [data-resend]');
  if(resend){
    if(cpActiveRun)return;                 /* 답이 도는 중에는 겹쳐 보내지 않는다 */
    const c=cpActiveConvo(); if(!c)return;
    const m=c.messages[Number(resend.dataset.resend)]; if(!m)return;
    cpAsk(m.text||'', cpKeyFor(m.text||''), {images:(m.images||[]).slice()});
    return;
  }
  /* 복사 — 질문 문장만. 성공·실패를 버튼이 스스로 말한다(조용히 실패하지 않는다). */
  const copy=e.target.closest('#cpThread [data-copy]');
  if(copy){
    const c=cpActiveConvo(); if(!c)return;
    const m=c.messages[Number(copy.dataset.copy)]; if(!m||!m.text)return;
    cpCopyText(m.text).then(ok=>{
      if(ok)cpFlashBtn(copy);
      cpToast(ok?'질문을 복사했습니다.':'복사하지 못했습니다.');
    });
    return;
  }
  /* 수정 — 질문과 사진을 입력창으로 되돌린다 */
  const again=e.target.closest('#cpThread [data-again]');
  if(again){
    const c=cpActiveConvo(); if(!c)return;
    const m=c.messages[Number(again.dataset.again)]; if(!m)return;
    const ta=$('#cpInput');
    if(ta){ ta.value=m.text||''; ta.style.height=''; ta.style.height=Math.min(ta.scrollHeight,120)+'px'; ta.focus(); }
    if(m.images&&m.images.length){ cpImages=m.images.slice(0,MAX_IMAGES).map(url=>({url})); cpImgPaint(); }
    return;
  }
  /* 답변 피드백 */
  const fb=e.target.closest('#cpThread [data-fb]');
  if(fb){ cpFeedback(Number(fb.dataset.fbIdx), fb.dataset.fb); return; }
  const fbr=e.target.closest('#cpThread [data-fb-reason]');
  if(fbr){ cpFeedback(Number(fbr.dataset.fbReason),'down',fbr.dataset.reason); return; }
  const fbc=e.target.closest('#cpThread [data-fb-close]');
  if(fbc){
    const c=cpActiveConvo(); const m=c&&c.messages[Number(fbc.dataset.fbClose)];
    if(m){ delete m.fbOpen; cpRenderThread(); }
    return;
  }
  /* 착장 생성 재시도 — 실패하면 문구만 남아 다시 만들 방법이 없었다 */
  const retry=e.target.closest('#cpThread [data-vf-retry]');
  if(retry){ const m=cpAIMessageFor(retry); if(m)cpGenerateFitMessage(m); return; }
  const fit=e.target.closest('#cpThread [data-virtual-fit]');
  if(fit){
    const c=cpActiveConvo();
    const m=cpAIMessageFor(fit);
    if(m){
      if(m.fit){
        if(m.fit.loading)return;
        m.fitSaved=m.fit; delete m.fit;
        cpRenderThread();
        return;
      }
      if(m.fitSaved){ m.fit=m.fitSaved; delete m.fitSaved; cpRenderThread(); return; }
      const aiIndex=c.messages.indexOf(m);
      const user=c.messages.slice(0,aiIndex).reverse().find(x=>x.role==='me');
      const images=(user&&user.images)||[];
      m.fit=cpNewFit(images,'');
      cpRenderThread();
      cpFitAutoSort(m);
    }
    return;
  }
  /* 옵션 서랍 열고 닫기 */
  const optsBtn=e.target.closest('#cpThread [data-vf-opts]');
  if(optsBtn){ const m=cpAIMessageFor(optsBtn); if(m&&m.fit){ m.fit.optsOpen=!m.fit.optsOpen; cpRenderThread(); } return; }
  /* 옵션 하나 켜고 끄기. 맞서는 짝(열기/닫기)은 하나만 남는다 —
     둘 다 보내면 프롬프트에 모순된 지시가 실린다(서버도 그때는 둘 다 버린다). */
  const opt=e.target.closest('#cpThread [data-vf-opt]');
  if(opt){
    const m=cpAIMessageFor(opt); if(!m||!m.fit)return;
    const key=opt.dataset.vfOpt, spec=VF_OPTIONS.find(o=>o.key===key); if(!spec)return;
    const on=cpFitOptionsOf(m.fit);
    const next=!on[key];
    if(next&&spec.pair)VF_OPTIONS.forEach(o=>{ if(o.pair===spec.pair)on[o.key]=false });
    on[key]=next;
    cpRenderThread();
    return;
  }
  const remove=e.target.closest('#cpThread [data-vf-remove]');
  if(remove){
    const m=cpAIMessageFor(remove), index=Number(remove.dataset.vfRemove);
    if(m&&m.fit&&cpFitItems(m.fit)[index]){
      const item=cpFitItems(m.fit)[index]; item.image=''; item.auto=false;
      m.fit.result=''; m.fit.status=''; m.fit.stateKind=''; cpRenderThread();
    }
    return;
  }
  const pick=e.target.closest('#cpThread [data-vf-pick]');
  if(pick){ const input=pick.closest('.cpFit').querySelector('[data-vf-file="'+pick.dataset.vfPick+'"]'); if(input)input.click(); return; }
  const generate=e.target.closest('#cpThread [data-vf-generate]');
  if(generate){ cpGenerateFit(generate); return; }
  /* 리포트 저장(PNG) · 공유 (2026-09-14) */
  const rpSave=e.target.closest('#cpThread [data-rp-save]');
  if(rpSave){ cpReportSave(rpSave); return; }
  const rpShare=e.target.closest('#cpThread [data-rp-share]');
  if(rpShare){ cpReportShare(rpShare); return; }
  /* 탭 리포트(구조안 02) — 서버 왕복 없이 그 카드 안에서만 전환한다. */
  const tb=e.target.closest('#cpThread [data-tab]');
  if(tb){
    const box=tb.closest('.tabreport'); if(!box)return;
    const key=tb.dataset.tab;
    box.querySelectorAll('.rpTabBtn').forEach(x=>x.classList.toggle('on', x===tb));
    box.querySelectorAll('.rpTabPanel').forEach(x=>x.classList.toggle('on', x.dataset.panel===key));
    return;
  }
});
document.addEventListener('change',async e=>{
  const cat=e.target.closest('#cpThread [data-vf-cat]');
  if(cat){
    const m=cpAIMessageFor(cat); if(!m||!m.fit)return;
    const item=cpFitItems(m.fit)[Number(cat.dataset.vfCat)]; if(!item)return;
    /* 사용자가 직접 고른 축은 자동 분류가 아니다 — auto 를 내려 두어야
       생성할 때 '자동 분류' 대신 고른 이름이 프롬프트에 실린다. */
    if(cat.value===VF_AUTO){ item.auto=true; }
    else if(VF_CATEGORIES.includes(cat.value)){ item.category=cat.value; item.auto=false; }
    return;
  }
  const model=e.target.closest('#cpThread [data-vf-model]');
  if(model){ const m=cpAIMessageFor(model); if(m&&m.fit)m.fit.model=model.value; return; }
  const file=e.target.closest('#cpThread [data-vf-file]');
  if(file){
    const m=cpAIMessageFor(file), picked=file.files&&file.files[0]; if(!m||!m.fit||!picked)return;
    const index=Number(file.dataset.vfFile);
    try{ const item=cpFitItems(m.fit)[index]; item.image=await imageFileToDataURL(picked); item.auto=false; m.fit.result=''; m.fit.status=''; m.fit.stateKind=''; }
    catch(_err){ m.fit.status='이미지를 읽지 못했습니다.'; m.fit.stateKind='error'; }
    cpRenderThread();
  }
});
async function cpGenerateFit(button){
  const m=cpAIMessageFor(button); if(!m||!m.fit||m.fit.loading)return;
  return cpGenerateFitMessage(m);
}
async function cpGenerateFitMessage(m){
  if(!m||!m.fit||m.fit.loading)return;
  /* 자동 분류가 돌고 있으면 끝난 뒤에 만든다 — 칸이 정해진 다음이라야
     프롬프트에 "2번째 이미지는 하의" 처럼 제대로 실린다. (2026-09-13) */
  if(m.fit._sort){ try{ await m.fit._sort }catch(e){ /* 분류 실패는 넘어간다 */ } }
  if(!m.fit||m.fit.loading)return;
  const items=cpFitItems(m.fit).filter(item=>item.image)
    .map(item=>({image:item.image,category:item.auto?VF_AUTO:item.category}));
  if(!items.length){ m.fit.status='아이템 사진이 하나 이상 필요합니다.'; m.fit.stateKind='error'; cpRenderThread(); return; }
  m.fit.loading=true; m.fit.status=''; m.fit.stateKind='loading'; cpRenderThread();
  try{
    const res=await fetch(API_BASE+'/v1/virtual-fitting',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({items,model_id:m.fit.model,options:cpFitOptionsOf(m.fit)})});
    const raw=await res.text();
    let data;
    try{ data=JSON.parse(raw); }
    catch(_parseError){ throw new Error('입혀보기 서버 응답을 확인하지 못했습니다. 배포 설정을 확인해 주세요.'); }
    if(!res.ok||!data.ok)throw new Error(data.message||'착용 이미지를 만들지 못했습니다.');
    m.fit.result=data.image; m.fit.status=''; m.fit.stateKind='success';
  }catch(err){ m.fit.status=(err&&err.message)||'착용 이미지를 만들지 못했습니다.'; m.fit.stateKind='error'; }
  m.fit.loading=false; cpRenderThread();
}
/* 피드백 한 번. '아쉬움' 은 사유를 고르는 줄로 한 번 더 열린다.
   보내기에 실패해도 화면은 고맙다고 답한다 — 사용자가 할 수 있는 일이 없다. */
function cpFeedback(idx,verdict,reason){
  const c=cpActiveConvo(); if(!c)return;
  const m=c.messages[idx]; if(!m)return;
  if(verdict==='down'&&!reason){ m.fbOpen=true; cpRenderThread(); return; }
  delete m.fbOpen;
  m.feedback=verdict;
  cpRenderThread(); cpSave();
  const user=c.messages.slice(0,idx).reverse().find(x=>x.role==='me');
  sendAnswerFeedback({verdict, reason:reason||'', mode:cpMode(),
    question:(user&&user.text)||'', intent:(m.turn&&m.turn.intent)||''});
}

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

/* ══════════════════════════════════════════════════════
   2026-09-14 추가 — 복사 · 알림 한 줄 · 리포트 저장/공유
   ══════════════════════════════════════════════════════ */

/* 클립보드. 보안 컨텍스트가 아니면(예: http 로 연 로컬 화면) Clipboard API 가
   없으므로 옛 방식으로 한 번 더 시도한다. 성공 여부를 그대로 돌려준다 —
   부르는 쪽이 "복사했습니다" 를 거짓으로 말하지 않게. */
async function cpCopyText(text){
  const value=String(text||'');
  if(!value)return false;
  try{
    if(navigator.clipboard&&window.isSecureContext){ await navigator.clipboard.writeText(value); return true }
  }catch(_e){ /* 아래 옛 방식으로 */ }
  try{
    const ta=document.createElement('textarea');
    ta.value=value; ta.setAttribute('readonly','');
    ta.style.cssText='position:fixed;top:-1000px;opacity:0';
    document.body.appendChild(ta); ta.select();
    const ok=document.execCommand('copy'); ta.remove(); return ok;
  }catch(_e){ return false }
}
/* 눌린 버튼이 스스로 "됐다" 고 말한다 — 화면을 다시 그리지 않는다(누른 자리가
   사라지면 무엇이 일어났는지 알 수 없다). */
function cpFlashBtn(btn){
  if(!btn)return;
  btn.classList.add('done');
  setTimeout(()=>btn.classList.remove('done'),1300);
}
let cpToastT=0;
function cpToast(text){
  const ov=$('#cpOverlay'); if(!ov)return;
  let box=$('#cpToast');
  if(!box){ box=document.createElement('div'); box.id='cpToast'; box.className='cpToast'; ov.appendChild(box); }
  box.textContent=String(text||'');
  box.classList.add('on');
  clearTimeout(cpToastT);
  cpToastT=setTimeout(()=>box.classList.remove('on'),2200);
}
/* 답변 본문(서버가 보낸 HTML)에서 글만 꺼낸다 — 공유는 태그가 아니라 말이다. */
function cpPlainText(html){
  const box=document.createElement('div');
  box.innerHTML=String(html||'');
  return (box.textContent||'').replace(/\n{3,}/g,'\n\n').trim();
}
/* 리포트 카드를 그림으로. html2canvas 는 누를 때 처음 불러온다 —
   쓰지 않는 사용자에게까지 번들을 지우지 않기 위해서다. */
async function cpReportCanvas(card){
  const mod=await import('html2canvas');
  const html2canvas=mod.default||mod;
  return html2canvas(card,{
    backgroundColor:'#ffffff',
    scale:Math.min(2,window.devicePixelRatio||1),
    useCORS:true,
    /* 저장·공유 버튼 자체는 그림에 넣지 않는다 */
    ignoreElements:el=>!!(el&&el.classList&&el.classList.contains('rpTools')),
  });
}
async function cpReportSave(btn){
  const card=btn.closest('.skillReport'); if(!card||btn.disabled)return;
  btn.disabled=true;
  try{
    const canvas=await cpReportCanvas(card);
    const a=document.createElement('a');
    a.href=canvas.toDataURL('image/png');
    a.download='feedit-report-'+Date.now().toString(36)+'.png';
    document.body.appendChild(a); a.click(); a.remove();
    cpFlashBtn(btn); cpToast('리포트를 이미지로 저장했습니다.');
  }catch(_e){ cpToast('리포트 이미지를 만들지 못했습니다.'); }
  btn.disabled=false;
}
/* 공유 — 기기가 지원하면 이미지째 넘기고(모바일 공유 시트), 없으면 답변 글과
   주소를 클립보드에 넣는다. 조용히 아무 일도 안 일어나는 경우를 만들지 않는다. */
async function cpReportShare(btn){
  const card=btn.closest('.skillReport');
  const m=cpAIMessageFor(btn);
  const text=cpPlainText(m&&m.html);
  const url=location.href;
  try{
    if(card&&navigator.share&&navigator.canShare){
      const canvas=await cpReportCanvas(card);
      const blob=await new Promise(done=>canvas.toBlob(done,'image/png'));
      if(blob){
        const file=new File([blob],'feedit-report.png',{type:'image/png'});
        if(navigator.canShare({files:[file]})){
          await navigator.share({files:[file],title:'FEEDiT 리포트',text});
          return;
        }
      }
    }
    if(navigator.share){ await navigator.share({title:'FEEDiT 리포트',text,url}); return; }
  }catch(err){
    if(err&&err.name==='AbortError')return;      /* 사용자가 공유 시트를 닫았다 */
  }
  const ok=await cpCopyText((text?text+'\n\n':'')+url);
  if(ok)cpFlashBtn(btn);
  cpToast(ok?'리포트 내용을 클립보드에 복사했습니다.':'공유하지 못했습니다.');
}
