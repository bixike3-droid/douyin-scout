"""网页扫码登录。

**要解决的问题**

原来登录只能在本地终端做：弹出浏览器 → 扫码 → 回终端按回车 → 导出 state → 传到服务器。
对比赛作品来说这不合格 —— 用户应该打开网页就能登录。

**怎么做的**

服务器上的**无头** Chromium 一样能渲染抖音登录页。所以：

    网页点「登录」→ 后端无头浏览器打开抖音 → 截图二维码 → 推给网页
    → 手机扫码 → 后端轮询检测登录成功 → 导出 storage_state → 写入账号目录

不需要 Xvfb、不需要显示器、不需要 VNC。

**两个必须防的坑**

1. **和采集抢内存。** 一个 Chromium 约 500MB，2G 内存跑不了两个。
   所以登录会话和采集共用一把锁：谁在跑，另一个就得等。

2. **浏览器泄漏。** 登录会话可能被用户晾在那儿（截了二维码不扫就跑了）。
   必须有超时自动回收，否则一个 Chromium 进程会一直占着内存。

**我还没验证过的事**

抖音登录页可能带滑块/验证码。**如果撞上，纯无头浏览器很可能过不去** ——
那时候二维码截不出来或者扫码后卡住。这是真实风险，不是"应该没事"。
"""

from __future__ import annotations

import asyncio
import base64
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

# 登录会话最长活多久（秒）。超时自动回收，防止浏览器进程泄漏。
SESSION_TTL_S = 300
# 轮询"登录成功了没"的间隔
POLL_INTERVAL_S = 2.0

# 二维码在抖音登录页上的可能位置。挨个试，都不中就截整个视口。
QR_SELECTORS = (
    "img[src*='qrcode']",
    "img[src*='qr_code']",
    "canvas[class*='qrcode']",
    "[class*='qrcode'] img",
    "[class*='qrcode-image']",
    "[class*='login'] canvas",
    "[class*='login'] img",
)


@dataclass
class LoginState:
    active: bool = False
    session_id: str = ""
    status: str = "idle"        # idle|starting|waiting|scanned|ok|expired|error|cancelled
    message: str = ""
    nickname: str = ""
    sec_uid: str = ""
    started_at: float = 0.0
    qr_at: float = 0.0
    error: str = ""
    qr_source: str = ""         # 二维码是"元素截图"还是"整屏截图"
    refreshes: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = {
            "active": self.active,
            "session_id": self.session_id,
            "status": self.status,
            "message": self.message,
            "nickname": self.nickname,
            "sec_uid": self.sec_uid,
            "error": self.error,
            "qr_source": self.qr_source,
            "refreshes": self.refreshes,
        }
        d["elapsed_s"] = round(time.time() - self.started_at, 1) if self.started_at else 0.0
        d["qr_age_s"] = round(time.time() - self.qr_at, 1) if self.qr_at else 0.0
        return d


class LoginSession:
    """全局唯一 —— 一个浏览器实例，一次只能服务一个人。"""

    _instance: "LoginSession | None" = None

    @classmethod
    def get(cls) -> "LoginSession":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self.state = LoginState()
        self._task: asyncio.Task | None = None
        self._ctx: Any = None
        self._page: Any = None
        self._qr_png: bytes = b""

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    # ── 生命周期 ────────────────────────────────────────────

    async def start(self, *, tier: str = "a", account: str = "") -> dict[str, Any]:
        from .runner import CollectionRunner

        if self.busy:
            return {"accepted": False, "reason": "已经有登录会话在进行中"}
        if CollectionRunner.get().busy:
            return {
                "accepted": False,
                "reason": "正在采集，浏览器被占用了。等这一轮跑完再登录（2G 内存跑不了两个浏览器）",
            }

        self.state = LoginState(
            active=True,
            session_id=uuid.uuid4().hex[:8],
            status="starting",
            message="正在启动浏览器…",
            started_at=time.time(),
        )
        self._qr_png = b""
        self._task = asyncio.create_task(self._run(tier=tier))
        await asyncio.sleep(0)     # 让 task 先跑起来
        return {"accepted": True, "session_id": self.state.session_id}

    async def cancel(self) -> dict[str, Any]:
        if not self.busy:
            return {"cancelled": False, "reason": "没有进行中的登录"}
        assert self._task is not None
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):
            pass
        await self._cleanup()
        self.state.active = False
        self.state.status = "cancelled"
        self.state.message = "已取消"
        return {"cancelled": True}

    async def _cleanup(self) -> None:
        ctx = self._ctx
        self._ctx = None
        self._page = None
        if ctx is not None:
            try:
                if ctx.session is not None:
                    await ctx.session.stop()
            except Exception:
                pass
            try:
                ctx.close()
            except Exception:
                pass

    # ── 二维码 ──────────────────────────────────────────────

    def qr_bytes(self) -> bytes:
        return self._qr_png

    async def refresh_qr(self) -> dict[str, Any]:
        """二维码过期了重新截一张（页面自己会换新码，重截即可）。"""
        if not self.busy or self._page is None:
            return {"ok": False, "reason": "没有进行中的登录会话"}
        try:
            await self._capture_qr(self._page)
            self.state.refreshes += 1
            return {"ok": True, "qr_source": self.state.qr_source}
        except Exception as exc:
            return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}

    async def _capture_qr(self, page: Any) -> None:
        """截二维码。先试元素截图（干净），不行就截整个视口。"""
        shot = None
        used = ""
        for sel in QR_SELECTORS:
            try:
                loc = page.locator(sel).first
                if await loc.count() == 0:
                    continue
                box = await loc.bounding_box()
                # 太小的多半是图标不是二维码
                if not box or box.get("width", 0) < 80 or box.get("height", 0) < 80:
                    continue
                shot = await loc.screenshot()
                used = f"元素 {sel}"
                break
            except Exception:
                continue

        if shot is None:
            # 兜底：整个视口。用户还是能看到二维码，只是图上多了些别的东西。
            shot = await page.screenshot(full_page=False)
            used = "整个视口（没找到二维码元素）"

        self._qr_png = shot
        self.state.qr_source = used
        self.state.qr_at = time.time()

    # ── 主流程 ──────────────────────────────────────────────

    async def _run(self, *, tier: str) -> None:
        from ..app import AppContext
        from ..collect.self_profile import SelfCollector

        try:
            ctx = AppContext.create(migrate_db=True)
            self._ctx = ctx

            # **强制无头。**
            #
            # 这是必须的，不是优化：网页登录由我们自己截图二维码给用户看，
            # 可见窗口毫无用处，却带来两个失败模式 ——
            #   1. 从后台进程启动可见浏览器，在无桌面会话的环境里会直接挂住
            #   2. 服务器上根本没有显示器
            # tier a 的配置是 headless=false（本机扫码方便），这里要覆盖掉。
            session = await ctx.open_session(headless_override=True)
            # 登录必须走持久 profile（不能读那个正要被更新的 state 文件）
            session.force_persistent_profile(tier)
            await session.ensure(tier)
            page = await session.page(tier)
            self._page = page

            home = ctx.config.targets.home_url
            self.state.message = "正在打开抖音…"
            # 加超时：抖音首页有一堆长连接，等"完全加载完"可能永远不返回。
            # 卡住的时候必须能失败，不能一直挂着。
            try:
                page = await asyncio.wait_for(
                    session.goto(tier, home, settle_s=3.0), timeout=45
                )
            except asyncio.TimeoutError:
                raise RuntimeError(
                    "打开抖音超时（45 秒）。可能是网络问题，或者浏览器起不来。"
                ) from None
            self._page = page

            collector = SelfCollector(ctx)

            async def probe_identity() -> tuple[str, str]:
                if "douyin.com" not in (page.url or ""):
                    return "", ""
                body, status, _err = await collector.fetch_in_page(
                    page, collector.api_url("self", 0)
                )
                if not body:
                    return "", ""
                import json as _json

                try:
                    payload = _json.loads(body.decode("utf-8", errors="replace"))
                except Exception:
                    return "", ""
                user = payload.get("user") or {}
                return user.get("sec_uid") or "", user.get("nickname") or ""

            sec_uid, nickname = await probe_identity()
            if sec_uid:
                # 已经登录着（持久 profile 里还有效）—— 直接导出，不用扫码
                self.state.status = "ok"
                self.state.nickname = nickname
                self.state.sec_uid = sec_uid
                self.state.message = f"已经是登录状态：{nickname}"
                await self._export(session, ctx, tier, sec_uid, nickname)
                return

            self.state.message = "正在截取二维码…"
            await self._capture_qr(page)
            self.state.status = "waiting"
            self.state.message = "请用抖音 App 扫码"

            deadline = time.time() + SESSION_TTL_S
            scanned_noted = False
            while time.time() < deadline:
                await asyncio.sleep(POLL_INTERVAL_S)
                sec_uid, nickname = await probe_identity()
                if sec_uid:
                    self.state.status = "ok"
                    self.state.nickname = nickname
                    self.state.sec_uid = sec_uid
                    self.state.message = f"登录成功：{nickname}"
                    await self._export(session, ctx, tier, sec_uid, nickname)
                    return
                # 二维码大概 3-5 分钟换一次，超过 90 秒就重截一张
                if time.time() - self.state.qr_at > 90:
                    try:
                        await self._capture_qr(page)
                    except Exception:
                        pass
                if not scanned_noted and time.time() - self.state.started_at > 25:
                    self.state.message = "还没检测到登录。二维码过期可以点「刷新二维码」"
                    scanned_noted = True

            self.state.status = "expired"
            self.state.message = "二维码超时（5 分钟）。点「重新开始」再试一次"

        except asyncio.CancelledError:
            self.state.status = "cancelled"
            self.state.message = "已取消"
            raise
        except Exception as exc:
            self.state.status = "error"
            self.state.error = f"{type(exc).__name__}: {exc}"
            self.state.message = f"登录失败：{self.state.error}"
        finally:
            self.state.active = False
            await self._cleanup()

    async def _export(self, session: Any, ctx: Any, tier: str, sec_uid: str, nickname: str) -> None:
        """把登录态写进账号目录。"""
        try:
            path = await session.export_state(tier, session.state_file_for(tier))
            ctx.db.log_event(
                "info", "login",
                f"网页扫码登录成功：{nickname or sec_uid[:16]}，登录态已写入 {path}",
            )
        except Exception as exc:
            self.state.error = f"登录成功但导出失败：{exc}"
