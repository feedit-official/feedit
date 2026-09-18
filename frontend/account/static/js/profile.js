import { $, $$, HAS_A, aAnimate, aStagger } from '../../../core/static/js/dom.js';
import { BADGES, bgDetail, bgRender } from './badges.js';
import { IMG, itemCard, LIKED, STYLES, toggleLike } from '../../../home/static/js/chat.js';
import { SIMG } from '../../../style/static/js/style_page.js';
import { styleProductCard, styleProductsURL } from '../../../style/static/js/products.js';
import { goView } from '../../../app_shell/static/js/router.js';
import { rkLevelOf, rkPaintAll, rkPaintAv, xpPaint } from './rank.js';
import { trRender } from '../../../trend/static/js/dispatch.js';
import { JOB_REVIEW_DEMO, jobFieldApply, jobFieldBind, jobFieldCheck, jobFieldReset, jobReviewBind, jobReviewRender } from './job.js';
import { googleLogin, googleSignupAccount, loginAccount, logoutAccount, prepareGoogle, saveAccount, saveLiked, session, signupAccount } from './account_api.js';

/* 내 계정 — 운영자라 최고 등급 고정 */
export const ME={name:'혁진',mail:'hyeokjin@feedit.co.kr',initial:'혁',xp:9400,   /* 누적 경험치. rank 는 여기서 계산된다 */
          height:'',weight:'',   /* 체형 — 가입·정보수정에서 받는다 */
          plan:'ADMIN · 서울',saved:128,
          role:'admin',      /* 운영자 계정 — 직업 배지 대신 ADMIN 을 유지한다. 새로 가입하면 'user' */
          job:'',            /* 승인된 직업(job.js JOBS id). 비어 있거나 승인 전이면 Basic 으로 보인다 */
          major:'',          /* Student 전공 */votes:42,hit:94,
          bio:'',            /* 비어 있으면 예시 문구가 흐리게 대신 선다 */
          birth:'',          /* 가입·정보수정에서 채운다 */
          ava:0,             /* 프로필 아이콘 색 (AVA 인덱스) */
          styles:new Set(['block','ameka','street'])};  /* 즐겨입는 스타일 (가입 시 선택) */
/* rank 는 저장하지 않는다 — 경험치에서 항상 다시 센다.
   이렇게 두면 XP 만 올려도 링·문구·바가 한꺼번에 따라온다. */
Object.defineProperty(ME,'rank',{get(){ return rkLevelOf(ME.xp) }, enumerable:true});

/* DB 사용자 응답을 기존 화면 모델(ME)에 옮긴다.
   마크업과 렌더 함수는 그대로 두고, 값의 출처만 목업에서 API로 바꾼다. */
function applyAccount(user){
  if(!user)return;
  ME.id=user.id==null?null:user.id;   /* 챗봇에 로그인 사실을 알릴 때 쓴다 (2026-09-18) */
  ME.name=user.nickname||user.username||ME.name;
  ME.initial=ME.name[0]||'F';
  ME.mail=user.email||user.username||'';
  ME.birth=user.birth_date||'';
  ME.height=user.height==null?'':String(user.height);
  ME.weight=user.weight==null?'':String(user.weight);
  ME.bio=user.bio||'';
  ME.ava=Number.isFinite(+user.avatar)?+user.avatar:0;
  ME.role=user.role||'user';
  ME.job=user.job||'';
  ME.major=user.major||'';
  ME.saved=Number(user.saved_count||0);
  ME.votes=Number(user.vote_count||0);
  const names=new Set(Array.isArray(user.styles)?user.styles:[]);
  ME.styles.clear();
  STYLES.forEach(s=>{ if(names.has(s.n))ME.styles.add(s.id) });
}
const styleNames=()=>STYLES.filter(s=>ME.styles.has(s.id)).map(s=>s.n);

/* 프로필 아이콘 색 — 팔레트 밖으로 나가지 않게 코랄·먹·모래 계열만 썼다 */
const AVA=[
  ['#ff6b4a','#ffb199'], ['#1c1a17','#4a453d'], ['#c8a27a','#e6d3bd'],
  ['#3d5a6c','#7d9db0'], ['#6b5b95','#a89bc4'], ['#4a6b52','#8fae95']
];
/* 아바타가 쓰이는 곳(마이페이지 원형 + 헤더 작은 원)을 한 번에 칠한다 */
function avaPaint(){
  const g=AVA[ME.ava]||AVA[0];
  const bg='linear-gradient(135deg,'+g[0]+','+g[1]+')';
  const c=$('#avatarInitial'); if(c){ c.style.background=bg; rkPaintAv(c, ME.rank) }
  $$('.mAuth .meAv').forEach(e=>{
    e.style.background=bg; e.style.color='#fff'; rkPaintAv(e, ME.rank);
  });
}

/* ── 소개글 인라인 편집 ──────────────────────────────────
   따로 창을 띄우지 않는다. 연필을 누르면 그 문장이 그대로 입력칸이 되고,
   Enter 나 바깥 클릭으로 저장, Esc 로 되돌린다. */
const BIO_MAX=60;
export function bioPaint(){
  const p=$('#trProfBio'); if(!p)return;
  p.textContent=ME.bio||'';
  p.classList.toggle('isEmpty',!ME.bio);
}
function bioEdit(on){
  const p=$('#trProfBio'), b=$('#trBioEdit');
  if(!p||!b)return;
  if(on){
    p.dataset.prev=ME.bio||'';
    p.setAttribute('contenteditable','plaintext-only');
    b.classList.add('on');
    p.focus();
    /* 커서를 문장 끝으로 */
    const r=document.createRange(); r.selectNodeContents(p); r.collapse(false);
    const s=getSelection(); s.removeAllRanges(); s.addRange(r);
  }else{
    ME.bio=(p.textContent||'').replace(/\s+/g,' ').trim().slice(0,BIO_MAX);
    p.removeAttribute('contenteditable');
    b.classList.remove('on');
    bioPaint();
    if(AUTH.in) saveAccount({bio:ME.bio}).then(d=>applyAccount(d.user))
      .catch(e=>acctToast(e.message||'소개글을 저장하지 못했습니다.'));
  }
}
function bioBind(){
  const p=$('#trProfBio'), b=$('#trBioEdit');
  if(!p||!b||b.dataset.bound)return;
  b.dataset.bound='1';
  b.addEventListener('click',e=>{ e.stopPropagation();
    bioEdit(p.getAttribute('contenteditable')===null); });
  p.addEventListener('click',()=>{ if(p.getAttribute('contenteditable')===null)bioEdit(true) });
  p.addEventListener('input',()=>{ p.classList.toggle('isEmpty',!p.textContent.trim()) });
  p.addEventListener('keydown',e=>{
    if(e.key==='Enter'){ e.preventDefault(); bioEdit(false) }
    else if(e.key==='Escape'){ e.preventDefault();
      p.textContent=p.dataset.prev||''; bioEdit(false) }
    else if(p.textContent.length>=BIO_MAX&&e.key.length===1&&!e.metaKey&&!e.ctrlKey)e.preventDefault();
  });
  p.addEventListener('blur',()=>{ if(p.getAttribute('contenteditable')!==null)bioEdit(false) });
}
bioBind();

/* ══════════════════════════════════════════════════════════════
   계정 — 로그인 · 회원가입 · 마이페이지
   --------------------------------------------------------------
   목업이라 서버가 없다. 인증 흉내는 여기서만 내고,
   실제 값은 전부 ME(사용자)와 기존 데이터(SV 찜 · VOTES 투표 · STYLES 스타일)에
   연결해 둔다. API 가 붙으면 authLogin / authSignup / acctSave 안쪽만 갈아 끼우면 된다.
   ══════════════════════════════════════════════════════════════ */
export var AUTH = { in: false };
/* 로그인 없이 쓸 수 없는 기능(챗봇 사용 · 트렌드 분석 · 살!말? 투표/등록)의
   공통 관문. 로그인 전이면 로그인 화면으로 보내고 false 를 돌려준다. */
/* 로그인 관문에 걸려 중단된 동작 하나. 로그인/가입이 끝나면 그대로 이어 한다.
   ★ 2026-09-13. 챗봇에 "발레코어 요즘 어때?" 를 치던 중 로그인 화면으로 넘어가면
     로그인을 마쳐도 질문이 사라져 있었다. 사용자는 같은 문장을 다시 쳐야 했다.
     하나만 들고 있는다 — 여러 개를 쌓아 두면 로그인 뒤에 예상치 못한 화면이
     연달아 뜬다. 새로 걸리면 앞의 것을 버린다. */
let pendingAfterAuth = null;
export function requireAuth(resume){
  if(AUTH.in)return true;
  pendingAfterAuth = (typeof resume === 'function') ? resume : null;
  goView('login');
  return false;
}
/* 로그인을 포기하고 다른 화면으로 갔다면 이어 할 일도 버린다 —
   한참 뒤에 로그인했을 때 잊고 있던 질문이 튀어나오면 안 된다. */
export function dropPendingAuth(){ pendingAfterAuth = null; }
function runPendingAuth(){
  const fn = pendingAfterAuth;
  pendingAfterAuth = null;
  if(!fn) return;
  /* 화면 전환(goView) 애니메이션이 끝난 뒤에 이어 한다 */
  setTimeout(() => { try{ fn() }catch(e){ /* 이어 하기 실패는 조용히 넘긴다 */ } }, 320);
}
/* 회원가입 진행 중 구글 모드 여부 — 가입 폼을 벗어나면 반드시 초기화된다 */
let signupGoogleMode = false;
/* 찜(위시리스트) — 실제 사용자 데이터가 없으므로 localStorage 목업(chat.js)이 출처다.
   예전에는 트렌드의 SV 예시 9개를 시드로 넣었지만, 이제 찜한 키워드 화면이
   '내가 실제로 찜한 상품'으로 그려지므로 가짜 시드는 넣지 않는다. */

/* 헤더 오른쪽 — 로그인 전에는 [로그인], 후에는 [혁진] 버튼이 마이페이지로 */
function authPaint(){
  const b = $('#mAuthBtn');
  if(!b) return;
  if(AUTH.in){
    b.className = 'pill me';
    b.removeAttribute('data-v');       /* 전역 [data-v] 위임 대신 메뉴를 연다 */
    b.innerHTML = '<span class="meAv">' + ME.initial + '</span>' + ME.name +
      '<svg class="meCaret" viewBox="0 0 12 12" fill="none" stroke="currentColor" ' +
      'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<path d="M2.5 4.5L6 8l3.5-3.5"/></svg>';
    avaPaint();
    const mj = $('#menuJobReview');
    if(mj) mj.hidden = !(ME.role === 'admin' || JOB_REVIEW_DEMO);
  }else{
    b.className = 'pill';
    b.dataset.v = 'login';
    b.textContent = '로그인';
    acctMenu(false);
  }
}
/* 로그인 뒤 이름 버튼을 누르면 뜨는 작은 메뉴 */
function acctMenu(on){
  const m = $('#acctMenu');
  if(m){
    m.classList.toggle('on', on === undefined ? !m.classList.contains('on') : on);
    const w = m.closest('.mAuthWrap');
    if(w) w.classList.toggle('open', m.classList.contains('on'));
  }
}
function authLogin(user){
  applyAccount(user);
  AUTH.in = true;
  authPaint();
  goView('home');
  runPendingAuth();
}
async function authLogout(){
  try{
    await logoutAccount();
    AUTH.in = false;
    pendingAfterAuth = null;
    authPaint();
    goView('home');
  }catch(e){ acctToast(e.message||'로그아웃하지 못했습니다.') }
}
/* 회원가입 완료(구글 · 아이디 공통) — 홈 화면으로 보낸 뒤 그 위에
   '즐겨입는 스타일' 선택 팝업을 띄운다. 팝업을 닫아도 화면은 홈에 그대로 남는다. */
function signupComplete(){
  AUTH.in = true;
  authPaint();
  ME.styles.clear();   /* 팝업은 항상 빈 상태에서 시작한다 */
  goView('home');
  openStyleSelect();
  runPendingAuth();
}
/* 작은 확인 토스트 — 살!말? 쪽과 같은 #toast 를 그대로 쓴다 */
var acctToastT;
function acctToast(msg){
  const t = $('#toast'); if(!t) return;
  t.textContent = msg; t.classList.add('on');
  clearTimeout(acctToastT);
  acctToastT = setTimeout(() => t.classList.remove('on'), 2200);
}

/* 스타일 칩 — 가입·마이페이지가 스타일 페이지와 같은 10종(STYLES)을 쓴다 */
const STYLE_MAX = 3;
function acctChips(host, sel){
  if(!host) return;
  host.innerHTML = STYLES.map(s =>
    '<button type="button" class="chip' + (sel.has(s.id) ? ' on' : '') +
    '" data-style-pick="' + s.id + '">' + s.n + '</button>').join('');
  host.onclick = e => {
    const b = e.target.closest('[data-style-pick]');
    if(!b) return;
    const id = b.dataset.stylePick;
    /* 가입 팝업과 같은 규칙 — 즐겨입는 스타일은 최대 3개 */
    if(!sel.has(id) && sel.size >= STYLE_MAX){
      acctToast('즐겨입는 스타일은 ' + STYLE_MAX + '개까지 고를 수 있어요. 하나를 먼저 빼 주세요.');
      return;
    }
    sel.has(id) ? sel.delete(id) : sel.add(id);
    b.classList.toggle('on', sel.has(id));
    if(host.id === 'styleWrap'){
      myRender();   /* 마이페이지는 고르는 즉시 추천이 바뀐다 */
      try{ document.dispatchEvent(new CustomEvent('feedit:styles')) }catch(e){}
    }
  };
}

/* 가입 완료 팝업 — 코어/원형 구분 없이 STYLES 순서 그대로, 최대 3개까지 중복 선택.
   처음엔 아무것도 선택돼 있지 않고(= signupComplete 에서 비워 둔다),
   3개가 찬 상태에서 새로 고르면 '가장 최근에 골랐던 것'의 테두리가 새 선택으로 옮겨간다. */
let styleSelOrder = [];
function styleSelectBuild(){
  styleSelOrder = [...ME.styles];
  const host = $('#styleSelectGrid'); if(!host) return;
  host.innerHTML = STYLES.map(s =>
    '<button type="button" class="styleSelCard' + (ME.styles.has(s.id) ? ' on' : '') +
    '" data-style-pick="' + s.id + '"><img src="' + SIMG(s) + '" alt="" draggable="false">' +
    '<span>' + s.n + '</span></button>').join('');
}
function styleSelectBind(){
  const host = $('#styleSelectGrid');
  if(host && !host.dataset.bound){
    host.dataset.bound = '1';
    host.addEventListener('click', e => {
      const b = e.target.closest('[data-style-pick]'); if(!b) return;
      const id = b.dataset.stylePick;
      if(ME.styles.has(id)){
        ME.styles.delete(id); b.classList.remove('on');
        styleSelOrder = styleSelOrder.filter(x => x !== id);
      }else{
        if(ME.styles.size >= STYLE_MAX){
          const last = styleSelOrder.pop();   /* 가장 최근 선택을 밀어낸다 */
          if(last){
            ME.styles.delete(last);
            const prev = host.querySelector('[data-style-pick="' + last + '"]');
            if(prev) prev.classList.remove('on');
          }
        }
        ME.styles.add(id); b.classList.add('on');
        styleSelOrder.push(id);
      }
    });
  }
  const save = $('#styleSelectSave');
  if(save && !save.dataset.bound){
    save.dataset.bound = '1';
    save.addEventListener('click', async () => {
      save.disabled=true;
      try{
        const data=await saveAccount({styles:styleNames()});
        applyAccount(data.user);
        acctModal('styleSelectModal', false);
        acctChips($('#styleWrap'), ME.styles);   /* 마이페이지 칩과 동기화 */
        myRender();
        acctToast('즐겨입는 스타일이 DB에 저장됐어요.');
      }catch(e){ acctToast(e.message||'스타일을 저장하지 못했습니다.') }
      finally{ save.disabled=false }
      /* 취향이 바뀐 것을 화면들에 알린다 — 챗봇 팝업의 '스타일 고르기' 안내는
         이 신호를 받아 사라진다(2026-09-13). */
      try{ document.dispatchEvent(new CustomEvent('feedit:styles')) }catch(e){}
    });
  }
  const close = $('#styleSelectClose');
  if(close && !close.dataset.bound){
    close.dataset.bound = '1';
    close.addEventListener('click', () => acctModal('styleSelectModal', false));
  }
}
export function openStyleSelect(){
  styleSelectBuild();
  styleSelectBind();
  acctModal('styleSelectModal', true);
}

/* 아이템 카드 — '스타일' 상세와 마이페이지가 같은 chat.js 의 itemCard() 를 그대로 쓴다 */

/* ── 오늘의 추천 (실데이터) ─────────────────────────── */
const REC_PER_BLOCK = 8;       /* 칸마다 보여 줄 카드 수 */
const REC_POOL = 16;           /* 스타일마다 받아 오는 후보 수 — 여기서 날짜별로 골라 쓴다 */
const REC_RISE = ['확산','재상승','재점화','정점 통과'];
const recCache = new Map();    /* 스타일명 → 상품 목록 Promise. 칩을 누를 때마다 다시 받지 않는다 */
let recSeq = 0;

function recFetch(styleName){
  if(!recCache.has(styleName)){
    const job = fetch(styleProductsURL(styleName, 0, REC_POOL))
      .then(r => r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)))
      .then(j => (j && j.status === 'ok' && j.data && Array.isArray(j.data.items)) ? j.data.items : [])
      .catch(e => { recCache.delete(styleName); throw e });   /* 실패는 캐시하지 않는다 */
    recCache.set(styleName, job);
  }
  return recCache.get(styleName);
}

/* 날짜를 씨앗으로 섞는다 — 같은 날에는 같은 순서, 다음 날에는 다른 상품이 앞에 선다 */
function recDayShuffle(list, salt){
  const d = new Date();
  let h = (d.getFullYear() * 400 + d.getMonth() * 31 + d.getDate()) ^ salt;
  const rnd = () => { h = (h * 1103515245 + 12345) & 0x7fffffff; return h / 0x7fffffff };
  const out = list.slice();
  for(let i = out.length - 1; i > 0; i--){ const j = Math.floor(rnd() * (i + 1)); [out[i], out[j]] = [out[j], out[i]] }
  return out;
}

/* 여러 스타일의 상품을 번갈아 뽑아 한 칸을 만든다. used 에 든 상품은 건너뛴다(두 칸 중복 방지) */
async function recPick(styles, used){
  const lists = await Promise.all(styles.map(s => recFetch(s.n).then(
    items => recDayShuffle(items, s.id.length * 7919).map(it => ({ it, s })),
    () => [])));
  const out = [];
  for(let round = 0; out.length < REC_PER_BLOCK; round++){
    let any = false;
    for(const l of lists){
      if(round >= l.length) continue;
      any = true;
      const { it, s } = l[round];
      const card = styleProductCard(it, s.n);
      if(used.has(card.id)) continue;
      used.add(card.id);
      out.push({ ...card, style: s.id });
      if(out.length >= REC_PER_BLOCK) break;
    }
    if(!any) break;
  }
  return out;
}

function recBlockHTML(host, cards, emptyText){
  host.innerHTML = cards.length
    ? cards.map(itemCard).join('')
    : '<div class="itState">' + emptyText + '</div>';
}

async function recRender(){
  const mineHost = $('#recMine'), hotHost = $('#recHot');
  if(!mineHost || !hotHost) return;
  const seq = ++recSeq;
  const picked = STYLES.filter(s => ME.styles.has(s.id)).slice(0, 3);
  const rising = STYLES.filter(s => REC_RISE.includes(s.pk) && !ME.styles.has(s.id));

  const mineTitle = $('#recMineTitle');
  if(mineTitle) mineTitle.textContent = '내 취향 ' + picked.length + '개 기준';

  if(!picked.length) mineHost.innerHTML = '<div class="itState recEmpty">즐겨입는 스타일을 추가해 보세요.</div>';
  else mineHost.innerHTML = '<div class="itState">상품을 불러오는 중…</div>';
  hotHost.innerHTML = '<div class="itState">상품을 불러오는 중…</div>';

  const used = new Set();
  try{
    const mine = picked.length ? await recPick(picked, used) : [];
    const hot = await recPick(rising, used);
    if(seq !== recSeq) return;   /* 그 사이 취향이 또 바뀌었으면 늦게 온 결과는 버린다 */
    if(picked.length) recBlockHTML(mineHost, mine, '고른 스타일에 연결된 상품이 아직 없습니다.');
    recBlockHTML(hotHost, hot, '지금 뜨는 스타일에 연결된 상품이 아직 없습니다.');
  }catch(e){
    if(seq !== recSeq) return;
    const msg = '<div class="itState">상품을 불러오지 못했습니다.</div>';
    if(picked.length) mineHost.innerHTML = msg;
    hotHost.innerHTML = msg;
  }
  syncTodayRecHeight();
}

export function myRender(){
  /* 프로필 */
  const av = $('#avatarInitial'), nm = $('#profileName'), em = $('#profileEmail');
  if(av) av.textContent = ME.initial;
  if(nm) nm.textContent = ME.name;
  if(em) em.textContent = ME.mail;
  xpPaint();
  avaPaint();

  /* 저장 · 투표 수는 실제 데이터에서 센다 */
  const savedN = $('#statSavedN'), votedN = $('#statVotedN');
  if(savedN) savedN.textContent = LIKED.size;
  const voted = (typeof VOTES !== 'undefined')
    ? VOTES.filter(v => v.voted !== null && v.voted !== undefined) : [];
  if(votedN) votedN.textContent = voted.length || ME.votes;
  /* 뱃지 — 컬렉션 뱃지 개수. 등급은 뱃지가 아니라 아바타 링으로 표현한다.
     팀원 데이터가 붙으면 BADGES 만 채우면 숫자도 같이 맞는다. */
  const badgeN = $('#statBadgeN');
  if(badgeN) badgeN.textContent = BADGES.filter(b => b.earned).length;

  /* 오늘의 추천 — 실데이터(/api/products) 상품으로 두 칸을 나눠 채운다(2026-09-17).
     · 내 취향 N개 기준 : 즐겨입는 스타일(최대 3개)에 태그된 상품
     · 지금 뜨는 코어 기준 : 추세 단계가 확산·재상승·재점화·정점 통과인 스타일의 상품
     매칭도(%) 표기는 계산 근거가 없어 뺐다. */
  recRender();
  syncTodayRecHeight();

  if(HAS_A){
    aAnimate($$('#v-mypage .panel'), {opacity:[0,1],translateY:[14,0],
      duration:640,delay:aStagger(60),ease:'out(3)',
      onComplete:()=>$$('#v-mypage .panel').forEach(e=>{e.style.transform='';e.style.opacity=''})});
  }
}

/* '오늘의 추천' 패널 높이를 왼쪽 컬럼(프로필+필터) 높이에 정확히 맞춘다 */
function syncTodayRecHeight(){
  const left = $('.myGrid .myCol:first-child');
  const panel = $('#todayRecPanel');
  if(!left || !panel || !panel.offsetParent) return;
  panel.style.height = Math.round(left.getBoundingClientRect().height) + 'px';
}
if(!window.__recHeightBound){
  window.__recHeightBound = true;
  addEventListener('resize', () => syncTodayRecHeight());
}

/* 모달 */
function acctModal(id, on){
  const m = $('#' + id);
  if(m) m.classList.toggle('on', on);
}

/* 카드 오른쪽 위 하트 — 눌러서 찜 토글. 어느 카드에서 누르든(스타일 상세 · 오늘의 추천 ·
   찜 목록 모달) 같은 저장소(chat.js 의 LIKED)로 모여 마이페이지 '찜'과 곧장 이어진다. */
export function likeClick(btn){
  if(!requireAuth())return;
  const id=btn.dataset.likeId; if(!id)return;
  const before=LIKED.get(id);
  const on=toggleLike(id);
  btn.classList.toggle('on',on);
  /* 서버에도 찜/해제를 남긴다 — 금주의 리포트 '새로 찜한 것 · 총 추적 수' */
  const d=on?LIKED.get(id):before;
  if(d){
    const st=STYLES.find(s=>s.id===d.style);
    saveLiked({ itemId:id, liked:on, name:d.nm||'', brand:d.br||'', style:d.styleName||(st?st.n:'') })
      .then(r=>{ if(r&&Number.isFinite(+r.saved_count))ME.saved=+r.saved_count; });
  }
  const n=$('#statSavedN'); if(n)n.textContent=LIKED.size;
}

/* Google 버튼 공통 처리 — 로그인 화면·가입 화면이 같은 흐름을 쓴다.
   ★ googleLogin() 은 await 앞에서 바로 불러야 팝업이 막히지 않는다. */
function googleContinue(btn, errEl){
  if(errEl) errEl.style.display = 'none';
  btn.disabled = true;
  googleLogin().then(data => {
    if(data.authenticated){ authLogin(data.user); return; }
    if(data.needs_signup) enterGoogleSignup(data.google || {});
  }).catch(e => {
    if(e && e.cancelled) return;   /* 사용자가 창을 닫은 것은 오류로 보이지 않는다 */
    const msg = (e && e.message) || 'Google 로그인에 실패했습니다.';
    if(errEl && errEl.closest('.view.on')){ errEl.textContent = msg; errEl.style.display = 'block'; }
    else acctToast(msg);
  }).finally(() => { btn.disabled = false; });
}

/* 처음 온 Google 계정 — 가입 화면을 Google 모드로 연다.
   아이디 칸에는 Google 이메일을 읽기 전용으로 두고, 비밀번호 칸은 숨긴다. */
function enterGoogleSignup(google){
  goView('signup');
  resetSignupForm();
  signupGoogleMode = true;
  const gs = $('#googleSignupBtn'), suIdField = $('#suIdField'), suPwBlock = $('#suPwBlock'),
        div = $('#signupGoogleDivider'), note = $('#signupGoogleNote'), suId = $('#suId'),
        nick = $('#suNickname');
  if(gs) gs.hidden = true;
  if(div) div.hidden = true;
  if(suPwBlock) suPwBlock.hidden = true;
  if(note) note.hidden = false;
  if(suIdField) suIdField.hidden = false;
  if(suId){ suId.value = google.email || ''; suId.readOnly = true; }
  if(nick && !nick.value) nick.value = String(google.name || '').trim().slice(0, 12);
}

/* 회원가입 폼 초기화 — 완료하지 않고 다른 화면으로 나가면 구글 모드를 포함해
   다음에 다시 들어왔을 때 처음 상태 그대로 보이게 한다. */
export function resetSignupForm(){
  signupGoogleMode = false;
  const gs = $('#googleSignupBtn'), suIdField = $('#suIdField'), suPwBlock = $('#suPwBlock'),
        div = $('#signupGoogleDivider'), note = $('#signupGoogleNote'), suId = $('#suId'),
        err = $('#signupErr'), form = $('#signupForm'),
        idMsg = $('#suIdMsg'), pwMsg = $('#suPwMsg'), bodyMsg = $('#suBodyMsg');
  if(gs) gs.hidden = false;
  if(suIdField) suIdField.hidden = false;
  if(suPwBlock) suPwBlock.hidden = false;
  if(div) div.hidden = false;
  if(note) note.hidden = true;
  if(suId) suId.readOnly = false;
  if(err) err.style.display = 'none';
  if(form) form.reset();
  if(idMsg){ idMsg.textContent = ''; idMsg.className = 'fieldMsg'; }
  if(pwMsg){ pwMsg.textContent = ''; pwMsg.className = 'fieldMsg'; }
  if(bodyMsg){ bodyMsg.textContent = ''; bodyMsg.className = 'fieldMsg'; }
  jobFieldReset('su', null);   /* form.reset() 은 파일 버튼 글자까지는 못 되돌린다 */
}

export function acctBoot(){
  /* ── 로그인 ── */
  const lf = $('#loginForm');
  if(lf) lf.addEventListener('submit', async e => {
    e.preventDefault();
    const id = $('#loginId').value.trim(), pw = $('#loginPw').value.trim();
    const err = $('#loginErr');
    if(!id || !pw){ err.style.display = 'block'; return; }
    err.style.display = 'none';
    const submit=lf.querySelector('[type="submit"]'); if(submit)submit.disabled=true;
    try{
      const data=await loginAccount(id,pw);
      authLogin(data.user);
      lf.reset();
    }catch(ex){ err.textContent=ex.message||'로그인하지 못했습니다.'; err.style.display='block' }
    finally{ if(submit)submit.disabled=false }
  });
  /* Google 로그인 — 화면이 뜰 때 GIS 스크립트와 클라이언트를 미리 준비해 둔다
     (클릭 뒤에 준비하면 브라우저가 팝업을 막는다). */
  prepareGoogle().catch(()=>{ /* 서버 연결 실패는 아래 session() 경고가 이미 알린다 */ });
  const gl = $('#googleLoginBtn');
  if(gl) gl.addEventListener('click', ()=>googleContinue(gl, $('#loginErr')));

  /* ── 직업 선택 · 서류 첨부 (가입 · 회원정보 수정 공통) ── */
  jobFieldBind('su');
  jobFieldBind('edit');
  jobReviewBind(ok => acctToast(ok ? '승인했어요. 배지가 바로 반영됩니다.' : '반려했어요.'));

  /* ── 회원가입 ── */
  const sf = $('#signupForm');
  if(sf) sf.addEventListener('submit', async e => {
    e.preventDefault();
    const err = $('#signupErr');
    const nick = $('#suNickname').value.trim();
    const pw = $('#suPw').value, pw2 = $('#suPw2').value;
    const id = $('#suId').value.trim();
    let msg = '';
    if(signupGoogleMode){
      /* 구글로 가입 — 아이디 칸엔 구글 이메일이 이미 채워져 있고 수정할 수 없다.
         비밀번호도 구글이 대신하니 닉네임·체형만 본다 */
      if(nick.length < 2 || nick.length > 12) msg = '닉네임은 2~12자로 입력해 주세요.';
      else {
        const b = bodyCheck($('#suHeight').value, $('#suWeight').value);
        if(b) msg = b;
      }
    }else{
      if(!/^[A-Za-z0-9]{4,16}$/.test(id)) msg = '아이디는 영문·숫자 4~16자로 입력해 주세요.';
      else if(nick.length < 2 || nick.length > 12) msg = '닉네임은 2~12자로 입력해 주세요.';
      else if(pw.length < 8) msg = '비밀번호는 8자 이상이어야 합니다.';
      else if(pw !== pw2) msg = '비밀번호가 서로 다릅니다.';
      else {
        const b = bodyCheck($('#suHeight').value, $('#suWeight').value);
        if(b) msg = b;
      }
    }
    if(!msg) msg = jobFieldCheck('su', null);
    if(msg){ err.textContent = msg; err.style.display = 'block'; return; }
    err.style.display = 'none';
    const submit=sf.querySelector('[type="submit"]'); if(submit)submit.disabled=true;
    try{
      const profileFields={
        nickname:nick,
        birth_date:$('#suBirth').value||'',
        height:$('#suHeight').value||null,
        weight:$('#suWeight').value||null,
      };
      /* Google 가입은 서버 세션에 보관된 Google 신원으로 계정을 만든다 —
         아이디·비밀번호는 보내지 않는다. */
      const data=signupGoogleMode
        ? await googleSignupAccount(profileFields)
        : await signupAccount({ username:id, password:pw, ...profileFields });
      applyAccount(data.user);
      ME.role='user'; ME.job=''; ME.major='';
      signupComplete();
      sf.reset();
    }catch(ex){ err.textContent=ex.message||'회원가입하지 못했습니다.'; err.style.display='block' }
    finally{ if(submit)submit.disabled=false }
  });
  /* 구글로 계속하기 — 이미 연결된 Google 계정이면 바로 로그인하고,
     처음이면 같은 회원가입 폼 위에서 아이디/비밀번호 입력만 막고 닉네임·생년월일·체형을 마저 받는다. */
  const gs = $('#googleSignupBtn');
  if(gs) gs.addEventListener('click', () => googleContinue(gs, $('#signupErr')));
  /* 아이디·비밀번호 안내는 치는 동안 바로 알려 준다 */
  const suId = $('#suId'), suIdMsg = $('#suIdMsg');
  if(suId) suId.addEventListener('input', () => {
    const v = suId.value.trim();
    if(!v){ suIdMsg.textContent = ''; suIdMsg.className = 'fieldMsg'; return; }
    const ok = /^[A-Za-z0-9]{4,16}$/.test(v);
    suIdMsg.textContent = ok ? '사용할 수 있는 아이디입니다.' : '영문·숫자 4~16자';
    suIdMsg.className = 'fieldMsg ' + (ok ? 'ok' : 'err');
  });
  const suPw = $('#suPw'), suPw2 = $('#suPw2'), suPwMsg = $('#suPwMsg');
  const pwCheck = () => {
    if(!suPw.value && !suPw2.value){ suPwMsg.textContent = ''; suPwMsg.className = 'fieldMsg'; return; }
    const ok = suPw.value.length >= 8 && suPw.value === suPw2.value;
    suPwMsg.textContent = suPw.value.length < 8 ? '8자 이상 입력해 주세요.'
      : (ok ? '비밀번호가 일치합니다.' : '비밀번호가 서로 다릅니다.');
    suPwMsg.className = 'fieldMsg ' + (ok ? 'ok' : 'err');
  };
  if(suPw) suPw.addEventListener('input', pwCheck);
  if(suPw2) suPw2.addEventListener('input', pwCheck);

  /* 체형 — 비워 둬도 통과시킨다. 넣었다면 사람 범위인지만 본다. */
function bodyCheck(h,w){
  if(h && (h<120 || h>220)) return '키는 120~220cm 사이로 입력해 주세요.';
  if(w && (w<30  || w>200)) return '몸무게는 30~200kg 사이로 입력해 주세요.';
  return '';
}
/* 가입 화면에서 치는 동안 세그먼트를 미리 알려 준다 */
const suH=$('#suHeight'), suW=$('#suWeight'), suBodyMsg=$('#suBodyMsg');
function bodyHint(){
  if(!suBodyMsg)return;
  const h=+suH.value, w=+suW.value;
  const bad=bodyCheck(suH.value,suW.value);
  if(bad){ suBodyMsg.textContent=bad; suBodyMsg.className='fieldMsg err'; return }
  if(!h||!w){ suBodyMsg.textContent=''; suBodyMsg.className='fieldMsg'; return }
  const bmi=w/((h/100)**2);
  const seg=bmi<18.5?'슬림':bmi<23?'표준':bmi<25?'스탠다드 플러스':'볼륨';
  suBodyMsg.textContent=''+seg+' 세그먼트로 분류돼요. 비슷한 체형의 살!말? 를 먼저 보여 드립니다.';
  suBodyMsg.className='fieldMsg ok';
}
if(suH) suH.addEventListener('input', bodyHint);
if(suW) suW.addEventListener('input', bodyHint);

/* ── 마이페이지 ── */
  acctChips($('#styleWrap'), ME.styles);
  const ssb = $('#styleSaveBtn');
  if(ssb) ssb.addEventListener('click', async () => {
    ssb.disabled=true;
    try{
      const data=await saveAccount({styles:styleNames()});
      applyAccount(data.user); myRender();
      acctToast('즐겨입는 스타일이 DB에 저장됐어요.');
    }catch(e){ acctToast(e.message||'스타일을 저장하지 못했습니다.') }
    finally{ ssb.disabled=false }
  });
  /* 로그아웃은 헤더 계정 메뉴 한 곳으로 모았다 (#menuLogout) */
  /* 아이콘 색 바꾸기 */
  const avb = $('#avatarEditBtn');
  if(avb) avb.addEventListener('click', () => {
    const w = $('#avaPick');
    if(w) w.innerHTML = AVA.map((g, i) =>
      '<button type="button" class="avaSw' + (i === ME.ava ? ' on' : '') +
      '" data-ava="' + i + '" style="background:linear-gradient(135deg,' + g[0] + ',' + g[1] + ')"' +
      ' aria-label="아이콘 ' + (i + 1) + '"></button>').join('');
    acctModal('avatarModal', true);
  });
  const aw = $('#avaPick');
  if(aw) aw.addEventListener('click', async e => {
    const b = e.target.closest('[data-ava]');
    if(!b) return;
    try{
      const data=await saveAccount({avatar:+b.dataset.ava});
      applyAccount(data.user);
      $$('.avaSw', aw).forEach(x => x.classList.toggle('on', x === b));
      avaPaint(); authPaint();
      setTimeout(() => acctModal('avatarModal', false), 240);
    }catch(ex){ acctToast(ex.message||'아이콘을 저장하지 못했습니다.') }
  });
  const ep = $('#editProfileBtn');
  if(ep) ep.addEventListener('click', () => {
    $('#editNickname').value = ME.name;
    $('#editBirth').value = ME.birth || '';
    $('#editHeight').value = ME.height || '';
    $('#editWeight').value = ME.weight || '';
    $('#editModalErr').style.display = 'none';
    jobFieldReset('edit', ME);
    /* 운영자 계정은 직업을 바꾸지 않는다 — 칸은 보이되 잠가 둔다 */
    const ej = $('#editJob'), ejb = $('#editJobFileBtn'), ejm = $('#editJobMsg');
    if(ej) ej.disabled = (ME.role === 'admin');
    if(ME.role === 'admin'){
      if(ejb) ejb.disabled = true;
      if(ejm){ ejm.textContent = '운영자 계정은 직업 대신 ADMIN 으로 표시됩니다.'; ejm.className = 'fieldMsg'; }
    }
    acctModal('editModal', true);
  });
  const ef = $('#editProfileForm');
  if(ef) ef.addEventListener('submit', async e => {
    e.preventDefault();
    const nick = $('#editNickname').value.trim();
    const pw = $('#editPw').value, pw2 = $('#editPw2').value;
    const err = $('#editModalErr');
    let msg = '';
    if(nick.length < 2 || nick.length > 12) msg = '닉네임은 2~12자로 입력해 주세요.';
    else if(pw && pw.length < 8) msg = '새 비밀번호는 8자 이상이어야 합니다.';
    else if(pw !== pw2) msg = '새 비밀번호가 서로 다릅니다.';
    else msg = bodyCheck($('#editHeight').value, $('#editWeight').value) || '';
    if(!msg && ME.role !== 'admin') msg = jobFieldCheck('edit', ME);
    if(msg){ err.textContent = msg; err.style.display = 'block'; return; }
    const submit=ef.querySelector('[type="submit"]'); if(submit)submit.disabled=true;
    try{
      const data=await saveAccount({
        nickname:nick, birth_date:$('#editBirth').value||'',
        height:$('#editHeight').value||null, weight:$('#editWeight').value||null,
        password:pw||'',
      });
      applyAccount(data.user);
      acctModal('editModal', false);
      ef.reset(); myRender(); authPaint();
      acctToast('회원정보가 DB에 저장됐어요.');
      if(typeof trRender === 'function' && document.body.dataset.view === 'trend') trRender('myfeed');
    }catch(ex){ err.textContent=ex.message||'회원정보를 저장하지 못했습니다.'; err.style.display='block' }
    finally{ if(submit)submit.disabled=false }
  });
  [$('#editModalClose'), $('#editModalCancel')].forEach(b =>
    b && b.addEventListener('click', () => acctModal('editModal', false)));

  /* 저장 · 투표 목록 모달 — 실제 찜 목록과 투표 이력을 그대로 보여 준다 */
  const sb = $('#statSavedBtn');
  if(sb) sb.addEventListener('click', () => {
    const g = $('#savedGrid');
    const items = [...LIKED.entries()];
    if(g) g.innerHTML = items.map(([id, d]) => itemCard({ ...d, id })).join('') ||
      '<p class="fieldMsg">찜한 아이템이 없습니다.</p>';
    acctModal('savedModal', true);
  });
  const vb = $('#statVotedBtn');
  if(vb) vb.addEventListener('click', () => {
    const g = $('#votedGrid');
    const voted = (typeof VOTES !== 'undefined')
      ? VOTES.filter(v => v.voted !== null && v.voted !== undefined) : [];
    if(g) g.innerHTML = voted.map(v => itemCard({
      img: v.imgURL, tag: v.voted === 0 ? '살! 선택' : '말? 선택',
      br: v.b, nm: v.t, pr: fmtWon(v.p)
    })).join('') || '<p class="fieldMsg">아직 투표한 카드가 없습니다. 살!말? 에서 골라 보세요.</p>';
    acctModal('votedModal', true);
  });
  /* 뱃지 — 컬렉션 뱃지 전용 자리다.
     등급은 뱃지가 아니라 아바타 링으로 표현하기로 했으니 여기 섞지 않는다.
     팀원 컬렉션 뱃지가 도착하면 BADGES 배열만 채우면 그대로 그려진다. */
  const bb = $('#statBadgeBtn');
  if(bb) bb.addEventListener('click', () => { bgRender(); acctModal('badgeModal', true) });
  /* 타일을 고르면 위 상세 패널이 바뀐다 */
  const bg = $('#badgeGrid');
  if(bg) bg.addEventListener('click', e => {
    const t = e.target.closest('.bgTile'); if(!t) return;
    $$('.bgTile.active', bg).forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    const b = BADGES.find(x => x.id === t.dataset.badge);
    if(b) bgDetail(b);
  });

  /* 회원 탈퇴 — 목업이라 진짜로 지우지는 않는다. 확인만 받고 로그아웃한다 */
  const lv = $('#leaveBtn');
  if(lv) lv.addEventListener('click', () => acctModal('leaveModal', true));
  const lvGo = $('#leaveConfirm');
  if(lvGo) lvGo.addEventListener('click', () => {
    acctModal('leaveModal', false);
    authLogout();
  });
  $$('[data-close-modal]').forEach(b =>
    b.addEventListener('click', () => $$('.acctModal').forEach(m => m.classList.remove('on'))));

  /* 트렌드 분석 로그인 안내 팝업 — 로그인은 로그인 화면으로, 취소는 홈으로 */
  const trGateLogin = $('#trendGateLogin');
  if(trGateLogin) trGateLogin.addEventListener('click', () => {
    acctModal('trendGateModal', false);
    goView('login');
  });
  const trGateCancel = $('#trendGateCancel');
  if(trGateCancel) trGateCancel.addEventListener('click', () => {
    acctModal('trendGateModal', false);
    goView('home');
  });
  $$('.acctModal').forEach(m => m.addEventListener('click', e => {
    if(e.target === m) m.classList.remove('on');
  }));
  addEventListener('keydown', e => {
    if(e.key === 'Escape') $$('.acctModal').forEach(m => m.classList.remove('on'));
  });

  /* 헤더 계정 메뉴 */
  const ab = $('#mAuthBtn');
  if(ab) ab.addEventListener('click', e => {
    if(!AUTH.in) return;              /* 로그인 전에는 data-v 위임이 로그인 화면으로 보낸다 */
    e.stopPropagation();
    acctMenu();
  });
  const mm = $('#menuMypage');
  if(mm) mm.addEventListener('click', () => { acctMenu(false); goView('mypage') });
  const mj = $('#menuJobReview');
  if(mj) mj.addEventListener('click', () => { acctMenu(false); jobReviewRender(); acctModal('jobReviewModal', true) });
  const ml = $('#menuLogout');
  if(ml) ml.addEventListener('click', () => { acctMenu(false); authLogout() });
  document.addEventListener('click', e => {
    if(!e.target.closest('.mAuthWrap')) acctMenu(false);
  });

  authPaint();
  rkPaintAll();      /* 화면에 이미 떠 있는 아바타들도 한 번 맞춰 둔다 */
  /* 새로고침해도 Django 세션 쿠키로 로그인 상태와 프로필을 복원한다. */
  session().then(data=>{
    if(!data.authenticated||!data.user)return;
    applyAccount(data.user); AUTH.in=true; authPaint();
    acctChips($('#styleWrap'),ME.styles);
    if(document.body.dataset.view==='mypage')myRender();
  }).catch(e=>console.warn('[account]',e.message||e));
}
