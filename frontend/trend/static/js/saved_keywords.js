import { $, $$, HAS_A, aAnimate, aSpring, aTimeline } from '../../../core/static/js/dom.js';
import { prime, primeUrl, sentimentUrl } from './live_data.js';
import { FIDX, fsExact, fsMatch, fsNorm } from '../../../style/static/js/search.js';
import { KW, trToast } from './render_helpers.js';
import { markTried, trRender } from './dispatch.js';
import { logSearch } from '../../../account/static/js/account_api.js';

/* 예시 질문 — 스타일 룩 · 아이템 위주. 전부 사전에 실제로 있는 말이라 그대로 검색된다. */
const KW_Q={
  temp:[['발레코어','지금 얼마나 뜨거워?'],['스트릿','아직 오르는 중이야?'],
        ['스투시 후디','언제 정점 찍었어?'],['고프코어','어느 플랫폼이 제일 뜨거워?'],
        ['삼바 OG','작년보다 많이 언급돼?']],
  assoc:[['발레코어','뭐랑 같이 언급돼?'],['아메카지','어떤 아이템이 많이 나와?'],
         ['카고 팬츠','같이 입는 게 뭐야?'],['블록코어','새로 붙은 연관어 있어?'],
         ['디트로이트 자켓','어떤 룩으로 소비돼?']],
  sentiment:[['발레코어','사려는 사람 많아?'],['스투시 후디','반응 어때?'],
             ['트랙 자켓','부정 반응은 뭐야?'],['그런지','가격 부담 얘기 많아?'],
             ['발레 플랫','재입고 문의 늘었어?']]
};
/* 할인률 챗바(fsQStep)와 같은 타임라인 — 문구만 파트별로 다르다 */
var kwQI=0, kwQBooked=false;
function kwQStep(){
  const line=$('#kwQ'); if(!line)return;
  const arr=KW_Q[KW.part]||KW_Q.temp;
  const q=arr[kwQI%arr.length]; kwQI++;
  const paint=()=>{ line.innerHTML='<i>“<b>'+q[0]+'</b>&nbsp;'+q[1]+'”</i>' };
  if(!HAS_A){ paint(); return }
  if(!line.firstElementChild){ paint();
    aAnimate(line,{opacity:[0,1],translateY:[8,0],duration:520,ease:'out(3)'}); return }
  const t=aTimeline();
  t.add(line,{opacity:[1,0],translateY:[0,-8],duration:260,ease:'in(2)',onComplete:paint},0)
   .add(line,{opacity:[0,1],translateY:[8,0],duration:520,
      ease:aSpring({stiffness:94,damping:16})},260);
}
function kwQTick(){
  try{ const i=$('#kwInput');
    if(i&&!i.value&&$('#trTabs').classList.contains('kwmode'))kwQStep(); }catch(e){}
  setTimeout(kwQTick,3200);
}
export function kwHideSug(){ const b=$('#kwSug'); if(b){b.hidden=true;b.innerHTML=''} KW.sug=[]; KW.cur=-1 }
function kwPaintSug(){
  const box=$('#kwSug'), inp=$('#kwInput'); if(!box||!inp)return;
  const q=inp.value.trim();
  if(!q){ kwHideSug(); return }
  /* ★ 2026-09-23 — 첫 줄을 미리 골라 두지 않는다. 미리 골라 두면 Enter 가
     친 말이 아니라 그 줄을 집어, '청바지' 를 치고 Enter 하면 연관어 '데님' 이 검색됐다.
     연관어는 드롭다운으로 보여 주되, 잡으려면 ↑↓ 나 클릭으로 직접 골라야 한다. */
  KW.sug=fsMatch(q,8); KW.cur=-1;
  if(!KW.sug.length){
    /* 실패로 끝내지 않는다 — 가까운 말을 보여주고, 없으면 등록을 받는다 */
    const n=fsNorm(q);
    let near=FIDX.filter(o=>o.key[0]===n[0]||o.key.indexOf(n.slice(0,1))>=0).slice(0,3);
    const fallback=!near.length;
    if(fallback)near=['발레코어','고프코어','카고 팬츠'].map(x=>({label:x}));
    const done=KW.asked[q];
    box.innerHTML='<div class="kwReq"><p><b>'+q+'</b>… 아직 사전에 없는 말입니다.<br>'+
      '이 검색은 소재 · 아이템 · 스타일 · 브랜드만 다룹니다.</p>'+
      (near.length?'<div class="near"><em>'+(fallback?'많이 찾는 키워드':'혹시 이건가요?')+'</em>'+
        near.map(o=>'<button type="button" data-kw="'+o.label+'">'+o.label+'</button>').join('')+'</div>':'')+
      '<div class="ask"><span>패션 용어가 맞다면 등록을 요청해 주세요. 검토 후 사전에 추가됩니다.</span>'+
      '<button type="button" id="kwAsk"'+(done?' disabled':'')+'>'+
      (done?'요청 완료':'등록 요청')+'</button></div></div>';
    box.hidden=false; return;
  }
  const esc=s=>s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
  const n=fsNorm(q);
  box.innerHTML=KW.sug.map((o,k)=>{
    let lb=esc(o.label); const i=fsNorm(o.label).indexOf(n);
    if(i>=0){ let c=0,s=-1,e=-1;
      for(let p=0;p<o.label.length;p++){ if(!/\s/.test(o.label[p])){ if(c===i)s=p; if(c===i+n.length-1)e=p; c++ } }
      if(s>=0&&e>=s)lb=esc(o.label.slice(0,s))+'<em>'+esc(o.label.slice(s,e+1))+'</em>'+esc(o.label.slice(e+1));
    }
    /* ★ 예전엔 o.path(스타일 › 종류 › 브랜드)를 뒤에 붙였다.
       세부 검색이 단계식에서 축별 필터로 바뀌면서 FIDX 에서 path 를 뺐다 —
       계층이 없는 사전 항목에는 어차피 없던 값이고, 여기서 읽으면 터진다.
       축 이름(o.f)만으로도 무엇인지는 충분히 읽힌다. */
    return '<button class="sg" data-k="'+k+'" type="button">'+
      '<span class="fc">'+esc(o.f)+'</span><span class="lb">'+lb+'</span></button>';
  }).join('');
  box.hidden=false;
}
function kwMoveSug(d){
  if(!KW.sug.length)return;
  KW.cur=(KW.cur+d+KW.sug.length)%KW.sug.length;
  $$('#kwSug .sg').forEach((b,i)=>b.classList.toggle('on',i===KW.cur));
}
/* 검색어 확정 → 그 파트를 다시 그린다 */
/* 알림(용어 사전 등재)에서 그 용어를 바로 검색할 때 쓴다 — notify.js openTarget (2026-09-19) */
window.feeditKwGo=v=>kwGo(v);
function kwGo(v){
  const inp=$('#kwInput'); if(!inp)return;
  const selected=v&&typeof v==='object'?v:null;
  if(selected)inp.value=selected.label;
  else if(v)inp.value=v;
  const typed=inp.value.trim();
  if(!typed){ kwPaintSug(); return }
  /* ★ 2026-09-23 — 친 말 그대로 간다. 연관어로 바꿔치기하지 않는다.
     예전에는 fsMatch 의 첫 줄을 집어서, '청바지' 를 치면 소재 '데님' 이 검색됐다.
     사전에 그 말이 없을 때만, 후보가 딱 하나면 그것으로 대신한다(별칭·오타 한 글자). */
  const near=selected?null:fsMatch(typed,2);
  const match=selected||fsExact(typed)||(near&&near.length===1?near[0]:null);
  if(!match){ kwPaintSug(); return }   /* 사전에 없으면 검색되지 않는다 */
  /* 실제로 조회하는 말은 사전의 대표 이름이다 — 화면·기록·API 가 서로 어긋나지 않게 한다 */
  const q=match.label||typed;
  inp.value=q;
  /* 금주의 리포트용 검색 기록 — 스타일 축이면 취향 지분 계산에도 쓴다 */
  logSearch(q, match.f||'', match.f==='스타일'?q:'');

  /* ★ 지표를 받아 오는 동안 돋보기를 돌린다.
     서버에 다녀오는 시간이 있는데 화면이 그대로면 눌린 줄을 모르고 또 누른다.
     받아 온 뒤에는 trRender 가 다시 그리므로 여기서 끄지 않아도 되지만,
     실패했을 때를 대비해 반드시 되돌린다(finally). */
  kwBusy(true);
  KW.q=q; KW.f=match.f||''; kwHideSug();
  /* 연관어 파트는 /api/assoc 도 새로 받는다 (사람이 직접 눌렀으니 캐시를 무시한다). */
  const assocUrl=KW.part==='assoc'?'/api/assoc?term='+encodeURIComponent(q):null;
  const sentUrl=KW.part==='sentiment'?sentimentUrl(q,KW.f):null;
  const jobs=sentUrl?[primeUrl(sentUrl,{force:true})]:[prime(q,undefined,{force:true})];
  if(assocUrl)jobs.push(primeUrl(assocUrl,{force:true}));
  Promise.all(jobs.map(j=>Promise.resolve(j).catch(()=>{}))).then(()=>{
    /* 내가 방금 물어봤다 — 이어서 도는 trRender 는 또 묻지 마라. */
    markTried(q); if(assocUrl)markTried(assocUrl); if(sentUrl)markTried(sentUrl);
    kwBusy(false);
    trRender(KW.part);
  });
}

/* 챗바를 '조회 중' 모양으로 바꾼다. CSS 가 회전을 맡는다. */
function kwBusy(on){
  const bar=$('#kwBar'), btn=$('#kwGoBtn');
  if(bar)bar.classList.toggle('busy',!!on);
  if(btn)btn.disabled=!!on;
}
export function kwWire(part){
  const inp=$('#kwInput'); if(!inp)return;
  KW.part=part;
  const bar=$('#kwBar'), clear=$('#kwClear');
  inp.addEventListener('input',()=>{
    bar.classList.toggle('typing',!!inp.value);   /* 입력 중엔 예시 질문이 비켜난다 */
    clear.hidden=!inp.value;
    kwPaintSug();
  });
  inp.addEventListener('keydown',e=>{
    if(e.key==='ArrowDown'){ e.preventDefault(); kwMoveSug(1) }
    else if(e.key==='ArrowUp'){ e.preventDefault(); kwMoveSug(-1) }
    else if(e.key==='Escape'){ kwHideSug() }
    else if(e.key==='Enter'){ e.preventDefault();
      if(KW.cur>=0&&KW.sug[KW.cur])kwGo(KW.sug[KW.cur]); else kwGo();
    }
  });
  inp.addEventListener('focus',()=>{ if(inp.value)kwPaintSug() });
  $('#kwSug').addEventListener('click',e=>{
    const sg=e.target.closest('.sg');
    if(sg){ kwGo(KW.sug[+sg.dataset.k]); return }
    const near=e.target.closest('[data-kw]');
    if(near){ kwGo(near.dataset.kw); return }
    const ask=e.target.closest('#kwAsk');
    if(ask&&!ask.disabled){
      KW.asked[inp.value.trim()]=1;
      ask.disabled=true; ask.textContent='요청 완료';
      trToast('“'+inp.value.trim()+'” 등록을 요청했습니다. 검토 후 사전에 추가됩니다.');
    }
  });
  const go=$('#kwGoBtn');
  if(go)go.addEventListener('click',()=>{ if(!go.disabled)kwGo() });
  clear.addEventListener('click',()=>{
    inp.value=''; bar.classList.remove('typing');
    clear.hidden=true; kwHideSug(); inp.focus();
  });
  /* ★ 탭을 바꾸면 trTabsRender 가 챗바를 통째로 새로 그린다.
     그러면 #kwQ 도 새 요소라 비어 있는데, 예전엔 kwQBooked 가 이미 true 라
     아무것도 안 그리고 **다음 3.2초 틱까지 빈칸**이었다. 그 사이 사용자는
     "예시 질문이 없어졌다"고 본다.
     그래서 **그릴 때마다 한 번은 바로 찍고**, 타이머만 한 번 건다. */
  if(!inp.value) kwQStep();
  if(!kwQBooked){ kwQBooked=true; setTimeout(kwQTick,3200) }
}
