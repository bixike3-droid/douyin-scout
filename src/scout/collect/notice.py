"""档 A：点赞人名单（网页端「互动消息」→「赞过的人」）。

## 真实形态（已实测确认）

入口是**你自己的个人主页** `www.douyin.com/user/self`，右侧浮着「互动消息」面板：

    「培德类 赞了你的作品」        ← 单人，可能直接带 sec_uid
    「JJ 等22人赞了你的作品」      ← 聚合条目，只露几个头像
    底部「暂时没有更多了」

点开聚合条目 → 弹出「**赞过的人**」覆盖层（带「返回」按钮）→ 里面才是完整名单。
**全程不跳转，都是同页覆盖层。**

## 因此有三个必须处理的坑

1. **面板内部滚动**：互动消息是面板自己的滚动条，不是整页。
   滚轮不悬停在面板上就滚不动 → 连续几轮没新响应 → 被误判触底 → **静默采到 0 条**。
   对策：优先 `notice_scroll_over` 悬停滚动；没有就用 `scroll_into_view_if_needed`
   把最后一个条目滚进视口，让容器自己滚（不依赖知道哪个容器在滚）。

2. **逐条展开**：聚合条目必须点开才拿到完整名单。
   用 `notice_item_pattern`（文案正则）枚举，不需要 CSS 选择器。

3. **收尾**：点「返回」回到列表，不是浏览器后退。

## 为什么坚持用档 A

这是唯一需要登录态的数据源，但它做的是"读自己的通知"，属于最自然的用户行为。
请求量仍然受配额严格约束。
"""

from __future__ import annotations

import re
from typing import Any

from ..humanize import human_gap, human_scroll, micro_move
from ..parse.registry import ParseResult
from .base import Collector

# 登录墙信号：URL 里出现这些就说明被挡了，早点停，别白滚
_LOGIN_WALL_URL_HINTS = ("passport", "/login", "verifycenter")


class NoticeCollector(Collector):
    kind = "fetch_notice"
    default_tier = "a"

    def __init__(self, ctx):
        super().__init__(ctx)
        # 从「赞过的人」覆盖层 DOM 里抽到的完整点赞人：{aweme_id: [{sec_uid, nickname}]}
        # 为什么走 DOM：实测确认完整名单**不在任何接口响应里**，
        # 是前端直接渲染的。翻遍归档都找不到那 27 个人，但 DOM 里有。
        self.harvested: dict[str, list[dict[str, Any]]] = {}
        self.stats: dict[str, Any] = {
            "rounds": 0,
            "reached_end": False,
            "stop_reason": "",
            "login_wall": False,
        }

    # ── 地址 ────────────────────────────────────────────────

    def url_for(self, target: str) -> str:
        notice_url = target or self.ctx.config.targets.notice_url
        if not notice_url:
            raise ValueError(
                "互动消息入口地址未配置。默认应是 https://www.douyin.com/user/self —— "
                "用 `scout probe --tier a --url <主页地址> --dump` 实测确认后写进 local.yaml。"
            )
        return notice_url

    # ── 条目定位（选择器优先，其次文案正则）──────────────────

    def _item_locator(self, page: Any) -> Any | None:
        targets = self.ctx.config.targets
        selector = (targets.notice_item_selector or "").strip()
        if selector:
            return page.locator(selector)
        pattern = (targets.notice_item_pattern or "").strip()
        if pattern:
            try:
                return page.get_by_text(re.compile(pattern))
            except Exception:
                return None
        return None

    def _item_source(self) -> str:
        targets = self.ctx.config.targets
        if (targets.notice_item_selector or "").strip():
            return f"selector:{targets.notice_item_selector}"
        if (targets.notice_item_pattern or "").strip():
            return f"pattern:{targets.notice_item_pattern}"
        return ""

    @staticmethod
    def _saw_notice_api(mirror: Any) -> bool:
        """镜像里有没有收到互动消息接口的响应。用于报告，**不能用来判断面板开没开**。

        为什么不能：这个接口在页面加载时就会被预取，所以它"被调用过"不代表
        面板是打开的 —— 拿它当判断依据，兜底逻辑永远不会触发。
        """
        try:
            return any("/notice" in c.url for c in mirror.peek())
        except Exception:
            return False

    async def _panel_visible(self, page: Any) -> bool:
        """面板到底开没开 —— 看页面上有没有「赞了你的作品」这行字。

        比"接口有没有被调用"准得多：接口会被预取，文字不会无中生有。
        """
        pattern = (self.ctx.config.targets.notice_item_pattern or "").strip()
        probes = [pattern, "赞了你的作品"] if pattern else ["赞了你的作品"]
        for probe in probes:
            if not probe:
                continue
            try:
                if await page.get_by_text(re.compile(probe)).count() > 0:
                    return True
            except Exception:
                continue
        return False

    # ── 推进列表：滚动面板加载更多 ──────────────────────────

    async def _advance(self, page: Any) -> None:
        """把列表往前推一格。

        三种手段按可靠性排序：
        1. 知道面板选择器 → 悬停上去滚轮
        2. 知道条目文案 → 把最后一条滚进视口，让容器自己滚（最通用）
        3. 都不行 → 滚整页
        """
        scroll_over = (self.ctx.config.targets.notice_scroll_over or "").strip()
        if scroll_over:
            await human_scroll(page, rounds=1, over=scroll_over)
            return

        locator = self._item_locator(page)
        if locator is not None:
            try:
                count = await locator.count()
                if count:
                    await locator.nth(count - 1).scroll_into_view_if_needed(timeout=5000)
                    await human_gap(0.6, 1.5)
                    return
            except Exception:
                pass

        await human_scroll(page, rounds=1)

    # ── 触底判定 ────────────────────────────────────────────

    async def _end_marker_visible(self, page: Any) -> bool:
        for text in self.ctx.config.targets.notice_end_texts:
            try:
                if await page.get_by_text(text, exact=False).count() > 0:
                    return True
            except Exception:
                continue
        return False

    async def _try_open_panel(self, page: Any, mirror: Any) -> bool:
        """按候选文案逐个试点，直到面板真的出现在页面上。

        为什么这样：写死一个文案（比如"消息"）很脆 —— 抖音改文案、加未读角标、
        或者把入口挪到别处，它就静默失效了，表现为"这个账号没人点赞"。
        实测还发现点「消息」打开的是**私信**页，而互动消息在「通知」下面。

        每点一次都验证面板是否可见，所以不会误判。
        """
        tried: list[str] = []
        for text in self.ctx.config.targets.notice_open_texts:
            if await self._panel_visible(page):
                break
            tried.append(text)
            try:
                locator = page.get_by_text(text, exact=True)
                if await locator.count() == 0:
                    locator = page.get_by_text(text, exact=False)
                if await locator.count() == 0:
                    continue
                await locator.first.click(timeout=4000)
            except Exception:
                continue
            await human_gap(1.2, 2.2)
            await mirror.drain(timeout=10.0)

        self.stats["open_tried"] = tried
        return await self._panel_visible(page)

    def _hit_login_wall(self, page: Any) -> bool:
        try:
            url = (page.url or "").lower()
        except Exception:
            return False
        return any(hint in url for hint in _LOGIN_WALL_URL_HINTS)

    # ── 主交互 ──────────────────────────────────────────────

    async def interact(self, page: Any, session: Any) -> None:
        from ..interact import run_actions

        tier = self.default_tier
        mirror = session.get(tier).mirror
        targets = self.ctx.config.targets
        max_rounds = max(1, int(targets.notice_max_rounds))
        idle_limit = max(1, int(targets.notice_idle_rounds))

        # ⚠️ 这里**不能**做鼠标微动。
        # 互动消息面板是活页：鼠标悬停在入口上才存在，一移开就自动关闭。
        # 任何"顺手动一下鼠标"的动作都会把刚打开的面板弄没。
        # （这个坑吃过：click 之后 micro_move，面板当场消失，dump 里什么都看不到。）
        pre = self.ctx.config.interaction(targets.notice_pre_actions)
        if pre:
            attempts: list[dict[str, Any]] = []
            for _ in (1, 2):
                pre_report = await run_actions(page, pre, export_dir=self.ctx.paths.export_dir)
                attempts.append(pre_report.summary())
                await mirror.drain(timeout=10.0)
                await human_gap(1.0, 2.0)
                if await self._panel_visible(page):
                    break
            self.stats["pre_attempts"] = attempts

        panel_opened = await self._panel_visible(page)

        # 兜底：预置动作没打开面板时，逐个试候选文案。
        # 每点一次都验证面板是否可见 —— 不靠猜哪个文案是对的。
        if not panel_opened:
            panel_opened = await self._try_open_panel(page, mirror)
        self.stats["panel_opened"] = panel_opened
        self.stats["notice_api_called"] = self._saw_notice_api(mirror)

        idle = 0
        rounds = 0
        stop_reason = "达到轮数上限"

        for _ in range(max_rounds):
            rounds += 1
            seen_before = len(mirror.peek())

            await self._advance(page)
            await mirror.drain(timeout=15.0)
            await human_gap(0.6, 1.6)

            if self._hit_login_wall(page):
                self.stats["login_wall"] = True
                stop_reason = "被重定向到登录/验证页"
                break

            if await self._end_marker_visible(page):
                self.stats["reached_end"] = True
                stop_reason = "页面提示暂时没有更多了"
                break

            if len(mirror.peek()) > seen_before:
                idle = 0
            else:
                idle += 1
                if idle >= idle_limit:
                    stop_reason = f"连续 {idle} 轮没有新响应"
                    break

        self.stats["rounds"] = rounds
        self.stats["stop_reason"] = stop_reason
        self.stats["item_source"] = self._item_source()

        # 硬失败：面板没开 → 一个点赞人都点不到。
        # 必须明确报错，绝不能让它表现成"这个账号没人点赞"。
        if not await self._panel_visible(page):
            raise RuntimeError(
                "互动消息面板没有打开 —— 页面上找不到「赞了你的作品」。"
                "实测点「消息」打开的是私信页，互动消息在「通知」下面；"
                "如果改了文案或结构，用 `scout notice --dump --manual` 看真实文案，"
                "然后改 config/default.yaml 里的 interactions.notice_pre。"
            )

        # 形态 B：逐条点开「等 N 人赞了你的作品」，取「赞过的人」完整名单
        await self._expand(page, session)

    # ── 逐条展开 ────────────────────────────────────────────

    async def _open_one(self, page: Any, index: int) -> bool:
        """打开第 index 条聚合通知的完整名单。

        优先点条目右侧那个 **› 箭头按钮** —— 实测这才是正确的目标，
        而且是图标、没有文字，只能按几何位置找（见 click_anchor_button）。

        找不到就退回点条目本身（有些版本整行都可点）。
        """
        from ..interact import run_actions

        targets = self.ctx.config.targets
        script = [dict(s) for s in self.ctx.config.interaction(targets.notice_click_actions)]
        if script:
            for step in script:
                if step.get("action") == "click_anchor_button":
                    step["nth"] = index          # 第几条通知，按顺序注入
            report = await run_actions(page, script, export_dir=self.ctx.paths.export_dir)
            if report.ok_count:
                self.stats.setdefault("open_method", []).append("arrow")
                return True
            detail = report.failed[0].detail if report.failed else "未知"
            self.stats.setdefault("arrow_failed", []).append(detail[:160])

        locator = self._item_locator(page)
        if locator is None:
            return False
        try:
            await locator.nth(index).scroll_into_view_if_needed(timeout=5000)
            await human_gap(0.3, 0.9)
            await locator.nth(index).click(timeout=8000)
            self.stats.setdefault("open_method", []).append("item")
            return True
        except Exception:
            return False

    def _like_notices(self, mirror: Any) -> list[dict[str, Any]]:
        """从已捕获的 notice 响应里解析出点赞类通知，**按 DOM 顺序排列**。

        DOM 里「等 N 人赞了你的作品」的先后顺序，与接口
        notice_list_v2 里 type=41 且有 from_user 的条目顺序一致。
        有了这个映射，才知道"点第几个箭头"对应"哪个作品"。
        """
        from ..parse import parse_payload

        merged: list[dict[str, Any]] = []
        try:
            items = list(mirror.peek())
        except Exception:
            return merged
        for item in items:
            if "/notice" not in item.url or not getattr(item, "is_json", False) or not item.body:
                continue
            try:
                res = parse_payload(item.url, item.json())
            except Exception:
                continue
            for n in res.notices:
                if n.get("type") != 41 or not n.get("aweme_id"):
                    continue
                if any(m["notice_id"] == n["notice_id"] for m in merged):
                    continue
                merged.append(n)
        return merged

    async def _expand(self, page: Any, session: Any) -> None:
        from ..interact import run_actions

        targets = self.ctx.config.targets
        # 点击动作和展开后的动作，任一存在就该走逐条展开流程。
        # （点击动作现在承担"打开名单"这件事，展开动作只是等加载 + 滚动）
        click_script = self.ctx.config.interaction(targets.notice_click_actions)
        actions = self.ctx.config.interaction(targets.notice_expand_actions)
        if not click_script and not actions:
            return

        tier = self.default_tier
        mirror = session.get(tier).mirror
        export_dir = self.ctx.paths.export_dir
        close_actions = self.ctx.config.interaction(targets.notice_close_actions) or [
            {"action": "press", "key": "Escape", "optional": True}
        ]

        source = self._item_source()
        if not source and not self.ctx.config.interaction(targets.notice_click_actions):
            self.stats["expand"] = {
                "mode": "skipped",
                "error": "notice_item_selector / notice_item_pattern / notice_click_actions 都没配",
            }
            return

        limit = max(0, int(targets.notice_max_items))
        opened = 0
        failed_items = 0
        steps_ok = 0
        steps_failed = 0

        # 关键：把"第 N 个箭头"映射到"哪个作品"。
        # 覆盖层显示的是**整个作品的完整点赞人**（不只那条通知里的那几个人），
        # 所以一个作品只需要开一次。
        notices = self._like_notices(mirror)
        plan: list[tuple[int, str]] = []
        seen_works: set[str] = set()
        for idx, n in enumerate(notices):
            aweme_id = n.get("aweme_id") or ""
            if not aweme_id or aweme_id in seen_works:
                continue
            seen_works.add(aweme_id)
            plan.append((idx, aweme_id))
        plan = plan[:limit]

        self.stats["like_notices"] = len(notices)
        self.stats["overlay_plan"] = [{"anchor_index": i, "aweme_id": a} for i, a in plan]

        for anchor_index, aweme_id in plan:
            await self._recover_list(page, session)

            # 每次开覆盖层用独立的 sink，抽出来的链接才能归属到正确的作品
            sink: dict[str, Any] = {}
            if not await self._open_one(page, anchor_index):
                failed_items += 1
                continue
            opened += 1
            await human_gap(1.0, 2.0)

            report = await run_actions(page, actions, export_dir=export_dir, sink=sink)
            steps_ok += report.ok_count
            steps_failed += len(report.failed)
            await mirror.drain(timeout=12.0)

            links = sink.get("user_links") or []
            if links:
                self.harvested.setdefault(aweme_id, []).extend(links)

            await run_actions(page, close_actions, export_dir=export_dir)
            await human_gap(0.7, 1.8)

        self.stats["expand"] = {
            "mode": "overlay",
            "source": source,
            "items_opened": opened,
            "items_failed": failed_items,
            "steps_ok": steps_ok,
            "steps_failed": steps_failed,
            "open_methods": self.stats.get("open_method"),
            "arrow_failed": self.stats.get("arrow_failed"),
            "harvested_works": len(self.harvested),
            "harvested_likers": sum(len(v) for v in self.harvested.values()),
        }

    async def _recover_list(self, page: Any, session: Any) -> None:
        """确保回到互动消息列表，并且能点到目标条目。

        覆盖层关掉后 SPA 经常把列表状态弄丢，所以认不出来就重新加载 + 恢复面板。
        """
        locator = self._item_locator(page)
        try:
            if locator is not None and await locator.count() > 0:
                return
        except Exception:
            pass

        targets = self.ctx.config.targets
        try:
            await page.goto(targets.notice_url, wait_until="domcontentloaded", timeout=25_000)
            await human_gap(1.0, 2.2)
            pre = self.ctx.config.interaction(targets.notice_pre_actions)
            if pre:
                from ..interact import run_actions

                await run_actions(page, pre, export_dir=self.ctx.paths.export_dir)
                await human_gap(0.8, 1.6)
            await self._advance(page)
            await session.get(self.default_tier).mirror.drain(timeout=10.0)
        except Exception as exc:
            self.stats.setdefault("expand", {})["recover_error"] = str(exc)

    def quota_cost(self) -> int:
        """一次导航 + 每个点开的通知条目各算一个动作。"""
        expand = self.stats.get("expand") or {}
        opened = int(expand.get("items_opened") or 0)
        return 1 + opened

    # ── 落库 + 扇出 ─────────────────────────────────────────

    def persist(self, parsed: ParseResult, task: dict[str, Any]) -> dict[str, Any]:
        ctx = self.ctx
        raw_id = parsed.raw_blob_id
        added = ctx.like_edges.add_many(parsed.like_edges, tier="a", raw_blob_id=raw_id)

        # from_user 本身带 sec_uid / nickname / follower_count / unique_id / 认证，
        # 所以这里就能把资料表填上一大部分 —— 不用访问他们主页。
        # 这是省配额的关键：档 B 只需要给真正要深挖的人跑。
        saved_users = 0
        for user in parsed.users:
            if user.get("sec_uid"):
                ctx.users.upsert(user, raw_blob_id=raw_id)
                ctx.snapshots.record(user["sec_uid"], user)
                saved_users += 1

        for work in parsed.works:
            if work.get("aweme_id"):
                ctx.works.upsert(work, raw_blob_id=raw_id)

        # 扇出：只为资料不完整的人建任务（有粉丝数说明画像已经够了）
        enqueued = 0
        for edge in parsed.like_edges:
            sec_uid = edge["sec_uid"]
            ctx.users.ensure(sec_uid, discovered_from="notice")
            if ctx.tasks.enqueue("fetch_profile", sec_uid, "b", priority=50):
                enqueued += 1

        incomplete = sum(1 for e in parsed.like_edges if e.get("has_more_likers"))

        # 覆盖层 DOM 抓到的完整点赞人 —— 这部分接口里根本没有
        harvested_edges: list[dict[str, Any]] = []
        for aweme_id, links in self.harvested.items():
            for link in links:
                sec_uid = link.get("sec_uid")
                if not sec_uid:
                    continue
                harvested_edges.append(
                    {
                        "sec_uid": sec_uid,
                        "aweme_id": aweme_id,
                        "notice_id": f"overlay:{aweme_id}",
                        "notice_kind": "digg",
                        "has_more_likers": False,
                        "source_url": "dom:overlay",
                    }
                )
                name = (link.get("nickname") or "").strip()
                if name and name != "<null>":
                    ctx.users.upsert({"sec_uid": sec_uid, "nickname": name})
                ctx.users.ensure(sec_uid, discovered_from="overlay")

        harvested_added = (
            ctx.like_edges.add_many(harvested_edges, tier="a") if harvested_edges else 0
        )

        distinct_likers = len({e["sec_uid"] for e in parsed.like_edges})
        ctx.notice_runs.record(
            tier="a",
            url=task.get("target") or self.ctx.config.targets.notice_url,
            rounds=int(self.stats.get("rounds", 0)),
            captured=int(task.get("_captured", 0) or 0),
            edges_seen=len(parsed.like_edges),
            new_edges=added,
            distinct_likers=distinct_likers,
            reached_end=bool(self.stats.get("reached_end")),
            stop_reason=str(self.stats.get("stop_reason") or ""),
            raw_ids=[raw_id] if raw_id else [],
        )

        expand = self.stats.get("expand") or {}
        ctx.db.log_event(
            "info",
            "notice",
            f"互动消息采集：{len(parsed.works)} 个作品、{len(parsed.like_edges)} 条点赞边"
            f"（新增 {added}），触底={'是' if self.stats.get('reached_end') else '否'}"
            + (f"；{incomplete} 条通知的名单不完整，需点开「赞过的人」" if incomplete else ""),
            {"distinct_likers": distinct_likers, "incomplete": incomplete, "expand": expand},
        )

        return {
            "new_edges": added,
            "edges_seen": len(parsed.like_edges),
            "distinct_likers": distinct_likers,
            "users_saved": saved_users,
            "works_saved": len(parsed.works),
            "new_profile_tasks": enqueued,
            "incomplete_notices": incomplete,
            "harvested_works": len(self.harvested),
            "harvested_likers": len(harvested_edges),
            "harvested_new": harvested_added,
            "rounds": self.stats.get("rounds"),
            "reached_end": self.stats.get("reached_end"),
            "stop_reason": self.stats.get("stop_reason"),
            "like_notices": self.stats.get("like_notices"),
            "expand": expand or None,
        }
