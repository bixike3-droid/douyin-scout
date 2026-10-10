"""解析层：把原始响应变成结构化记录。

设计要点（这条决定了项目的长期可维护性）：
**采集与解析解耦，解析器必须容错。**
抖音改版只影响 parse/，collect/ 不动；而且解析失败绝不抛异常中断采集，
只记 notes 并把原始响应留在归档里，随时可以回放重解。
"""

from .extract import detect_kind, extract_cursor, extract_user, extract_work
from .registry import ParseResult, parse_payload, parser, registered_patterns
from .walk import dig, first_of, iter_dicts, looks_like_sec_uid

__all__ = [
    "ParseResult",
    "parse_payload",
    "parser",
    "registered_patterns",
    "detect_kind",
    "extract_user",
    "extract_work",
    "extract_cursor",
    "dig",
    "first_of",
    "iter_dicts",
    "looks_like_sec_uid",
]
