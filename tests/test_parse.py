"""解析层测试。

重点验证「容错」这个性质：形状对就抽得出来，形状不对也绝不抛异常。
"""

from __future__ import annotations

import json

from scout.parse import parse_payload, registered_patterns
from scout.parse.extract import extract_cursor, extract_like_edges, extract_users, extract_works
from scout.parse.walk import as_int, dig, first_of, looks_like_work

SEC_A = "MS4wLjABAAAAaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SEC_B = "MS4wLjABAAAAbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

FIXTURE = {
    "status_code": 0,
    "has_more": 1,
    "max_cursor": "1700000000000",
    "aweme_list": [
        {
            "aweme_id": "7300000000000000001",
            "desc": "第一条作品 #测试",
            "create_time": 1699000000,
            "duration": 15000,
            "statistics": {"digg_count": 120, "comment_count": 8, "share_count": 3},
            "text_extra": [{"hashtag_name": "测试"}, {"hashtag_name": "日常"}],
            "music": {"title": "背景音乐"},
            "author": {"sec_uid": SEC_A, "uid": "1001", "nickname": "作者甲", "unique_id": "jia123",
                       "follower_count": 5200, "aweme_count": 33,
                       "avatar_thumb": {"url_list": ["https://cdn.test/a.jpg"]}},
            "video": {"cover": {"url_list": ["https://cdn.test/c.jpg"]}},
        },
        {
            "aweme_id": "7300000000000000002",
            "desc": "第二条",
            "create_time": 1699100000,
            "statistics": {"digg_count": 5},
            "author": {"sec_uid": SEC_A, "nickname": "作者甲"},
        },
    ],
    "extra": {"nested": {"user": {"sec_uid": SEC_B, "nickname": "路人乙", "follower_count": 80}}},
}


def test_extract_works_keeps_richest_record():
    works = extract_works(FIXTURE)
    assert len(works) == 2
    first = next(w for w in works if w["aweme_id"].endswith("001"))
    assert first["description"] == "第一条作品 #测试"
    assert first["digg_count"] == 120
    assert first["duration_ms"] == 15000
    assert first["author_sec_uid"] == SEC_A
    assert first["music_title"] == "背景音乐"
    assert set(first["hashtags"]) == {"测试", "日常"}
    assert first["cover_url"] == "https://cdn.test/c.jpg"


def test_extract_users_dedups_and_prefers_richest():
    users = extract_users(FIXTURE)
    assert len(users) == 2, "同一 sec_uid 只应出现一次"
    a = next(u for u in users if u["sec_uid"] == SEC_A)
    assert a["nickname"] == "作者甲"
    assert a["douyin_id"] == "jia123"
    assert a["follower_count"] == 5200
    assert a["avatar_url"] == "https://cdn.test/a.jpg"

    b = next(u for u in users if u["sec_uid"] == SEC_B)
    assert b["follower_count"] == 80, "嵌套深处的用户也要抽得到"


def test_extract_cursor():
    cursor = extract_cursor(FIXTURE)
    assert cursor["cursor"] == "1700000000000"
    assert cursor["has_more"] is True


def test_extract_like_edges_from_notice():
    payload = {
        "notice_list": [
            {"id": "n1", "type": 1, "sec_uid": SEC_A, "aweme_id": "7300000000000000001"},
            {"id": "n2", "type": 1, "sec_uid": SEC_B},
            {"id": "n3", "type": 1, "sec_uid": "not-a-sec-uid", "aweme_id": "x"},
        ]
    }
    edges = extract_like_edges(payload)
    assert len(edges) == 2, "非 sec_uid 形状的必须被排除"
    assert {e["sec_uid"] for e in edges} == {SEC_A, SEC_B}


def test_parse_payload_uses_registered_parser_for_known_url():
    result = parse_payload("https://www.douyin.com/aweme/v1/web/aweme/post/?x=1", FIXTURE)
    assert result.parser_name == "douyin.user_works"
    assert len(result.works) == 2


def test_parse_payload_falls_back_to_generic_for_unknown_url():
    result = parse_payload("https://www.douyin.com/some/brand/new/api", FIXTURE)
    assert result.parser_name == "generic"
    assert len(result.works) == 2, "URL 不认识也必须能抽出数据"


def test_parse_payload_never_raises_on_garbage():
    for payload in (None, 42, "字符串", [], {}, {"a": [object()]}):
        result = parse_payload("https://x.test/aweme/post", payload)
        assert result is not None


def test_parse_payload_survives_broken_parser(monkeypatch):
    """精确解析器报错时必须回退到通用抽取，而不是中断采集。"""
    from scout.parse import registry

    def boom(url, payload):
        raise ValueError("模拟改版")

    monkeypatch.setattr(registry, "_RULES", [("boom", "aweme/post", boom)])
    result = registry.parse_payload("https://x.test/aweme/post", FIXTURE)
    assert result.parser_name == "generic"
    assert len(result.works) == 2
    assert any("回退" in n for n in result.notes)


def test_registered_patterns_present():
    names = {p["name"] for p in registered_patterns()}
    assert {"douyin.notice", "douyin.user_works", "douyin.profile"} <= names


def test_walk_helpers_are_defensive():
    assert dig({"a": {"b": {"c": 1}}}, "a", "b", "c") == 1
    assert dig({"a": 1}, "a", "b", "c") is None
    assert dig(None, "a") is None
    assert dig({"a": {"b": None}}, "a", "b", default="d") == "d"

    assert first_of({"x": "", "y": 0, "z": "hit"}, ("x", "y", "z")) == 0, "0 是有效值，不能被跳过"
    assert first_of({"x": ""}, ("x",), default="fallback") == "fallback"

    assert as_int("1,234") == 1234
    assert as_int("abc") is None
    assert as_int(True) is None, "布尔不该被当成数字"
    assert as_int(3.9) == 3

    assert looks_like_work({"aweme_id": "123", "desc": "x"}) is True
    assert looks_like_work({"aweme_id": "abc", "desc": "x"}) is False
    assert looks_like_work({"desc": "x"}) is False


def test_parse_result_merge():
    a = parse_payload("https://x.test/aweme/post", FIXTURE)
    # 用一个没有注册精确解析器的 URL，确保走通用抽取（能出作品）
    b = parse_payload("https://x.test/some/other/api", json.loads(json.dumps(FIXTURE)))
    assert len(a.works) == 2 and len(b.works) == 2
    a.merge(b)
    assert len(a.works) == 4
    assert not a.is_empty()
    assert a.summary()["works"] == 4
    assert a.raw_blob_id is None


def test_empty_payload_is_empty():
    result = parse_payload("https://x.test/aweme/post", {"status_code": 0})
    assert result.is_empty()
