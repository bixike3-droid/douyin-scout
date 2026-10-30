"""作品媒体：详情聚合、本机代理流、播放地址失效判定与显式保存。

设计取舍（见 docs/privacy.md）：

- **默认不落盘**：播放走本机代理，Python 带着 Referer 去取源站字节再转发，
  前端不直接接触签名地址，也就不用担心防盗链与过期地址。
- **显式保存**：只有用户点「保存到本机」才写到 `state/work-media/`，
  可随时删除、可查看占用。
- **地址会过期**：抖音的播放地址带 `x-expires`。这里只判断是否过期，
  真正的刷新（需要真实浏览器）由 Gateway 注入，保持本模块不依赖 playwright。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .db.connect import Database

AWEME_ID = re.compile(r"^\d{6,32}$")
REFERER = "https://www.douyin.com/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
CHUNK = 64 * 1024
PASS_HEADERS = ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "Last-Modified", "ETag")
LIKER_LIMIT = 30


class WorkMediaError(RuntimeError):
    """对外可展示的失败原因。"""


class WorkNotFound(WorkMediaError):
    pass


class WorkMediaBusy(WorkMediaError):
    pass


class UpstreamUnavailable(WorkMediaError):
    pass


def has_play_url(row: dict[str, Any] | None) -> bool:
    return bool(row and str(row.get("play_url") or "").strip())


def url_expired(row: dict[str, Any], *, now: float | None = None) -> bool:
    if not has_play_url(row):
        return True
    try:
        expires = int(row.get("play_url_expires") or 0)
    except (TypeError, ValueError):
        return False
    if not expires:
        return False
    return expires <= (now if now is not None else time.time())


class WorkMedia:
    def __init__(self, paths, *, opener: Callable[..., tuple[int, dict[str, str], Any]] | None = None):
        self.paths = paths
        self.folder = paths.state_dir / "work-media"
        self._opener = opener or open_upstream

    # ── 读取 ────────────────────────────────────────────────

    def row(self, aweme_id: str) -> dict[str, Any]:
        if not AWEME_ID.match(str(aweme_id or "")):
            raise WorkNotFound("作品编号无效")
        with Database.open(self.paths.db_path, read_only=True) as db:
            row = db.query_one("SELECT * FROM works WHERE aweme_id = ?", (aweme_id,))
        if row is None:
            raise WorkNotFound("作品不存在")
        return dict(row)

    def detail(self, aweme_id: str) -> dict[str, Any]:
        row = self.row(aweme_id)
        images = _images(row)
        kind = "image" if images else ("video" if has_play_url(row) else "unknown")
        total, likers = self._likers(aweme_id)
        saved = self.saved(aweme_id)
        return {
            "work": {
                "aweme_id": row["aweme_id"],
                "description": row.get("description") or "",
                "create_time": row.get("create_time"),
                "duration_ms": row.get("duration_ms") or 0,
                "play_count": row.get("play_count"),
                "digg_count": row.get("digg_count"),
                "comment_count": row.get("comment_count"),
                "share_count": row.get("share_count"),
                "collect_count": row.get("collect_count"),
                "music_title": row.get("music_title") or "",
                "hashtags": _hashtags(row),
                "share_url": row.get("share_url") or "",
                "media_kind": kind,
                "image_count": len(images),
                "is_mine": bool(row.get("is_mine")),
                "stats_fetched_at": row.get("stats_fetched_at"),
            },
            "likers": {"total": total, "items": likers},
            "saved": saved,
            "urls": {
                "media": f"/api/works/{aweme_id}/media" if kind == "video" else "",
                "cover": f"/api/works/{aweme_id}/cover",
                "images": [f"/api/works/{aweme_id}/image/{index}" for index in range(len(images))],
            },
        }

    def _likers(self, aweme_id: str) -> tuple[int, list[dict[str, Any]]]:
        with Database.open(self.paths.db_path, read_only=True) as db:
            total = int(db.scalar("SELECT COUNT(DISTINCT sec_uid) FROM like_edges WHERE aweme_id = ?", (aweme_id,), default=0))
            rows = db.rows_as_dicts(
                """
                SELECT le.sec_uid, COALESCE(u.nickname, '') AS nickname,
                       COALESCE(u.avatar_url, '') AS avatar_url, MAX(le.discovered_at) AS at
                FROM like_edges le LEFT JOIN users u ON u.sec_uid = le.sec_uid
                WHERE le.aweme_id = ?
                GROUP BY le.sec_uid ORDER BY at DESC, le.sec_uid LIMIT ?
                """,
                (aweme_id, LIKER_LIMIT),
            )
        return total, rows

    def play_url(self, aweme_id: str) -> str:
        row = self.row(aweme_id)
        if url_expired(row):
            raise UpstreamUnavailable("播放地址已过期")
        return str(row["play_url"])

    def image(self, aweme_id: str, index: int) -> str:
        return image_url(self.row(aweme_id), index)

    def cover(self, aweme_id: str) -> str:
        return cover_url(self.row(aweme_id))

    # ── 代理 ────────────────────────────────────────────────

    def open(self, url: str, range_header: str = "") -> tuple[int, dict[str, str], Any]:
        return self._opener(url, range_header)

    def fetch_bytes(self, url: str, *, limit: int = 12_000_000) -> tuple[int, str, bytes]:
        status, headers, body = self.open(url)
        try:
            data = body.read(limit) if hasattr(body, "read") else b"".join(body)
        finally:
            _close(body)
        return status, headers.get("Content-Type", ""), data

    # ── 显式保存 ────────────────────────────────────────────

    def saved(self, aweme_id: str) -> dict[str, Any] | None:
        path = self._saved_path(aweme_id)
        if path is None:
            return None
        return {"bytes": path.stat().st_size, "name": path.name}

    def _saved_path(self, aweme_id: str) -> Path | None:
        if not self.folder.is_dir():
            return None
        for path in self.folder.glob(f"{aweme_id}.*"):
            if path.is_file() and path.suffix in (".mp4", ".webm", ".mov"):
                return path
        return None

    def save(self, aweme_id: str, url: str) -> dict[str, Any]:
        self.folder.mkdir(parents=True, exist_ok=True)
        status, headers, body = self.open(url)
        if status not in (200, 206):
            _close(body)
            raise UpstreamUnavailable(f"源站返回 {status}，无法保存")
        content_type = headers.get("Content-Type", "")
        suffix = ".mp4" if "mp4" in content_type else (".webm" if "webm" in content_type else Path(url.split("?")[0]).suffix or ".mp4")
        target = self.folder / f"{aweme_id}{suffix}"
        temporary = target.with_suffix(target.suffix + ".part")
        written = 0
        try:
            with temporary.open("wb") as handle:
                while True:
                    chunk = body.read(CHUNK) if hasattr(body, "read") else b""
                    if not chunk:
                        break
                    handle.write(chunk)
                    written += len(chunk)
            temporary.replace(target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        finally:
            _close(body)
        for stale in self.folder.glob(f"{aweme_id}.*"):
            if stale != target and stale.suffix in (".mp4", ".webm", ".mov"):
                stale.unlink(missing_ok=True)
        return {"bytes": written, "name": target.name}

    def forget(self, aweme_id: str) -> bool:
        path = self._saved_path(aweme_id)
        if path is None:
            return False
        path.unlink(missing_ok=True)
        return True

    def usage(self) -> dict[str, Any]:
        count = 0
        total = 0
        if self.folder.is_dir():
            for path in self.folder.iterdir():
                if path.is_file():
                    count += 1
                    total += path.stat().st_size
        return {"files": count, "bytes": total}

    def clear(self) -> dict[str, Any]:
        removed = 0
        freed = 0
        if self.folder.is_dir():
            for path in self.folder.iterdir():
                if path.is_file():
                    freed += path.stat().st_size
                    path.unlink(missing_ok=True)
                    removed += 1
        return {"files": removed, "bytes": freed}


# ── 源站 ────────────────────────────────────────────────────


def open_upstream(url: str, range_header: str = "") -> tuple[int, dict[str, str], Any]:
    """带 Referer 取源站字节。返回 (状态码, 头, 可读流)。"""
    headers = {"User-Agent": USER_AGENT, "Referer": REFERER, "Accept": "*/*"}
    if range_header:
        headers["Range"] = range_header
    try:
        response = urlopen(Request(url, headers=headers), timeout=30)
    except HTTPError as exc:
        return exc.code, {key: value for key, value in (exc.headers or {}).items() if key in PASS_HEADERS}, iter(())
    except (URLError, TimeoutError, OSError) as exc:
        raise UpstreamUnavailable(f"源站不可达：{exc}") from exc
    kept = {key: value for key, value in response.headers.items() if key in PASS_HEADERS}
    return response.status, kept, response


def download(url: str, dest: Path, *, limit: int = 250_000_000) -> int:
    """把源站视频完整写到 dest（先写 .part 再替换），返回字节数。"""
    status, headers, body = open_upstream(url)
    if status not in (200, 206):
        _close(body)
        raise UpstreamUnavailable(f"视频源返回 {status}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    written = 0
    try:
        with part.open("wb") as handle:
            while True:
                chunk = body.read(CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
                written += len(chunk)
                if written > limit:
                    raise UpstreamUnavailable("视频超过 250MB，暂不处理")
        part.replace(dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    finally:
        _close(body)
    return written


def _close(body: Any) -> None:
    close = getattr(body, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def chunks(body: Any) -> Iterator[bytes]:
    try:
        while True:
            data = body.read(CHUNK)
            if not data:
                break
            yield data
    finally:
        _close(body)


def _images(row: dict[str, Any]) -> list[str]:
    try:
        value = json.loads(row.get("images_json") or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def _hashtags(row: dict[str, Any]) -> list[str]:
    try:
        value = json.loads(row.get("hashtags_json") or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()][:12]


def image_url(row: dict[str, Any], index: int) -> str:
    images = _images(row)
    if index < 0 or index >= len(images):
        raise WorkNotFound("图片不存在")
    return images[index]


def cover_url(row: dict[str, Any]) -> str:
    images = _images(row)
    if images:
        return images[0]
    value = str(row.get("cover_url") or "").strip()
    if not value:
        raise WorkNotFound("没有封面")
    return value
