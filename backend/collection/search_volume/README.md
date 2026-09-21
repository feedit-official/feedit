# 패션 트렌드 키워드 검색량 수집 파이프라인

네이버/구글에서 패션 관련 키워드의 검색량을 API로 수집하여 S3에 적재 → 정규화 전처리 → RDS(PostgreSQL)에 적재하는 Python 데이터 파이프라인입니다.

## 아키텍처

```
키워드 파일 (fashion_keywords.txt)
        │
        ▼
┌─────────────────────────────────┐
│    STEP 1: Collect (수집)        │
│  ┌───────────────┐  ┌──────────┐│
│  │ 네이버 검색광고 │  │ 네이버    ││
│  │ (월간 절대값)   │  │ 데이터랩  ││
│  └───────┬───────┘  └────┬─────┘│
│  ┌───────────────┐  ┌──────────┐│
│  │ Google Trends  │  │ Google   ││
│  │ (pytrends)     │  │ Keyword  ││
│  └───────┬───────┘  └────┬─────┘│
└──────────┼───────────────┼──────┘
           ▼               ▼
┌─────────────────────────────────┐
│  STEP 2: Store Raw (S3 적재)     │
│  s3://bucket/raw/{source}/{date} │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│  STEP 3: Process (정규화)        │
│  상대값 → 절대값 치환 공식:       │
│  B = (B_ratio / A_ratio) × A_vol │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│  STEP 4: Load (RDS 적재)         │
│  PostgreSQL Tables:              │
│  - keyword_monthly_volume        │
│  - keyword_trend                 │
│  - collection_log                │
└─────────────────────────────────┘
```

## 빠른 시작

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. 환경변수 설정

```bash
# .env.example을 복사하여 .env 파일 생성
cp config/.env.example config/.env

# .env 파일을 열어서 API 키와 AWS 정보 입력
```

### 3. 키워드 설정

`keywords/fashion_keywords.txt` 파일에 검색할 키워드를 한 줄에 하나씩 입력합니다.

### 4. 실행

```bash
# 전체 파이프라인 실행
python main.py

# Dry Run (API 호출 없이 구조 검증)
python main.py --dry-run

# 네이버만 수집
python main.py --source naver

# 구글만 수집
python main.py --source google

# S3/RDS 건너뛰기 (로컬 파일만 저장)
python main.py --skip-s3 --skip-rds

# 상세 로그
python main.py --verbose
```

## API 키 발급 가이드

### 네이버 검색광고 API
1. [searchad.naver.com](https://searchad.naver.com) 접속 → 회원가입/로그인
2. 좌측 메뉴 → 도구 → API 사용 관리
3. API 키 발급 (API_KEY, SECRET_KEY, CUSTOMER_ID)

### 네이버 데이터랩 API
1. [developers.naver.com](https://developers.naver.com) 접속 → 로그인
2. Application → 애플리케이션 등록
3. 사용 API에서 "데이터랩 (검색어트렌드)" 선택
4. CLIENT_ID, CLIENT_SECRET 발급

### Google Trends
- API 키 불필요 (pytrends 라이브러리 사용)

### Google Keyword Planner (선택)
1. [Google Ads](https://ads.google.com) 계정 생성
2. API 개발자 토큰 발급 (승인까지 며칠 소요)
3. OAuth2 인증 설정

## 프로젝트 구조

```
navergoogle/
├── config/
│   ├── .env.example          # 환경변수 템플릿
│   └── settings.py           # 설정 관리
├── collectors/
│   ├── naver_searchad.py     # 네이버 검색광고 API
│   ├── naver_datalab.py      # 네이버 데이터랩 API
│   ├── google_trends.py      # Google Trends
│   └── google_keyword.py     # Google Keyword Planner
├── processors/
│   ├── normalizer.py         # 정규화 전처리 (상대값→절대값)
│   └── transformer.py        # 데이터 변환/통합
├── storage/
│   ├── s3_uploader.py        # S3 적재
│   └── rds_loader.py         # PostgreSQL RDS 적재
├── keywords/
│   └── fashion_keywords.txt  # 패션 키워드 목록
├── requirements.txt          # 의존성
├── main.py                   # 파이프라인 메인
└── README.md                 # 이 파일
```

## DB 스키마

### keyword_monthly_volume
| 컬럼 | 타입 | 설명 |
|------|------|------|
| keyword | VARCHAR(200) | 키워드 |
| platform | VARCHAR(20) | 'naver' / 'google' |
| year_month | VARCHAR(7) | '2026-09' |
| pc_search_volume | BIGINT | PC 월간 검색량 |
| mobile_search_volume | BIGINT | 모바일 월간 검색량 |
| total_search_volume | BIGINT | 총 월간 검색량 |
| competition_level | VARCHAR(20) | 경쟁정도 |

### keyword_trend
| 컬럼 | 타입 | 설명 |
|------|------|------|
| keyword | VARCHAR(200) | 키워드 |
| platform | VARCHAR(20) | 'naver' / 'google' |
| period | DATE | 날짜 |
| ratio | FLOAT | 상대값 (0~100) |
| estimated_volume | BIGINT | 추정 절대 검색량 |
