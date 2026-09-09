# 읽기 전용 API 만 담는 이미지 — 2026-09-09
#
# web.Dockerfile 과 무엇이 다른가
#   · requirements-api.txt 만 설치한다 (128개 → 20개)
#   · playwright·chromium 을 안 받는다
#   · gcc·libpq-dev 를 안 깐다 — psycopg-binary 가 이미 컴파일된 것이라
#     빌드 도구가 필요 없다
#
# 결과: EC2 에서 몇 분이면 빌드가 끝난다. web.Dockerfile 로는
# torch(2.5GB급) 때문에 작은 인스턴스에서 사실상 안 끝난다.
#
# 크롤러·OCR·비전을 서버에서 돌릴 일이 생기면 그때는 web.Dockerfile 을 쓴다.
# 이 이미지는 "RDS 를 읽어 JSON 을 준다" 하나만 한다.

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/requirements-api.txt /tmp/requirements-api.txt

RUN pip install --no-cache-dir -r /tmp/requirements-api.txt

COPY backend/ /app/
