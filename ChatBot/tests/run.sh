#!/usr/bin/env bash
# 테스트 하네스.
#
# 왜 딴 데로 복사해서 도나 —
#  (1) 테스트가 feedit-web 을 상대경로로 import 한다. 두 저장소가 나란히 있다는
#      보장이 없으니 한자리에 모아 놓고 돈다.
#  (2) 마운트된 사용자 폴더 안에서는 rm 이 막혀 있어 뒷정리를 못 한다.
#      그래서 무대는 $HOME 스크래치에 차린다. 사용자 폴더에는 아무것도 남기지 않는다.
# 복사본을 편집하지 말 것 — 매 실행마다 원본에서 새로 만든다.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
web="${FEEDIT_WEB:-$here/../../feedit-web}"
stage="${TMPDIR:-/tmp}/feedit-chat-tests"

[ -d "$web/home" ] || { echo "feedit-web 을 못 찾음: $web  (FEEDIT_WEB=... 로 지정)"; exit 2; }

rm -rf "$stage"; mkdir -p "$stage/app" "$stage/css"
cp "$here"/*.test.mjs "$here"/popup.html "$stage"/
cp -r "$here"/sse "$stage"/ 2>/dev/null || true
cp "$here"/fixtures.json "$stage/_chat_fixtures.json"
# 기능 폴더 구조를 그대로 뜬다 — chat_popup.js 가 ../../../core/static/js/dom.js 를 부른다
for d in core home app_shell trend salmal style account; do
  [ -d "$web/$d/static/js" ] && mkdir -p "$stage/app/$d/static/js" \
    && cp "$web/$d/static/js/"*.js "$stage/app/$d/static/js/" 2>/dev/null || true
done
cp "$web"/home/static/js/chat_api.js "$stage/chat_api.js"
# CSS 는 전부 모은다 — 클래스 존재 검사는 feedit-web 전체가 기준이다
find "$web" -name '*.css' -not -path '*/node_modules/*' -exec cp {} "$stage/css/" \;
ln -s "$here/../node_modules" "$stage/node_modules" 2>/dev/null || true

cd "$stage"
fail=0
for f in *.test.mjs; do
  printf '\n── %s\n' "$f"
  node "$f" || fail=1
done
cd /; rm -rf "$stage"
[ "$fail" = 0 ] && echo "전부 통과" || echo "실패 있음"
exit $fail
