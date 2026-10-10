"""登录态健康检查。

不能等到采集返回一堆空数据才发现登录掉了——那时候你已经污染了分析结果。
所以每次采集轮次开始前先探一次。

判定依据（按可靠性排序）：
1. cookie 里还有 sessionid 之类——最直接，但可能有"过期但仍在"的情况。
2. 打开一个需要登录的页面，看是否被重定向到登录/弹登录框。
3. 抓一个只有登录才返回数据的接口，看 data 是否为空。

三种证据都记下来，人工判断时有依据。
"""

from __future__ import annotations

from typing import Any, Sequence

LOGIN_COOKIES = ("sessionid", "sessionid_ss", "sid_tt", "uid_tt")


def _cookie_names_from(cookies: Any) -> set[str]:
    return {c.get("name", "") for c in cookies or []}


async def async_cookie_names(context: Any) -> set[str]:
    try:
        cookies = await context.cookies()
    except Exception:
        return set()
    return _cookie_names_from(cookies)


async def check_login(
    context: Any,
    page: Any,
    *,
    probe_url: str = "",
    login_marker_selectors: Sequence[str] = (),
    ready_marker_selectors: Sequence[str] = (),
    timeout_ms: int = 15_000,
) -> dict[str, Any]:
    """返回 {ok, logged_in, evidence, detail}。绝不抛异常，探测失败也返回结果。"""
    evidence: dict[str, Any] = {}
    names = await async_cookie_names(context)
    evidence["login_cookies"] = sorted(n for n in LOGIN_COOKIES if n in names)
    evidence["cookie_count"] = len(names)

    if not evidence["login_cookies"]:
        return {
            "ok": True,
            "logged_in": False,
            "reason": "缺少登录 cookie",
            "evidence": evidence,
        }

    if not probe_url:
        return {
            "ok": True,
            "logged_in": True,
            "reason": "登录 cookie 存在（未做页面探测）",
            "evidence": evidence,
        }

    try:
        await page.goto(probe_url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception as exc:
        return {
            "ok": False,
            "logged_in": None,
            "reason": f"探测页面打开失败：{exc}",
            "evidence": evidence,
        }

    for selector in ready_marker_selectors:
        try:
            if await page.locator(selector).count() > 0:
                evidence["ready_marker"] = selector
                return {
                    "ok": True,
                    "logged_in": True,
                    "reason": f"命中已登录标志 {selector}",
                    "evidence": evidence,
                }
        except Exception:
            continue

    for selector in login_marker_selectors:
        try:
            if await page.locator(selector).count() > 0:
                evidence["login_marker"] = selector
                return {
                    "ok": True,
                    "logged_in": False,
                    "reason": f"命中登录墙标志 {selector}",
                    "evidence": evidence,
                }
        except Exception:
            continue

    evidence["final_url"] = getattr(page, "url", "")
    return {
        "ok": True,
        "logged_in": None,
        "reason": "未配置标志选择器，无法判定；请用 scout probe 确定后写入 local.yaml",
        "evidence": evidence,
    }
