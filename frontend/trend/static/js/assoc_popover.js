import { $, $$ } from '../../../core/static/js/dom.js';

export function assocOpenPop(triggerEl,cat,item){
  $$('#trBody .axList .axRow').forEach(t=>t.classList.remove('on'));
  triggerEl.classList.add('on');
  const pop=$('#assocPop');
  $('#apWord').textContent=item.n; $('#apCat').textContent=cat;
  /* 스파크라인 — 연관어별 추이가 없으면(실데이터) 선을 비운다. 지어낸 곡선을 그리지 않는다. */
  const pts=Array.isArray(item.spark)?item.spark:[];
  const line=$('#apSparkLine');
  if(pts.length>1){
    const max=Math.max.apply(null,pts), min=Math.min.apply(null,pts), span=(max-min)||1;
    const step=180/(pts.length-1);
    line.setAttribute('points',pts.map((v,i)=>(10+i*step).toFixed(1)+','+(40-((v-min)/span)*32).toFixed(1)).join(' '));
  } else line.setAttribute('points','');
  const esc=v=>String(v==null?'':v).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const src=Array.isArray(item.src)?item.src:[];
  $('#apSrc').innerHTML=(src.length?src:[{tag:'근거',text:'이 연관어의 근거 문장이 아직 적재되지 않았습니다.'}]).map(s=>
    '<div class="apSrcItem"><span class="apSrcTag">'+esc(s.tag)+'</span><span class="apSrcText">'+esc(s.text)+'</span></div>'
  ).join('');
  pop.classList.add('on');
  const r=triggerEl.getBoundingClientRect();
  const pw=pop.offsetWidth||272, ph=pop.offsetHeight||180;
  const vw=window.innerWidth, vh=window.innerHeight, pad=10;
  let left=r.left, top=r.bottom+8;
  if(left+pw>vw-pad) left=vw-pad-pw;
  if(left<pad) left=pad;
  if(top+ph>vh-pad) top=r.top-ph-8;
  pop.style.left=left+'px'; pop.style.top=top+'px';
}
export function assocClosePop(){
  $('#assocPop').classList.remove('on');
  $$('#trBody .axList .axRow, #sigWrap tr').forEach(t=>t.classList.remove('on'));
}
$('#apClose').addEventListener('click',assocClosePop);
document.addEventListener('click',e=>{
  const pop=$('#assocPop');
  if(!pop.classList.contains('on'))return;
  if(e.target.closest('#assocPop')||e.target.closest('.axList .axRow')||e.target.closest('#sigWrap tr'))return;
  assocClosePop();
});
document.addEventListener('keydown',e=>{ if(e.key==='Escape') assocClosePop(); });
window.addEventListener('resize',()=>{ if($('#assocPop').classList.contains('on')) assocClosePop(); });
