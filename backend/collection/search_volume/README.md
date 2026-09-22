# 검색량 수집 도구

기준일: 2026-09-22. `main.py`의 실제 CLI와 현재 모노레포 경로 기준입니다.

이 도구는 사전 CSV에서 키워드를 읽고 공급자별 데이터를 수집해 로컬 raw/processed 파일을 생성합니다. RDS 적재는 Django 관리 명령의 후속 단계입니다. S3/RDS까지 자동 완료되는 단일 명령으로 취급하지 않습니다.

## 설정과 실행

저장소 루트 `.env`를 우선 읽고 패키지 내부 `.env`, `sv_config/.env`를 호환 경로로 읽습니다. 필요한 네이버/Google 설정은 `sv_config/settings.py`와 루트 환경 예시를 참고합니다.

```bash
# backend/에서, 전체 분석 환경 또는 이 패키지 requirements 준비 후
python collection/search_volume/main.py --dry-run
python collection/search_volume/main.py --source naver
python collection/search_volume/main.py --source google --csv /path/to/dictionary.csv
python collection/search_volume/main.py --source all --verbose

# 생성 파일을 확인한 뒤 별도 적재
python manage.py load_search_metrics --dir /path/to/output/processed/TIMESTAMP
```

`--skip-s3`, `--skip-rds`는 현재 CLI 옵션이 아닙니다. `--dry-run`은 공급자 수집 호출 없이 구조·설정을 점검하며 키워드 입력은 필요합니다. API 키·고객 식별 정보를 실행 결과와 함께 공유하지 마세요.

## 동작 범위

네이버 검색광고, Google Trends, Google Keyword 관련 수집 코드가 있습니다. 메인 파이프라인의 네이버 데이터랩 호출은 현재 주석 처리되어 있습니다. 상대 추이를 앵커 기반으로 정규화한 값은 관측 절대값과 구분해야 합니다.

정기 태스크 `collect_search_daily`/`collect_search_weekly`는 별도 경로입니다. 저장 모델은 현재 Django의 검색 지표 모델과 관리 명령을 기준으로 확인합니다. 이전 문서의 `keyword_monthly_volume` 같은 독립 프로젝트 테이블 명칭을 현재 RDS 스키마로 사용하지 않습니다.

[전체 데이터 흐름](../../../docs/DATA_PIPELINE.md) · [기술 명세](../../../docs/TECHNOLOGY.md)
