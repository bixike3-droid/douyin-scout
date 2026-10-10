"""可见性勘探工具的实现。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlparse

from ..app import AppContext
from ..humanize import human_gap, human_scroll, micro_move
from ..parse.registry import ParseResult, parse_payload
from ..util import iso, safe_filename, truncate

# 登录墙的常见信号。抖音改版频繁，所以只作为"提示"，不作为判定依据。
LOGIN_WALL_HINTS = (
    "login",
    "passport",
    "verify",
    "captcha",
    "verifycenter",
    "sso",
)


@dataclass
class ProbeItem:
    url: str
    status: int
    content_type: str
    byte_size: int
    is_json: bool
    error: str = ""
    raw_id: int | None = None
    parsed: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status": self.status,
            "content_type": self.content_type,
            "byte_size": self.byte_size,
            "is_json": self.is_json,
            "error": self.error,
            "raw_id": self.raw_id,
            "parsed": self.parsed,
        }


@dataclass
class ProbeReport:
    url: str
    tier: str
    started_at: str = field(default_factory=iso)
    finished_at: str = ""
    final_url: str = ""
    title: str = ""
    items: list[ProbeItem] = field(default_factory=list)
    login_wall_suspected: bool = False
    login_wall_evidence: list[str] = field(default_factory=list)
    parse_ok: bool = False
    notes: list[str] = field(default_factory=list)
    actions: dict[str, Any] = field(default_factory=dict)
    dump: dict[str, Any] = field(default_factory=dict)
    static_skipped: int = 0
    api_summary: list[dict[str, Any]] = field(default_factory=list)
    # 从 DOM 抽到的完整点赞人（接口里没有这部分）
    harvested: list[dict[str, Any]] = field(default_factory=list)
    harvest_works: list[str] = field(default_factory=list)
    json_path: str = ""
    md_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "tier": self.tier,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "final_url": self.final_url,
            "title": self.title,
            "login_wall_suspected": self.login_wall_suspected,
            "login_wall_evidence": self.login_wall_evidence,
            "parse_ok": self.parse_ok,
            "notes": self.notes,
            "actions": self.actions,
            "dump": self.dump,
            "static_skipped": self.static_skipped,
            "api_summary": self.api_summary,
            "harvested": self.harvested,
            "harvest_works": self.harvest_works,
            "items": [i.to_dict() for i in self.items],
        }

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append(f"# 勘探报告 {self.started_at}")
        lines.append("")
        lines.append(f"- 目标 URL：`{self.url}`")
        lines.append(f"- 档位：`{self.tier}`")
        lines.append(f"- 落地 URL：`{self.final_url}`")
        lines.append(f"- 页面标题：{self.title or '（取不到）'}")
        lines.append(f"- 捕获响应数：**{len(self.items)}**（数据接口）"
                     + (f"，另有 {self.static_skipped} 个静态资源已跳过" if self.static_skipped else ""))
        lines.append(f"- 是否疑似登录墙：**{'是' if self.login_wall_suspected else '否'}**")
        if self.login_wall_evidence:
            lines.append(f"  - 证据：{', '.join(self.login_wall_evidence)}")
        lines.append(f"- 是否解析出数据：**{'是' if self.parse_ok else '否'}**")

        if self.api_summary:
            lines.append("")
            lines.append("## 发现的数据接口（按请求数排序）")
            lines.append("")
            lines.append("| 接口路径 | 请求数 | 用户 | 作品 | 点赞边 |")
            lines.append("|----------|--------|------|------|--------|")
            for row in self.api_summary:
                lines.append(
                    f"| `{truncate(row['path'], 80)}` | {row['count']} | {row['users']} "
                    f"| {row['works']} | {row['like_edges']} |"
                )
            lines.append("")
            lines.append("> 这一张表就是答案：哪个接口返回了点赞人，看它。")
            lines.append("> 把它填进 `src/scout/parse/registry.py` 和 `session/mirror.py` 的 include 模式。")
        if self.notes:
            lines.append("")
            lines.append("## 备注")
            for note in self.notes:
                lines.append(f"- {note}")

        if self.dump:
            lines.append("")
            lines.append("## 页面上的可见短文本（找按钮文案用）")
            lines.append("")
            for step in self.dump.get("detail", []):
                if step.get("action") == "dump_texts" and step.get("ok"):
                    lines.append("```")
                    for chunk in str(step.get("detail", "")).split(" | "):
                        lines.append(chunk)
                    lines.append("```")
                elif step.get("action") == "dump_network" and step.get("ok"):
                    lines.append("")
                    lines.append("## 页面请求过的所有 URL（浏览器自己记的，跑不掉）")
                    lines.append("")
                    lines.append("```")
                    for chunk in str(step.get("detail", "")).split(" | "):
                        lines.append(chunk)
                    lines.append("```")
                elif step.get("action") == "dump_html":
                    lines.append(f"- DOM 快照：{step.get('detail')}")

        if self.actions:
            lines.append("")
            lines.append("## 交互动作执行结果")
            lines.append("")
            lines.append(
                f"共 {self.actions.get('steps', 0)} 步，成功 {self.actions.get('ok', 0)}，"
                f"失败 {self.actions.get('failed', 0)}"
                + ("，**中途中止**" if self.actions.get("aborted") else "")
            )
            lines.append("")
            lines.append("| 动作 | 结果 | 说明 |")
            lines.append("|------|------|------|")
            for step in self.actions.get("detail", []):
                mark = "✓" if step.get("ok") else "✗"
                lines.append(f"| {step.get('action')} | {mark} | {truncate(step.get('detail') or '', 70)} |")

        lines.append("")
        lines.append("## 捕获到的响应")
        lines.append("")
        lines.append("| # | 状态 | 大小 | JSON | 解析结果 | URL |")
        lines.append("|---|------|------|------|----------|-----|")
        for idx, item in enumerate(self.items, 1):
            parsed = ""
            if item.parsed:
                parsed = f"U{item.parsed.get('users', 0)}/W{item.parsed.get('works', 0)}/L{item.parsed.get('like_edges', 0)}"
            lines.append(
                f"| {idx} | {item.status} | {item.byte_size} | {'✓' if item.is_json else ''} "
                f"| {parsed} | `{truncate(item.url, 120)}` |"
            )
        lines.append("")
        lines.append("> U=用户 W=作品 L=点赞边。非 JSON 或被拦截的资源不参与解析。")
        lines.append("")
        lines.append("## 下一步")
        lines.append("")
        lines.append("1. 在上表里找出真正返回数据的那几个接口，把 URL 模式填进")
        lines.append("   `config/local.yaml` 的 `browser.…` 与采集器的 include 模式。")
        lines.append("2. 如果解析结果全是 0，说明接口结构变了：用 `scout replay <raw_id>`")
        lines.append("   对归档里的原始响应重新解析，不用重新采集。")
        lines.append("3. 把结论写进 `docs/visibility-report.md`。")
        return "\n".join(lines)


class Prober:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    async def run(
        self,
        url: str,
        *,
        tier: str = "b",
        scroll_rounds: int | None = None,
        settle_s: float = 2.0,
        export_dir: Path | None = None,
        actions: str = "",
        dump: bool = False,
        notice_flow: bool = False,
        manual_prompt: str = "",
        manual_seconds: int = 0,
        harvest: bool = False,
    ) -> ProbeReport:
        from ..interact import run_actions

        ctx = self.ctx
        report = ProbeReport(url=url, tier=tier)
        session = await ctx.open_session()
        sess = await session.ensure(tier)

        # 勘探阶段把 URL 全收（目的是看清楚有哪些接口），
        # 但静态资源的正文仍然不读 —— 那是浏览器卡顿的头号原因。
        sess.mirror.include = ()
        sess.mirror.capture_static_bodies = ctx.config.storage.archive_static
        sess.mirror.clear()

        page = await session.goto(tier, url, settle_s=settle_s)
        try:
            report.title = (await page.title()) or ""
        except Exception:
            report.title = ""

        await micro_move(page)

        # 人工介入模式：把浏览器交给人操作，期间照常镜像所有响应。
        # 这是自动化失效时的逃生出口 —— 抖音改 UI 时不用干等。
        if manual_prompt:
            import asyncio
            import time

            print("\n" + "=" * 62)
            print(manual_prompt)
            print("=" * 62)

            export_dir = ctx.paths.export_dir
            export_dir.mkdir(parents=True, exist_ok=True)
            stamp = report.started_at.replace(":", "").replace("-", "")[:15]

            if manual_seconds > 0:
                # 倒计时模式。
                # 为什么需要它：抖音的「互动消息」面板是**活页** ——
                # 鼠标悬停才存在，移开就关闭。人根本没法"把面板留着"
                # 再走回终端按回车。所以改成给一段固定操作时间，
                # 期间持续把响应收进来，并每隔几秒截一张图留证。
                deadline = time.monotonic() + manual_seconds
                shots: list[str] = []
                last_shot = 0.0
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    print(
                        f"\r  还剩 {int(remaining):>2} 秒 — 请在浏览器里操作"
                        f"（面板是活页，鼠标别移开）",
                        end="", flush=True,
                    )
                    await asyncio.sleep(0.4)
                    await sess.mirror.drain(timeout=2.0)
                    now = time.monotonic()
                    if now - last_shot >= 5.0 and len(shots) < 10:
                        last_shot = now
                        try:
                            shot = export_dir / f"manual-{stamp}-{len(shots) + 1}.png"
                            await page.screenshot(path=str(shot))
                            shots.append(str(shot))
                        except Exception:
                            pass
                print()
                if shots:
                    report.notes.append("人工介入截图：" + "；".join(shots))
            else:
                await asyncio.to_thread(input, "操作完成后回到本终端按回车继续（别关掉页面）：")
                try:
                    shot = export_dir / f"manual-{stamp}.png"
                    await page.screenshot(path=str(shot))
                    report.notes.append(f"人工介入截图：{shot}")
                except Exception as exc:
                    report.notes.append(f"截图失败：{exc}")

            await sess.mirror.drain(timeout=15.0)
            report.notes.append("人工介入模式：响应来自手动操作")

        # 互动消息是面板形态，默认是关的 —— 不先点开，
        # 列表接口永远不会被调用，勘探结果里一个数据接口都不会有。
        if notice_flow:
            pre = ctx.config.interaction(ctx.config.targets.notice_pre_actions)
            if pre:
                pre_report = await run_actions(page, pre, export_dir=ctx.paths.export_dir)
                report.actions = pre_report.summary()
                await human_gap(0.8, 1.8)
            else:
                report.notes.append(
                    "targets.notice_pre_actions 没配 —— 如果面板默认是关的，"
                    "列表接口不会被调用，勘探会看不到任何数据接口"
                )

        rounds = scroll_rounds if scroll_rounds is not None else int(ctx.tier_cfg(tier).scroll_rounds)
        # 人工介入模式下不自动滚动：用户刚点开的面板，别手贱把它滚没了
        if manual_prompt:
            rounds = 0
        await human_scroll(
            page, rounds=rounds, over=(ctx.config.targets.notice_scroll_over or "")
        )
        await human_gap(1.0, 2.0)

        # 先把页面上有什么按钮、DOM 长什么样导出来 —— 定位选择器靠它，不靠猜
        if dump:
            dump_script = [
                {"action": "dump_texts", "max": 400, "max_len": 24, "optional": True},
                {"action": "dump_network", "max": 250, "skip_static": True, "optional": True},
                {"action": "dump_html", "selector": "body", "path": f"dom-{tier}.html",
                 "max_chars": 400_000, "optional": True},
            ]
            dump_report = await run_actions(page, dump_script, export_dir=ctx.paths.export_dir)
            report.dump = dump_report.summary()
            await human_gap(0.5, 1.2)

        # 勘探时可以试跑交互脚本，看它点了什么、有没有把目标响应触发出来
        script = ctx.config.interaction(actions)
        if script:
            action_report = await run_actions(page, script, export_dir=ctx.paths.export_dir)
            if report.actions:
                # 把 notice_flow 的 pre 步骤也并进去，报告里看得到完整过程
                merged = dict(report.actions)
                merged["steps"] = merged.get("steps", 0) + action_report.summary()["steps"]
                merged["ok"] = merged.get("ok", 0) + action_report.ok_count
                merged["failed"] = merged.get("failed", 0) + len(action_report.failed)
                merged["detail"] = list(merged.get("detail", [])) + action_report.summary()["detail"]
                report.actions = merged
            else:
                report.actions = action_report.summary()
            await human_gap(0.8, 2.0)
        elif actions:
            report.notes.append(f"interactions 里没有名为 {actions!r} 的脚本，已跳过")

        await sess.mirror.drain(timeout=30.0)

        try:
            report.final_url = page.url
        except Exception:
            report.final_url = url

        captured = sess.mirror.take()
        aggregated = ParseResult(url=url, kind="probe")

        # 静态资源和数据接口分开处理：一次页面加载几百个 JS/CSS，
        # 全归档既浪费磁盘又会把真正的接口淹掉（也会把配额烧穿）。
        data_items = [c for c in captured if c.is_data]
        static_items = [c for c in captured if not c.is_data]
        report.static_skipped = len(static_items)
        todo = captured if ctx.config.storage.archive_static else data_items

        if not data_items:
            report.notes.append(
                f"⚠️ 一个数据接口都没触发（收到 {len(captured)} 个响应，全是静态资源）。"
                f"最常见原因：面板/列表没打开。用 --actions 或 notice_pre_actions 先把面板点开。"
            )

        for item in todo:
            entry = ProbeItem(
                url=item.url,
                status=item.status,
                content_type=item.content_type,
                byte_size=item.byte_size,
                is_json=item.is_json,
                error=item.error,
            )
            if item.body:
                ref = ctx.archive.save(
                    item.body,
                    url=item.url,
                    tier=tier,
                    content_type=item.content_type,
                    source="probe",
                    note=f"probe:{safe_filename(url)}",
                )
                entry.raw_id = ref.id
                ctx.telemetry.log_request(
                    tier=tier, url=item.url, status=item.status,
                    ok=200 <= item.status < 400, byte_size=item.byte_size,
                    duration_ms=item.duration_ms, error=item.error, raw_blob_id=ref.id,
                )

            if item.is_json and item.body:
                parsed = parse_payload(item.url, item.json(), raw_blob_id=entry.raw_id)
                aggregated.merge(parsed)
                entry.parsed = {
                    "kind": parsed.kind,
                    "users": len(parsed.users),
                    "works": len(parsed.works),
                    "like_edges": len(parsed.like_edges),
                    "parser": parsed.parser_name,
                }
            report.items.append(entry)

        report.api_summary = _summarize_apis(report.items)
        report.parse_ok = not aggregated.is_empty()

        # 收尾：从 DOM 里把「赞过的人」名单抽出来。
        # 实测确认完整名单**不在任何接口响应里**，只在 DOM 里 ——
        # 所以这一步是拿全名单的唯一途径，不是可选项。
        if harvest:
            sink: dict[str, Any] = {}
            harvest_report = await run_actions(
                page,
                [{"action": "extract_user_links", "max": 500, "optional": True}],
                export_dir=ctx.paths.export_dir,
                sink=sink,
            )
            links = sink.get("user_links") or []
            report.harvested = links
            report.actions = report.actions or harvest_report.summary()
            report.notes.append(f"DOM 抽取：{len(links)} 个用户链接")
            if not links:
                report.notes.append(
                    "没抽到用户链接 —— 覆盖层当时没开着。"
                    "人工介入模式下请把鼠标留在名单上，倒计时结束前别移开。"
                )
            # 归属：当前这批通知里，哪些作品的名单不完整
            incomplete = [n for n in aggregated.notices if n.get("has_more_likers")]
            works = []
            for n in incomplete:
                if n.get("aweme_id") and n["aweme_id"] not in works:
                    works.append(n["aweme_id"])
            report.harvest_works = works if len(works) == 1 else []
            if len(works) == 1:
                report.notes.append(f"名单归属作品：{works[0]}")
            elif works:
                report.notes.append(
                    f"有 {len(works)} 个作品的名单都不完整，无法自动归属；"
                    f"这次抽到的人只入库不建关联（{works}）"
                )

        low = (report.final_url or "").lower()
        hits = [h for h in LOGIN_WALL_HINTS if h in low]
        if hits:
            report.login_wall_suspected = True
            report.login_wall_evidence.extend(f"URL 含 {h}" for h in hits)

        # 配额按"动作"计：勘探就是一次导航 = 1 个动作。
        # 收到的数据接口数量只作为观测指标，不计费 ——
        # 按响应数计费会让一次勘探消耗上百点配额，而那些请求大多是站点自己的。
        ctx.quota.consume(tier, 1)
        report.finished_at = iso()

        export_dir = export_dir or ctx.paths.export_dir
        export_dir.mkdir(parents=True, exist_ok=True)
        stamp = report.started_at.replace(":", "").replace("-", "")[:15]
        json_path = export_dir / f"probe-{stamp}.json"
        md_path = export_dir / f"probe-{stamp}.md"
        json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(report.to_markdown(), encoding="utf-8")
        report.json_path, report.md_path = str(json_path), str(md_path)

        ctx.db.log_event(
            "info", "probe",
            f"勘探 {url}：捕获 {len(report.items)} 个响应，解析成功={report.parse_ok}",
            {"md": report.md_path},
        )
        return report


def _summarize_apis(items: Sequence[ProbeItem]) -> list[dict[str, Any]]:
    """按接口路径聚合，把"哪个接口返回了数据"排在前面。

    没有这张表的话，几百个响应里真正的接口根本看不见 —— 这是勘探报告里最有用的一节。
    """
    agg: dict[str, dict[str, Any]] = {}
    for item in items:
        try:
            path = urlparse(item.url).path or item.url
        except Exception:
            path = item.url
        row = agg.setdefault(
            path,
            {"path": path, "count": 0, "users": 0, "works": 0,
             "like_edges": 0, "json": 0, "bytes": 0},
        )
        row["count"] += 1
        row["bytes"] += item.byte_size
        if item.is_json:
            row["json"] += 1
        if item.parsed:
            row["users"] += int(item.parsed.get("users", 0))
            row["works"] += int(item.parsed.get("works", 0))
            row["like_edges"] += int(item.parsed.get("like_edges", 0))

    # 先按"解析出的数据量"排，再按请求数排 —— 有数据的接口永远在最前
    return sorted(
        agg.values(),
        key=lambda r: (-(r["like_edges"] * 100 + r["users"] * 10 + r["works"]), -r["count"]),
    )


def save_endpoint(config_path: Path, key: str, value: str) -> None:
    """把勘探出来的地址写进 config/local.yaml，避免手改出错。"""
    import yaml

    data: dict[str, Any] = {}
    if config_path.is_file():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    data.setdefault("targets", {})[key] = value
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
