# feedit-chat — 챗봇 서버
#
# ★ web.Dockerfile 과 따로 둔다.
#   web 쪽은 torch·easyocr·playwright 까지 깔아 이미지가 수 GB 다.
#   챗봇이 실제로 쓰는 건 requests 와 PyYAML 뿐이라, 같이 묶으면
#   챗봇 코드 한 줄 고칠 때마다 그 무거운 빌드를 다시 기다리게 된다.

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 의존성을 먼저 깔아 레이어를 캐시한다 — 코드만 바뀌면 재설치가 없다.
COPY ChatBot/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY ChatBot/ /app/

# 컨테이너 안에서는 밖에서 닿아야 하므로 0.0.0.0 에 연다.
#   ★ 그래도 compose 가 포트를 호스트의 127.0.0.1 에만 묶는다.
#     인증이 아직 없어서 인터넷에 내놓으면 안 된다.
ENV FEEDIT_CHAT_HOST=0.0.0.0
ENV FEEDIT_CHAT_PORT=8770

# 크롤러 저장소는 compose 가 읽기 전용으로 마운트한다.
ENV FEEDIT_CRAWLER_DIR=/crawler

EXPOSE 8770

# 준비물이 없으면 server.py 가 무엇이 없는지 말하고 종료 코드 2 로 멈춘다.
CMD ["python3", "server.py"]
