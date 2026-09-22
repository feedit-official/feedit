# 수동 진단 도구

기준일: 2026-09-22. Django 환경과 DB 접근이 준비된 상태에서 사용합니다. 앱 등록 대상이 아닙니다.

`perf_check.py`는 관리자 페이지 응답 시간과 쿼리 수를 확인합니다. 저장소 루트에서:

```bash
docker compose -f docker/compose.api.yml exec api python manage.py shell -c "exec(open('tools/perf_check.py').read())"
```

쿼리가 많으면 반복 조회를, 소수의 쿼리가 느리면 실행 계획과 대용량 컬럼을, 쿼리 외 시간이 길면 외부 호출을 확인합니다. 운영 DB에 부하를 줄 수 있으므로 반복 실행 빈도를 조절합니다.

`check_salmal_segment.py`는 살말 관련 세그먼트 점검 도구입니다. 실행 전 현재 코드를 읽고 필요한 데이터 범위를 확인하세요.
