"""Generate the desktop application icon using Qt's native painter."""
import os
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from scout.desktop.theme import apply_theme, icon

app = QApplication([])
apply_theme(app)
image = QPixmap(256, 256)
image.fill(Qt.GlobalColor.transparent)
painter = QPainter(image)
painter.setRenderHint(QPainter.RenderHint.Antialiasing)
painter.setPen(Qt.PenStyle.NoPen)
painter.setBrush(QColor("#191E26"))
painter.drawRoundedRect(QRectF(8, 8, 240, 240), 48, 48)
painter.drawPixmap(30, 30, icon("sparkles", "#75D8BA", 196).pixmap(196, 196))
painter.end()
target = Path(__file__).resolve().parents[1] / "src/scout/desktop/assets/yuanjing.ico"
target.parent.mkdir(parents=True, exist_ok=True)
if not image.save(str(target), "ICO"):
    raise RuntimeError("Cannot write application icon")
print(target)
