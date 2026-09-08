# SSM 굴 — 사설 RDS 로 나가는 길.
#
# ══════════════════════════════════════════════════════════════
#  2026-09-08 — 빌드가 깨져서 고친 것
# ══════════════════════════════════════════════════════════════
# 전에는 두 내려받기가 **x86_64 로 박혀** 있었다.
#   awscli-exe-linux-x86_64.zip · plugin/latest/ubuntu_64bit/…
# 애플 실리콘 맥에서 빌드하면 ubuntu:24.04 가 arm64 로 잡히므로
# 아키텍처가 어긋나 dpkg 가 거절한다.
#
# 그리고 curl 에 -f 가 없었다. 404 나 오류 응답이 와도 **그 오류 본문을
# .deb 로 저장하고** 다음 줄로 넘어간다. 그러면 dpkg 가
# "not a Debian format archive" 를 내는데, 진짜 원인(내려받기 실패)은
# 화면 어디에도 안 남는다. 이제 -f 로 그 자리에서 멈춘다.

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        unzip \
        socat \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# AWS CLI v2 — 이 이미지의 아키텍처에 맞는 것을 받는다.
RUN set -eux; \
    case "$(dpkg --print-architecture)" in \
      amd64) AWS_ARCH=x86_64  ;; \
      arm64) AWS_ARCH=aarch64 ;; \
      *) echo "지원하지 않는 아키텍처: $(dpkg --print-architecture)" >&2; exit 1 ;; \
    esac; \
    curl -fsSL --retry 3 --retry-delay 2 \
        "https://awscli.amazonaws.com/awscli-exe-linux-${AWS_ARCH}.zip" \
        -o /tmp/awscliv2.zip; \
    unzip -q /tmp/awscliv2.zip -d /tmp; \
    /tmp/aws/install; \
    rm -rf /tmp/aws /tmp/awscliv2.zip; \
    aws --version

# AWS Session Manager Plugin — 같은 이유로 아키텍처를 따라간다.
#   ★ dpkg -i 대신 apt-get install ./…deb 를 쓴다.
#     dpkg 는 의존 패키지를 못 채우고 "dependency problems" 로 멈춘다.
RUN set -eux; \
    case "$(dpkg --print-architecture)" in \
      amd64) SSM_DIR=ubuntu_64bit ;; \
      arm64) SSM_DIR=ubuntu_arm64 ;; \
      *) echo "지원하지 않는 아키텍처: $(dpkg --print-architecture)" >&2; exit 1 ;; \
    esac; \
    curl -fsSL --retry 3 --retry-delay 2 \
        "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/${SSM_DIR}/session-manager-plugin.deb" \
        -o /tmp/session-manager-plugin.deb; \
    apt-get update; \
    apt-get install -y --no-install-recommends /tmp/session-manager-plugin.deb; \
    rm -rf /tmp/session-manager-plugin.deb /var/lib/apt/lists/*; \
    session-manager-plugin --version
