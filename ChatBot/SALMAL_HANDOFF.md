# 인수인계 — 살말 챗봇 (2026-09-11 갱신)

작업 저장소: `/Users/jeonseoyeon/Desktop/feedit`
기준 브랜치: `main` · 기준 커밋: `1445d33 살말 챗봇 응답 리포트&GPT Image2 연결`
현재 상태: 아래 내용은 **로컬 작업 트리에만** 있다. 커밋·푸시·배포하지 않았다.

> 이 문서는 2026-09-11 오전에 쓴 `salmal_chatbot_handoff.md` 를 대체한다.
> 그 문서의 0절(핵심 세로 경로 구현)은 여전히 유효하고, 그 뒤에 일어난 일이
> 아래 2·3절이다.
>
> 작업 전에 `ChatBot/AGENTS.md` 와 `frontend/AGENTS.md` 를 먼저 읽을 것.
> 이 문서는 *무엇을 왜 고쳤는가*, 그쪽은 *어떻게 고칠 것인가* 다.

---

## 1. 지금 동작하는 것

```text
상품 이름·링크·사진으로 "이거 사도 될까?"
  → 즐겨입는 스타일 + 최근 검색 + 찜을 taste_context 로 전달
  → 링크면 web_search 로 무엇인지 확인(한 번만)
  → 지표·트렌드·가격·커뮤니티 조회 → get_salmal_index
  → 0~100 살말 지수 + 살/말/보류 + 신뢰도 + 근거/결측 리포트 카드
  → 답변 아래 [지표로 보기] [물어보기] [입혀보기]
```

- **살말 지수**: `ChatBot/app/salmal_index.py`
  취향 35 · 검색/찜 25 · 트렌드 20 · 가격 15 · 커뮤니티 5.
  없는 축은 50으로 메우지 않고 분모에서 뺀다. `coverage` 40% 미만이면 결론은 `보류`.
- **물어보기**: 챗봇이 확인한 상품명·브랜드·가격이 커뮤니티 카드 작성칸에 미리 채워진다.
- **입혀보기**: 다른 페이지로 가지 않는다. 클릭한 답변 바로 아래에서 펼쳐지고
  결과도 같은 대화에 남는다(GPT Image 2, `ChatBot/app/vton.py`).

---

## 2. 2026-09-11 오후에 고친 것

### 2.1 리포트 카드가 통째로 사라지던 버그 (가장 중요)

`report_skill.build` 는 모듈이 하나라도 있으면 `spec.get("title")` 을 읽는데,
그 위의 **"살말 근거와 없는 자료는 숨기지 않는다"** 루프가 `spec` 과 무관하게
모듈을 넣는다. 그래서 `compose_report` 를 못 부른 채(예산 끊김) 살말·결측
모듈만 있는 상태가 되면 `spec` 이 `None` 인 채로 `.get()` 이 불려 `AttributeError`
가 났다. 그 예외를 `agent_path` 가 **조용히 삼켜서**(`except Exception: blks=[]`)
화면에는 답변 문장만 남고 카드가 사라졌다. 콘솔에도 아무 것도 남지 않았다.

- `spec or {}` 로 읽고 `source` 를 `fallback` 으로 표시한다.
- 예외를 삼키되 **콘솔에 남긴다.** 한 줄 로그에 `블록=N`(실패 시 사유)이 찍힌다.
- `get_metric` 의 `has_metric=False` 도 버리지 않고 결측 모듈로 남긴다.
  조회한 용어가 전부 무측정이면 카탈로그가 비어 카드가 아예 안 뜨던 자리다.

### 2.2 링크 질문의 시간 예산

실측 로그:

```
! 18574ms stopped=time_budget 바퀴=3(5563+6871ms) 웹검색=2 호출=5 블록=1
  도구=search_terms,get_metric,get_metric,get_metric,get_salmal_index
```

① 링크 확인(호스티드 web_search) 5.6초 ② 지표·지수 조회 6.9초 ③ 답 쓰기 —
③이 시작도 못 했다. ①은 **링크 질문에만 있는 비용**인데 같은 시계를 주니
구조적으로 답을 못 쓴다.

- `budget_for(question)` — 질문에 URL 이 있으면 `LINK_EXTRA`(기본 8초,
  `FEEDIT_CHAT_LINK_EXTRA`)를 더 준다. 일반 질문은 그대로다.
- **조회가 끝났으면 뒷몫에서 빌린다.** `TAIL_RESERVE`(8초)는 루프가 답을 못
  썼을 때 `_finish` 가 대신 쓰라고 비워 둔 시간인데, 그 시간을 비워 두느라
  루프가 답을 못 쓰면 같은 일을 하려고 예산을 두 번 쓰는 셈이다. 남은 일이
  '답 쓰기' 하나면 `deadline - VERIFY_RESERVE` 까지 쓴다. 빌린 바퀴에는
  "도구 더 부르지 말고 compose_report 한 번 뒤 답을 쓰라"고 알려 준다.
- **써 둔 답을 버리지 않는다.** `pending_answer`(디자인 호출을 기다리며
  보류한 답)를 예전에는 `compose_report` 가 돌았을 때만 꺼냈다. 이제 루프가
  끝났는데 답이 없으면 그것을 쓴다 — 모델을 한 번 더 부르지 않는다.
- 프롬프트: 링크 확인 `web_search` 는 **한 번만**.
- 콘솔 로그에 `18574ms/25000ms` 처럼 예산을 함께 찍는다.

**두 번째 실측 — 이번엔 바퀴가 모자랐다**

```
! 33058ms/33000ms stopped=max_rounds 바퀴=4(5328+12387+4624+3006ms) 웹검색=2
  도구=…,get_salmal_index,declare_missing,declare_missing,compose_report
```

예산은 늘어나 `compose_report` 까지 갔는데, **답을 쓰는 다섯 번째 바퀴가
없었다**(`MAX_ROUNDS=4`). 시간이 아니라 바퀴가 모자란 것이다.

- `rounds_for(question)` — 링크 질문은 `MAX_ROUNDS + 1`. 예산과 같은 이유다.
- **도구를 부르면서 같이 쓴 답변 문장을 버리지 않는다.** 루프는 호출이 있으면
  같은 응답의 문장을 통째로 버리고 다음 바퀴에서 다시 쓰게 했다. 그 바퀴가
  없으면 답이 사라진다. `compose_report` 가 포함된 바퀴의 문장만 받는다 —
  그것은 조회가 끝났다는 신호라서, 중간 바퀴의 혼잣말과 구분된다.
- **되살린 답에는 "조회를 끝까지 하지 못했다" 를 붙이지 않는다**(`Result.recovered`).
  온전한 답 아래에 경고가 붙으면 사용자는 멀쩡한 답을 의심한다.
- 프롬프트: `declare_missing` 은 `compose_report` 와 **같은 바퀴에서** 부른다.
  따로 나누면 바퀴를 하나 더 쓴다.

### 2.3 끊겨도 무엇을 봤는지는 말한다

`_finish` 가 모델을 부를 시간조차 없으면 예전에는 "여기까지 확인했습니다.
어느 쪽을 더 볼까요?" 한 줄로 닫혔다. 카드는 다 그려져 있는데 본문이 비는 셈이다.

`_recap()` 을 추가했다 — **모델을 부르지 않고 궤적에서 직접 쓴다.**

```
살말 지수 44점 · 보류 (신뢰도 낮음).
확인한 지표: 아디다스 58점 (따뜻함).
측정 자료가 없던 것: 폴로셔츠.
빠진 신호: 취향 · 가격.
```

값이 전부 도구 결과라 `verify` 도 그대로 통과한다(실측: removed 없음).
조회가 하나도 없을 때만 예전 한 줄로 닫는다.

### 2.4 살말 지수의 '취향' 축 정정

축의 출처는 맞았다 — 가입할 때 고른 즐겨입는 스타일(`ME.styles`)이
`favorite_styles` 로 서버까지 간다. 그런데 비교가 **문자열 완전 일치**였다.
취향은 스타일 이름("블록코어"), 상품은 아이템 이름("벌룬 카고 미디 스커트")
으로 들어오므로 두 어휘가 만나는 일이 사실상 없었고, 가중치가 가장 큰 취향
축(35)은 상품 태그가 있으면 거의 항상 25점(취향 거리)으로 떨어졌다.

- 프런트가 스타일의 대표 어휘(`STYLES.kw`)를 `favorite_style_profiles` 로 함께 보낸다.
- 서버는 띄어쓰기를 눌러 **포함 관계**로 비교한다(`_squash` · `_overlap`).
- 검색·찜 축도 같은 비교로 맞췄다.
- 표는 `STYLES` 에 드러나 있고 고치면 판단이 바뀐다 — 답변 경로에 숨은 분류표가 아니다.

### 2.5 물어보기 초안

링크를 주면 챗봇은 이미 상품명을 확인하는데 그 이름이 **답변 문장 안에만**
있어서, 카드 상품명 칸에 링크 주소가 그대로 들어갔다.

- 답변에서 정규식으로 뽑지 않는다. `get_salmal_index(term, item_name, brand,
  price)` 가 **같은 호출에서** 받는다(전용 도구를 따로 두면 바퀴를 하나 더 쓴다
  — 실제로 그렇게 했다가 2.1의 버그를 깨웠다).
- 모델이 못 적었으면 `search_terms` 의 `q`(실제로 찾아본 이름)로 떨어진다.
  주소로 시작하는 `q` 는 쓰지 않는다.
- 화면에서도 **링크는 상품명이 아니다.** 서버 초안이 없고 사용자 문장에 주소가
  섞여 있으면 상품명 칸을 비워 둔다.
- 확인하지 못한 칸은 비워 두고 사용자가 적는다. 가격은 실제로 본 판매가만.

### 2.6 화면

- **브랜드 검색**: 카드 등록창의 `<select>` 를 검색 입력칸 + 자동완성 목록으로.
  ↑↓·Enter·Esc. 목록에 없는 브랜드도 그대로 적어 낼 수 있다.
- **입혀보기**: 세 버튼(지표로 보기·물어보기·입혀보기)을 같은 디자인으로.
  카드는 대화 너비를 그대로 쓰고(680px 제한 해제), 아이템 칸 300px · 결과 칸 520px.
  아이템 사진은 `max-width/max-height + auto` 로 **어떤 경우에도 잘리지 않는다.**
  옷 종류에서 안경·양말·벨트를 뺐다(화면 목록과 `vton.CATEGORIES` 둘 다).
- **리포트 시각 문법**: `note` 블록은 누가 고르든 한 가지 모양(compact · normal ·
  12열). 한 줄에 남는 칸이 있으면 그 줄의 마지막 모듈이 채운다(`_pack_rows`).
  KPI 열 수는 최종 폭을 보고 정한다 — 폭을 다 쓰면 지표 4개가 한 줄에 선다.
- **주문 요청**: "이거 대신 주문해 줘" 에 되묻지 않는다. 되묻는 순간 고르기만
  하면 해 준다는 뜻으로 읽힌다. 규칙 3과 `ask_user` **도구 설명** 양쪽에 적었다.

---

## 3. 이번에 건드린 파일

| 파일 | 무엇 |
| --- | --- |
| `ChatBot/app/report_skill.py` | spec=None 크래시 · note 통일 · 줄 채움 · KPI 열 |
| `ChatBot/app/agent_blocks.py` | `has_metric=False` 결측 모듈 |
| `ChatBot/app/agent_path.py` | 블록 조립 예외 로그 · `item_draft` · 링크 예산 |
| `ChatBot/app/orchestrator.py` | `budget_for` · 뒷몫 빌리기 · `_recap` · 규칙(주문·web_search 1회) |
| `ChatBot/app/tools.py` | `get_salmal_index` 인자 확장 · `ask_user` 경계 |
| `ChatBot/app/salmal_index.py` | 취향·행동 축 포함 관계 비교 |
| `ChatBot/app/vton.py` | 카테고리 축소 |
| `ChatBot/server.py` | `clean_taste_context` · 물어보기 draft · 로그(블록·예산) |
| `frontend/index.html` | 브랜드 검색 마크업 (**실제 화면은 이 파일이다**) |
| `frontend/salmal/templates/salmal.html` | 같은 마크업 (참고용 사본) |
| `frontend/salmal/static/js/vote_app.js` · `css/vote_app.css` | 브랜드 검색 · 초안 채우기 |
| `frontend/home/static/js/chat_popup.js` · `chat_api.js` | 취향 프로필 · draft · 카테고리 |
| `frontend/home/static/css/chat_popup.css` | 입혀보기 크기·버튼 |

새 테스트: `test_item_draft.py` · `test_empty_lookup_card.py` ·
`test_report_layout.py` · `test_time_budget.py`

---

## 4. 검증 상태

- ChatBot Python 테스트 **47건 통과**
- 변경 Python 컴파일 검사 · 변경 JavaScript `node --check` · `git diff --check` 통과
- 브랜드 검색과 초안 채우기는 **jsdom 에서 실제로 실행**해 확인
  (`main.js` 로 앱을 띄우고 `salmalBoot()`: "ad"→ADIDAS, ↓+Enter 선택,
  초안 주입 시 상품명·브랜드·가격이 각각 채워짐)
- `_recap` 출력을 실제 `TraceLog` 로 `verify` 에 통과시켜 숫자가 지워지지 않는 것 확인

**확인하지 못한 것 (그대로 적는다)**

- `npm run build` · `npm run dev` — 작업 환경이 linux-arm64 인데 `node_modules` 가
  다른 플랫폼용이라 rollup 네이티브 모듈을 못 찾는다. **맥에서 한 번 돌려야 한다.**
- 브라우저 시각 검수 — 입혀보기 크기, 리포트 카드 여백·안내문 통일은 눈으로 봐야 한다.
- 실제 모델 실행 — 링크 질문이 답 쓰는 바퀴까지 가는지, 주문 요청에 되묻지 않는지,
  모델이 `item_name·brand·price` 를 채우는지는 키와 네트워크가 필요하다.
- GPT Image 2 실생성 · 실제 RDS 조회는 호출하지 않았다.

---

## 5. 다음 세션에서 할 일

1. **맥에서 `npm run build` 와 브라우저 검수.** 2.6 항목 전부.
2. **링크 질문을 다시 재 본다.** 콘솔 한 줄이 전부 말해 준다.
   - `stopped=done` 이면 고쳐진 것.
   - `time_budget` 이면 시간이 모자란 것 → `FEEDIT_CHAT_LINK_EXTRA` 를 올린다.
   - `max_rounds` 면 바퀴가 모자란 것 → `LINK_EXTRA_ROUNDS` 를 올린다.
   - `웹검색=1` 인지, `declare_missing` 이 `compose_report` 와 같은 바퀴인지도 본다.
   - 지금은 링크 질문이 30초를 넘게 쓴다. 가장 긴 바퀴는 지표 조회(12.4초)였다.
     더 줄이려면 그 바퀴의 모델 시간을 재는 것부터 해야 한다.
3. 주문·결제 요청 한 번 쳐 보기. 되묻으면 규칙이 아니라 **도구 목록**에서
   막아야 한다(살말 모드에서 ask_user 를 빼는 방향).
4. 상세 모달 `buildAIReport()` 목업을 같은 서버 판단 결과로 통합 (기존 4단계).
5. 실제 RDS 읽기 연동 · 인증 연동 후 취향/검색/찜을 서버 확정 데이터로 전환.
6. 커밋·푸시 — 이번 작업은 전부 미커밋 상태다.

---

## 6. 함정

- `frontend/salmal/templates/*.html` 은 **참고용 사본**이다. 실제 화면은
  `frontend/index.html`. 둘 다 고쳐야 한다.
- 프런트가 모르는 block/kind 는 **오류 없이 사라진다.** 새 타입을 만들면
  백엔드 생성 · 스킬 허용 목록 · 프런트 렌더러 · CSS · 테스트를 함께 고친다.
- 예산 상수(`TIME_BUDGET` · `TAIL_RESERVE` · `WRITE_MIN`)를 만질 때는
  **양쪽 실패를 같이 본다.** 너무 크면 루프가 답을 못 만들고, 너무 작으면
  답을 못 쓴다. `HANDOVER_agent.md` 11장에 그 실측 이력이 있다.
- 살말 결론은 `get_salmal_index` 의 `recommendation` 만 쓴다. 투표는 참고 신호(5%)다.
