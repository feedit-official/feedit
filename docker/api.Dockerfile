# Django API 및 경량 Celery 작업 이미지. OCR·GPU·브라우저 분석은 web.Dockerfile을 사용합니다.
# API는 RDS 읽기/쓰기와 사용자 기능을 제공하며 worker는 수집·텍스트 분석을 수행합니다.

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/requirements-api.txt /tmp/requirements-api.txt

RUN pip install --no-cache-dir -r /tmp/requirements-api.txt

COPY backend/ /app/
