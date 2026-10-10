"""作品归属测试 —— 防止"别人的视频挂在你名下"。

踩过的大坑（2026-10-10）：用户发现一个 **98 粉丝**的号，页面上挂着 **178 万赞**的视频，
去抖音一看那人的作品最高才十来个赞。

根因：`_parse_user_works` 原来调 `extract_works(payload)`，
而那个函数**递归遍历整个响应的每一层**，把任何"长得像作品"的对象都收进来。
抖音会在 `aweme/post` 响应里塞推广/推荐位视频（别人家的、动辄百万赞），
于是这些视频被当成"这个人的作品"存下来、并关联到他名下。

这个错误**极度危险**，因为它污染的是**作品归属关系** ——
后面的 AI 画像、数据可视化全部建立在"这个作品是谁的"之上。

所以加固三层，这组测试盯住每一层：
1. 解析器只读 `aweme_list`，不递归扫
2. 解析时按作者过滤
3. 落库时只关联作者确实是本人的作品
"""

from __future__ import annotations

from scout.parse import parse_payload

ME = "MS4wLjABAAAAme_aaaaaaaaaaaaaaaaaaaaaaaaaa"
OTHER = "MS4wLjABAAAAother_bbbbbbbbbbbbbbbbbbbbbbbb"
URL = f"https://www.douyin.com/aweme/v1/web/aweme/post/?sec_user_id={ME}&count=18&max_cursor=0"


def _work(aid: str, author: str, desc: str = "x", digg: int = 1) -> dict:
    return {
        "aweme_id": aid,
        "desc": desc,
        "create_time": 1700000000,
        "author": {"sec_uid": author, "nickname": "某人"},
        "statistics": {"digg_count": digg, "comment_count": 1, "share_count": 0},
    }


def test_only_reads_aweme_list():
    """响应里 aweme_list 之外的对象**绝对不能**被当成作品收进来。"""
    payload = {
        "status_code": 0,
        "aweme_list": [_work("111", ME), _work("222", ME)],
        # 模拟抖音塞进来的推广/推荐位 —— 别人的爆款视频
        "recommend_banner": {
            "cards": [
                {"aweme_id": "999", "desc": "别人的爆款",
                 "author": {"sec_uid": OTHER},
                 "statistics": {"digg_count": 1784075, "comment_count": 215111}},
            ]
        },
        "has_more": 0,
        "max_cursor": 0,
    }
    result = parse_payload(URL, payload)
    ids = {w["aweme_id"] for w in result.works}
    assert ids == {"111", "222"}, f"混进了非 aweme_list 的作品：{ids}"
    assert "999" not in ids, "推广位视频混进来了 —— 这正是 178 万赞那个 bug"


def test_drops_works_by_other_author():
    """aweme_list 里混进别人的作品也要丢掉（第二层防护）。"""
    payload = {
        "status_code": 0,
        "aweme_list": [_work("111", ME), _work("999", OTHER, digg=1784075)],
        "has_more": 0,
    }
    result = parse_payload(URL, payload)
    ids = {w["aweme_id"] for w in result.works}
    assert ids == {"111"}
    assert any("作者不是本人" in n for n in result.notes)


def test_keeps_own_works_when_author_matches():
    payload = {"status_code": 0, "aweme_list": [_work("111", ME), _work("222", ME)], "has_more": 0}
    result = parse_payload(URL, payload)
    assert len(result.works) == 2
    assert not any("丢掉" in n for n in result.notes)


def test_nested_aweme_objects_in_time_list_are_ignored():
    """`time_list` 这类字段里嵌套的对象也不能被当成作品。"""
    payload = {
        "status_code": 0,
        "aweme_list": [_work("111", ME)],
        "time_list": [{"date": "2024-01", "items": [_work("888", OTHER, digg=999999)]}],
        "has_more": 0,
    }
    result = parse_payload(URL, payload)
    assert {w["aweme_id"] for w in result.works} == {"111"}


def test_missing_aweme_list_reports_structure_change():
    result = parse_payload(URL, {"status_code": 0, "data": []})
    assert result.works == []
    assert any("结构可能变了" in n for n in result.notes)


def test_real_case_98_fans_with_1_7m_likes_is_impossible():
    """回归测试：真实事故。

    新（98 粉丝）的响应 aweme_list 是 14 条他自己的作品，
    但解析器吐出 17 条，多出的 3 条是别人 178 万赞的爆款。
    现在必须严格等于 14。

    注意 aweme_id 必须是**纯数字字符串** —— `looks_like_work` 就是这么判的，
    非数字会被当成"不像作品"直接跳过（写这条测试时踩过）。
    """
    mine = [_work(str(7000000000000000000 + i), ME) for i in range(14)]
    payload = {
        "status_code": 0,
        "aweme_list": mine,
        "has_more": 0,
        "max_cursor": 0,
        # 这三个就是当时混进来的（嵌套在 aweme_list 之外）
        "extra": {
            "7271271600689777976": _work("7271271600689777976", OTHER, "这样的男孩，是不是你？", 1784075),
            "7277924627853200694": _work("7277924627853200694", OTHER, "什么样的男生不可能是渣男？", 241038),
            "7281197367133523211": _work("7281197367133523211", OTHER, "两个细节判断男生是不是喜欢你", 243206),
        },
    }
    result = parse_payload(URL, payload)
    assert len(result.works) == 14, f"应严格 14 条，实际 {len(result.works)}"
    assert all(w["author_sec_uid"] == ME for w in result.works)
    assert max(w["digg_count"] for w in result.works) <= 9, "混进来了百万赞的别人视频"
