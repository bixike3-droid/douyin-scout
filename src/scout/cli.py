"""命令行入口。

约定：
- 所有命令都通过 AppContext 取依赖，不自己 new。
- 需要浏览器的命令才会启动 Playwright，纯查询命令保持轻量。
- 任何写操作都要能重复执行（幂等）。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

try:
    import typer
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
except ImportError as _exc:  # pragma: no cover
    sys.stderr.write(
        "缺少命令行依赖（typer / rich）。请在项目根目录执行：\n"
        "    pwsh -File scripts/setup.ps1\n"
        "或手动安装：\n"
        "    .\\.venv\\Scripts\\python.exe -m pip install -e .\n\n"
        "如果只是想确认核心逻辑是否正常（不需要联网），可以跑：\n"
        "    python scripts/smoke.py\n\n"
        f"原始错误：{_exc}\n"
    )
    raise SystemExit(2) from None

from .analyze import analyze_users, export_csv, overview, render_markdown
from .app import AppContext
from .config import load_config
from .paths import DEFAULT_ACCOUNT, Paths, get_current_account, set_current_account
from .store.account import adopt as account_adopt
from .store.account import check_account, stored_identity
from .store.migrate_layout import migrate_legacy, needs_migration
from .util import truncate

app = typer.Typer(
    name="scout",
    help="抖音互动数据采集与分析框架（本地自用，稳定优先）",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@app.callback()
def _main(
    account: str = typer.Option(
        DEFAULT_ACCOUNT,
        "--account",
        "-a",
        envvar="SCOUT_ACCOUNT",
        help="账号槽位名。每个账号是一套完全独立的数据目录，互不影响。",
    ),
) -> None:
    """全局入口：先确定用哪个账号的数据目录。

    账号隔离靠独立目录实现 —— 切换账号不会污染另一套数据。
    """
    try:
        set_current_account(account)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=2) from None
    _ensure_layout()


def _ensure_layout() -> None:
    """首次运行时把旧布局的数据搬进账号目录。

    只搬一次（幂等），而且**绝不覆盖**已存在的目标 —— 宁可停下让人处理，
    也不要静默覆盖数据。
    """
    paths = Paths.build()
    if not needs_migration(paths):
        return
    result = migrate_legacy(paths, account=paths.account)
    if result.changed:
        console.print(
            f"[yellow]检测到旧版数据布局，已迁移到账号目录「{paths.account}」[/]"
        )
        for src, dst in result.moved:
            console.print(f"  [dim]{src} → {dst}[/]")
    if result.failed:
        for src, reason in result.failed:
            console.print(f"[red]迁移失败：{src} —— {reason}[/]")
        raise typer.Exit(code=3)
    if result.skipped:
        for note in result.skipped:
            console.print(f"[yellow]跳过（目标已存在，未覆盖）：{note}[/]")


# ── 辅助 ─────────────────────────────────────────────────────


def _ctx(*, migrate_db: bool = True) -> AppContext:
    return AppContext.create(migrate_db=migrate_db)


def _run(coro):
    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        console.print("\n[yellow]已中断。running 任务会在下次启动时被自动捞回。[/]")
        raise typer.Exit(code=130) from None


def _kv_table(title: str, rows: dict) -> Table:
    table = Table(title=title, show_header=False, box=None)
    table.add_column("k", style="cyan", no_wrap=True)
    table.add_column("v")
    for key, value in rows.items():
        table.add_row(str(key), str(value))
    return table


# ── 初始化 ───────────────────────────────────────────────────


@app.command()
def init() -> None:
    """建目录、建库、跑迁移，并生成 local.yaml（如果还没有）。"""
    paths = Paths.build().ensure()
    example = paths.config_dir / "local.yaml.example"
    local = paths.local_config
    if not local.exists() and example.is_file():
        local.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        console.print(f"[green]已生成 {local}[/]（不放版本库，随便改）")

    with _ctx() as ctx:
        console.print(_kv_table("初始化完成", {
            "项目根": ctx.paths.root,
            "数据库": ctx.paths.db_path,
            "原始归档": ctx.paths.raw_dir,
            "配置来源": ", ".join(ctx.config.sources) or "（默认值）",
            "启用档位": ", ".join(ctx.config.enabled_tiers()),
        }))
    console.print("\n下一步：`scout probe --help` 看怎么勘探，或 `scout web` 打开面板。")


@app.command("account")
def cmd_account(
    action: str = typer.Argument(
        "show", help="show=当前账号｜list=所有账号｜adopt=认领当前登录号｜check=核对登录态"
    ),
    force: bool = typer.Option(False, "--yes", "-y", help="adopt 时跳过确认"),
) -> None:
    """账号管理：看当前用哪套数据、有哪些账号、核对/认领登录身份。

    账号隔离靠"一个账号一个数据目录"实现，切换账号不会污染另一套数据。
    """
    from rich.table import Table

    paths = Paths.build()

    if action == "list":
        names = paths.list_accounts()
        current = get_current_account()
        if not names:
            console.print("[yellow]还没有任何账号目录[/]")
            return
        table = Table(title="账号目录")
        for col in ("账号", "数据目录", "在用"):
            table.add_column(col)
        for n in names:
            table.add_row(n, str(paths.account_dirs(n)), "←" if n == current else "")
        console.print(table)
        return

    if action == "show":
        with _ctx() as ctx:
            sec, nick = stored_identity(ctx)
            console.print(_kv_table("当前账号", {
                "账号槽位": paths.account,
                "数据目录": str(paths.data_dir),
                "数据库": "存在" if paths.db_path.exists() else "还没有（首次采集会创建）",
                "数据属于": (f"{nick}（{sec[:20]}…）" if sec else "还没记录（首次采集后自动记录）"),
                "所有账号": ", ".join(paths.list_accounts()) or "（仅当前）",
            }))
        return

    if action == "check":
        with _ctx() as ctx:
            report = _run(_probe_identity(ctx))
            console.print(f"[{'green' if report.ok else 'red'}]{'✓' if report.ok else '✗'} {report.message}[/]")
            if not report.ok:
                raise typer.Exit(code=4)
        return

    if action == "adopt":
        with _ctx() as ctx:
            report = _run(_probe_identity(ctx))
            if not report.live_sec_uid:
                console.print("[red]拿不到当前登录身份。先跑 scout login --tier a[/]")
                raise typer.Exit(code=4)
            if report.ok:
                console.print(f"[green]✓ {report.message}，无需认领[/]")
                return
            console.print(Panel.fit(
                f"当前数据目录：[bold]{paths.account}[/]\n"
                f"原本属于：[bold]{report.stored_nickname or (report.stored_sec_uid[:20] or '（空）')}[/]\n"
                f"现在登录的是：[bold]{report.live_nickname or report.live_sec_uid[:20]}[/]\n\n"
                "[yellow]认领后这套目录会记成新号。\n"
                "已采集的旧数据不会删除，但两个号的数据会混在一起，且无法事后分辨。\n"
                "推荐改用： scout --account <新名字> ...[/]",
                title="认领确认",
            ))
            if not force and not typer.confirm("确定要把这个目录认成新号吗？"):
                raise typer.Exit(code=1)
            account_adopt(ctx, report.live_sec_uid, report.live_nickname)
            console.print(f"[green]✓ 已认领：{report.live_nickname or report.live_sec_uid[:20]}[/]")
        return

    console.print(f"[red]未知操作：{action}。可用：show | list | adopt | check[/]")
    raise typer.Exit(code=2)


def _verify_account_or_die() -> None:
    """开跑前核对身份；不一致就停下并给出处理办法。

    只在库里**已有身份记录**时才核对 —— 首次采集还没有记录，让采集流程自己去建立。
    """
    with _ctx() as ctx:
        sec, nick = stored_identity(ctx)
        if not sec:
            return
        report = _run(_probe_identity(ctx))
        if report.ok:
            return
        console.print(Panel.fit(
            f"[red]{report.message}[/]",
            title="账号核对未通过",
        ))
        raise typer.Exit(code=4)


async def _probe_identity(ctx):
    """调一次 profile/self 拿到当前登录身份，跟库里记录比对。"""
    from .collect.self_profile import SelfCollector

    live_sec = live_nick = ""
    try:
        session = await ctx.open_session()
        await session.ensure("a")
        page = await session.page("a")
        collector = SelfCollector(ctx)
        # 必须先站在抖音域下 —— 页面内 fetch 是同源请求，
        # 停在 about:blank 时会被当跨域拦掉，拿回空 body（踩过一次）
        try:
            current = page.url or ""
        except Exception:
            current = ""
        if "douyin.com" not in current:
            page = await session.goto(
                "a", ctx.config.targets.home_url, settle_s=1.5
            )
        body, status, err = await collector.fetch_in_page(page, collector.api_url("self", 0))
        if body:
            payload = json.loads(body.decode("utf-8", errors="replace"))
            user = payload.get("user") or {}
            live_sec = user.get("sec_uid") or ""
            live_nick = user.get("nickname") or ""
        elif status != 200:
            console.print(f"[yellow]查询登录身份失败：status={status} {err}[/]")
    except Exception as exc:
        console.print(f"[yellow]查询登录身份失败：{type(exc).__name__}: {exc}[/]")
    finally:
        try:
            await ctx.session.stop()
        except Exception:
            pass
    return check_account(ctx, live_sec_uid=live_sec, live_nickname=live_nick)


@app.command("doctor")
def doctor() -> None:
    """环境自检：依赖、配置、数据库、登录态锁。装不上依赖或跑不动时先看这里。"""
    import importlib.util

    rows: dict[str, str] = {}
    rows["Python"] = f"{sys.version.split()[0]}（需 >=3.11）"

    deps = {
        "yaml": ("PyYAML", "配置解析"),
        "typer": ("typer", "命令行"),
        "rich": ("rich", "终端输出"),
        "playwright": ("playwright", "浏览器（采集必需）"),
        "fastapi": ("fastapi", "本地面板"),
        "uvicorn": ("uvicorn", "本地面板"),
        "pytest": ("pytest", "测试（可选）"),
    }
    missing: list[str] = []
    for module, (package, purpose) in deps.items():
        found = importlib.util.find_spec(module) is not None
        rows[package] = f"{'✓' if found else '✗ 缺失'}  {purpose}"
        if not found:
            missing.append(package)
    console.print(_kv_table("依赖", rows))

    info: dict[str, str] = {}
    try:
        cfg = load_config(Paths.build())
        info["配置文件"] = ", ".join(cfg.sources) or "（仅默认值）"
        info["启用档位"] = ", ".join(cfg.enabled_tiers()) or "（无）"
        info["通知流地址"] = cfg.targets.notice_url or "✗ 未配置（档 A 无法工作）"
    except Exception as exc:
        info["配置"] = f"✗ 加载失败：{exc}"
        cfg = None
    console.print(_kv_table("配置", info))

    paths = Paths.build()
    db_info: dict[str, str] = {"数据库文件": str(paths.db_path)}
    if paths.db_path.exists():
        try:
            from .db.migrate import pending_versions

            with _ctx() as ctx:
                pending = pending_versions(ctx.db)
                db_info["迁移"] = "✓ 已是最新" if not pending else f"✗ 待应用 {pending}"
                db_info["表数量"] = str(ctx.db.scalar(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table'", default=0))
                db_info["原始归档"] = f"{ctx.archive.stats()['count']} 条"
        except Exception as exc:
            db_info["迁移"] = f"✗ {exc}"
    else:
        db_info["迁移"] = "✗ 数据库不存在，请先运行 scout init"
    console.print(_kv_table("数据", db_info))

    if cfg is not None:
        locks: dict[str, str] = {}
        from .session.lock import ProfileLock

        for name, tier in sorted(cfg.tiers.items()):
            if tier.mode != "logged_in":
                continue
            status = ProfileLock.status(tier.resolved_profile_dir(paths))
            locks[f"档 {name}"] = (
                f"⚠ 被占用 pid={status.get('holder', {}).get('pid')}"
                if status["locked"] else "✓ 空闲"
            )
        if locks:
            console.print(_kv_table("登录态 profile 锁", locks))

    if missing:
        console.print(Panel.fit(
            "缺少：" + "、".join(missing) + "\n\n"
            "在项目根目录执行：\n"
            "    pwsh -File scripts/setup.ps1\n\n"
            "若本机无外网，可指定国内镜像：\n"
            "    .\\.venv\\Scripts\\python.exe -m pip install -e . "
            "-i https://pypi.tuna.tsinghua.edu.cn/simple",
            title="[yellow]依赖不完整[/]",
        ))
    else:
        console.print("[green]依赖齐全。[/]")


@app.command("config")
def config_show() -> None:
    """显示生效配置（含来源优先级）。"""
    with _ctx() as ctx:
        console.print_json(json.dumps(ctx.snapshot(), ensure_ascii=False, default=str))


# ── 可见性勘探（M1）──────────────────────────────────────────


@app.command()
def probe(
    url: str = typer.Option("", "--url", "-u", help="要勘探的页面地址；留空则用 targets.notice_url（你的个人主页）"),
    tier: str = typer.Option("b", "--tier", "-t", help="用哪个档位（a=登录态，b=匿名）"),
    scroll: int = typer.Option(5, "--scroll", "-s", help="滚动轮数"),
    settle: float = typer.Option(2.0, "--settle", help="打开后等待秒数"),
    save_endpoint: str = typer.Option("", "--save-endpoint", help="把该 URL 写入 local.yaml 的 targets 键名"),
    actions: str = typer.Option("", "--actions", "-a", help="试跑 config.interactions 里的交互脚本名"),
    dump: bool = typer.Option(False, "--dump", "-d", help="导出页面可见文本清单和 DOM 快照（定位选择器用）"),
) -> None:
    """勘探一个页面：归档它发出的所有响应，产出报告。

    这是写采集逻辑之前必须做的一步——不要猜接口，看真实响应。
    不传 --url 时默认勘探 targets.notice_url（你的个人主页上的互动消息入口）。
    """
    from .lab.probe import ProbeReport, Prober, save_endpoint as write_endpoint

    target_url = url

    async def _do() -> ProbeReport:
        ctx = _ctx()
        try:
            resolved = target_url or ctx.config.targets.notice_url
            if not resolved:
                raise ValueError(
                    "没有可勘探的地址：--url 留空且 targets.notice_url 也没配。"
                )
            report = await Prober(ctx).run(
                resolved, tier=tier, scroll_rounds=scroll, settle_s=settle,
                actions=actions, dump=dump,
            )
        finally:
            if ctx.session is not None:
                await ctx.session.stop()
            ctx.close()
        return report

    report = _run(_do())
    console.print(Panel.fit(
        f"捕获响应：[bold]{len(report.items)}[/]\n"
        f"疑似登录墙：[bold]{'是' if report.login_wall_suspected else '否'}[/]\n"
        f"解析出数据：[bold]{'是' if report.parse_ok else '否'}[/]\n"
        f"报告：{report.md_path}\n清单：{report.json_path}",
        title="勘探完成",
    ))

    if report.dump:
        console.print("\n[cyan]页面可见短文本（找按钮文案用）：[/]")
        for step in report.dump.get("detail", []):
            if step.get("action") == "dump_texts" and step.get("ok"):
                for chunk in str(step.get("detail", "")).split(" | "):
                    if chunk.strip():
                        console.print(f"  · {chunk.strip()}")
            elif step.get("action") == "dump_html":
                console.print(f"  [dim]DOM 快照：{step.get('detail')}[/]")

    if report.actions:
        console.print(_kv_table("交互动作", {
            "步数": report.actions.get("steps", 0),
            "成功": report.actions.get("ok", 0),
            "失败": report.actions.get("failed", 0),
            "中止": "是" if report.actions.get("aborted") else "否",
        }))
        for step in report.actions.get("detail", []):
            mark = "[green]✓[/]" if step.get("ok") else "[red]✗[/]"
            console.print(f"  {mark} {step.get('action')} — {truncate(step.get('detail') or '', 70)}")

    table = Table(show_header=True, header_style="bold")
    for col in ("#", "状态", "大小", "JSON", "解析", "URL"):
        table.add_column(col)
    for idx, item in enumerate(report.items[:30], 1):
        parsed = ""
        if item.parsed:
            parsed = f"U{item.parsed['users']}/W{item.parsed['works']}/L{item.parsed['like_edges']}"
        table.add_row(
            str(idx), str(item.status), str(item.byte_size),
            "✓" if item.is_json else "", parsed, truncate(item.url, 90),
        )
    console.print(table)
    _print_api_table(report)

    if save_endpoint:
        write_endpoint(Paths.build().local_config, save_endpoint, url)
        console.print(f"[green]已写入 local.yaml: targets.{save_endpoint} = {url}[/]")


def _print_api_table(report) -> None:
    """把勘探出来的数据接口按"有没有数据"排序打出来。"""
    rows = getattr(report, "api_summary", None) or []
    if not rows:
        console.print("\n[yellow]没有发现任何数据接口。[/]")
        console.print(
            "  最常见原因：面板/列表没打开。试试 `scout notice --dump` 看面板里的文案。\n"
            "  其次：抖音可能把数据 SSR 进了 HTML（那种情况看报告里的 text/html 一行）。"
        )
        return
    table = Table(title="发现的数据接口（有数据的排前面）", show_header=True, header_style="bold")
    for col in ("点赞人", "用户", "作品", "JSON", "请求数", "接口路径"):
        table.add_column(col)
    for row in rows[:20]:
        mark = "[green]★[/]" if (row["like_edges"] or row["users"]) else ""
        table.add_row(
            str(row["like_edges"]), str(row["users"]), str(row["works"]),
            str(row["json"]), str(row["count"]), f"{mark} {truncate(row['path'], 70)}",
        )
    console.print(table)


@app.command()
def notice(
    tier: str = typer.Option("a", "--tier", "-t", help="档位，互动消息必须用 a"),
    scroll: int = typer.Option(3, "--scroll", "-s", help="滚动轮数"),
    expand: bool = typer.Option(True, "--expand/--no-expand", help="是否试跑一次展开动作"),
    dump: bool = typer.Option(False, "--dump", "-d", help="导出页面可见文本和 DOM 快照"),
    manual: bool = typer.Option(False, "--manual", "-m", help="人工介入模式：你手动操作，程序只负责记录"),
    seconds: int = typer.Option(
        25, "--seconds", "-n",
        help="人工介入模式给多少秒操作时间（到点自动进入下一步，不用按回车）",
    ),
    harvest: bool = typer.Option(
        True, "--harvest/--no-harvest",
        help="结束后从 DOM 抽出「赞过的人」名单并入库",
    ),
    url: str = typer.Option("", "--url", "-u", help="留空则用 targets.notice_url"),
) -> None:
    """打开「互动消息」面板并勘探 —— 一条命令看清点赞人列表从哪个接口来。

    自动模式会尝试悬停/点击打开面板（元素名会变，可能失败）。
    **失败就用 --manual**：浏览器打开后你自己操作，程序照常记录所有请求。

    实测三点，都写进代码了：
      1. 「互动消息」面板是**活页** —— 鼠标悬停才存在，移开就关闭。
         所以自动流程里不做鼠标微动，且打开方式以悬停为主。
      2. 点「消息」打开的是私信页，互动消息在「通知」下面。
      3. 完整名单不在 notice 接口里（那里只给 7 个预览），要点条目右侧的
         › 箭头才展开 —— 它是图标，没有文字，只能按几何位置找。

    人工模式**不用按回车**：给一段倒计时，到点自动继续。
    因为活页根本没法"留着面板再走回终端"。
    """
    from .lab.probe import ProbeReport, Prober

    target_url = url
    use_countdown = manual and seconds > 0
    manual_prompt = (
        f"浏览器已打开你自己的主页。请在接下来的 {seconds} 秒内完成：\n"
        "\n"
        "  ① 鼠标移到右上角，把「互动消息」面板悬停出来\n"
        "     （能看到「XX 赞了你的作品」的那个面板）\n"
        "  ② 移到「JJ 等22人赞了你的作品」右边那个 › 箭头，把完整名单打开\n"
        "  ③ 名单出来后滚到底\n"
        "\n"
        "⚠️ 面板是活页，鼠标移开就消失 —— 所以不用回终端按回车，\n"
        f"   倒计时结束程序自动接管。期间每 5 秒会自动截一张图留证。"
    ) if use_countdown else (
        "浏览器已打开你自己的主页。请手动操作，完成后回终端按回车。"
    )

    async def _do() -> ProbeReport:
        ctx = _ctx()
        try:
            resolved = target_url or ctx.config.targets.notice_url
            return await Prober(ctx).run(
                resolved,
                tier=tier,
                scroll_rounds=scroll,
                settle_s=2.5,
                actions="" if manual else ("notice_click" if expand else ""),
                dump=dump,
                notice_flow=not manual,
                manual_prompt=manual_prompt if manual else "",
                manual_seconds=seconds if use_countdown else 0,
                harvest=harvest,
            )
        finally:
            if ctx.session is not None:
                await ctx.session.stop()
            ctx.close()

    report = _run(_do())
    console.print(Panel.fit(
        f"捕获数据接口：[bold]{len(report.items)}[/]"
        + (f"（跳过 {report.static_skipped} 个静态资源）" if report.static_skipped else "")
        + f"\n解析出数据：[bold]{'是' if report.parse_ok else '否'}[/]"
        + f"\nDOM 抽出名单：[bold]{len(report.harvested)}[/] 人"
        + f"\n报告：{report.md_path}",
        title="互动消息勘探完成",
    ))

    # 把 DOM 里抽到的名单落库 —— 这部分接口里根本没有
    if harvest and report.harvested:
        with _ctx() as ctx:
            works = report.harvest_works or []
            edges = []
            for link in report.harvested:
                sec_uid = link.get("sec_uid")
                if not sec_uid:
                    continue
                name = (link.get("nickname") or "").strip()
                if name and name != "<null>":
                    ctx.users.upsert({"sec_uid": sec_uid, "nickname": name})
                ctx.users.ensure(sec_uid, discovered_from="notice_overlay")
                for aweme_id in works:
                    edges.append({
                        "sec_uid": sec_uid,
                        "aweme_id": aweme_id,
                        "notice_id": f"overlay:{aweme_id}",
                        "notice_kind": "digg",
                        "source_url": "dom:overlay",
                    })
            added = ctx.like_edges.add_many(edges, tier="a") if edges else 0
            dist = ctx.like_edges.stats()
        console.print(_kv_table("已入库", {
            "用户": len(report.harvested),
            "点赞边新增": added,
            "归属作品": ", ".join(works) if works else "（未能归属，只入库用户）",
            "库中点赞人总数": dist["distinct_users"],
        }))
        if not works:
            console.print(
                "[yellow]没能自动归属到作品（有多个作品的名单都不完整）。"
                "人已入库，作品关联需要人工确认。[/]"
            )

    if report.actions:
        console.print("\n[cyan]动作执行：[/]")
        for step in report.actions.get("detail", []):
            mark = "[green]✓[/]" if step.get("ok") else "[red]✗[/]"
            console.print(f"  {mark} {step.get('action')} — {truncate(step.get('detail') or '', 66)}")

    if report.dump:
        console.print("\n[cyan]面板里的可见文本：[/]")
        for step in report.dump.get("detail", []):
            if step.get("action") == "dump_texts" and step.get("ok"):
                for chunk in str(step.get("detail", "")).split(" | "):
                    if chunk.strip():
                        console.print(f"  · {chunk.strip()}")
            elif step.get("action") == "dump_network" and step.get("ok"):
                console.print("\n[cyan]页面请求过的所有 URL（只在报告里全列，终端只显示带关键词的）：[/]")
                for chunk in str(step.get("detail", "")).split(" | "):
                    if any(k in chunk for k in ("notice", "digg", "like", "favor", "user")):
                        console.print(f"  · {chunk.strip()[:120]}")
            elif step.get("action") == "dump_html":
                console.print(f"  [dim]DOM 快照：{step.get('detail')}[/]")

    _print_api_table(report)


@app.command()
def discover(
    tier: str = typer.Option("a", "--tier", "-t", help="用哪个档位勘探（通知流必须用 a）"),
    scroll: int = typer.Option(4, "--scroll", "-s", help="每个候选址滚几轮"),
    url: list[str] = typer.Option(None, "--url", "-u", help="自定义候选址，可重复；不给则用配置里的候选"),
    save: bool = typer.Option(True, "--save/--no-save", help="找到最佳候选后写入 local.yaml"),
    actions: str = typer.Option("", "--actions", "-a", help="试跑 config.interactions 里的交互脚本名"),
    dump: bool = typer.Option(False, "--dump", "-d", help="顺带导出页面文本清单和 DOM 快照"),
) -> None:
    """依次勘探多个候选地址，找出「消息-赞」真正的地址。

    前提假设是网页端能看到完整点赞人名单；这个命令负责把它**验证出来**：
    哪个地址真的返回了点赞人数据，哪个只是空壳页面。
    """
    from .lab.probe import Prober, save_endpoint as write_endpoint

    if url:
        candidates = list(url)
    else:
        candidates = list(load_config(Paths.build()).targets.notice_url_candidates)
    if not candidates:
        console.print("[red]没有候选地址。用 --url 指定，或在 local.yaml 的 targets.notice_url_candidates 里配置。[/]")
        raise typer.Exit(code=1)

    console.print(f"将勘探 {len(candidates)} 个候选地址（档位 {tier}）：")
    for c in candidates:
        console.print(f"  - {c}")

    async def _do():
        ctx = _ctx()
        results = []
        try:
            prober = Prober(ctx)
            for cand in candidates:
                console.print(f"\n[cyan]>>> {cand}[/]")
                try:
                    report = await prober.run(
                        cand, tier=tier, scroll_rounds=scroll, settle_s=2.0,
                        actions=actions, dump=dump,
                    )
                except Exception as exc:
                    console.print(f"[red]    勘探失败：{exc}[/]")
                    results.append({"url": cand, "ok": False, "error": str(exc)})
                    continue
                likers = sum((i.parsed or {}).get("like_edges", 0) for i in report.items)
                users = sum((i.parsed or {}).get("users", 0) for i in report.items)
                results.append({
                    "url": cand, "ok": True, "captured": len(report.items),
                    "like_edges": likers, "users": users,
                    "login_wall": report.login_wall_suspected,
                    "final_url": report.final_url, "md": report.md_path,
                })
                console.print(
                    f"    捕获 {len(report.items)} 个响应｜点赞人 {likers}｜用户 {users}"
                    f"｜登录墙 {'是' if report.login_wall_suspected else '否'}"
                )
        finally:
            if ctx.session is not None:
                await ctx.session.stop()
            ctx.close()
        return results

    results = _run(_do())

    table = Table(title="候选地址对比", show_header=True, header_style="bold")
    for col in ("成绩", "点赞人", "用户", "响应数", "登录墙", "地址"):
        table.add_column(col)
    best = None
    for r in results:
        if not r.get("ok"):
            table.add_row("✗", "-", "-", "-", "-", f"{r['url']}（{r.get('error', '')[:30]}）")
            continue
        score = r["like_edges"] * 100 + r["users"]
        if best is None or score > best[1]:
            best = (r["url"], score)
        table.add_row(
            "★" if r["like_edges"] > 0 else ("○" if r["users"] > 0 else "✗"),
            str(r["like_edges"]), str(r["users"]), str(r["captured"]),
            "是" if r["login_wall"] else "否", truncate(r["url"], 60),
        )
    console.print(table)

    if best and best[1] > 0:
        console.print(f"\n[green]最佳候选：{best[0]}[/]")
        if save:
            write_endpoint(Paths.build().local_config, "notice_url", best[0])
            console.print("[green]已写入 local.yaml: targets.notice_url[/]")
    else:
        console.print(
            "\n[yellow]没有任何候选返回点赞人数据。[/]\n"
            "可能情况：\n"
            "  1. 档 A 没登录成功 → 先跑 `scout login --tier a`\n"
            "  2. 网页端确实没有这个入口 → 方案需要改成 App 端，停下来重新评估\n"
            "  3. 地址在别处 → 手动打开「消息-赞」，把地址栏里的 URL 用 --url 传进来"
        )


@app.command()
def coverage() -> None:
    """看点赞人名单的完整性证据：有没有触底、共覆盖多少不同的人。"""
    with _ctx() as ctx:
        data = ctx.notice_runs.coverage()
        runs = ctx.notice_runs.recent(limit=10)

    console.print(Panel.fit(
        f"结论：[bold]{data['verdict']}[/]\n"
        f"不同点赞人：{data['distinct_likers']}｜点赞边：{data['like_edges']}\n"
        f"采集轮次：{data['runs_total']}（其中触底 {data['runs_reached_end']}）",
        title="名单完整性",
    ))

    last = data.get("last_run")
    if last:
        console.print(_kv_table("最近一次采集", {
            "时间": last["started_at"],
            "轮数": last["rounds"],
            "看到": f"{last['edges_seen']} 条",
            "新增": f"{last['new_edges']} 条",
            "不同点赞人": last["distinct_likers"],
            "触底": "是" if last["reached_end"] else "否",
            "停止原因": last["stop_reason"],
        }))

    if runs:
        table = Table(title="历史采集", show_header=True, header_style="bold")
        for col in ("时间", "档", "轮数", "看到", "新增", "人数", "触底", "停止原因"):
            table.add_column(col)
        for r in runs:
            table.add_row(
                truncate(r["started_at"], 19), r["tier"], str(r["rounds"]),
                str(r["edges_seen"]), str(r["new_edges"]), str(r["distinct_likers"]),
                "✓" if r["reached_end"] else "✗", truncate(r["stop_reason"], 26),
            )
        console.print(table)


# ── 登录 ─────────────────────────────────────────────────────


@app.command()
def login(
    tier: str = typer.Option("a", "--tier", "-t", help="要登录哪个档位（默认 a，小号）"),
    url: str = typer.Option("", "--url", help="登录页地址，默认抖音首页"),
) -> None:
    """打开浏览器手动扫码登录，登录态落到该档位的持久化 profile。

    只用小号。登录完成后回到这个终端按回车。
    """
    console.print(f"[yellow]将在档位 [bold]{tier}[/] 打开浏览器。请用**小号**扫码登录。[/]")
    console.print("[dim]登录完成后回到本终端按回车。[/]")

    async def _flow() -> str:
        ctx = _ctx()
        session = await ctx.open_session(headless_override=False)
        # 登录必须走持久 profile：否则会去读那个"正要被更新"的 state 文件，
        # 登录态一过期就成了死循环（要登录 → 读旧 state → 失败 → 要登录）
        session.force_persistent_profile(tier)
        try:
            target = url or ctx.config.targets.home_url
            await session.goto(tier, target, settle_s=2.0)
            await asyncio.to_thread(input, "登录完成后按回车继续：")
            return str(await session.export_state(tier, ctx.paths.state_dir / f"tier_{tier}_storage.json"))
        finally:
            await session.stop()
            ctx.close()

    path = _run(_flow())
    console.print(f"[green]登录态已导出：{path}[/]")
    console.print("profile 目录已持久化，后续不需要重复登录（除非掉线）。")


# ── 采集 ─────────────────────────────────────────────────────


@app.command()
def seed() -> None:
    """根据现有数据补齐待办任务（通知流 / 待采资料）。"""
    from .schedule import Engine

    with _ctx() as ctx:
        counts = Engine(ctx).seed()
        console.print(_kv_table("已入队", counts))
        console.print(f"当前任务：{ctx.tasks.stats()}")


@app.command()
def run(
    max_tasks: int = typer.Option(0, "--max-tasks", "-n", help="本轮最多几个任务，0=用配置值"),
    tier: str = typer.Option("", "--tier", "-t", help="只跑某个档位"),
    kind: str = typer.Option("", "--kind", "-k", help="只跑某类任务，可重复：kind=a --kind=b"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只走流程不发请求"),
    skip_account_check: bool = typer.Option(
        False, "--skip-account-check",
        help="跳过「数据目录 vs 登录账号」核对（只在明确知道后果时用）",
    ),
) -> None:
    """跑一轮采集。到配额或到达上限就停——这是设计，不是失败。"""
    from .schedule import Engine

    # ── 开跑前对账：这套数据目录，和当前登录的号，是不是同一个 ──
    # 目录隔离挡不住"目录是 A 号的、登录的是 B 号"这种情况 ——
    # 那样所有采集都会写进 A 号的库，且无声无息、事后不可逆。
    # 所以宁可每次多花一次请求，也要在一开始就拦下来。
    if not dry_run and not skip_account_check:
        _verify_account_or_die()

    async def _do():
        ctx = _ctx()
        try:
            engine = Engine(ctx)
            engine.seed()
            return await engine.run_round(
                max_tasks=max_tasks or None,
                tiers=[tier] if tier else None,
                kinds=[k.strip() for k in kind.split(",") if k.strip()] if kind else None,
                dry_run=dry_run,
            )
        finally:
            if ctx.session is not None:
                await ctx.session.stop()
            ctx.close()

    report = _run(_do())
    console.print(Panel.fit(
        f"尝试 {report.attempted}｜成功 {report.ok}｜空返回 {report.empty}"
        f"｜失败 {report.failed}｜被拦 {report.blocked}\n停止原因：{report.stop_reason or '（任务跑完）'}",
        title="本轮结果",
    ))
    if report.runs:
        table = Table(show_header=True, header_style="bold")
        for col in ("任务", "目标", "结果", "捕获", "解析", "用时ms"):
            table.add_column(col)
        for item in report.runs[:30]:
            parsed = item.get("parsed") or {}
            mark = "✓" if item.get("ok") else ("空" if item.get("empty") else "✗")
            table.add_row(
                str(item.get("kind")), truncate(str(item.get("target")), 30), mark,
                str(item.get("captured", "")),
                f"U{parsed.get('users', 0)}/W{parsed.get('works', 0)}/L{parsed.get('like_edges', 0)}",
                str(item.get("duration_ms", "")),
            )
        console.print(table)


# ── 查询 ─────────────────────────────────────────────────────


@app.command()
def status(json_out: bool = typer.Option(False, "--json", help="输出原始 JSON")) -> None:
    """一屏看全：数据量、配额、熔断、任务。"""
    with _ctx() as ctx:
        data = overview(ctx)
    if json_out:
        console.print_json(json.dumps(data, ensure_ascii=False, default=str))
        return

    console.print(_kv_table("用户", data["users"]))
    console.print(_kv_table("作品", data["works"]))
    console.print(_kv_table("点赞边", data["like_edges"]))
    console.print(_kv_table("原始归档", data["raw"]))
    console.print(_kv_table("请求（24h）", data["requests"]))
    console.print(_kv_table("任务", data["tasks"]))

    quota = Table(title="今日动作数", show_header=True, header_style="bold")
    for col in ("档位", "已做", "上限", "剩余"):
        quota.add_column(col)
    for name, info in data["quota"].items():
        if info.get("unlimited"):
            quota.add_row(name, str(info["used"]), "[dim]不限[/]", "[dim]—[/]")
        else:
            quota.add_row(name, str(info["used"]), str(info["limit"]), str(info["remaining"]))
    console.print(quota)
    console.print("[dim]“动作”= 一次页面导航或一次点击。默认不设上限，只计数。[/]")

    if data["circuit"]:
        circ = Table(title="熔断状态", show_header=True, header_style="bold")
        for col in ("键", "状态", "原因", "冷却至"):
            circ.add_column(col)
        for row in data["circuit"]:
            circ.add_row(row["key"], row["state"], truncate(row.get("reason") or "", 40),
                         str(row.get("cooldown_until") or "-"))
        console.print(circ)


@app.command()
def users(
    limit: int = typer.Option(30, "--limit", "-n"),
    order: str = typer.Option("like_count", "--order", help="like_count|fans|recent|nickname"),
    state: str = typer.Option("", "--state", help="pending|ok|blocked|error"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """列出已采到的用户。"""
    with _ctx() as ctx:
        rows = ctx.users.list(limit=limit, order=order, state=state or None)
    if json_out:
        console.print_json(json.dumps(rows, ensure_ascii=False, default=str))
        return
    table = Table(show_header=True, header_style="bold")
    for col in ("昵称", "抖音号", "粉丝", "关注", "点赞次数", "状态", "sec_uid"):
        table.add_column(col)
    for row in rows:
        table.add_row(
            truncate(row.get("nickname") or "-", 20), row.get("douyin_id") or "-",
            str(row.get("follower_count") if row.get("follower_count") is not None else "-"),
            str(row.get("following_count") if row.get("following_count") is not None else "-"),
            str(row.get("like_count", 0)), row.get("profile_state") or "-",
            truncate(row.get("sec_uid") or "", 24),
        )
    console.print(table)


@app.command()
def tasks(
    limit: int = typer.Option(30, "--limit", "-n"),
    state: str = typer.Option("", "--state"),
) -> None:
    """查看任务队列。"""
    with _ctx() as ctx:
        rows = ctx.tasks.list(limit=limit, state=state or None)
    table = Table(show_header=True, header_style="bold")
    for col in ("id", "kind", "target", "tier", "state", "尝试", "可用时间", "最后错误"):
        table.add_column(col)
    for row in rows:
        table.add_row(
            str(row["id"]), row["kind"], truncate(row["target"], 24), row["tier"],
            row["state"], f"{row['attempts']}/{row['max_attempts']}",
            truncate(row["available_at"], 19), truncate(row.get("last_error") or "", 30),
        )
    console.print(table)


@app.command()
def raw(
    limit: int = typer.Option(20, "--limit", "-n"),
    show: int = typer.Option(0, "--show", help="显示某个 raw_id 的内容（前 4000 字符）"),
) -> None:
    """查看原始归档。这是项目最重要的资产。"""
    with _ctx() as ctx:
        if show:
            row = ctx.archive.get(show)
            if not row:
                console.print(f"[red]raw_id {show} 不存在[/]")
                raise typer.Exit(code=1)
            console.print_json(json.dumps(row, ensure_ascii=False, default=str))
            text = ctx.archive.load_text(show)
            console.print(text[:4000])
            return
        rows = ctx.archive.recent(limit)
    table = Table(show_header=True, header_style="bold")
    for col in ("id", "时间", "来源", "档位", "类型", "字节", "URL"):
        table.add_column(col)
    for row in rows:
        table.add_row(
            str(row["id"]), truncate(row["collected_at"], 19), row["source"], row["tier"],
            truncate(row["content_type"], 20), str(row["byte_size"]), truncate(row["url"], 60),
        )
    console.print(table)


@app.command()
def replay(
    raw_id: int = typer.Argument(None, help="raw_blobs.id；用 --all 时可以不填"),
    all_: bool = typer.Option(False, "--all", help="回放所有匹配 --match 的归档"),
    match: str = typer.Option("", "--match", help="URL 子串过滤（配合 --all）"),
    limit: int = typer.Option(300, "--limit", help="--all 时最多处理多少条"),
    persist: bool = typer.Option(False, "--persist", help="解析成功后写入数据库"),
) -> None:
    """对归档的原始响应重新解析，不需要重新采集。

    抖音改版后这是主力工具：改解析器 → replay → 数据自动回填。

    批量回填：
        scout replay --all --match "/aweme/v1/web/notice/" --persist
    """
    from .parse import parse_payload

    with _ctx() as ctx:
        if all_:
            if not match:
                console.print("[red]--all 需要配合 --match 指定 URL 子串，避免误操作全库。[/]")
                raise typer.Exit(code=1)
            rows = ctx.db.query(
                "SELECT id, url FROM raw_blobs WHERE url LIKE ? ORDER BY id LIMIT ?",
                (f"%{match}%", limit),
            )
            if not rows:
                console.print(f"[yellow]没有匹配 {match!r} 的归档。[/]")
                return
            console.print(f"将回放 {len(rows)} 条归档（URL 含 {match!r}）")
            totals = {"users": 0, "works": 0, "edges": 0, "skipped": 0, "failed": 0}
            for row in rows:
                try:
                    payload = json.loads(ctx.archive.load_text(int(row["id"])))
                except Exception:
                    totals["skipped"] += 1
                    continue
                result = parse_payload(row["url"], payload, raw_blob_id=int(row["id"]))
                if result.is_empty():
                    totals["skipped"] += 1
                    continue
                totals["users"] += _persist_parsed(ctx, result, int(row["id"]))
                totals["works"] += len(result.works)
                totals["edges"] += len(result.like_edges)
                _persist_side_tables(ctx, result, int(row["id"]))
            console.print(_kv_table("批量回放结果", {
                "归档数": len(rows),
                "用户": totals["users"],
                "作品": totals["works"],
                "点赞边": totals["edges"],
                "跳过（无数据）": totals["skipped"],
            }))
            return

        if raw_id is None:
            console.print("[red]请给一个 raw_id，或用 --all --match <子串>。[/]")
            raise typer.Exit(code=1)

        row = ctx.archive.get(raw_id)
        if row is None:
            console.print(f"[red]raw_id {raw_id} 不存在[/]")
            raise typer.Exit(code=1)
        text = ctx.archive.load_text(raw_id)
        payload = json.loads(text)
        result = parse_payload(row["url"], payload, raw_blob_id=raw_id)
        console.print_json(json.dumps(result.summary(), ensure_ascii=False, default=str))

        if persist and not result.is_empty():
            n = _persist_parsed(ctx, result, raw_id) + len(result.works)
            n += len(result.like_edges)
            _persist_side_tables(ctx, result, raw_id)
            console.print(f"[green]已写入 {n} 条记录[/]")


def _persist_parsed(ctx, result, raw_id: int) -> int:
    """把解析结果写进主表。CLI 与批量回放共用。"""
    n = 0
    for user in result.users:
        if user.get("sec_uid"):
            ctx.users.upsert(user, raw_blob_id=raw_id)
            n += 1
    for work in result.works:
        if work.get("aweme_id"):
            ctx.works.upsert(work, raw_blob_id=raw_id)
    return n


def _persist_side_tables(ctx, result, raw_id: int) -> None:
    """点赞边这种关联表。"""
    if result.like_edges:
        ctx.like_edges.add_many(result.like_edges, tier="a", raw_blob_id=raw_id)


# ── 分析 ─────────────────────────────────────────────────────


@app.command()
def report(
    out: str = typer.Option("", "--out", help="markdown 输出路径，默认写到 exports/"),
) -> None:
    """生成用户画像报告。"""
    with _ctx() as ctx:
        data = analyze_users(ctx)
        text = render_markdown(data)
        target = Path(out) if out else (ctx.paths.export_dir / "user-report.md")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    console.print(text[:6000])
    console.print(f"\n[green]报告已写入 {target}[/]")


@app.command()
def export(
    table: str = typer.Option("users", "--table", help="users|works|like_edges"),
    out: str = typer.Option("", "--out", help="csv 路径"),
) -> None:
    """导出 CSV（utf-8-sig，Excel 直接打开不乱码）。"""
    with _ctx() as ctx:
        target = Path(out) if out else (ctx.paths.export_dir / f"{table}.csv")
        path = export_csv(ctx, target, table=table)
    console.print(f"[green]已导出 {path}[/]")


# ── 运维 ─────────────────────────────────────────────────────


circuit_app = typer.Typer(help="熔断器操作", no_args_is_help=True)
app.add_typer(circuit_app, name="circuit")


@circuit_app.command("status")
def circuit_status() -> None:
    """查看所有熔断器状态。"""
    with _ctx() as ctx:
        rows = ctx.circuit.snapshot()
    table = Table(show_header=True, header_style="bold")
    for col in ("键", "状态", "连续空", "连续错", "熔断次数", "原因", "冷却至"):
        table.add_column(col)
    for row in rows:
        table.add_row(
            row["key"], row["state"], str(row["consecutive_empty"]), str(row["consecutive_error"]),
            str(row["open_count"]), truncate(row.get("reason") or "", 36), str(row.get("cooldown_until") or "-"),
        )
    console.print(table)


@circuit_app.command("reset")
def circuit_reset(tier: str = typer.Argument("b", help="要重置的档位")) -> None:
    """人工解除熔断，重新放行。"""
    with _ctx() as ctx:
        ctx.circuit.reset(tier)
    console.print(f"[green]{tier} 已重置为 closed[/]")


@circuit_app.command("open")
def circuit_open(tier: str = typer.Argument("b"), reason: str = typer.Option("人工熔断", "--reason")) -> None:
    """手动熔断某个档位（比如你发现数据不对想先停下来）。"""
    with _ctx() as ctx:
        ctx.circuit.force_open(tier, reason)
    console.print(f"[yellow]{tier} 已熔断：{reason}[/]")


@app.command("cleanup")
def cmd_cleanup(
    dry_run: bool = typer.Option(
        True, "--dry-run/--apply",
        help="默认只预览不动手。确认要执行加 --apply",
    ),
    raw_days: int = typer.Option(-1, "--raw-days", help="归档正文保留天数，覆盖配置"),
    log_days: int = typer.Option(-1, "--log-days", help="日志保留天数，覆盖配置"),
    task_days: int = typer.Option(-1, "--task-days", help="已完成任务保留天数，覆盖配置"),
    edge_days: int = typer.Option(-1, "--edge-days", help="点赞边陈旧阈值，覆盖配置"),
    force: bool = typer.Option(False, "--yes", "-y", help="跳过确认"),
) -> None:
    """按保留策略清理：归档正文、日志、陈旧标记、已完成任务。

    三条取舍（都是宁可保守）：

    - **删正文，保留元数据** —— raw_blobs 行只占几字节，
      留下 sha256/url/byte_size，"曾经采过什么"仍可追溯
    - **陈旧的点赞边只标记，不删除** —— 可能是接口偶发，删了找不回来
    - **默认 dry-run** —— 破坏性操作必须先能预览
    """
    from .store.cleanup import archive_stats, plan_cleanup, run_cleanup

    with _ctx() as ctx:
        cur = archive_stats(ctx)
        console.print(_kv_table("归档现状", {
            "归档记录": f"{cur['rows']} 条（其中已清正文 {cur['pruned_rows']} 条）",
            "正文占用": f"{cur['disk_mb']} MB / {cur['disk_files']} 个文件",
            "保留策略": f"{cur['retention_days']} 天",
            "最早归档": (cur["oldest"] or "—")[:19],
        }))

        overrides = {
            k: v for k, v in (
                ("raw_days", raw_days), ("log_days", log_days),
                ("task_days", task_days), ("edge_days", edge_days),
            ) if v >= 0
        }
        plan = plan_cleanup(ctx, **overrides)

        console.print(_kv_table("本次将处理（按优先级）", {
            "① 归档正文": (
                f"删 {plan.raw_files} 个文件，释放 {plan.raw_bytes/1048576:.2f} MB"
                f"（涉及 {len(plan.raw_dirs)} 个日期目录，元数据保留）"
            ),
            "② 日志": ", ".join(f"{k} {v} 行" for k, v in plan.log_rows.items()) or "无",
            "③ 点赞边": (
                f"标记陈旧 {plan.unconfirmed_edges} 条（不删除）"
                f"（已有陈旧 {plan.stale_edges} 条）"
            ),
            "④ 已完成任务": f"删 {plan.task_rows} 行",
        }))

        if not (plan.raw_rows or plan.log_rows or plan.unconfirmed_edges or plan.task_rows):
            console.print("[green]没有需要清理的内容[/]")
            return

        if dry_run:
            console.print("\n[yellow]这是预览，什么都没动。确认要执行就加 --apply[/]")
            return

        if not force and not typer.confirm("确认执行清理？归档正文删了就回不来（元数据保留）"):
            raise typer.Exit(code=1)

        result = run_cleanup(ctx, plan, dry_run=False)
        console.print(_kv_table("清理结果", {
            "删除文件": f"{result['files_deleted']} 个",
            "释放空间": f"{result['bytes_freed']/1048576:.2f} MB",
            "标记已清正文": f"{result['raw_marked']} 条",
            "删除日志": ", ".join(f"{k} {v}" for k, v in result["logs_deleted"].items()) or "无",
            "标记陈旧点赞边": f"{result['edges_marked']} 条",
            "删除已完成任务": f"{result['tasks_deleted']} 行",
        }))
        for e in result["errors"][:5]:
            console.print(f"[red]  出错：{e}[/]")
        ctx.db.log_event("info", "cleanup", f"清理完成：释放 {result['bytes_freed']} 字节")


@app.command()
def cache(action: str = typer.Argument("stats", help="stats|purge")) -> None:
    """去重缓存操作。命中去重能省掉一大半请求量。"""
    with _ctx() as ctx:
        if action == "purge":
            n = ctx.cache.purge_expired()
            console.print(f"[green]清理了 {n} 条过期缓存[/]")
        else:
            stats = getattr(ctx.cache, "stats", lambda: {})()
            console.print(_kv_table("缓存", stats or {"entries": len(ctx.cache.keys())}))


@app.command()
def prune(
    dry_run: bool = typer.Option(False, "--dry-run", help="只统计不删除"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认"),
) -> None:
    """清理归档里的静态资源（JS/CSS/图片/字体）。

    早期版本会把页面上几百个 JS/CSS 也归档下来，既占磁盘又把真正的接口淹没。
    这个命令只删静态资源，**数据接口的归档一律不碰**。
    """
    with _ctx() as ctx:
        before = ctx.archive.static_stats()
        if before["blobs"] == 0:
            console.print("[green]没有需要清理的静态资源。[/]")
            return
        console.print(_kv_table("待清理", {
            "文件数": before["blobs"],
            "占用": f"{before['bytes'] / 1024 / 1024:.1f} MB",
        }))
        if not yes and not dry_run:
            typer.confirm("确认删除这些静态资源归档？", abort=True)
        result = ctx.archive.prune_static(dry_run=dry_run)
    console.print(_kv_table("结果", {
        "模式": "预演" if result["dry_run"] else "已删除",
        "记录数": result["blobs"],
        "文件数": result["files_unlinked"],
        "释放空间": f"{result['bytes_freed'] / 1024 / 1024:.1f} MB",
    }))
    if dry_run:
        console.print("[dim]加 --yes 去掉 --dry-run 才会真正删除。[/]")


quota_app = typer.Typer(help="配额账本操作", no_args_is_help=True)
app.add_typer(quota_app, name="quota")

@quota_app.command("show")
def quota_show() -> None:
    """查看今日动作数。默认不设上限，这里只是让你知道今天跑了多少。"""
    with _ctx() as ctx:
        snap = ctx.quota.snapshot()
        rows = ctx.telemetry.quota_all()
    table = Table(title="今日动作数", show_header=True, header_style="bold")
    for col in ("档位", "已做", "上限", "剩余", "使用率"):
        table.add_column(col)
    for tier, info in snap.items():
        if info.get("unlimited"):
            table.add_row(tier, str(info["used"]), "[dim]不限[/]", "[dim]—[/]", "[dim]—[/]")
        else:
            ratio = f"{info['ratio']:.0%}" if info["ratio"] is not None else "-"
            table.add_row(tier, str(info["used"]), str(info["limit"]),
                          str(info["remaining"]), ratio)
    console.print(table)
    console.print(
        "[dim]“动作”= 一次页面导航或一次点击，不是页面的请求数。\n"
        "默认不设上限（daily_request_quota: 0）。要加总量闸门就改 config/local.yaml。[/]"
    )
    if rows:
        console.print(_kv_table("账本行", {f"{r['day']}/{r['tier']}": r["used"] for r in rows}))


@quota_app.command("reset")
def quota_reset(
    tier: str = typer.Option("", "--tier", "-t", help="只重置某个档位；不给则重置全部"),
    day: str = typer.Option("", "--day", "-d", help="指定日期 YYYY-MM-DD，默认今天"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认"),
) -> None:
    """清空配额账本。

    什么时候用：口径修正（比如旧版本把静态资源也算进了配额）、误操作烧掉额度。
    **这不是常规操作**，动之前先想清楚为什么。
    """
    if not yes:
        target = tier or "全部档位"
        typer.confirm(f"确认把 {day or '今天'} 的配额账本清零（{target}）？", abort=True)
    with _ctx() as ctx:
        n = ctx.telemetry.quota_reset(tier or None, day or None)
        ctx.db.log_event("warn", "quota", f"人工重置配额：tier={tier or 'ALL'} day={day or 'today'}")
        snap = ctx.quota.snapshot()
    console.print(f"[green]已清理 {n} 行配额账本[/]")
    console.print(_kv_table("重置后", {k: f"{v['used']}/{v['limit']}" for k, v in snap.items()}))


@quota_app.command("set")
def quota_set(
    tier: str = typer.Argument(..., help="档位名"),
    used: int = typer.Argument(..., help="把今日用量设成这个值"),
) -> None:
    """把某个档位今天的用量直接设成指定值（口径修正用）。"""
    with _ctx() as ctx:
        ctx.telemetry.quota_set(tier, used, limit=ctx.quota.limit(tier) or None)
        ctx.db.log_event("warn", "quota", f"人工设置配额：{tier}={used}")
        snap = ctx.quota.snapshot()
    console.print(f"[green]{tier} 今日用量已设为 {used}[/]")
    console.print(_kv_table("当前", {k: f"{v['used']}/{v['limit']}" for k, v in snap.items()}))


# ── 面板 ─────────────────────────────────────────────────────


@app.command()
def web(
    host: str = typer.Option("", "--host"),
    port: int = typer.Option(0, "--port"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """启动本地网页面板。"""
    try:
        import uvicorn
    except ImportError:
        console.print("[red]未安装 uvicorn/fastapi，请先运行 scripts/setup.ps1[/]")
        raise typer.Exit(code=1) from None

    with _ctx() as ctx:
        h = host or ctx.config.web.host
        p = port or ctx.config.web.port

    console.print(f"[green]面板地址： http://{h}:{p}[/]  （Ctrl+C 停止）")
    uvicorn.run("scout.web.app:create_app", factory=True, host=h, port=p, reload=reload, log_level="info")


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
