/* ============================================================
   텍스트 파티클 모핑
   글자를 오프스크린에 그려 픽셀을 읽고, 그 좌표를 입자로 삼는다.
   문자열이 바뀔 때 앞머리 글자(기본 'A')는 흩어지지 않고
   새 자리로 미끄러져 간다 — 나머지만 분해·재조합된다.
   중앙정렬은 매 상태마다 다시 계산하므로 항상 유지된다.
   ============================================================ */

const DPR = () => Math.min(window.devicePixelRatio || 1, 2);

/* 문자열 하나를 점 배열로 — 오프스크린 캔버스의 알파를 훑는다 */
function samplePoints(text, font, step){
  const probe = document.createElement('canvas').getContext('2d');
  probe.font = font;
  const m = probe.measureText(text);
  const asc = Math.ceil(m.actualBoundingBoxAscent || 0) + 6;
  const desc = Math.ceil(m.actualBoundingBoxDescent || 0) + 6;
  const w = Math.max(2, Math.ceil(m.width) + 8);
  const h = Math.max(2, asc + desc);

  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const x = c.getContext('2d', { willReadFrequently: true });
  x.font = font;
  x.textBaseline = 'alphabetic';
  x.fillStyle = '#fff';
  x.fillText(text, 4, asc);

  const d = x.getImageData(0, 0, w, h).data;
  const pts = [];
  for (let py = 0; py < h; py += step){
    for (let px = 0; px < w; px += step){
      if (d[(py * w + px) * 4 + 3] > 128){
        // 격자가 눈에 띄지 않도록 셀 안에서 살짝 흔든다
        pts.push([
          px - 4 + (Math.random() - 0.5) * step,
          py - asc + (Math.random() - 0.5) * step,
        ]);
      }
    }
  }
  return { pts, width: m.width, ascent: asc };
}

/* 목표 개수에 정확히 맞춘다 — 모자라면 복제, 남으면 솎아낸다 */
function fit(pts, n){
  if (!pts.length) return Array.from({ length: n }, () => [0, 0]);
  const src = pts.slice();
  for (let i = src.length - 1; i > 0; i--){          // Fisher–Yates
    const j = (Math.random() * (i + 1)) | 0;
    [src[i], src[j]] = [src[j], src[i]];
  }
  const out = new Array(n);
  for (let i = 0; i < n; i++) out[i] = src[i % src.length].slice();
  return out;
}

/* x 순으로 정렬하면 입자가 짧은 거리를 이동해
   글자가 옆으로 흘러가는 것처럼 읽힌다 */
const byX = (a, b) => (a[0] - b[0]) || (a[1] - b[1]);

export function createTextMorph(canvas, opts = {}){
  const {
    states  = [],                 // ['AI Championship 2026', ...]
    keep    = 1,                  // 앞에서 몇 글자를 유지할지
    weight  = 600,
    family  = "'Space Grotesk','Helvetica Neue',Arial,sans-serif",
    sizeOf  = (w) => Math.min(w * 0.062, 96),
    yOf     = (h) => h * 0.5,
    nHead   = 900,
    nTail   = 4200,
    dotBase = 1.55,
    inkColor:  ink0  = '#101114',
    headColor: head0 = '#ff5a1f',
    scatter = 1,
  } = opts;

  const ctx = canvas.getContext('2d');
  let inkColor = ink0, headColor = head0;

  let layouts = [];        // 상태별 {head:[], tail:[]}
  let cur = 0, nxt = 0, prog = 1;
  let dirty = true;          // 값이 바뀐 프레임에만 다시 그린다
  let W = 0, H = 0;
  let dot = dotBase;

  // 입자마다 다른 출발 시점과 흩어지는 방향
  const seed = Array.from({ length: nTail }, () => ({
    d: Math.random() * 0.45,
    a: Math.random() * Math.PI * 2,
    r: 0.25 + Math.random() * 1.0,
    /* 솎아낼 때 쓰는 난수. 점은 x 순으로 정렬돼 있으므로
       인덱스로 자르면 문자열 오른쪽이 통째로 사라진다.
       이 난수로 걸러야 글자 전체에서 고르게 빠진다. */
    u: Math.random(),
  }));

  function layout(){
    W = canvas.clientWidth; H = canvas.clientHeight;
    const dpr = DPR();
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const size = sizeOf(W);
    dot = Math.max(1.05, dotBase * (size / 74));
    const font = `${weight} ${size}px ${family}`;
    const step = Math.max(2, Math.round(size / 26));

    const probe = document.createElement('canvas').getContext('2d');
    probe.font = font;

    const baseY = yOf(H);

    layouts = states.map((text) => {
      const head = text.slice(0, keep);
      const tail = text.slice(keep);
      const wHead = probe.measureText(head).width;
      const wTail = probe.measureText(tail).width;
      const x0 = (W - (wHead + wTail)) / 2;          // 항상 중앙정렬

      const hs = samplePoints(head, font, step);
      const ts = tail ? samplePoints(tail, font, step) : { pts: [] };

      const hp = fit(hs.pts, nHead).map(([x, y]) => [x0 + x, baseY + y]).sort(byX);
      const tp = fit(ts.pts, nTail).map(([x, y]) => [x0 + wHead + x, baseY + y]).sort(byX);
      /* 실제 표본 수에 비례해 쓰는 입자를 정한다.
         남는 입자는 알파 0 으로 물러나 있다가, 긴 문자열로 갈 때 다시 나온다. */
      const used = Math.max(500, Math.min(nTail, Math.round(ts.pts.length * 1.15)));
      return { head: hp, tail: tp, used, w: wHead + wTail, x0, baseY };
    });
  }

  function draw(){
    if (!layouts.length || !dirty) return;
    dirty = false;
    ctx.clearRect(0, 0, W, H);

    const A = layouts[cur], B = layouts[nxt];
    const t = prog;
    const e = t * t * (3 - 2 * t);

    // 유지되는 앞머리 — 흩어지지 않고 새 자리로 미끄러진다
    ctx.fillStyle = headColor;
    for (let i = 0; i < nHead; i++){
      const a = A.head[i], b = B.head[i];
      const x = a[0] + (b[0] - a[0]) * e;
      const y = a[1] + (b[1] - a[1]) * e;
      ctx.beginPath(); ctx.arc(x, y, dot * 1.06, 0, 6.2832); ctx.fill();
    }

    // 나머지 — 분해되었다가 다시 모인다
    ctx.fillStyle = inkColor;
    for (let i = 0; i < nTail; i++){
      const s = seed[i];
      const a = A.tail[i], b = B.tail[i];
      let k = (t - s.d) / (1 - s.d);
      k = k < 0 ? 0 : k > 1 ? 1 : k;
      k = k * k * (3 - 2 * k);

      const arc = Math.sin(k * Math.PI) * s.r * 96 * scatter;
      const x = a[0] + (b[0] - a[0]) * k + Math.cos(s.a) * arc;
      const y = a[1] + (b[1] - a[1]) * k + Math.sin(s.a) * arc * 1.05;

      // 남는 입자는 사라지고 모자라면 나타난다 (공간이 아닌 난수로 솎는다)
      const uA = s.u < A.used / nTail ? 1 : 0;
      const uB = s.u < B.used / nTail ? 1 : 0;
      const vis = uA + (uB - uA) * k;
      const al = (1 - Math.sin(k * Math.PI) * 0.42) * vis;
      if (al <= 0.01) continue;
      ctx.globalAlpha = al;
      ctx.beginPath(); ctx.arc(x, y, dot, 0, 6.2832); ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  return {
    layout(){ layout(); dirty = true; },
    draw,
    resize(){ layout(); dirty = true; draw(); },
    /* 상태 전환은 progress 를 0→1 로 밀어 넣어 제어한다 */
    setPair(from, to){ cur = from; nxt = to; dirty = true; },
    setProgress(p){ const q = p < 0 ? 0 : p > 1 ? 1 : p;
                    if (q !== prog){ prog = q; dirty = true; } },
    settle(i){ cur = nxt = i; prog = 1; dirty = true; },
    /* 상태 i 의 좌표 — 옆에 붙일 로고 마크의 자리를 잡는 데 쓴다 */
    box(i){ const L = layouts[i]; return L ? { x0: L.x0, w: L.w, y: L.baseY } : null; },
    get index(){ return nxt; },
    /* 지면이 검정으로 뒤집힐 때 글자색도 뒤집는다 */
    setColors(ink, head){ if (ink) inkColor = ink; if (head) headColor = head; dirty = true; },
  };
}
