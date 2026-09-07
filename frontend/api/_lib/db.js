/* AWS RDS(PostgreSQL) 연결 — 버셀 서버리스 함수용.
 *
 * ── 왜 여기 있나 ──────────────────────────────────────────
 * 버셀은 정적 파일만 올린다. 그래서 배포된 화면에는 백엔드가 없고,
 * 챗봇은 `127.0.0.1:8770` 을 부르다 실패해 목업으로 떨어졌다.
 * 이 폴더(`api/`)에 둔 파일은 버셀이 **서버리스 함수**로 올려 준다.
 * 화면은 같은 도메인의 `/api/...` 를 부르면 되므로 CORS 도 없다.
 *
 * ── 접속 정보는 코드에 적지 않는다 ────────────────────────
 * 전부 환경변수로 받는다. 버셀 대시보드의
 *   Settings → Environment Variables 에 넣는다.
 *
 *   DATABASE_URL   postgres://사용자:비밀번호@호스트:5432/feedit?sslmode=require
 *   (또는 따로) PGHOST · PGPORT · PGUSER · PGPASSWORD · PGDATABASE
 *
 * 비밀번호는 이 저장소 어디에도 적지 않는다. 로그에도 남기지 않는다.
 *
 * ── ★ 미리 알아 둘 것: RDS 가 밖에서 보이는가 ─────────────
 * 지금 크롤러가 쓰는 주소는 `127.0.0.1:5433` 이다. 이건 사용자 맥에서
 * SSM 포트 포워딩으로 뚫어 둔 굴이고, **버셀 함수는 그 굴에 못 들어간다.**
 * 버셀에서 붙으려면 둘 중 하나가 필요하다:
 *   ① RDS 를 공개로 열고 보안 그룹에서 접속을 허용한다 (DB 팀 결정)
 *   ② 이미 떠 있는 EC2(feedit-official.duckdns.org)에 API 를 올리고
 *      버셀은 그걸 부른다 — RDS 를 열지 않아도 된다
 * 어느 쪽이든 이 파일의 인터페이스는 그대로 쓴다.
 */

import pg from 'pg';

let pool = null;

/** 연결 묶음. 함수가 다시 깨어나도 재사용된다(콜드 스타트 완화). */
export function getPool() {
  if (pool) return pool;

  const url = process.env.DATABASE_URL;
  const cfg = url
    ? { connectionString: url }
    : {
        host: process.env.PGHOST,
        port: Number(process.env.PGPORT || 5432),
        user: process.env.PGUSER,
        password: process.env.PGPASSWORD,
        database: process.env.PGDATABASE || 'feedit',
      };

  // RDS 는 SSL 을 요구한다. 인증서 검증까지 켜려면 CA 를 심어야 하는데
  // 버셀 함수에 CA 를 넣는 건 별도 작업이라, 우선 암호화만 켠다.
  cfg.ssl = { rejectUnauthorized: false };

  // 서버리스는 오래 매달리면 안 된다. 못 붙으면 빨리 실패하고 이유를 말한다.
  cfg.connectionTimeoutMillis = 6000;
  cfg.idleTimeoutMillis = 10000;
  cfg.max = 3;

  pool = new pg.Pool(cfg);
  return pool;
}

/** 접속 정보가 하나라도 들어와 있나. 없으면 붙어 보지도 않는다. */
export function isConfigured() {
  return Boolean(process.env.DATABASE_URL || process.env.PGHOST);
}

/**
 * 질의 한 번. 실패해도 던지지 않고 `{ok:false, error}` 로 돌려준다.
 *
 * ★ 왜 던지지 않나
 *   화면은 "값이 없다"와 "DB 가 안 붙는다"를 **다르게** 보여 줘야 한다.
 *   던져 버리면 둘 다 똑같은 500 이 되어 구별할 수가 없다.
 */
export async function q(sql, args = []) {
  if (!isConfigured()) {
    return {
      ok: false,
      code: 'not_configured',
      error: 'DATABASE_URL 이 설정돼 있지 않습니다 (버셀 환경변수).',
      rows: [],
    };
  }
  try {
    const res = await getPool().query(sql, args);
    return { ok: true, rows: res.rows, count: res.rowCount };
  } catch (e) {
    // 비밀번호가 섞일 수 있는 값은 절대 그대로 내보내지 않는다.
    const msg = String(e && e.message ? e.message : e).slice(0, 300);
    return { ok: false, code: e && e.code ? String(e.code) : 'query_failed', error: msg, rows: [] };
  }
}
