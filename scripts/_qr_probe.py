"""测试：能否从抖音页面上下文中直接调用**登录二维码接口**。

背景：昨晚发现全新匿名上下文访问 douyin.com 首页会返回「验证码中间页」，
于是判断"网页扫码登录做不了"。

但那个页面的**域名仍然是 douyin.com** —— 从它里面发 fetch 依然是同源的。
而我们早就验证过 favorite/list、aweme/post 这些接口通过页面内 fetch 全部正常。

所以真正该问的是：**登录二维码接口能不能也这样调？**

如果能，通用登录就有路了：不需要渲染登录页，只需要调接口拿二维码 →
展示给用户 → 轮询扫码状态 → 拿到 cookie。
"""

import asyncio
import json
import sys

sys.path.insert(0, "src")
from playwright.async_api import async_playwright

# 抖音 web 登录相关的候选接口。不确定哪个是对的，全试。
CANDIDATES = [
    "/passport/web/get_qrcode/?aid=6383&next=https%3A%2F%2Fwww.douyin.com%2F",
    "/aweme/v1/web/get_qrcode/?aid=6383",
    "/passport/web/get_qrcode/?aid=6383",
    "/passport/web/check_qrconnect/?aid=6383&token=test",
]

JS = """
async (args) => {
  try {
    const r = await fetch(args.url, {
      credentials: 'include',
      headers: {'accept': 'application/json, text/plain, */*'}
    });
    const t = await r.text();
    return {status: r.status, len: t.length, body: t.slice(0, 1200)};
  } catch (e) {
    return {status: -1, len: 0, body: '', error: String(e)};
  }
}
"""


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        # 全新上下文 = 未登录
        ctx = await b.new_context(locale="zh-CN", viewport={"width": 1280, "height": 900})
        pg = await ctx.new_page()

        print("=== 1. 先看首页到底是什么（确认域名和内容）===")
        await pg.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=45000)
        await pg.wait_for_timeout(5000)
        print("  URL  :", pg.url)
        print("  标题 :", await pg.title())
        print("  同源? :", "yes - fetch 能带 cookie" if "douyin.com" in pg.url else "NO")

        # 看看页面上有没有 QR 相关的东西（万一验证码页之后还有内容）
        info = await pg.evaluate("""() => ({
            imgs: document.querySelectorAll('img').length,
            canvas: document.querySelectorAll('canvas').length,
            scripts: document.querySelectorAll('script').length,
            bodyLen: (document.body ? document.body.innerHTML.length : 0),
            cookies: document.cookie.length,
        })""")
        print("  页面元素:", json.dumps(info, ensure_ascii=False))

        print()
        print("=== 2. 逐个试登录相关接口 ===")
        for path in CANDIDATES:
            res = await pg.evaluate(JS, {"url": path})
            body = res.get("body") or ""
            status = res.get("status")
            mark = "★" if status == 200 and len(body) > 40 else " "
            print(f"\n  {mark} {path}")
            print(f"     HTTP {status}  {res.get('len', 0)} 字节")
            if res.get("error"):
                print(f"     error: {res['error'][:100]}")
            if body:
                print(f"     内容: {body[:300].replace(chr(10), ' ')}")
            await asyncio.sleep(1.5)

        print()
        print("=== 3. 看看这次访问种下了哪些 cookie ===")
        cookies = await ctx.cookies()
        names = sorted({c["name"] for c in cookies})
        print(f"  共 {len(cookies)} 个 cookie")
        for n in names[:20]:
            print(f"    {n}")

        await b.close()


asyncio.run(main())
