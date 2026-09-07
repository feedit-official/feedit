"""이 term 에 대해 무엇을 말해도 되는가.

챗봇의 정직함이 여기서 나온다.
데이터가 없는데 답하면 지어내는 것이고, 있는데 안 답하면 쓸모가 없다.
그 경계를 한 곳에서 정한다.

2026-09-02 실측 (최신 2026-09-01, term 509개, source `__all__`)

    축         term   n7>=3  n14>=5  n28>=10   최신일에 있음
    style        34      17      12        8            32
    item        111      56      43       37            96
    material     64      30      24       14            56
    brand       223       2       1        0           200   ← 방향을 말할 수 없다
    detail       41      18      13       13            31
    fit/color/tpo 36       0       0        0            36   ← 시계열이 아예 없다

브랜드가 223개 중 ma7 가능 2개다. **브랜드에 "오르는 중"이라고 말하면 안 된다.**
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from .config import MIN_OBS_7, MIN_OBS_14, MIN_OBS_28, THIN_SAMPLE


@dataclass
class Coverage:
    """무엇을 말해도 되는지 켜고 끄는 스위치 묶음."""
    has_latest: bool = False        # 최신 스냅샷이 있나
    can_level: bool = False         # 지금 온도·언급량을 말해도 되나
    can_direction: bool = False     # 오르는지 내리는지 말해도 되나
    can_delta14: bool = False       # 2주 변화를 말해도 되나
    can_assoc: bool = False
    can_sentiment: bool = False
    thin_sample: bool = False       # 표본이 적어 경고를 붙여야 하나
    stale_days: int = 0             # 이 term 의 최신 관측이 며칠 묵었나
    obs7: int = 0
    obs14: int = 0
    obs28: int = 0
    reasons: list = None            # 못 하는 것마다 왜 못 하는지

    def as_dict(self):
        d = asdict(self)
        d["reasons"] = self.reasons or []
        return d


def assess(store, term_key: str, as_of: str, latest: dict | None,
           sentiment: dict | None, assoc_count: int) -> Coverage:
    c = Coverage(reasons=[])
    if not latest:
        c.reasons.append(("NO_METRIC", "이 말은 사전에는 있지만 아직 수집된 언급이 없습니다."))
        return c

    c.has_latest = True
    c.can_level = True
    raw = int(latest.get("raw_count") or 0)
    c.thin_sample = raw < THIN_SAMPLE
    if c.thin_sample:
        c.reasons.append(("THIN_SAMPLE",
                          f"최신 언급이 {raw}건뿐이라 값이 크게 흔들립니다."))

    c.obs7 = store.obs_count(term_key, 7, as_of)
    c.obs14 = store.obs_count(term_key, 14, as_of)
    c.obs28 = store.obs_count(term_key, 28, as_of)

    c.can_direction = c.obs28 >= MIN_OBS_28 and c.obs7 >= MIN_OBS_7
    if not c.can_direction:
        c.reasons.append(("SHORT_HISTORY",
                          f"최근 28일 중 관측이 {c.obs28}일뿐이라 "
                          f"오르는지 내리는지 말할 수 없습니다."))

    c.can_delta14 = c.obs14 >= MIN_OBS_14
    if not c.can_delta14:
        c.reasons.append(("SHORT_HISTORY_14",
                          f"최근 14일 중 관측이 {c.obs14}일뿐이라 2주 변화를 낼 수 없습니다."))

    c.can_assoc = assoc_count > 0
    if not c.can_assoc:
        c.reasons.append(("NO_ASSOC", "아직 계산된 연관어가 없습니다."))

    n_sent = int((sentiment or {}).get("n_total") or 0)
    c.can_sentiment = n_sent > 0
    if not c.can_sentiment:
        c.reasons.append(("NO_SENTIMENT", "구매의향을 판단할 문장이 아직 없습니다."))
    elif n_sent < THIN_SAMPLE:
        c.reasons.append(("THIN_SENTIMENT",
                          f"구매의향 표본이 {n_sent}건이라 중립 쪽으로 보정됩니다."))

    obs = latest.get("observed_on")
    if obs and obs < as_of:
        from datetime import date
        c.stale_days = (date.fromisoformat(as_of) - date.fromisoformat(obs)).days
    return c


def direction(latest: dict) -> dict | None:
    """방향은 온도로 말하지 않는다. ma7/ma28 배수로 말한다.

    이유 — momentum 이 포화돼 있다. 2026-09-01 기준 451개 중 410개(90.9%)가 99 이상이다.
    `momentum = 100/(1+exp(-6*(ma7/ma28-1)))` 에서 수집량이 계속 늘어
    ma7/ma28 이 항상 1을 넘고 시그모이드가 천장에 붙었다.
    그래서 `temp = 0.6*level + 0.4*momentum` 이 사실상 `0.6*level + 40` 이다.
    온도로는 오르는지 식는지 구분할 수 없다.
    """
    ma7 = float(latest.get("ma7") or 0)
    ma28 = float(latest.get("ma28") or 0)
    if ma28 <= 0:
        return None
    ratio = ma7 / ma28
    if ratio >= 1.5:
        label, tone = "가파른 상승", "up"
    elif ratio >= 1.1:
        label, tone = "완만한 상승", "up"
    elif ratio >= 0.9:
        label, tone = "평평함", "flat"
    else:
        label, tone = "내려오는 중", "down"
    return {"ratio": round(ratio, 2), "label": label, "tone": tone,
            "ma7": round(ma7, 2), "ma28": round(ma28, 2)}
