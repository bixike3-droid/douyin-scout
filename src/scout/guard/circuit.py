"""熔断器。

要解决的问题：抖音降级处罚是**静默**的——接口不报错，只是开始返回空数据。
如果不管它，你会把一大批空数据当有效数据洗进分析结果。所以：

- 连续 N 次空返回 → 判定为静默降级 → 熔断
- 连续 N 次错误 → 熔断
- 冷却结束后进入 half_open，放一个探测请求过去；成功则恢复，失败则加倍冷却

熔断先于告警：宁可停下来等人看，也不要跑完一天才发现全是空。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from ..config import CircuitConfig
from ..store.telemetry import Telemetry
from ..util import iso, parse_iso, utcnow


class CircuitOpen(RuntimeError):
    def __init__(self, key: str, reason: str, cooldown_until: str | None):
        super().__init__(
            f"[{key}] 已熔断：{reason}；冷却至 {cooldown_until or '未知'}。"
            f"用 `scout circuit reset {key}` 手动恢复。"
        )
        self.key = key
        self.reason = reason
        self.cooldown_until = cooldown_until


class CircuitBreaker:
    def __init__(self, telemetry: Telemetry, cfg: CircuitConfig):
        self.tel = telemetry
        self.cfg = cfg

    # ── 检查 ────────────────────────────────────────────────

    def check(self, key: str) -> str:
        """返回当前状态。open 且未到冷却时间就抛 CircuitOpen。"""
        state = self.tel.circuit_load(key)
        if state["state"] != "open":
            return state["state"]

        cooldown_until = state.get("cooldown_until")
        if cooldown_until and parse_iso(cooldown_until) <= utcnow():
            # 冷却结束，转入半开：只放一个探测请求
            self.tel.circuit_save(key, state="half_open")
            self.tel.db.log_event("info", f"circuit:{key}", "冷却结束，转入 half_open，放行一次探测")
            return "half_open"
        raise CircuitOpen(key, state.get("reason") or "未说明原因", cooldown_until)

    # ── 记录结果 ────────────────────────────────────────────

    def record_success(self, key: str) -> str:
        state = self.tel.circuit_load(key)
        was = state["state"]
        self.tel.circuit_save(
            key,
            state="closed",
            reason="",
            opened_at=None,
            cooldown_until=None,
            open_count=0,
            consecutive_empty=0,
            consecutive_error=0,
        )
        if was != "closed":
            self.tel.db.log_event("info", f"circuit:{key}", f"探测成功，熔断解除（原状态 {was}）")
        return "closed"

    def record_empty(self, key: str) -> str:
        state = self.tel.circuit_load(key)
        empties = int(state["consecutive_empty"]) + 1
        if state["state"] == "half_open" or empties >= self.cfg.consecutive_empty_open:
            return self._open(key, f"连续 {empties} 次空返回（疑似静默降级）", empties, int(state["consecutive_error"]))
        self.tel.circuit_save(key, consecutive_empty=empties, consecutive_error=0)
        return state["state"]

    def record_error(self, key: str, message: str = "") -> str:
        state = self.tel.circuit_load(key)
        errors = int(state["consecutive_error"]) + 1
        if state["state"] == "half_open" or errors >= self.cfg.consecutive_error_open:
            return self._open(key, f"连续 {errors} 次请求失败：{message[:200]}", int(state["consecutive_empty"]), errors)
        self.tel.circuit_save(key, consecutive_error=errors, consecutive_empty=0)
        return state["state"]

    def _open(self, key: str, reason: str, empties: int, errors: int) -> str:
        state = self.tel.circuit_load(key)
        open_count = int(state["open_count"]) + 1
        # 连续熔断则加倍冷却：45min → 90min → 180min …
        minutes = self.cfg.cooldown_minutes * (2 ** (open_count - 1))
        minutes = min(minutes, 24 * 60)
        cooldown_until = iso(utcnow() + timedelta(minutes=minutes))
        self.tel.circuit_save(
            key,
            state="open",
            reason=reason,
            opened_at=iso(),
            cooldown_until=cooldown_until,
            open_count=open_count,
            consecutive_empty=empties,
            consecutive_error=errors,
        )
        self.tel.db.log_event(
            "error",
            f"circuit:{key}",
            f"熔断：{reason}；冷却 {minutes} 分钟（第 {open_count} 次）",
            {"cooldown_until": cooldown_until},
        )
        return "open"

    # ── 人工干预 ────────────────────────────────────────────

    def reset(self, key: str) -> None:
        self.tel.circuit_save(
            key, state="closed", reason="", opened_at=None, cooldown_until=None,
            open_count=0, consecutive_empty=0, consecutive_error=0,
        )
        self.tel.db.log_event("info", f"circuit:{key}", "人工重置为 closed")

    def force_open(self, key: str, reason: str) -> None:
        self._open(key, reason, 0, 0)

    def snapshot(self) -> list[dict[str, Any]]:
        return self.tel.circuit_all()
