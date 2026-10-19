"""品牌资源：统一从这里取 logo，读不到就退回原来的矢量图标。

品牌源文件在仓库根目录 `brand/`（SVG 为准），由 `scripts/build_brand_assets.py`
生成 `assets/` 下的 PNG/ICO，运行时只读产物，不做矢量渲染。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon, QPixmap

ASSETS = Path(__file__).resolve().parent / "assets"
APP_ICON = ASSETS / "yuanjing.ico"
APP_PNG = ASSETS / "brand_app.png"
MARK_PNG = ASSETS / "brand_mark.png"


def app_icon() -> QIcon:
    """窗口/任务栏图标：优先 ico（多尺寸），其次 256 PNG，最后退回旧图标。"""
    for path in (APP_ICON, APP_PNG):
        if path.exists():
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon
    from .theme import icon as vector_icon
    return vector_icon("sparkles", "#007AFF", 32)


def brand_pixmap(size: int = 28, *, mark: bool = True) -> QPixmap | None:
    """品牌图形（默认透明底的图形标志，用于标题栏/启动页）。"""
    path = MARK_PNG if mark else APP_PNG
    if not path.exists():
        return None
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None
    from PySide6.QtCore import Qt
    return pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
