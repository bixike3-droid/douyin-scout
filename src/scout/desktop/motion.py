"""Small native transitions; never manufacture operation progress."""
from PySide6.QtCore import (Qt, Property, QObject, QEvent, QPropertyAnimation,
                            QEasingCurve, QAbstractAnimation)
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


def fade_popup(widget, duration=90):
    """菜单 / 工具提示出现时快速淡入（QMenu、QTipLabel 共用）。"""
    animation = QPropertyAnimation(widget, b"windowOpacity", widget)
    animation.setStartValue(0.25)
    animation.setEndValue(1.0)
    animation.setDuration(duration)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    widget._popup_fade = animation
    animation.start()


class ComboPopupMotion(QObject):
    """下拉框弹层：淡入 + 轻微下落，避免“啪”地一下弹出来。"""

    def __init__(self, combo, enabled):
        super().__init__(combo)
        self._combo = combo
        self._enabled = enabled
        self._container = None
        self.attach()

    def attach(self):
        """弹层容器可能晚于控件创建，第一次显示前再挂一次。"""
        try:
            container = self._combo.view().window()
        except RuntimeError:
            return
        if container is None or container is self._container:
            return
        # 圆角弹层需要透明底色，否则方角背景会把圆角盖掉。
        try:
            container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            container.setObjectName("comboPopup")
            view = self._combo.view()
            view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            view.viewport().setAutoFillBackground(False)
            container.style().unpolish(container)
            container.style().polish(container)
            view.style().unpolish(view)
            view.style().polish(view)
        except RuntimeError:
            pass
        container.installEventFilter(self)
        self._container = container

    def eventFilter(self, obj, event):
        try:
            if event.type() == QEvent.Type.Show and self._enabled():
                # 只做淡入：位移动画会和 QComboBox 自身的弹层定位打架，
                # 表现为弹层位置错、盖在控件上。
                animation = QPropertyAnimation(obj, b"windowOpacity", obj)
                animation.setDuration(170)
                animation.setStartValue(0.0)
                animation.setEndValue(1.0)
                animation.setEasingCurve(QEasingCurve.Type.OutQuart)
                obj._combo_fade = animation
                animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        except Exception:
            pass
        return False


def attach_combo_animations(root, enabled):
    """给整个窗口（含后续页面）里的下拉框挂上过渡动画。"""
    from PySide6.QtWidgets import QComboBox
    for combo in root.findChildren(QComboBox):
        if getattr(combo, "_combo_motion", None) is None:
            combo._combo_motion = ComboPopupMotion(combo, enabled)


class PopupFader(QObject):
    """全局事件过滤器：给 QMenu / QToolTip 的显示事件加淡入（尊重动效开关）。

    注意：暂未在窗口里启用 —— 以宿主窗口为 parent、回调又持有窗口引用时
    会形成引用环，旧窗口无法释放，后续 `setStyleSheet` 会越来越慢（实测
    测试套件里表现为愈演愈烈的“卡死”）。重新启用前需：回调改弱引用，
    并在窗口销毁时显式卸下事件过滤器。
    """

    def __init__(self, enabled, parent=None):
        super().__init__(parent)
        self._enabled = enabled

    def eventFilter(self, obj, event):
        try:
            if (event.type() == QEvent.Type.Show and self._enabled()
                    and obj.metaObject().className() in ("QMenu", "QTipLabel")):
                fade_popup(obj)
        except Exception:
            pass
        return False
