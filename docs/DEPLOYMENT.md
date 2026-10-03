# 배포와 운영

기준일: 2026-09-22 · 저장소 설정 기준. 명령은 운영 작업 참고용이며 이번 문서 정리에서 배포를 수행하지 않았습니다.

## Vercel

| 항목 | 값 |
| --- | --- |
| Root Directory | `frontend` |
| Framework | Vite |
| Build | `npm run build` |
| Output | `dist` |
| Install | 현재 `vercel.json`의 `npm install` |
| 로컬 재현 설치 | 잠금 파일을 사용하는 `npm ci` |

`frontend/vercel.json`의 rewrite와 함수 제한시간 설정을 함께 유지합니다. Node 운영 버전은 Vercel 프로젝트 설정에서 별도로 확인합니다. `.nvmrc`만으로 운영 런타임을 확정하지 않습니다.

| Vercel 변수 | 용도 |
| --- | --- |
| `BACKEND_API_URL` | Django의 `/api`까지 포함한 기본 주소 |
| `BACKEND_API_TOKEN` | Django `FEEDIT_API_TOKEN`과 대응 |
| `CHAT_BACKEND_URL` | 챗봇 서버의 기본 origin; `/v1/chat`을 붙이지 않음 |
| `CHAT_BACKEND_TOKEN` | 챗봇 `FEEDIT_CHAT_TOKEN`과 대응; 베타 정책 확인 |
| `DATABASE_URL` 또는 `PG*` | 해당 함수의 직접 DB 조회 폴백을 사용하는 경우 |

Production과 Preview의 환경값·접근 범위를 구분합니다. 브라우저 번들에 비밀값을 넣지 않습니다. 플랫폼 데이터에 접근하려고 RDS를 공개 인터넷에 개방하는 것을 기본 배포 방법으로 삼지 않습니다.

## EC2: API를 먼저, 챗봇을 다음에

운영 서버의 저장소 루트에서 환경값을 준비합니다. 질문 어휘 추출기는 챗봇 이미지(`ChatBot/vendor/`)에 포함되어 별도 마운트가 필요 없습니다.

```bash
docker compose --env-file .env -f docker/compose.api.yml up -d --build
docker compose --env-file .env -f docker/compose.chat.yml up -d --build
```

두 Compose 프로젝트를 임의로 합치거나 다른 서비스에 `--remove-orphans`를 적용하지 않습니다. 챗봇은 API의 `feedit-api_default` 네트워크를 사용합니다.

| 서버 변수 | 확인 사항 |
| --- | --- |
| `DJANGO_SECRET_KEY`, `DJANGO_DEBUG` | 운영 키와 디버그 비활성화 |
| `DB_*` | EC2에서 접근 가능한 RDS 사설 주소·계정 |
| `API_PORT` | nginx 예시의 8001과 일치; Compose 기본은 8000 |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | 실제 프론트와 프록시 origin |
| `FEEDIT_API_TOKEN` | Vercel 중계 토큰과 일치 |
| `OPENAI_API_KEY` | 챗봇 모델 호출 |
| `FEEDIT_TEXT_OPENAI_API_KEY` | 배치 텍스트 분석 |
| `FEEDIT_BACKEND_API` | 기본 `http://feedit-api:8000/api` |
| `FEEDIT_PUBLIC_BETA`, `FEEDIT_CHAT_TOKEN` | 베타와 토큰 검사 정책을 함께 확인 |
| `FEEDIT_PLAN_SECRET` | 요금제 확인증 서명 키(Django 서명 · 챗봇 검사). 비우면 `FEEDIT_CHAT_TOKEN` 을 쓴다. 베타 동안은 쓰이지 않는다 |
| `FEEDIT_CHAT_ORCHESTRATOR` | 모델 도구 오케스트레이션 사용 설정 |
| `DASHBOARD_OTP_REQUIRED` | 관리자 TOTP 강제. HTTPS·마이그레이션·최초 등록 확인 후 `1` |
| `DASHBOARD_SESSION_AGE` | 마지막 활동 기준 관리자 세션 수명(초), 기본 3600 |
| `DASHBOARD_ALLOWED_EMAILS` | 쉼표로 구분한 관리자 팀 이메일. 설정 시 staff/superuser여도 목록 밖이면 차단 |
| `DJANGO_SECURE_COOKIES` | 관리자 HTTPS 확인 후 `1`; 세션·CSRF 쿠키만 Secure 처리 |
| `DJANGO_SECURE_SSL_REDIRECT` | 모든 API 클라이언트를 HTTPS로 전환한 뒤 `1`; 그전에는 `0` |
| `DJANGO_HSTS_SECONDS` | 최초 0, 안정화 뒤 300 → 86400 → 31536000 순으로 증가 |
| `GUNICORN_WORKERS`, `GUNICORN_THREADS` | API 동시 처리. 기본 3 × 4 (gthread). 이전 sync 3개는 동시 요청 3개가 한계였다 (2026-10-02) |
| `DB_CONN_MAX_AGE` | Django RDS 연결 재사용(초), 기본 60. 0 이면 요청마다 새로 접속 |
| `FEEDIT_RDS_POOL` | 챗봇 RDS 연결 수, 기본 4. 예전에는 연결 하나를 모든 요청이 나눠 썼다 |

`FEEDIT_PUBLIC_BETA`의 코드 기본값은 1입니다. 공유 토큰·플랜 정책이 비베타 모드와 달라집니다. 알파 계정(`FEEDIT_ALPHA_MODE`, `FEEDIT_ALPHA_UNTIL`, `FEEDIT_ALPHA_CHAT_QUOTA`)과 별도 정책이므로 각각 확인합니다. 화면의 사용량 차감만으로 서버 비용 제한이 강제된다고 간주하지 않습니다.

### 베타 종료 — 요금제 켜기 (2026-10-03)

요금제(프리 · 프로 · 비즈니스)는 코드에 들어 있지만 `FEEDIT_PUBLIC_BETA` 가 켜져 있는 동안(기본값)은 아무것도 막지 않습니다.
Django 와 챗봇이 루트 `.env` 의 같은 변수를 봅니다.

1. `python manage.py migrate core 0070` — 알림 종류 하나 추가(DB 변화 없음). 요금제 값은 `app_user.profile_metadata` 에 둡니다.
2. 루트 `.env` 에 `FEEDIT_PUBLIC_BETA=0`, 그리고 `FEEDIT_CHAT_TOKEN` 이 비어 있다면 `FEEDIT_PLAN_SECRET` 을 넣습니다.
3. API · 챗봇 컨테이너를 둘 다 다시 띄웁니다. 한쪽만 띄우면 화면과 챗봇이 다른 요금제를 말합니다.
4. 확인: 일반 계정으로 트렌드 분석 › 연관어가 잠기는지, 요금제 화면에서 프로 신청 → 운영 계정 메뉴 '요금제 신청 심사' 에서 승인 → 잠금이 풀리는지.

결제는 붙어 있지 않습니다. 승인은 운영자가 확인했다는 뜻입니다. 되돌릴 때는 `FEEDIT_PUBLIC_BETA=1` 로 바꾸고 두 컨테이너를 다시 띄웁니다(신청 · 승인 기록은 남습니다).

## 프록시와 DB 변경

`docker/nginx-feedit-api.conf`, `docker/nginx-feedit-chat.conf`를 실제 nginx 서버 블록에 맞게 적용하고 설정 검사를 거칩니다. 기존 nginx가 있으면 Caddy standalone 프로필을 동시에 올리지 않습니다.

관리자 화면을 공개할 때는 `docker/nginx-feedit-admin.conf`의 요청·연결 제한도
같이 적용합니다. 해당 예시의 `limit_*_zone`은 `http {}` 안, `location`은 실제
HTTPS `server {}` 안에 둡니다. 포트는 추측하지 않고 운영 서버의 `docker ps`와
`nginx -T` 결과를 기준으로 맞춥니다.

API는 읽기/쓰기 기능을 제공하지만 기동 명령에 `migrate`를 포함하지 않습니다. 스키마 변경은 백업·마이그레이션 계획을 검토한 별도 작업입니다. Redis는 현재 큐 용도이며 저장 비활성화·64 MB·noeviction 설정입니다. 큐 내구성과 용량을 운영 수준에 맞게 점검해야 합니다.

## 확인 순서

1. API·worker·beat·chatbot 컨테이너 상태와 시작 로그 확인.
2. nginx upstream 포트와 외부 네트워크 연결 확인.
3. `/api/health`, `/api/v1/health`와 실제 로그인·조회·채팅 확인. HTTP 200만으로 실데이터/모델 연결을 단정하지 않음.
4. worker에서 분석·수집 작업의 마지막 성공과 오류 확인.
5. 배포 버전·마이그레이션 적용 내역·환경 변경 항목 기록. 비밀값은 기록하지 않음.

## 관리자 HTTPS와 OTP 안전 적용 순서

관리자 페이지는 아래 순서를 바꾸지 않습니다. OTP 플래그를 먼저 켜면 테이블이
없거나 인증 앱을 등록하지 못한 상태에서 운영자가 잠길 수 있습니다.

1. DuckDNS가 현재 EC2 IP를 가리키는지, 80·443 보안 그룹과 nginx의 기존
   `server_name`을 읽기 전용으로 확인합니다.
   Django 호스트 포트(현재 8001)와 PostgreSQL 5432는 인터넷에 열지 않습니다.
   SSM만 사용한다면 SSH 22도 팀의 기존 접속 여부를 확인한 뒤 제거합니다.
2. Let's Encrypt 인증서를 발급하고 HTTPS 접속을 먼저 확인합니다. 이때 HSTS는
   `0`으로 둡니다.
3. API 이미지만 빌드합니다. `docker compose ... up -d --build`로 worker·beat를
   함께 재생성하지 않습니다.
4. 다음 명령으로 OTP 마이그레이션 계획을 확인한 뒤 새 테이블 하나만 적용합니다.

   ```bash
   sudo docker compose --env-file .env -f docker/compose.api.yml build api
   sudo docker compose --env-file .env -f docker/compose.api.yml run --rm api \
     python manage.py migrate dashboard --plan
   sudo docker compose --env-file .env -f docker/compose.api.yml run --rm api \
     python manage.py migrate dashboard
   sudo docker compose --env-file .env -f docker/compose.api.yml up -d --no-deps api
   ```

5. `DASHBOARD_OTP_REQUIRED=0` 상태에서 관리자 비밀번호로 다시 로그인한 후
   `/admin-dashboard/otp/setup/`에서 각 관리자 인증 앱을 등록하고 복구 코드를
   개인별로 안전하게 보관합니다.
6. 등록을 확인한 뒤 `.env`에 아래 값을 반영하고 API만 다시 생성합니다.

   ```dotenv
   DJANGO_SECURE_COOKIES=1
   DJANGO_SECURE_SSL_REDIRECT=0
   DJANGO_HSTS_SECONDS=0
   DASHBOARD_ALLOWED_EMAILS=feedit31@gmail.com,skn31final4team@gmail.com
   DASHBOARD_OTP_REQUIRED=1
   DASHBOARD_SESSION_AGE=3600
   ```

7. 일반 회원·비밀번호만 입력한 관리자·잘못된 OTP가 차단되고 정상 OTP만
   통과하는지 확인합니다. 사용자 로그인·찜·검색 API도 함께 점검합니다.
8. 안정화 후 `DJANGO_HSTS_SECONDS`를 단계적으로 늘립니다. 처음부터 preload를
   켜지 않습니다.

인증 앱과 복구 코드를 모두 잃은 운영 계정은 EC2 안에서만 다음 명령으로
초기화합니다. 실행 후 그 계정은 다시 비밀번호와 새 인증 앱으로 연결해야 합니다.

```bash
sudo docker exec feedit-api python manage.py reset_dashboard_otp <관리자아이디>
```

`docker/compose.prod.yml`은 SSM·Caddy 등을 함께 올리는 대체/이전 구성입니다. 현재 EC2 분리 구성의 기본 진입점으로 사용하지 않습니다.
