"""通用工具：时间、JSON、哈希、文本。核心模块不依赖第三方库。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

_FALLBACK_TZ = timezone(timedelta(hours=8), name="UTC+08:00")


def local_tz(name: str = "Asia/Shanghai"):
    """取时区；Windows 缺 tz 数据库时退化为固定 +08:00，绝不抛错。"""
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return _FALLBACK_TZ


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    """UTC ISO8601，秒精度，带 Z。数据库里所有时间戳都用这个格式。"""
    dt = dt or utcnow()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def local_day(tz_name: str = "Asia/Shanghai", dt: datetime | None = None) -> str:
    """本地日期 YYYY-MM-DD。配额账本按这个分桶。"""
    dt = dt or utcnow()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(local_tz(tz_name)).strftime("%Y-%m-%d")


def local_hm(ts_epoch: int, tz_name: str = "Asia/Shanghai") -> int:
    """把秒级时间戳换算成本地小时（0-23），用于活跃时段分析。"""
    dt = datetime.fromtimestamp(int(ts_epoch), tz=timezone.utc).astimezone(local_tz(tz_name))
    return dt.hour


def dumps(obj: Any) -> str:
    """稳定序列化：键排序 + 不转义中文，便于比对和人工排查。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def loads(text: str | bytes | None, default: Any = None) -> Any:
    if text is None:
        return default
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8", errors="replace")
        except Exception:
            return default
    try:
        return json.loads(text)
    except Exception:
        return default


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_SAFE = re.compile(r"[^0-9A-Za-z._-]+")


def safe_filename(text: str, *, max_len: int = 60) -> str:
    name = _SAFE.sub("_", text).strip("_")
    return (name or "unnamed")[:max_len]


def truncate(text: str | None, limit: int = 200) -> str:
    if not text:
        return ""
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"
