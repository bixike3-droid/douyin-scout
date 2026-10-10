"""翻页游标测试。

这里踩过一个很隐蔽的坑：解析器返回的游标键名是 `cursor`，
而采集器翻页逻辑读的是 `max_cursor` —— 键名对不上，
每页都拿到 None，判定"到底了"，**结果只采第一页就停**。

表现出来是"接口说有 33 个作品，我们只采到 17 个"，从结果上完全看不出是翻页坏了。
所以这组测试专门盯着键名和翻页行为。
"""

from __future__ import annotations

from scout.collect.api_base import ApiCollector
from scout.parse.extract import extract_cursor
from scout.parse.registry import ParseResult

POST_PAYLOAD = {
    "status_code": 0,
    "aweme_list": [{"aweme_id": "1", "desc": "x", "create_time": 1}],
    "has_more": 1,
    "max_cursor": 1778431677000,
    "min_cursor": 1778431677000,
}


class _Stub(ApiCollector):
    kind = "stub"
    api_url = staticmethod(lambda target, cursor: "u")


def _breaker() -> _Stub:
    return _Stub.__new__(_Stub)


def test_extract_cursor_exposes_both_key_names():
    """`cursor` 和 `max_cursor` 都要有 —— 键名对不上就会只采第一页。"""
    cur = extract_cursor(POST_PAYLOAD)
    assert cur["max_cursor"] == "1778431677000"
    assert cur["cursor"] == "1778431677000"
    assert cur["has_more"] is True


def test_should_continue_reads_max_cursor():
    parsed = ParseResult(cursor=extract_cursor(POST_PAYLOAD))
    assert _breaker().should_continue(parsed, 0) == 1778431677000


def test_should_continue_falls_back_to_cursor_key():
    """只有 `cursor` 键时也必须能翻页（老解析器/别的接口的兼容）。"""
    parsed = ParseResult(cursor={"cursor": "12345", "has_more": True})
    assert _breaker().should_continue(parsed, 0) == 12345


def test_should_continue_stops_when_has_more_false():
    parsed = ParseResult(cursor={"max_cursor": "999", "has_more": False})
    assert _breaker().should_continue(parsed, 0) is None


def test_should_continue_stops_when_cursor_repeats():
    """游标没往前走就停，避免死循环。"""
    parsed = ParseResult(cursor={"max_cursor": "555", "has_more": True})
    assert _breaker().should_continue(parsed, 555) is None


def test_should_continue_stops_on_empty_cursor():
    parsed = ParseResult(cursor={"cursor": "", "max_cursor": "", "has_more": True})
    assert _breaker().should_continue(parsed, 0) is None


def test_should_continue_tolerates_garbage_cursor():
    parsed = ParseResult(cursor={"max_cursor": "not-a-number", "has_more": True})
    assert _breaker().should_continue(parsed, 0) is None


def test_real_post_parse_paginates():
    """端到端：真实结构经解析器出来，翻页逻辑必须能拿到下一页。"""
    from scout.parse import parse_payload

    result = parse_payload(
        "https://www.douyin.com/aweme/v1/web/aweme/post/?sec_user_id=X&max_cursor=0",
        POST_PAYLOAD,
    )
    assert _breaker().should_continue(result, 0) == 1778431677000
