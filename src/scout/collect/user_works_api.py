"""采集器：某个用户的作品列表。

    GET /aweme/v1/web/aweme/post/?sec_user_id=<sec_uid>&count=18&max_cursor=0

实测（2026-10-10）：不带签名直接 fetch 返回 200，每条作品带

    标题(desc)、时长(duration)、发布时间(create_time)、
    点赞/评论/转发/收藏数(statistics)、封面 URL、话题标签

**这就是 AI 做画像的原料** —— 没有它，AI 只能对着昵称和粉丝数瞎编。

和点赞人接口同一套路：页面内 fetch、分页翻到底、不需要签名、需要登录态。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from ..guard.circuit import CircuitOpen
from ..guard.quota import QuotaExceeded
from ..parse.registry import ParseResult, parse_payload
from ..store.collection import Coverage
from .api_base import COMMON_PARAMS, ApiCollector
from .base import CollectOutcome

API_BASE = "https://www.douyin.com/aweme/v1/web/aweme/post/?"

# 主页兜底：等页面自己发出作品请求；滚动触发下一页。
CAPTURE_TIMEOUT_S = 20
CAPTURE_NEXT_TIMEOUT_S = 9
MAX_CAPTURE_BYTES = 8_000_000


class UserWorksApiCollector(ApiCollector):
    kind = "fetch_user_works"

    @property
    def max_pages(self) -> int:
        return max(1, int(self.ctx.config.targets.works_max_pages))

    def _page_size(self) -> int:
        size = max(1, min(50, int(self.ctx.config.targets.works_page_size)))
        remaining = getattr(self, "_remaining", 0)
        return min(size, remaining) if remaining else size

    def max_items(self, task):
        if task.get("target") == self.ctx.cursors.get("self_sec_uid"):
            return 0
        return max(0, int(task.get("_item_limit", self.ctx.config.targets.works_per_user_limit)))

    def filter_parsed(self, parsed, task):
        target = task.get("target")
        original = len(parsed.works)
        parsed.works = [w for w in parsed.works if w.get("author_sec_uid") == target]
        if len(parsed.works) != original:
            parsed.notes.append(f"跳过 {original-len(parsed.works)} 条作者归属未确认的作品")
        return parsed

    def api_url(self, target: str, cursor: int) -> str:
        return (
            API_BASE
            + COMMON_PARAMS
            + f"&sec_user_id={target}"
            + f"&count={self._page_size()}"
            + "&" + self.cursor_query(cursor)
            + "&locate_query=false&show_live_replay_strategy=1"
        )

    def persist(self, parsed: ParseResult, task: dict[str, Any]) -> dict[str, Any]:
        ctx = self.ctx
        sec_uid = task.get("target", "")
        raw_id = parsed.raw_blob_id

        # 第三层防护：**只关联作者确实是本人的作品**。
        # 前两层是"只读 aweme_list"和"解析时按作者过滤"，
        # 这一层兜住任何漏网的 —— 关联错了会让页面上出现
        # "98 粉丝的号挂着 178 万赞视频"这种一眼假的数据。
        linked: list[str] = []
        skipped = 0
        for work in parsed.works:
            aweme_id = work.get("aweme_id")
            if not aweme_id:
                continue
            author = work.get("author_sec_uid") or ""
            if sec_uid and author != sec_uid:
                skipped += 1
                continue
            ctx.works.upsert(work, raw_blob_id=raw_id)
            linked.append(aweme_id)

        if linked:
            ctx.works.link_listings(sec_uid, linked, raw_blob_id=raw_id)
            ctx.users.mark_state(sec_uid, "ok", tier="a")
            if sec_uid == ctx.cursors.get("self_sec_uid"):
                ctx.works.mark_mine_by_author(sec_uid)

        out = {"works_saved": len(linked), "works_linked": len(linked)}
        if skipped:
            out["skipped_other_author"] = skipped
        return out

    # ── API 被风控拦下时的兜底 ───────────────────────────────

    async def run(self, task: dict[str, Any]) -> CollectOutcome:
        """先走手工拼的接口；被 Argus 拦（403）就改为读页面自己发的请求。

        2026-10-17 实测：`/aweme/v1/web/aweme/post/` 现在要求 a_bogus、
        msToken、uifid、x-secsdk-web-signature 一整套签名，手工拼的 URL 会被
        「Blocked by ArgusSecurityPlugin」直接 403；而用户主页由抖音自己的
        前端发同一接口，签名是它算的，响应可以直接读。
        """
        outcome = await super().run(task)
        if "HTTP 403" not in str(outcome.error or ""):
            return outcome
        return await self._run_by_page(task, cause=str(outcome.error or ""))

    async def _run_by_page(self, task: dict[str, Any], *, cause: str = "") -> CollectOutcome:
        ctx = self.ctx
        tier = task.get("tier") or self.default_tier
        target = str(task.get("target") or "")
        outcome = CollectOutcome(kind=self.kind, tier=tier, target=target)
        started = time.monotonic()
        coverage = Coverage(ctx.db)
        limit = max(0, self.max_items(task))
        seen: set[str] = set()
        merged = ParseResult(url=target, kind=self.kind)
        bodies: list[tuple[str, bytes]] = []
        pages = 0
        state = "partial"
        callback = getattr(self, "on_progress", None)

        def progress(message: str) -> None:
            if callback:
                callback({"type": "page", "kind": self.kind, "page": pages + 1,
                          "items": len(seen), "message": message})

        try:
            ctx.guard(tier)
            coverage.reset_items(self.kind, target)
            session = await ctx.open_session()
            await session.ensure(tier)
            page = await session.page(tier)

            async def on_response(response) -> None:
                if "aweme/post" not in response.url or response.status != 200:
                    return
                try:
                    text = await response.text()
                except Exception:      # noqa: BLE001 —— 响应读不到就跳过这一条
                    return
                if not text.lstrip().startswith("{"):
                    return
                if any(url == response.url for url, _ in bodies):
                    return
                bodies.append((response.url, text[:MAX_CAPTURE_BYTES].encode("utf-8")))

            page.on("response", on_response)
            try:
                progress("接口被风控拦截，改为读取主页自身请求…")
                await session.goto(tier, f"https://www.douyin.com/user/{target}", settle_s=2.0)
                while pages < self.max_pages:
                    await self._wait_capture(bodies, pages, CAPTURE_TIMEOUT_S if pages == 0 else CAPTURE_NEXT_TIMEOUT_S)
                    if len(bodies) <= pages:
                        break
                    url, body = bodies[pages]
                    pages += 1
                    request_start = time.monotonic()
                    ctx.quota.consume(tier)
                    ref = ctx.archive.save(body, url=url, tier=tier, content_type="application/json",
                                           source="collect", note=f"{self.kind}:{target}:page{pages}")
                    outcome.raw_ids.append(ref.id)
                    outcome.captured += 1
                    outcome.data_requests += 1
                    try:
                        payload = json.loads(body.decode("utf-8", errors="replace"))
                    except (ValueError, UnicodeError):
                        payload = None
                    valid = isinstance(payload, dict) and payload.get("status_code") in (0, None)
                    ctx.telemetry.log_request(tier=tier, url=url, status=200, ok=valid,
                        duration_ms=int((time.monotonic() - request_start) * 1000), byte_size=len(body),
                        error="", task_id=task.get("id"), raw_blob_id=ref.id)
                    if not valid:
                        outcome.error = "页面返回的作品数据无法解析"
                        break
                    parsed = self.filter_parsed(parse_payload(url, payload, raw_blob_id=ref.id), task)
                    if limit:
                        remaining = max(0, limit - len(seen))
                        parsed.works = parsed.works[:remaining]
                    with ctx.db.transaction():
                        saved = self.persist(parsed, {**task, "_captured": pages}) or {}
                        coverage.add_items(self.kind, target, self._identifiers(parsed))
                    for key, value in saved.items():
                        outcome.persisted[key] = (outcome.persisted.get(key, 0) + value
                                                  if isinstance(value, int) and not isinstance(value, bool) else value)
                    merged.merge(parsed)
                    seen.update(self._identifiers(parsed))
                    progress(f"主页第 {pages} 页已归档，共确认 {len(seen)} 条作品")
                    if not payload.get("has_more"):
                        state = "full" if seen else "empty"
                        break
                    if limit and len(seen) >= limit:
                        state = "sampled"
                        break
                    await page.mouse.wheel(0, 2600)
                    await asyncio.sleep(1.5)
                if state == "partial":
                    # 读到了首页但分页没走完：按抽样处理，下次可继续
                    state = "sampled" if seen else "empty"
                if not bodies:
                    # 页面自己也没发出作品请求：不能当成「这个号没作品」
                    state = "error"
                    outcome.error = f"{cause or '接口拒绝访问'}；用主页读取兜底也没取到作品数据"
                outcome.ok = state in ("full", "empty", "sampled") and not outcome.error
                if outcome.ok:
                    ctx.circuit.record_success(tier)
            finally:
                try:
                    page.remove_listener("response", on_response)
                except Exception:  # noqa: BLE001
                    pass
        except (QuotaExceeded, CircuitOpen) as exc:
            outcome.blocked = True
            outcome.error = str(exc)
        except Exception as exc:  # noqa: BLE001 —— 与 API 路径一致的失败呈现
            outcome.error = f"{type(exc).__name__}: {exc}"
        finally:
            if not outcome.ok:
                state = "partial" if seen else "error"
            coverage.save(self.kind, target, state=state, item_count=len(seen), item_limit=limit,
                          next_cursor=0, pages=pages, error=outcome.error, hint=task.get("_hint", ""))
        outcome.parsed = merged
        outcome.empty = merged.is_empty()
        outcome.requests = max(1, pages)
        outcome.persisted.update(pages=pages, exhausted=state in ("full", "empty"),
                                 collection_state=state, items=len(seen), mode="page_capture")
        outcome.duration_ms = int((time.monotonic() - started) * 1000)
        return outcome

    @staticmethod
    async def _wait_capture(bodies: list, before: int, timeout: float) -> None:
        waited = 0.0
        while len(bodies) <= before and waited < timeout:
            await asyncio.sleep(0.4)
            waited += 0.4
