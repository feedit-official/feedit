# FEEDiT 연관어 실데이터 작업 인수인계

작성일: 2026-09-17 KST  
기준 브랜치: `main`  
기준 커밋: `cc57ae6` (`살말 댓글 모델과 0054 마이그레이션 동기화`)

현재 작업 브랜치: `feat/assoc-existing-data`  
현재 작업 상태: 문서와 직접 연결 fast path 구현 중, 아직 commit/push하지 않음

이 문서는 다음 작업자가 기존 대화 없이도 FEEDiT 프로젝트의 현재 상태를 파악하고,
연관어 화면을 **추가 수집 없이 기존 RDS 데이터로 완성**할 수 있도록 만든 작업 메모다.

---

## 1. 사용자가 원하는 결과

- 트렌드 분석의 `연관어` 페이지를 실제 DB 데이터로 완성한다.
- 새로운 외부 크롤링이나 추가 수집을 먼저 제안하지 않는다.
- 현재 RDS에 이미 쌓인 사전·원문·언급 분석 데이터를 최대한 활용한다.
- 현재 프론트 디자인과 화면 구조는 유지한다.
- 데이터가 없거나 계산할 수 없으면 목업이나 난수로 채우지 않는다.
- 빈 상태, 연결 오류, 실제 0건을 서로 다른 상태로 표시한다.
- 찜, 살말 투표, 살말 사용자 댓글 기능은 다른 작업자가 담당한다.
  이 작업에서는 해당 API나 프론트 동작을 수정하지 않는다.

### 사용자가 추가로 확정한 최우선 방향

`term_assoc_daily`와 같은 메트릭 테이블이 제대로 채워지지 않았다는 이유로
연관어 화면을 멈추지 않는다.

긍부정이 집계 메트릭 대신 실제 댓글의 `TextTermMention`을 직접 읽듯이,
연관어도 DB 안에 이미 존재하는 공통 키를 먼저 직접 연결한다.

우선순위:

1. 같은 `TextDocument`에서 함께 언급된 사전 용어
2. 같은 `ProductSource`에 붙은 `ProductTerm`
3. 같은 `ContentItem.analysis_tags`에 들어 있는 사전 용어
4. 이미 적재된 `TermAssocDaily`가 정상이라면 그 결과
5. 요청 시 직접 계산이 너무 느릴 때만 기존 연관어 테이블에 결과를 materialize

외부 데이터를 더 모으거나 빈 메트릭을 억지로 채우는 것이 목표가 아니다.
현재 DB의 상품·콘텐츠·댓글·자막·리뷰가 공유하는 사전 용어 키를 이용해
빠르게 실제 결과를 만드는 것이 목표다.

사용자가 첨부한 화면의 핵심 구성은 다음과 같다.

- 검색창과 기준 용어
- 연관어 포화도 및 확산 단계
- 최다 연관어, 가장 뜨거운 축, 축당 평균 다양성 KPI
- 연관어 총량 추이
- 축별 비중
- 아이템·소재·컬러·핏·상황(TPO)별 순위 카드
- 연관어 클릭 시 지표와 근거 문장을 보여 주는 팝오버

첨부 화면은 디자인 목표다.
화면에 보이는 숫자와 문구를 DB 사실로 간주하거나 그대로 하드코딩하면 안 된다.

---

## 2. 프로젝트 한눈에 보기

FEEDiT는 패션 트렌드 데이터를 모아 사용자 화면에 보여 주는 모노레포다.

```text
feedit/
├─ backend/     Django, RDS 모델, 읽기 API, 관리자 화면
├─ frontend/    Vite SPA, Vercel 서버리스 API, 사용자 화면
├─ ChatBot/     별도 챗봇 서버
├─ docker/      Django·Redis·SSM 터널 실행 구성
├─ outputs/     프로젝트 산출물
└─ .env         비밀값. 절대 커밋하거나 출력하지 않는다.
```

트렌드 화면의 일반 데이터 흐름은 다음과 같다.

```text
브라우저
  → /api/assoc
  → 로컬: Vite proxy
  → 배포: Vercel function frontend/api/assoc.js
  → BACKEND_API_URL이 있으면 Django /api/assoc
  → Django ORM
  → AWS RDS
```

배포 환경에서 `BACKEND_API_URL`이 없을 때는 Vercel 함수가 PostgreSQL에 직접
접속하는 fallback을 사용한다. 다만 연관어 fallback은 현재 최신 스키마와 맞지 않는다.
자세한 내용은 아래 `7. 현재 발견된 문제`를 참고한다.

---

## 3. 지금까지의 주요 작업 이력

최근 main의 중요한 커밋은 다음과 같다.

| 커밋 | 내용 |
|---|---|
| `732786e` | 트렌드 대시보드를 RDS 실데이터와 Django API에 연결 |
| `bd50f31` | 긍부정 지표 화면 수정 |
| `f2c0e02` | 스타일 페이지 상품을 실제 상품 DB와 연결 |
| `8948f8e` | 찜한 키워드 화면을 실데이터에 연결 |
| `baf4a4f` | 살말 카드에 스타일 선택 추가 |
| `1aac86f` | 댓글 원문 기반 긍부정, 일반 로그인, 개인화 YouTube 추천 |
| `449d055` | 위 기능을 최신 main에 병합 |
| `cc57ae6` | 공유 DB에 이미 적용된 `0054` 마이그레이션을 Git과 동기화 |

작업 과정에서 긍부정은 집계표만 읽는 방식에서 다음 방식으로 개선됐다.

- 사전 용어: `TextTermMention`의 댓글 언급 분석행을 직접 집계
- 브랜드: 실제 브랜드 표기를 포함한 댓글 문맥만 집계
- 없는 데이터는 추정하지 않고 `empty`로 응답

금주의 리포트 추천 영상은 다음 데이터를 조합한다.

- 사용자가 선택한 스타일: `app.user_taste`
- 찜 상품의 사전 태그: `app.user_saved_item`, `commerce.product_term`
- YouTube 분석 태그: `content.content_item.analysis_tags`
- 반응: `content.content_snapshot`

찜 DB 쓰기, 살말 투표, 살말 사용자 댓글의 실제 화면/API 연결은 다른 작업자 담당이다.
로컬에 `codex/wip-user-interactions` 브랜치가 남아 있을 수 있으나,
그 브랜치를 main에 병합하거나 cherry-pick하지 않는다.

---

## 4. 일반 로그인 반영 여부

**일반 아이디 회원가입·로그인·로그아웃·프로필 저장은 main에 올라가 있다.**

관련 파일:

- `backend/apps/api/auth_views.py`
- `backend/apps/api/urls.py`
- `backend/config/settings.py`
- `frontend/account/static/js/account_api.js`
- `frontend/account/static/js/profile.js`
- `frontend/api/auth/[action].js`
- `frontend/tests/account_api.test.mjs`
- `frontend/tests/account_ui.test.mjs`

방식:

- 계정: Django `auth_user`
- FEEDiT 프로필: `app.app_user`
- 로그인 상태: Django 세션 쿠키
- 세션 쿠키: `HttpOnly`
- 쓰기 요청 보호: CSRF 토큰
- 비밀번호 및 세션 토큰을 `localStorage`에 저장하지 않음
- 새로고침 시 `GET /api/auth/me`로 로그인 상태 복원

아직 없는 것:

- Google OAuth 실제 연동
- 찜 버튼의 DB 쓰기 연동
- 살말 투표 및 사용자 댓글 API 연동

---

## 5. API 공통 규칙

### 5.1 응답 상태

Django 읽기 API는 대체로 다음 세 상태를 사용한다.

```json
{ "status": "ok", "data": {} }
```

```json
{ "status": "empty", "reason": "자료가 없는 구체적인 이유", "data": null }
```

```json
{ "status": "error", "reason": "연결 또는 서버 오류", "data": null }
```

규칙:

- `empty`: 연결과 질의는 성공했지만 적재 행 또는 해당 용어 데이터가 없음
- `error`: DB, 프록시, 인증 토큰, 서버 연결 등에 실패
- 실제 `0`: 측정된 값이 0인 경우이며 `empty`와 다름
- 없는 값을 `0`, 난수, 목업 데이터로 대체하지 않는다.

### 5.2 백엔드 주소와 프록시

- Django의 실제 경로에는 `/api/`가 붙는다.
- 로컬 Vite의 `/api/*`는 Django로 전달된다.
- 로컬 Django 포트는 루트 `.env`의 `API_PORT`를 따른다.
- 기본값은 `8000`이지만 충돌 시 `8001` 등이 될 수 있다.
- 프록시 설정을 바꾼 뒤에는 `npm run dev`를 다시 실행해야 한다.
- Vercel은 `BACKEND_API_URL`을 우선 사용한다.
- 서버 보호 토큰은 `BACKEND_API_TOKEN`과 서버의 `FEEDIT_API_TOKEN`이 같아야 한다.
- 비밀값은 문서, 코드, 터미널 출력에 남기지 않는다.

### 5.3 주요 사용자 API

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/api/health` | DB 표 행 수, 스키마 불일치, 지표 상태 |
| GET | `/api/terms` | 실제 지표가 존재하는 검색 용어 |
| GET | `/api/dictionary` | 사전 용어와 브랜드 검색 후보 |
| GET | `/api/facets` | 세부 검색 축 후보 |
| GET | `/api/trend?term=...&days=...` | 언급량·온도 등 시계열 |
| GET | `/api/sentiment?term=...&days=...&subject=brand` | 댓글 원문 기반 긍부정 |
| GET | `/api/assoc?term=...&limit=...&days=...` | 연관어와 추이 |
| GET | `/api/discount?...` | 할인률 변화 |
| GET | `/api/resale?...` | 리세일 시세 지수 |
| GET | `/api/lifecycle?...` | 수명주기 |
| GET | `/api/products?...` | 실제 상품 목록 |
| GET | `/api/price-history?...` | 상품 가격 이력 |

인증 API:

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/api/auth/me` | 세션 및 현재 사용자, CSRF 토큰 |
| POST | `/api/auth/signup` | 일반 회원가입 |
| POST | `/api/auth/login` | 일반 로그인 |
| POST | `/api/auth/logout` | 로그아웃 |
| POST | `/api/auth/profile` | 프로필 및 선호 스타일 저장 |
| GET | `/api/auth/weekly-videos` | 사용자 취향 기반 추천 영상 |

---

## 6. 연관어 API 현재 명세

### 6.1 요청

```http
GET /api/assoc?term=발레코어&limit=60&days=120
```

| 파라미터 | 기본값 | 범위 | 설명 |
|---|---:|---:|---|
| `term` | 없음 | 필수 | 표준명, 정규화명 또는 별칭 |
| `limit` | 60 | 5~200 | 최신 기준일의 최대 연관어 수 |
| `days` | 120 | 7~730 | 추이 이력 조회 기간 |

용어 해석 순서:

1. `dictionary.dictionary_term.canonical_name`
2. `normalized_name`
3. `dictionary.term_alias`
4. 사전에 연결된 브랜드명

### 6.2 성공 응답

현재 Django API 응답의 핵심 형태:

```json
{
  "status": "ok",
  "data": {
    "term": "발레코어",
    "as_of": "2026-09-01",
    "previous": "2026-08-25",
    "metric_version": "feedit-l2-v1",
    "items": [
      {
        "term": "새틴",
        "facet": "MATERIAL",
        "facet_ko": "소재",
        "cooccurrence": 9,
        "lift": 2.31,
        "pmi": 1.21,
        "percentile": 97.5,
        "rank": 1,
        "change": 2,
        "evidence": [
          { "tag": "YouTube", "text": "실제 저장된 언급 문맥" }
        ]
      }
    ],
    "history": [
      { "date": "2026-08-25", "count": 16, "cooc": 55 }
    ]
  }
}
```

`change` 의미:

- 양수: 이전 기준일보다 순위 상승
- 음수: 순위 하락
- `0`: 순위 유지
- `"new"`: 이전 기준일에 없었던 신규 연관어
- `null`: 비교 기준이 없음

### 6.3 읽는 DB 표

`analysis.term_assoc_daily`의 Django 모델은 `TermAssocDaily`다.

주요 컬럼:

- `source_term_id`
- `target_term_id`
- `metric_date`
- `cooccurrence_count`
- `lift`
- `pmi`
- `association_percentile`
- `association_rank`
- `is_new`
- `metric_version`
- `metrics` JSON

근거 문장은 별도 수집하지 않는다.
이미 적재된 `analysis.text_term_mention`에서 같은 문서 안에 기준 용어와 대상 용어가
함께 존재하는 행을 찾아 `mention_text`를 최대 2개 제공한다.

### 6.4 프론트 연결

관련 파일:

- `frontend/trend/static/js/dispatch.js`
- `frontend/trend/static/js/live_data.js`
- `frontend/trend/static/js/assoc_popover.js`
- `frontend/trend/static/js/chart_engine.js`
- `frontend/trend/static/js/render_helpers.js`
- `frontend/trend/static/css/`
- `frontend/api/assoc.js`

현재 화면은 이미 다음을 렌더링한다.

- 포화도: 최대 50개를 기준으로 `items.length / 50`
- 확산 단계: 연관어 개수 구간으로 4단계 표시
- KPI: 최상위 연관어, 동시 언급 합이 가장 큰 축, 축당 다양성
- 추이: API `history[].count`
- 축별 카드: 축당 최대 10개
- 팝오버: lift, PMI, 동시 언급 수, 실제 `evidence`

프론트는 `primeUrl()`로 URL 단위 캐시를 사용한다.

- `ok`, `empty`: 5분 캐시
- `error`: 15초 캐시
- 사용자가 다시 조회하면 `force:true`로 재요청

---

## 7. 현재 발견된 문제

### 7.0 메트릭 비의존 fast path

작업 브랜치 `feat/assoc-existing-data`에는 다음 1차 구현이 들어 있다.

- `TermAssocDaily`에 기준 용어 데이터가 있으면 기존 적재 지표를 우선 사용
- 없으면 다음 공통 키를 직접 집계
  - `TextTermMention.document_id`
  - `ProductTerm.product_source_id`
  - `ContentItem.analysis_tags` 안의 표준명·정규화명·검수 별칭
- 결과에 `method: "DIRECT_SHARED_KEYS"`를 표시
- 각 연관어에 `sources.documents`, `sources.products`, `sources.contents`를 표시
- lift, PMI, percentile, 시계열은 계산 근거가 없으므로 `null` 또는 빈 배열
- 프론트는 직접 연결 모드에서 확산 메트릭인 것처럼 표현하지 않고
  `직접 연결 탐색`, `공통 레코드`, `문서·상품·콘텐츠`로 출처를 밝힘

현재 구현 파일:

- `backend/apps/api/views.py`
- `frontend/trend/static/js/dispatch.js`

주의:

- 아직 실제 RDS 연결 검증 전이다.
- `ContentItem.analysis_tags`의 실제 JSON 변형을 샘플로 확인해야 한다.
- 요청 시 전체 콘텐츠 JSON을 읽으므로 데이터가 크게 늘면 materialize 또는 캐시가 필요하다.
- 서로 단위가 다른 문서·상품·콘텐츠 수의 합은 공식 연관 지표가 아니다.
  UI 정렬을 위한 공통 레코드 수이며, 원천별 수를 반드시 함께 표시한다.

### 7.1 연관어 적재 생산 코드가 저장소에 없다

현재 저장소 검색 결과 `TermAssocDaily`를 읽는 코드는 있지만,
기존 `TextDocument`와 `TextTermMention`에서 연관어 지표를 계산해
`TermAssocDaily`에 쓰는 명령 또는 작업 코드는 찾지 못했다.

따라서 표가 비어 있다면 외부 데이터를 새로 수집할 일이 아니라,
**이미 저장된 문서·언급 행을 집계해 연관어 표를 backfill하는 작업**이 필요하다.

### 7.2 DB 실제 상태는 다시 확인해야 한다

이 문서를 작성한 시점에는 로컬 SSM/RDS 연결이 timeout이었다.
따라서 현재 `analysis.term_assoc_daily`의 정확한 행 수를 확인했다고 쓰면 안 된다.

첨부된 현재 화면에는 다음 메시지가 보인다.

```text
연관어 표가 비어 있습니다. 적재가 아직 돌지 않았습니다.
```

다음 작업자는 터널을 복구한 뒤 반드시 실제 행 수와 적재 버전을 먼저 확인한다.

### 7.3 Vercel DB 직결 fallback의 컬럼명이 낡았다

`frontend/api/assoc.js`의 PostgreSQL 직접 조회는 현재 다음 컬럼을 읽는다.

- `association_score`
- `confidence`

하지만 최신 Django 모델과 `0049` 이후 스키마는 다음 컬럼을 사용한다.

- `lift`
- `pmi`
- `association_percentile`
- `association_rank`
- `is_new`

`BACKEND_API_URL`이 설정된 환경에서는 Django로 전달되어 문제가 숨겨진다.
직결 fallback 환경에서는 SQL 오류 또는 서로 다른 응답 계약이 생길 수 있다.

권장 처리:

- Django API를 단일 기준으로 삼는다.
- fallback을 유지해야 한다면 최신 컬럼과 Django 응답 계약으로 맞춘다.
- 두 경로에서 지표를 서로 다르게 계산하지 않는다.

### 7.4 화면의 해석 문구를 데이터 정의보다 앞서 확정하면 안 된다

현재 포화도와 `정체/완만/활발/폭발` 단계는 연관어 개수 기준이다.
이 기준이 공식 지표 정의인지 단순 UI 표현인지 확인해야 한다.

검증 전에는 lift나 PMI를 새 공식 점수로 합성하지 않는다.
화면 문구가 데이터가 보장하는 범위보다 강하면 문구를 완화한다.

### 7.5 축 명칭 확인

API의 축 한글 매핑은 현재 다음을 포함한다.

```text
브랜드, 스타일, 아이템, 소재, 디테일, 색, TPO, 인물
```

첨부 화면은 `아이템, 소재, 컬러, 핏, 상황(TPO)`을 사용한다.

- `COLOR → 컬러` 또는 `색`
- `DETAIL → 핏`으로 단순 치환 가능한지
- 실제 사전의 `term_type`과 속성 정의가 무엇인지

를 DB에서 먼저 확인한다. 이름만 맞추려고 서로 다른 개념을 합치지 않는다.

---

## 8. 다음 에이전트가 해야 할 일

### 8.1 시작 전 Git 절차

```powershell
git status --short
git switch main
git pull --ff-only origin main
git switch -c feat/assoc-realdata
```

main에 직접 작업하지 않는다.
다른 작업자의 변경을 되돌리거나 찜·살말 파일을 함께 수정하지 않는다.

### 8.2 1단계: 기존 DB 자산 조사

새 수집을 하기 전에 최소한 아래를 확인한다.

1. `analysis.term_assoc_daily`
   - 전체 행 수
   - 최신 `metric_date`
   - `metric_version`별 행 수
   - 기준 용어 수와 기준일 수
   - 각 지표 컬럼의 null 비율
2. `analysis.text_document`
   - 전체 문서 수
   - `document_type`별 문서 수
   - 플랫폼별 문서 수
   - 실제 게시일을 찾을 수 있는 메타데이터
3. `analysis.text_term_mention`
   - 전체 언급 행 수
   - 고유 문서 수와 고유 용어 수
   - 용어 유형별 행 수
   - 같은 문서에 둘 이상의 용어가 있는 문서 수
4. 사전
   - 활성 `DictionaryTerm` 수
   - `term_type`별 수
   - 별칭과 정규화명 연결 상태

행 수만 보지 말고 샘플 용어 몇 개를 실제로 조회한다.
`발레코어`, 핵심 스타일, 소재, 아이템, 브랜드를 섞어 확인한다.

### 8.3 2단계: 분기 결정

#### A. `term_assoc_daily`에 쓸 수 있는 데이터가 이미 있는 경우

- 다시 계산하거나 외부 데이터를 모으지 않는다.
- Django `/api/assoc`가 올바른 버전과 최신 기준일을 선택하는지 확인한다.
- API 응답을 실제 데이터로 검증한다.
- 프론트의 축·순위·근거 문장 매핑만 고친다.

#### B. 표가 비어 있지만 `text_term_mention`이 있는 경우

먼저 작업 브랜치의 `DIRECT_SHARED_KEYS` 경로를 실제 DB로 검증한다.
화면 요구를 충족하고 응답 시간이 충분하면 별도 backfill 없이 이 경로로 빠르게 마무리한다.

요청 시 계산이 느리거나 일별 추이·순위 변화가 반드시 필요할 때만 아래 materialize 작업을 한다.

- 기존 언급 행으로 idempotent backfill 명령을 만든다.
- 권장 위치는 Django management command다.
- 외부 API 또는 크롤러를 호출하지 않는다.
- 문서 단위로 중복 용어를 제거한 뒤 동시 출현을 계산한다.
- 한 문서에 같은 용어가 여러 번 나와도 동시 언급 문서 수는 한 번만 센다.
- 자기 자신 `(source_term == target_term)`은 제외한다.
- 기간, 문서 유형, 최소 동시 언급 수, 버전은 인자로 드러낸다.
- `--dry-run`과 처리 건수 출력을 제공한다.
- 재실행해도 중복 행이 생기지 않도록 upsert 또는 교체 범위를 명확히 한다.

Lift와 PMI는 프로젝트의 공식 지표 정의를 먼저 찾고 그대로 구현한다.
일반적인 공식을 임의로 공식 정의로 확정하지 않는다.

참고용 일반 정의는 다음과 같지만, 공식 설계와 대조하기 전에는 코드에 박지 않는다.

```text
N       = 기준 기간 전체 문서 수
n(a)    = 기준 용어 a가 등장한 문서 수
n(b)    = 대상 용어 b가 등장한 문서 수
n(a,b)  = a와 b가 함께 등장한 문서 수

lift = N × n(a,b) / (n(a) × n(b))
PMI  = log(N × n(a,b) / (n(a) × n(b)))
```

로그 밑, 집계 기간, 최소 support, 문서 유형 범위는 반드시 기존 설계와 맞춘다.

#### C. `text_term_mention`도 부족한 경우

- 즉시 새 수집으로 넘어가지 않는다.
- `TextDocument.body`, `ContentItem.analysis_tags`, `ProductTerm` 등 이미 적재된 대체 자산을 조사한다.
- 어떤 자산으로 어떤 품질까지 만들 수 있는지 먼저 보고한다.
- 사용자가 요청하지 않은 크롤링이나 외부 API 호출은 하지 않는다.

### 8.4 3단계: API 정리

- Django `/api/assoc`를 기준 계약으로 유지한다.
- 최신 기준일의 items와 기간 history를 함께 반환한다.
- `metric_version`이 섞이지 않게 한다.
- 순위 변화는 같은 버전의 바로 이전 기준일과 비교한다.
- 근거 문장은 실제 같은 문서의 `mention_text`만 사용한다.
- `frontend/api/assoc.js` fallback을 최신 스키마로 맞추거나 명시적으로 제거한다.
- `empty`와 `error`를 구분한다.

### 8.5 4단계: 프론트 검증

현재 디자인은 유지하면서 다음 상태를 모두 확인한다.

- 검색 전 빈 화면
- 로딩
- 실데이터 정상 표시
- 사전에 있지만 연관어가 없는 용어
- 사전에 없는 용어
- 연관어 표 전체가 빈 상태
- Django 404/500
- 프록시가 HTML을 돌려주는 잘못된 연결
- 근거 문장이 있는 항목과 없는 항목
- 이전 기준일이 없어 순위 변화가 없는 경우

화면 숫자는 API 값만 사용한다.
`frontend/trend/static/js/data.js`의 `ASSOC_BALLET`는 목업 데이터이므로
실데이터 경로에서 fallback으로 사용하지 않는다.

### 8.6 5단계: 테스트

최소 검증:

```powershell
cd backend
..\.venv\Scripts\python.exe manage.py check

cd ..\frontend
npm test
npm run build

cd ..
git diff --check
```

연관어 전용으로 추가할 테스트:

- 최신 스키마 컬럼으로 API 응답
- metric version 혼합 방지
- 최신/이전 기준일 순위 변화
- 신규 연관어 `change: "new"`
- 문서 단위 중복 제거
- 근거 문장이 실제 같은 문서에서만 선택됨
- 전체 표가 비었을 때의 `empty`
- 특정 용어만 없을 때의 `empty`
- Vercel 중계와 Django 응답 계약 일치
- 정상·빈 값·오류의 프론트 렌더

가짜 데이터 단위 테스트만 통과시키지 말고,
가능하면 실제 RDS의 대표 용어 몇 개로 읽기 검증을 추가한다.

---

## 9. 반드시 지킬 프로젝트 규칙

전체 원문은 `frontend/AGENTS.md`와 `frontend/docs/WORKFLOW.md`를 먼저 읽는다.

핵심 규칙:

1. 모르는 것을 아는 척하지 않는다.
2. 확인하지 않은 숫자를 화면에 표시하지 않는다.
3. 데이터가 없으면 없다고 말하고 목업으로 채우지 않는다.
4. 코드를 고치기 전에 현재 파일과 최신 main을 먼저 읽는다.
5. 다른 작업자의 미커밋 변경을 되돌리지 않는다.
6. 사용자 요청 없이 commit, push, 배포, 서버 재시작, 운영 DB 삭제를 하지 않는다.
7. 읽기 검사는 가능하지만 DB 쓰기 전에는 대상 행 수와 영향을 확인한다.
8. `.env`, 토큰, DB 비밀번호를 코드·문서·출력에 남기지 않는다.
9. 화면은 정상·빈 값·오류·로딩을 각각 검증한다.
10. 작업 후 `frontend/docs/DEVELOPLOG.md` 맨 아래에 새 기록을 추가한다.
11. 기존 로그를 수정하거나 지우지 않는다.
12. 새 수집보다 기존 DB 활용을 우선한다.

현재 `0054_votecomment_saved_constraints_seed_cards`는 공유 DB와 Git main에 모두 존재한다.
연관어 작업에서 이 마이그레이션을 수정하거나 번호를 재사용하지 않는다.

---

## 10. 자주 쓰는 파일 지도

| 목적 | 파일 |
|---|---|
| 연관어 Django API | `backend/apps/api/views.py`의 `assoc()` |
| API URL | `backend/apps/api/urls.py` |
| 연관어 모델 | `backend/apps/core/models/analysis.py`의 `TermAssocDaily` |
| 원문·언급 모델 | 같은 파일의 `TextDocument`, `TextTermMention` |
| Vercel 연관어 함수 | `frontend/api/assoc.js` |
| Vercel 백엔드 중계 | `frontend/api/_lib/db.js` |
| 연관어 화면 렌더 | `frontend/trend/static/js/dispatch.js` |
| API 캐시 | `frontend/trend/static/js/live_data.js` |
| 연관어 팝오버 | `frontend/trend/static/js/assoc_popover.js` |
| 차트 | `frontend/trend/static/js/chart_engine.js` |
| 검색 상태 | `frontend/trend/static/js/saved_keywords.js` |
| 목업 데이터 | `frontend/trend/static/js/data.js` |
| API 테스트 | `frontend/tests/api.test.mjs` |
| 화면 배선 테스트 | `frontend/tests/trend_wiring.test.mjs` |
| 빈 상태 테스트 | `frontend/tests/trend_empty.test.mjs` |
| 전체 작업 로그 | `frontend/docs/DEVELOPLOG.md` |

---

## 11. 완료 조건

아래가 모두 충족돼야 연관어 작업 완료로 본다.

- 추가 외부 수집 없이 기존 DB를 사용했다.
- 실제 데이터 출처와 집계 기간을 설명할 수 있다.
- 대표 검색어의 API 응답을 실제 RDS에서 확인했다.
- 최신 모델과 Vercel fallback의 응답 계약이 일치한다.
- 프론트의 모든 숫자가 API 또는 DB 근거를 가진다.
- 근거가 없는 단계·평가 문구를 사실처럼 표시하지 않는다.
- 빈 데이터와 서버 오류를 구분한다.
- 현재 디자인의 구조와 시각적 결을 유지한다.
- 찜·살말 담당자의 영역을 건드리지 않았다.
- 백엔드 검사, 프론트 테스트, 빌드, `git diff --check`가 통과했다.
- 변경 이유와 검증 결과를 `DEVELOPLOG.md`에 남겼다.

---

## 12. 다음 에이전트에게 주는 첫 실행 지시

다음 순서로 시작한다.

1. `frontend/AGENTS.md`와 이 문서를 끝까지 읽는다.
2. `git status`와 최신 main을 확인하고 기능 브랜치를 만든다.
3. SSM/RDS 연결 상태를 복구하거나 확인한다.
4. `term_assoc_daily`, `text_document`, `text_term_mention`의 실제 현황을 읽기 전용으로 조사한다.
5. 조사 결과를 먼저 보고한 뒤 A/B/C 분기 중 하나를 선택한다.
6. 새 수집 없이 기존 데이터로 가능한 범위를 최대화한다.
7. 구현 후 실제 데이터와 화면 상태를 함께 검증한다.

가장 먼저 코드를 쓰지 말고,
**현재 DB에 무엇이 얼마나 들어 있는지부터 확인하는 것이 이 작업의 시작점이다.**
