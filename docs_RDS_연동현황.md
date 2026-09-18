# FEEDiT AWS RDS 연동 현황

기준: 2026-09-14 KST, 운영 RDS `feedit` 실조회. 로컬 SQLite 데이터는 이관하지 않는다.

## 연결한 흐름

- 프론트 조회: 브라우저 → Vercel `/api/*` → EC2 Django → AWS RDS
- 회원: 가입·로그인·프로필·취향·탈퇴 → Django session/auth → `app.*`
- 챗봇: `FEEDIT_DATA_BACKEND=rds` → RDS 사전·지표·근거 조회
- 대화: 완료된 질문·답변·구조화 리포트 → `app.chat_session`, `app.chat_message`
- 살말: 카드·투표 → `app.vote_card`, `app.vote_ballot`; 목록도 RDS에서 다시 읽음
- 행동: 채팅·피드백·저장·투표 → `app.user_event`
- 상품·패싯: 실제 운영 스키마의 `product_source_id` 기준으로 조회 및 교집합 필터

운영 RDS의 최신 컬럼명을 사용한다. 예를 들어 온도는 `temp`가 아니라
`trend_temperature`, 순위는 `pct_rank`가 아니라 `percentile`, 상품 태그 연결은
`product_id`가 아니라 `product_source_id`다.

## 현재 RDS 데이터 때문에 아직 표시할 수 없는 것

| 기능 | 현재 상태 | 이유 / 필요한 데이터 |
| --- | --- | --- |
| 주간·월간 방향, 수명주기 | 판단 보류 | 지표 날짜가 2026-09-08 하루뿐이다. 최소 7/14/28일 관측이 필요하다. |
| 연관어 리포트 | 빈 상태 | `analysis.term_assoc_daily`가 0행이다. DB 팀의 연관어 배치 적재가 필요하다. |
| 살말 기존 게시물 | 빈 상태에서 시작 | `app.vote_card`가 0행이다. 이제 화면에서 만든 카드부터 RDS에 쌓인다. |
| 취향 유사 세그먼트·구매 만족도 | “측정 전” | 사용자·투표·구매 결과 데이터가 아직 0행이다. 기존 화면의 임의 계산은 제거했다. |
| 이미지가 포함된 살말 글쓰기 | 이미지 없이만 가능 | 브라우저의 `blob:` URL은 재접속하면 사라진다. S3 presigned upload API와 object URL 컬럼 연결이 필요하다. |
| Google 로그인/가입 | 준비 안내만 표시 | OAuth client ID/secret, callback URL, 계정 연결 정책이 없다. 가짜 Google 계정 생성은 중단했다. |
| 댓글 영구 저장 | 기존 화면 내 임시 상태 | 운영 스키마에 살말 댓글 테이블/API가 없다. 댓글 모델과 moderation 필드가 필요하다. |
| 일부 상품의 정규 상품 정보 | 원천명으로 폴백 | `commerce.product_source` 3,121개 중 575개가 `product_id`와 연결되지 않았다. |
| 일부 상품 가격 | “가격 기록 없음” | 3,121개 상품 소스 중 가격 스냅샷이 있는 소스는 2,757개다. 0원으로 대체하지 않는다. |

## 배포 시 필요한 값

- EC2 Django/ChatBot: `DB_HOST`, `DB_PORT=5432`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
- ChatBot: `FEEDIT_DATA_BACKEND=rds`, `FEEDIT_METRIC_VERSION=feedit-l2-v2`
- EC2 Django: `FEEDIT_API_TOKEN`, 안전한 `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`
- Vercel: `BACKEND_API_URL`, EC2와 동일한 `BACKEND_API_TOKEN`
- 보안 그룹: RDS 5432 인바운드는 EC2 보안 그룹만 허용하고 Vercel/공개 인터넷에는 열지 않는다.

배포 전 DB 팀의 migration 0051 상태를 기준으로 해야 한다. 이 저장소의 오래된 0029까지의
마이그레이션을 운영 RDS에 다시 실행해 되돌리면 안 된다.
