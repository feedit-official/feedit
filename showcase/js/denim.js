/* ============================================================
   데님 — 절차적 직조
   실제 데님의 구조를 그대로 짠다.
   · 3/1 우능직(right-hand twill) — 날실이 씨실 셋을 넘고 하나를 지난다
   · 날실은 인디고, 씨실은 미표백 면 → 겉면이 푸르고 뒷면이 희다
   · 링스펀 특유의 슬럽(실 굵기 불균일)과 트위스트
   · 실 한 올마다 단면이 둥글어 위쪽에서 빛을 받는다
   이 네 가지가 다 있어야 '부직포'가 아니라 데님으로 보인다.
   ============================================================ */

/* 값싼 해시 노이즈 — 같은 입력이면 늘 같은 값 */
function hash(n){
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return s - Math.floor(s);
}
function noise1(x){
  const i = Math.floor(x), f = x - i;
  const a = hash(i), b = hash(i + 1);
  const u = f * f * (3 - 2 * f);
  return a + (b - a) * u;
}
/* 옥타브를 겹쳐 자연스러운 굵기 변화를 만든다 */
function fbm1(x){
  return noise1(x) * 0.55 + noise1(x * 2.3 + 11.3) * 0.28 + noise1(x * 4.7 + 29.1) * 0.17;
}
function noise2(x, y){
  const xi = Math.floor(x), yi = Math.floor(y);
  const xf = x - xi, yf = y - yi;
  const h = (a, b) => hash(a * 57.0 + b * 131.0);
  const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
  const a = h(xi, yi),     b = h(xi + 1, yi);
  const c = h(xi, yi + 1), d = h(xi + 1, yi + 1);
  return (a + (b - a) * u) + ((c + (d - c) * u) - (a + (b - a) * u)) * v;
}

const clamp255 = (v) => (v < 0 ? 0 : v > 255 ? 255 : v);

/**
 * @param {HTMLCanvasElement} canvas
 * @param {number} yarn  실 한 올의 두께(px). 5 안팎이 화면에서 가장 데님답다
 */
export function paintDenim(canvas, { w = 1280, h = 860, yarn = 5 } = {}){
  canvas.width = w; canvas.height = h;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const img = ctx.createImageData(w, h);
  const d = img.data;

  /* 실 색 — 인디고는 겉만 진하게 물든다(링 다잉) */
  const WARP_DEEP = [ 17, 30, 60];    // 날실 그늘
  const WARP_FACE = [ 46, 76,128];    // 날실 겉면
  const WEFT_DEEP = [ 74, 80, 92];    // 씨실 그늘
  const WEFT_FACE = [150,153,162];    // 씨실 겉면 (미표백 면) — 겉으로 조금만 비친다

  for (let y = 0; y < h; y++){
    for (let x = 0; x < w; x++){
      const i = (y * w + x) * 4;

      const cx = Math.floor(x / yarn);          // 날실 번호
      const cy = Math.floor(y / yarn);          // 씨실 번호
      const fx = (x / yarn) - cx;               // 실 안에서의 위치 0..1
      const fy = (y / yarn) - cy;

      /* 3/1 우능직 — (날실 - 씨실) mod 4 가 0 일 때만 씨실이 겉으로 나온다.
         이 한 줄이 데님의 그 사선 결을 만든다. */
      const warpOver = ((((cx - cy) % 4) + 4) % 4) !== 0;

      let base, deep, crown, along, sink;
      if (warpOver){
        base = WARP_FACE; deep = WARP_DEEP;
        crown = Math.sin(fx * Math.PI);         // 단면이 둥그니 가운데가 밝다
        along = y / yarn + cx * 17.7;           // 슬럽은 실을 따라 흐른다
        sink  = 1;
      } else {
        base = WEFT_FACE; deep = WEFT_DEEP;
        crown = Math.sin(fy * Math.PI);
        along = x / yarn + cy * 23.3;
        // 씨실은 날실 아래로 한 단 내려앉아 있다 — 그만큼 그늘진다
        sink  = 0.62;
      }

      /* 날실마다 인디고가 물든 정도가 다르다 — 이게 없으면 인쇄물처럼 보인다 */
      const dye = warpOver ? 0.80 + hash(cx * 5.3) * 0.42 : 1;

      /* 슬럽 — 실 굵기가 들쭉날쭉해야 손으로 짠 물건처럼 보인다 */
      const slub = fbm1(along * 0.16) - 0.5;
      /* 트위스트 — 실이 꼬여 있어 미세한 사선 반짝임이 생긴다 */
      const twist = Math.sin((x * 1.7 + y * 2.9) * 0.9) * 0.5 + 0.5;

      /* 빛은 왼쪽 위에서. 능선 위쪽이 밝고 아래쪽이 그늘진다 */
      let lit = (0.26 + crown * 0.80 + slub * 0.34 + twist * 0.07) * sink * dye;
      lit = lit < 0 ? 0 : lit > 1.35 ? 1.35 : lit;

      /* 실 사이 골 — 여기가 어두워야 올이 분리돼 보인다 */
      const gap = Math.min(fx, 1 - fx, fy, 1 - fy) < 0.10 ? 0.66 : 1;

      const n = (noise2(x * 0.7, y * 0.7) - 0.5) * 11;

      d[i]   = clamp255((deep[0] + (base[0] - deep[0]) * lit) * gap + n);
      d[i+1] = clamp255((deep[1] + (base[1] - deep[1]) * lit) * gap + n);
      d[i+2] = clamp255((deep[2] + (base[2] - deep[2]) * lit) * gap + n);
      d[i+3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);

  /* ── 후처리: 워싱 ────────────────────────────────── */

  // 세로 결을 따라 바래는 자국(휘스커·페이드)
  ctx.globalCompositeOperation = 'lighter';
  for (let k = 0; k < 26; k++){
    const fx0 = (hash(k * 3.1) * 1.15 - 0.08) * w;
    const wd  = (12 + hash(k * 7.7) * 70);
    const g = ctx.createLinearGradient(fx0 - wd, 0, fx0 + wd, 0);
    g.addColorStop(0,   'rgba(150,175,215,0)');
    g.addColorStop(0.5, `rgba(150,175,215,${0.05 + hash(k * 11.3) * 0.09})`);
    g.addColorStop(1,   'rgba(150,175,215,0)');
    ctx.fillStyle = g;
    ctx.fillRect(fx0 - wd, 0, wd * 2, h);
  }

  // 가운데가 밝게 닳은 자리
  const wash = ctx.createRadialGradient(w * 0.5, h * 0.42, 0, w * 0.5, h * 0.5, Math.max(w, h) * 0.66);
  wash.addColorStop(0,    'rgba(150,180,225,.16)');
  wash.addColorStop(0.55, 'rgba(90,120,175,0)');
  ctx.fillStyle = wash;
  ctx.fillRect(0, 0, w, h);

  // 가장자리 그늘
  ctx.globalCompositeOperation = 'multiply';
  const vig = ctx.createRadialGradient(w * 0.5, h * 0.46, Math.min(w, h) * 0.28,
                                       w * 0.5, h * 0.5, Math.max(w, h) * 0.78);
  vig.addColorStop(0, 'rgba(255,255,255,1)');
  vig.addColorStop(1, 'rgba(96,112,150,1)');
  ctx.fillStyle = vig;
  ctx.fillRect(0, 0, w, h);

  ctx.globalCompositeOperation = 'source-over';
  return canvas;
}
