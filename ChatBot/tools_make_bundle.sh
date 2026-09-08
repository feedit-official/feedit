#!/usr/bin/env bash
# 챗봇이 돌아가는 데 **꼭 필요한 것만** 묶는다.
#
# ── 왜 이게 필요한가 ──────────────────────────────────────
# 크롤러 저장소는 1.6GB 다. 그런데 챗봇이 실제로 읽는 건 다섯 개뿐이고
# 합쳐서 42MB 다. 서버에 크롤러를 통째로 올릴 이유가 없다.
#
#   crawler/data/feedit.db              지표 (42MB)
#   crawler/config/lexicon.yaml         어휘 사전
#   crawler/feedit_crawler/lexicon.py   lexicon_gate 가 import
#   crawler/feedit_crawler/__init__.py  위 import 를 위한 패키지 표시
#   tools/question_extract.py           어휘 추출기
#
# 둘 다 표준 라이브러리와 PyYAML 만 쓴다 — 크롤러의 다른 코드를 안 끌고 온다.
# (2026-09-08 확인: 이 다섯 개만으로 엔진이 부팅되고 답까지 나온다)
#
# ── 쓰는 법 ──────────────────────────────────────────────
#   ./tools_make_bundle.sh                     .env 의 경로를 쓴다
#   ./tools_make_bundle.sh /경로/feedit-crawler /경로/tools
#
# 결과: feedit-chat-bundle.tar.gz
#   scp feedit-chat-bundle.tar.gz  ec2-user@서버:/tmp/
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

# 경로: 인자 > .env > 포기
CRAWLER="${1:-}"
TOOLS="${2:-}"
if [ -z "$CRAWLER" ] && [ -f "$REPO/.env" ]; then
  CRAWLER=$(grep -E '^FEEDIT_CRAWLER_DIR=' "$REPO/.env" | tail -1 | cut -d= -f2-)
  TOOLS=$(grep -E '^FEEDIT_EXTRACTOR_DIR=' "$REPO/.env" | tail -1 | cut -d= -f2- || true)
fi
[ -n "${TOOLS:-}" ] || TOOLS="$(dirname "$CRAWLER")/tools"

if [ -z "$CRAWLER" ] || [ ! -d "$CRAWLER" ]; then
  echo "크롤러 저장소를 못 찾았습니다: '${CRAWLER:-(비어 있음)}'" >&2
  echo "  .env 에 FEEDIT_CRAWLER_DIR 을 넣거나, 인자로 주세요." >&2
  exit 1
fi

OUT="$HERE/feedit-chat-bundle.tar.gz"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/bundle/crawler/data" \
         "$STAGE/bundle/crawler/config" \
         "$STAGE/bundle/crawler/feedit_crawler" \
         "$STAGE/bundle/tools"

need() {   # 없으면 그 자리에서 멈춘다 — 반쪽 묶음을 서버에 올리면 거기서 헤맨다
  [ -f "$1" ] || { echo "없습니다: $1" >&2; exit 1; }
  cp "$1" "$2"
}
need "$CRAWLER/data/feedit.db"             "$STAGE/bundle/crawler/data/"
need "$CRAWLER/config/lexicon.yaml"        "$STAGE/bundle/crawler/config/"
need "$CRAWLER/feedit_crawler/lexicon.py"  "$STAGE/bundle/crawler/feedit_crawler/"
need "$CRAWLER/feedit_crawler/__init__.py" "$STAGE/bundle/crawler/feedit_crawler/"
need "$TOOLS/question_extract.py"          "$STAGE/bundle/tools/"

tar -czf "$OUT" -C "$STAGE" bundle

echo "만들었습니다: $OUT  ($(du -h "$OUT" | cut -f1))"
echo
echo "서버에 올리기:"
echo "  scp $OUT  <사용자>@<서버>:/tmp/"
echo
echo "서버에서 풀기:"
echo "  sudo mkdir -p /opt/feedit-chat-data"
echo "  sudo tar -xzf /tmp/feedit-chat-bundle.tar.gz -C /opt/feedit-chat-data --strip-components=1"
echo
echo "서버 .env 에 두 줄:"
echo "  FEEDIT_CRAWLER_DIR=/opt/feedit-chat-data/crawler"
echo "  FEEDIT_EXTRACTOR_DIR=/opt/feedit-chat-data/tools"
