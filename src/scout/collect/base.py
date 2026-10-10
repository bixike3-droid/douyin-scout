"""采集器基类：模板方法 + 统一的护栏/归档/解析/落库流程。"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..app import AppContext
from ..guard.circuit import CircuitOpen
from ..guard.quota import QuotaExceeded
from ..humanize import human_gap, micro_move
from ..parse.registry import ParseResult, parse_payload
from ..util import truncate

# 单次导航最多收多少个响应，防止某个页面刷出成百上千条把配额瞬间吃光
MAX_CAPTURES_PER_RUN = 12


@dataclass
class CollectOutcome:
    kind: str
    tier: str
    target: str
    url: str = ""
    ok: bool = False
    empty: bool = True
    error: str = ""
    blocked: bool = False          # 被护栏拦下（配额/熔断），不是失败
    captured: int = 0              # 收到的响应总数（含静态资源）
    data_requests: int = 0         # 其中属于数据接口的数量（这才是计费口径）
    static_skipped: int = 0        # 被跳过的静态资源数
    requests: int = 0
    raw_ids: list[int] = field(default_factory=list)
    duration_ms: int = 0
    parsed: ParseResult | None = None
    persisted: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "tier": self.tier,
            "target": truncate(self.target, 80),
            "url": truncate(self.url, 160),
            "ok": self.ok,
            "empty": self.empty,
            "error": truncate(self.error, 200),
            "blocked": self.blocked,
            "captured": self.captured,
            "data_requests": self.data_requests,
            "static_skipped": self.static_skipped,
            "requests": self.requests,
            "raw_ids": self.raw_ids,
            "duration_ms": self.duration_ms,
            "persisted": self.persisted,
            "parsed": self.parsed.summary() if self.parsed else None,
        }


class Collector(ABC):
    kind: str = "generic"
    default_tier: str = "b"
    # True 表示这个采集器"在页面里 fetch"，不做整页导航（见 LikersCollector）
    fetch_mode: bool = False

    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    # ── 页面内请求 ──────────────────────────────────────────

    FETCH_JS = """
    async (args) => {
      try {
        const r = await fetch(args.url, {
          credentials: 'include',
          headers: {'accept': 'application/json, text/plain, */*'}
        });
        const t = await r.text();
        return {status: r.status, body: t.slice(0, args.max), error: ''};
      } catch (e) {
        return {status: -1, body: '', error: String(e)};
      }
    }
    """

    async def fetch_in_page(
        self, page: Any, url: str, *, max_bytes: int = 8_000_000
    ) -> tuple[bytes, int, str]:
        """在页面上下文里发请求，返回 (body, status, error)。

        这是"让浏览器替我们发请求"这条原则最直接的形式：
        同源、自带 cookie、由页面自己的环境发出，签名（如果需要）也由页面负责。

        比模拟点击可靠得多 —— 没有元素要猜、没有悬停时机、没有活页会消失。
        实测点赞人接口甚至不需要 a_bogus。
        """
        res = await page.evaluate(self.FETCH_JS, {"url": url, "max": max_bytes})
        if not isinstance(res, dict):
            return b"", -1, f"fetch 返回异常：{res!r}"
        body = str(res.get("body") or "").encode("utf-8")
        return body, int(res.get("status") or -1), str(res.get("error") or "")

    # ── 子类接口 ────────────────────────────────────────────

    @abstractmethod
    def url_for(self, target: str) -> str: ...

    async def interact(self, page: Any, session: Any) -> None:
        """页面打开后的拟人动作。

        session 传进来是为了让需要翻页的采集器能实时观察镜像里收了多少响应
        （比如通知流要一直滚到"没有更多了"）。
        """
        await micro_move(page)
        await human_gap(0.4, 1.1)

    def persist(self, parsed: ParseResult, task: dict[str, Any]) -> dict[str, Any]:
        """把解析结果落库。默认什么都不做。"""
        return {}

    def quota_cost(self) -> int:
        """这次采集算几个"动作"，用于配额记账。

        默认 1（就是一次页面导航）。需要逐条展开的采集器覆盖它，
        把每次点开也算进去。

        为什么按动作而不是按响应计：一次页面加载会触发上百个 XHR，
        其中大部分是站点自己的后台埋点。把它们算成我们的消耗毫无意义 ——
        实测一次勘探因此被记了 136 点配额。

        这个方法在 interact() 之后调用，所以子类可以从 self.stats 里读展开次数。
        """
        return 1

    # ── 主流程 ──────────────────────────────────────────────

    async def run(self, task: dict[str, Any]) -> CollectOutcome:
        tier = task.get("tier") or self.default_tier
        target = task.get("target") or ""
        task_id = task.get("id")
        outcome = CollectOutcome(kind=self.kind, tier=tier, target=target)
        started = time.monotonic()

        try:
            self.ctx.guard(tier)
        except (QuotaExceeded, CircuitOpen) as exc:
            outcome.blocked = True
            outcome.error = str(exc)
            outcome.duration_ms = int((time.monotonic() - started) * 1000)
            return outcome

        try:
            url = self.url_for(target)
            outcome.url = url
            session = await self.ctx.open_session()
            tier_cfg = self.ctx.tier_cfg(tier)
            sess = await session.ensure(tier)
            mirror = sess.mirror

            mirror.clear()
            await self.ctx.throttle.wait(tier, tier_cfg)
            self.ctx.throttle.note_request(tier)

            page = await session.goto(tier, url, settle_s=tier_cfg.page_stay_s)
            await self.interact(page, session)
            await mirror.drain()

            captured = mirror.take()
            outcome.captured = len(captured)

            # 关键：先按"是不是数据接口"筛掉静态资源，**再**截断。
            # 反过来的话，一次页面加载几百个 JS/CSS 会把名额全占掉，
            # 真正的接口一个都轮不到。
            data_items = [c for c in captured if c.is_data]
            outcome.data_requests = len(data_items)
            outcome.static_skipped = outcome.captured - outcome.data_requests
            picked = data_items[:MAX_CAPTURES_PER_RUN]

            keep_static = self.ctx.config.storage.archive_static
            if keep_static:
                picked = (data_items + [c for c in captured if not c.is_data])[:MAX_CAPTURES_PER_RUN]

            # 配额记的是**我们做了几个动作**，不是页面自己发了几个请求。
            # 一次导航算一个动作；展开动作按实际点开的条目数计价。
            # 早期按响应数计费，导致一次勘探消耗 136 点配额 —— 而其中大部分
            # 是抖音自己的后台埋点，跟我们发多少请求毫无关系。
            outcome.requests = self.quota_cost()

            merged = ParseResult(url=url, kind=self.kind)
            for item in picked:
                raw_id = None
                if item.body:
                    ref = self.ctx.archive.save(
                        item.body,
                        url=item.url,
                        tier=tier,
                        content_type=item.content_type,
                        source="collect",
                        note=f"{self.kind}:{target}",
                    )
                    raw_id = ref.id
                    outcome.raw_ids.append(raw_id)

                self.ctx.telemetry.log_request(
                    tier=tier,
                    url=item.url,
                    status=item.status,
                    ok=200 <= item.status < 400,
                    byte_size=item.byte_size,
                    duration_ms=item.duration_ms,
                    error=item.error,
                    task_id=task_id,
                    raw_blob_id=raw_id,
                )

                payload = item.json() if item.is_json else None
                if payload is not None:
                    merged.merge(
                        parse_payload(item.url, payload, raw_blob_id=raw_id)
                    )

            # 配额记账：只按数据接口计，静态资源不烧配额
            self.ctx.quota.consume(tier, outcome.requests)

            outcome.parsed = merged
            outcome.empty = merged.is_empty()

            if outcome.data_requests == 0:
                outcome.empty = True
                outcome.error = (
                    f"页面没有触发任何数据接口（共收到 {outcome.captured} 个响应，"
                    f"全是静态资源）——可能面板没打开，或 URL 不对"
                )

            # 熔断判定：空返回和错误分开计
            if outcome.empty:
                self.ctx.circuit.record_empty(tier)
            else:
                self.ctx.circuit.record_success(tier)

            outcome.persisted = self.persist(merged, {**task, "_captured": len(captured)}) or {}
            outcome.ok = not outcome.empty

        except Exception as exc:  # 采集失败绝不外抛
            outcome.ok = False
            outcome.error = f"{type(exc).__name__}: {exc}"
            try:
                self.ctx.telemetry.log_request(
                    tier=tier, url=outcome.url or self.kind, ok=False, error=outcome.error, task_id=task_id
                )
                self.ctx.circuit.record_error(tier, outcome.error)
            except Exception:
                pass

        outcome.duration_ms = int((time.monotonic() - started) * 1000)
        return outcome
