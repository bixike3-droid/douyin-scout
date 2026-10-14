"""Small native widgets shared by the desktop pages."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .theme import icon


def text(value, style="", parent=None):
    widget = QLabel(value, parent)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    if style:
        widget.setObjectName(style)
    return widget


def card(title="", description=""):
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)
    if title:
        layout.addWidget(text(title, "sectionTitle"))
    if description:
        layout.addWidget(text(description, "muted"))
    return frame, layout


class MetricCard(QFrame):
    def __init__(self, title, note, symbol):
        super().__init__()
        self.setObjectName("card")
        self.setMinimumHeight(136)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        header = QHBoxLayout()
        header.addWidget(text(title, "metricTitle"), 1)
        glyph = QLabel()
        glyph.setPixmap(icon(symbol, "#6887D5", 22).pixmap(22, 22))
        header.addWidget(glyph)
        layout.addLayout(header)
        self.value = text("—", "metricValue")
        layout.addWidget(self.value)
        layout.addWidget(text(note, "metricNote"))


class TaskSummary(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)
        self.rows = {}
        for state, title, color in [("done", "已完成", "#42AF94"), ("pending", "待处理", "#E7AF50"),
                                    ("running", "执行中", "#527AF2"), ("failed", "失败", "#DA7382"),
                                    ("blocked", "已暂停", "#99A6BB")]:
            row = QHBoxLayout()
            dot = QLabel()
            dot.setFixedSize(8, 8)
            dot.setStyleSheet(f"background:{color};border-radius:4px;")
            row.addWidget(dot)
            row.addWidget(text(title, "muted"), 1)
            value = text("—")
            value.setMinimumHeight(20)
            row.addWidget(value)
            layout.addLayout(row)
            self.rows[state] = value

    def update_counts(self, counts):
        for key, widget in self.rows.items():
            widget.setText(f"{int(counts.get(key, 0)):,}")
