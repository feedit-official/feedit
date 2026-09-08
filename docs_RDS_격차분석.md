# RDS 표 격차 분석 — 무엇이 더 필요한가

2026-09-07. `feedit-official/feedit` 통합 저장소 기준.
근거는 전부 이 저장소의 코드다 — 추측이 아니라 파일을 열어 확인한 것만 적는다.

---

## 0. 세 줄 요약

**표는 잘 잡혀 있다. 38개 중 구조가 잘못된 건 거의 없다.**

문제는 두 가지다.

1. **분석 표 세 개(`analysis.*`)를 채우는 코드가 아무 데도 없다.**
   모델과 마이그레이션만 있고, 쓰는 곳이 0곳이다.
2. **지표를 담을 컬럼이 모자라다.** 특히 온도·모멘텀이 들어갈 자리가 없다.

---

## 1. 지금 있는 표 (38개)

```
analysis   term_metric_daily · term_assoc_daily · text_document
app        app_user · chat_session · chat_message · user_event
           user_saved_item · user_taste · vote_card · vote_ballot
collection crawl_run · crawl_target · raw_document · source
commerce   product · product_source · product_term
content    content_item · content_profile
dictionary brand · brand_source · category · category_alias · color · detail
           dictionary_term · item · mapping_candidate · material · style
           term_alias · term_candidate · term_relation · tpo
snapshot   content_snapshot · product_source_snapshot · resale_snapshot
```

사전(dictionary) 쪽은 아주 촘촘하다.
`term_candidate` 에 `embedding` · `similarity_score` · `decision_reason` 까지 있어
등록 요청과 승인 흐름이 그대로 붙는다. 여기는 손댈 게 없다.

---

## 2. ★ 제일 큰 문제 — 분석 표를 채우는 코드가 없다

```
$ grep -rn "TermMetricDaily" --include=*.py backend/
  backend/apps/core/models/analysis.py          ← 정의
  backend/apps/core/migrations/0008_….py        ← 표 만들기
  (그 외 0곳)
```

`TermAssocDaily` · `TextDocument` 도 똑같다.

**즉 "연동이 안 된 것"이 아니라 "보내는 코드가 아직 없는 것"이다.**
크롤러 쪽 `rds_sync` 가 쓰는 표도 여덟 개뿐이고 `analysis.*` 는 거기 없다.

한편 크롤러 SQLite 에는 지표가 이미 쌓여 있다:

```
metric_term_daily            12,484행   용어 584개   2024-09-27 ~ 2026-09-04
metric_term_assoc_daily         538행
metric_term_sentiment_daily     499행
text_document                12,314행
```

**옮길 자료는 있다. 옮기는 길이 없다.**

---

## 3. 지표별 — 무엇이 모자란가

### ① 트렌드 온도 — 컬럼이 없다 ★

설계서 §1 이 요구하는 값과 표에 있는 칸이 어긋난다.

| 설계서가 쓰는 값 | `term_metric_daily` 에 | |
|---|---|---|
| `temp` (온도) | 없음 | ★ |
| `momentum` (가속) | 없음 | ★ |
| `ma7` · `ma28` | 없음 | ★ |
| `level` · `pct_rank` | 없음 | ★ |
| 언급량 | `mention_count` | ✅ |
| 문서수·출처수 | `document_count` · `source_count` | ✅ |
| 감성 | `sentiment_avg` | ✅ |
| 증가율 | `growth_rate` | ✅ |
| — | `trend_score` (정의가 어디에도 없음) | ⚠ |

**정할 것:** `metrics` JSON 에 담을지, 컬럼을 더할지.
JSON 이 빠르지만 인덱스를 못 걸어서 "온도 높은 순 정렬"이 느려진다.
화면 첫 진입이 그 정렬이라면 컬럼으로 빼는 게 맞다.

### ①b 플랫폼별 온도 — 표가 없다 ★

설계서 §1 '플랫폼별 온도' 는 (용어 × 소스 × 날짜) 단위다.
지금은 `source_count` 라는 **개수 하나뿐**이라 소스별로 나눌 수가 없다.

> "무신사에서는 뜨는데 지그재그에선 아직" 같은 말을 못 한다.

필요: `analysis.term_source_metric_daily` (term, source, metric_date, …)

### ② 연관어 — 컬럼은 되고, 값이 없다

`cooccurrence_count` · `association_score` · `confidence` · `metrics` 로
설계서의 리프트(lift)까지 담을 수 있다. **표는 그대로 두면 된다.**
비어 있는 것만 문제다.

### ③ 구매의향 — 집계 표가 없다 ★

`text_document.intent_code` 는 **문서 한 건**의 라벨이다.
설계서 §3 이 화면에 띄우려는 건 **용어별·날짜별 지수**다.

지금 구조로 하려면 매번 12,314건을 훑어 집계해야 한다 — 화면이 느려진다.

필요: `analysis.term_sentiment_daily`
(term, metric_date, intent 별 건수, 구매의향 지수, 표본 수)

### ④ 구매 점수 — 재고 희소성만 빠졌다

`product_source_snapshot` 이 꽤 잘 돼 있다:
`list_price` · `sale_price` · `discount_rate` · `rank_position` · `rating` ·
`review_count` · `stock_status` · `platform_metrics(JSON)`

설계서 §4 공식 중 못 채우는 건 하나다:

```
scarcity = 100 × (1 − 구매 가능 사이즈 수 / 전체 사이즈 수)
```

`stock_status` 는 품절/판매중 **한 글자**라 사이즈별 재고를 모른다.
`platform_metrics` JSON 에 사이즈별 재고를 넣으면 표를 안 늘려도 된다.

⚠ 그리고 **가격 이력이 짧다.** `Δdisc_14`(14일 전 대비)를 쓰려면
최소 14일치가 쌓여 있어야 하는데 아직 그만큼이 아니다.

### ⑤ 리세일 — 표는 훌륭하다. 비어 있을 뿐

`resale_snapshot` 에 `resale_index` · `resale_price_ratio` · `lowest_ask` ·
`highest_bid` · `last_trade_price` · `trade_volume` 까지 다 있다.
설계서 §5 를 그대로 담을 수 있다.

다만 §5 의 **'선행일수'**(소셜보다 며칠 먼저 움직였나)는 계산 결과를
저장할 자리가 없다. `market_metrics` JSON 에 넣으면 된다.

### ⑥ 수명주기 — 표가 통째로 없다 ★

설계서 §6 은 단계(도입·성장·성숙·쇠퇴)·잔존 기간·발주 판정·신뢰도를 말한다.
**이걸 담을 표가 하나도 없다.**

필요: `analysis.term_lifecycle`
(term, 단계, 잔존주수, 신뢰도, 피팅 파라미터, 판정일)

---

## 4. 앱 기능별 — 무엇이 모자란가

### 살!말? — 지수를 담을 자리가 없다 ★

`vote_card` · `vote_ballot` 로 **투표**는 된다.
그런데 살말 챗봇이 "살" / "말" 을 **왜 그렇게 봤는지**를 남길 곳이 없다.

`vote_card` 에는 title · description · image_url · tags · status 뿐이라,
그때의 할인율·온도·리세일 지수가 안 남는다.
나중에 "그때 왜 살이라고 했지?"를 되짚을 수가 없다.

필요: `vote_card` 에 `metrics_snapshot` (JSON) 한 칸
— 판단 시점의 지표를 굳혀 둔다. 가격은 매일 바뀌므로 굳히지 않으면 근거가 사라진다.

### 챗봇 — 세 칸이 없다

| 필요 | 지금 | |
|---|---|---|
| 일반 / 살말 **모드** 구분 | `chat_session` 에 없음 | ★ |
| 답의 **근거**(어느 지표를 인용했나) | `chat_message` 에 없음 | ★ |
| 질문 **의도 코드** | `chat_message` 에 없음 | |
| 사용량 카운터(플랜별 제한) | 표 없음 | |

`chat_session.context` · `chat_message.metadata` 가 JSON 이라
급하면 거기 넣을 수 있다. 다만 "근거 없는 답을 걸러내기"를 하려면
`cited` 는 조회가 되어야 하므로 칸으로 빼는 게 낫다.

### 플랜(FREE/PRO) — 없다

`app_user` 에 `plan` 이 없다.
프론트는 이미 `window.FEEDIT_PLAN` 으로 화면을 갈아 끼우고 있어서
서버 쪽 값이 필요하다.

### 저장한 키워드 — 상품·콘텐츠만 저장된다 ★

`user_saved_item` 은 `product` 와 `content_item` 만 가리킨다.
그런데 트렌드 탭에 **'저장한 키워드'** 화면(`saved_keywords.js`)이 있다.
**용어(term)를 저장할 수가 없다.**

필요: `user_saved_item.term` FK 추가 (셋 중 하나만 채우는 형태)

### 주간 리포트 — 저장 표가 없다

`weekly_report.js` 가 화면에 있는데, 리포트를 담아 둘 표가 없다.
매번 다시 계산하면 느리고, "지난주에 뭐라고 했지"를 볼 수가 없다.

---

## 5. 백엔드 결합이 어려운가

**어렵지 않다. 다만 지금은 못 붙는다.** 이유가 셋인데 전부 코드가 아니라 배선 문제다.

### ① 공개 API 가 없다 ★

```
backend/apps/api/urls.py         0줄
backend/apps/api/views.py        3줄 (django 기본 껍데기)
backend/apps/api/serializers.py  0줄
backend/config/urls.py           admin · normalization 만 등록
```

**API 앱이 만들어져만 있고 비어 있다.** 라우팅에도 안 걸려 있다.
프론트가 부를 주소가 하나도 없다.

### ② RDS 가 사설이라 버셀이 못 들어간다 ★

`docker/compose.yml` 을 보면 구조가 이렇다:

```
web (Django) ──▶ ssm-tunnel 컨테이너 ──SSM──▶ RDS
```

RDS 는 밖에서 안 보이고 **SSM 굴로만** 열린다.
버셀 함수는 그 굴에 못 들어간다. 길은 둘이다:

- **RDS 를 공개로 연다** — 간단하지만 DB 가 인터넷에 노출된다. DB 팀 결정.
- **Django 를 공개로 올리고 버셀이 그걸 부른다** (권장)
  RDS 를 열지 않아도 되고, 굴은 서버 안에서만 쓴다.

### ③ Django 가 개발 서버로 뜬다

```yaml
command: python manage.py runserver 0.0.0.0:8000
```

`runserver` 는 개발용이다. 상시 공개 서비스로 쓰면 안 된다.
gunicorn 같은 것으로 바꾸고 앞에 nginx 를 두어야 한다.

### 붙이는 순서

```
1. apps/api 에 읽기 전용 엔드포인트를 만든다   (하루)
2. config/urls.py 에 등록한다                  (한 줄)
3. gunicorn 으로 바꾸고 도메인·HTTPS 를 붙인다
4. 버셀 환경변수에 그 주소를 넣는다            (CHAT_BACKEND_URL / API_BASE)
```

프론트 쪽은 이미 준비돼 있다.
`frontend/api/` 의 버셀 함수들이 같은 도메인 `/api/...` 를 받아
뒤로 넘기게 돼 있고, 값이 없으면 **'측정 불가'** 를 그린다.
숫자를 지어내지 않는다.

---

## 6. 정리 — 우선순위

| 순위 | 할 일 | 왜 |
|---|---|---|
| 1 | **SQLite → `analysis.*` 적재 경로** | 이게 없으면 트렌드 탭이 통째로 빈다 |
| 2 | **온도·모멘텀 담을 자리 정하기** (JSON vs 컬럼) | 1번을 만들기 전에 정해야 한다 |
| 3 | **`apps/api` 읽기 전용 엔드포인트** | 프론트가 부를 주소가 없다 |
| 4 | `user_saved_item.term` 추가 | 저장한 키워드 화면이 못 돈다 |
| 5 | `vote_card.metrics_snapshot` 추가 | 살말 판단 근거가 사라진다 |
| 6 | `analysis.term_sentiment_daily` | 구매의향을 매번 12,314건 훑을 순 없다 |
| 7 | `analysis.term_source_metric_daily` | 플랫폼별 온도 |
| 8 | `analysis.term_lifecycle` | 수명주기 |
| 9 | `chat_session.mode` · `chat_message.cited` | 살말 모드·근거 표시 |
| 10 | `app_user.plan` | 요금제 화면 |

1~3번까지만 되면 **트렌드·연관어·상품이 실데이터로 뜬다.**
4번 이후는 화면을 하나씩 늘리는 일이다.

---

## 확인 방법

버셀에 `DATABASE_URL` 을 넣고 배포한 뒤 `/api/health` 를 열면
표별 행 수와 지표 컬럼 유무가 그대로 나온다.
이 문서의 판단이 아직 맞는지 그때그때 확인할 수 있다.

---

# 부록 — 2026-09-07 코드로 해결한 것

## 온도·모멘텀은 **컬럼**으로 뺐다

### 왜 JSON 이 아닌가

이 값들은 **정렬과 범위 조회에 쓰인다.**

```
화면 첫 진입      ORDER BY temp DESC LIMIT 20
구간 필터         WHERE temp >= 75            (과열)
챗봇 "요즘 뜨는"   ORDER BY momentum DESC
```

JSONB 도 표현식 인덱스로 정렬은 된다. 다만 두 가지가 걸린다.

- 질의가 인덱스 표현식과 **한 글자라도 다르면** 조용히 전체 훑기로 떨어진다.
  느려지는데 에러가 안 나서 알아채기 어렵다.
- JSON 안 숫자는 타입이 없다. Django ORM 이 문자열로 비교하면
  **"9" > "10"** 이 참이 된다. 값이 틀려도 에러가 안 난다.

그래서 **자주 정렬·필터하는 여섯 개만 컬럼**으로 빼고,
나머지(`raw_count`·`log_value`·`share_pct`·실험값)는 `metrics` JSON 에 둔다.

| 컬럼 | 자리수 | 범위(크롤러 실측) |
|---|---|---|
| `temp` | 5,2 | 0 ~ 100 |
| `momentum` | 8,4 | 0.247 ~ 99.99999 |
| `level` | 5,2 | 0 ~ 100 |
| `ma7` · `ma28` | 14,4 | 0 ~ 64 |
| `pct_rank` | 6,3 | **0 ~ 100** ← 이름과 달리 0~1 이 아니다 |

### ★ 실데이터로 돌려서 잡은 것 두 가지

**(1) `pct_rank` 는 0~1 이 아니라 0~100 이다.**
이름만 보고 `max_digits=6, decimal_places=5`(최대 9.99999)로 뒀더니
12,484행 중 **7,171행(57%)이 numeric overflow** 로 죽었다.
`6,3` 으로 고쳤다. 실제로 넣어 보지 않았으면 적재 당일에 터졌을 자리다.

**(2) unique 제약이 플랫폼별 행을 막고 있었다.**
예전 제약은 `(term, metric_date)` 뿐이었다.
크롤러는 (용어 × 플랫폼 × 날짜)로 계산하므로 하루에 한 용어가 8행이다
(`__all__` 합산 + musinsa·youtube·naver·zigzag·ably·kream·musinsa_used).

```
전체 12,484행 → (용어,날짜)로만 묶으면 5,209행
즉 7,275행(58%)이 들어가지 못한다
```

`(term, source, metric_date, metric_version)` 로 바꾸고
`nulls_distinct=False` 를 걸었다 — 합산 행(source=NULL)도 하루에 하나여야 한다.

### 함께 더한 것

- **`source` FK** (NULL = 전 플랫폼 합산) → 플랫폼별 온도가 가능해진다
- **`metric_version`** → 공식이 바뀌어도 옛 값과 안 섞인다.
  이게 없으면 그래프가 어느 날 튀는데 원인을 못 찾는다
- 인덱스 `(metric_date, -temp)` · `(metric_date, -momentum)` · `(source, metric_date)`

**파일:** `backend/apps/core/models/analysis.py`
**마이그레이션:** `0029_remove_termmetricdaily_uq_term_metric_day_and_more.py`

---

## 비어 있던 `apps/api` 를 채웠다

```
GET /api/health     붙었나 · 표별 행 수 · 온도가 실제로 채워졌나
GET /api/terms      지표가 있는 용어 목록
GET /api/trend      ?term= &days= &source=   (source 없으면 합산)
GET /api/assoc      ?term= &limit=
GET /api/products   ?q= &brand= &limit=
```

`config/urls.py` 에 `path("api/", include("apps.api.urls"))` 로 걸었다.

전부 **GET 이고 조회만** 한다. 쓰는 길은 두지 않았다.
**지표를 계산하지 않는다** — 정의의 원본은 설계서이고 계산은 수집·정제 쪽이다.
여기서 다시 계산하면 화면과 챗봇이 다른 숫자를 말하게 된다.

값이 없으면 지어내지 않는다:

```json
{"status":"empty","reason":"‘엄브로’ 은 사전에 있지만 최근 90일 안에 측정된 지표가 없습니다.","known":true}
```

행은 있는데 온도만 비면 그것도 알려 준다:

```json
{"status":"ok","unavailable":{"fields":["pct_rank"],"reason":"이 값들이 아직 비어 있습니다 …"}}
```

---

## 프론트는 RDS 대신 이 API 를 본다

```
브라우저 → 버셀 함수 → BACKEND_API_URL(Django) → RDS
```

**RDS 를 인터넷에 열지 않아도 된다.**
버셀 환경변수에 `BACKEND_API_URL` 만 넣으면 그쪽으로 넘어가고,
없으면 예전처럼 `DATABASE_URL` 로 직결한다(RDS 를 공개로 연 경우).

---

## 검증

```bash
# 백엔드 — 크롤러 실데이터 243행을 넣고 API 를 실제로 호출
FEEDIT_CRAWLER_DB=…/feedit.db python3 backend/apps/api/tests.py   # 9가지

# 프론트 — 응답 계약 + 백엔드 경유
cd frontend && npm test                                            # 18가지 + 차트 6가지
```

`makemigrations --check` 로 모델과 마이그레이션이 어긋나지 않는 것도 확인했다.

⚠ **PostgreSQL 로는 못 돌려 봤다.** 작업 환경에 PG 를 못 깔아서
SQLite 로 마이그레이션과 API 를 돌렸다. SQLite 는 `nulls_distinct` 를
지원하지 않아 **그 제약 하나만 실제로 걸리는 걸 못 봤다.**
`manage.py migrate` 를 RDS 에 처음 돌릴 때 그 부분을 확인해 주면 좋겠다.

---

## 남은 것 (코드가 아니라 결정)

1. Django 를 `runserver` 말고 gunicorn 으로 올리고 도메인·HTTPS 붙이기
2. `user_saved_item.term` · `vote_card.metrics_snapshot` ·
   `chat_session.mode` · `chat_message.cited` · `app_user.plan`
3. `analysis.term_lifecycle` · `term_sentiment_daily` (새 표)

2·3번은 화면을 하나씩 늘릴 때 같이 하면 된다. 지금 급한 건 1번이다.

---

## nginx 는 안 써도 된다 — 대신 두 가지는 반드시 해야 한다

### 정정

앞에서 "gunicorn·whitenoise 둘 다 없다"고 적었는데 **틀렸다.**
`requirements.txt` 가 UTF-16 이라 grep 이 못 읽은 것이고,
**`gunicorn==26.2.0` 은 이미 들어 있다.** 없던 건 whitenoise 뿐이다.

### nginx 가 하던 일 중 우리에게 필요한 건 둘뿐이다

| nginx 가 하던 일 | 우리에게 | 어떻게 대신하나 |
|---|---|---|
| 정적 파일 서빙 | **필요** | **whitenoise** (Django 미들웨어 한 줄) |
| HTTPS 종료 | **필요** | **Caddy** (인증서 자동 발급·갱신) |
| 프론트 정적 파일 호스팅 | 불필요 | 프론트는 Vercel 에 있다 |
| 로드밸런싱 | 불필요 | 서버 한 대다 |
| 캐싱 | 불필요 | Vercel 이 앞에서 캐시한다 |

### ★ 정적 파일 — 실측으로 확인했다

`runserver` 는 정적 파일을 알아서 준다. **gunicorn 은 안 준다.**
그냥 바꾸면 admin CSS 가 통째로 깨진다.

```
gunicorn 단독
  /api/health                   200
  /admin/                       302
  /static/admin/css/base.css    404   ← admin 이 맨몸으로 뜬다

whitenoise 를 넣은 뒤
  /static/admin/css/base.css    200 · 22,120 bytes · text/css   ✅
```

미들웨어 한 줄이면 되므로 이것 때문에 nginx 를 세울 이유는 없다.
단 `collectstatic` 을 배포 때 한 번 돌려야 한다 — compose 명령에 넣어 뒀다.

### ★ HTTPS — 이건 진짜로 필요하다

지금 `feedit-official.duckdns.org` 는 **HTTP** 다.

당장 화면이 깨지지는 않는다. 브라우저 → Vercel 은 HTTPS 이고,
Vercel 함수 → Django 는 **서버끼리** 부르는 것이라 브라우저가 안 막는다.
(브라우저에서 Django 를 직접 불렀다면 mixed content 로 막혔을 것이다.)

그래도 해야 하는 이유:

- 인터넷 구간이 **평문**이다. 중간에서 읽고 바꿀 수 있다.
- 나중에 로그인·개인 취향·결제가 오가면 그때는 선택지가 없다.
- admin 로그인 비밀번호가 지금 평문으로 오간다.

### 추천 — nginx 대신 Caddy

nginx 도 되지만 인증서를 certbot 으로 따로 발급·갱신해야 한다.
**갱신이 조용히 실패하면 90일 뒤 사이트가 죽는다.** 그때 아무도 안 보고 있다.

Caddy 는 도메인만 적으면 Let's Encrypt 인증서를 자동으로 받고 자동으로 갱신한다.
설정이 파일 하나다. 팀에 인프라 전담이 없을수록 덜 틀린다.

### 넣어 둔 것

```
docker/Caddyfile           앞단 — HTTPS 종료 + web:8000 으로 넘김
docker/compose.prod.yml    배포용 (개발용 compose.yml 은 그대로 뒀다)
requirements.txt           whitenoise==6.8.2   (gunicorn 은 이미 있었다)
backend/config/settings.py WhiteNoise 미들웨어 · STORAGES ·
                           SECURE_PROXY_SSL_HEADER · CSRF_TRUSTED_ORIGINS
```

개발용 `compose.yml` 은 건드리지 않았다. 지금 작업 흐름은 그대로 돈다.

```bash
docker compose -f docker/compose.prod.yml up -d
```

배포용에서 달라지는 것:

- `runserver` → `gunicorn --workers 3 --timeout 60`
- **web 이 포트를 밖으로 안 연다.** Caddy 만 80·443 을 갖는다.
  gunicorn 을 인터넷에 그대로 노출하면 느린 연결(slowloris)에 약하다.
- `DJANGO_BEHIND_PROXY=true` — 앞단이 붙여 주는 `X-Forwarded-Proto` 를 믿는다.
  ⚠ **앞단이 있을 때만 켠다.** 없이 켜면 누구나 https 인 척 위조할 수 있다.

### 남은 확인

Caddy 가 인증서를 받으려면 **80·443 이 밖에서 열려 있어야 한다**
(Let's Encrypt 가 그 도메인으로 되돌아와 확인한다).
EC2 보안 그룹에 80·443 인바운드가 있는지 확인이 필요하다.

docker 가 작업 환경에 없어 **compose 와 Caddyfile 을 실제로 띄워 보지는 못했다.**
YAML 구조와 Caddyfile 괄호·지시어는 확인했고, gunicorn+whitenoise 는
실제로 띄워서 위 응답 코드를 받아 본 것이다.
