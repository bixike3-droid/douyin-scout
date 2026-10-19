"""视频缓存：带 Referer 下载 + LRU 清理。

设计取舍：
- 只有点了播放才下载，浏览热点不产生缓存；
- 链接是抖音签名地址（会过期），下到本地后不受影响，所以缓存有意义；
- 清理三层：容量上限（默认 500MB，超限降到 80%）、7 天未访问、手动清空。
"""
from __future__ import annotations

import time
from http.client import IncompleteRead
from pathlib import Path
from urllib.request import Request, urlopen

MAX_AGE_DAYS = 7
DEFAULT_LIMIT_MB = 500
KEEP_RATIO = 0.8
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Referer": "https://www.douyin.com/",
}


def media_dir(root) -> Path:
    folder = Path(root) / "data" / "media"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def video_path(root, aweme_id: str) -> Path:
    safe = "".join(ch for ch in str(aweme_id) if ch.isdigit()) or "unknown"
    return media_dir(root) / f"{safe}.mp4"


def image_path(root, aweme_id: str, index: int) -> Path:
    safe = "".join(ch for ch in str(aweme_id) if ch.isdigit()) or "unknown"
    return media_dir(root) / f"{safe}_{index:02d}.jpg"


def download_file(url: str, dest: Path, timeout: float = 30.0, attempts: int = 2) -> bool:
    """通用下载（视频 / 图片），同样带 Referer 与重试。"""
    if not url:
        return False
    for _ in range(max(1, attempts)):
        blob = b""
        try:
            with urlopen(Request(url, headers=_HEADERS), timeout=timeout) as response:
                blob = response.read()
        except IncompleteRead as partial:
            blob = partial.partial or b""
        except Exception:      # noqa: BLE001
            continue
        if len(blob) > 1024:
            try:
                Path(dest).parent.mkdir(parents=True, exist_ok=True)
                Path(dest).write_bytes(blob)
                return True
            except OSError:
                return False
    return False


def download_video(url: str, dest: Path, timeout: float = 30.0, attempts: int = 2) -> bool:
    """下载 mp4。CDN 偶发截断，接受已读到的部分数据并重试一次。"""
    if not url:
        return False
    for _ in range(max(1, attempts)):
        blob = b""
        try:
            with urlopen(Request(url, headers=_HEADERS), timeout=timeout) as response:
                blob = response.read()
        except IncompleteRead as partial:
            blob = partial.partial or b""
        except Exception:      # noqa: BLE001 —— 下载失败由上层提示，不抛给界面
            continue
        if len(blob) > 4096:
            try:
                Path(dest).parent.mkdir(parents=True, exist_ok=True)
                Path(dest).write_bytes(blob)
                return True
            except OSError:
                return False
    return False


def used_bytes(root) -> int:
    total = 0
    for pattern in ("*.mp4", "*.jpg"):
        for path in media_dir(root).glob(pattern):
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total


def prune(root, limit_mb: int = DEFAULT_LIMIT_MB, max_age_days: int = MAX_AGE_DAYS) -> int:
    """按「过期 → 超容量」两步清；limit_mb<=0 表示不缓存，全部删除。

    返回删除的字节数。
    """
    files: list[tuple[float, int, Path]] = []
    for pattern in ("*.mp4", "*.jpg"):
        for path in media_dir(root).glob(pattern):
            try:
                info = path.stat()
            except OSError:
                continue
            # Windows 上 atime 常不更新，取 atime/mtime 里较新的那个
            stamp = max(info.st_atime, info.st_mtime)
            files.append((stamp, info.st_size, path))

    removed = 0
    now = time.time()
    survivors: list[tuple[float, int, Path]] = []
    for stamp, size, path in files:
        expired = max_age_days > 0 and (now - stamp) > max_age_days * 86400
        over = limit_mb <= 0
        if expired or over:
            try:
                path.unlink()
                removed += size
                continue
            except OSError:
                pass
        survivors.append((stamp, size, path))

    total = sum(size for _, size, _ in survivors)
    limit = limit_mb * 1024 * 1024
    if limit > 0 and total > limit:
        target = int(limit * KEEP_RATIO)
        for stamp, size, path in sorted(survivors):
            if total <= target:
                break
            try:
                path.unlink()
                total -= size
                removed += size
            except OSError:
                continue
    return removed


def clear(root) -> int:
    return prune(root, limit_mb=0)


def touch(root, aweme_id: str) -> None:
    """播放一次就刷新访问时间，LRU 才不会把常用的删掉。"""
    path = video_path(root, aweme_id)
    try:
        if path.exists():
            now = time.time()
            import os
            os.utime(path, (now, now))
    except OSError:
        pass
