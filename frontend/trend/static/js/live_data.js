/* 실데이터 공급기 — 화면이 난수 대신 AWS RDS 값을 쓰게 한다.
 *
 * ══════════════════════════════════════════════════════════
 *  왜 이게 필요한가
 * ══════════════════════════════════════════════════════════
 * `chart_engine.js` 는 지금까지 `gSeries()` 로 **씨드 난수**를 그렸다.
 * 이름을 씨앗으로 고정해서 "언제 봐도 같은 그림"이 나오게 만든 것이라,
 * 데이터가 하나도 없어도 화면은 멀쩡해 보였다. 이게 제일 위험하다 —
 * 보는 사람은 그게 진짜 측정값인 줄 안다.
 *
 * 그래서 규칙을 바꾼다:
 *
 *     값이 있으면 → 그 값을 그린다
 *     값이 없으면 → **'측정 불가'라고 적는다.** 난수로 채우지 않는다
 *
 * ══════════════════════════════════════════════════════════
 *  왜 미리 받아 두나 (동기 조회가 필요하다)
 * ══════════════════════════════════════════════════════════
 * `gChart()` 는 동기 함수다. 그 안에서 await 를 하려면 차트를 그리는
 * 모든 자리를 async 로 바꿔야 하는데, 그건 화면 전체를 흔드는 일이다.
 * 대신 **탭을 열 때 미리 받아 두고**, 그릴 때는 캐시에서 꺼내 쓴다.
 */

const CACHE = new Map();   // term → {status, reason, byDate:Map, unavailable}
const INFLIGHT = new Map();

/** 지표가 실제로 있는 용어 목록 (검색 후보). 없으면 빈 배열. */
export let AVAILABLE_TERMS = [];

/**
 * 이 용어의 지표를 받아 둔다. 그리기 전에 한 번 부른다.
 * 같은 용어를 여러 번 불러도 요청은 한 번만 나간다.
 */
export async function prime(term, days = 120) {
  const key = String(term || '').trim();
  if (!key) return null;
  if (CACHE.has(key)) return CACHE.get(key);
  if (INFLIGHT.has(key)) return INFLIGHT.get(key);

  const p = (async () => {
    let out;
    try {
      const r = await fetch(`/api/trend?term=${encodeURIComponent(key)}&days=${days}`);
      const j = await r.json();
      out = toEntry(j);
    } catch (e) {
      out = {
        status: 'error',
        reason: '지표 서버에 닿지 못했습니다.',
        byDate: null,
        unavailable: null,
      };
    }
    CACHE.set(key, out);
    INFLIGHT.delete(key);
    return out;
  })();

  INFLIGHT.set(key, p);
  return p;
}

function toEntry(j) {
  if (!j || j.status === 'error') {
    return { status: 'error', reason: (j && j.reason) || '알 수 없는 오류', byDate: null, unavailable: null };
  }
  if (j.status === 'empty') {
    return { status: 'empty', reason: j.reason || '측정된 자료가 없습니다.', byDate: null, unavailable: null };
  }
  const byDate = new Map();
  for (const p of j.data.series) byDate.set(p.date, p);
  return {
    status: 'ok',
    reason: '',
    byDate,
    facet: j.data.facet,
    term: j.data.term,
    unavailable: j.unavailable || null,   // temp·momentum 처럼 RDS 에 없는 값
  };
}

/** 지금 이 용어가 어떤 상태인가 — 그리기 전에 확인한다. */
export function stateOf(term) {
  const e = CACHE.get(String(term || '').trim());
  if (!e) return { status: 'unknown', reason: '아직 확인하지 않았습니다.' };
  return e;
}

/**
 * 차트가 쓸 0~1 배열을 만든다. 값이 없으면 **null 을 돌려준다.**
 *
 * ★ 0 으로 채우지 않는다. 0 은 "측정했는데 0이었다"는 뜻이고,
 *   여기 상황은 "측정하지 못했다"라서 완전히 다른 말이다.
 *
 * @param field 'mention' | 'score' | 'temp' …  (RDS 에 없으면 null)
 */
export function seriesOf(term, { points = 30, step = 'd', field = 'mention' } = {}) {
  const e = CACHE.get(String(term || '').trim());
  if (!e || e.status !== 'ok' || !e.byDate) return null;

  const raw = [];
  const today = new Date();
  for (let i = points - 1; i >= 0; i--) {
    const d = new Date(today);
    if (step === 'd') d.setDate(d.getDate() - i);
    else if (step === 'w') d.setDate(d.getDate() - i * 7);
    else d.setMonth(d.getMonth() - i);
    raw.push(pickNear(e.byDate, d, step, field));
  }
  // 한 점도 못 찾았으면 그릴 게 없다.
  if (!raw.some((v) => v !== null)) return null;

  // 0~1 로 눕힌다. 차트 엔진이 그 범위를 기대한다.
  const nums = raw.filter((v) => v !== null);
  const lo = Math.min(...nums);
  const hi = Math.max(...nums);
  const span = hi - lo || 1;
  // 빈 자리는 앞뒤 값으로 잇는다 — 없는 날을 0 으로 떨어뜨리면
  // 그래프가 바닥을 치는 것처럼 보여서 거짓말이 된다.
  let last = null;
  const filled = raw.map((v) => (v === null ? last : (last = v)));
  for (let i = filled.length - 1; i >= 0; i--) if (filled[i] === null) filled[i] = filled[i + 1] ?? lo;

  return filled.map((v) => (v - lo) / span);
}

/** 그 날짜(또는 그 구간)의 값. 주·월이면 구간 안 평균. */
function pickNear(byDate, d, step, field) {
  const iso = (x) => x.toISOString().slice(0, 10);
  if (step === 'd') {
    const p = byDate.get(iso(d));
    return p ? numOr(p[field]) : null;
  }
  const back = step === 'w' ? 7 : 30;
  const vals = [];
  for (let k = 0; k < back; k++) {
    const t = new Date(d);
    t.setDate(t.getDate() - k);
    const p = byDate.get(iso(t));
    const v = p ? numOr(p[field]) : null;
    if (v !== null) vals.push(v);
  }
  return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
}

function numOr(v) {
  return v === null || v === undefined || Number.isNaN(Number(v)) ? null : Number(v);
}

/** 지표가 있는 용어 목록을 한 번 받아 둔다. */
export async function loadAvailableTerms() {
  try {
    const j = await fetch('/api/trend').then((r) => r.json());
    AVAILABLE_TERMS = j.status === 'ok' ? j.data : [];
    return { status: j.status, reason: j.reason || '', terms: AVAILABLE_TERMS };
  } catch (e) {
    AVAILABLE_TERMS = [];
    return { status: 'error', reason: '지표 서버에 닿지 못했습니다.', terms: [] };
  }
}

/**
 * '측정 불가' 안내 HTML.
 * 실존 클래스만 쓴다 — `.note` (trend/static/css/weekly_report.css).
 */
export function unavailableHTML(reason, extra) {
  const 줄 = [
    '<b>측정 불가</b>',
    reason || '이 값은 아직 측정된 자료가 없습니다.',
  ];
  if (extra) 줄.push(extra);
  return `<div class="note">${줄.map(esc).join('<br>')}</div>`;
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (m) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
}
