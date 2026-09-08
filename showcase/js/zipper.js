/* ============================================================
   지퍼 — 캔버스로 그리는 금속 지퍼
   · 이빨은 사각형이 아니라 실제 형상: 몸통이 좁아졌다가 머리에서 부풀고 끝이 둥글다
   · 좌우 이빨이 반 칸씩 어긋나 서로의 사이로 물린다
   · 세로 그라디언트(위 밝고 아래 어두움) + 가로 스페큘러 띠로 금속을 만든다
   · 테이프에는 스티치가 박혀 있다
   같은 edge() 함수가 데님 클립 경계도 만들어, 지퍼가 지나간 자리에 정확히 천이 생긴다.
   ============================================================ */

export const ZIP = {
  rows: 42,          // 한쪽 이빨 개수
  open: 0.26,        // 화면폭 대비 아래쪽 최대 벌어짐
  tooth: 22,         // 이빨 길이(px)
  th: 5.2,           // 이빨 반높이(px)
  tape: 44,          // 테이프 폭(px)
  gap: 11,           // 중심선에서 테이프 안쪽까지 — 이빨이 절반쯤 겹치는 거리
};

/** 진행도 p(0=열림, 1=잠김)에서 y 높이의 중심선 이격 거리 */
export function edgeAt(y, p, w, h){
  const sy = p * h;
  return y <= sy ? 0 : ((y - sy) / h) * (w * ZIP.open);
}

/* 이빨 하나 — 오른쪽(+x)을 향한 형상. 좌측은 스케일로 뒤집는다 */
function toothPath(ctx, L, H){
  ctx.beginPath();
  ctx.moveTo(0, -H);
  ctx.lineTo(L * 0.50, -H);
  ctx.quadraticCurveTo(L * 0.70, -H * 1.06, L * 0.80, -H * 0.52);
  ctx.lineTo(L * 0.87, -H * 0.28);
  ctx.quadraticCurveTo(L * 1.02, 0, L * 0.87, H * 0.28);
  ctx.lineTo(L * 0.80, H * 0.52);
  ctx.quadraticCurveTo(L * 0.70, H * 1.06, L * 0.50, H);
  ctx.lineTo(0, H);
  ctx.closePath();
}

function metalGrad(ctx, H){
  const g = ctx.createLinearGradient(0, -H, 0, H);
  g.addColorStop(0.00, '#fdfefe');
  g.addColorStop(0.22, '#c3ccd9');
  g.addColorStop(0.44, '#7d8896');
  g.addColorStop(0.52, '#ffffff');   // 스페큘러
  g.addColorStop(0.62, '#8d97a6');
  g.addColorStop(0.86, '#59636f');
  g.addColorStop(1.00, '#8a94a2');
  return g;
}

function drawTooth(ctx, x, y, dir, L, H, alpha){
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(dir, 1);
  ctx.globalAlpha = alpha;

  ctx.shadowColor = 'rgba(6,12,26,.55)';
  ctx.shadowBlur = 3;
  ctx.shadowOffsetY = 1.4;

  toothPath(ctx, L, H);
  ctx.fillStyle = metalGrad(ctx, H);
  ctx.fill();

  ctx.shadowColor = 'transparent';
  ctx.lineWidth = 0.7;
  ctx.strokeStyle = 'rgba(14,22,40,.55)';
  ctx.stroke();

  // 머리 위쪽 하이라이트 한 점
  ctx.beginPath();
  ctx.ellipse(L * 0.62, -H * 0.42, L * 0.20, H * 0.16, 0, 0, 6.2832);
  ctx.fillStyle = 'rgba(255,255,255,.72)';
  ctx.fill();

  ctx.restore();
}

function drawSlider(ctx, cx, sy){
  ctx.save();
  ctx.translate(cx, sy);

  ctx.shadowColor = 'rgba(4,10,24,.6)';
  ctx.shadowBlur = 12;
  ctx.shadowOffsetY = 4;

  // 몸통 — 위가 넓고 아래로 좁아진다
  ctx.beginPath();
  ctx.moveTo(-26, -34);
  ctx.quadraticCurveTo(-30, -34, -30, -26);
  ctx.lineTo(-16, 20);
  ctx.quadraticCurveTo(-14, 30, 0, 30);
  ctx.quadraticCurveTo(14, 30, 16, 20);
  ctx.lineTo(30, -26);
  ctx.quadraticCurveTo(30, -34, 26, -34);
  ctx.closePath();
  const g = ctx.createLinearGradient(-30, -34, 30, 30);
  g.addColorStop(0.00, '#ffffff');
  g.addColorStop(0.28, '#cbd3de');
  g.addColorStop(0.46, '#78828f');
  g.addColorStop(0.54, '#f6f8fa');
  g.addColorStop(0.78, '#6b7480');
  g.addColorStop(1.00, '#aab3c0');
  ctx.fillStyle = g;
  ctx.fill();
  ctx.shadowColor = 'transparent';
  ctx.lineWidth = 0.9;
  ctx.strokeStyle = 'rgba(12,20,36,.6)';
  ctx.stroke();

  // 상단 크라운
  ctx.beginPath();
  ctx.roundRect(-11, -44, 22, 14, 5);
  ctx.fillStyle = g;
  ctx.fill(); ctx.stroke();

  // 풀탭 고리 + 탭
  ctx.beginPath();
  ctx.moveTo(-4, 26); ctx.lineTo(4, 26);
  ctx.lineTo(6, 34); ctx.lineTo(-6, 34);
  ctx.closePath();
  ctx.fillStyle = '#9aa3b0'; ctx.fill(); ctx.stroke();

  ctx.beginPath();
  ctx.roundRect(-9, 34, 18, 40, 7);
  const g2 = ctx.createLinearGradient(-9, 34, 9, 74);
  g2.addColorStop(0, '#eef2f6'); g2.addColorStop(.45, '#8b95a3');
  g2.addColorStop(.55, '#f4f7fa'); g2.addColorStop(1, '#69727e');
  ctx.fillStyle = g2; ctx.fill(); ctx.stroke();

  // 탭 안쪽 구멍
  ctx.beginPath();
  ctx.roundRect(-4.5, 42, 9, 24, 4);
  ctx.fillStyle = 'rgba(18,26,42,.72)'; ctx.fill();

  ctx.restore();
}

/**
 * @param {HTMLCanvasElement} canvas
 * @param {number} p 0(완전히 열림) → 1(끝까지 잠김)
 */
export function drawZipper(canvas, p){
  const dpr = Math.min(devicePixelRatio || 1, 2);
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (canvas.width !== Math.round(w * dpr)){
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const cx = w / 2;
  const sy = p * h;
  const E = (y) => edgeAt(y, p, w, h);

  /* ── 테이프 두 폭 ── */
  for (const dir of [-1, 1]){
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(cx + dir * (ZIP.gap + E(0)), 0);
    ctx.lineTo(cx + dir * (ZIP.gap + ZIP.tape + E(0)), 0);
    ctx.lineTo(cx + dir * (ZIP.gap + ZIP.tape + E(h)), h);
    ctx.lineTo(cx + dir * (ZIP.gap + E(h)), h);
    ctx.closePath();

    const tg = ctx.createLinearGradient(cx + dir * ZIP.gap, 0, cx + dir * (ZIP.gap + ZIP.tape), 0);
    tg.addColorStop(0.00, '#1b2942');
    tg.addColorStop(0.28, '#3a4d73');
    tg.addColorStop(0.72, '#31436b');
    tg.addColorStop(1.00, '#1a2740');
    ctx.fillStyle = tg;
    ctx.fill();

    // 스티치 — 테이프 바깥쪽에 한 줄
    ctx.clip();
    ctx.setLineDash([6, 5]);
    ctx.lineWidth = 1.6;
    ctx.strokeStyle = 'rgba(226,232,244,.42)';
    ctx.beginPath();
    ctx.moveTo(cx + dir * (ZIP.gap + ZIP.tape - 8 + E(0)), 0);
    ctx.lineTo(cx + dir * (ZIP.gap + ZIP.tape - 8 + E(h)), h);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();
  }

  /* ── 이빨 ── */
  const step = h / ZIP.rows;
  for (let i = 0; i < ZIP.rows * 2; i++){
    const dir = i % 2 ? 1 : -1;
    const row = (i / 2) | 0;
    // 오른쪽 줄을 반 칸 내려 서로의 사이로 물린다
    const y = (row + 0.5) * step + (dir > 0 ? step * 0.5 : 0);
    if (y > h + 20) continue;

    const e = E(y);
    // 뿌리는 늘 테이프 안쪽 가장자리, 머리는 늘 중심선 쪽을 향한다.
    // 닫힌 구간(e≈0)에서는 좌우 이빨이 중심선을 넘어 서로의 사이로 물린다.
    const x = cx + dir * (ZIP.gap + e);
    drawTooth(ctx, x, y, -dir, ZIP.tooth, ZIP.th, 1);
  }

  /* ── 슬라이더 ── */
  drawSlider(ctx, cx, sy);
}
