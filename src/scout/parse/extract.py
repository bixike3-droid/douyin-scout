"""从任意 JSON 里抽出用户 / 作品 / 游标。

这是"没有 HAR 也能先跑起来"的关键：不依赖精确的接口 schema，
只按对象形状识别。等 HAR 到手后，再在 registry 里补精确解析器替换它。
**注意：通用抽取是保底手段，不是终点。** 精确解析器永远优先。
"""

from __future__ import annotations

from typing import Any

from .walk import (
    as_int,
    as_str,
    dig,
    first_of,
    iter_dicts,
    looks_like_sec_uid,
    looks_like_user,
    looks_like_work,
)

_CURSOR_KEYS = ("max_cursor", "cursor", "min_cursor", "offset", "next_cursor")
_HAS_MORE_KEYS = ("has_more", "hasMore")


def pick_avatar(node: dict) -> str:
    for key in ("avatar_larger", "avatar_medium", "avatar_thumb", "avatar_168x168", "avatar_300x300"):
        block = node.get(key)
        if isinstance(block, dict):
            urls = block.get("url_list")
            if isinstance(urls, list) and urls:
                return as_str(urls[0])
            if block.get("url"):
                return as_str(block["url"])
        if isinstance(block, str) and block:
            return block
    return ""


def extract_hashtags(node: dict) -> list[str]:
    out: list[str] = []
    for key in ("text_extra", "cha_list", "hashtags"):
        block = node.get(key)
        if not isinstance(block, list):
            continue
        for item in block:
            if isinstance(item, dict):
                name = first_of(item, ("hashtag_name", "cha_name", "name", "title"))
            else:
                name = item
            if isinstance(name, str) and name and name not in out:
                out.append(name)
    return out


def normalize_user(node: dict) -> dict[str, Any]:
    """用户对象 → 我们的字段名。缺失一律返回 None / ""，不编造。

    关于 is_verified：**不能信这个布尔字段**。
    实测 favorite/list 返回的 27 个人里 is_verified 全是 true，
    但 custom_verify / enterprise_verify_reason 全是空的 —— 显然是接口的默认值，
    不是真的"认证"。所以只在**有认证文案**时才认为已认证。
    """
    stats = node.get("stats") if isinstance(node.get("stats"), dict) else {}
    verify_text = first_of(node, ("custom_verify", "enterprise_verify_reason", "verify_info"))

    return {
        "sec_uid": as_str(node.get("sec_uid")),
        "uid": as_str(node.get("uid")),
        "douyin_id": as_str(first_of(node, ("unique_id", "short_id", "douyin_id", "display_id"))),
        "nickname": as_str(node.get("nickname")),
        "signature": as_str(first_of(node, ("signature", "signature_extra"))),
        "avatar_url": pick_avatar(node),
        "gender": as_int(node.get("gender")),
        "region": as_str(first_of(node, ("region", "country", "city", "province", "location"))),
        "ip_location": as_str(node.get("ip_location")),
        "follower_count": as_int(first_of(node, ("follower_count", "fans_count")) or stats.get("follower_count")),
        "following_count": as_int(first_of(node, ("following_count", "follow_count")) or stats.get("following_count")),
        "total_favorited": as_int(first_of(node, ("total_favorited", "favoriting_count")) or stats.get("digg_count")),
        "aweme_count": as_int(first_of(node, ("aweme_count", "video_count")) or stats.get("aweme_count")),
        "verification": as_str(verify_text),
        "is_verified": 1 if verify_text else 0,
    }


def normalize_work(node: dict) -> dict[str, Any]:
    stats = node.get("statistics") if isinstance(node.get("statistics"), dict) else {}
    video = node.get("video") if isinstance(node.get("video"), dict) else {}
    cover = video.get("cover") or video.get("origin_cover") or {}
    cover_url = ""
    if isinstance(cover, dict):
        urls = cover.get("url_list")
        cover_url = as_str(urls[0]) if isinstance(urls, list) and urls else as_str(cover.get("url"))
    music = node.get("music") if isinstance(node.get("music"), dict) else {}
    def metric(*keys):
        value = first_of(stats, keys)
        return as_int(value if value is not None else first_of(node, keys))
    return {
        "aweme_id": as_str(node.get("aweme_id") or node.get("awemeId")),
        "author_sec_uid": as_str(dig(node, "author", "sec_uid", default="")),
        "description": as_str(first_of(node, ("desc", "description", "title"))),
        "create_time": as_int(node.get("create_time")),
        "duration_ms": as_int(first_of(node, ("duration", "duration_ms"))),
        "digg_count": metric("digg_count", "like_count"),
        "comment_count": metric("comment_count"),
        "share_count": metric("share_count"),
        "collect_count": metric("collect_count"),
        "play_count": metric("play_count"),
        "music_title": as_str(music.get("title")),
        "hashtags": extract_hashtags(node),
        "cover_url": cover_url,
        "share_url": as_str(first_of(node, ("share_url", "share_info"))),
        "is_top": 1 if node.get("is_top") or node.get("is_top_show") else 0,
    }


def extract_users(payload: Any) -> list[dict[str, Any]]:
    """深度找出所有用户对象，按 sec_uid 去重（后者不覆盖前者，保留信息最全的）。"""
    best: dict[str, dict[str, Any]] = {}
    scores: dict[str, int] = {}
    for node in iter_dicts(payload):
        if not looks_like_user(node):
            continue
        record = normalize_user(node)
        sec_uid = record["sec_uid"]
        if not sec_uid:
            continue
        # 完整度打分：字段非空数量越多越好（主页资料 > 引用对象）
        score = sum(1 for v in record.values() if v not in (None, "", 0))
        if score > scores.get(sec_uid, -1):
            scores[sec_uid] = score
            best[sec_uid] = record
    return list(best.values())


def extract_works(payload: Any) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    scores: dict[str, int] = {}
    for node in iter_dicts(payload):
        if not looks_like_work(node):
            continue
        record = normalize_work(node)
        aweme_id = record["aweme_id"]
        if not aweme_id:
            continue
        score = sum(1 for v in record.values() if v not in (None, "", 0))
        if score > scores.get(aweme_id, -1):
            scores[aweme_id] = score
            best[aweme_id] = record
    return list(best.values())


def extract_like_edges(payload: Any, *, notice_id_hint: str = "") -> list[dict[str, Any]]:
    """从通知流里抽点赞人。只有 sec_uid 是硬要求，其余能取到就带上。"""
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for node in iter_dicts(payload):
        sec_uid = node.get("sec_uid")
        if not looks_like_sec_uid(sec_uid):
            continue
        aweme_id = as_str(first_of(node, ("aweme_id", "item_id", "object_id")))
        notice_id = as_str(first_of(node, ("notice_id", "id", "nid"))) or notice_id_hint
        kind = as_str(first_of(node, ("type", "notice_type", "action"))) or "digg"
        key = (sec_uid, aweme_id or notice_id)
        if key in seen:
            continue
        seen.add(key)
        edges.append(
            {
                "sec_uid": sec_uid,
                "aweme_id": aweme_id,
                "notice_id": notice_id,
                "notice_kind": kind,
            }
        )
    return edges


def extract_cursor(payload: Any) -> dict[str, Any]:
    """找出分页游标和 has_more。多层结构里取第一个命中的。

    ⚠️ 返回的键里**必须同时有 `max_cursor`**。
    踩过的坑：这里原来只返回 `cursor`，而采集器的翻页逻辑读的是 `max_cursor`，
    键名对不上 → 每页都拿到 None → 判定"到底了" → **只采第一页就停**。
    表现出来是"接口说有 33 个作品，我们只采到 17 个"，非常难察觉。
    """
    for node in iter_dicts(payload):
        cursor = first_of(node, _CURSOR_KEYS)
        has_more = first_of(node, _HAS_MORE_KEYS)
        if cursor not in (None, "", 0) or has_more is not None:
            value = as_str(cursor) if cursor is not None else ""
            if isinstance(has_more, bool):
                more = has_more
            elif isinstance(has_more, str) and has_more.lower() in ("true", "false"):
                more = has_more.lower() == "true"
            else:
                numeric = as_int(has_more)
                more = bool(numeric) if numeric in (0, 1) else None
            return {
                # 两个键都给：`cursor` 是通用名，`max_cursor` 是抖音的实际字段名，
                # 翻页逻辑两个都能读，避免再出现键名对不上的问题。
                "cursor": value,
                "max_cursor": value,
                "has_more": bool(more),
                "has_more_known": more is not None,
            }
    return {"cursor": "", "max_cursor": "", "has_more": False, "has_more_known": False}


def detect_kind(url: str) -> str:
    """判断这个响应属于哪一类。

    注意 "/im/" 曾经被误判成通知，导致表情包资源接口
    （/aweme/v1/web/im/resources/emoticon/trending）被抽出一堆假的"点赞人"。
    私信接口是 protobuf，跟点赞人毫无关系，必须分开。
    """
    u = url.lower()
    if "/notice" in u:
        return "notice"
    if "imapi" in u or "/im/" in u or "/message" in u:
        return "im"
    if "/aweme/post" in u or "aweme_list" in u:
        return "works"
    if "user/profile" in u or "/user/" in u:
        return "profile"
    if "comment" in u:
        return "comment"
    if "search" in u:
        return "search"
    return "unknown"


def extract_user(node: dict) -> dict[str, Any] | None:
    return normalize_user(node) if looks_like_user(node) else None


def extract_work(node: dict) -> dict[str, Any] | None:
    return normalize_work(node) if looks_like_work(node) else None
