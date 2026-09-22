# 배포 안내

2026-09-22에 현재 모노레포 기준으로 통합했습니다. [배포·환경변수·운영 점검](../../docs/DEPLOYMENT.md)을 사용하세요.

Vercel Root Directory는 `frontend`입니다. 서버는 API와 챗봇 Compose를 분리하고 EC2에서 사설 RDS에 연결합니다. 과거의 독립 저장소 초기화나 RDS 공개 개방 안내를 현재 기본 절차로 사용하지 않습니다.
