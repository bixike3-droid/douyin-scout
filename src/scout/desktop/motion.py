"""Small native transitions; never manufacture operation progress."""
from PySide6.QtCore import Qt, Property, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget, QFrame, QPushButton, QVBoxLayout, QHBoxLayout, QGraphicsOpacityEffect, QSizePolicy
from .components import text
from .appearance import color


class ActivityDot(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(16, 16)
        self._strength = 1.0
        self.running = False
        self.motion_enabled = True
        self.animation = QPropertyAnimation(self, b"strength", self)
        self.animation.setStartValue(0.25)
        self.animation.setEndValue(1.0)
        self.animation.setDuration(850)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.animation.setLoopCount(-1)

    def get_strength(self):
        return self._strength

    def set_strength(self, value):
        self._strength = value
        self.update()

    strength = Property(float, get_strength, set_strength)

    def set_running(self, running):
        self.running = running
        self.animation.stop()
        self.set_strength(1.0)
        if running and self.motion_enabled:
            self.animation.start()
        self.update()

    def set_motion(self, enabled):
        self.motion_enabled = enabled
        self.set_running(self.running)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        shade = QColor(color("accent" if self.running else "faint"))
        shade.setAlphaF(self._strength)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shade)
        painter.drawEllipse(4, 4, 8, 8)


class Disclosure(QFrame):
    def __init__(self, title, subtitle, *, expanded=False):
        super().__init__()
        self.setObjectName("stageCard")
        self.expanded = expanded
        self.motion_enabled = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        self.toggle = QPushButton(title + "    ›")
        self.toggle.setObjectName("stageToggle")
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.clicked.connect(self.flip)
        header = QHBoxLayout()
        header.setSpacing(14)
        header.addWidget(self.toggle)
        self.subtitle = text(subtitle, "muted")
        header.addWidget(self.subtitle, 1)
        layout.addLayout(header)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(9)
        layout.addWidget(self.body)
        self.animation = QPropertyAnimation(self.body, b"maximumHeight", self)
        self.animation.setDuration(190)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self._finished)
        self.body.setMaximumHeight(16777215 if expanded else 0)
        self.body.setVisible(expanded)

    def flip(self):
        self.set_expanded(not self.expanded)

    def set_expanded(self, expanded):
        self.expanded = expanded
        self.animation.stop()
        self.body.setVisible(True)
        target = self.body.sizeHint().height() if expanded else 0
        if self.motion_enabled and self.isVisible():
            self.animation.setStartValue(self.body.height())
            self.animation.setEndValue(target)
            self.animation.start()
        else:
            self._finished()

    def _finished(self):
        self.body.setMaximumHeight(16777215 if self.expanded else 0)
        self.body.setVisible(self.expanded)

    def set_motion(self, enabled):
        self.motion_enabled = enabled
        self.animation.stop()
        self._finished()


def fade_in(widget, enabled, start=0.35, duration=170):
    previous = getattr(widget, "_fade", None)
    if previous:
        previous.stop()
    if not enabled:
        widget.setGraphicsEffect(None)
        return
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setStartValue(start)
    animation.setEndValue(1.0)
    animation.setDuration(duration)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    widget._fade = animation
    animation.finished.connect(lambda: widget.setGraphicsEffect(None) if widget.graphicsEffect() is effect else None)
    animation.start()
