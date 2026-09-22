> **과거 설계·인수인계 기록** — 본문은 작성 당시 상태를 보존합니다. 현재 구조·운영 방법은 [최신 문서](README.md)를 사용하세요. 과거 수치와 실행 예시는 현행 상태의 보증이 아닙니다. (구분일: 2026-09-22)

# RDS 텍스트 신호 파이프라인 설계·운영서

기준일: 2026-09-20 (Asia/Seoul)

## 1. 결론

YouTube 댓글과 커머스 리뷰를 서로 다른 일회성 스크립트로 다루지 않고, 아래 한 경로로 통합한다.

```text
플랫폼 원문
  → S3 원본 보관 + collection.raw_document
  → analysis.text_document (공통 문서 계약)
  → 1차 사전·신호 필터
  → 2차 LLM 구조화 분석
  → 원문 근거 위치 검증
  → analysis.text_term_mention
  → 일별 용어·연관어·플랫폼 품질 지표
  → 백엔드 API + 살말 챗봇
```

이 구조의 핵심은 원천 테이블의 키를 복사해서 새 규격에 억지로 맞추는 것이 아니라, `source_id + document_type + external_id`를 공통 외부키로 두고 YouTube는 `content_item_id`, 리뷰는 `product_source_id`로 원본 엔터티에 연결하는 것이다. 원천별 추가 값은 `analysis_metadata`에 보존한다.

## 2. 현재 RDS 확인 결과

운영 RDS를 읽기 전용으로 확인한 결과다. 행 수는 기준일에 각 테이블을 직접 `count(*)`한 값이다.

### 핵심 데이터 상태

| 항목 | 확인값 | 판단 |
|---|---:|---|
| YouTube 콘텐츠 | 1,124 | 댓글이 귀속될 영상 키가 존재함 |
| YouTube 댓글 문서 | 24,560 | 기존 분석 완료 데이터, 외부 ID 중복 없음 |
| 커머스 상품 리뷰 | 1,512 | 90개 `product_source_id`, 작성일 누락 없음 |
| 텍스트 용어 언급 | 52,116 | 기존 근거는 마이그레이션 시 `LEGACY`로 유지 |
| 용어 일별 지표 | 20,900 | 여러 metric version이 공존함 |
| 용어 연관 지표 | 22,111 | 새 통합 버전도 매일 함께 계산해야 챗봇 연관어가 비지 않음 |
| 활성 YouTube CrawlTarget | 0 | 타깃 스케줄에 의존하지 않고 등록된 `content_profile` 36개를 일일 갱신하도록 설계 |

현재 `text_document`에서 `(source_id, document_type, external_id)` 중복은 0건이라 새 부분 유니크 제약을 적용할 수 있다.

### 스키마별 전체 테이블 현황

| 스키마 | 테이블(대략 행 수) | 역할 |
|---|---|---|
| `collection` | `source` 7, `crawl_target` 524, `crawl_run` 1,253, `raw_document` 2,833, `task` 0 | 수집 대상·실행 이력·S3 원본 위치 |
| `content` | `content_profile` 36, `content_item` 1,124 | YouTube 채널과 영상의 안정 키 |
| `commerce` | `product` 2,546, `product_source` 40,222, `product_review` 1,512, `product_term` 28,000, `product_term_relation` 8,423 | 표준 상품, 플랫폼 상품, 리뷰, 상품 속성 연결 |
| `dictionary` | `dictionary_term` 634, `term_alias` 1,125, `term_candidate` 839, `term_candidate_observation` 18, `term_relation` 81, `brand` 3,716, `brand_source` 6,618, `brand_source_styles` 1,013, `brand_styles` 16, `category` 118, `category_source` 296, `style` 27, `item` 119, `material` 68, `detail` 195, `color` 82, `tpo` 56, `person` 0, `discovery_exclusion` 77 | 표준 용어·별칭·미등록 후보와 도메인 사전 |
| `analysis` | `text_document` 25,528, `text_term_mention` 52,116, `term_metric_daily` 20,900, `term_assoc_daily` 22,111, `term_search_metric_monthly` 542 | 공통 텍스트, 검증 근거, 트렌드·연관·검색 지표 |
| `app` | `app_user` 28, `chat_session` 40, `chat_message` 30, `user_event` 236, `user_saved_item` 40, `user_taste` 69, `notification` 21, `notification_setting` 0, `term_request` 0, `vote_card` 51, `vote_ballot` 275, `vote_comment` 174, `vote_feedback` 3, `vote_report` 2 | 사용자·챗봇 대화·행동·알림·투표 서비스 |

이번 마이그레이션 전에는 `analysis.pipeline_run`과 `analysis.platform_metric_daily`가 없다. 배포 시 생성된다.

## 3. 왜 이 테이블들이 필요한가

### 원본·수집 계층

- `collection.source`: 모든 외부 키의 플랫폼 구분자다. 서로 같은 문자열 ID가 있어도 플랫폼이 다르면 충돌하지 않는다.
- `collection.crawl_run`: 매일 무엇을 몇 건 수집했고 어디서 실패했는지 운영자가 확인한다.
- `collection.raw_document`: S3에 보관한 원본 JSON의 위치를 남긴다. 분석 결과가 잘못되면 원본부터 재현할 수 있다.
- `content.content_profile`: CrawlTarget 활성 상태와 무관하게 이미 등록된 YouTube 채널을 일일 갱신하는 기준이다.
- `content.content_item`: 댓글을 실제 영상에 연결하고 제목·URL·게시일·영상 태그를 분석 문맥으로 제공한다.
- `commerce.product_review`: 현재 RDS 리뷰 원문이다. 기존 테이블은 변경하지 않고 읽기 전용 모델로 연결한다.
- `commerce.product_source`: 리뷰를 실제 플랫폼 상품·브랜드·카테고리·상품 URL에 연결한다.

### 사전·분석 계층

- `dictionary.dictionary_term`, `dictionary.term_alias`: 1차 필터와 LLM 허용 표준어의 단일 원본이다.
- `dictionary.term_candidate`: 사전 밖 표현을 검토·승격하기 위한 목적이다. 이번 파이프라인은 우선 문서 JSONB에 후보를 보존하며, 자동 승격하지 않는다.
- `analysis.text_document`: YouTube 댓글과 상품 리뷰가 동일 분석기로 들어가기 위한 공통 계약이다.
- `analysis.text_term_mention`: 용어, 감성, 의도, 정확한 근거 문장과 문자 위치를 저장하는 Evidence Layer다.
- `analysis.term_metric_daily`: 소스별 및 전체 용어의 언급량, 백분위, 7/28일 추이, 온도, 감성, 구매의도 지표다.
- `analysis.term_assoc_daily`: 같은 문서에서 함께 검증된 용어의 lift/PMI/순위를 저장한다. 챗봇의 “같이 뜨는 소재/아이템” 답변에 필요하다.
- `analysis.platform_metric_daily`(신규): 플랫폼별 분석 커버리지, 유효 근거율, 감성 및 구매 신호를 감시한다. 데이터가 들어오지만 분석이 멈춘 상태를 찾는다.
- `analysis.pipeline_run`(신규): 모델·프롬프트·파이프라인 버전, 처리/실패 수, 토큰과 추정 비용을 실행 단위로 남긴다.

### 서비스 계층

- `app.chat_session`, `app.chat_message`: 챗봇 대화 상태와 메시지 기록이다.
- `app.user_taste`, `app.user_event`, `app.user_saved_item`: 트렌드 신호와 개인 취향·행동을 결합할 때 사용한다.
- `app.term_request`: 챗봇 사용자가 요청했지만 사전에 없는 용어를 운영 검토로 보낼 수 있다.

## 4. 유연한 키 연결 규칙

| 원천 | 공통 외부키 | 강한 FK | 원천 값 보존 |
|---|---|---|---|
| YouTube 댓글 | `YOUTUBE + COMMENT + comment_id` | `content_item_id` | 작성자, 채널 ID, 좋아요, 대댓글/부모 ID, video ID |
| 커머스 리뷰 | `source_id + REVIEW + source_review_id` | `product_source_id` | 평점, 옵션, 성별/키/몸무게, 설문, 리뷰 유형 |

`external_id`가 비어 있지 않을 때만 `(source, document_type, external_id)`를 유니크하게 만든다. 원문 본문 SHA-256인 `source_payload_hash`가 달라진 경우에만 `PENDING`으로 돌려 LLM을 다시 호출한다. 상품·영상 키값이 바뀌지 않는 한 원천 컬럼이 추가돼도 JSONB 메타데이터로 먼저 수용할 수 있다.

### 이번 마이그레이션의 정확한 스키마 변경

| 테이블 | 추가/생성 필드 | 제약·인덱스 |
|---|---|---|
| `analysis.text_document` | `product_source_id`, `analysis_run_id`, `source_published_at`, `source_payload_hash(64)`, `analysis_version(64)` | 외부키 부분 유니크, 상품/문서유형 및 소스/버전/상태 인덱스 |
| `analysis.text_term_mention` | `evidence_start`, `evidence_end`, `evidence_status`, `analysis_version(64)`; `mention_role`에 `COMMENT`, `REVIEW` 추가 | 근거 위치는 둘 다 NULL 또는 `end > start` |
| `analysis.pipeline_run` | `source_id`, `run_date`, pipeline/prompt/model version, status, 시작/종료, 입력/분석/생략/실패 수, 토큰 3종, 추정 비용, metrics, error_message | 날짜/상태 인덱스 |
| `analysis.platform_metric_daily` | `source_id`, `metric_date`, 문서/분석/keep/mention/candidate 수, 커버리지·근거유효·긍정·부정·구매의도 비율, version, metrics | `(source_id, metric_date, metric_version)` 유니크 |

`commerce.product_review`는 이미 운영 RDS에 있으므로 새로 만들지 않는다. Django에는 `managed=False` 읽기 모델만 추가해 외부 적재 소유권을 그대로 유지한다.

## 5. 일일 파이프라인 실행 순서

매일 04:10 KST에 Celery Beat가 `core.refresh_text_signals_daily`를 실행한다.

1. `content_profile`의 활성 YouTube 채널을 최대 50개 읽는다.
2. 채널별 최근 영상 10개를 갱신하고 원본 응답을 S3 및 `raw_document`에 남긴다.
3. 최근 180일 영상 중 최신 100개의 댓글을 최신순으로 영상당 최대 100개 수집한다.
4. 댓글을 `text_document(COMMENT)`에 idempotent upsert한다.
5. `commerce.product_review` 원문을 `text_document(REVIEW)`로 동기화한다.
6. 댓글은 사전 용어 또는 질문·구매·평가 신호가 있을 때만 LLM으로 보낸다. 리뷰는 상품 평가 원문이므로 전부 분석한다.
7. LLM 구조화 출력의 표준 용어, 대상, 의도, 감성, 원문 인용, 문자 시작/끝을 검증한다.
8. 검증된 언급만 `text_term_mention`에 저장하고 문서 메타데이터에 후보와 판정 근거를 남긴다.
9. 최근 35일의 `term_metric_daily`, `term_assoc_daily`, `platform_metric_daily`를 같은 버전으로 다시 계산한다.
10. 백엔드와 챗봇은 `FEEDIT_METRIC_VERSION=feedit-unified-text-v1`을 읽는다.

환경변수로 채널·영상·댓글 수와 분석 문서 상한을 조절할 수 있다. `FEEDIT_TEXT_DAILY_ANALYSIS_LIMIT=0`은 당일 대기 문서를 전부 처리한다.

## 6. 잘못된 짧은 span 문제의 해결

기존 방식은 LLM이 `span="경량패딩"`처럼 단어만 출력해도 “원문에 포함된다”는 조건을 통과했다. 이후 별도 복원 스크립트가 같은 단어의 여러 위치 중 평가 표현이 있는 긴 문장을 골라 붙였기 때문에, 드물게 LLM이 의도한 언급과 다른 위치를 고를 수 있었다.

새 방식은 다음 계약을 한 번에 강제한다.

1. LLM은 `surface`, `evidence_quote`, `char_start`, `char_end`를 모두 반환한다.
2. 서버는 `body[char_start:char_end] == evidence_quote`를 먼저 확인한다.
3. 위치가 틀리면 정확히 일치하는 인용문을 찾고, 그래도 없으면 정확한 `surface` 위치만 사용한다.
4. 단어 수준이거나 평가 맥락이 없을 때는 **그 동일 위치가 들어 있는 문장만** 확장한다.
5. 원문에 없는 표면형, 지어낸 문장, 표면형이 빠진 인용은 `INVALID`로 폐기한다.
6. `evidence_start < evidence_end` 또는 둘 다 NULL이어야 한다는 DB 제약도 추가한다.

즉 `span_repair.py`는 기존 데이터 응급 복원 참고자료로만 남고, 신규 데이터의 정상 흐름에는 필요하지 않다.

## 7. 감성과 의도 계산 규칙

- 감성은 용어별 `POS=1`, `NEU=0.5`, `NEG=0`으로 저장한다.
- “예쁘다”가 크리에이터를 향하면 상품 신호로 세지 않고 `target=CREATOR`로 구분한다.
- “비싸서 못 사겠다”, “품절이라 아쉽다”는 부정 감성과 구매 수요가 동시에 존재할 수 있다.
- 질문은 기본 중립이며 `QUESTION`, 실제 구매 언급은 `PURCHASE`, 사용 후기는 `EXPERIENCE`로 분리한다.
- 영상 태그와 일치하는 용어는 `attributed=true`로 표시해 영상 맥락과 댓글에서 새로 나온 표현을 구분한다.
- 사전 밖 표현은 자동으로 표준 용어가 되지 않고 후보로 남긴다.

## 8. 배포 및 최초 적용

### 필수 환경변수

```dotenv
OPENAI_API_KEY=...                # 챗봇 전용
FEEDIT_TEXT_OPENAI_API_KEY=...    # 리뷰·댓글 분석 전용 (2026-09-20 분리 — 챗봇 키로 대신하지 않는다)
YOUTUBE_API_KEY=...
AWS_STORAGE_BUCKET_NAME=...
AWS_REGION=ap-northeast-2
FEEDIT_METRIC_VERSION=feedit-unified-text-v1
FEEDIT_TEXT_LLM_MODEL=gpt-5.6-luna
FEEDIT_TEXT_LLM_EFFORT=low
FEEDIT_TEXT_DAILY_ANALYSIS_LIMIT=0
```

### 서버 반영

```bash
docker compose -f docker/compose.prod.yml build web celery-worker celery-beat chatbot
docker compose -f docker/compose.prod.yml up -d web celery-worker celery-beat chatbot
```

`web` 시작 명령이 `python manage.py migrate --noinput`을 먼저 실행한다. 마이그레이션만 미리 확인하려면 다음을 실행한다.

```bash
docker compose -f docker/compose.prod.yml run --rm web python manage.py migrate --plan
```

### 데이터 변경 없는 사전 확인

마이그레이션 적용 뒤 다음 명령은 대상 건수만 보여 주고 LLM이나 DB 적재를 실행하지 않는다.

```bash
docker compose -f docker/compose.prod.yml exec web python manage.py run_text_signal_pipeline --plan
```

### 최초 수동 실행

신규 리뷰 동기화, 대기 문서 분석, 최근 90일 지표 재계산:

```bash
docker compose -f docker/compose.prod.yml exec web \
  python manage.py run_text_signal_pipeline --collect-youtube --metric-days 90
```

기존 24,560개 YouTube 댓글을 새 프롬프트로 재판정하는 것은 비용이 발생하므로 자동으로 하지 않는다. 필요하면 다음 명령을 반복해 500건씩 단계적으로 전환한다. 처리된 문서는 새 버전으로 표시되므로 다음 실행에서는 남은 문서로 넘어간다.

```bash
docker compose -f docker/compose.prod.yml exec web \
  python manage.py run_text_signal_pipeline --include-stale --limit 500 --no-metrics
```

마지막 배치 후 `--no-metrics` 없이 한 번 실행해 통합 지표를 갱신한다.

## 9. 운영 확인 기준

- `analysis.pipeline_run.status`: `SUCCESS`가 기본, `PARTIAL`이면 `error_message`와 실패 수 확인
- `analysis.platform_metric_daily.analysis_coverage_rate`: 급락 시 워커·LLM 키·스키마 상태 확인
- `evidence_valid_rate`: 프롬프트나 모델 변경 후 급락하면 배포 중지
- `candidate_count`: 급증하면 신조어이거나 사전 누락 가능성 검토
- Celery Beat는 1개만 실행한다. 여러 개면 일일 작업이 중복 예약될 수 있다.
- 같은 원문은 외부키와 해시로 중복/재분석을 막지만, S3 원본은 실행별 감사 기록으로 유지한다.

## 10. 변경된 주요 코드

- `backend/collection/youtube/daily.py`: 채널 → 영상 → 댓글 일일 수집
- `backend/analysis/text_signals/prompts.py`: 구조화 LLM 계약
- `backend/analysis/text_signals/evidence.py`: 근거 위치 검증 및 안전한 문장 확장
- `backend/analysis/text_signals/service.py`: 리뷰 동기화와 공통 분석/적재
- `backend/analysis/text_signals/metrics.py`: 통합 트렌드·연관·품질 지표
- `backend/apps/core/migrations/0062_productreview_platformmetricdaily_and_more.py`: 신규 테이블·컬럼·제약
- `backend/apps/core/tasks.py`, `backend/config/celery.py`: 매일 04:10 자동 실행
- `docker/compose.prod.yml`: 운영 Celery worker/beat 서비스
