"""统计数据质量测试。

背景：用户看到页面上"转发是点赞的 8 倍""评论多于点赞"，判断是 bug。
查证结论是 —— **这些数字就是抖音接口返回的，我们没算错**
（12 个作品抽样对比实时接口，10 个完全一致，2 个差 1 个赞）。

真正的问题是两个机制缺失：
1. 反常数字没有校验，被当正常数据展示
2. 页面不标数据时效，把可能过期的数字当"当前事实"呈现

这组测试盯住这两件事。
"""

from __future__ import annotations

from scout.store.quality import check_stats


def test_normal_video_is_clean():
    """正常比例不该被标记 —— 假警报多了人就无视它了。"""
    assert check_stats({
        "digg_count": 10000, "comment_count": 300,
        "share_count": 800, "collect_count": 1200,
    }) == ""


def test_detects_comment_over_like():
    """实测：#小狗 赞 6207 评 11193。"""
    note = check_stats({"digg_count": 6207, "comment_count": 11193})
    assert "评论(11193)多于点赞(6207)" in note


def test_detects_share_far_over_like():
    """实测：#小狗 转 50701 / 赞 6207 = 8.2 倍。"""
    note = check_stats({"digg_count": 6207, "share_count": 50701})
    assert "8.2 倍" in note


def test_detects_collect_over_like():
    note = check_stats({"digg_count": 1000, "collect_count": 3000})
    assert "收藏(3000)是点赞(1000)的 3.0 倍" in note


def test_low_volume_is_not_flagged():
    """**样本量门槛**：1 个赞 2 条评论是噪声，不是异常。

    实测踩过这个坑：不设门槛时 296 个作品标出 11 个，
    其中大部分是"1 赞 2 评论"这种小号的正常互动 —— 满屏假警报。
    """
    assert check_stats({"digg_count": 1, "comment_count": 2}) == ""
    assert check_stats({"digg_count": 23, "comment_count": 40}) == ""
    assert check_stats({"digg_count": 4, "comment_count": 14}) == ""


def test_threshold_boundary():
    """刚好到门槛（100 赞）才开始判断。"""
    assert check_stats({"digg_count": 99, "comment_count": 500}) == ""
    assert check_stats({"digg_count": 100, "comment_count": 500}) != ""


def test_negative_like_is_flagged_even_when_small():
    assert "点赞数为负" in check_stats({"digg_count": -5})


def test_missing_fields_do_not_crash():
    assert check_stats({}) == ""
    assert check_stats({"digg_count": None, "comment_count": None}) == ""
    assert check_stats({"digg_count": "abc"}) == ""


def test_note_says_data_is_unmodified():
    """标注文案必须说清：这是接口原文，我们没改。

    因为结论可能是"这条视频确实转发多"，而不是数据错。
    """
    note = check_stats({"digg_count": 6207, "share_count": 50701})
    assert "未经修改" in note


def test_multiple_anomalies_are_joined():
    note = check_stats({"digg_count": 6207, "comment_count": 11193, "share_count": 50701})
    assert "评论" in note and "转发" in note
