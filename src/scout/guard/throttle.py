"""节流：请求之间的拟人化间隔。

原则：
- 间隔是随机的，不是一个固定数字（固定间隔本身就是机器特征）。
- 每 N 个请求插一次长停顿，模拟人离开屏幕。
- 每个档位独立计数，档 A 的节奏不会把档 B 带快。

这里只负责"什么时候可以发下一个请求"，不负责"能不能发"（那是配额和熔断）。
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

from ..config import ThrottleConfig, TierConfig


class Throttle:
    def __init__(self, cfg: ThrottleConfig):
        self.cfg = cfg
        self._counters: dict[str, int] = {}
        self._last_wait: dict[str, float] = {}
        self._long_pauses: dict[str, int] = {}

    def _next_delay(self, tier_cfg: TierConfig) -> tuple[float, bool]:
        lo, hi = float(tier_cfg.min_delay_s), float(tier_cfg.max_delay_s)
        if hi < lo:
            lo, hi = hi, lo
        base = random.uniform(lo, hi)
        # 抖动：避免"均匀分布 + 固定上下界"这种过于规整的形态
        jitter = self.cfg.jitter_ratio
        if jitter > 0:
            base *= 1.0 + random.uniform(-jitter, jitter)
        return max(0.1, base), False

    def _is_long_pause(self, tier: str) -> bool:
        every = self.cfg.long_pause_every
        if every <= 0:
            return False
        return self._counters.get(tier, 0) > 0 and self._counters.get(tier, 0) % every == 0

    def _long_pause(self) -> float:
        lo, hi = self.cfg.long_pause_min_s, self.cfg.long_pause_max_s
        if hi < lo:
            lo, hi = hi, lo
        return random.uniform(lo, hi)

    async def wait(self, tier: str, tier_cfg: TierConfig) -> float:
        """在下一个请求前调用。返回实际等待秒数。"""
        delay, _ = self._next_delay(tier_cfg)
        long_pause = self._is_long_pause(tier)
        if long_pause:
            delay += self._long_pause()
            self._long_pauses[tier] = self._long_pauses.get(tier, 0) + 1
        self._last_wait[tier] = delay
        await asyncio.sleep(delay)
        return delay

    def count(self, tier: str) -> int:
        return self._counters.get(tier, 0)

    def note_request(self, tier: str) -> int:
        """记一次请求，供长停顿判定使用。"""
        self._counters[tier] = self._counters.get(tier, 0) + 1
        return self._counters[tier]

    def stats(self) -> dict[str, Any]:
        return {
            "counters": dict(self._counters),
            "long_pauses": dict(self._long_pauses),
            "last_wait_s": {k: round(v, 2) for k, v in self._last_wait.items()},
        }
