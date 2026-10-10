"""统计数据合理性校验。

**为什么需要这个模块**

页面上出现过"转发是点赞的 8 倍""评论多于点赞"的数字。查证下来，
这些数字**就是抖音接口返回的，我们没有算错**（12 个作品抽样对比实时接口，
10 个完全一致，2 个差 1 个赞 —— 是别人刚点的）。

所以问题不在解析，而在两件事：

1. **没有校验**：反常数字被当成正常数据直接展示，用户看到就觉得是 bug
2. **没有时效标注**：页面把可能过期的数字当"当前事实"呈现

这个模块负责第 1 件。第 2 件由 `stats_fetched_at` + TTL 刷新负责。

**设计原则：标注，不修改。**
我们不该假装知道哪个数字"对"——可能真的是那条视频转发多。
所以只**标记出来**并说明理由，让人去核实。既不掩盖，也不篡改。
"""

from __future__ import annotations

from typing import Any

# 阈值定得偏保守：宁可少标，也不要满屏噪声。
# 正常的抖音视频，评论一般是点赞的 1%-10%，转发 1%-20%。
COMMENT_VS_DIGG = 1.5      # 评论 > 点赞 × 1.5 → 反常
SHARE_VS_DIGG = 3.0        # 转发 > 点赞 × 3 → 反常
COLLECT_VS_DIGG = 2.0      # 收藏 > 点赞 × 2 → 反常

# **样本量门槛**：点赞太少时，比例全是噪声。
# 实测踩过：1 个赞 2 条评论也会被标出来 —— 那是小号上朋友互相评论，
# 完全正常。满屏假警报比没有警报更糟，因为人会开始无视它。
MIN_DIGG_FOR_RATIO = 100


def _positive(value: Any) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def check_stats(record: dict[str, Any]) -> str:
    """检查一条作品的统计是否反常，返回说明文字；正常返回空串。"""
    digg = _positive(record.get("digg_count"))
    comment = _positive(record.get("comment_count"))
    share = _positive(record.get("share_count"))
    collect = _positive(record.get("collect_count"))
    notes: list[str] = []

    # 点赞量太小就不做比例判断 —— 那是噪声，不是异常
    enough = bool(digg and digg >= MIN_DIGG_FOR_RATIO)

    if enough and comment and comment > digg * COMMENT_VS_DIGG:
        notes.append(f"评论({comment})多于点赞({digg})")
    if enough and share and share > digg * SHARE_VS_DIGG:
        notes.append(f"转发({share})是点赞({digg})的 {share / digg:.1f} 倍")
    if enough and collect and collect > digg * COLLECT_VS_DIGG:
        notes.append(f"收藏({collect})是点赞({digg})的 {collect / digg:.1f} 倍")

    if record.get("digg_count") is not None and not digg:
        try:
            if int(record["digg_count"]) < 0:
                notes.append("点赞数为负")
        except (TypeError, ValueError):
            pass

    if not notes:
        return ""
    return "；".join(notes) + "（数据来自抖音接口原文，未经修改，建议核实）"
