"""Generate the desktop application icon from the brand SVG."""
import os
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "brand" / "源镜_App图标.svg"
TARGET = ROOT / "src" / "scout" / "desktop" / "assets"

app = QApplication([])
renderer = QSvgRenderer(str(SOURCE))
if not renderer.isValid():
    raise RuntimeError(f"Cannot read brand svg: {SOURCE}")

image = QImage(256, 256, QImage.Format.Format_ARGB32)
image.fill(Qt.GlobalColor.transparent)
painter = QPainter(image)
painter.setRenderHint(QPainter.RenderHint.Antialiasing)
renderer.render(painter)
painter.end()

icon = QPixmap.fromImage(image)
TARGET.mkdir(parents=True, exist_ok=True)
for name in ("yuanjing.ico", "scout.ico"):
    target = TARGET / name
    if not icon.save(str(target), "ICO"):
        raise RuntimeError(f"Cannot write {target}")
    print(target)
