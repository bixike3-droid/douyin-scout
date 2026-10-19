"""账号头像：本地缓存 + 圆形绘制。

头像 URL 来自「识别本人账号」那次请求（users.avatar_url），这里只负责
下载一次、落盘缓存、画成圆形给左下角用。下载失败不影响界面。
"""
from __future__ import annotations

from pathlib import Path
from urllib.request import Request, urlopen


def avatar_dir(root: Path) -> Path:
    folder = Path(root) / "data" / "avatars"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def avatar_path(root: Path, sec_uid: str) -> Path:
    """按 sec_uid 缓存，换号后不会串头像。"""
    safe = "".join(ch for ch in (sec_uid or "") if ch.isalnum() or ch in "-_")[:64] or "self"
    return avatar_dir(root) / f"{safe}.jpg"


def fetch_avatar(url: str, dest: Path, timeout: float = 8.0, attempts: int = 3) -> bool:
    """下载头像。抖音 CDN 偶发 IncompleteRead，所以带重试并接受已读到的部分数据。"""
    if not url:
        return False
    from http.client import IncompleteRead

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Referer": "https://www.douyin.com/",
    }
    for _ in range(max(1, attempts)):
        blob = b""
        try:
            with urlopen(Request(url, headers=headers), timeout=timeout) as response:
                blob = response.read()
        except IncompleteRead as partial:
            blob = partial.partial or b""
        except Exception:      # noqa: BLE001 —— 头像拿不到就不显示，不影响主流程
            continue
        if len(blob) > 1024:
            try:
                Path(dest).parent.mkdir(parents=True, exist_ok=True)
                Path(dest).write_bytes(blob)
                return True
            except OSError:
                return False
    return False


def round_pixmap(pixmap, size: int):
    """裁成圆形。

    注意：QPainter 在设置了 devicePixelRatio 的画布上用**逻辑坐标**，
    所以这里按 size 画圆、按 size×size 贴图，内部自动映射到 2x 像素。
    """
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QPainter, QPainterPath, QPixmap

    side = size * 2
    result = QPixmap(side, side)
    result.setDevicePixelRatio(2)
    result.fill(Qt.GlobalColor.transparent)

    # 先居中裁成正方形，再缩到目标尺寸，避免 KeepAspectRatioByExpanding 后偏移
    width, height = pixmap.width(), pixmap.height()
    edge = min(width, height)
    if edge <= 0:
        return result
    crop = QRect((width - edge) // 2, (height - edge) // 2, edge, edge)
    square = pixmap.copy(crop).scaled(side, side, Qt.AspectRatioMode.IgnoreAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)

    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    painter.setClipPath(path)
    painter.drawPixmap(QRect(0, 0, size, size), square)
    painter.end()
    return result


def placeholder_pixmap(text: str, size: int, fill: str, shade: str):
    """没有头像时画一个首字母圆牌，比空白或默认人像干净。"""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap

    side = size * 2
    result = QPixmap(side, side)
    result.setDevicePixelRatio(2)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(fill))
    painter.drawEllipse(QRectF(0, 0, size, size))
    painter.setPen(QColor(shade))
    font = QFont(painter.font())
    font.setPointSizeF(max(7.0, size * 0.42))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter,
                     (text or "?").strip()[:1].upper())
    painter.end()
    return result
