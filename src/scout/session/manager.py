"""浏览器会话管理。

一个 Playwright 实例，两个隔离的上下文：
    context_A  ← 持久化 profile，带登录态；只访问通知流
    context_B  ← 全新上下文，匿名；承载全部公开数据采集

刻意不做的事（见 docs/architecture.md 的说明）：
- 不实现 a_bogus / msToken 等签名，全部交给页面自身的 JS。
- 不伪造 navigator.webdriver、不改指纹、不用 stealth 插件。
  请求特征保持真实是这套方案的核心优势，伪造就把它抹掉了。
  如果确实需要更高真实性，用 browser.cdp_url 连接你自己启动的真实浏览器。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from ..config import BrowserConfig, Config, TierConfig
from ..paths import Paths
from ..util import iso
from .lock import ProfileLock
from .mirror import ResponseMirror


class SessionError(RuntimeError):
    pass


def _require_playwright():
    try:
        from playwright.async_api import async_playwright  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise SessionError(
            "未安装 playwright。请先运行 scripts/setup.ps1，或执行："
            "pip install playwright && playwright install chromium"
        ) from exc
    return async_playwright


@dataclass
class TierSession:
    name: str
    config: TierConfig
    context: Any
    mirror: ResponseMirror
    page: Any = None
    lock: ProfileLock | None = None
    started_at: str = field(default_factory=iso)
    requests_made: int = 0

    def describe(self) -> dict[str, Any]:
        return {
            "tier": self.name,
            "mode": self.config.mode,
            "headless": self.config.headless,
            "started_at": self.started_at,
            "has_page": self.page is not None,
            "requests_made": self.requests_made,
        }


class SessionManager:
    def __init__(self, config: Config, *, headless_override: bool | None = None):
        self.config = config
        self.paths: Paths = config.paths
        self.browser_cfg: BrowserConfig = config.browser
        self.headless_override = headless_override
        # 强制走持久 profile 的档位（见 force_persistent_profile）
        self._force_persistent: set[str] = set()
        self._pw_manager: Any = None
        self._playwright: Any = None
        self._browser: Any = None            # 匿名浏览器实例
        self._sessions: dict[str, TierSession] = {}
        self._started = False

    # ── 启动 / 关闭 ─────────────────────────────────────────

    async def start(self) -> "SessionManager":
        """只启动 Playwright 与浏览器本体。**各档位上下文按需惰性创建。**

        这样 `probe --tier b` 不会顺手打开档 A 的可见窗口、也不会无谓占用
        profile 锁——只有真正用到某个档位时它才会被创建。
        """
        if self._started:
            return self
        async_playwright = _require_playwright()
        self._pw_manager = async_playwright()
        self._playwright = await self._pw_manager.start()

        cdp_url = getattr(self.browser_cfg, "cdp_url", "") or ""
        if cdp_url:
            # 连接你自己启动的浏览器：不启动新进程、不伪造任何东西
            self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
        else:
            self._browser = await self._playwright.chromium.launch(
                headless=self._resolve_headless("b"),
                channel=self.browser_cfg.channel or None,
            )
        self._started = True
        return self

    async def ensure(self, name: str) -> TierSession:
        """取出档位上下文；不存在就现在创建。"""
        if name in self._sessions:
            return self._sessions[name]
        if not self._started:
            await self.start()
        tier = self.config.tier(name)
        if not tier.enabled:
            raise SessionError(f"档位 {name!r} 在配置里是关闭的（tiers.{name}.enabled = false）")
        await self._open_tier(name)
        return self._sessions[name]

    async def stop(self) -> None:
        # 用 storage_state 起来的会话，抖音会刷新部分 cookie。
        # 在关掉之前写回去 —— 否则每次跑都用旧的 cookie，
        # 直到某天突然"登录失效"，而其实早就拿到过新的。
        for session in list(self._sessions.values()):
            if session.config.use_storage_state:
                try:
                    await session.context.storage_state(path=str(self.state_file_for(session.name)))
                except Exception:
                    pass
        for session in list(self._sessions.values()):
            try:
                session.mirror.detach()
                if session.lock:
                    session.lock.release()
                if session.config.mode == "logged_in":
                    await session.context.close()
            except Exception:
                pass
        self._sessions.clear()
        try:
            if self._browser is not None:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._pw_manager is not None:
                await self._pw_manager.__aexit__(None, None, None)
        except Exception:
            pass
        self._started = False

    async def __aenter__(self) -> "SessionManager":
        return await self.start()

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    # ── 上下文构造 ──────────────────────────────────────────

    def _resolve_headless(self, tier: str) -> bool:
        if self.headless_override is not None:
            return self.headless_override
        try:
            return bool(self.config.tier(tier).headless)
        except KeyError:
            return True

    def _context_kwargs(self) -> dict[str, Any]:
        cfg = self.browser_cfg
        kwargs: dict[str, Any] = {
            "locale": cfg.locale,
            "timezone_id": cfg.timezone,
            "viewport": {"width": cfg.viewport_width, "height": cfg.viewport_height},
        }
        if cfg.user_agent:
            kwargs["user_agent"] = cfg.user_agent
        return kwargs

    def state_file_for(self, name: str) -> Path:
        """登录态导出文件的位置（每个档位一个）。"""
        return self.paths.state_dir / f"tier_{name}_storage.json"

    def force_persistent_profile(self, name: str) -> None:
        """让某个档位**强制**走持久 profile，忽略 use_storage_state。

        为什么需要：`scout login` 必须在持久 profile 里扫码。
        如果不排除，它会去读那个正要被更新的 state 文件 ——
        登录态过期时就成了死循环（要登录 → 读旧 state → 失败 → 要登录）。
        """
        self._force_persistent.add(name)

    async def _open_tier(self, name: str) -> None:
        tier = self.config.tier(name)
        mirror = ResponseMirror(
            capture_static_bodies=self.config.storage.archive_static,
            max_body_bytes=self.config.storage.raw_max_bytes,
        )
        lock: ProfileLock | None = None

        state_file = self.state_file_for(name)

        if (
            tier.mode == "logged_in"
            and tier.use_storage_state
            and name not in self._force_persistent
            and state_file.is_file()
        ):
            # ── 无头服务器路线：用导出的登录态起一次性上下文 ──
            #
            # 为什么不用 launch_persistent_context：
            #   1. 它**不接受 storage_state 参数**（Playwright 的 API 就是这样）
            #   2. 持久 profile 目录跨机器搬不动 —— 本机是 Edge on Windows，
            #      服务器是 Chromium on Linux，profile 格式不通用
            #
            # storage_state 只存 cookie + localStorage，跟浏览器和系统无关，
            # 是 Playwright 官方支持的跨机器迁移登录态的方式。
            #
            # 所以：本地扫码登录（有屏幕）→ 导出 state → 拷到服务器 → 这里注入。
            context = await self._browser.new_context(
                storage_state=str(state_file), **self._context_kwargs()
            )
        elif tier.mode == "logged_in":
            profile_dir = tier.resolved_profile_dir(self.paths)
            lock = ProfileLock(profile_dir).acquire()
            context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=self._resolve_headless(name),
                channel=self.browser_cfg.channel or None,
                **self._context_kwargs(),
            )
        else:
            context = await self._browser.new_context(**self._context_kwargs())

        await self._apply_resource_blocking(context)
        mirror.attach(context)
        self._sessions[name] = TierSession(
            name=name, config=tier, context=context, mirror=mirror, lock=lock
        )

    async def _apply_resource_blocking(self, context: Any) -> None:
        """拦掉图片/视频/字体/埋点：只影响渲染，不改变请求特征，纯收益。"""
        cfg = self.browser_cfg
        types = {t for t in cfg.block_resources if t}
        globs = tuple(cfg.block_url_globs)
        if not types and not globs:
            return

        import fnmatch

        async def handler(route: Any) -> None:
            request = route.request
            try:
                if request.resource_type in types:
                    await route.abort()
                    return
                url = request.url
                if globs and any(fnmatch.fnmatch(url, g) for g in globs):
                    await route.abort()
                    return
            except Exception:
                pass
            try:
                await route.continue_()
            except Exception:
                pass

        try:
            await context.route("**/*", handler)
        except Exception:
            pass

    # ── 取用 ────────────────────────────────────────────────

    def get(self, tier: str) -> TierSession:
        try:
            return self._sessions[tier]
        except KeyError:
            raise SessionError(
                f"档位 {tier!r} 还没启动。请先 await ensure({tier!r})。"
                f"已启动：{sorted(self._sessions)}"
            ) from None

    async def page(self, tier: str, *, fresh: bool = False) -> Any:
        session = await self.ensure(tier)
        if fresh or session.page is None or session.page.is_closed():
            session.page = await session.context.new_page()
        return session.page

    async def goto(
        self,
        tier: str,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
        timeout_ms: int = 45_000,
        settle_s: float = 1.0,
    ) -> Any:
        """打开一个页面并给 SPA 一点时间发起它自己的请求。"""
        import asyncio

        session = await self.ensure(tier)
        page = await self.page(tier)
        await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
        await asyncio.sleep(settle_s)
        session.requests_made += 1
        return page

    # ── 登录态存取 ──────────────────────────────────────────

    async def export_state(self, tier: str, path: str | Path) -> Path:
        session = await self.ensure(tier)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        await session.context.storage_state(path=str(target))
        return target

    async def import_state(self, tier: str, path: str | Path) -> bool:
        """把 cookies/localStorage 注入到匿名上下文——用于档 B 的可选提速。"""
        import json

        session = await self.ensure(tier)
        source = Path(path)
        if not source.is_file():
            return False
        state = json.loads(source.read_text(encoding="utf-8"))
        cookies = state.get("cookies") or []
        if cookies:
            await session.context.add_cookies(cookies)
        return True

    # ── 观测 ────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        return {
            "started": self._started,
            "cdp": bool(getattr(self.browser_cfg, "cdp_url", "")),
            "lazy": True,
            "opened": sorted(self._sessions),
            "enabled": self.config.enabled_tiers(),
            "sessions": [s.describe() for s in self._sessions.values()],
            "mirror": {k: v.mirror.stats() for k, v in self._sessions.items()},
        }

    def login_tier(self) -> str | None:
        for name, tier in sorted(self.config.tiers.items()):
            if tier.mode == "logged_in" and tier.enabled:
                return name
        return None
