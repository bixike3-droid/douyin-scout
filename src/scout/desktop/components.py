"""Small native widgets shared by the desktop pages."""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import QStyle, QStyleOption
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .theme import icon


class ElidedLabel(QLabel):
    """Keep the full title available while painting a single fitted line."""
    def __init__(self, value="", style="", parent=None):
        super().__init__(value, parent)
        if style:
            self.setObjectName(style)
        self.setWordWrap(False)
        self.setToolTip(value)

    def setText(self, value):
        super().setText(value)
        self.setToolTip(value)

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def sizeHint(self):
        hint = super().sizeHint()
        return QSize(min(400, hint.width()), hint.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        option = QStyleOption()
        option.initFrom(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, option, painter, self)
        fitted = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.contentsRect().width())
        self.style().drawItemText(painter, self.contentsRect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                 self.palette(), self.isEnabled(), fitted, QPalette.ColorRole.WindowText)


def text(value, style="", parent=None):
    widget = QLabel(value, parent)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    if style:
        widget.setObjectName(style)
    return widget


def soft_shadow(widget, blur=32, dy=8, alpha=28):
    """统一的层次投影：卡片浮在画布上，靠柔和投影而不是重描边分层。"""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QGraphicsDropShadowEffect
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    shade = QColor(15, 18, 24)
    shade.setAlpha(alpha)
    effect.setColor(shade)
    widget.setGraphicsEffect(effect)


def card(title="", description=""):
    frame = QFrame()
    frame.setObjectName("card")
    soft_shadow(frame)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)
    if title:
        layout.addWidget(text(title, "sectionTitle"))
    if description:
        layout.addWidget(text(description, "muted"))
    return frame, layout


class MetricCard(QFrame):
    clicked = Signal()

    def __init__(self, title, note, symbol):
        super().__init__()
        self.setObjectName("card")
        soft_shadow(self)
        self.setMinimumHeight(136)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        header = QHBoxLayout()
        header.addWidget(text(title, "metricTitle"), 1)
        glyph = QLabel()
        glyph.setProperty("themeGlyph", symbol)
        glyph.setProperty("themeGlyphSize", 22)
        glyph.setPixmap(icon(symbol, size=22).pixmap(22, 22))
        header.addWidget(glyph)
        layout.addLayout(header)
        self.value = text("—", "metricValue")
        layout.addWidget(self.value)
        layout.addWidget(text(note, "metricNote"))

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class AccountAvatar(QLabel):
    """左下角账号头像：有图用图，没图用首字圆牌。"""

    def __init__(self, size=26, parent=None):
        super().__init__(parent)
        self._size = size
        self._label = ""
        self._image = None
        self.setFixedSize(size, size)
        self.setObjectName("accountAvatar")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.refresh()

    @property
    def has_image(self):
        return self._image is not None

    def set_text(self, value):
        self._label = (value or "").strip()
        if self._image is None:
            self.refresh()

    def set_image(self, path) -> bool:
        from PySide6.QtGui import QPixmap
        from .avatar import round_pixmap
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return False
        self._image = round_pixmap(pixmap, self._size)
        self.setPixmap(self._image)
        return True

    def refresh(self):
        """主题切换后占位圆牌要跟着换色。"""
        if self._image is not None:
            self.setPixmap(self._image)
            return
        from .appearance import color
        from .avatar import placeholder_pixmap
        self.setPixmap(placeholder_pixmap(self._label, self._size, color("subtle"), color("muted")))


class TaskSummary(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)
        self.rows = {}
        for state, title in [("done", "已完成"), ("pending", "待处理"), ("running", "执行中"),
                             ("failed", "失败"), ("blocked", "已暂停")]:
            row = QHBoxLayout()
            dot = QLabel()
            dot.setFixedSize(8, 8)
            dot.setObjectName("statusDot")
            dot.setProperty("status", state)
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
