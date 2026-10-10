"""通知接口解析器测试。

依据 2026-10-10 从真实归档（raw_id 407/413）校准出的结构写死。
这个解析器是整个项目的关键路径，改版时最先坏的就是它，所以必须有测试盯着。
"""

from __future__ import annotations

from scout.parse import parse_payload
from scout.parse.registry import NOTICE_TYPE_DIGG

SEC_A = "MS4wLjABAAAAaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SEC_B = "MS4wLjABAAAAbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
SEC_ME = "MS4wLjABAAAAzzzzzzzzzzzzzzzzzzzzzzzzzzzz"

NOTICE_URL = "https://www.douyin.com/aweme/v1/web/notice/?notice_group=960&count=10"

# 结构完全照抄真实响应，包括那几个坑
FIXTURE = {
    "status_code": 0,
    "notice_list": [],          # ← 空数组，读它就什么都拿不到
    "notice_list_v2": [
        {
            "nid": 7689872494865597478,
            "nid_str": "7689872494865597478",
            "type": NOTICE_TYPE_DIGG,
            "create_time": 1790437964,
            "aweme_id": "7689477790995846377",
            "user_id": "1131858773674704",
            "digg": {
                "aweme": {
                    "aweme_id": "7689477790995846377",
                    "desc": "第一条抖音 #测试",
                    "create_time": 1790346064,
                    "author": {          # ← 这是视频作者（我自己），不是点赞人
                        "uid": "1131858773674704",
                        "sec_uid": SEC_ME,
                        "nickname": "我自己",
                        "follower_count": 1,
                    },
                },
                "from_user": [           # ← 点赞人在这里
                    {
                        "uid": "76398776832",
                        "sec_uid": SEC_A,
                        "nickname": "培德娄",
                        "unique_id": "",
                        "follower_count": 61,
                        "is_verified": True,
                        "custom_verify": "",
                        "signature": "签名甲",
                    }
                ],
                "content": "",
                "merge_count": 1,
                "digg_type": 1,
                "has_digg_list": False,
            },
        },
        {
            "nid": 7689685162887808000,
            "nid_str": "7689685162887808000",
            "type": NOTICE_TYPE_DIGG,
            "create_time": 1790387964,
            "aweme_id": "7689477790995846377",
            "digg": {
                "aweme": {"aweme_id": "7689477790995846377", "desc": "第一条抖音"},
                "from_user": [
                    {"sec_uid": SEC_B, "nickname": "JJ", "unique_id": "28998945176"},
                ],
                "merge_count": 22,       # 聚合 22 人
                "has_digg_list": True,   # 但只给了 1 个
            },
        },
        {   # 关注类通知：没有 digg
            "nid": 7689790464820134962,
            "nid_str": "7689790464820134962",
            "type": 33,
            "create_time": 1790387964,
            "aweme_id": "0",
            "digg": None,
            "user": {"sec_uid": SEC_A, "nickname": "关注我的人"},
        },
    ],
    "has_more": 0,
    "max_time": 1790359807,
    "min_time": 1790345758,
}


def test_reads_notice_list_v2_not_notice_list():
    """notice_list 是空数组，必须读 notice_list_v2 —— 这是踩过的坑。"""
    result = parse_payload(NOTICE_URL, FIXTURE)
    assert FIXTURE["notice_list"] == []
    assert len(result.like_edges) == 2
    assert result.parser_name == "douyin.notice"


def test_liker_is_from_user_not_aweme_author():
    """点赞人在 digg.from_user，不是 digg.aweme.author（那是视频作者自己）。"""
    result = parse_payload(NOTICE_URL, FIXTURE)
    likers = {e["sec_uid"] for e in result.like_edges}
    assert SEC_A in likers and SEC_B in likers
    assert SEC_ME not in likers, "不能把视频作者当成点赞人"


def test_users_carry_profile_data():
    """from_user 自带画像字段，不用访问主页就能拿到。"""
    result = parse_payload(NOTICE_URL, FIXTURE)
    user_a = next(u for u in result.users if u["sec_uid"] == SEC_A)
    assert user_a["nickname"] == "培德娄"
    assert user_a["follower_count"] == 61
    assert user_a["signature"] == "签名甲"
    user_b = next(u for u in result.users if u["sec_uid"] == SEC_B)
    assert user_b["douyin_id"] == "28998945176"


def test_merge_count_and_incomplete_flag():
    """聚合条目的名单可能不全，要能标出来 —— 只有这些才值得去点开。"""
    result = parse_payload(NOTICE_URL, FIXTURE)
    by_uid = {e["sec_uid"]: e for e in result.like_edges}
    assert by_uid[SEC_A]["merge_count"] == 1
    assert by_uid[SEC_A]["has_more_likers"] is False
    assert by_uid[SEC_B]["merge_count"] == 22
    assert by_uid[SEC_B]["has_more_likers"] is True


def test_works_extracted_with_aweme_id():
    result = parse_payload(NOTICE_URL, FIXTURE)
    ids = {w["aweme_id"] for w in result.works}
    assert "7689477790995846377" in ids


def test_cursor_from_notice_fields():
    result = parse_payload(NOTICE_URL, FIXTURE)
    assert result.cursor["max_time"] == 1790359807
    assert result.cursor["min_time"] == 1790345758
    assert result.cursor["has_more"] is False


def test_follow_notice_without_digg_still_yields_user():
    """关注类通知没有 digg，但里面的人名不该浪费。"""
    result = parse_payload(NOTICE_URL, FIXTURE)
    assert SEC_A in {u["sec_uid"] for u in result.users}


def test_missing_from_user_does_not_crash():
    payload = dict(FIXTURE)
    payload["notice_list_v2"] = [{"nid_str": "1", "type": 41, "digg": {"merge_count": 5}}]
    result = parse_payload(NOTICE_URL, payload)
    assert result.like_edges == []
    assert result.users == []


def test_notice_type_maps_to_kind():
    result = parse_payload(NOTICE_URL, FIXTURE)
    kinds = {e["notice_kind"] for e in result.like_edges}
    assert "digg" in kinds


def test_emoticon_endpoint_no_longer_yields_fake_likers():
    """回归测试：表情包资源接口曾经被抽出 36 条假点赞人。"""
    url = "https://www.douyin.com/aweme/v1/web/im/resources/emoticon/trending"
    payload = {"resources": [{"sec_uid": SEC_A, "nickname": "不该被当点赞人", "id": "1"}]}
    result = parse_payload(url, payload)
    assert result.like_edges == [], "非通知接口不能产出点赞边"
