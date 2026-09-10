# 챗봇 리포트 탭 구조(구조안 02) 구현 — 인수인계

작성: 2026-09-10 · 작업 대상: `/Users/jeonseoyeon/Desktop/feedit`

## 배경

FEEDiT 챗봇 응답 리포트를 **취향분석 / 트렌드지표 / 상품추천** 세 섹션을 탭으로
전환하며 보여주는 구조(앞서 아티팩트로 시안 비교·예시를 만들었던 "구조안 02
탭 전환형")로 실제 챗봇에도 적용해 달라는 요청으로 시작한 작업입니다.

코드를 확인해보니 **트렌드지표는 실 데이터로 바로 연결**할 수 있지만,
**취향분석·상품추천은 백엔드에 실 데이터 연결이 아직 없어서**(취향은 RDS
테이블은 있으나 챗봇이 안 읽고 있고, 상품 추천/검색 도구 자체가 없음) 사용자와
합의한 범위는 다음과 같습니다:

> **탭 UI + 트렌드지표만 실데이터로 채우고, 취향분석·상품추천은
> "아직 연결 안 됨"을 정직하게 보여준다.** (가짜 데이터를 서비스 코드에
> 심지 않는다 — 이 프로젝트의 기존 원칙과 동일.)

## 지금 상태 (2026-09-10 세션 종료 시점)

- 백엔드·프론트엔드 코드는 **다 작성해서 저장까지 완료**했습니다.
- 문법 검사(`py_compile`, `node --check`, CSS 중괄호 밸런스)는 모두 통과했고,
  `agent_blocks.build()`를 트레이스를 직접 넣어 호출해보는 방식으로 블록
  모양도 확인했습니다.
- **그런데 사용자가 실제 화면에서 확인해보니 탭이 눌리지 않고, 세 섹션이
  구분 없이 위아래로 다 펼쳐진 채(버튼 글자도 "취향분석트렌드지표상품추천"처럼
  붙어서) 나왔습니다.** (스크린샷 첨부됨 — "고프코어 요즘 어때?" 질문에 대한
  실제 응답 화면)
- **원인을 찾아서 방금 고쳤습니다**: 아래 "방금 고친 버그" 참고. 다음 세션은
  **이 수정이 화면에 실제로 반영됐는지 확인하는 것부터 시작**하면 됩니다.

## 방금 고친 버그 (★ 다음 세션이 제일 먼저 확인할 것)

새 탭 스타일을 담은 `frontend/home/static/css/chat_report.css` 파일이
**`frontend/main.css`의 `@import` 목록에 아예 없었습니다.** 즉 이 파일은
작성만 되어 있고 브라우저까지 전혀 도달하지 않고 있었습니다 — `.tabreport`
`.rpTabs` `.rpTabBtn` `.rpTabPanel` 같은 새 클래스는 물론, 이 파일이 원래
갖고 있던 `.rpFull` `.rpProse` `.msg.ai .kpis`(2열 접기) 같은 기존 규칙도
전부 무시되고 있었다는 뜻입니다 (이건 제가 이번에 만든 버그가 아니라 이
세션에서 손대기 전부터 있던 상태로 보입니다).

**고친 내용**: `frontend/main.css`의 `@import './home/static/css/chat.css';`
바로 다음 줄에 `@import './home/static/css/chat_report.css';`를 추가했습니다
(`.msg.ai .kpis` 오버라이드가 `chat.css`의 `.kpis` 뒤에 와야 하므로 이 위치가
맞습니다).

**다음 세션에서 할 일**: Vite 개발 서버를 켠 상태라면 CSS는 보통 핫리로드되지만,
안 먹으면 dev 서버를 껐다 켜고 브라우저를 새로고침해서 스크린샷의 화면이
① 탭 버튼 3개가 알약 모양 없이도 좌우로 균등폭 나뉘고 ② 탭을 누르면 다른
탭 내용은 숨고 눌린 탭만 보이고 ③ 카드 전체에 테두리·그림자가 도는지
확인해 주세요. 안 된다면 브라우저 개발자도구에서 `.tabreport` 요소에
`chat_report.css` 규칙이 실제로 적용되는지(Computed 탭) 확인하는 게 다음
디버깅 단계입니다.

## 구현 내용 — 파일별

### 백엔드 — `ChatBot/app/agent_blocks.py`

- `_taste_tab(trace)` — `get_user_taste` 도구 호출 결과를 보고 취향분석 탭을
  만듭니다. 지금은 백엔드에 취향 데이터 원본이 없어서 거의 항상
  `state: "unavailable"`.
- `_reco_tab()` — 상품추천 탭. 상품 카탈로그/검색 도구 자체가 없어서 항상
  `state: "unavailable"`.
- `build()` 함수 안에 `is_tab_case` 분기를 추가했습니다:
  - **탭 구조를 쓰는 경우**: `rank_terms`로 열거한 질문("가을에 뭘 입으면
    좋을까?" 류) 또는 term 하나만 조회한 단일 트렌드 질문("고프코어 요즘
    어때?" 류) — `len(built) < 2 and (got["rank"] or len(built) == 1)`.
  - **탭 구조를 안 쓰는 경우(기존 동작 그대로)**: "A랑 B 중에 뭐가 나아?" 같은
    2개 이상 비교 질문. 기존의 나란히 보기(`b_compare`) 화면을 그대로 씁니다 —
    건드리지 않았습니다.
  - 탭 케이스일 때 `{"type": "tabreport", "slot": "full", "tabs": [...]}`
    블록 하나를 만듭니다. `tabs`는 `[취향분석, 트렌드지표, 상품추천]` 순서
    고정 3개.
  - 트렌드지표 탭의 `blocks`는 **기존에 이미 있던 렌더러**(`_rank_block`,
    `B.b_metric_rank`, `B.b_direction`, `B.b_sources`, `B.b_assoc`,
    `B.b_evidence`)를 그대로 재사용합니다 — 새 데이터 출처를 만들지 않았습니다.

**tabreport 블록 모양 예시**:
```python
{
  "type": "tabreport", "slot": "full",
  "tabs": [
    {"key": "taste", "label": "취향분석", "state": "unavailable",
     "message": "로그인하면 취향분석을 볼 수 있어요. (데이터 연결 준비 중)"},
    {"key": "trend", "label": "트렌드지표", "state": "ready",
     "blocks": [ {"type": "rank", ...}, {"type": "kpis", ...}, ... ]},
    {"key": "reco", "label": "상품추천", "state": "unavailable",
     "message": "상품 추천은 아직 연결되어 있지 않습니다. 곧 연결할 예정이에요."},
  ],
}
```

파일 머리말 주석에 "여기서 새 블록 타입을 만들지 않는다"는 기존 원칙이
있어서, `tabreport`를 새 타입으로 추가한 이유와 프론트도 같은 커밋에서
같이 채웠다는 점을 주석으로 남겨뒀습니다(파일 상단 "예외: tabreport는 새
블록 타입이다" 문단).

### 프론트엔드

- **`frontend/home/static/js/chat_api.js`**
  - `BLOCK` 디스패치 테이블에 `tabreport` 렌더러 추가. 탭 버튼 3개(`.rpTabBtn`,
    `data-tab` 속성)와 패널 3개(`.rpTabPanel`, `data-panel` 속성)를 그립니다.
  - 트렌드 탭 안의 서브 블록은 `BLOCK[sb.type](sb)`로 **기존 렌더러를 그대로
    재사용**합니다(rank/kpis/bars/quotes 등 — 새로 만들지 않음).
  - `state !== 'ready'`인 탭(취향분석·상품추천)은 `.rpTabEmpty`에 서버가 준
    `message`를 그대로 보여줍니다 — 빈 칸을 숨기지 않습니다.
  - 파일 머리말의 "여기서 쓰는 클래스는 전부 이미 CSS에 있는 것들" 목록에
    새 클래스 위치(`chat_report.css`)를 추가해뒀습니다.

- **`frontend/home/static/js/chat_popup.js`**
  - 기존 `document.addEventListener('click', ...)` 위임 리스너(각종
    `data-kw`/`data-mode`/`data-href`/`data-lexreq` 처리하던 곳)에
    `data-tab` 케이스를 추가. 서버 왕복 없이 `.tabreport` 카드 안에서만
    `.rpTabBtn`/`.rpTabPanel`의 `on` 클래스를 토글합니다.

- **`frontend/home/static/css/chat_report.css`**
  - `.tabreport`(카드 테두리·그림자, `.ansCard`와 같은 톤)
  - `.rpTabs` / `.rpTabBtn`(탭 바 — 밑줄 스윕 애니메이션은 기존
    `.mNav button.on::after`와 같은 `scaleX` 방식을 그대로 따름)
  - `.rpTabPanel`(`display:none` → `.on`일 때만 `block`)
  - `.rpTabEmpty`(연결 안 됨 안내문 스타일)
  - **⚠️ 처음에는 `.trTabs`/`.trTab`/`.trPanel`이라는 이름을 썼다가, 이미
    `frontend/trend/static/css/dispatch.css`에 같은 이름의 클래스가 다른
    스타일로 있는 걸 발견해서 `.rpTabs`/`.rpTabBtn`/`.rpTabPanel`/`.rpTabEmpty`로
    바꿨습니다.** 앞으로 이 접두어(`rpTab*`)를 벗어난 이름을 쓸 땐 꼭
    `grep -rn "<이름>" frontend/ --include=*.css`로 충돌 여부를 먼저
    확인하세요 — 이 프로젝트는 전역 CSS 캐스케이드(`main.css`가 전부
    `@import`)라 같은 이름이면 나중에 로드되는 쪽이 조용히 이깁니다.
  - **오늘 발견한 버그**: 이 파일 자체가 `main.css`에 `@import`되어 있지
    않았음 → 지금 세션에서 고쳤습니다(위 "방금 고친 버그" 참고).

## 확인한 것 / 확인 안 된 것

**확인함**
- `python3 -m py_compile ChatBot/app/agent_blocks.py` 통과
- `node --check` (`chat_api.js`, `chat_popup.js`) 통과
- `agent_blocks.build()`를 가짜 트레이스로 직접 호출 — `rank_terms` 트레이스를
  넣었을 때 `tabreport` 블록이 `tabs: [taste(unavailable), trend(ready),
  reco(unavailable)]` 모양으로 정확히 나오는 것을 확인
- 빈 트레이스 / 취향만 있고 트렌드 데이터 없는 트레이스에서는 빈 리스트가
  나와 예전처럼 빈 카드가 안 뜨는 것도 확인
- CSS 클래스 이름 충돌 없음(`grep`으로 전체 재검사)

**확인 못 함 (다음 세션 몫)**
- **실제 브라우저 렌더링** — 이 세션은 이 VM에서 Vite 개발 서버를 못 띄웁니다
  (`@rollup/rollup-linux-arm64-gnu` 모듈 에러 — `node_modules`가 사용자의 맥에서
  설치돼 있어서 이 리눅스 VM과 아키텍처가 안 맞음). 그래서 이번 CSS
  import 수정이 실제로 화면을 고쳤는지는 **아직 못 봤습니다.** 스크린샷으로
  다시 확인해 주세요.
- 탭 3개 다 있는 상태에서 실제 대화 흐름(모바일 폭, 긴 트렌드지표 내용일 때
  스크롤 등) 육안 확인
- `is_tab_case` 분기 조건이 실제 orchestrator 응답에서 의도한 질문들(단일
  트렌드 질문, 비교 질문)에 대해 정확히 갈리는지 — 지금은 `agent_blocks.build()`
  단위 테스트로만 확인했고, 실제 LLM이 어떤 도구를 어떤 조합으로 부르는지는
  실제 대화로만 확인 가능

## 남은 작업

### 필수 (이번 요청 범위 마무리)
1. `main.css` import 수정 후 스크린샷으로 실제 탭 동작 재확인
2. 살까말까(살말) 모드에서도 같은 트리거 조건(`is_tab_case`)이 걸리는지 확인
   — 지금 구현은 모드에 상관없이 트레이스만 보고 판단하므로 이론상 살말
   모드에서도 똑같이 tabreport가 뜰 것으로 보이지만, 실제로 살말 모드
   질문으로 테스트는 안 해봤습니다

### 선택 / 향후 (백엔드 데이터가 준비되면)
1. **취향분석 실데이터 연결** — `ChatBot/app/tools.py`의 `Toolbox.taste`를
   실제 RDS 취향 테이블에 연결하고, `agent_blocks._taste_tab()`에
   `state: "ready"` + 실제 취향 태그/매치율을 채우는 분기 추가
   (현재 함수 구조상 이 함수 하나만 고치면 됩니다 — 프론트는 `state` 값만
   보고 그리므로 손댈 필요 없음)
2. **상품추천 데이터/도구 연결** — 상품 카탈로그 검색 도구를 `tools.py`에
   새로 만들고, `agent_blocks._reco_tab()`을 그 결과로 채우기
   (지금은 함수가 인자 없이 고정 문구만 반환 — 실제 구현 시 트레이스나
   호출 결과를 받아오도록 시그니처를 바꿔야 함)

## 참고 — 이번 세션에서 만든 예시 아티팩트

실제 코드 작업 전에 구조를 논의하며 만든 시안들 (같은 계정 아티팩트 갤러리에서
찾을 수 있습니다):
- 구조 후보 4가지 비교 — "챗봇 리포트 구조안"
- 구조 02(탭 전환형) 살말 모드 예시 — "탭 전환형 리포트 예시"
- 구조 02 일반 모드 예시(질문 2개) — "일반 모드 리포트 예시"

이번에 실제 코드에 반영한 것은 이 중 **구조 02(탭 전환형)** 이고, 탭 안의
트렌드지표 시각화(막대→꺾은선 그래프 수정 포함)까지는 시안 단계에서만
반영했고, 실제 챗봇 트렌드지표 탭은 기존 `.rank`/`.kpis`/`.bars` 렌더러를
그대로 쓰므로 시안과 시각적으로 100% 동일하지는 않습니다(구조·정보 배치는
같지만 세부 스타일은 기존 블록 스타일을 따릅니다).
