import { $ } from '../../../core/static/js/dom.js';

/* ── 요금제 ─────────────────────────────────────────── */
const PRICES=[
  {n:'프리',p:'0',u:'원 / 월',d:'개인 사용자를 위한 기본 플랜'},
  {n:'프로',p:'19,900',u:'원 / 월',d:'실무에 매일 쓰는 분들께',best:1},
  {n:'비즈니스',p:'문의',u:'',d:'팀 단위 협업과 데이터 연동'}
];
/* 기능 비교표 — 값은 [프리, 프로, 비즈니스] 순. 줄바꿈은 '|' */
const COMPARE=[
  ['살!말? 참여',['무제한','무제한','무제한']],
  ['AI 챗',['하루 20회','무제한','무제한']],
  ['트렌드 분석',['FEED 전체|+|EDIT 언급량·온도','FEED 전체|+|EDIT 전체','FEED 전체|+|EDIT 전체']],
  ['리포트 내보내기',['미지원','지원','지원']],
  ['데이터 API 연동',['미지원','미지원','지원']]
];
const FAQS=[
  ['데이터는 어디서 수집하나요?','무신사·지그재그·KREAM 등 커머스와 유튜브(롱폼/숏폼), 패션 카페·블로그, 네이버 데이터랩을 24시간 주기로 수집합니다.'],
  ['상승·하락은 어떤 기준인가요?','직전 4주 평균 대비 최근 7일 언급량 변화율을 기본으로, 긍부정 반응률과 저장·클릭을 가중합니다. “언급은 늘었는데 반응은 나쁜” 케이스를 걸러내기 위해서입니다.'],
  ['살!말?은 누구에게 노출되나요?','기본값은 취향 태그가 2개 이상 겹치는 유저입니다.'],
  ['무료 플랜에도 제한이 있나요?','AI 챗은 하루 20회, 랭킹은 TOP 10까지 보입니다. 살!말? 참여와 스타일 탐색은 제한 없이 사용할 수 있습니다.']
];
var prToastT;
function prToast(msg){
  const t=$('#toast'); if(!t)return;
  t.textContent=msg; t.classList.add('on');
  clearTimeout(prToastT);
  prToastT=setTimeout(()=>t.classList.remove('on'),2600);
}
export function prBuild(){
  const cards=PRICES.map(p=>
    '<div class="prCard'+(p.best?' best':'')+'" role="button" tabindex="0"><div class="pl"><div class="bd1"><b>'+p.n+'</b>'+
    (p.best?'<u>추천</u>':'')+'</div><div class="ds">'+p.d+'</div></div>'+
    '<div class="pz"><b>'+p.p+'</b><span>'+p.u+'</span></div></div>').join('');
  const table='<table class="prTbl"><thead><tr><th class="corner"><i>요금제</i><em>기능</em></th>'+
    PRICES.map(p=>'<th>'+p.n+'</th>').join('')+'</tr></thead><tbody>'+
    COMPARE.map(r=>'<tr><th>'+r[0]+'</th>'+
      r[1].map(v=>'<td>'+v.split('|').join('<br>')+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
  $('#prGrid').innerHTML='<div class="prCards">'+cards+'</div><div class="prTblWrap">'+table+'</div>';
  document.querySelectorAll('#prGrid .prCard').forEach(c=>{
    const go=()=>prToast('현재 베타 기간으로 무료로 사용 가능합니다.');
    c.addEventListener('click',go);
    c.addEventListener('keydown',e=>{ if(e.key==='Enter'||e.key===' '){ e.preventDefault(); go(); } });
  });
  $('#faq').innerHTML=FAQS.map(f=>'<details><summary>'+f[0]+'</summary><p>'+f[1]+'</p></details>').join('');
}
