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
| `FEEDIT_CHAT_ORCHESTRATOR` | 모델 도구 오케스트레이션 사용 설정 |

`FEEDIT_PUBLIC_BETA`의 코드 기본값은 1입니다. 공유 토큰·플랜 정책이 비베타 모드와 달라집니다. 알파 계정(`FEEDIT_ALPHA_MODE`, `FEEDIT_ALPHA_UNTIL`, `FEEDIT_ALPHA_CHAT_QUOTA`)과 별도 정책이므로 각각 확인합니다. 화면의 사용량 차감만으로 서버 비용 제한이 강제된다고 간주하지 않습니다.

## 프록시와 DB 변경

`docker/nginx-feedit-api.conf`, `docker/nginx-feedit-chat.conf`를 실제 nginx 서버 블록에 맞게 적용하고 설정 검사를 거칩니다. 기존 nginx가 있으면 Caddy standalone 프로필을 동시에 올리지 않습니다.

API는 읽기/쓰기 기능을 제공하지만 기동 명령에 `migrate`를 포함하지 않습니다. 스키마 변경은 백업·마이그레이션 계획을 검토한 별도 작업입니다. Redis는 현재 큐 용도이며 저장 비활성화·64 MB·noeviction 설정입니다. 큐 내구성과 용량을 운영 수준에 맞게 점검해야 합니다.

## 확인 순서

1. API·worker·beat·chatbot 컨테이너 상태와 시작 로그 확인.
2. nginx upstream 포트와 외부 네트워크 연결 확인.
3. `/api/health`, `/api/v1/health`와 실제 로그인·조회·채팅 확인. HTTP 200만으로 실데이터/모델 연결을 단정하지 않음.
4. worker에서 분석·수집 작업의 마지막 성공과 오류 확인.
5. 배포 버전·마이그레이션 적용 내역·환경 변경 항목 기록. 비밀값은 기록하지 않음.

`docker/compose.prod.yml`은 SSM·Caddy 등을 함께 올리는 대체/이전 구성입니다. 현재 EC2 분리 구성의 기본 진입점으로 사용하지 않습니다.
