"""声明式页面交互。

为什么要有这一层：抖音的界面元素名、按钮文案、"查看全部"放在哪，我猜不出来，
而且会改。所以把交互做成一串**配置里的动作**，而不是写死在采集器里。
改版时改 YAML，不改代码。

支持的动作：
    click          按选择器点击           selector, nth, timeout_ms
    click_text     按文案点击             text, exact, nth, timeout_ms
    click_pattern  按正则匹配文案点击      pattern, selector(限定范围), nth, max, timeout_ms
    click_all      匹配到的元素全点一遍    text 或 selector, max, timeout_ms
    hover          悬停                   selector
    scroll         拟人滚动               rounds, min_px, max_px
    wait           等待                   seconds
    press          按键                   key
    goto           跳转                   url
    back           浏览器返回             （无参数）
    move           鼠标微动               times
    screenshot     截图                   path, full_page
    dump_texts     列出可见短文本（找按钮文案用）  keyword, max, max_len
    dump_html      导出元素 outerHTML（看结构用）  selector, path

任何动作加 optional: true，失败就跳过而不中止整串。

用法：
    actions = ctx.config.interactions.get("notice_expand")
    report = await run_actions(page, actions)
    print(report.summary())
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .humanize import human_gap, human_scroll, micro_move


@dataclass
class ActionResult:
    action: str
    ok: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "ok": self.ok, "detail": self.detail}


@dataclass
class ActionReport:
    results: list[ActionResult] = field(default_factory=list)
    aborted: bool = False

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def failed(self) -> list[ActionResult]:
        return [r for r in self.results if not r.ok]

    def summary(self) -> dict[str, Any]:
        return {
            "steps": len(self.results),
            "ok": self.ok_count,
            "failed": len(self.failed),
            "aborted": self.aborted,
            "detail": [r.to_dict() for r in self.results],
        }


async def run_actions(
    page: Any,
    actions: Sequence[dict] | None,
    *,
    export_dir: Path | None = None,
    sink: dict | None = None,
) -> ActionReport:
    """按顺序执行动作串。任何单步失败都不会抛出去。

    sink：给动作一个回传结构化数据的地方（比如抽出的一批用户链接）。
    字符串 detail 装不下列表。
    """
    report = ActionReport()
    if not actions:
        return report

    for raw in actions:
        if not isinstance(raw, dict):
            report.results.append(ActionResult("invalid", False, f"动作必须是映射：{raw!r}"))
            continue
        name = str(raw.get("action") or "").strip()
        optional = bool(raw.get("optional"))
        try:
            detail = await _dispatch(page, name, raw, export_dir, sink)
            report.results.append(ActionResult(name, True, detail))
        except Exception as exc:
            report.results.append(ActionResult(name, False, f"{type(exc).__name__}: {exc}"))
            if not optional:
                report.aborted = True
                break
        await asyncio.sleep(0.3)

    return report


async def _dispatch(
    page: Any, name: str, spec: dict, export_dir: Path | None, sink: dict | None = None
) -> str:
    if name == "click":
        selector = str(spec.get("selector") or "")
        if not selector:
            raise ValueError("click 需要 selector")
        locator = page.locator(selector)
        count = await locator.count()
        if count == 0:
            raise LookupError(f"没找到元素 {selector}")
        nth = int(spec.get("nth", 0))
        await locator.nth(nth).click(timeout=int(spec.get("timeout_ms", 5000)))
        return f"{selector}[{nth}]（匹配 {count} 个）"

    if name == "click_text":
        text = str(spec.get("text") or "")
        if not text:
            raise ValueError("click_text 需要 text")
        locator = page.get_by_text(text, exact=bool(spec.get("exact", False)))
        count = await locator.count()
        if count == 0:
            raise LookupError(f"没有文案为「{text}」的元素")
        nth = int(spec.get("nth", 0))
        await locator.nth(nth).click(timeout=int(spec.get("timeout_ms", 5000)))
        return f"「{text}」[{nth}]（匹配 {count} 个）"

    if name == "click_all":
        text = spec.get("text")
        selector = spec.get("selector")
        if not text and not selector:
            raise ValueError("click_all 需要 text 或 selector")
        limit = int(spec.get("max", 10))
        locator = page.get_by_text(str(text), exact=False) if text else page.locator(str(selector))
        total = await locator.count()
        count = min(total, limit)
        clicked = 0
        for i in range(count):
            try:
                await locator.nth(i).click(timeout=int(spec.get("timeout_ms", 3000)))
                clicked += 1
                await human_gap(0.4, 1.2)
            except Exception:
                continue
        if clicked == 0:
            raise LookupError(f"click_all 一个都没点到（匹配 {total} 个）")
        return f"点开 {clicked}/{total} 个"

    if name == "hover":
        selector = str(spec.get("selector") or "")
        if not selector:
            raise ValueError("hover 需要 selector")
        await page.locator(selector).first.hover(timeout=int(spec.get("timeout_ms", 5000)))
        return selector

    if name == "scroll":
        rounds = int(spec.get("rounds", 1))
        await human_scroll(
            page,
            rounds=rounds,
            min_px=int(spec.get("min_px", 480)),
            max_px=int(spec.get("max_px", 1100)),
            over=str(spec.get("over") or ""),
        )
        return f"滚动 {rounds} 轮" + (f"（悬停 {spec['over']}）" if spec.get("over") else "")

    if name == "wait":
        seconds = float(spec.get("seconds", 1.0))
        await asyncio.sleep(max(0.0, seconds))
        return f"等待 {seconds}s"

    if name == "press":
        key = str(spec.get("key") or "Escape")
        await page.keyboard.press(key)
        return key

    if name == "goto":
        url = str(spec.get("url") or "")
        if not url:
            raise ValueError("goto 需要 url")
        await page.goto(url, wait_until=str(spec.get("wait_until", "domcontentloaded")),
                        timeout=int(spec.get("timeout_ms", 45000)))
        return url

    if name == "back":
        await page.go_back(wait_until="domcontentloaded", timeout=int(spec.get("timeout_ms", 20000)))
        return "back"

    if name == "move":
        await micro_move(page, times=int(spec.get("times", 2)))
        return "鼠标微动"

    if name == "screenshot":
        if export_dir is None:
            raise ValueError("screenshot 需要 export_dir")
        export_dir.mkdir(parents=True, exist_ok=True)
        target = export_dir / str(spec.get("path") or f"action-{int(asyncio.get_event_loop().time())}.png")
        await page.screenshot(path=str(target), full_page=bool(spec.get("full_page", False)))
        return str(target)

    if name == "click_pattern":
        pattern = str(spec.get("pattern") or "")
        if not pattern:
            raise ValueError("click_pattern 需要 pattern")
        scope = spec.get("selector")
        root = page.locator(str(scope)) if scope else page
        locator = root.get_by_text(re.compile(pattern))
        total = await locator.count()
        if total == 0:
            raise LookupError(f"没有文案匹配 /{pattern}/ 的元素")
        nth = int(spec.get("nth", 0))
        await locator.nth(nth).click(timeout=int(spec.get("timeout_ms", 5000)))
        return f"/{pattern}/[{nth}]（匹配 {total} 个）"

    if name == "hover_text":
        """悬停到某段文字上。

        为什么需要：抖音的「互动消息」面板是**活页** —— 鼠标悬停在入口上才存在，
        鼠标一移开就自动关闭。所以"点开"这个动作本身就是错的：
        点完鼠标就离开了，面板当场消失，后面什么都抓不到。
        正确做法是悬停并**保持鼠标不离**。
        """
        text = str(spec.get("text") or "")
        if not text:
            raise ValueError("hover_text 需要 text")
        locator = page.get_by_text(text, exact=bool(spec.get("exact", True)))
        if await locator.count() == 0:
            locator = page.get_by_text(text, exact=False)
        count = await locator.count()
        if count == 0:
            raise LookupError(f"没有文案为「{text}」的元素")
        await locator.first.hover(timeout=int(spec.get("timeout_ms", 5000)))
        return f"悬停「{text}」（匹配 {count} 个）"

    if name == "click_anchor_button":
        """在锚点文案所在的行里，点击最靠右的按钮/图标。

        为什么需要它：互动消息里那条「JJ 等22人赞了你的作品」右侧有个 **› 箭头按钮**，
        点它才展开完整名单。而它是个**图标，没有文字** ——
        click_text / click_pattern 全都点不到，只会静默失败。

        做法：按 DOM 找到锚点文案所在的最小元素 → 逐层往上找容器 →
        在容器里挑最靠右的可点元素（箭头都在行尾）→ 按坐标点它。
        不依赖任何类名，抖音改样式也能用。
        """
        anchor = str(spec.get("anchor") or spec.get("text") or "")
        if not anchor:
            raise ValueError("click_anchor_button 需要 anchor（锚点文案）")
        nth = int(spec.get("nth", 0))
        candidates = str(
            spec.get("candidates")
            or 'button,[role="button"],svg,[class*="arrow"],[class*="Arrow"],[class*="next"],[class*="more"]'
        )
        script = """
        (args) => {
            // 锚点可能被拆成多个叶子节点（"等22人" + "赞了你的作品"），
            // 所以先用完整锚点找，找不到再用尾部关键词找。
            const probes = [args.anchor];
            if (args.anchor.length > 5) probes.push(args.anchor.slice(-5));

            const collect = (probe) => {
                const out = [];
                for (const el of document.querySelectorAll('*')) {
                    if (el.children.length > 0) continue;
                    const t = (el.textContent || '').trim();
                    if (!t || !t.includes(probe)) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) continue;
                    out.push(el);
                }
                return out;
            };

            let leaves = [];
            let usedProbe = args.anchor;
            for (const probe of probes) {
                leaves = collect(probe);
                if (leaves.length) { usedProbe = probe; break; }
            }
            if (leaves.length <= args.nth) return {found: false, count: leaves.length};
            const leaf = leaves[args.nth];

            let node = leaf;
            for (let up = 0; up < 10 && node; up++) {
                let best = null, bestX = -1;
                try {
                    for (const c of node.querySelectorAll(args.candidates)) {
                        if (c === leaf) continue;
                        const r = c.getBoundingClientRect();
                        if (r.width === 0 || r.height === 0) continue;
                        if (r.left > bestX) { bestX = r.left; best = c; }
                    }
                } catch (e) { /* 无效选择器就跳过这一层 */ }
                if (best) {
                    const r = best.getBoundingClientRect();
                    return {
                        found: true,
                        x: r.left + r.width / 2,
                        y: r.top + r.height / 2,
                        tag: best.tagName,
                        cls: String(best.className || '').slice(0, 60),
                        depth: up,
                        probe: usedProbe,
                        count: leaves.length,
                    };
                }
                node = node.parentElement;
            }
            return {found: false, count: leaves.length, reason: '容器里没找到可点元素'};
        }
        """
        res = await page.evaluate(script, {"anchor": anchor, "nth": nth, "candidates": candidates})
        if not res or not res.get("found"):
            raise LookupError(f"锚点「{anchor}」没找到对应的按钮：{res}")
        x, y = float(res["x"]), float(res["y"])
        mode = str(spec.get("mode") or "click")
        await page.mouse.move(x, y, steps=6)
        await asyncio.sleep(0.15)
        if mode == "hover":
            # 活页面板：移过去就行，点了反而会把它弄没
            await asyncio.sleep(0.4)
        elif mode == "move":
            pass
        else:
            await page.mouse.click(x, y)
        return (
            f"{mode} {res.get('tag')} @({int(x)},{int(y)}) "
            f"层级+{res.get('depth')} class={res.get('cls')!r} probe={res.get('probe')!r}"
        )

    if name == "dump_texts":
        """把页面上可见的短文本列出来。找按钮文案用它，不用猜。

        注意别加太多限制：面板/弹层通常渲染在 body 末尾的 portal 里，
        如果按 DOM 顺序取前 N 条就收工，永远看不到面板内容 ——
        踩过这个坑（600 字符截断 + 顺序取前 N），导致找不到「赞过全部」按钮。
        """
        limit = int(spec.get("max", 400))
        max_len = int(spec.get("max_len", 30))
        selector = spec.get("selector")
        script = """
        (args) => {
            const seen = new Set();
            const out = [];
            let root = document.body;
            if (args.scope) {
                try { root = document.querySelector(args.scope) || document.body; }
                catch (e) { root = document.body; }
            }
            if (!root) return {texts: [], total: 0};
            const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
            let node;
            while ((node = walker.nextNode())) {
                const text = (node.textContent || '').trim().replace(/\\s+/g, ' ');
                if (!text || text.length > args.maxLen) continue;
                const el = node.parentElement;
                if (!el) continue;
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                if (seen.has(text)) continue;
                seen.add(text);
                out.push(text);
                if (out.length >= args.limit) break;
            }
            return {texts: out, total: out.length};
        }
        """
        payload = await page.evaluate(
            script, {"maxLen": max_len, "limit": limit, "scope": selector or ""}
        )
        texts = (payload or {}).get("texts") or []
        keyword = str(spec.get("keyword") or "")
        if keyword:
            texts = [t for t in texts if keyword in t]
        joined = " | ".join(str(t) for t in texts)
        max_chars = int(spec.get("max_chars", 4000))
        if len(joined) > max_chars:
            joined = joined[:max_chars] + f" …（还有更多，共 {len(texts)} 条）"
        return joined or "（没有可见短文本）"

    if name == "extract_user_links":
        """从 DOM 里抽出「用户链接」——每个都带 sec_uid 和昵称。

        为什么需要它：**完整点赞人名单不在任何接口响应里**。
        实测确认：「赞过的人」覆盖层的数据是前端直接渲染出来的，
        归档里翻遍所有响应都找不到那 27 个人。
        但 DOM 里有 —— 每个人都是一个链接：

            <a href="//www.douyin.com/user/MS4wLjABAAAA...">
              <div class="E5TO3Wiu">培德娄</div>
            </a>

        sec_uid 在 href 里，昵称是链接内最长的那段叶子文本。
        所以正确做法不是找接口，是**读 DOM** —— 这也正是"把人手动做的事自动化"的本意。

        结果通过 sink 返回给调用方（结构化数据没法塞进 detail 字符串）。
        """
        script = """
        (args) => {
            const out = [];
            const seen = new Set();
            let root = document;
            if (args.scope) {
                try { root = document.querySelector(args.scope) || document; } catch (e) {}
            }
            for (const a of root.querySelectorAll('a[href*="/user/"]')) {
                const href = a.getAttribute('href') || '';
                const m = href.match(/\\/user\\/(MS4wLjAB[A-Za-z0-9_\\-]+)/);
                if (!m) continue;
                const sec = m[1];
                if (seen.has(sec)) continue;

                let name = '';
                for (const el of a.querySelectorAll('*')) {
                    if (el.children.length > 0) continue;
                    const t = (el.textContent || '').trim();
                    if (!t || t.length > 40) continue;
                    if (/^[\\d\\s\\-:.]+$/.test(t)) continue;   // 跳过数字/日期
                    if (t.length > name.length) name = t;
                }
                if (!name) {
                    const t = (a.textContent || '').trim();
                    if (t && t.length <= 40) name = t;
                }
                seen.add(sec);
                out.push({sec_uid: sec, nickname: name});
                if (out.length >= args.limit) break;
            }
            return out;
        }
        """
        found = await page.evaluate(
            script,
            {"scope": str(spec.get("selector") or ""), "limit": int(spec.get("max", 200))},
        ) or []
        if sink is not None:
            bucket = sink.setdefault("user_links", [])
            existing = {u["sec_uid"] for u in bucket}
            for item in found:
                if isinstance(item, dict) and item.get("sec_uid") not in existing:
                    bucket.append(item)
        return f"抽出 {len(found)} 个用户链接"

    if name == "dump_network":
        """列出这个页面**请求过的所有 URL**（来自浏览器的资源计时）。

        为什么需要：如果某个请求的响应没被我们捕获（被 abort、走了 service worker、
        或者属于我们还没认出来的接口），只看归档会得出"这个接口不存在"的错误结论。
        performance 里的资源计时是浏览器自己记的，跑不掉。

        实测用它定位过好几个"看不见的"接口。
        """
        script = """
        (args) => {
            const out = [];
            const seen = new Set();
            for (const e of performance.getEntriesByType('resource')) {
                const url = e.name || '';
                if (!url || seen.has(url)) continue;
                seen.add(url);
                const low = url.toLowerCase();
                if (args.skipStatic &&
                    /\\.(js|css|png|jpg|jpeg|webp|gif|svg|woff2?|mp4|ico)(\\?|$)/.test(low)) continue;
                out.push(url);
                if (out.length >= args.limit) break;
            }
            return out;
        }
        """
        urls = await page.evaluate(
            script,
            {"limit": int(spec.get("max", 200)), "skipStatic": bool(spec.get("skip_static", True))},
        ) or []
        keyword = str(spec.get("keyword") or "")
        if keyword:
            urls = [u for u in urls if keyword in u]
        joined = " | ".join(str(u) for u in urls)
        max_chars = int(spec.get("max_chars", 6000))
        if len(joined) > max_chars:
            joined = joined[:max_chars] + f" …（共 {len(urls)} 条）"
        return joined or "（没有记录到任何请求）"

    if name == "dump_html":
        selector = str(spec.get("selector") or "body")
        if export_dir is None:
            raise ValueError("dump_html 需要 export_dir")
        export_dir.mkdir(parents=True, exist_ok=True)
        name_hint = str(spec.get("path") or f"dom-{selector.replace('.', '_').replace('#', '')[:24]}.html")
        target = export_dir / name_hint
        html = str(await page.locator(selector).first.evaluate("el => el.outerHTML"))
        # 抖音整页 DOM 动辄几 MB，截断到有意义的范围，够看清结构即可
        max_chars = int(spec.get("max_chars", 400_000))
        truncated = len(html) > max_chars
        if truncated:
            html = html[:max_chars] + "\n<!-- 已截断 -->\n"
        target.write_text(html, encoding="utf-8")
        return f"{selector} → {target.name}（{len(html)} 字符{'，已截断' if truncated else ''}）"

    raise ValueError(f"未知动作：{name!r}")
