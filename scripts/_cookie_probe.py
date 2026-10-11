"""决定性测试：登录态里的关键 cookie，能不能被网页 JS（document.cookie）读到。

**为什么这个问题最关键**

如果 `document.cookie` 能读到登录所需的 cookie，那么"自动获取 cookie"就有一个
**零安装**的方案：书签小工具（bookmarklet）——

    用户在抖音页面上点一下书签 → JS 读取 cookie → POST 到我们的服务

用户不需要装任何东西，不需要开发者工具，不需要懂任何技术。

**但如果关键 cookie 是 HttpOnly 的**，JS 读不到，这条路就断了，
只能走「浏览器扩展」或「本地小程序」。

这是一个纯经验问题，不能靠猜。
"""

import asyncio
import json
import sys

sys.path.insert(0, "src")
from scout.app import AppContext
from scout.collect.self_profile import SelfCollector

JS = """
() => {
  const raw = document.cookie || '';
  const names = raw.split(';').map(s => s.trim().split('=')[0]).filter(Boolean);
  return {
    count: names.length,
    names: names.sort(),
    hasSessionid: names.some(n => n === 'sessionid' || n === 'sessionid_ss'),
    rawLen: raw.length,
  };
}
"""


async def main():
    ctx = AppContext.create(migrate_db=False)
    session = await ctx.open_session()
    try:
        session.force_persistent_profile("a")
        await session.ensure("a")
        page = await session.page("a")
        if "douyin.com" not in (page.url or ""):
            page = await session.goto("a", ctx.config.targets.home_url, settle_s=3.0)

        print("=== A. 网页 JS 能读到哪些 cookie（document.cookie）===")
        r = await page.evaluate(JS)
        print(f"  JS 可见 cookie 数: {r['count']}   （{r['rawLen']} 字符）")
        print(f"  含 sessionid?     : {'是 ★' if r['hasSessionid'] else '否 ✗'}")
        print(f"  可见的：{', '.join(r['names'][:25])}")

        print()
        print("=== B. 浏览器里实际存了哪些 cookie（含 HttpOnly）===")
        cookies = await session._sessions["a"].context.cookies()
        all_names = sorted({c["name"] for c in cookies})
        http_only = sorted({c["name"] for c in cookies if c.get("httpOnly")})
        print(f"  总数: {len(cookies)}")
        print(f"  HttpOnly 的（JS 读不到）: {len(http_only)} 个")
        print(f"     {', '.join(http_only[:20])}")

        js_names = set(r["names"])
        hidden = [n for n in all_names if n not in js_names]
        print()
        print(f"=== C. JS 读不到的 cookie 共 {len(hidden)} 个 ===")
        print(f"  {', '.join(hidden[:25])}")

        key = {"sessionid", "sessionid_ss", "sid_tt", "sid_guard", "uid_tt", "odin_tt"}
        blocked = sorted(key & set(hidden))
        visible = sorted(key & js_names)
        print()
        print("=== D. 结论 ===")
        print(f"  登录关键 cookie 中，JS 可见的: {visible or '无'}")
        print(f"  登录关键 cookie 中，被 HttpOnly 挡住的: {blocked or '无'}")
        if not blocked:
            print("  → ★ 书签小工具方案可行（零安装）")
        else:
            print("  → ✗ 必须装东西（浏览器扩展 或 本地程序）")

        print()
        print("=== E. 页面 localStorage 里有什么 ===")
        ls = await page.evaluate("() => Object.keys(window.localStorage)")
        print(f"  {len(ls)} 个键: {', '.join(ls[:12])}")
        print(f"  HasUserLogin = {await page.evaluate('() => window.localStorage.getItem(\"HasUserLogin\")')}")
    finally:
        await session.stop()
        ctx.close()


asyncio.run(main())
