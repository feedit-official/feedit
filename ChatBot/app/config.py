"""feedit-chat — 경로와 상수 한 곳.

이 서비스는 **따로 선다.** 크롤러도 Django 도 건드리지 않는다.
나중에 백엔드에 합칠 때 이 파일의 경로만 갈아 끼우면 되도록 모아 뒀다.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # feedit-chat/
WORKSPACE = ROOT.parent                            # Final/
CRAWLER = WORKSPACE / "feedit-crawler"

# 지금은 크롤러 SQLite 를 읽기 전용으로 본다.
#   여기가 지표계산 설계서의 값이 실제로 있는 유일한 곳이다.
#   AWS RDS(Django) 에는 temp·momentum·ma7·ma28 컬럼이 없다 — 설계서 2.2b.
DB_PATH = Path(os.getenv("FEEDIT_CHAT_DB", CRAWLER / "data" / "feedit.db"))
LEXICON_PATH = Path(os.getenv("FEEDIT_CHAT_LEXICON", CRAWLER / "config" / "lexicon.yaml"))

# 어휘 추출기 (검증 완료 — 설계서 3.3)
EXTRACTOR_DIR = WORKSPACE / "tools"

METRIC_VERSION = os.getenv("FEEDIT_METRIC_VERSION", "feedit-l2-v2-shadow")

# ── 시계열을 말해도 되는 최소 관측 (2026-09-02 실측으로 정한 값) ──
#   최신일 기준 창 안에 관측이 이만큼은 있어야 그 지표를 입에 올린다.
#   실측 결과 — 최신 2026-09-01, term 509개
#       n7>=3   123개    ma7 을 말할 수 있다
#       n14>=5   93개    2주 변화를 말할 수 있다
#       n28>=10  72개    방향(ma7/ma28)을 말할 수 있다
#   축별로는 브랜드가 223개 중 n7>=3 이 2개뿐이다. 브랜드는 방향을 못 말한다.
MIN_OBS_7 = 3
MIN_OBS_14 = 5
MIN_OBS_28 = 10

# 표본이 이보다 적으면 숫자 옆에 경고를 붙인다.
#   trend_chat.py 가 이미 쓰는 기준을 그대로 가져왔다. 새로 만들면 화면과 다른 말을 하게 된다.
THIN_SAMPLE = 20

# 챗봇이 검색어(주어)로 인정하는 축
SEARCH_FACETS = ("style", "material", "item", "brand")

# 온도 구간 — trend_chat.temperature_label() 과 같은 경계를 쓴다
TEMP_BANDS = ((25, "차가움"), (50, "미지근"), (75, "따뜻함"), (101, "과열"))


def temp_band(value) -> str:
    v = float(value or 0)
    for edge, name in TEMP_BANDS:
        if v < edge:
            return name
    return "과열"
