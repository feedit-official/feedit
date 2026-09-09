# 인수인계 — 챗봇 에이전트 경로 (2026-09-09)

앞으로 이 부분을 맡을 분에게. **읽는 순서대로** 썼다.
30분이면 지금 상태를 다 알 수 있게, 함정은 함정이라고 적어 뒀다.

`ChatBot/README.md` 는 여전히 유효하다 — 켜는 법, 크롤러 저장소가 왜 필요한지는
거기에 있다. 이 문서는 **README 가 아직 모르는 것**, 즉 새로 만든 에이전트 경로만 다룬다.

---

## 1. 한 줄 요약

챗봇 답변을 만드는 길이 지금 **두 개**다. 환경변수 하나로 갈아 낀다.

```bash
FEEDIT_CHAT_ORCHESTRATOR=1   # 새 경로 (도구 루프)
# 없거나 0                    # 기존 경로 (정규식 의도 분류 → 고정 템플릿)
```

기존 경로를 **지우지 않았다.** 새 경로가 어느 질문에서 더 나은지 실제로 재 본 뒤에
기본값을 바꾸면 된다. 돌고 있는 챗봇을 세우지 않고 갈아 끼우기 위한 것이다.

---

## 2. 왜 새로 만들었나

기존 경로는 `intents.py` 의 정규식 14개로 의도를 **확정**하고, `templates.py` 가
그 의도에 붙은 블록을 그렸다. 근거를 보기 전에 되돌릴 수 없는 결정을 하는 구조라
세 곳에서 깨진다.

| 깨지는 질문 | 왜 |
| --- | --- |
| "살로몬 XT-6 지금 사도 돼?" | 할인률·수명주기·리세일 셋 다인데 하나를 고르는 순간 나머지 근거가 사라진다 |
| "이거 어때?" | 분류하려면 "이거" 가 뭔지 알아야 하는데, 그건 분류 이후에나 정해진다. 순서가 뒤집혀 있다 |
| "요즘 뭐가 핫해?" | 사전에 걸리는 말이 없다고 범용으로 흘러갔다. 답이 용어인 질문인데 우리 데이터를 안 보고 지어냈다 |

새 경로는 의도 코드를 만들지 않는다. **다음에 부를 도구**만 정하고, 결과를 보고
다시 정한다. 위 셋이 전부 이 한 가지로 풀린다.

> 설계 원칙: **분류하지 말고 도구를 골라라.**
> 어휘 사전은 관문(gate)이 아니라 도구다. 되묻기(`ask_user`)와 없다고 말하기
> (`declare_missing`)도 실패 경로가 아니라 도구다.

---

## 3. 파일 지도

새로 만든 것 (전부 아직 **커밋 안 됨** — 5장 참고):

| 파일 | 줄 | 하는 일 |
| --- | --- | --- |
| `app/tools.py` | 632 | 도구 10개의 규격과 구현. 여기가 제일 크다 |
| `app/orchestrator.py` | 267 | L1 — 도구를 고르고, 결과를 보고 다시 고른다 |
| `app/verify.py` | 253 | L3 — 답변의 숫자가 도구 결과에 실제로 있는지 대조 |
| `app/agent_path.py` | 164 | 두 경로를 잇는 이음매. 화면이 아는 모양으로 바꿔 준다 |
| `app/agent_blocks.py` | 180 | 궤적 → 화면 블록 |

고친 것:

| 파일 | 무엇을 |
| --- | --- |
| `app/store.py` | 근거에 `platform` · `url` · `at_iso` 추가 (**RDS 교체 지점**, 4장) |
| `app/report.py` | `evidence` 에 `url` 통과, `DOC_KO` 에 `product_review` |
| `app/engine.py` | 두 경로 스위치 |
| `server.py` | 진행 상황(`on_progress`) 을 SSE 로 흘려보냄 |
| `frontend/home/static/js/chat_api.js` | 블록이 없으면 빈 카드 대신 아무것도 안 그린다 |

흐름:

```
질문
 └ L0 컨텍스트   보던 용어 · 살말 카드 · 로그인 여부 · 직전 대화 3턴
 └ L1 오케스트레이터 (terra/medium)   ← 도구를 고른다. 결과를 보고 다시 고른다
     └ L2 도구 10개                    ← 값은 전부 여기서만 나온다
 └ L3 검증 (luna/none)                ← 지어낸 숫자를 걸러낸다
 └ 화면: 말풍선(문장) + 카드(블록)
```

---

## 4. 손대기 전에 알아야 할 함정

### ★ 값은 도구에서만 나온다

제일 위험한 실패는 **"DB 가 안 붙었는데 화면에 그럴듯한 숫자가 떠 있는 것"** 이다.
화면 쪽은 이미 그 원칙을 지킨다 — 값이 없으면 `unavailableHTML` 이 사유를 적지,
난수를 그리지 않는다. 챗봇에도 같은 자리를 만들어 둔 것이 `verify.py` 다.

그래서 지켜야 할 규칙이 셋이다.

1. **`TraceLog` 는 도구 결과를 원본 그대로 들고 있어야 한다.**
   요약해서 저장하면 대조할 것이 없어지고, 검증은 그냥 통과 도장이 된다.
2. **블록은 궤적에서 만든다. 답변 문장에서 만들지 않는다.**
   문장을 파싱해 블록을 만들면 모델이 지어낸 말이 그대로 막대그래프가 된다.
   숫자를 검증하는 층을 두고서 그 옆으로 지어낸 값이 그림이 되어 새어 나가는 셈이다.
   (`agent_path._terms_from()` 과 `agent_blocks.build()` 가 같은 이유로 궤적만 읽는다)
3. **`may_say` 를 무시하지 마라.** 관측이 모자라 말하면 안 되는 축이다.

### ★ 프론트가 모르는 블록 타입은 조용히 사라진다

`chat_api.js` 의 `BLOCK` 에 있는 것만 그려진다 — `rank` `bars` `table` `kpis`
`quotes` `prose` `links` `note` `upsell`. 모르는 `type` 은 **에러 없이 안 그려진다.**
`metric_chart` 같은 걸 새로 지어 쓰면 원인 없는 빈 칸이 된다. 새 블록이 필요하면
`blocks.py` 와 `chat_api.js` 를 **같이** 고쳐야 한다.

### ★ `as_of` 는 문자열이 아니라 객체다

`chat_api.reportHTML` 이 `rep.as_of && rep.as_of.metric` 으로 읽는다.
문자열을 주면 `.metric` 이 `undefined` 라 카드의 기준일이 **조용히 사라진다.**
한 번 당했다.

### ★ 근거 링크 — 없으면 없는 채로 내보낸다

`store.evidence_link()` 는 되돌아갈 수 있는 주소만 만든다.

| 플랫폼 | `product_uid` | 링크 |
| --- | --- | --- |
| 유튜브 | `yt:<video_id>` | `youtube.com/watch?v=...` |
| 무신사 | 숫자 상품 id | `musinsa.com/products/...` |
| 네이버 | `kw:<검색어>` | **불가능** — 글이 아니라 검색어다 |

실측(2026-09-09, 근거 454건): **308건(67%) 링크 가능.**

여기서 "네이버 블로그 검색 결과" 같은 그럴듯한 주소를 지어 붙이면, 누른 사람은
우리가 인용한 글이 **아닌** 곳에 떨어진다. 틀린 숫자와 같은 종류의 거짓말이다.
`url` 이 없으면 `None` 인 채로 내보내고, 답변에는 `(원문 링크 없음)` 이라고 적는다.
`orchestrator.INSTRUCTIONS` 6번 규칙이 그것이다.

### ★ RDS 로 갈아탈 때 손댈 곳은 `store.py` 하나다

지금 지표는 로컬 SQLite(`feedit-crawler/data/feedit.db`)에서 읽는다.
DB팀의 전처리가 끝나면 AWS RDS 로 옮긴다. 그때 고칠 함수는 셋뿐이다.

```
store.evidence_link()    플랫폼별 원문 주소 규칙
store.platform_label()   source_code · doc_kind → 한글 이름
store.at_iso()           시점 표기 통일 (RDS 는 timestamp 라 그냥 통과)
```

**위쪽(tools · orchestrator · blocks)은 건드리지 않는다.** 그러라고 이 경계를 만들었다.
(`at_iso` 가 왜 있냐면 — 네이버만 `20260902`, 나머지는 `2026-09-08` 로 와서
한 답변 안에 두 표기가 섞였다. 사람은 앞엣것을 숫자로 읽는다.)

### ★ 날짜를 숫자로 세지 마라

`verify.py` 가 답변의 숫자를 뽑아 도구 결과와 대조하는데, `2026-09-08` 을 그냥
숫자로 뽑으면 `-09` `-08` 이 **"지어낸 음수"** 로 잡힌다. 기준일을 성실히 밝힌
답변일수록 더 많이 걸리는, 정확히 거꾸로 된 판정이었다. `_DATE` 정규식으로
날짜를 **먼저** 걷어낸 뒤에 숫자를 뽑는다. 이 순서를 바꾸지 마라.

---

## 5. 지금 상태 — 커밋 전에 볼 것

`git status` 에 이렇게 뜬다.

**이 작업 것 (올려야 함)**

```
?? ChatBot/app/agent_blocks.py     ?? ChatBot/app/orchestrator.py
?? ChatBot/app/agent_path.py       ?? ChatBot/app/tools.py
?? ChatBot/app/verify.py
 M ChatBot/app/engine.py            M ChatBot/app/store.py
 M ChatBot/app/llm.py               M ChatBot/server.py
 M ChatBot/app/report.py            M frontend/home/static/js/chat_api.js
```

**이 작업과 무관 — 랜딩 페이지 쪽 (누가 하던 것인지 확인하고 따로 올릴 것)**

```
 M landing/css/landing.css   M landing/index.html   M landing/js/*.js
?? landing/assets/*.svg
```

한 커밋에 섞지 않는 편이 낫다.

### 알려진 문제

- **`.git/index.lock` 이 남아 있으면** 지우고 시작한다.
  `rm -f .git/index.lock .git/objects/14/tmp_obj_*`
- **`ChatBot/tests/render.test.mjs` 7번 실패는 이 작업과 무관하다.**
  테스트가 `API_BASE === 'http://127.0.0.1:8770'` 를 기대하는데, Vercel 릴레이
  때문에 `/api` 로 바꾼 것이 반영 안 된 오래된 단언이다. 테스트를 고쳐야 한다.

---

## 6. 남은 일 (순서대로)

| # | 할 일 | 크기 |
| --- | --- | --- |
| 14 | **살!말? 어댑터.** `t_get_salmal` · `t_search_salmal` 이 지금 빈 껍데기라 `unavailable` 만 돌려준다. 살말 데이터 소스를 붙이면 살말 모드가 산다 | 중 |
| 15 | **되묻기 예산 1회 / 대화.** 지금은 상한이 없다. 기본값 + 보정 제안 형태로 바꾼다. 세션 기억(최근 조회 용어 5개, 살말 카드 이력, 마지막 본 상품)도 여기 | 중 |
| 16 | **비교 질문** ("A랑 B 중에 뭐"). 새 에이전트를 만들 일이 아니라 프롬프트 + 스키마로 푼다는 것이 지금 입장. `blocks.b_compare` 는 이미 있다 | 소 |
| — | **실제 OpenAI API 로 한 번도 안 돌려 봤다.** 구조·스키마는 맞춰 뒀지만 실호출 검증이 남았다. `tools_llm_check.py` 부터 | **먼저** |
| — | `intents.py` · `templates.py` 는 비교가 끝날 때까지 남겨 둔다. 새 경로가 이긴 뒤에 지운다 | — |

### 배포 쪽 남은 것

- EC2 가 **HTTP 만** 연다(443 없음). `X-FEEDiT-Token` 과 `FEEDIT_CHAT_TOKEN` 이
  평문으로 다닌다. certbot 을 붙여야 한다.
- `feedit-redis` 가 `0.0.0.0:6379` 로 열려 있다.
- `FEEDIT_MCP_SERVERS` 는 `require_approval: "never"` 로 설정돼 있다.
  **읽기 전용 서버만** 목록에 넣을 것.

---

## 7. 환경변수

새 경로가 읽는 것 전부.

| 이름 | 기본값 | 뜻 |
| --- | --- | --- |
| `FEEDIT_CHAT_ORCHESTRATOR` | (꺼짐) | `1` 이면 새 경로 |
| `OPENAI_API_KEY` | — | 필수 |
| `FEEDIT_LLM_MODEL_LARGE` | `gpt-5.6-sol` | 아직 어느 역할도 안 쓴다 |
| `FEEDIT_LLM_MODEL_MID` | `gpt-5.6-terra` | 오케스트레이터 · 해석 · 조언 |
| `FEEDIT_LLM_MODEL_SMALL` | `gpt-5.6-luna` | 검증 · 발췌 · 다듬기 · 되묻기 |
| `FEEDIT_TOOL_WEB_SEARCH` | (꺼짐) | 호스티드 웹검색 |
| `FEEDIT_MCP_SERVERS` | (없음) | MCP 서버 JSON 배열 |
| `FEEDIT_LLM_DISABLED` | (꺼짐) | 모델 호출을 막는다 (테스트용) |

**모델을 왜 이렇게 나눴나** — 큰 모델을 다 쓰면 비싸고, 작은 모델을 다 쓰면
판단이 무너진다. 기준은 **"이 자리가 만들어 내는 일인가, 맞춰 보는 일인가"** 다.
검증은 창작이 아니라 일치 확인이고 출력이 스키마로 닫혀 있어서, 큰 모델로 올려도
얻는 게 거의 없다. 판단을 만들어야 하는 자리는 L1·L2 다.
`luna` 가 `terra` 보다 **기능이 적은 게 아니라** 깊이와 값이 다를 뿐이라,
작은 모델을 놓은 자리도 성능 저하가 아니다.

---

## 8. 손대기 전에 돌려 볼 것

```bash
# 1) 문법·import
cd ChatBot && python3 -c "from app import store, tools, orchestrator, verify, agent_path, agent_blocks; print('ok')"

# 2) 근거 링크가 실제 DB 에서 나오나
python3 - <<'PY'
import sys, os; sys.path.insert(0, '.')
from app import store as S
st = S.ReadOnlyStore(os.environ['FEEDIT_CRAWLER_DIR'] + '/data/feedit.db')
for e in st.term_evidence('material:스웨이드', limit=3):
    print(e['platform'], e['at'], e['url'] or '(원문 링크 없음)')
PY

# 3) 프론트 렌더 테스트 (7번 실패는 알려진 것)
FEEDIT_WEB=../frontend bash tests/run.sh
```

---

## 9. 물어볼 사람

이 부분은 혁진이 작업했다. 설계 의도는 각 파일 **머리말 주석**에 다 적혀 있다 —
`orchestrator.py` · `verify.py` · `agent_blocks.py` 세 개의 머리말을 읽으면
"왜 이렇게 했나" 는 대부분 답이 나온다. 코드보다 그 주석이 먼저다.
