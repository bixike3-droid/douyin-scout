"""通用遍历与取值工具。

这些函数是解析层的地基：抖音的 JSON 结构经常变，但"安全取值 + 深度遍历"
这两件事永远需要，所以它们必须极端容错——用错类型也只会返回默认值，绝不抛异常。
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

_SEC_UID_RE = re.compile(r"^MS4wLjAB")
_MISSING = object()


def iter_dicts(node: Any) -> Iterable[dict]:
    """深度遍历任意 JSON 结构，产出所有 dict（含根）。"""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from iter_dicts(value)
    elif isinstance(node, list):
        for value in node:
            yield from iter_dicts(value)


def iter_lists(node: Any) -> Iterable[list]:
    if isinstance(node, list):
        yield node
        for value in node:
            yield from iter_lists(value)
    elif isinstance(node, dict):
        for value in node.values():
            yield from iter_lists(value)


def dig(node: Any, *path: str, default: Any = None) -> Any:
    """安全取嵌套值：dig(obj, "author", "sec_uid")。任一层缺失返回 default。"""
    cur = node
    for key in path:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur if cur is not None else default


def first_of(node: Any, keys: Sequence[str], default: Any = None) -> Any:
    """按顺序返回第一个存在且非空的键值。用于同一语义的多种字段名。"""
    if not isinstance(node, dict):
        return default
    for key in keys:
        value = node.get(key, _MISSING)
        if value is not _MISSING and value not in (None, "", [], {}):
            return value
    return default


def as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return default


def as_int(value: Any, default: int | None = None) -> int | None:
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        try:
            return int(float(text))
        except ValueError:
            return default
    return default


def looks_like_sec_uid(value: Any) -> bool:
    return isinstance(value, str) and bool(_SEC_UID_RE.match(value))


def looks_like_user(node: Any) -> bool:
    """判断一个 dict 是不是用户对象。不依赖具体接口，只看形状。"""
    if not isinstance(node, dict):
        return False
    sec_uid = node.get("sec_uid")
    if not isinstance(sec_uid, str) or not sec_uid:
        return False
    # 必须有昵称或 uid 之一，避免把只带 sec_uid 的引用对象当成完整资料
    return bool(node.get("nickname") or node.get("uid") or node.get("unique_id"))


def looks_like_work(node: Any) -> bool:
    if not isinstance(node, dict):
        return False
    aweme_id = node.get("aweme_id") or node.get("awemeId")
    if not isinstance(aweme_id, str) or not aweme_id.isdigit():
        return False
    return any(k in node for k in ("desc", "create_time", "statistics", "video", "author"))


def looks_like_like_notice(node: Any) -> bool:
    """互动通知：带 sec_uid 但没有完整资料，同时出现在通知结构里。"""
    if not isinstance(node, dict):
        return False
    return looks_like_sec_uid(node.get("sec_uid")) and bool(
        node.get("nickname") or node.get("type") or node.get("create_time")
    )
