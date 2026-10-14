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
from dataclasses import replace
from typing import Any

from ..guard.circuit import CircuitOpen
from ..guard.quota import QuotaExceeded
from ..parse.registry import ParseResult, parse_payload
from .base import CollectOutcome, Collector
from ..store.collection import Coverage
from ..util import iso, utcnow
from datetime import timedelta

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

    def max_items(self, task: dict[str, Any]) -> int:
        return 0

    def filter_parsed(self, parsed, task):
        return parsed

    def _identifiers(self, parsed):
        if self.kind == "fetch_user_works":
            return {str(w["aweme_id"]) for w in parsed.works if w.get("aweme_id")}
        if self.kind == "fetch_likers":
            return {str(e["sec_uid"]) for e in parsed.like_edges if e.get("sec_uid")}
        return {str(u["sec_uid"]) for u in parsed.users if u.get("sec_uid")}

    # ── 主流程 ──────────────────────────────────────────────

    async def run(self, task: dict[str, Any]) -> CollectOutcome:
        tier = task.get("tier") or self.default_tier
        target = str(task.get("target") or "")
        outcome = CollectOutcome(kind=self.kind, tier=tier, target=target)
        started = time.monotonic()
        coverage = Coverage(self.ctx.db)
        limit = max(0, self.max_items(task))
        previous = coverage.get(self.kind, target)
        recent = iso(utcnow() - timedelta(hours=self.ctx.config.targets.collection_ttl_hours))
        resume = bool(task.get("_resume", False) and previous and previous["state"] in ("partial", "sampled")
                      and previous["updated_at"] >= recent and previous["hint"] == task.get("_hint", ""))
        seen = coverage.items(self.kind, target) if resume else set()
        cursor = int(previous["next_cursor"]) if resume and seen else 0
        pages, state, clean_status = 0, "partial", False
        merged = ParseResult(url=target, kind=self.kind)
        self.stats = {"pages": 0, "exhausted": False}
        try:
            self.ctx.guard(tier)
            if not resume:
                coverage.reset_items(self.kind, target)
            session = await self.ctx.open_session()
            cfg = self.ctx.tier_cfg(tier)
            if task.get("_api_cadence"):
                minimum = max(0.8, self.ctx.config.targets.api_min_delay_s)
                cfg = replace(cfg, min_delay_s=minimum,
                              max_delay_s=max(minimum, self.ctx.config.targets.api_max_delay_s))
            await session.ensure(tier)
            page = await session.page(tier)
            if "douyin.com" not in (page.url or ""):
                page = await session.goto(tier, self.origin_url(target), settle_s=cfg.page_stay_s)

            if limit and len(seen) >= limit:
                state = "sampled"
            else:
                while pages < self.max_pages:
                    self.ctx.guard(tier)
                    self._remaining = max(0, limit - len(seen)) if limit else 0
                    callback = getattr(self, "on_progress", None)
                    if callback:
                        callback({"type": "page", "kind": self.kind, "page": pages + 1,
                                  "items": len(seen), "message": f"正在采集第 {pages + 1} 页，已确认 {len(seen)} 条；等待请求间隔…"})
                    await self.ctx.throttle.wait(tier, cfg)
                    self.ctx.guard(tier)
                    self.ctx.throttle.note_request(tier)
                    pages += 1
                    url = self.api_url(target, cursor)
                    request_start = time.monotonic()
                    try:
                        body, status, err = await self.fetch_in_page(page, url)
                    finally:
                        self.ctx.quota.consume(tier)
                    duration = int((time.monotonic() - request_start) * 1000)
                    outcome.captured += 1
                    outcome.data_requests += 1
                    raw_id = None
                    if body:
                        ref = self.ctx.archive.save(body, url=url, tier=tier, content_type="application/json",
                            source="collect", note=f"{self.kind}:{target}:p{pages}")
                        raw_id = ref.id
                        outcome.raw_ids.append(raw_id)
                    try:
                        payload = json.loads((body or b"").decode("utf-8", errors="replace"))
                    except (ValueError, UnicodeError):
                        payload = None
                    valid = isinstance(payload, dict) and status == 200 and not err and payload.get("status_code") in (0, None)
                    self.ctx.telemetry.log_request(tier=tier, url=url, status=status, ok=valid,
                        duration_ms=duration, byte_size=len(body or b""), error=err, task_id=task.get("id"), raw_blob_id=raw_id)
                    if not valid:
                        outcome.error = "接口拒绝访问（HTTP 403），需确认登录或稍后重试" if status == 403 else err or (f"接口返回 status_code={payload.get('status_code')} {payload.get('status_msg') or ''}"
                            if isinstance(payload, dict) else f"响应不是有效 JSON（status={status}）")
                        break
                    clean_status = True
                    parsed = parse_payload(url, payload, raw_blob_id=raw_id)
                    if any("结构可能变了" in note for note in parsed.notes):
                        outcome.error = "接口结构变化，停止采集等待核验"
                        break
                    parsed = self.filter_parsed(parsed, task)
                    if self.kind == "fetch_self" and parsed.is_empty():
                        outcome.error = "本人资料缺失，无法确认账号"
                        break
                    if self.kind == "fetch_likers" and not seen and not parsed.like_edges:
                        work = self.ctx.works.get(target) or {}
                        if payload.get("user_list") or (work.get("digg_count") or 0) > 0:
                            outcome.error = "名单结果与作品统计不一致，完整性待核验"
                            break
                    if self.kind == "fetch_user_works" and not parsed.works and any("作者不是本人" in n or "归属未确认" in n for n in parsed.notes):
                        outcome.error = "作品作者归属无法确认，等待核验"
                        break
                    overflow = False
                    if limit and self.kind == "fetch_user_works":
                        remaining = max(0, limit - len(seen))
                        accepted, added = [], 0
                        for work in parsed.works:
                            identifier = str(work.get("aweme_id") or "")
                            if identifier in seen or added < remaining:
                                accepted.append(work)
                                if identifier not in seen:
                                    added += 1
                            else:
                                overflow = True
                        parsed.works = accepted
                    merged.merge(parsed)
                    with self.ctx.db.transaction():
                        saved = self.persist(parsed, {**task, "_captured": pages}) or {}
                        identifiers = self._identifiers(parsed)
                        coverage.add_items(self.kind, target, identifiers)
                    seen.update(identifiers)
                    for key, value in saved.items():
                        outcome.persisted[key] = outcome.persisted.get(key, 0) + value if isinstance(value, int) and not isinstance(value, bool) else value
                    has_more = bool((parsed.cursor or {}).get("has_more"))
                    nxt = self.should_continue(parsed, cursor)
                    if self.kind != "fetch_self" and ("has_more" not in (parsed.cursor or {}) or not parsed.cursor.get("has_more_known", True)):
                        outcome.error = "响应缺少分页标志，无法确认触底"
                    elif has_more and nxt is None:
                        outcome.error = "游标缺失或重复，名单只完成一部分"
                    elif has_more and parsed.is_empty():
                        outcome.error = "分页仍有更多，但有效结果为空，等待核验"
                    elif not has_more:
                        state = "full" if seen else "empty"
                    elif limit and len(seen) >= limit:
                        state = "sampled"
                    if has_more and nxt is not None and not overflow:
                        cursor = nxt
                    coverage.save(self.kind, target, state=state, item_count=len(seen), item_limit=limit,
                        next_cursor=cursor, pages=pages, error=outcome.error, hint=task.get("_hint", ""))
                    if callback:
                        callback({"type": "page", "kind": self.kind, "page": pages, "items": len(seen),
                                  "message": f"第 {pages} 页已归档，共确认 {len(seen)} 条"})
                    if outcome.error or state in ("full", "empty", "sampled"):
                        break
                if state == "partial" and not outcome.error:
                    outcome.error = "达到页数上限，尚未触底；下次继续"
            outcome.ok = state in ("full", "empty", "sampled") and not outcome.error
            if outcome.ok:
                if self.kind == "fetch_likers" and state in ("full", "empty"):
                    outcome.persisted["unconfirmed_edges"] = coverage.mark_absent_likers(target)
                self.ctx.circuit.record_success(tier)
            elif clean_status and seen and outcome.error.startswith("达到页数上限"):
                self.ctx.circuit.record_success(tier)
            elif clean_status and seen:
                # A transport/pagination failure must not be promoted to success.
                self.ctx.circuit.record_error(tier, outcome.error)
            else:
                self.ctx.circuit.record_error(tier, outcome.error or "无有效响应")
        except (QuotaExceeded, CircuitOpen) as exc:
            outcome.blocked = True
            outcome.error = str(exc)
        except Exception as exc:
            outcome.error = f"{type(exc).__name__}: {exc}"
            self.ctx.circuit.record_error(tier, outcome.error)
        finally:
            if not outcome.ok:
                state = "partial" if seen else "error"
            coverage.save(self.kind, target, state=state, item_count=len(seen), item_limit=limit,
                next_cursor=cursor, pages=pages, error=outcome.error, hint=task.get("_hint", ""))
            self.stats.update(pages=pages, exhausted=state in ("full", "empty"))
        outcome.parsed = merged
        outcome.empty = merged.is_empty()
        outcome.requests = pages
        outcome.persisted.update(pages=pages, exhausted=self.stats["exhausted"],
                                 collection_state=state, items=len(seen))
        outcome.duration_ms = int((time.monotonic() - started) * 1000)
        return outcome
