import { $, A, HAS_A, aAnimate, aStagger } from '../../../core/static/js/dom.js';
import { stateOf, seriesOf, seriesFromRows, lastDateOf, unavailableHTML } from './live_data.js';

/* ══════════════════════════════════════════════════════
   차트 엔진 — 일 · 주 · 월 전환과 마우스오버 판독
   같은 아이템은 언제 봐도 같은 수치가 나와야 하므로 난수를 이름으로 고정한다.
   ══════════════════════════════════════════════════════ */
export function gSeed(s){ let h=2166136261; s=String(s);
  for(let i=0;i<s.length;i++){ h^=s.charCodeAt(i); h=Math.imul(h,16777619) }
  return (h>>>0)/4294967295;
}
function gRand(seed){ let x=seed*10000%1||0.137;
  return ()=>{ x=(x*9301+0.49297)%1; return x } }
const GRAN=[['d','일별',30],['w','주별',26],['m','월별',18]];
const G_UNIT={d:'일',w:'주',I:'',m:'개월'};
/* 오늘로부터 거슬러 올라가는 눈금 라벨 */
function gLabels(g,n,endIso){
  /* 실데이터는 마지막 적재일을 끝 눈금으로 쓴다. 장식용(난수)은 예전 기준일 그대로. */
  const now=endIso?new Date(endIso+'T00:00:00'):new Date(2026,7,19), out=[];
  for(let i=n-1;i>=0;i--){
    const t=new Date(now);
    if(g==='d')t.setDate(t.getDate()-i);
    else if(g==='w')t.setDate(t.getDate()-i*7);
    else t.setMonth(t.getMonth()-i);
    out.push(g==='m'?(t.getFullYear()+'.'+String(t.getMonth()+1).padStart(2,'0'))
      :(String(t.getMonth()+1).padStart(2,'0')+'.'+String(t.getDate()).padStart(2,'0')
        +(g==='w'?' 주':'')));
  }
  return out;
}
/* 추세 + 계절성 + 잡음. shape 로 곡선 성격을 바꾼다. */
function gSeries(key,g,shape,lo,hi){
  const n=GRAN.find(x=>x[0]===g)[2], r=gRand(gSeed(key+g+shape)), out=[];
  for(let i=0;i<n;i++){
    const p=i/(n-1); let base;
    if(shape==='rise')      base=Math.pow(p,1.7);
    else if(shape==='fall') base=1-Math.pow(p,1.5);
    else if(shape==='peak') base=Math.sin(p*Math.PI);
    else if(shape==='late') base=p<.62?p*.35:.22+Math.pow((p-.62)/.38,1.6)*.78;
    else                    base=.5+Math.sin(p*Math.PI*2)*.28;
    const noise=(r()-.5)*(g==='d'?.14:g==='w'?.09:.05);
    out.push(Math.max(0,Math.min(1,base+noise)));
  }
  const sm=out.map((v,i,a)=>g==='d'?(v*.6+(a[i-1]??v)*.25+(a[i+1]??v)*.15):v);
  return sm.map(v=>+(lo+v*(hi-lo)).toFixed(1));
}
/* 여러 계열을 한 좌표계에 그린다. 판독용 히트존은 계열과 무관하게 하나. */
export function gChart(host,cfg){
  const el=(typeof host==='string')?$(host):host; if(!el)return;
  const W=620,H=210,PL=34,PR=14,PT=14,PB=28;
  const g=el.dataset.g||'w';
  const N=GRAN.find(x=>x[0]===g)[2];
  const labels=gLabels(g,N);
  /* 계열 하나를 실값으로 만든다. index:true 면 최대값을 100 으로 둔 지수로 바꾼다
     (언급량처럼 단위가 다른 값을 온도 0–100 축에 겹칠 때). */
  const toLive=(s,d)=>{
    if(!d)return null;
    if(s.index){ const mx=Math.max.apply(null,d)||1; d=d.map(v=>v/mx*100); }
    return Object.assign({},s,{data:d.map(v=>+(+v).toFixed(2))});
  };
  /* ★ 실데이터가 먼저다.
       cfg.rows — 날짜별 행을 직접 받은 차트 (할인률·리세일·수명주기)
       cfg.term — 용어 캐시(/api/trend)를 쓰는 차트
       값이 없으면 난수로 채우지 않고 '측정 불가'를 적고 끝낸다.
       둘 다 없는 차트(장식용 미니 스파크 등)만 예전처럼 씨드 난수를 쓴다. */
  /* ★ 관측이 하루뿐이면 추이를 그리지 않는다.
       한 점을 앞뒤로 이어 30일짜리 평평한 선을 만들면, 없던 과거를 지어낸 그림이 된다. */
  const obsDays=(rows,field)=>new Set((rows||[]).filter(r=>r&&r[field]!=null&&r.date)
    .map(r=>String(r.date).slice(0,10))).size;
  const THIN='관측된 날짜가 하루뿐이라 추이를 그리지 않습니다. 적재가 쌓이면 자동으로 그려집니다.';
  if(cfg.rows){
    const thin=cfg.sets.every(s=>obsDays(s.rows||cfg.rows,s.field||'value')<2);
    if(thin&&cfg.rows.length){
      el.innerHTML=unavailableHTML(THIN,'');
      el.dataset.live='thin';
      return;
    }
    const live=cfg.sets.map(s=>toLive(s,seriesFromRows(s.rows||cfg.rows,{points:N,step:g,field:s.field||'value',raw:true})));
    if(live.every(Boolean)){
      el.dataset.live='ok';
      return gPaint(el,cfg,g,gLabels(g,N,lastDateOf(cfg.rows)),live);
    }
    el.innerHTML=unavailableHTML(cfg.emptyReason||'이 차트에 쓸 값이 아직 없습니다.',
      cfg.sets.filter((s,i)=>!live[i]).map(s=>s.name).join(' · ')+(live.some(Boolean)?' 계열이 비어 있어 섞어 그리지 않습니다.':''));
    el.dataset.live=live.some(Boolean)?'partial':'unavailable';
    return;
  }
  if(cfg.term){
    const st=stateOf(cfg.term);
    if(st.status==='empty'||st.status==='error'){
      el.innerHTML=unavailableHTML(st.reason,
        st.status==='error' ? '연결이 되면 자동으로 실제 값이 뜹니다.' : '');
      el.dataset.live='unavailable';
      return;
    }
    if(st.status==='ok'){
      if(st.byDate&&st.byDate.size<2){
        el.innerHTML=unavailableHTML(THIN,'');
        el.dataset.live='thin';
        return;
      }
      const live=cfg.sets.map(s=>toLive(s,seriesOf(cfg.term,{points:N,step:g,
                                   field:s.field||'mention',raw:true})));
      if(live.every(Boolean)){
        el.dataset.live='ok';
        return gPaint(el,cfg,g,gLabels(g,N,lastDateOf(st.byDate)),live);
      }
      /* 계열 중 하나라도 값이 없으면 섞어 그리지 않는다.
         반은 진짜, 반은 난수인 그래프는 읽는 사람을 속인다. */
      el.innerHTML=unavailableHTML(
        '이 지표는 아직 RDS 에 값이 없습니다.',
        (st.unavailable && st.unavailable.reason) || '');
      el.dataset.live='partial';
      return;
    }
  }
  const sets=cfg.sets.map(s=>Object.assign({},s,{data:gSeries(cfg.key+s.id,g,s.shape,s.lo,s.hi)}));
  el.dataset.live='seeded';
  return gPaint(el,cfg,g,labels,sets);
}

/* 좌표계에 실제로 그리는 부분. 값이 어디서 왔든 그리는 방법은 같다. */
function gPaint(el,cfg,g,labels,sets){
  const H=210,PL=34,PR=14,PT=14,PB=28;
  /* cfg.wide — 가로 전체 카드(.trGrid.one)에 놓인 차트.
     viewBox 가 620×210 로 고정이면 폭을 늘린 만큼 높이 · 글씨 · 선 굵기가 같이 커진다.
     그래서 폭(W)만 늘린다 — 원래 자리(1.5fr 칸)보다 넓어진 비율만큼 W 를 키우면
     높이와 글씨는 원래 크기 그대로, 가로로만 늘어난다. */
  const W=cfg.wide?gWideW(el):620;
  const n=labels.length;
  const all=sets.reduce((a,s)=>a.concat(s.data),[]);
  const mn=cfg.min!=null?cfg.min:Math.min.apply(null,all), mx=cfg.max!=null?cfg.max:Math.max.apply(null,all);
  const pad=(mx-mn)*.16||1, LO=cfg.min!=null?mn:mn-pad, HI=cfg.max!=null?mx:mx+pad;
  const X=i=>PL+(W-PL-PR)*(n===1?0:i/(n-1));
  const Y=v=>PT+(H-PT-PB)*(1-(v-LO)/((HI-LO)||1));
  const line=d=>d.map((v,i)=>(i?'L':'M')+X(i).toFixed(1)+' '+Y(v).toFixed(1)).join(' ');
  const gridY=[0,.25,.5,.75,1].map(p=>{
    const y=PT+(H-PT-PB)*p, v=(HI-(HI-LO)*p);
    return '<line class="grid" x1="'+PL+'" y1="'+y.toFixed(1)+'" x2="'+(W-PR)+'" y2="'+y.toFixed(1)+'"/>'+
      '<text class="axl" x="'+(PL-7)+'" y="'+(y+3).toFixed(1)+'" text-anchor="end">'+
      (Math.round(v*10)/10)+'</text>';
  }).join('');
  const step=Math.max(1,Math.ceil(n/6));
  const gridX=labels.map((l,i)=>(i%step===0||i===n-1)
    ? '<text class="axl" x="'+X(i).toFixed(1)+'" y="'+(H-8)+'" text-anchor="middle">'+l+'</text>':'').join('');
  const paths=sets.map(s=>'<path class="'+(s.accent?'ln2':'ln')+'" d="'+line(s.data)+'"/>').join('');
  const heads=sets.map(s=>'<circle class="'+(s.accent?'hd2':'hd')+'" data-s="'+s.id+'" r="4.5" cx="0" cy="0"/>').join('');
  el.innerHTML=
    '<div class="gSel">'+GRAN.map(x=>'<button type="button" data-g="'+x[0]+'"'+
      (x[0]===g?' class="on"':'')+'>'+x[1]+'</button>').join('')+'</div>'+
    '<div class="chartBox">'+
      '<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none">'+
        (cfg.band?'<rect class="band" x="'+X(Math.round(n*cfg.band[0]))+'" y="'+PT+'" width="'+
          (X(Math.round(n*cfg.band[1]))-X(Math.round(n*cfg.band[0])))+'" height="'+(H-PT-PB)+'"/>':'')+
        gridY+gridX+
        '<line class="ax" x1="'+PL+'" y1="'+(H-PB)+'" x2="'+(W-PR)+'" y2="'+(H-PB)+'" stroke="var(--pink-3)"/>'+
        paths+
        '<line class="xh" x1="0" y1="'+PT+'" x2="0" y2="'+(H-PB)+'"/>'+heads+
        '<rect x="'+PL+'" y="0" width="'+(W-PL-PR)+'" height="'+H+'" fill="transparent" class="hit"/>'+
      '</svg>'+
      '<div class="gTip"></div>'+
    '</div>'+
    (cfg.sets.length>1?'<div class="gLegend">'+sets.map(s=>
      '<span><i style="background:'+(s.accent?'var(--coral)':'var(--pink-0)')+'"></i>'+s.name+'</span>').join('')+'</div>':'');
  /* 판독 — viewBox 가 늘어나므로 화면 좌표를 비율로 되돌려 인덱스를 찾는다 */
  const box=el.querySelector('.chartBox'), svg=el.querySelector('svg'), tip=el.querySelector('.gTip');
  const xh=el.querySelector('.xh'), hds=[...el.querySelectorAll('.hd,.hd2')];
  const read=e=>{
    const r=svg.getBoundingClientRect(); if(!r.width)return;
    const px=(e.clientX-r.left)/r.width*W;
    let i=Math.round((px-PL)/((W-PL-PR)/(n-1||1)));
    i=Math.max(0,Math.min(n-1,i));
    box.classList.add('hov');
    xh.setAttribute('x1',X(i)); xh.setAttribute('x2',X(i));
    hds.forEach((h,k)=>{ h.setAttribute('cx',X(i)); h.setAttribute('cy',Y(sets[k].data[i])) });
    tip.innerHTML='<span class="dt">'+labels[i]+'</span>'+sets.map(s=>
      '<span class="vv"><i style="background:'+(s.accent?'var(--coral)':'var(--paper)')+'"></i>'+
      '<b>'+s.data[i].toFixed(1)+'</b><span>'+(s.unit||'')+'</span></span>').join('');
    tip.style.left=(X(i)/W*100)+'%';
    tip.style.top=(Math.min.apply(null,sets.map(s=>Y(s.data[i])))/H*100-4)+'%';
  };
  svg.addEventListener('mousemove',read);
  svg.addEventListener('mouseleave',()=>box.classList.remove('hov'));
  el.querySelector('.gSel').addEventListener('click',ev=>{
    const b=ev.target.closest('button'); if(!b)return;
    el.dataset.g=b.dataset.g; gChart(el,cfg);
    if(HAS_A)aAnimate(el.querySelectorAll('.ln,.ln2'),{opacity:[0,1],duration:420,ease:'out(2)'});
  });
  gDraw(el.querySelectorAll('.ln,.ln2'),1050,180);
  return el;
}
function gWideW(el){
  const grid=el.closest('.trGrid'), panel=el.closest('.panelC');
  const G=grid?grid.clientWidth:0;
  if(!G||!panel)return Math.round(620*1.7);
  const cs=getComputedStyle(panel);
  const chrome=parseFloat(cs.paddingLeft)+parseFloat(cs.paddingRight)+
               parseFloat(cs.borderLeftWidth)+parseFloat(cs.borderRightWidth);
  const wide=G-chrome;                               /* 지금 카드 안쪽 폭 */
  const base=(G-12)*1.5/2.5-chrome;                  /* 원래 두 칸일 때 왼쪽 카드 안쪽 폭 (.trGrid 1.5fr : 1fr, gap 12px) */
  return Math.round(620*Math.max(1,wide/Math.max(1,base)));
}
/* 선이 그려지며 들어오는 연출.
   createDrawable 은 "엘리먼트"가 아니라 "프록시"를 돌려주고, 그 프록시를 타깃으로
   써야 draw 가 먹는다. 엘리먼트를 그대로 넘기면 stroke-dasharray 가 0 인 채로 남아
   선이 통째로 사라진다. 끝나면 대시를 지워 어떤 경우에도 실선으로 남긴다. */
export function gDraw(paths,dur,stag){
  const ps=[...paths]; if(!ps.length)return;
  const clear=()=>ps.forEach(p=>{ p.style.strokeDasharray=''; p.style.strokeDashoffset=''; });
  const dr=HAS_A&&((A&&A.svg&&A.svg.createDrawable)||(A&&A.createDrawable));
  if(!dr){ clear(); return }
  let tg=[];
  try{ tg=ps.map(p=>dr(p)).filter(Boolean) }catch(e){ clear(); return }
  if(!tg.length){ clear(); return }
  try{
    aAnimate(tg,{draw:['0 0','0 1'],duration:dur||1050,
      delay:aStagger(stag==null?180:stag),ease:'inOut(3)',onComplete:clear});
  }catch(e){ clear() }
  /* 혹시 draw 가 끝까지 안 돌아도 선은 반드시 보이게 */
  setTimeout(clear,(dur||1050)+ps.length*(stag==null?180:stag)+260);
}
