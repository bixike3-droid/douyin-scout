"""每日动作配额（可选的自我保护，默认不启用）。

算法很简单，但概念要说清楚：

**配额记的是"我们做了几个动作"，不是"页面发了几个请求"。**
一次页面导航触发上百个 XHR 是站点的正常行为，不是你的消耗。
早期版本按响应数计费，一次勘探被记了 136 点 —— 那是错的。

默认 `daily_request_quota = 0` 表示**不设上限**，只做计数和展示。
日常采集一天几个到几十个动作，设上限只会挡住你自己的正常操作。

什么时候该设：数据量大起来之后（几千个用户要逐个访问主页），
加一道总量闸门更稳妥。设了就按天计数，到点自动停。

真正防封靠的是**节流**（`guard/throttle.py`）和**熔断**（`guard/circuit.py`），
这两样永远开启，跟量级无关。
"""

from __future__ import annotations

from typing import Any

from ..store.telemetry import Telemetry


class QuotaExceeded(RuntimeError):
    def __init__(self, tier: str, used: int, limit: int):
        super().__init__(
            f"[{tier}] 今日动作数已达上限：{used}/{limit}。"
            f"要么等到明天，要么调高 tiers.{tier}.daily_request_quota（0 = 不限制）。"
            f"当前数据量不大的话，直接设成 0 更省事。"
        )
        self.tier = tier
        self.used = used
        self.limit = limit


class QuotaManager:
    """按本地日期分桶的动作计数。持久化在 quota_ledger，重启不清零。"""

    def __init__(self, telemetry: Telemetry, limits: dict[str, int] | None = None):
        self.tel = telemetry
        self.limits = dict(limits or {})

    def set_limit(self, tier: str, limit: int) -> None:
        self.limits[tier] = int(limit)

    def limit(self, tier: str) -> int:
        return int(self.limits.get(tier, 0))

    def unlimited(self, tier: str) -> bool:
        return self.limit(tier) <= 0

    def used(self, tier: str) -> int:
        return self.tel.quota_used(tier)

    def remaining(self, tier: str) -> int | None:
        if self.unlimited(tier):
            return None
        return max(0, self.limit(tier) - self.used(tier))

    def check(self, tier: str) -> None:
        """不满足配额就抛 QuotaExceeded。发请求前必调。未设上限时永远通过。"""
        if self.unlimited(tier):
            return
        used = self.used(tier)
        if used >= self.limit(tier):
            raise QuotaExceeded(tier, used, self.limit(tier))

    def consume(self, tier: str, n: int = 1) -> int:
        """记账。应在动作真正发生之后调用。"""
        limit = self.limit(tier) or None
        return self.tel.quota_add(tier, limit, n=n)

    def snapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for tier in sorted(self.limits):
            limit = self.limit(tier)
            used = self.used(tier)
            out[tier] = {
                "used": used,
                "limit": limit,
                "unlimited": limit <= 0,
                "remaining": None if limit <= 0 else max(0, limit - used),
                "ratio": round(used / limit, 3) if limit > 0 else None,
            }
        return out
