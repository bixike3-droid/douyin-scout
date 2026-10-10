"""拟人化动作。

借鉴 MediaCrawler 的 tools/easing.py 思路：滚动和鼠标移动用缓动曲线，
而不是"瞬间跳到目标位置"。瞬移是最容易被识别为自动化的特征之一。

本模块不 import playwright，page 参数用 Any，保证核心逻辑可单测。
"""

from __future__ import annotations

import asyncio
import math
import random
from typing import Any


# ── 缓动曲线 ─────────────────────────────────────────────────


def ease_in_out_quad(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return 2 * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 2) / 2


def ease_out_cubic(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


def ease_in_out_sine(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return -(math.cos(math.pi * t) - 1) / 2


EASINGS = {
    "quad": ease_in_out_quad,
    "cubic": ease_out_cubic,
    "sine": ease_in_out_sine,
}


def jittered(value: float, ratio: float = 0.25) -> float:
    return value * (1.0 + random.uniform(-ratio, ratio))


def pick(pool: list[Any]) -> Any:
    return random.choice(pool) if pool else None


# ── 异步动作 ─────────────────────────────────────────────────


async def human_gap(min_s: float, max_s: float) -> float:
    """一次短停顿。上下界会小幅抖动，避免边界值被统计出来。"""
    if max_s < min_s:
        min_s, max_s = max_s, min_s
    delay = jittered(random.uniform(min_s, max_s), 0.2)
    delay = max(0.05, delay)
    await asyncio.sleep(delay)
    return delay


async def scroll_steps(
    page: Any,
    *,
    total_px: int,
    steps: int = 6,
    easing: str = "quad",
    settle_s: float = 0.35,
) -> None:
    """把一次滚动拆成若干带缓动的小步。"""
    fn = EASINGS.get(easing, ease_in_out_quad)
    prev = 0.0
    for i in range(1, steps + 1):
        pos = fn(i / steps)
        delta = int((pos - prev) * total_px)
        prev = pos
        if delta:
            await page.mouse.wheel(0, delta)
        await asyncio.sleep(jittered(settle_s / steps, 0.4))
    await asyncio.sleep(jittered(settle_s, 0.3))


async def human_scroll(
    page: Any,
    *,
    rounds: int = 5,
    min_px: int = 480,
    max_px: int = 1100,
    over: str = "",
) -> int:
    """滚动若干轮，逐步加载内容。返回累计像素。

    over：先悬停到某个元素再滚。**面板/弹层内部滚动时必须给**，
    否则滚轮事件落在整页上，内部列表纹丝不动 —— 结果就是"连续几轮没有新响应"
    被误判成触底，静默采到 0 条。这个坑很难从结果上看出来。
    """
    if over:
        try:
            await page.locator(over).first.hover(timeout=5000)
            await asyncio.sleep(jittered(0.25, 0.4))
        except Exception:
            pass

    total = 0
    for _ in range(max(0, rounds)):
        px = random.randint(min_px, max_px)
        await scroll_steps(page, total_px=px)
        total += px
        await human_gap(0.6, 1.8)
    return total


async def micro_move(page: Any, *, times: int = 2) -> None:
    """小幅鼠标移动。不制造"鼠标从未移动过"这种静态特征。"""
    for _ in range(max(0, times)):
        x, y = random.randint(120, 900), random.randint(120, 600)
        try:
            await page.mouse.move(x, y, steps=random.randint(8, 22))
        except Exception:
            return
        await asyncio.sleep(jittered(0.25, 0.5))


async def approach_and_click(page: Any, locator: Any) -> bool:
    """先移动过去再点，而不是直接 locator.click()。失败返回 False。"""
    try:
        box = await locator.bounding_box()
        if box:
            x = box["x"] + box["width"] * random.uniform(0.35, 0.65)
            y = box["y"] + box["height"] * random.uniform(0.35, 0.65)
            await page.mouse.move(x, y, steps=random.randint(10, 28))
            await asyncio.sleep(jittered(0.18, 0.4))
        await locator.click(timeout=5000)
        return True
    except Exception:
        return False
