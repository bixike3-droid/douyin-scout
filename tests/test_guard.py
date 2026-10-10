"""护栏测试：配额、熔断、节流。这三样决定项目能不能长期活着。"""

from __future__ import annotations

import asyncio

import pytest

from scout.config import CircuitConfig
from scout.guard.circuit import CircuitBreaker, CircuitOpen
from scout.guard.quota import QuotaExceeded, QuotaManager
from scout.guard.throttle import Throttle


# ── 配额 ─────────────────────────────────────────────────────


def test_quota_allows_until_limit(ctx):
    quota: QuotaManager = ctx.quota
    assert quota.limit("a") == 5
    for _ in range(5):
        quota.check("a")
        quota.consume("a")
    assert quota.used("a") == 5
    with pytest.raises(QuotaExceeded):
        quota.check("a")


def test_quota_persists_across_instances(ctx):
    ctx.quota.consume("a", 3)
    fresh = QuotaManager(ctx.telemetry, {"a": 5})
    assert fresh.used("a") == 3, "重启不能清零配额"


def test_quota_zero_means_unlimited(ctx):
    quota = QuotaManager(ctx.telemetry, {"z": 0})
    for _ in range(50):
        quota.check("z")
    assert quota.remaining("z") is None
    assert quota.unlimited("z") is True


def test_quota_default_is_unlimited(ctx):
    """默认不设上限 —— 日常采集不需要总量闸门，设了只会挡住自己。"""
    quota = QuotaManager(ctx.telemetry, {"a": 0, "b": 0})
    for _ in range(1000):
        quota.check("a")
        quota.consume("a")
    assert quota.used("a") == 1000
    assert quota.unlimited("a") is True


def test_quota_snapshot_marks_unlimited(ctx):
    snap = QuotaManager(ctx.telemetry, {"b": 0}).snapshot()
    assert snap["b"]["unlimited"] is True
    assert snap["b"]["limit"] == 0
    assert snap["b"]["ratio"] is None


def test_quota_exceeded_message_suggests_zero(ctx):
    """报错信息要告诉用户'其实可以不设上限'，而不是只叫他等到明天。"""
    quota = QuotaManager(ctx.telemetry, {"a": 1})
    quota.consume("a", 1)
    with pytest.raises(QuotaExceeded) as exc:
        quota.check("a")
    assert "0 = 不限制" in str(exc.value)


def test_quota_snapshot(ctx):
    ctx.quota.consume("b", 10)
    snap = ctx.quota.snapshot()
    assert snap["b"]["used"] == 10
    assert snap["b"]["remaining"] == 90


# ── 熔断 ─────────────────────────────────────────────────────


def test_circuit_opens_on_consecutive_empty(ctx):
    breaker = CircuitBreaker(ctx.telemetry, CircuitConfig(consecutive_empty_open=3, cooldown_minutes=60))
    for _ in range(2):
        breaker.record_empty("b")
        breaker.check("b")  # 还没到阈值
    breaker.record_empty("b")
    with pytest.raises(CircuitOpen):
        breaker.check("b")


def test_circuit_opens_on_consecutive_error(ctx):
    breaker = CircuitBreaker(ctx.telemetry, CircuitConfig(consecutive_error_open=2, cooldown_minutes=60))
    breaker.record_error("b", "timeout")
    breaker.record_error("b", "timeout")
    with pytest.raises(CircuitOpen):
        breaker.check("b")


def test_success_resets_counters(ctx):
    breaker = CircuitBreaker(ctx.telemetry, CircuitConfig(consecutive_empty_open=3))
    breaker.record_empty("b")
    breaker.record_empty("b")
    breaker.record_success("b")
    breaker.record_empty("b")
    breaker.check("b")  # 计数已清零，不应熔断


def test_circuit_half_open_after_cooldown(ctx):
    breaker = CircuitBreaker(ctx.telemetry, CircuitConfig(consecutive_empty_open=1, cooldown_minutes=0))
    breaker.record_empty("b")
    assert breaker.check("b") == "half_open", "冷却结束应放行一次探测"


def test_half_open_failure_reopens_and_doubles_cooldown(ctx):
    breaker = CircuitBreaker(
        ctx.telemetry, CircuitConfig(consecutive_empty_open=1, cooldown_minutes=10)
    )
    breaker.record_empty("b")
    assert ctx.telemetry.circuit_load("b")["open_count"] == 1
    with pytest.raises(CircuitOpen):
        breaker.check("b")  # 冷却没到，必须拦住

    # 直接构造 half_open 状态，再让它失败一次
    ctx.telemetry.circuit_save("b", state="half_open")
    breaker.record_empty("b")
    state = ctx.telemetry.circuit_load("b")
    assert state["open_count"] == 2, "连续熔断应累计次数以加倍冷却"
    assert state["state"] == "open"


def test_circuit_half_open_success_closes(ctx):
    breaker = CircuitBreaker(
        ctx.telemetry, CircuitConfig(consecutive_empty_open=1, cooldown_minutes=10)
    )
    breaker.record_empty("b")
    ctx.telemetry.circuit_save("b", state="half_open")
    assert breaker.record_success("b") == "closed"
    assert ctx.telemetry.circuit_load("b")["open_count"] == 0


def test_circuit_reset(ctx):
    breaker = CircuitBreaker(ctx.telemetry, CircuitConfig(consecutive_empty_open=1))
    breaker.record_empty("b")
    with pytest.raises(CircuitOpen):
        breaker.check("b")
    breaker.reset("b")
    assert breaker.check("b") == "closed"


def test_circuit_force_open(ctx):
    breaker = CircuitBreaker(ctx.telemetry, CircuitConfig(cooldown_minutes=60))
    breaker.force_open("b", "人工")
    with pytest.raises(CircuitOpen):
        breaker.check("b")


def test_circuit_logs_event(ctx):
    breaker = CircuitBreaker(ctx.telemetry, CircuitConfig(consecutive_empty_open=1, cooldown_minutes=5))
    breaker.record_empty("b")
    events = ctx.telemetry.events(limit=10)
    assert any("熔断" in e["message"] for e in events)


# ── 节流 ─────────────────────────────────────────────────────


def test_throttle_waits_within_bounds(ctx):
    from scout.config import TierConfig

    async def scenario() -> float:
        throttle = Throttle(ctx.config.guard.throttle)
        tier = TierConfig(name="t", min_delay_s=0.01, max_delay_s=0.02, headless=True)
        return await throttle.wait("t", tier)

    waited = asyncio.run(scenario())
    assert 0.0 < waited < 1.0


def test_throttle_long_pause_every_n(ctx):
    """第 N 个请求（N = long_pause_every）要插入一次长停顿。"""
    from scout.config import ThrottleConfig, TierConfig

    async def scenario() -> list[float]:
        # 注意：Throttle._next_delay 有 0.1s 下限，所以长停顿要设得比它大才区分得开
        throttle = Throttle(
            ThrottleConfig(
                long_pause_every=2, long_pause_min_s=0.5, long_pause_max_s=0.6, jitter_ratio=0.0
            )
        )
        tier = TierConfig(name="t", min_delay_s=0.0, max_delay_s=0.001, headless=True)
        waits = []
        for _ in range(3):
            throttle.note_request("t")
            waits.append(await throttle.wait("t", tier))
        return waits

    first, second, third = asyncio.run(scenario())
    assert first < 0.5, "第 1 个请求不该有长停顿"
    assert second >= 0.5, "第 2 个请求（== long_pause_every）应插入长停顿"
    assert third < 0.5, "第 3 个请求不该有长停顿"
    assert Throttle(ctx.config.guard.throttle).count("nope") == 0


def test_throttle_counter_tracks(ctx):
    throttle = Throttle(ctx.config.guard.throttle)
    throttle.note_request("b")
    throttle.note_request("b")
    assert throttle.stats()["counters"]["b"] == 2
