/* ============================================================
   FEEDiT — 소개 페이지 오케스트레이션
   S0 대기 → S1 붕괴 → S2 텍스트 모핑 → S3 지퍼·데님·THINK
   → S4 WHY(신발끈) → S5 BUILD
   ============================================================ */

import * as THREE from 'three';
import { buildFigures, FIGURES } from './figures.js';
import { createTextMorph } from './textmorph.js';
import { paintDenim } from './denim.js';
import { drawZipper, edgeAt, ZIP } from './zipper.js';

/* 무대 배역 — 인체 다섯 중 누가 어느 장면을 맡는지 */
const F_IMPACT = 2;   // 가운데. 붕괴 후 홀로 남는다
const F_THINK  = 3;   // S3 에서 데님 위에 재조립
const F_BUILD  = 4;   // S5 에서 다시 뭉쳐 회전

const PLATFORM_URL = 'https://fee-di-t-frontend.vercel.app/';
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
const lerp  = (a, b, t) => a + (b - a) * t;

/* ══════════════════════════════════════════════════
   1. 3D — 파티클 인체
   ══════════════════════════════════════════════════ */

const glCanvas = $('#gl');
const renderer = new THREE.WebGLRenderer({ canvas: glCanvas, antialias: true, alpha: true });
const DPR = Math.min(devicePixelRatio || 1, 2);
renderer.setPixelRatio(DPR);
renderer.setClearAlpha(0);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);

const FIG = buildFigures({ perFigure: window.innerWidth < 760 ? 17000 : 46000 });
FIG.material.uniforms.uPixelRatio.value = DPR;
scene.add(FIG.points);

/* 렌더 상태 — 스크롤과 타임라인이 이 값만 건드린다 */
const N_FIG = FIGURES.length;
const S = {
  morph: new Array(N_FIG).fill(0),   // 인체별 분해도
  spinV: new Array(N_FIG).fill(0),   // 회전 속도(rad/s)
  spin:  new Array(N_FIG).fill(0),   // 누적 각도
  cam:   { x: 0, y: 1.02, z: 5.55, lookX: 0, lookY: 0.96 },
  opacity: 1,
  labels: 0,
  text: 1,          // 타이틀·락업 캔버스 (오프닝 이후 걷힌다)
};

function resize3D(){
  const w = innerWidth, h = innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}

/* ══════════════════════════════════════════════════
   2. 텍스트 파티클
   ══════════════════════════════════════════════════ */

const title = createTextMorph($('#txTitle'), {
  states: ['AI Championship 2026', 'Are you ready?', 'Already.'],
  keep: 1,
  weight: 600,
  sizeOf: (w) => clamp(w * 0.047, 24, 74),
  yOf: (h) => h * 0.505,
  nHead: 1300, nTail: 6600,
});

const lockup = createTextMorph($('#txLockup'), {
  states: ['IMPACT · THINK · BUILD', 'FEEDiT'],
  keep: 0,
  weight: 500,
  sizeOf: (w) => clamp(w * 0.021, 13, 32),
  yOf: (h) => h * 0.505 + clamp(innerWidth * 0.047, 24, 74) * 0.98,
  nHead: 1, nTail: 2600,
  inkColor: '#3b3f46',
  scatter: 0.7,
});

function layoutText(){
  title.layout();
  lockup.layout();
  placeMark();
}

/* FEEDiT 마크를 락업 글자 왼쪽에 붙인다.
   글자가 중앙정렬이므로 마크 폭만큼 함께 밀어 균형을 맞춘다. */
function placeMark(){
  const el = $('#fmark');
  const b = lockup.box(1);
  if (!b) return;
  const size = clamp(innerWidth * 0.047, 24, 74) * 0.78;
  const gap  = size * 0.42;
  el.style.width = size + 'px';
  el.style.height = size + 'px';
  el.style.left = (b.x0 - gap - size / 2) + 'px';
  el.style.top  = (b.y - size * 0.36) + 'px';
}

/* ══════════════════════════════════════════════════
   3. 데님 텍스처 — 능직(twill)을 절차적으로 짠다
   ══════════════════════════════════════════════════ */

function makeDenim(){
  const c = $('#denimTex');
  paintDenim(c, {
    w: Math.min(Math.round(innerWidth  * 1.05), 1600),
    h: Math.min(Math.round(innerHeight * 1.05), 1100),
    yarn: innerWidth < 760 ? 5 : 6,
  });
  $('#denim').style.setProperty('--tex', `url("${c.toDataURL('image/jpeg', 0.88)}")`);
}

/* ══════════════════════════════════════════════════
   4. 지퍼
   ══════════════════════════════════════════════════ */

/* 지퍼는 js/zipper.js 가 캔버스에 그린다.
   여기서는 같은 edge 규칙으로 데님 클립만 맞춰 준다. */
let lastZip = 0;
function updateZip(p){
  lastZip = p;
  drawZipper($('#zip'), p);
  const d = $('#denim');
  d.style.setProperty('--zp', (p * 100) + '%');
  d.style.setProperty('--zo', (ZIP.open * 100) + '%');
}

/* ══════════════════════════════════════════════════
   5. 신발끈 — S자로 늘어진 경로
   ══════════════════════════════════════════════════ */

function buildLace(){
  const sec = $('#sWhy');
  const svg = $('#lace');
  const w = sec.clientWidth, h = sec.scrollHeight;
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.style.height = h + 'px';

  // 좌우로 흔들리며 내려가는 제어점
  const pts = [];
  const n = 9;
  for (let i = 0; i <= n; i++){
    const t = i / n;
    const swing = Math.sin(t * Math.PI * 2.1) * 0.30;
    pts.push([w * (0.5 + swing), h * (0.02 + t * 0.96)]);
  }
  // Catmull-Rom → 베지어
  let dPath = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++){
    const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i+1], p3 = pts[i+2] || pts[i+1];
    const c1 = [p1[0] + (p2[0]-p0[0])/6, p1[1] + (p2[1]-p0[1])/6];
    const c2 = [p2[0] - (p3[0]-p1[0])/6, p2[1] - (p3[1]-p1[1])/6];
    dPath += `C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }

  svg.innerHTML = `
    <path id="laceGhost" d="${dPath}" fill="none" stroke="rgba(255,255,255,.07)" stroke-width="9" stroke-linecap="round"/>
    <path id="laceCore"  d="${dPath}" fill="none" stroke="rgba(226,232,244,.34)" stroke-width="7" stroke-linecap="round"/>
    <path id="laceWeave" d="${dPath}" fill="none" stroke="rgba(90,110,150,.42)" stroke-width="7"
          stroke-linecap="butt" stroke-dasharray="2.2 6"/>
    <path id="laceGloss" d="${dPath}" fill="none" stroke="rgba(255,255,255,.30)" stroke-width="1.8"
          stroke-linecap="round" transform="translate(-1.4,-1.4)"/>`;

  const core = svg.querySelector('#laceCore');
  const L = core.getTotalLength();
  ['#laceCore', '#laceGloss'].forEach(sel => {
    const el = svg.querySelector(sel);
    el.style.strokeDasharray = L;
    el.style.strokeDashoffset = L;
    el.dataset.len = L;
  });
  const weave = svg.querySelector('#laceWeave');
  weave.style.strokeDasharray = `2.5 7`;
  weave.style.opacity = 0;
  return L;
}

function drawLace(p){
  const svg = $('#lace');
  const core = svg.querySelector('#laceCore');
  if (!core) return;
  const L = +core.dataset.len;
  core.style.strokeDashoffset = L * (1 - p);
  const gloss = svg.querySelector('#laceGloss');
  gloss.style.strokeDashoffset = L * (1 - p);
  svg.querySelector('#laceWeave').style.opacity = p > 0.02 ? 1 : 0;
}

/* ══════════════════════════════════════════════════
   6. 도식 — 포지셔닝 맵 / 4원 교집합
   ══════════════════════════════════════════════════ */

function buildPosmap(){
  const players = [
    { x:205, y:210, r:74, n:'썸트렌드', s:'소셜 리스닝' },
    { x:150, y:330, r:62, n:'블링',     s:'인플루언서' },
    { x:288, y:338, r:60, n:'패션넷',   s:'빅데이터' },
    { x:560, y:196, r:70, n:'인스타그램', s:'SNS 커머스' },
    { x:672, y:274, r:64, n:'유튜브',   s:'콘텐츠' },
    { x:556, y:330, r:52, n:'틱톡',     s:'숏폼' },
    { x:520, y:492, r:66, n:'무신사',   s:'패션 커머스' },
    { x:452, y:576, r:56, n:'에이블리', s:'AI 피팅' },
    { x:614, y:566, r:58, n:'지그재그', s:'AI 추천' },
  ];
  const bubbles = players.map((p, i) => `
    <g class="pm-b" style="--i:${i}">
      <circle cx="${p.x}" cy="${p.y}" r="${p.r}" fill="rgba(255,255,255,.055)" stroke="rgba(255,255,255,.14)"/>
      <text x="${p.x}" y="${p.y - 3}" class="pm-n">${p.n}</text>
      <text x="${p.x}" y="${p.y + 16}" class="pm-s">${p.s}</text>
    </g>`).join('');

  $('#posmap').innerHTML = `
    <style>
      .pm-ax{stroke:rgba(255,255,255,.3);stroke-width:1.2}
      .pm-al{fill:rgba(255,255,255,.5);font:500 12px var(--mono, monospace);letter-spacing:.06em}
      .pm-n{fill:#fff;font:600 15px var(--sans, sans-serif);text-anchor:middle;letter-spacing:-.02em}
      .pm-s{fill:rgba(255,255,255,.5);font:400 11px var(--sans, sans-serif);text-anchor:middle}
      .pm-b{opacity:0}
      .pm-me circle{fill:rgba(255,90,31,.10);stroke:#ff5a1f;stroke-width:1.6}
      .pm-me .pm-n{fill:#fff;font-size:19px;font-weight:700}
      .pm-me .pm-s{fill:#ff8a5c;font-size:11px;font-weight:600}
      .pm-note{fill:rgba(255,255,255,.42);font:400 11.5px var(--sans, sans-serif)}
      .pm-note b{fill:rgba(255,255,255,.72)}
    </style>
    <line class="pm-ax" x1="390" y1="34"  x2="390" y2="600"/>
    <line class="pm-ax" x1="26"  y1="390" x2="754" y2="390"/>
    <path d="M390 26 l-6 12 h12 z" fill="rgba(255,255,255,.3)"/>
    <path d="M390 608 l-6 -12 h12 z" fill="rgba(255,255,255,.3)"/>
    <path d="M18 390 l12 -6 v12 z" fill="rgba(255,255,255,.3)"/>
    <path d="M762 390 l-12 -6 v12 z" fill="rgba(255,255,255,.3)"/>
    <text class="pm-al" x="402" y="24">멀티플랫폼 통합</text>
    <text class="pm-al" x="402" y="626" >자사 플랫폼 한정</text>
    <text class="pm-al" x="26"  y="372">데이터 가공 / 분석</text>
    <text class="pm-al" x="754" y="372" text-anchor="end">구매 판단 지원</text>
    ${bubbles}
    <g class="pm-b pm-me" style="--i:9">
      <circle cx="390" cy="246" r="86" />
      <text x="390" y="238" class="pm-n">FEEDiT</text>
      <text x="390" y="260" class="pm-s">멀티플랫폼 데이터</text>
      <text x="390" y="276" class="pm-s">가공 · 분석 · 구매판단</text>
    </g>`;
}

function buildVenn(){
  const C = [
    { x:268, y:236, t:'Fashion Tech',       s:'AI × 패션 산업' },
    { x:492, y:236, t:'AI Personal Styling',s:'개인화 스타일링' },
    { x:268, y:428, t:'Social Listening',   s:'트렌드 분석' },
    { x:492, y:428, t:'Fashion E-commerce', s:'온라인 패션 소비' },
  ];
  const circles = C.map((c, i) => `
    <g class="vn-c" style="--i:${i}">
      <circle cx="${c.x}" cy="${c.y}" r="152" fill="rgba(255,255,255,.03)"
              stroke="rgba(255,255,255,.24)" stroke-width="1.2"/>
      <text x="${c.x}" y="${c.y - 6}" class="vn-t">${c.t}</text>
      <text x="${c.x}" y="${c.y + 18}" class="vn-s">${c.s}</text>
    </g>`).join('');

  $('#venn').innerHTML = `
    <style>
      .vn-t{fill:#fff;font:700 18px var(--mono, sans-serif);text-anchor:middle;letter-spacing:-.01em}
      .vn-s{fill:rgba(255,255,255,.52);font:400 12px var(--sans, sans-serif);text-anchor:middle}
      .vn-c{opacity:0}
      .vn-core{opacity:0}
      .vn-core circle{fill:rgba(20,28,46,.92);stroke:#ff5a1f;stroke-width:1.8}
      .vn-core text{fill:#fff;font:700 26px var(--mono, sans-serif);text-anchor:middle;letter-spacing:-.02em}
    </style>
    ${circles}
    <g class="vn-core">
      <circle cx="380" cy="332" r="86"/>
      <text x="380" y="342">FEEDiT</text>
    </g>`;
}

/* ══════════════════════════════════════════════════
   7. 숫자 카운트업
   ══════════════════════════════════════════════════ */

function countUp(el){
  const to  = parseFloat(el.dataset.count);
  const dec = +(el.dataset.dec || 0);
  const suf = el.dataset.suffix || '';
  const unit = el.dataset.unit || '';
  const o = { n: 0 };
  gsap.to(o, {
    n: to, duration: 1.7, ease: 'expo.out',
    onUpdate(){ el.textContent = o.n.toFixed(dec) + suf + unit; }
  });
}

/* ══════════════════════════════════════════════════
   8. 오디오
   ══════════════════════════════════════════════════ */

const bgm = $('#bgm');
const soundBtn = $('#sound');
let audioOn = false;

function startAudio(){
  if (audioOn) return;
  bgm.volume = 0;
  bgm.play().then(() => {
    audioOn = true;
    soundBtn.setAttribute('aria-pressed', 'true');
    gsap.to(bgm, { volume: 0.62, duration: 3.2, ease: 'power2.out' });
  }).catch(() => { /* 정책상 막히면 조용히 넘어간다 */ });
}
soundBtn.addEventListener('click', () => {
  if (!audioOn) { startAudio(); return; }
  if (bgm.paused){ bgm.play(); soundBtn.setAttribute('aria-pressed','true'); }
  else { bgm.pause(); soundBtn.setAttribute('aria-pressed','false'); }
});

/* ══════════════════════════════════════════════════
   9. 스와이프 제스처 잔상
   ══════════════════════════════════════════════════ */

function swipeFlick(dir = 1){
  const el = $('#swipe');
  gsap.killTweensOf([el, el.children]);
  gsap.set(el, { opacity: 1, x: -60 * dir });
  gsap.set(el.children, { opacity: .5, scaleY: 1 });
  gsap.to(el, { x: 90 * dir, opacity: 0, duration: .85, ease: 'power3.out' });
  gsap.to(el.children, { scaleY: .35, duration: .85, ease: 'power3.out', stagger: .04 });
}

/* ══════════════════════════════════════════════════
   10. 오프닝 시퀀스 — 스크롤은 잠겨 있다
   ══════════════════════════════════════════════════ */

let sequenceDone = false;

function runOpening(){
  if (sequenceDone) return;
  sequenceDone = true;

  $('#enter').classList.add('gone');
  startAudio();

  const tl = gsap.timeline({
    onComplete(){
      document.body.classList.remove('is-locked');
      $('#hint').hidden = false;
      gsap.fromTo('#hint', { opacity: 0 }, { opacity: 1, duration: .7 });
      ScrollTrigger.refresh();
    }
  });

  // ① 가운데 IMPACT 를 뺀 넷이 바깥에서 안쪽 순으로 무너진다
  [0, 4, 1, 3].forEach((fi, n) => {
    tl.to(S.morph, { [fi]: 1, duration: 2.2, ease: 'power2.in' }, n * 0.22);
  });
  tl.to(S, { labels: 0, duration: .6 }, 0)
    // ② IMPACT 만 남아 천천히 돌기 시작한다
    .to(S.spinV, { [F_IMPACT]: 0.40, duration: 2.0, ease: 'power2.out' }, 0.9)
    .to(S.cam, { x: -0.62, y: 1.58, z: 4.95, lookX: -0.78, lookY: 0.78,
                 duration: 3.4, ease: 'power2.inOut' }, 0.9);

  // ③ 제목 — AI Championship 2026 → Are you ready?
  const p1 = { v: 0 };
  tl.to(p1, {
    v: 1, duration: 1.5, ease: 'power2.inOut',
    onStart(){ title.setPair(0, 1); },
    onUpdate(){ title.setProgress(p1.v); },
  }, 1.5);

  // ④ → Already. 와 동시에 하단 락업이 FEEDiT 로 조립된다
  const p2 = { v: 0 }, p3 = { v: 0 };
  tl.to(p2, {
    v: 1, duration: 1.7, ease: 'power2.inOut',
    onStart(){ title.setPair(1, 2); swipeFlick(1); },
    onUpdate(){ title.setProgress(p2.v); },
  }, 3.7)
   .to(p3, {
    v: 1, duration: 1.8, ease: 'power2.inOut',
    onStart(){ lockup.setPair(0, 1); placeMark(); },
    onUpdate(){ lockup.setProgress(p3.v); },
  }, 3.85)
   .fromTo('#fmark', { opacity: 0, scale: .5, rotate: -25 },
                     { opacity: 1, scale: 1, rotate: 0, duration: 1.1, ease: 'back.out(1.7)' }, 4.9);

  tl.to({}, { duration: .6 });
}

/* 첫 제스처가 시퀀스를 깨운다 — 이 제스처가 오디오도 해금한다 */
function armOpening(){
  const fire = (e) => {
    if (sequenceDone) return;
    if (e.type === 'keydown' && !['Space','ArrowDown','Enter'].includes(e.code)) return;
    runOpening();
  };
  ['wheel', 'touchstart', 'click', 'keydown'].forEach(t =>
    window.addEventListener(t, fire, { passive: true }));
}

/* ══════════════════════════════════════════════════
   11. 스크롤 — S3 / S4 / S5
   ══════════════════════════════════════════════════ */

function wireScroll(){
  gsap.registerPlugin(ScrollTrigger);

  let lenis = null;
  if (window.Lenis){
    lenis = new Lenis({ duration: 1.15, smoothWheel: true, lerp: .09 });
    lenis.on('scroll', ScrollTrigger.update);
    gsap.ticker.add(t => lenis.raf(t * 1000));
    gsap.ticker.lagSmoothing(0);
  }

  const onScroll = () => document.body.classList.toggle('scrolled', scrollY > 40);
  addEventListener('scroll', onScroll, { passive: true });
  if (lenis) lenis.on('scroll', onScroll);

  /* ── S3 · 지퍼 → 데님 → THINK ── */
  ScrollTrigger.create({
    trigger: '#sZip', start: 'top top', end: 'bottom bottom', scrub: .5,
    onUpdate(self){
      const p = self.progress;

      // 오프닝의 글자는 지퍼가 내려오기 시작하면 걷힌다
      S.text = 1 - clamp(p / 0.09, 0, 1);

      // 0 → .42 : 지퍼가 잠기고 데님이 드러난다
      const zp = clamp(p / 0.42, 0, 1);
      updateZip(zp);
      $('#zip').style.opacity = p < 0.02 ? 0 : (p > 0.55 ? clamp(1 - (p - 0.55) / 0.18, 0, 1) : 1);
      // 불투명도로 페이드하면 지퍼가 연 자리가 안 보인다 — 클립이 드러냄을 맡는다
      $('#denim').style.opacity = clamp(zp / 0.05, 0, 1);
      document.body.classList.toggle('on-dark', zp > 0.35);

      // .30 → .70 : 바닥의 가루가 THINK 로 다시 뭉친다
      S.morph[F_THINK] = 1 - clamp((p - 0.30) / 0.40, 0, 1);
      // IMPACT 는 제 역할을 마치고 다시 가루로
      S.morph[F_IMPACT] = clamp((p - 0.04) / 0.22, 0, 1);

      // 카메라가 가운데(THINK)로 붙는다
      const k = clamp((p - 0.15) / 0.5, 0, 1);
      const tx = FIGURES[F_THINK].x;
      S.cam.x = lerp(-0.62, tx, k);
      S.cam.lookX = lerp(-0.78, tx, k);
      S.cam.z = lerp(4.95, 3.95, k);
      S.cam.y = lerp(1.58, 1.02, k);
      S.cam.lookY = lerp(0.78, 0.94, k);

      // .55 이후 THINK 가 돌기 시작
      S.spinV[F_THINK]  = clamp((p - 0.5) / 0.25, 0, 1) * 0.5;
      S.spinV[F_IMPACT] = 0.40 * (1 - clamp((p - 0.1) / 0.3, 0, 1));

      // 마지막 구간에서 인체가 서서히 사라진다(WHY 로 넘어갈 준비)
      S.opacity = 1 - clamp((p - 0.86) / 0.14, 0, 1);
    }
  });

  gsap.fromTo('#zipcopy', { opacity: 0, y: 26 }, {
    opacity: 1, y: 0, duration: 1, ease: 'power3.out',
    scrollTrigger: { trigger: '#sZip', start: 'top -55%', toggleActions: 'play none none reverse' }
  });

  /* ── S4 · WHY ── */
  buildLace();
  ScrollTrigger.create({
    trigger: '#sWhy', start: 'top 78%', end: 'bottom bottom', scrub: .6,
    onUpdate(self){ drawLace(self.progress); }
  });

  $$('.beat').forEach((b, i) => {
    gsap.fromTo(b, { opacity: 0, y: 44 }, {
      opacity: 1, y: 0, duration: 1, ease: 'power3.out',
      scrollTrigger: { trigger: b, start: 'top 82%', once: true, onEnter: () => swipeFlick(i % 2 ? -1 : 1) }
    });
  });

  gsap.fromTo('.why-title', { opacity: 0, y: 36 }, {
    opacity: 1, y: 0, duration: 1.1, ease: 'power3.out',
    scrollTrigger: { trigger: '.why-head', start: 'top 78%', once: true }
  });

  // 수명주기 막대
  ScrollTrigger.create({
    trigger: '.b-life', start: 'top 72%', once: true,
    onEnter(){
      gsap.to('.life-bar .was', { width: '100%', duration: 1.5, ease: 'expo.out' });
      gsap.to('.life-bar .is',  { width: '12%',  duration: 1.5, ease: 'expo.out', delay: .25 });
      $$('.b-life [data-count]').forEach(countUp);
    }
  });

  // 신호 칩
  ScrollTrigger.create({
    trigger: '.b-sig', start: 'top 74%', once: true,
    onEnter(){ gsap.to('.sigs span', { opacity: 1, y: 0, duration: .7, ease: 'power3.out', stagger: .08 }); }
  });

  // 이탈 통계
  ScrollTrigger.create({
    trigger: '.b-drop', start: 'top 72%', once: true,
    onEnter(){ $$('.stats [data-count]').forEach(countUp); }
  });

  // 도식
  ScrollTrigger.create({
    trigger: '.b-map', start: 'top 70%', once: true,
    onEnter(){
      gsap.to('.pm-b', { opacity: 1, duration: .8, ease: 'power2.out',
        stagger: { each: .07, from: 'random' } });
    }
  });
  ScrollTrigger.create({
    trigger: '.b-venn', start: 'top 70%', once: true,
    onEnter(){
      gsap.to('.vn-c', { opacity: 1, duration: .9, ease: 'power2.out', stagger: .13 });
      gsap.to('.vn-core', { opacity: 1, duration: .9, ease: 'power2.out', delay: .55 });
    }
  });

  /* ── S5 · BUILD ── */
  ScrollTrigger.create({
    trigger: '#sBuild', start: 'top bottom', end: 'bottom bottom', scrub: .5,
    onUpdate(self){
      const p = self.progress;
      $('#sheet').style.opacity = clamp(p / 0.3, 0, 1);
      S.opacity = clamp((p - 0.08) / 0.22, 0, 1);
      document.body.classList.remove('on-dark');

      S.text = 0;
      // 가루였던 BUILD 가 다시 뭉치고, 나머지는 물러난다
      S.morph[F_BUILD] = 1 - clamp((p - 0.18) / 0.42, 0, 1);
      const away = clamp(p / 0.22, 0, 1);
      for (let i = 0; i < N_FIG; i++) if (i !== F_BUILD) S.morph[i] = Math.max(S.morph[i], away);

      const k = clamp((p - 0.1) / 0.5, 0, 1);
      const bx = FIGURES[F_BUILD].x;
      S.cam.x = lerp(FIGURES[F_THINK].x, bx, k);
      S.cam.lookX = lerp(FIGURES[F_THINK].x, bx, k);
      S.cam.z = lerp(3.95, 4.35, k);
      S.cam.y = lerp(1.02, 1.14, k);
      S.cam.lookY = lerp(0.94, 1.02, k);

      S.spinV[F_BUILD] = clamp((p - 0.55) / 0.2, 0, 1) * 0.5;
      S.spinV[F_THINK] = 0;
    }
  });

  gsap.fromTo('#buildCopy', { opacity: 0, y: 30 }, {
    opacity: 1, y: 0, duration: 1.1, ease: 'power3.out',
    scrollTrigger: { trigger: '#sBuild', start: 'top -40%', toggleActions: 'play none none reverse' }
  });

  addEventListener('load', () => ScrollTrigger.refresh());
}

/* ══════════════════════════════════════════════════
   12. 라벨 투영 · 렌더 루프
   ══════════════════════════════════════════════════ */

/* 라벨은 인체 수만큼 만든다 — 인체를 늘리면 라벨도 따라온다 */
const labelEls = FIGURES.map((F) => {
  const el = document.createElement('span');
  el.textContent = F.label;
  $('#figlabels').appendChild(el);
  return el;
});
const _v = new THREE.Vector3();

function placeLabels(){
  if (S.labels <= 0.01){
    labelEls.forEach(e => e.style.opacity = 0);
    return;
  }
  labelEls.forEach((el, i) => {
    const F = FIGURES[i];
    _v.set(F.x, F.ly * F.s, F.z);        // 포즈마다 다른 머리 높이 위에 붙인다
    _v.project(camera);
    const x = (_v.x * 0.5 + 0.5) * innerWidth;
    const y = (-_v.y * 0.5 + 0.5) * innerHeight;
    el.style.transform = `translate(-50%,-50%) translate(${x}px,${y}px)`;
    el.style.opacity = (_v.z < 1 ? S.labels : 0) * (1 - S.morph[i]);
  });
}

let last = performance.now();
function loop(now){
  const dt = Math.min((now - last) / 1000, 0.05);
  last = now;

  for (let i = 0; i < N_FIG; i++) S.spin[i] += S.spinV[i] * dt;

  const u = FIG.material.uniforms;
  u.uTime.value = now / 1000;
  for (let i = 0; i < N_FIG; i++){ u.uMorph.value[i] = S.morph[i]; u.uSpin.value[i] = S.spin[i]; }
  u.uOpacity.value = S.opacity;

  camera.position.set(S.cam.x, S.cam.y, S.cam.z);
  camera.lookAt(S.cam.lookX, S.cam.lookY, 0);

  renderer.render(scene, camera);

  const txEl = $('#txTitle'), lkEl = $('#txLockup'), fmEl = $('#fmark');
  txEl.style.opacity = lkEl.style.opacity = S.text;
  if (S.text < 1) fmEl.style.opacity = S.text;
  if (S.text > 0.001){ title.draw(); lockup.draw(); }

  placeLabels();

  requestAnimationFrame(loop);
}

/* ══════════════════════════════════════════════════
   13. 부팅
   ══════════════════════════════════════════════════ */

function boot(){
  resize3D();
  layoutText();
  makeDenim();
  updateZip(0);
  buildPosmap();
  buildVenn();

  title.settle(0);
  lockup.settle(0);

  // 좁은 화면에서는 세 인체가 다 들어오도록
  if (innerWidth < 760){ S.cam.z = 8.6; S.cam.y = 1.06; S.cam.lookY = 0.98; }

  $('#buildBtn').setAttribute('href', PLATFORM_URL);

  if (REDUCED){
    // 모션을 끈 사용자에게는 완성된 장면만 보여준다
    document.body.classList.remove('is-locked');
    S.morph = new Array(N_FIG).fill(0);
    title.settle(2); lockup.settle(1);
    $('#enter').classList.add('gone');
    $('#denim').style.opacity = 1;
    gsap.set(['.pm-b', '.vn-c', '.vn-core', '.sigs span'], { opacity: 1, y: 0 });
    $$('[data-count]').forEach(e => {
      e.textContent = (+e.dataset.count).toFixed(+(e.dataset.dec||0)) + (e.dataset.suffix||'') + (e.dataset.unit||'');
    });
    gsap.set('.life-bar .was', { width: '100%' });
    gsap.set('.life-bar .is',  { width: '12%' });
    buildLace(); drawLace(1);
    renderer.render(scene, camera);
    title.draw(); lockup.draw();
    return;
  }

  S.labels = 1;
  armOpening();
  wireScroll();
  requestAnimationFrame(loop);
}

let rzT;
addEventListener('resize', () => {
  clearTimeout(rzT);
  rzT = setTimeout(() => {
    resize3D(); layoutText(); makeDenim(); updateZip(lastZip); buildLace();
    if (window.ScrollTrigger) ScrollTrigger.refresh();
  }, 180);
});

boot();
