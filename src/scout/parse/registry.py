"""解析器注册表。

规则：**按 URL 匹配的精确解析器优先，通用抽取器兜底。**

这样安排的好处：
- 抖音改版时，只需要在 parse/ 里加/改一个精确解析器；
- 在新接口还没摸清 schema 之前，通用抽取器照样能出数据，不会卡住整个流程；
- 采集层完全不需要知道解析细节。
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any, Callable

from .extract import (
    detect_kind,
    extract_cursor,
    extract_like_edges,
    extract_users,
    extract_works,
)


@dataclass
class ParseResult:
    url: str = ""
    kind: str = "unknown"
    users: list[dict[str, Any]] = field(default_factory=list)
    works: list[dict[str, Any]] = field(default_factory=list)
    like_edges: list[dict[str, Any]] = field(default_factory=list)
    # 评论：每条必须带 aweme_id（归口约定，不留无主数据）。
    comments: list[dict[str, Any]] = field(default_factory=list)
    # 每条通知的元信息（哪个作品、聚合了多少人、名单是否完整）。
    # 用来把 DOM 上第 N 个「等 M 人赞了…」映射到具体作品。
    notices: list[dict[str, Any]] = field(default_factory=list)
    cursor: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    raw_blob_id: int | None = None
    parser_name: str = ""

    def is_empty(self) -> bool:
        return not (self.users or self.works or self.like_edges or self.comments)

    def merge(self, other: "ParseResult") -> "ParseResult":
        self.users.extend(other.users)
        self.works.extend(other.works)
        self.like_edges.extend(other.like_edges)
        self.comments.extend(other.comments)
        self.notices.extend(other.notices)
        self.notes.extend(other.notes)
        if other.cursor:
            self.cursor = other.cursor
        if other.raw_blob_id:
            self.raw_blob_id = other.raw_blob_id
        return self

    def summary(self) -> dict[str, Any]:
        return {
            "url": self.url[:200],
            "kind": self.kind,
            "parser": self.parser_name,
            "users": len(self.users),
            "works": len(self.works),
            "like_edges": len(self.like_edges),
            "comments": len(self.comments),
            "notices": len(self.notices),
            "cursor": self.cursor,
            "notes": self.notes[:5],
            "raw_blob_id": self.raw_blob_id,
        }


ParserFn = Callable[[str, Any], ParseResult]
_RULES: list[tuple[str, str, ParserFn]] = []


def parser(name: str, *patterns: str) -> Callable[[ParserFn], ParserFn]:
    """把一个解析函数注册到若干 URL 模式上。"""

    def decorator(fn: ParserFn) -> ParserFn:
        for pattern in patterns:
            _RULES.append((name, pattern, fn))
        return fn

    return decorator


def registered_patterns() -> list[dict[str, str]]:
    return [{"name": n, "pattern": p} for n, p, _ in _RULES]


def _pick(url: str) -> tuple[str, ParserFn] | None:
    for name, pattern, fn in _RULES:
        if fnmatch.fnmatch(url, pattern) or pattern in url:
            return name, fn
    return None


def generic_parse(url: str, payload: Any, *, raw_blob_id: int | None = None) -> ParseResult:
    """与 schema 无关的兜底解析：按对象形状识别，尽量把东西捞出来。

    注意：**只有通知类响应才抽点赞边**。早期版本对所有 unknown 都抽，
    结果表情包资源接口被抽出 36 条假"点赞人" —— 宁可少抽，不可脏数据。
    """
    result = ParseResult(url=url, kind=detect_kind(url), raw_blob_id=raw_blob_id)
    try:
        result.users = extract_users(payload)
    except Exception as exc:
        result.notes.append(f"extract_users 失败：{exc}")
    try:
        result.works = extract_works(payload)
    except Exception as exc:
        result.notes.append(f"extract_works 失败：{exc}")
    if result.kind == "notice":
        try:
            result.like_edges = extract_like_edges(payload)
        except Exception as exc:
            result.notes.append(f"extract_like_edges 失败：{exc}")
    try:
        result.cursor = extract_cursor(payload)
    except Exception as exc:
        result.notes.append(f"extract_cursor 失败：{exc}")
    result.parser_name = "generic"
    return result


def parse_payload(
    url: str,
    payload: Any,
    *,
    raw_blob_id: int | None = None,
    force_generic: bool = False,
) -> ParseResult:
    """解析入口。任何异常都被吞掉并记入 notes——解析绝不允许打断采集。"""
    if force_generic or payload is None:
        return generic_parse(url, payload, raw_blob_id=raw_blob_id)

    picked = _pick(url)
    if picked is None:
        return generic_parse(url, payload, raw_blob_id=raw_blob_id)

    name, fn = picked
    try:
        result = fn(url, payload)
        result.url = result.url or url
        result.raw_blob_id = raw_blob_id
        result.parser_name = name
        return result
    except Exception as exc:
        fallback = generic_parse(url, payload, raw_blob_id=raw_blob_id)
        fallback.notes.append(f"精确解析器 {name} 失败（{exc}），已回退到通用抽取")
        return fallback


# ── 内置精确解析器 ──────────────────────────────────────────
#
# 下面是**实测校准过**的解析器（依据真实归档 raw_id 407）。
# 抖音改版时只改这里，采集层一行不动。


NOTICE_TYPE_DIGG = 41  # 点赞通知（实测值；31=评论类 33=关注类，尚未逐一确认）


@parser("douyin.notice", "/aweme/v1/web/notice")
def _parse_notice(url: str, payload: Any) -> ParseResult:
    """解析互动消息列表。

    实测结构（2026-10-10 校准）::

        {
          "notice_list":    [],              ← 空的，别读它
          "notice_list_v2": [ {              ← 数据在这里
              "nid_str": "...", "type": 41, "aweme_id": "...", "create_time": ...,
              "digg": {
                  "aweme":      { 被赞的作品完整对象 },
                  "from_user":  [ { sec_uid, uid, nickname, follower_count, ... } ],
                  "content":    "",
                  "merge_count": 22,          ← 这条通知聚合了多少人
                  "has_digg_list": true,      ← true 表示 from_user 只给了一部分
              }
          } ],
          "has_more": 0, "max_time": ..., "min_time": ...
        }

    关键点：**点赞人在 digg.from_user，不是 digg.aweme.author**（后者是视频作者，也就是你自己）。
    早期通用抽取器就把作者当成了点赞人。
    """
    from .extract import normalize_user, normalize_work

    result = ParseResult(url=url, kind="notice")
    if not isinstance(payload, dict):
        return result

    items = payload.get("notice_list_v2") or payload.get("notice_list") or []
    if not isinstance(items, list):
        return result

    for item in items:
        if not isinstance(item, dict):
            continue
        notice_type = item.get("type")
        nid = str(item.get("nid_str") or item.get("nid") or "")
        created = item.get("create_time")

        digg = item.get("digg") if isinstance(item.get("digg"), dict) else {}

        # 被赞的作品：优先取 digg.aweme 的完整对象（字段最全）
        aweme = digg.get("aweme") if isinstance(digg.get("aweme"), dict) else None
        aweme_id = ""
        if aweme:
            work = normalize_work(aweme)
            aweme_id = work.get("aweme_id") or ""
            if aweme_id:
                result.works.append(work)
        if not aweme_id:
            aweme_id = str(item.get("aweme_id") or "")
            if aweme_id in ("0", "None"):
                aweme_id = ""

        merge_count = digg.get("merge_count")
        has_more_likers = bool(digg.get("has_digg_list"))

        # 点赞人
        from_users = digg.get("from_user")
        if not isinstance(from_users, list):
            from_users = []

        given = 0
        for raw_user in from_users:
            if not isinstance(raw_user, dict):
                continue
            record = normalize_user(raw_user)
            sec_uid = record.get("sec_uid")
            if not sec_uid:
                continue
            given += 1
            result.users.append(record)
            result.like_edges.append(
                {
                    "sec_uid": sec_uid,
                    "aweme_id": aweme_id,
                    "notice_id": nid,
                    "notice_kind": "digg" if notice_type == NOTICE_TYPE_DIGG else f"type{notice_type}",
                    "merge_count": merge_count,
                    "has_more_likers": has_more_likers,
                    "notice_type": notice_type,
                    "discovered_at": None,
                    "source_url": url,
                }
            )

        if given:
            result.notices.append(
                {
                    "notice_id": nid,
                    "type": notice_type,
                    "aweme_id": aweme_id,
                    "merge_count": merge_count,
                    "has_more_likers": has_more_likers,
                    "likers_given": given,
                }
            )

        # 关注类通知（digg 为空）里的人名也别浪费
        if not from_users:
            for key in ("user", "from_user", "fans"):
                other = item.get(key)
                if isinstance(other, dict):
                    record = normalize_user(other)
                    if record.get("sec_uid"):
                        result.users.append(record)
                elif isinstance(other, list):
                    for raw_user in other:
                        if isinstance(raw_user, dict):
                            record = normalize_user(raw_user)
                            if record.get("sec_uid"):
                                result.users.append(record)

    result.cursor = {
        "cursor": str(payload.get("max_time") or ""),
        "min_time": payload.get("min_time"),
        "max_time": payload.get("max_time"),
        "has_more": extract_cursor(payload)["has_more"],
        "has_more_known": extract_cursor(payload)["has_more_known"],
        "notice_group": payload.get("notice_group"),
    }
    if not result.like_edges and not result.users:
        result.notes.append(
            "notice 接口返回里没有解析出点赞人；检查 notice_list_v2 / digg.from_user 是否改名"
        )
    return result


@parser("douyin.likers", "/aweme/v1/web/favorite/list")
def _parse_likers(url: str, payload: Any) -> ParseResult:
    """解析「某作品的完整点赞人列表」。

    这是**最关键的一个接口**，实测（2026-10-10 校准）::

        GET /aweme/v1/web/favorite/list/?item_id=<AWEME_ID>&count=50&max_cursor=0

        {
          "status_code": 0,
          "user_list": [ { sec_uid, uid, nickname, signature, follower_count,
                           aweme_count, total_favorited, location, unique_id,
                           is_verified, custom_verify, avatar_larger, ... } ],
          "max_cursor": ..., "min_cursor": ..., "has_more": false,
          "favorite_list_text": "谁可以查看我作品下的点赞"
        }

    名字容易误导：`favorite` 在这里是"点赞"，不是"收藏"。
    它的 user_list 就是**点赞过这个作品的完整名单**（每条用户对象都是一个完整主页）。

    而且实测**不需要 a_bogus 签名** —— 用浏览器会话直接 fetch 就返回 200 和全部数据。
    所以它既能拿全名单，又能拿到画像字段，还不用挨个访问主页。
    """
    from .extract import normalize_user
    from urllib.parse import parse_qs, urlparse

    result = ParseResult(url=url, kind="likers")
    if not isinstance(payload, dict):
        return result

    try:
        item_id = (parse_qs(urlparse(url).query).get("item_id") or [""])[0]
    except Exception:
        item_id = ""

    users = payload.get("user_list")
    if not isinstance(users, list):
        result.notes.append("favorite/list 里没有 user_list，接口结构可能变了")
        return result

    for raw in users:
        if not isinstance(raw, dict):
            continue
        record = normalize_user(raw)
        sec_uid = record.get("sec_uid")
        if not sec_uid:
            continue
        result.users.append(record)
        if item_id:
            result.like_edges.append(
                {
                    "sec_uid": sec_uid,
                    "aweme_id": item_id,
                    # 用 api: 前缀把"接口拿到的完整名单"和"通知流里的预览"区分开，
                    # 这样 seeds 判断"这个作品的名单是否已经拿全"才有依据。
                    "notice_id": f"api:{item_id}",
                    "notice_kind": "digg",
                    "has_more_likers": False,
                    "source_url": url,
                }
            )

    result.cursor = {
        "cursor": str(payload.get("max_cursor") or ""),
        "min_cursor": payload.get("min_cursor"),
        "max_cursor": payload.get("max_cursor"),
        "has_more": bool(payload.get("has_more")),
    }
    if not result.users:
        result.notes.append(
            "user_list 为空 —— 可能该作品没人点赞，或隐私设置为「谁可以查看我作品下的点赞」不允许"
        )
    return result


@parser("douyin.user_works", "/aweme/v1/web/aweme/post", "aweme/post")
def _parse_user_works(url: str, payload: Any) -> ParseResult:
    """解析某用户的作品列表。

    ⚠️ **只读 `aweme_list`，绝不做递归扫描。**

    踩过的大坑（2026-10-10）：这里原来调的是 `extract_works(payload)`，
    那个函数会**递归遍历整个响应的每一层**，把任何"长得像作品"的对象都收进来。
    结果：抖音在响应里塞的推广/推荐位视频（别人家的、动辄百万赞）也被当成
    「这个人的作品」收了进来，并被 `link_listings` 关联到这个用户名下。

    表现：一个 98 粉丝的号，页面上挂出 178 万赞的视频。用户一眼就看出不对。

    所以现在：
    1. 显式只取 `aweme_list`
    2. **按作者过滤** —— 只有 author.sec_uid 和请求的 sec_user_id 一致才收
       （抖音偶尔会把「推荐」混进 aweme_list，这层过滤兜住）
    """
    from .extract import extract_cursor, extract_users, looks_like_work, normalize_work
    from urllib.parse import parse_qs, urlparse

    result = ParseResult(url=url, kind="works")

    try:
        asked = (parse_qs(urlparse(url).query).get("sec_user_id") or [""])[0]
    except Exception:
        asked = ""

    raw = payload.get("aweme_list") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        result.notes.append("响应里没有 aweme_list，接口结构可能变了")
        result.cursor = extract_cursor(payload)
        return result

    dropped = 0
    for node in raw:
        if not isinstance(node, dict) or not looks_like_work(node):
            continue
        record = normalize_work(node)
        if not record.get("aweme_id"):
            continue
        # 第二层防护：作者必须是本人
        author = record.get("author_sec_uid") or ""
        if asked and author and author != asked:
            dropped += 1
            continue
        result.works.append(record)

    if dropped:
        result.notes.append(
            f"丢掉了 {dropped} 条作者不是本人的作品（响应里混进来的推荐/推广位）"
        )

    result.users = extract_users(payload)
    result.cursor = extract_cursor(payload)
    return result


@parser("douyin.profile", "/aweme/v1/web/user/profile", "user/profile")
def _parse_profile(url: str, payload: Any) -> ParseResult:
    result = ParseResult(url=url, kind="profile")
    result.users = extract_users(payload)
    return result


@parser("douyin.comments", "/aweme/v1/web/comment/list")
def _parse_comments(url: str, payload: Any) -> ParseResult:
    """解析作品评论区（/aweme/v1/web/comment/list/）。

    第一版按公开 web 结构实现（2026-10-17）::

        { "comments": [ { "cid", "text", "aweme_id", "create_time",
                           "digg_count", "reply_comment_total", "user": {...} } ],
          "cursor": 20, "has_more": 1, "total": 41 }

    尚未用真实登录账号核验；真机字段若变化，在这里改解析器即可，
    采集层不感知。评论一律带 aweme_id（归口约定）。
    """
    from .extract import normalize_user
    from urllib.parse import parse_qs, urlparse

    result = ParseResult(url=url, kind="comments")
    if not isinstance(payload, dict):
        return result

    try:
        aweme_id = (parse_qs(urlparse(url).query).get("aweme_id") or [""])[0]
    except Exception:
        aweme_id = ""

    items = payload.get("comments")
    if not isinstance(items, list):
        result.notes.append("comment/list 里没有 comments，接口结构可能变了")
        return result

    for raw in items:
        if not isinstance(raw, dict):
            continue
        comment_id = str(raw.get("cid") or raw.get("comment_id") or "")
        if not comment_id:
            continue
        user_payload = raw.get("user") if isinstance(raw.get("user"), dict) else {}
        record = normalize_user(user_payload) if user_payload else {}
        sec_uid = record.get("sec_uid") or str(raw.get("sec_uid") or "")
        if record.get("sec_uid"):
            result.users.append(record)
        result.comments.append(
            {
                "comment_id": comment_id,
                "aweme_id": aweme_id or str(raw.get("aweme_id") or ""),
                "sec_uid": sec_uid,
                "text": str(raw.get("text") or "").strip(),
                "digg_count": raw.get("digg_count"),
                "reply_count": raw.get("reply_comment_total", raw.get("reply_count")),
                "create_time": raw.get("create_time"),
            }
        )

    result.cursor = {
        "cursor": payload.get("cursor"),
        "has_more": bool(payload.get("has_more")),
        "total": payload.get("total"),
    }
    if not result.comments:
        result.notes.append("comment/list 没解析出评论；检查 comments / user 字段是否改名")
    return result
