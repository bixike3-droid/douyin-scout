"""「页面内 fetch + 分页」型采集器的基类。

这一类采集器的共同点（也是它们比 UI 自动化可靠得多的原因）：

- 不做页面导航、不点击、不悬停 —— 没有元素要猜，没有活页会消失
- 请求由页面自己发出：同源、自带 cookie
- **实测抖音这些接口不需要 a_bogus 签名**，所以连签名都不用管
- 翻页机制统一：用上一页返回的 max_cursor 取下一页，has_more 为 false 就到底

子类只需要实现两件事：`api_url(target, cursor)` 和 `persist()`。
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..guard.circuit import CircuitOpen
from ..guard.quota import QuotaExceeded
from ..parse.registry import ParseResult, parse_payload
from .base import CollectOutcome, Collector

# 抖音 web 端通用查询参数。实测这些够了，多余的设备指纹参数不影响返回。
COMMON_PARAMS = (
    "device_platform=webapp&aid=6383&channel=channel_pc_web"
    "&update_version_code=170400&pc_client_type=1&platform=PC"
    "&version_code=170400&version_name=17.4.0"
    "&browser_language=zh-CN&browser_platform=Win32"
)


class ApiCollector(Collector):
    kind = "api_generic"
    fetch_mode = True
    # 这两个接口实测都要求登录态：匿名会返回 {"status_code":8,"status_msg":"用户未登录"}
    default_tier = "a"

    # ── 子类必须实现 ────────────────────────────────────────

    def api_url(self, target: str, cursor: int) -> str:
        raise NotImplementedError

    def cursor_query(self, cursor: int) -> str:
        """拼分页参数。

        ⚠️ **不同接口对游标参数的容忍度不一样**，所以它是个可覆盖的方法。

        实测（2026-10-10，筑荧）：
        - 作品列表 `/aweme/post/`：把 `min_cursor` 和 `max_cursor` 设成同一个值，
          **第二页直接返回 0 条**（has_more 也变 0）。表现是"只采到第一页 17 条"，
          而接口自己说这人 33 个作品。只给 `max_cursor` 才正常。
        - 点赞人列表 `/favorite/list/`：min=max 是可以的（实测翻 6 页正常）。

        默认用只给 max_cursor 的写法 —— 这个对两种接口都有效。
        """
        return f"max_cursor={cursor}"

    def url_for(self, target: str) -> str:
        """基类 ABC 要求的接口。

        API 型采集器不做页面导航，所以这里返回"第一页的接口地址"，
        只是为了让抽象接口完整、日志里能看到目标地址。
        """
        return self.api_url(target, 0)

    def origin_url(self, target: str) -> str:
        """同源要求：页面必须站在抖音域下，fetch 才带得上 cookie。"""
        return self.ctx.config.targets.home_url

    # ── 子类可覆盖 ──────────────────────────────────────────

    @property
    def max_pages(self) -> int:
        return 40

    def should_continue(self, parsed: ParseResult, cursor: int) -> int | None:
        """返回下一页的 cursor；返回 None 表示到底了。

        容错读游标：不同解析器给的键名可能不同（`max_cursor` / `cursor` /
        `next_cursor`），任何一个都认 —— 键名对不上会静默变成"只采第一页"。
        """
        cur = parsed.cursor or {}
        if not cur.get("has_more"):
            return None
        for key in ("max_cursor", "cursor", "next_cursor"):
            value = cur.get(key)
            if value in (None, "", 0, "0"):
                continue
            try:
                nxt = int(value)
            except (TypeError, ValueError):
                continue
            if nxt != cursor:
                return nxt
        return None

    # ── 主流程 ──────────────────────────────────────────────

    async def run(self, task: dict[str, Any]) -> CollectOutcome:
        tier = task.get("tier") or self.default_tier
        target = str(task.get("target") or "")
        outcome = CollectOutcome(kind=self.kind, tier=tier, target=target)
        started = time.monotonic()
        self.stats: dict[str, Any] = {"pages": 0, "exhausted": False}

        try:
            self.ctx.guard(tier)
        except (QuotaExceeded, CircuitOpen) as exc:
            outcome.blocked = True
            outcome.error = str(exc)
            return outcome

        try:
            session = await self.ctx.open_session()
            tier_cfg = self.ctx.tier_cfg(tier)
            await session.ensure(tier)

            # 同源：先落到抖音域名下（已有页面时不会重复导航）
            page = await session.page(tier)
            try:
                current = page.url or ""
            except Exception:
                current = ""
            if "douyin.com" not in current:
                await self.ctx.throttle.wait(tier, tier_cfg)
                self.ctx.throttle.note_request(tier)
                page = await session.goto(
                    tier, self.origin_url(target), settle_s=tier_cfg.page_stay_s
                )

            merged = ParseResult(url=target, kind=self.kind)
            cursor = 0
            pages = 0
            exhausted = False
            clean_status = False

            while pages < self.max_pages:
                pages += 1
                url = self.api_url(target, cursor)
                await self.ctx.throttle.wait(tier, tier_cfg)
                self.ctx.throttle.note_request(tier)

                body, status, err = await self.fetch_in_page(page, url)
                outcome.captured += 1
                outcome.data_requests += 1

                raw_id = None
                if body:
                    ref = self.ctx.archive.save(
                        body, url=url, tier=tier, content_type="application/json",
                        source="collect", note=f"{self.kind}:{target}:p{pages}",
                    )
                    raw_id = ref.id
                    outcome.raw_ids.append(raw_id)

                self.ctx.telemetry.log_request(
                    tier=tier, url=url, status=status, ok=(status == 200 and not err),
                    byte_size=len(body or b""), error=err, task_id=task.get("id"),
                    raw_blob_id=raw_id,
                )

                payload = None
                if body:
                    try:
                        payload = json.loads(body.decode("utf-8", errors="replace"))
                    except Exception:
                        payload = None
                if payload is None:
                    outcome.error = err or f"响应不是 JSON（status={status}）"
                    break

                code = payload.get("status_code")
                if code not in (0, None):
                    outcome.error = (
                        f"接口返回 status_code={code} {payload.get('status_msg') or ''}"
                    ).strip()
                    break
                clean_status = True

                parsed = parse_payload(url, payload, raw_blob_id=raw_id)
                merged.merge(parsed)

                nxt = self.should_continue(parsed, cursor)
                if nxt is None:
                    exhausted = True
                    break
                cursor = nxt

            self.stats["pages"] = pages
            self.stats["exhausted"] = exhausted
            outcome.requests = pages
            self.ctx.quota.consume(tier, pages)

            outcome.parsed = merged
            outcome.empty = merged.is_empty()

            if outcome.empty and clean_status:
                # **接口正常返回、只是列表为空**：这个人没作品，或作品都设了私密。
                # 这是正常结果，不是账号被降级 —— 绝不能记成"空返回"，
                # 否则采几百个用户之后会把熔断器误触发，把正常采集也停掉。
                outcome.ok = True
                outcome.persisted = {
                    "note": "接口正常返回但列表为空（无作品/私密/没人点赞）"
                }
                self.ctx.circuit.record_success(tier)
            elif outcome.empty:
                if not outcome.error:
                    outcome.error = "响应异常且没有数据"
                self.ctx.circuit.record_empty(tier)
            else:
                outcome.ok = True
                self.ctx.circuit.record_success(tier)

            if outcome.ok:
                outcome.persisted.update(
                    self.persist(merged, {**task, "_captured": pages}) or {}
                )
            outcome.persisted.update({"pages": pages, "exhausted": exhausted})

        except Exception as exc:
            outcome.ok = False
            outcome.error = f"{type(exc).__name__}: {exc}"
            try:
                self.ctx.telemetry.log_request(
                    tier=tier, url=target, ok=False, error=outcome.error, task_id=task.get("id")
                )
                self.ctx.circuit.record_error(tier, outcome.error)
            except Exception:
                pass

        outcome.duration_ms = int((time.monotonic() - started) * 1000)
        return outcome
