import { $, $$ } from '../../../core/static/js/dom.js';

/* ══════════════════════════════════════════════════════════════
   직업 인증 · 배지
   --------------------------------------------------------------
   가입 · 회원정보 수정에서 직업을 고르고, 증빙 서류를 올린다.
   서류는 관리자가 확인해 승인해야만 배지와 사이드바 직위에 반영된다.

   ★ 직업 선택은 선택 입력이다.
     관련 직종이어도 인증이 번거로워 Basic 으로 가입하는 사람이 있다.
     그래서 직업을 비워 두거나, 승인 전이면 모두 Basic 으로 보인다.

   목업이라 서버가 없다. 심사 대기열(JOB_QUEUE)은 이 모듈 안에만 있다.
   API 가 붙으면 jobSubmit / jobDecide 안쪽만 갈아 끼우면 된다.
   ══════════════════════════════════════════════════════════════ */

/* 드롭다운 목록 — fashion:true 는 주황 배지, Basic 은 검정 배지 */
export const JOBS=[
  {id:'MD',       label:'MD',       fashion:true,  doc:'재직증명서'},
  {id:'Buyer',    label:'Buyer',    fashion:true,  doc:'재직증명서'},
  {id:'Designer', label:'Designer', fashion:true,  doc:'재직증명서'},
  {id:'Stylist',  label:'Stylist',  fashion:true,  doc:'재직증명서'},
  {id:'Creator',  label:'Creator',  fashion:true,  doc:'운영 중인 SNS 계정 캡처'},
  {id:'Editor',   label:'Editor',   fashion:true,  doc:'운영 중인 SNS 계정 캡처'},
  {id:'Marketer', label:'Marketer', fashion:true,  doc:'재직증명서'},
  {id:'Platform', label:'Platform', fashion:true,  doc:'재직증명서'},
  {id:'Student',  label:'Student',  fashion:true,  doc:'입학증명서 또는 재학증명서'},
  {id:'Basic',    label:'Basic',    fashion:false, doc:''}
];
export const jobOf=id=>JOBS.find(j=>j.id===id)||null;
/* 서류가 필요한 직업인가 — Basic 은 확인할 것이 없으니 바로 반영한다 */
export const jobNeedsDoc=id=>{ const j=jobOf(id); return !!(j&&j.fashion) };

/* 목업 시연용 — 가입 직후엔 관리자 계정이 아니라 심사 화면을 열 사람이 없다.
   시연 중에도 승인 흐름을 보여 줄 수 있게 메뉴를 열어 둔다.
   실제 서비스에서는 false 로 두고 관리자 계정에서만 보이게 한다. */
export const JOB_REVIEW_DEMO=true;

/* 심사 대기열 — {id, user, nick, job, major, file, url, at, status} */
export const JOB_QUEUE=[];
let JOB_UID=1;

const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,
  c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

/* ── 배지 ──
   승인된 직업만 주황으로 선다. 직업이 없거나 승인 전이면 검정 Basic. */
export function jobBadgeHTML(jobId){
  const j=jobOf(jobId)||jobOf('Basic');
  return '<span class="jobBadge'+(j.fashion?'':' basic')+'" title="'+esc(j.label)+'">'+esc(j.label)+'</span>';
}
/* 사용자 객체에서 지금 보여 줄 직업 — 관리자 계정은 직업 배지를 달지 않는다 */
export function jobShown(u){
  if(!u||u.role==='admin')return null;
  return u.job||'Basic';
}
/* 사이드바 하단 닉네임 아래 한 줄 */
export function jobPlanText(u){
  if(!u)return '';
  if(u.role==='admin')return u.plan||'ADMIN';
  const j=jobOf(u.job)||jobOf('Basic');
  const req=jobPendingOf(u);
  return j.label+(u.job==='Student'&&u.major?' · '+u.major:'')+(req?' · 인증 대기':'');
}
export function jobPendingOf(u){
  return JOB_QUEUE.find(r=>r.user===u&&r.status==='pending')||null;
}

/* ── 가입 · 수정 폼 한 줄 ──
   [파일 첨부 버튼] [직업 드롭다운] 순서. 직업에 맞춰 안내 문구가 바뀐다.
   prefix 는 'su'(가입) 또는 'edit'(회원정보 수정). */
export function jobFieldBind(prefix){
  const sel=$('#'+prefix+'Job'), file=$('#'+prefix+'JobFile'),
        btn=$('#'+prefix+'JobFileBtn'), msg=$('#'+prefix+'JobMsg'),
        majorWrap=$('#'+prefix+'MajorWrap');
  if(!sel||sel.dataset.bound)return;
  sel.dataset.bound='1';
  if(sel.options.length<=1){
    sel.insertAdjacentHTML('beforeend',JOBS.map(j=>
      '<option value="'+j.id+'">'+(j.id==='Student'?'Student (전공)':j.id==='Basic'?'Basic (일반 사용자)':j.label)+'</option>').join(''));
  }
  btn.addEventListener('click',()=>{ if(!btn.disabled)file.click() });
  file.addEventListener('change',()=>jobFieldPaint(prefix));
  sel.addEventListener('change',()=>{
    if(!jobNeedsDoc(sel.value)){ file.value='' }
    jobFieldPaint(prefix);
  });
  jobFieldPaint(prefix);
}
export function jobFieldPaint(prefix,note){
  const sel=$('#'+prefix+'Job'), file=$('#'+prefix+'JobFile'),
        btn=$('#'+prefix+'JobFileBtn'), msg=$('#'+prefix+'JobMsg'),
        majorWrap=$('#'+prefix+'MajorWrap');
  if(!sel)return;
  const j=jobOf(sel.value), f=file.files&&file.files[0];
  const need=jobNeedsDoc(sel.value);
  btn.disabled=!need;
  btn.classList.toggle('has',!!f);
  btn.querySelector('span').textContent=f?f.name:'서류 첨부';
  if(majorWrap)majorWrap.hidden=(sel.value!=='Student');
  if(!msg)return;
  let t='', cls='fieldMsg';
  if(note){ t=note }
  else if(!j){ t='선택 입력입니다. 비워 두면 Basic 으로 가입됩니다.' }
  else if(!need){ t='Basic 은 인증 없이 바로 적용됩니다.' }
  else if(f){ t='관리자 승인 후 '+j.label+' 배지가 달립니다.'; cls+=' ok' }
  else { t='첨부할 서류: '+j.doc+'\n관리자 승인 후 배지가 달립니다.' }
  msg.innerHTML=esc(t).replace(/\n/g,'<br>');
  msg.className=cls;
}
export function jobFieldReset(prefix,u){
  const sel=$('#'+prefix+'Job'), file=$('#'+prefix+'JobFile'), major=$('#'+prefix+'Major');
  if(!sel)return;
  sel.value=(u&&u.role!=='admin'&&u.job)||'';
  if(file)file.value='';
  if(major)major.value=(u&&u.major)||'';
  const req=u&&jobPendingOf(u);
  jobFieldPaint(prefix, req?(jobOf(req.job).label+' 인증을 심사 중입니다.\n새 서류를 올리면 이전 신청을 대신합니다.'):'');
}
/* 폼 값 검사 — 문제가 있으면 문구, 없으면 '' */
export function jobFieldCheck(prefix,u){
  const sel=$('#'+prefix+'Job'), file=$('#'+prefix+'JobFile');
  if(!sel)return '';
  const f=file.files&&file.files[0];
  if(!jobNeedsDoc(sel.value))return '';
  /* 이미 승인된 직업을 그대로 두는 것은 다시 인증할 필요가 없다 */
  if(u&&u.job===sel.value&&!f)return '';
  if(u&&jobPendingOf(u)&&jobPendingOf(u).job===sel.value&&!f)return '';
  if(!f)return '선택한 직업을 확인할 서류를 첨부하거나, 직업을 비워 두세요.';
  if(f.size>10*1024*1024)return '서류 파일은 10MB 이하로 올려 주세요.';
  return '';
}
/* 폼 값을 사용자에게 반영한다.
   Basic · 비움 → 바로 반영. 패션 직종 + 서류 → 심사 대기열로. */
export function jobFieldApply(prefix,u){
  const sel=$('#'+prefix+'Job'), file=$('#'+prefix+'JobFile'), major=$('#'+prefix+'Major');
  if(!sel||!u)return null;
  const v=sel.value, f=file.files&&file.files[0];
  const mj=major?major.value.trim().slice(0,20):'';
  if(!jobNeedsDoc(v)){
    /* 관리자 계정은 직업을 바꾸지 않는다 */
    if(u.role!=='admin'){
      u.job=v||'Basic'; u.major='';
      JOB_QUEUE.forEach(r=>{ if(r.user===u&&r.status==='pending')r.status='cancelled' });
    }
    jobNotify(); return null;
  }
  if(!f){
    if(v==='Student'&&u.job==='Student')u.major=mj||u.major;
    jobNotify(); return null;
  }
  return jobSubmit(u,v,mj,f);
}
export function jobSubmit(u,job,major,file){
  JOB_QUEUE.forEach(r=>{ if(r.user===u&&r.status==='pending')r.status='cancelled' });
  const isImg=/^image\//.test(file.type);
  const req={id:JOB_UID++, user:u, nick:u.name, job, major:job==='Student'?major:'',
    file:file.name, url:isImg?URL.createObjectURL(file):'', at:new Date(), status:'pending'};
  JOB_QUEUE.unshift(req);
  jobNotify();
  return req;
}
/* 관리자 결정 — 승인이면 그때 비로소 직업과 배지가 바뀐다 */
export function jobDecide(id,ok){
  const r=JOB_QUEUE.find(x=>x.id===id); if(!r||r.status!=='pending')return;
  r.status=ok?'approved':'rejected';
  if(ok){ r.user.job=r.job; r.user.major=r.major }
  jobNotify();
}
function jobNotify(){ try{ document.dispatchEvent(new CustomEvent('feedit:job')) }catch(e){} }

/* ── 관리자 심사 모달 ── */
export function jobReviewRender(){
  const host=$('#jobReviewList'); if(!host)return;
  const list=JOB_QUEUE.filter(r=>r.status!=='cancelled');
  if(!list.length){
    host.innerHTML='<p class="jrEmpty">아직 들어온 인증 신청이 없습니다.<br>가입이나 회원정보 수정에서 서류를 올리면 여기에 쌓입니다.</p>';
    return;
  }
  const ST={pending:'대기',approved:'승인',rejected:'반려'};
  host.innerHTML=list.map(r=>{
    const j=jobOf(r.job);
    return '<div class="jrItem '+r.status+'">'+
      '<div class="jrThumb">'+(r.url?'<img src="'+r.url+'" alt="">':'<span>FILE</span>')+'</div>'+
      '<div class="jrBody">'+
        '<div class="jrHead">'+jobBadgeHTML(r.job)+'<b>'+esc(r.nick)+'</b>'+
          '<em class="jrSt">'+ST[r.status]+'</em></div>'+
        '<div class="jrMeta">'+esc(j?j.doc:'')+(r.major?' · 전공 '+esc(r.major):'')+'<br>'+
          (r.url?'<a href="'+r.url+'" target="_blank" rel="noopener">'+esc(r.file)+'</a>':esc(r.file))+'</div>'+
      '</div>'+
      (r.status==='pending'
        ? '<div class="jrActs"><button type="button" class="pill ghost sm" data-jr-no="'+r.id+'">반려</button>'+
          '<button type="button" class="pill sm" data-jr-ok="'+r.id+'">승인</button></div>'
        : '')+
    '</div>';
  }).join('');
}
export function jobReviewBind(onDone){
  const host=$('#jobReviewList');
  if(!host||host.dataset.bound)return;
  host.dataset.bound='1';
  host.addEventListener('click',e=>{
    const ok=e.target.closest('[data-jr-ok]'), no=e.target.closest('[data-jr-no]');
    if(!ok&&!no)return;
    const id=+(ok?ok.dataset.jrOk:no.dataset.jrNo);
    jobDecide(id,!!ok);
    jobReviewRender();
    if(onDone)onDone(!!ok);
  });
}
