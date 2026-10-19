"""从品牌 SVG 生成程序需要的位图与 .ico（矢量为准，位图只是产物）。"""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "brand"
TARGET = ROOT / "src" / "scout" / "desktop" / "assets"
SITE = ROOT / "site" / "assets"

app = QApplication([])


def render(svg_path: Path, size: int) -> QPixmap:
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise RuntimeError(f"无法读取 SVG：{svg_path}")
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return QPixmap.fromImage(image)


def save_png(svg_path: Path, target: Path, size: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not render(svg_path, size).save(str(target), "PNG"):
        raise RuntimeError(f"写入失败：{target}")
    print("png", target.relative_to(ROOT), size)


def save_ico(svg_path: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    base = render(svg_path, 256)
    if not base.save(str(target), "ICO"):
        raise RuntimeError(f"写入失败：{target}")
    print("ico", target.relative_to(ROOT))


app_icon_svg = BRAND / "源镜_App图标.svg"
mark_svg = BRAND / "源镜_图形标志_透明底.svg"

save_png(app_icon_svg, TARGET / "brand_app.png", 256)
save_png(app_icon_svg, TARGET / "brand_app_128.png", 128)
save_png(mark_svg, TARGET / "brand_mark.png", 128)
save_ico(app_icon_svg, TARGET / "yuanjing.ico")

save_png(mark_svg, SITE / "logo-mark.png", 96)
save_ico(app_icon_svg, SITE / "app-icon.ico")

# 站点直接用矢量
(SITE / "logo-mark.svg").write_bytes(mark_svg.read_bytes())
(SITE / "app-icon.svg").write_bytes(app_icon_svg.read_bytes())
print("site svg copied")
