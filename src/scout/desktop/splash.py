"""启动页：品牌 + 真实阶段文案，就绪（或超时）后淡出进入主界面。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .appearance import color
from .branding import brand_pixmap
from .components import text
from .motion import ActivityDot


class Splash(QWidget):
    """不伪造进度的启动动画：只显示真实阶段，最长停留由调用方控制。"""

    def __init__(self, motion: bool = True):
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self.motion_enabled = motion
        self._fading = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(420, 246)
        self.setStyleSheet(f"""
QFrame#splashCard {{ background: {color('window')}; border: 1px solid {color('border')}; border-radius: 16px; }}
QLabel#splashMark {{ background: transparent; }}
QLabel#splashTitle {{ font-size: 21px; font-weight: 600; color: {color('text')}; }}
QLabel#splashSubtitle, QLabel#splashStage {{ color: {color('muted')}; font-size: 12px; }}
""")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        card = QFrame()
        card.setObjectName("splashCard")
        outer.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(30, 28, 30, 24)
        layout.setSpacing(8)
        mark_row = QHBoxLayout()
        mark = QLabel()
        mark.setObjectName("splashMark")
        mark.setFixedSize(48, 48)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo = brand_pixmap(48)
        if logo is not None:
            mark.setPixmap(logo)
        else:
            mark.setText("源")
        mark_row.addWidget(mark)
        mark_row.addStretch()
        layout.addLayout(mark_row)
        title = QLabel("源镜")
        title.setObjectName("splashTitle")
        layout.addWidget(title)
        layout.addWidget(text("抖音互动洞察工作台", "splashSubtitle"))
        layout.addStretch()
        stage_row = QHBoxLayout()
        stage_row.setSpacing(8)
        self.dot = ActivityDot()
        self.dot.set_motion(motion)
        self.dot.set_running(True)
        stage_row.addWidget(self.dot)
        self.stage = text("正在读取本地数据", "splashStage")
        stage_row.addWidget(self.stage, 1)
        layout.addLayout(stage_row)

    def show_centered(self):
        screen = QApplication.primaryScreen()
        if screen is not None:
            center = screen.availableGeometry().center()
            self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)
        self.show()
        self.raise_()

    def set_stage(self, message: str):
        if message and self.stage.text() != message:
            self.stage.setText(message)

    def finish(self, motion: bool | None = None):
        """淡出并关闭；关闭动效时直接消失。"""
        motion = self.motion_enabled if motion is None else motion
        self.dot.set_running(False)
        if not motion:
            self.close()
            return
        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        fade.setDuration(180)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade.finished.connect(self.close)
        self._fading = fade
        fade.start()
