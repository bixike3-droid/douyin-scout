"""互动名单（点赞人 / 评论 / 粉丝）的体量自适应抽样策略。

背景：小名单全采没问题；爆款作品的点赞/评论动辄成千上万，
"有数据就全量翻到底"会把请求量成倍放大。所以按体量分段定预算：

    total ≤ all_below      → 全采（total 条）
    更大                    → min(cap, max(floor, ceil(total × ratio)))
    未知（None / 非正数）    → floor（先按一页规模探一层）

默认参数示例（0.4 / 20 / 100 / 30）：10 → 10；30 → 30；50 → 20；10000 → 100。

三种可组合的玩法（见 docs/product.md「采集策略」）：
    A 抽样直采：预算 = 采集量 = 分析量（默认，省请求）
    B 全采后清洗：全量存下 → 清洗（门槛过滤/去重）→ 分析清洗后数据
    C 组合：全采 → 清洗 → 按预算随机抽样（本模块 sample_rows）→ 分析
"""
from __future__ import annotations

import math
import random
from typing import Any, Iterable, Sequence


def budget(total: int | None, *, ratio: float = 0.4, floor: int = 20,
           cap: int = 100, all_below: int = 30) -> int:
    """按总量算一条名单的采集/分析预算。"""
    try:
        total = int(total)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        total = None
    if total is None or total <= 0:
        return max(0, floor)  # 未知体量：先探一层，不放大请求
    if total <= all_below:
        return total
    return min(cap, max(floor, math.ceil(total * ratio)))


def budget_for(cfg: Any, total: int | None) -> int:
    """从 targets 配置（ctx.config.targets）取策略参数计算预算。"""
    return budget(total, ratio=cfg.sampling_ratio, floor=cfg.sampling_floor,
                  cap=cfg.sampling_cap, all_below=cfg.sampling_all_below)


def sample_rows(rows: Sequence[Any] | Iterable[Any], count: int,
                *, rng: random.Random | None = None) -> list[Any]:
    """从已存数据里随机抽 count 条（组合模式 C 的分析前抽样）。保持原始相对顺序。"""
    items = list(rows)
    if count >= len(items):
        return items
    if count <= 0:
        return []
    picker = rng or random.Random()
    picked = sorted(picker.sample(range(len(items)), count))
    return [items[index] for index in picked]
