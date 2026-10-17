"""抖音实时热榜：直接调抖音官方接口（不是搜索）。

与账号采集同一条路线：真实浏览器页面内发请求、走护栏（熔断 / 配额 / 节奏）、
原始响应落盘（raw_blobs）、请求记入 telemetry、解析后写入热榜快照。
优先用登录档（和采集一致），不可用时自动回落其它已启用档位。
"""
from __future__ import annotations

import json
import time
from typing import Any

from ..collect.base import Collector
from ..collect.api_base import COMMON_PARAMS
from ..store.hot import HotTopics

# 实测（2026-10-15，匿名档 b）：该接口不需要签名，页面内 fetch 返回 50 条；
# 注意不能带 source=trending_page（接口要求 source 为整数，传字符串会 400）。
HOT_URL = ("https://www.douyin.com/aweme/v1/web/hot/search/list/?" + COMMON_PARAMS
           + "&detail_list=1")
# 走浏览器上下文直接请求时必须带 Referer，否则接口返回空体（2026-10-15 实测）。
HOT_HEADERS = {"Referer": "https://www.douyin.com/"}
MAX_BYTES = 4_000_000

# 「200 但空体」与「200 但榜单缩水」不是同一件事：前者多是登录态/签名，后者多是降级。
LOGIN_MARKERS = ("2483", "请先登录", "登录后查看", "not login")


class HotFetchError(RuntimeError):
    """带失败类型的抓取错误，方便上层给出可操作的提示而不是一句“失败了”。"""

    LABELS = {"login_required": "需要登录或登录态已失效",
              "empty": "接口返回空响应",
              "http": "HTTP 状态码异常",
              "invalid_json": "响应不是有效 JSON",
              "degraded": "返回 200 但榜单为空（疑似降级或接口结构变化）",
              "network": "请求未完成"}

    def __init__(self, kind: str, detail: str = ""):
        self.kind = kind
        super().__init__(f"{self.LABELS.get(kind, kind)}" + (f"：{detail}" if detail else ""))


def classify_failure(*, status: int, body: bytes, payload: Any, error: str = "") -> HotFetchError:
    """把一次请求结果归成可判别的失败类型。调用方只在“没拿到榜单”时用它。"""
    text = body[:800].decode("utf-8", errors="replace") if body else ""
    if any(marker in text for marker in LOGIN_MARKERS) or status == 2483:
        return HotFetchError("login_required", "接口要求登录（2483）；请重新登录抖音")
    if not body and error:
        return HotFetchError("network", error[:120])
    if status and status != 200:
        return HotFetchError("http", f"HTTP {status}")
    if not body:
        return HotFetchError("empty", "status=200 但响应体为空")
    if not isinstance(payload, dict):
        return HotFetchError("invalid_json", f"status={status}，无法解析 JSON")
    return HotFetchError("degraded", f"status={status}，榜单字段为空")


def extract_words(payload: Any) -> list[dict[str, Any]]:
    """容错读取：不同版本的字段名都可能出现。"""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []
    for key in ("word_list", "trending_list", "list", "hotsearch_list"):
        value = data.get(key)
        if isinstance(value, list) and value:
            words = [item for item in value
                     if isinstance(item, dict) and (item.get("word") or item.get("sentence"))]
            if words:
                return words
    return []


def pick_tier(ctx, *, headless: bool = False) -> str:
    """无头启动刷新优先匿名档（避开登录态）；否则登录档优先（和采集一致）。"""
    names = list(ctx.enabled_tiers())
    want = "anonymous" if headless else "logged_in"
    for name in names:
        try:
            if ctx.tier_cfg(name).mode == want:
                return name
        except Exception:  # noqa: BLE001 —— 配置异常时继续找下一个
            continue
    return names[0] if names else "b"


def _tier_order(ctx, preferred: str | None, *, headless: bool = False) -> list[str]:
    order = []
    for name in [preferred or pick_tier(ctx, headless=headless), *ctx.enabled_tiers()]:
        if name and name not in order:
            order.append(name)
    return order or ["b"]


async def _fetch_once(ctx, tier: str, *, headless: bool = False) -> tuple[dict, int | None]:
    """一个档位抓一次：页面内请求优先，page.request 兜底；返回 (payload, raw_id)。"""
    cfg = ctx.tier_cfg(tier)
    ctx.guard(tier)
    session = await ctx.open_session(headless_override=True if headless else None)
    await session.ensure(tier)
    page = await session.page(tier)
    if "douyin.com" not in (page.url or ""):
        page = await session.goto(tier, "https://www.douyin.com/")
    await ctx.throttle.wait(tier, cfg)
    ctx.throttle.note_request(tier)
    started = time.monotonic()
    body, status, error = b"", -1, ""
    try:
        # 主通道：页面内 fetch（同源 + 自带 cookie，签名由页面环境负责）
        try:
            result = await page.evaluate(Collector.FETCH_JS, {"url": HOT_URL, "max": MAX_BYTES})
            body = str((result or {}).get("body") or "").encode("utf-8")
            status = int((result or {}).get("status") or -1)
            error = str((result or {}).get("error") or "")
        except Exception as exc:  # noqa: BLE001 —— 退回请求上下文通道
            error = f"{type(exc).__name__}：{exc}"
            body, status = b"", -1
        if not body:
            # 兜底：浏览器上下文直接请求（首页落到验证码中间页也打不断它）
            response = await page.request.get(HOT_URL, headers=HOT_HEADERS)
            status = response.status
            body = (await response.text()).encode("utf-8")
            error = "" if status == 200 else f"HTTP {status}"
    finally:
        ctx.quota.consume(tier)
    duration = int((time.monotonic() - started) * 1000)
    raw_id = None
    if body:
        ref = ctx.archive.save(body, url=HOT_URL, tier=tier, content_type="application/json",
                               source="hot", note="hot_topics")
        raw_id = ref.id
    try:
        payload = json.loads(body.decode("utf-8", errors="replace")) if body else None
    except (ValueError, UnicodeError):
        payload = None
    valid = isinstance(payload, dict) and status == 200 and bool(extract_words(payload))
    ctx.telemetry.log_request(tier=tier, url=HOT_URL, status=status, ok=valid, duration_ms=duration,
                              byte_size=len(body or b""), error=error, task_id=None, raw_blob_id=raw_id)
    if not valid:
        failure = classify_failure(status=status, body=body or b"", payload=payload, error=error)
        # 静默降级和普通错误都要计入熔断，否则会一直重试下去
        if failure.kind in ("degraded", "empty"):
            ctx.circuit.record_empty(tier)
        else:
            ctx.circuit.record_error(tier, str(failure)[:200])
        raise failure
    ctx.circuit.record_success(tier)
    return payload, raw_id


async def fetch_hot(ctx, *, tier: str | None = None, headless: bool = False) -> dict:
    """抓抖音热榜并写入快照；按档位逐个试，全失败才抛最后一个错误。"""
    last_error: Exception | None = None
    for name in _tier_order(ctx, tier, headless=headless):
        try:
            payload, raw_id = await _fetch_once(ctx, name, headless=headless)
        except Exception as exc:  # noqa: BLE001 —— 换档位再试
            last_error = exc
            continue
        try:
            HotTopics(ctx.db).save_snapshot(extract_words(payload), tier=name, raw_blob_id=raw_id,
                                            source="douyin")
        except Exception:  # noqa: BLE001 —— 入库失败不影响本次展示
            pass
        return payload
    raise last_error if last_error else RuntimeError("没有可用的采集档位")
