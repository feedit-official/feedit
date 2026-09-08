# feedit-chat

FEEDiT 챗봇 — **따로 선다.** 크롤러도 Django 도 고치지 않는다.

프론트(`feedit-web`)와 먼저 붙이고, 나중에 백엔드로 그대로 넘겨 합친다.
그래서 합칠 때 갈아 끼울 곳을 한 군데로 모아 뒀다 — `app/config.py` 와 `app/store.py`.

---

## 지금 어디서 데이터를 읽나

```
feedit-crawler/data/feedit.db   (SQLite, 읽기 전용)
```

여기가 **지표계산 설계서의 값이 실제로 있는 유일한 곳**이다.
AWS RDS(Django)에는 `temp` · `momentum` · `ma7` · `ma28` 컬럼이 아예 없다.
합칠 때 `store.py` 의 SQL 만 Django ORM 으로 바꾸면 나머지는 그대로 간다.

**쓰지 않는다.** `mode=ro` 로 열어 실수로도 못 쓰게 해 뒀다.
**계산하지 않는다.** 온도·연관어는 `crawler/metrics.py` 가 원본이다.
여기서 다시 계산하면 화면과 챗봇이 다른 숫자를 말한다.

---

## 처음 켜는 사람에게 — 5분

```bash
git clone https://github.com/feedit-official/feedit.git
cd feedit

cp .env.example .env          # ① 값을 채운다 (아래 두 줄이 핵심)
python3 ChatBot/tools_env_check.py   # ② 무엇이 없는지 화면에 나온다
```

`.env` 에서 **반드시** 채워야 하는 두 줄:

```bash
OPENAI_API_KEY=sk-...                          # 각자 발급 (platform.openai.com)
FEEDIT_CRAWLER_DIR=/절대/경로/feedit-crawler     # 크롤러 저장소를 받아 둔 곳
```

`tools_env_check.py` 가 ✔ 만 찍으면 그때 켠다.

```bash
python3 ChatBot/tools_llm_check.py   # 모델을 실제로 한 번 불러 본다 (네트워크 필요)
cd ChatBot && python3 server.py      # http://127.0.0.1:8770
```

### ★ 왜 크롤러 저장소가 따로 필요한가

이 저장소에는 **지표 데이터도, 어휘 사전도 없다.** 챗봇은 크롤러 쪽의
네 가지를 그대로 쓴다 — 데이터 둘, **코드 둘**이다.

| 필요한 것 | 어디에 쓰나 |
| --- | --- |
| `data/feedit.db` | 지표 (`store.py` 가 읽기 전용으로 연다) |
| `config/lexicon.yaml` | 어휘 사전 |
| `feedit_crawler/lexicon.py` | `lexicon_gate.py` 가 **import** 한다 |
| `tools/question_extract.py` | 어휘 추출기 — 복사하지 않고 재사용한다 |

없으면 `server.py` 가 무엇이 없는지 찍고 멈춘다. 조용히 죽지 않는다.

> RDS 로 옮기는 길은 아직 열려 있지 않다. `docs_RDS_격차분석.md` 기준으로
> `analysis.term_metric_daily` 는 **컬럼만 있고 적재 코드가 없어 비어 있고**,
> `metric_term_sentiment_daily` · `text_entity_opinion` · `text_entity_mention` 은
> 표 자체가 없다. 그 셋이 채워지기 전까지는 크롤러 SQLite 가 유일한 원본이다.

### 키가 없는 팀원도 화면은 본다

`.env` 에 `FEEDIT_LLM_DISABLED=1` 을 넣으면 LLM 을 아예 안 부르고 규칙으로만 돈다.
답이 조금 딱딱해질 뿐 화면은 전부 그려진다.

---

## 도커로 띄우기

```bash
docker compose -f docker/compose.yml up chatbot
```

`.env` 하나로 Django·Redis·챗봇이 같은 값을 본다.
크롤러 저장소는 `FEEDIT_CRAWLER_DIR` 을 읽기 전용으로 마운트한다.

크롤러가 없으면 챗봇만 빼고 쓴다:

```bash
docker compose -f docker/compose.yml up ssm-tunnel redis web
```

> ★ 포트는 `127.0.0.1:8770` 에만 묶여 있다. **인증이 없기 때문이다.**
> 배포용 `compose.prod.yml` 에서도 챗봇은 밖으로 열지 않았다 —
> 공개하려면 인증을 먼저 붙여야 한다. 그 순서는 `compose.prod.yml` 주석에 있다.

---

## 돌려 보기

```bash
cd ChatBot

python3 tools_env_check.py  # 설정 점검 (네트워크 안 씀)
python3 smoke.py            # 진짜 DB 로 10개 질문을 돌린다 (서버 없이)
python3 server.py           # http://127.0.0.1:8770
```

의존성은 두 개뿐이다 (`requests` · `PyYAML` — `ChatBot/requirements.txt`).
서버도 표준 라이브러리로만 짰다 — FastAPI 를 안 쓴 이유는 `server.py` 맨 위에 적어 뒀다.
`.env` 는 `app/env.py` 가 표준 라이브러리로 읽는다. python-dotenv 도 필요 없다.

### 프론트와 붙이기

```bash
# 1) 챗봇 서버
cd feedit/ChatBot && python3 server.py

# 2) 프론트 (다른 창)
cd feedit/frontend && npm run dev
```

`vite.config.js` 에 `/api → 127.0.0.1:8770` 프록시를 넣어 뒀다.
브라우저 입장에서 같은 출처라 CORS 가 아예 생기지 않는다.

**서버를 안 켜도 프론트는 그냥 돈다.** 챗봇만 기존 목업 응답으로 떨어진다.
데모가 서버 유무에 좌우되면 안 되기 때문이다.

플랜을 바꿔 보려면 브라우저 콘솔에서:

```js
window.FEEDIT_PLAN = 'FREE'   // 기본값은 'PRO'
```

인증이 아직 없다. 서버는 요청에 실린 plan 을 그대로 믿는다. **개발용이다.**

## API

```
GET  /v1/health                 떠 있나 · 기준일 · 적재 term 수
GET  /v1/llm                    LLM 배선 진단 — 모델 · 키 유무 · 마지막 오류
                                (★ 키 값은 안 나간다. 길이만 나온다)
GET  /v1/me?plan=FREE           플랜과 하루 한도
POST /v1/chat                   SSE — status → text → report → actions → done
POST /v1/lexicon/requests       어휘 등록 요청 → data/lexicon_requests.jsonl
```

SSE 순서는 프론트가 이미 그리는 순서에 맞췄다 —
글자를 먼저 흘리고 카드를 나중에 보내야 `.ansCard.reveal.in` 이 뒤따라 떠오른다.

등록 요청은 지금 파일에 쌓인다. 배포되면 RDS 의 `dictionary.term_candidate` 로 간다.
**버튼만 만들어 두고 아무 데도 안 보내면 "누르면 되는 척" 이 된다.** 그래서 실제로 남긴다.

## 검증

```bash
cd ~/Desktop/Final/feedit-web && npm i -D jsdom      # 한 번만
cd ../feedit-chat/tests
node render.test.mjs         # 렌더러 단위 — 쓰는 CSS 클래스가 실제로 있는지까지 본다
node popup.test.mjs          # 팝업 통합 — 서버 있을 때 / 죽었을 때 / FREE / 사전 밖
node blocks.test.mjs         # 의도별 구조가 실제로 다른가 + 모르는 블록 방어
node fallback_leak.test.mjs  # 목업이 진짜 답 위로 새지 않는가 (회귀)
```

`tests/sse/*.sse` 는 **진짜 서버 출력**이다. 형식을 흉내낸 게 아니다.
`tests/fixtures.json` 도 실제 DB 로 만든 응답 그대로다.

`node --check` 는 문법만 본다. 정의되지 않은 이름을 부르는 코드를 통과시키므로
프론트 코드는 반드시 jsdom 으로 돌려야 한다 (AGENTS.md §5).

---

## 구조

```
app/
  env.py          저장소 .env 읽기 (표준 라이브러리).  ← 키가 들어오는 유일한 문
  config.py       경로 · 임계값 한 곳.  ← 합칠 때 여기부터 본다
  store.py        크롤러 SQLite 읽기 전용 어댑터
  coverage.py     "이 term 에 대해 무엇을 말해도 되는가"  ← 정직함이 여기서 나온다
  lexicon_gate.py 어휘 게이트 (tools/question_extract.py 재사용)
  intents.py      의도 분류 (규칙)
  blocks.py       응답 블록 만들기 — 프론트에 실제로 있는 것만
  templates.py    의도 → 어떤 블록을 쓸 것인가.  ★ 구조의 원본은 여기 하나
  nlu.py          ① 의도 분류에 Luna 를 얹는다 — 규칙이 못 잡을 때만
  polish.py       ② 어투 다듬기 — 숫자를 자리표시자로 봉인
  websearch.py    ③ 웹 검색 요약 — 출처 없으면 안 올린다
  llm.py          Luna 클라이언트 (OpenAI Responses API)
  plans.py        플랜 게이팅 · 한도
  report.py       리포트 조립 · 한 줄 결론
  engine.py       입구.  ChatEngine().ask(질문, mode, plan)
smoke.py          실데이터 스모크
server.py         SSE 개발 서버
tools_env_check.py  켜기 전 점검 — 무엇이 없는지 (네트워크 안 씀)
tools_llm_check.py  Luna 연결·3기능 실호출 (네트워크 필요)
requirements.txt    requests · PyYAML 둘뿐
tests/            jsdom 검증
```

---

## 질문 유형마다 응답 구조가 다르다

같은 카드에 다른 내용을 담는 게 아니라, **구조 자체가 달라진다.**

```
metric.level       rank[왼] · bars[오] · quotes[오] · note
metric.direction   kpis[전체폭] · rank[왼] · bars[오]          ← 방향이 맨 위로 온다
metric.assoc       rank[왼: 연관어] · bars[오: 축별 비중]
metric.sentiment   kpis[전체폭: 지수·긍정·부정] · rank · quotes
metric.platform    rank[왼] · mTable[오: 플랫폼별 온도] · bars
metric.compare     bars[전체폭: 나란히] · rank · bars
knowledge.origin   prose[왼: 웹 요약] · links[왼: 출처] · rank[오: 우리 지표]
FREE 플랜          잠긴 블록이 통째로 빠지고 upsell 이 그 자리에 온다
```

### 이걸 프롬프트로 하지 않는 이유 세 가지

1. **화면이 깨진다.** LLM 이 없는 CSS 클래스를 지어내면 버튼이 맨 글자로 나온다.
   AGENTS.md §4.2 가 적어 둔 실제 사고다.
2. **매번 다르다.** 같은 질문에 어제와 오늘 구조가 다르면 그건 제품이 아니다.
3. **숫자가 샌다.** 구조를 LLM 이 만들면 그 안의 값도 LLM 이 쓰게 된다.

### 그래서 어떻게 하나

```
app/blocks.py      블록을 만든다.   프론트에 실제로 있는 것만 만든다
app/templates.py   의도 → 블록 목록.  ★ 구조의 원본은 이 파일 하나
chat_api.js        블록 타입별로 그린다. 모르는 타입은 조용히 건너뛴다
```

LLM 은 구조를 **만들지 않는다.** 애매할 때 `templates.CHOOSABLE` 목록에서 고르는 것만 할 수 있다.
목록 밖은 나올 수가 없다.

블록을 새로 만들 때는 **CSS 에 그 클래스가 있는지 먼저 확인한다.**
`blocks.test.mjs` 가 쓰는 클래스를 전부 CSS 와 대조하므로, 없는 걸 쓰면 시험이 잡는다.

## Luna(LLM)를 쓰는 곳 — 세 자리뿐

```
① 의도 분류    app/nlu.py        규칙이 못 잡을 때만 부른다
② 어투 다듬기  app/polish.py     값을 다 꽂은 뒤 문장만
③ 웹 검색      app/websearch.py  지식 질문. 출처 없으면 안 올린다
```

모델은 크롤러와 같은 `gpt-5.6-luna` 다. 두 곳이 다른 모델을 쓰면 "왜 답이 다르지" 를 못 쫓는다.

설정은 전부 `.env` 로 뺐다 — 코드를 고쳐 모델을 바꾸면 누가 언제 바꿨는지 기록에 안 남는다.

| 환경변수 | 기본값 | |
| --- | --- | --- |
| `OPENAI_API_KEY` | — | 각자 발급. 없으면 규칙으로만 돈다 |
| `FEEDIT_LLM_MODEL` | `gpt-5.6-luna` | 팀 표준. 바꾸면 팀에 알린다 |
| `FEEDIT_LLM_EFFORT` | `low` | `none`·`low`·`medium`·`high`·`xhigh`·`max` |
| `FEEDIT_LLM_DISABLED` | `0` | `1` 이면 LLM 을 아예 안 부른다 |
| `OPENAI_BASE_URL` | OpenAI | 사내 게이트웨이를 쓸 때만 |

키를 찾는 순서는 ① 환경변수 `OPENAI_API_KEY`(셸 · 도커 `env_file` · 저장소 `.env`)
② 크롤러 `data/keys.json` 이다. **어느 경로로도 키 값을 출력하지 않는다** — 예외 문구에도.

`effort` 는 목록 밖 값이 오면 `low` 로 되돌린다. 오타 하나로 챗봇 전체가
규칙으로 떨어지고 아무도 이유를 모르는 상황을 막기 위해서다.

안 붙을 때는 `GET /v1/llm` 을 열거나 `python3 tools_env_check.py` 를 돌린다.
`last_error` 가 `HTTP_401`(키 틀림) · `HTTP_404`(모델명 틀림) · `HTTP_429`(한도) 를
구분해서 알려 준다.

### LLM 이 하지 않는 것

| 안 시키는 것 | 왜 |
| --- | --- |
| 지표 해석 | 온도 86점의 뜻은 설계서가 원본이다. 맡기면 화면과 챗봇이 다른 말을 한다 |
| 엔티티 결정 | 4종 축 게이트는 사전이 정한다. 맡기면 사전에 없는 말이 뒷문으로 들어온다 |
| 숫자 | 값은 서버가 DB 에서 직접 꽂는다 |

### ② 숫자는 부탁하지 않고 봉인한다

"값을 바꾸지 마라" 라고 시켜도 모델은 86점을 87점으로, 333건을 300여 건으로 고친다.
악의가 아니라 문장을 다듬다 그렇게 된다. 그리고 그건 **지어낸 숫자**다.

그래서 보내기 전에 숫자를 자리표시자로 바꾼다.

```
발레코어의 트렌드 온도는 86점 · 과열입니다.
→ 발레코어의 트렌드 온도는 ⟦0⟧점 · 과열입니다.
```

모델은 ⟦0⟧ 이 무슨 값인지 모른다. **바꿀 수가 없다.**
돌아온 문장을 검사해 하나라도 어긋나면 원문을 그대로 쓴다.

검사 항목 — 자리표시자 개수·번호 일치 · 새 숫자 없음 · 태그 균형 · 재촉 금지어 · 길이.

### 셋 다 없어도 돌아간다

키가 없거나 호출이 실패하면 규칙으로 떨어진다. 응답에 흔적이 남는다.

```
nlu.source = 'rule' | 'llm' | 'rule_fallback'
tone       = 'rule' | 'llm'
notes      = WEB_UNAVAILABLE · WEB_NO_SOURCE · WEB_INJECTION
```

`ChatEngine(use_llm=False)` 로 아예 끌 수도 있다.

### 확인

```bash
python3 tools_llm_check.py     # 연결 + 세 기능을 한 번씩 실제 호출
```

**네트워크가 되는 곳에서 돌려야 한다.** Claude 작업 환경은 `api.openai.com` 이 막혀 있다.

## 두 가지 원칙

**1. 없는 건 없다고 한다.**

`coverage.py` 가 term 마다 무엇을 말해도 되는지 켜고 끈다.
관측일이 모자라면 방향을 말하지 않고, **왜 못 말하는지 이유를 같이 준다.**

```
발레코어  temp=86  raw=333
   ! SHORT_HISTORY: 최근 28일 중 관측이 6일뿐이라 오르는지 내리는지 말할 수 없습니다.
```

2026-09-02 실측 기준 (최신 2026-09-01, term 509개):

| 축 | term | 방향을 말할 수 있는 term |
| --- | --- | --- |
| item | 111 | 37 |
| material | 64 | 14 |
| detail | 41 | 13 |
| style | 34 | 8 |
| **brand** | **223** | **0** |
| fit·color·tpo | 36 | 0 (시계열 자체가 없다) |

**브랜드는 지금 온도만 말할 수 있고 방향은 못 말한다.** 223개 중 ma7 가능한 게 2개다.

**2. 숫자를 LLM 이 쓰지 않는다.**

문장은 자리표시자가 있는 틀이고, 값은 서버가 DB 반환값에서 직접 꽂는다.
LLM 은 어투만 다듬는다 (아직 안 붙였다). 그래야 지어낸 숫자가 구조적으로 불가능하다.

---

## 아직 없는 것

- 살!말? 모드 — 살!말?지수 계산 (설계서 7장). 수명주기 표와 가격 이력이 먼저 필요하다
- 멀티모달 · 착장 이미지
- 대화 저장 · 사용량 카운터 (플랜 한도는 값만 정해 뒀고 세지 않는다)
- 인증. 지금은 요청에 실린 plan 을 그대로 믿는다

## 합칠 때

1. `store.py` 를 Django ORM 으로 바꾼다. 나머지 모듈은 `store` 인터페이스만 본다
2. `plans.py` 의 플랜을 `AppUser.plan` 에서 읽는다
3. `report.compose()` 결과를 `ChatMessage.metadata` 에 그대로 저장한다

자세한 건 `../FEEDiT_챗봇_설계서.md` 11장.
