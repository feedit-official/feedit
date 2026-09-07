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
