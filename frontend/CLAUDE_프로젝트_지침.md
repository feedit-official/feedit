# FEEDiT 프로젝트 안내

기준일: 2026-09-22. 이 파일은 특정 외부 작업 폴더를 전제로 하지 않습니다.

작업 전 [AGENTS.md](AGENTS.md)와 [협업 규칙](docs/WORKFLOW.md)을 읽으세요. 제품 맥락은 [프로젝트 컨텍스트](../docs/PROJECT_CONTEXT.md), 실제 실행 구조는 [시스템 구성](../docs/ARCHITECTURE.md)이 기준입니다.

프론트는 Vite + Vanilla JS이며 `main.js`/`main.css`와 기능별 폴더를 사용합니다. 백엔드는 같은 저장소의 `backend/` Django, 챗봇은 `ChatBot/` Python 서버입니다. API와 모델의 실제 응답을 검증하고, 없는 데이터로 화면을 채우지 않습니다. 미커밋 변경을 보존하고 검증하지 못한 사항을 명시합니다.
