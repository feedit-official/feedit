/* ============================================================
   파티클 인체 — 절차적 생성 (v2)
   · 관절 좌표로 골격을 세우고 캡슐 부피를 점으로 채운다
   · 점을 가로 띠(scan band)에 정렬해 3D 스캔 포인트클라우드 질감을 만든다
   · 다섯 인체가 서로 다른 동적 포즈를 갖고, 깊이·크기도 어긋난다
   외부 모델·이미지 없이 전부 코드로 만든다.
   ============================================================ */

import * as THREE from 'three';

/* ── 기본 골격 ──────────────────────────────────────
   키 1.8 단위, 발바닥 y=0. +x 오른쪽, +y 위, +z 앞(카메라 쪽).   */

const BASE = {
  head:[0,1.70,0], neck:[0,1.50,0],
  chestT:[0,1.44,0], chestB:[0,1.16,0], pelvis:[0,0.98,0],
  shL:[ 0.215,1.45,0], elL:[ 0.255,1.13,0], wrL:[ 0.27,0.81,0],
  shR:[-0.215,1.45,0], elR:[-0.255,1.13,0], wrR:[-0.27,0.81,0],
  hipL:[ 0.11,0.96,0], knL:[ 0.13,0.53,0], anL:[ 0.13,0.08,0], ftL:[ 0.13,0.03,0.15],
  hipR:[-0.11,0.96,0], knR:[-0.13,0.53,0], anR:[-0.13,0.08,0], ftR:[-0.13,0.03,0.15],
};

/* ── 포즈 다섯 ──────────────────────────────────────
   전부 실루엣이 달라야 한 줄로 세웠을 때 그림이 산다.        */

const POSES = {
  /* REACH — 한 팔을 머리 위로 뻗어 올린 순간. 몸이 길게 늘어난다 */
  reach: {
    head:[0.03,1.72,0.03], neck:[0.02,1.52,0.01],
    chestT:[0.02,1.46,0.01], chestB:[0.01,1.17,0],
    shL:[ 0.20,1.48,0.02], elL:[ 0.30,1.83,0.04], wrL:[ 0.26,2.18,0.02],
    shR:[-0.22,1.44,-0.01], elR:[-0.34,1.16,-0.10], wrR:[-0.30,0.86,-0.22],
    hipL:[ 0.11,0.97,0], knL:[ 0.13,0.54,0.03], anL:[ 0.13,0.09,0.01], ftL:[ 0.13,0.03,0.17],
    hipR:[-0.11,0.95,0], knR:[-0.17,0.52,-0.05], anR:[-0.21,0.08,-0.10], ftR:[-0.22,0.03,0.04],
  },
  /* CROUCH — 무릎을 깊게 접고 상체를 앞으로. 출발 직전의 자세 */
  crouch: {
    head:[0.12,0.98,0.34], neck:[0.08,0.80,0.26],
    chestT:[0.07,0.76,0.24], chestB:[0.04,0.58,0.12], pelvis:[0,0.44,-0.04],
    shL:[ 0.23,0.78,0.24], elL:[ 0.34,0.56,0.40], wrL:[ 0.33,0.30,0.52],
    shR:[-0.21,0.74,0.22], elR:[-0.33,0.52,0.32], wrR:[-0.28,0.26,0.46],
    hipL:[ 0.14,0.42,-0.06], knL:[ 0.23,0.28,0.40], anL:[ 0.18,0.06,0.06], ftL:[ 0.18,0.03,0.22],
    hipR:[-0.14,0.42,-0.06], knR:[-0.23,0.26,0.36], anR:[-0.18,0.06,0.02], ftR:[-0.18,0.03,0.18],
  },
  /* STRIDE — 크게 내딛는 걸음. 팔다리가 대각으로 벌어진다 */
  stride: {
    head:[0.04,1.70,0.08], neck:[0.03,1.50,0.05],
    chestT:[0.03,1.44,0.05], chestB:[0.01,1.16,0.02],
    shL:[ 0.21,1.46,0.06], elL:[ 0.27,1.16,-0.18], wrL:[ 0.27,0.88,-0.38],
    shR:[-0.21,1.44,0.03], elR:[-0.28,1.15,0.22], wrR:[-0.25,0.90,0.44],
    hipL:[ 0.11,0.96,0], knL:[ 0.15,0.56,0.28], anL:[ 0.16,0.16,0.52], ftL:[ 0.16,0.05,0.64],
    hipR:[-0.11,0.96,0], knR:[-0.14,0.50,-0.24], anR:[-0.14,0.13,-0.46], ftR:[-0.14,0.03,-0.34],
  },
  /* KNEEL — 한쪽 무릎을 바닥에. 상체는 곧게 세운다 */
  /* SIT — 무릎을 앞으로 세우고 앉은 자세. 정면에서 실루엣이 또렷하다 */
  kneel: {
    head:[-0.03,1.18,0.08], neck:[-0.02,0.98,0.04],
    chestT:[-0.02,0.92,0.04], chestB:[-0.01,0.70,0.02], pelvis:[0,0.50,-0.06],
    shL:[ 0.21,0.94,0.04], elL:[ 0.30,0.70,0.16], wrL:[ 0.24,0.52,0.36],
    shR:[-0.21,0.92,0.03], elR:[-0.30,0.68,0.14], wrR:[-0.23,0.50,0.34],
    hipL:[ 0.14,0.48,-0.08], knL:[ 0.21,0.52,0.36], anL:[ 0.20,0.08,0.34], ftL:[ 0.20,0.03,0.48],
    hipR:[-0.14,0.48,-0.08], knR:[-0.21,0.50,0.32], anR:[-0.20,0.08,0.30], ftR:[-0.20,0.03,0.44],
  },
  /* STAND — 무게를 한쪽 다리에 실은 콘트라포스토 */
  stand: {
    head:[-0.03,1.70,0.01], neck:[-0.02,1.50,0],
    chestT:[-0.02,1.44,0], chestB:[-0.01,1.16,0], pelvis:[0.02,0.98,0],
    shL:[ 0.20,1.45,0.01], elL:[ 0.28,1.15,0.06], wrL:[ 0.29,0.84,0.14],
    shR:[-0.22,1.43,-0.01], elR:[-0.27,1.13,-0.03], wrR:[-0.24,0.83,0.05],
    hipL:[ 0.12,0.98,0], knL:[ 0.11,0.54,0.02], anL:[ 0.10,0.08,0], ftL:[ 0.10,0.03,0.16],
    hipR:[-0.10,0.95,0], knR:[-0.19,0.52,-0.04], anR:[-0.24,0.08,-0.08], ftR:[-0.25,0.03,0.06],
  },
};

/* 뼈대 — [관절A, 관절B, 시작반지름, 끝반지름] */
const BONES = [
  ['neck','chestT',0.052,0.112],
  ['chestT','chestB',0.126,0.104],
  ['chestB','pelvis',0.100,0.098],
  ['chestT','shL',0.082,0.055], ['chestT','shR',0.082,0.055],
  ['shL','elL',0.044,0.035],    ['shR','elR',0.044,0.035],
  ['elL','wrL',0.034,0.024],    ['elR','wrR',0.034,0.024],
  ['pelvis','hipL',0.090,0.070],['pelvis','hipR',0.090,0.070],
  ['hipL','knL',0.070,0.045],   ['hipR','knR',0.070,0.045],
  ['knL','anL',0.045,0.027],    ['knR','anR',0.045,0.027],
  ['anL','ftL',0.029,0.021],    ['anR','ftR',0.029,0.021],
];

function pose(name){
  const j = {};
  for (const k in BASE) j[k] = BASE[k].slice();
  const p = POSES[name] || {};
  for (const k in p) j[k] = p[k].slice();
  return j;
}

const v = (a) => new THREE.Vector3(a[0], a[1], a[2]);

function pointInBone(a, b, r0, r1, out){
  const t = Math.random();
  out.copy(a).lerp(b, t);
  const r = (r0 + (r1 - r0) * t) * Math.pow(Math.random(), 0.74);

  const axis = new THREE.Vector3().subVectors(b, a).normalize();
  const ref = Math.abs(axis.y) > 0.9 ? new THREE.Vector3(1,0,0) : new THREE.Vector3(0,1,0);
  const u = new THREE.Vector3().crossVectors(axis, ref).normalize();
  const w = new THREE.Vector3().crossVectors(axis, u);

  const th = Math.random() * Math.PI * 2;
  out.addScaledVector(u, Math.cos(th) * r);
  out.addScaledVector(w, Math.sin(th) * r);
  return out;
}

function sampleFigure(poseName, count){
  const j = pose(poseName);
  const segs = BONES.map(([a,b,r0,r1]) => {
    const A = v(j[a]), B = v(j[b]);
    return { A, B, r0, r1, wgt: A.distanceTo(B) * ((r0 + r1) / 2) ** 2 };
  });
  const headC = v(j.head), headR = 0.079;
  const total = segs.reduce((s, x) => s + x.wgt, 0) + headR ** 3 * 3.6;

  const pts = new Float32Array(count * 3);
  const tmp = new THREE.Vector3();

  for (let i = 0; i < count; i++){
    let pick = Math.random() * total, done = false;
    for (const s of segs){
      pick -= s.wgt;
      if (pick <= 0){ pointInBone(s.A, s.B, s.r0, s.r1, tmp); done = true; break; }
    }
    if (!done){
      // 타원체 — 정면에서 좁고 위아래로 길어야 두상으로 읽힌다
      const r = headR * Math.pow(Math.random(), 0.58);
      const u2 = Math.random() * 2 - 1, ph = Math.random() * Math.PI * 2;
      const sr = Math.sqrt(1 - u2 * u2);
      tmp.set(headC.x + r * sr * Math.cos(ph) * 0.88,
              headC.y + r * u2 * 1.32,
              headC.z + r * sr * Math.sin(ph) * 1.00);
    }
    pts[i*3] = tmp.x; pts[i*3+1] = tmp.y; pts[i*3+2] = tmp.z;
  }
  return pts;
}

/* ── 셰이더 ───────────────────────────────────────── */

const VERT = /* glsl */`
uniform float uMorph[5];
uniform float uSpin[5];
uniform vec3  uOrigin[5];
uniform float uTime;
uniform float uSize;
uniform float uPixelRatio;

attribute vec3  aFloor;
attribute vec3  aRand;
attribute float aFig;
attribute vec3  aColor;
attribute float aScale;
attribute float aAlpha;

varying vec3  vColor;
varying float vFade;

vec3 rotY(vec3 p, float a){
  float c = cos(a), s = sin(a);
  return vec3(c * p.x + s * p.z, p.y, -s * p.x + c * p.z);
}

void main(){
  int f = int(aFig + 0.5);
  float m = uMorph[f];
  vec3 org = uOrigin[f];
  float sp = uSpin[f];

  float delay = aRand.x * 0.42;
  float t = clamp((m - delay) / (1.0 - delay), 0.0, 1.0);
  t = t * t * (3.0 - 2.0 * t);

  vec3 home = position;
  home.y += sin(uTime * 0.9 + aRand.y * 6.28) * 0.006;
  home = rotY(home - org, sp) + org;

  vec3 p = mix(home, aFloor, t);

  vec3 out3 = normalize(home - org + vec3(0.0001));
  float arc = sin(t * 3.14159);
  p += out3 * arc * aRand.z * 0.85;
  p.y += arc * (0.22 + aRand.y * 0.30);

  vFade = (1.0 - t * 0.30) * aAlpha;
  vColor = aColor;

  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = uSize * aScale * uPixelRatio * (1.0 / -mv.z);
}`;

const FRAG = /* glsl */`
precision mediump float;
varying vec3  vColor;
varying float vFade;
uniform float uOpacity;

void main(){
  vec2 c = gl_PointCoord - 0.5;
  float d = dot(c, c);
  if (d > 0.25) discard;
  float a = smoothstep(0.25, 0.05, d);
  gl_FragColor = vec4(vColor, a * vFade * uOpacity);
}`;

/* ── 무대 구성 ────────────────────────────────────────
   가운데(index 2)가 IMPACT — 붕괴 후 홀로 남는다.
   양옆은 깊이(z)와 크기를 어긋나게 두어 군상처럼 보이게 한다.  */

export const FIGURES = [
  // ly = 라벨을 띄울 높이(포즈의 머리 위)
  { key:'build-l', pose:'crouch', label:'BUILD',  x:-2.62, z:-0.95, s:1.12, ly:1.24,
    c0:[0.42,0.53,0.98], c1:[0.76,0.48,0.97] },
  { key:'think-l', pose:'kneel',  label:'THINK',  x:-1.34, z: 0.62, s:1.16, ly:1.44,
    c0:[1.00,0.52,0.16], c1:[0.99,0.76,0.30] },
  { key:'impact',  pose:'reach',  label:'IMPACT', x: 0.04, z: 0.10, s:1.20, ly:2.06,
    c0:[0.24,0.80,0.36], c1:[0.58,0.92,0.34] },
  { key:'think-r', pose:'stand',  label:'THINK',  x: 1.42, z:-0.30, s:1.10, ly:1.96,
    c0:[0.33,0.46,0.97], c1:[0.58,0.42,0.96] },
  { key:'build-r', pose:'stride', label:'BUILD',  x: 2.72, z:-0.85, s:1.08, ly:1.96,
    c0:[0.99,0.40,0.53], c1:[0.98,0.60,0.76] },
];

export function buildFigures({ perFigure = 46000, floorY = -0.02, band = 0.0135 } = {}){
  const N = perFigure * FIGURES.length;

  const position = new Float32Array(N * 3);
  const aFloor   = new Float32Array(N * 3);
  const aRand    = new Float32Array(N * 3);
  const aColor   = new Float32Array(N * 3);
  const aFig     = new Float32Array(N);
  const aScale   = new Float32Array(N);
  const aAlpha   = new Float32Array(N);

  const origins = [];

  FIGURES.forEach((F, fi) => {
    origins.push(new THREE.Vector3(F.x, 0.9 * F.s, F.z));
    const pts = sampleFigure(F.pose, perFigure);

    for (let i = 0; i < perFigure; i++){
      const k = fi * perFigure + i;
      let x = pts[i*3], y = pts[i*3+1], z = pts[i*3+2];

      /* 흩날림 — 대부분은 몸을 이루고 소수가 위로 날린다 */
      const hf   = THREE.MathUtils.clamp(y / 1.9, 0, 1);
      const disp = Math.pow(Math.random(), 3.9);
      const amt  = disp * (0.05 + hf * hf * hf * 0.42);
      const da   = Math.random() * Math.PI * 2;
      x += Math.cos(da) * amt;
      z += Math.sin(da) * amt * 0.8;
      y += (0.25 + Math.random() * 0.75) * amt * 1.15;

      /* 스캔 밴딩 — 점을 가로 띠에 붙인다.
         3D 스캐너가 훑고 지나간 듯한 결이 생긴다.
         이게 없으면 그냥 뿌연 안개로 보인다. */
      y = Math.round(y / band) * band + (Math.random() - 0.5) * band * 0.22;

      const S = F.s;
      position[k*3]   = x * S + F.x;
      position[k*3+1] = y * S;
      position[k*3+2] = z * S + F.z;

      /* 바닥에 쌓일 자리 */
      const ang = Math.random() * Math.PI * 2;
      const rad = Math.pow(Math.random(), 0.62) * (0.42 + y * 0.42);
      aFloor[k*3]   = position[k*3]   + Math.cos(ang) * rad;
      aFloor[k*3+1] = floorY + Math.random() * 0.05;
      aFloor[k*3+2] = position[k*3+2] + Math.sin(ang) * rad * 0.62;

      aRand[k*3]   = Math.random();
      aRand[k*3+1] = Math.random();
      aRand[k*3+2] = Math.random();

      /* 색 — 키를 따라 두 정점 사이를 오간다 */
      const mixv = THREE.MathUtils.clamp(hf + (Math.random() - 0.5) * 0.20, 0, 1);
      aColor[k*3]   = F.c0[0] + (F.c1[0] - F.c0[0]) * mixv;
      aColor[k*3+1] = F.c0[1] + (F.c1[1] - F.c0[1]) * mixv;
      aColor[k*3+2] = F.c0[2] + (F.c1[2] - F.c0[2]) * mixv;

      aFig[k]   = fi;
      aScale[k] = (0.46 + Math.pow(Math.random(), 2.3) * 0.78) * (1 - disp * 0.34);
      aAlpha[k] = (0.72 + Math.random() * 0.28) * (1 - disp * 0.46);
    }
  });

  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(position, 3));
  geo.setAttribute('aFloor',   new THREE.BufferAttribute(aFloor, 3));
  geo.setAttribute('aRand',    new THREE.BufferAttribute(aRand, 3));
  geo.setAttribute('aColor',   new THREE.BufferAttribute(aColor, 3));
  geo.setAttribute('aFig',     new THREE.BufferAttribute(aFig, 1));
  geo.setAttribute('aScale',   new THREE.BufferAttribute(aScale, 1));
  geo.setAttribute('aAlpha',   new THREE.BufferAttribute(aAlpha, 1));
  geo.computeBoundingSphere();

  const mat = new THREE.ShaderMaterial({
    vertexShader: VERT,
    fragmentShader: FRAG,
    uniforms: {
      uMorph:      { value: new Array(5).fill(0) },
      uSpin:       { value: new Array(5).fill(0) },
      uOrigin:     { value: origins },
      uTime:       { value: 0 },
      uSize:       { value: 15 },
      uPixelRatio: { value: 1 },
      uOpacity:    { value: 1 },
    },
    transparent: true,
    depthWrite: false,
    blending: THREE.NormalBlending,
  });

  const points = new THREE.Points(geo, mat);
  points.frustumCulled = false;

  return { points, material: mat, origins, perFigure, count: FIGURES.length };
}
