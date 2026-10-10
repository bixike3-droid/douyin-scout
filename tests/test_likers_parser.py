"""点赞人接口解析器测试 —— 这是整个项目最关键的一个接口。

    GET /aweme/v1/web/favorite/list/?item_id=<AWEME_ID>&count=50&max_cursor=0

实测（2026-10-10）：一次返回该作品的完整点赞人名单，每人带完整主页数据，
而且**不需要 a_bogus 签名**（用浏览器会话直接 fetch 就 200）。
"""

from __future__ import annotations

from scout.parse import parse_payload

SEC_A = "MS4wLjABAAAAaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SEC_B = "MS4wLjABAAAAbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
ITEM = "7689477790995846377"
URL = (
    "https://www.douyin.com/aweme/v1/web/favorite/list/"
    f"?device_platform=webapp&aid=6383&item_id={ITEM}&count=50&max_cursor=0"
)

FIXTURE = {
    "status_code": 0,
    "user_list": [
        {
            "uid": "76398776832",
            "sec_uid": SEC_A,
            "short_id": "1385159080",
            "unique_id": "jialei",
            "nickname": "培德娄",
            "signature": "爱到白头偕老",
            "follower_count": 61,
            "following_count": 876,
            "aweme_count": 12,
            "total_favorited": 340,
            # 实测这个布尔在 favorite/list 里对所有人都是 true，不能信
            "is_verified": True,
            "custom_verify": "",
            "location": "CN",
            "avatar_larger": {"url_list": ["https://p3-pc.douyinpic.com/a.jpeg"]},
        },
        {
            "uid": "1",
            "sec_uid": SEC_B,
            "nickname": "企业号",
            "follower_count": 9999,
            "is_verified": True,
            "custom_verify": "某某公司官方账号",
        },
    ],
    "max_cursor": 1790359806000,
    "min_cursor": 1790437963000,
    "has_more": False,
    "favorite_list_text": "谁可以查看我作品下的点赞",
}


def test_parses_full_user_list():
    result = parse_payload(URL, FIXTURE)
    assert result.parser_name == "douyin.likers"
    assert len(result.users) == 2
    assert len(result.like_edges) == 2


def test_carries_full_profile_fields():
    """这个接口一次给全画像数据，不用挨个访问主页。"""
    result = parse_payload(URL, FIXTURE)
    u = next(x for x in result.users if x["sec_uid"] == SEC_A)
    assert u["nickname"] == "培德娄"
    assert u["signature"] == "爱到白头偕老"
    assert u["follower_count"] == 61
    assert u["following_count"] == 876
    assert u["aweme_count"] == 12
    assert u["douyin_id"] == "jialei"
    assert u["avatar_url"].startswith("https://")


def test_item_id_from_url_lands_on_edges():
    result = parse_payload(URL, FIXTURE)
    assert all(e["aweme_id"] == ITEM for e in result.like_edges)


def test_edges_use_api_prefix_so_reseeding_is_idempotent():
    """notice_id 用 api: 前缀，works.need_likers 靠它判断"已经拿全了"。"""
    result = parse_payload(URL, FIXTURE)
    assert all(e["notice_id"] == f"api:{ITEM}" for e in result.like_edges)


def test_is_verified_requires_verification_text():
    """is_verified 布尔在这个接口里不可靠（27/27 全是 true）。

    只有 custom_verify 这种文案非空才算真的认证。
    """
    result = parse_payload(URL, FIXTURE)
    by_uid = {u["sec_uid"]: u for u in result.users}
    assert by_uid[SEC_A]["is_verified"] == 0, "只有布尔字段，不算认证"
    assert by_uid[SEC_B]["is_verified"] == 1, "有认证文案才算"
    assert by_uid[SEC_B]["verification"] == "某某公司官方账号"


def test_cursor_and_has_more():
    result = parse_payload(URL, FIXTURE)
    assert result.cursor["has_more"] is False
    assert result.cursor["max_cursor"] == 1790359806000


def test_empty_user_list_is_empty_result():
    result = parse_payload(URL, {"status_code": 0, "user_list": []})
    assert result.is_empty()
    assert any("user_list 为空" in n for n in result.notes)


def test_missing_user_list_reports_structure_change():
    result = parse_payload(URL, {"status_code": 0, "data": []})
    assert result.is_empty()
    assert any("结构可能变了" in n for n in result.notes)


def test_not_logged_in_response_does_not_crash():
    """匿名态调这个接口会返回 status_code=8「用户未登录」。"""
    result = parse_payload(URL, {"status_code": 8, "status_msg": "用户未登录"})
    assert result.is_empty()
    assert result.users == []
