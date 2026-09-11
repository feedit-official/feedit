# 배포에서 실데이터 쓰기 — 지금 상태와 남은 일

2026-09-07 기준. 코드 쪽 준비는 끝났고, **남은 건 접속 정보 하나**다.

---

## 1. 지금 무엇이 되어 있나

버셀은 정적 파일만 올리던 곳이었다.
그래서 배포된 화면에는 백엔드가 없었고, 챗봇은 방문자의 `127.0.0.1:8770`
을 부르다 실패해 조용히 목업으로 떨어졌다.

이제 `api/` 폴더가 생겼다. 버셀이 이걸 **서버리스 함수**로 올려 주므로,
화면은 같은 도메인의 `/api/...` 를 부르면 된다. CORS 도 없다.

```
GET  /api/health              AWS RDS 가 실제로 어떤 상태인지 그대로 본다
GET  /api/trend               지표가 있는 용어 목록
GET  /api/trend?term=발레코어   그 용어의 시계열
GET  /api/assoc?term=발레코어   연관어
GET  /api/products?q=엄브로     상품·가격
GET  /api/v1/health           챗봇이 답할 수 있는 상태인가
POST /api/v1/chat             챗봇 (SSE) — feedit-chat 으로 넘긴다
POST /api/v1/virtual-fitting  입혀보기 — feedit-chat 으로 넘긴다
```

---

## 2. 해야 할 일 — 버셀 환경변수 두 개

버셀 → 프로젝트 → **Settings → Environment Variables**

| 이름 | 값 | 없으면 |
|---|---|---|
| `DATABASE_URL` | `postgres://사용자:비밀번호@호스트:5432/feedit?sslmode=require` | 화면이 '측정 불가'로 뜬다 |
| `CHAT_BACKEND_URL` | feedit-chat 이 떠 있는 주소 | 챗봇이 "연결되지 않았습니다"라고 답한다 |

넣고 **다시 배포**한 뒤 `https://<배포주소>/api/health` 를 열어 본다.
표별 행 수와 판정이 그대로 나온다. 추측할 필요가 없다.

> 비밀번호는 이 저장소 어디에도 적지 않는다.
> 버셀 대시보드에만 넣는다.

---

## 3. ★ 먼저 정해야 할 것 — RDS 가 밖에서 보이는가

지금 크롤러가 쓰는 주소는 `127.0.0.1:5433` 이다.
이건 사용자 맥에서 SSM 포트 포워딩으로 뚫어 둔 굴이고,
**버셀 함수는 그 굴에 못 들어간다.**

길은 둘이다.

**① RDS 를 밖에서 보이게 한다**
공개 접근을 켜고 보안 그룹에서 허용한다. `DATABASE_URL` 만 넣으면 끝난다.
대신 DB 가 인터넷에 노출되므로 **DB 팀이 정할 일이다.**

**② 이미 떠 있는 EC2 에 API 를 얹는다** (권장)
`feedit-official.duckdns.org` (15.164.151.62) 에 Django 가 이미 돌고 있고
RDS 에 닿는다. 거기에 읽기 전용 API 를 만들고, 버셀은 그걸 부른다.
RDS 를 열지 않아도 된다.

> 참고: 그 Django 의 `apps/api/urls.py` 는 **비어 있다.**
> `views.py` 도 Django 기본 껍데기다. 대시보드 화면들도 전부
> `render(template)` 만 하고 값을 넘기지 않는다 — 그래서 카운터가 `-` 로 뜬다.
> ②를 고르면 그 API 를 만드는 일이 먼저다.

---

## 4. ★ 지표는 아직 RDS 에 없다 — 연결 문제가 아니다

RDS 에 상품·브랜드·사전은 들어가 있는데 **지표는 0행**이다.
이건 연동이 끊긴 게 아니라 **보내는 코드가 없는 것**이다.

크롤러의 `rds_sync.py` 가 쓰는 표는 여덟 개다:

```
collection.source          commerce.product        commerce.product_source
commerce.product_term      dictionary.brand        dictionary.category
dictionary.dictionary_term snapshot.product_source_snapshot
```

`analysis.term_metric_daily` 도 `analysis.term_assoc_daily` 도 **여기 없다.**
크롤러 SQLite 에는 지표가 12,484행(용어 584개, 2024-09-27 ~ 2026-09-04)
쌓여 있는데, 그걸 RDS 로 옮기는 길이 아직 안 만들어졌다.

게다가 RDS 쪽 표에는 **온도·모멘텀 컬럼 자체가 없다.**

```
있는 것   mention_count · document_count · source_count
          sentiment_avg · growth_rate · trend_score · metrics(JSON)
없는 것   temp · momentum · ma7 · ma28 · level · pct_rank
```

그래서 D→C 적재를 만들 때 **둘 중 하나를 먼저 정해야 한다** —
`metrics` JSON 에 담을지, 스키마에 컬럼을 더할지. DB 팀과 합의할 일이다.

---

## 5. 값이 없을 때 화면은 어떻게 되나

지어내지 않는다. 이게 이번 작업의 핵심이다.

전에는 트렌드 수치가 전부 **씨드 난수**(`chart_engine.js` 의 `gSeries`)여서,
데이터가 하나도 없어도 화면이 멀쩡해 보였다. 보는 사람은 그게 진짜
측정값인 줄 안다. 그래서 규칙을 바꿨다.

| 상황 | 화면 | `data-live` |
|---|---|---|
| 값이 있다 | 실제 값을 그린다 | `ok` |
| 붙었는데 값이 없다 | **측정 불가** + 왜 없는지 | `unavailable` |
| DB 가 안 붙는다 | **측정 불가** + "연결되면 자동으로 뜹니다" | `unavailable` |
| 계열 일부만 있다 | 섞어 그리지 않고 측정 불가 | `partial` |
| `term` 없는 장식 차트 | 예전처럼 씨드 난수 | `seeded` |

**'값이 없다'와 'DB 가 안 붙는다'를 반드시 구별한다.**
둘 다 숫자가 없지만 사람이 할 일이 다르다 — 앞은 기다리는 것이고
뒤는 고치는 것이다.

---

## 6. 확인

```bash
npm test          # API 응답 계약 15가지 + 차트 실데이터 6가지
```

차트 시험은 jsdom 으로 **실제로 그려 본다.**
`node --check` 는 문법만 보므로, 함수를 쪼개다 변수 하나가 밖에 남아도
통과시킨다 — 그래서 돌려 봐야 한다.

> `feedit-web/node_modules` 는 맥용이다.
> 작업 VM 에서 `npm install` 하지 않는다 — 사용자 맥 바이너리가 덮인다.
> 버셀은 배포할 때 알아서 설치한다.
