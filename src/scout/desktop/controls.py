"""Fluent 控件接入层。

目前只把下拉框换成 PySide6-Fluent-Widgets 的 ComboBox：它的弹层、圆角、
动效（展开/收起）都是自带的，正好替代我们反复手调的原生 QComboBox。
其余控件仍走项目自己的 QSS 体系，避免一次性重写整个界面。
"""
from __future__ import annotations

from qfluentwidgets import ComboBox as _FluentComboBox
from qfluentwidgets import SwitchButton, Theme, setTheme, setThemeColor


def switch(text="", parent=None):
    """Fluent 开关。

    注意：SwitchButton.__init__ 是 singledispatch，子类覆盖 __init__ 会递归，
    所以这里只做工厂函数，不继承。API 上 isChecked/setChecked 与 QCheckBox 一致，
    信号名是 checkedChanged（不是 toggled）。
    """
    return SwitchButton(text, parent)


class ComboBox(_FluentComboBox):
    """Fluent 下拉框：对齐项目里 `addItem(文本, 数据)` 的调用习惯。"""

    def addItem(self, text, userData=None):
        super().addItem(text, userData=userData)

    def insertItem(self, index, text, userData=None):
        super().insertItem(index, text, userData=userData)


def sync_theme(mode: str) -> None:
    """跟随项目深浅色切换 Fluent 自己的主题。"""
    try:
        setTheme(Theme.DARK if mode == "dark" else Theme.LIGHT)
        setThemeColor("#0A84FF" if mode == "dark" else "#007AFF")
    except Exception:      # noqa: BLE001 —— 主题同步失败不影响主界面
        pass


def notify(parent, title: str, content: str = "", kind: str = "success", duration: int = 2600) -> None:
    """右上角消息条：采集完成 / 失败 / 登录失效等，比状态栏一行字显眼。"""
    try:
        from qfluentwidgets import InfoBar, InfoBarPosition
        show = {"success": InfoBar.success, "warning": InfoBar.warning,
                "error": InfoBar.error, "info": InfoBar.info}.get(kind, InfoBar.info)
        show(title, content, orient=None, isClosable=True,
             position=InfoBarPosition.TOP_RIGHT, duration=duration, parent=parent)
    except Exception:      # noqa: BLE001 —— 提示失败不影响主流程
        pass


def state_tip(parent, title: str, content: str = ""):
    """长任务浮窗；失败时返回 None。"""
    try:
        from qfluentwidgets import StateToolTip
        tip = StateToolTip(title, content, parent)
        tip.show()
        return tip
    except Exception:      # noqa: BLE001
        return None


def progress_ring():
    """不确定进度环（顶栏用）。"""
    from qfluentwidgets import ProgressRing
    ring = ProgressRing(useAni=True)
    ring.setFixedSize(18, 18)
    return ring


def fluent_icon(name: str, color: str | None = None):
    """取一个 Fluent 图标（name 如 SYNC / FOLDER / PEOPLE）。

    FluentIcon 默认按库自己的 Theme.AUTO 上色，在深色主界面里会看不见，
    所以这里显式传入项目当前主题的前景色。
    """
    try:
        from PySide6.QtGui import QColor
        from qfluentwidgets import FluentIcon
        from .appearance import color as theme_color

        item = getattr(FluentIcon, name, None)
        if item is None:
            return None
        return item.icon(color=QColor(color or theme_color("text")))
    except Exception:      # noqa: BLE001
        return None


def set_fluent_icon(target, name: str, color: str | None = None) -> bool:
    """给按钮/动作换 Fluent 图标，并登记 fluentGlyph 让切主题时自动重画。

    color 用于深色按钮上的白图标（主题刷新时会用 fluentGlyphColor 重新取色）。
    """
    try:
        fresh = fluent_icon(name, color)
        if fresh is None:
            return False
        target.setIcon(fresh)
        target.setProperty("fluentGlyph", name)
        if color:
            target.setProperty("fluentGlyphColor", color)
        return True
    except Exception:      # noqa: BLE001 —— 图标失败不影响功能
        return False


def command_bar():
    """表格上方的操作条；库不可用时返回 None（调用方自行跳过）。"""
    try:
        from PySide6.QtCore import Qt
        from qfluentwidgets import CommandBar
        bar = CommandBar()
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        return bar
    except Exception:      # noqa: BLE001
        return None


def bar_action(bar, icon_name: str, text: str, slot=None, checkable: bool = False, checked: bool = False):
    """往操作条里加一个动作，返回 QAction（失败返回 None）。"""
    try:
        from qfluentwidgets import Action, FluentIcon
        item = Action(getattr(FluentIcon, icon_name), text, checkable=checkable, checked=checked)
        if slot is not None:
            if checkable:
                item.toggled.connect(slot)
            else:
                item.triggered.connect(lambda *_: slot())
        bar.addAction(item)
        return item
    except Exception:      # noqa: BLE001
        return None


def install_fluent_tooltips(root, show_delay: int = 420) -> int:
    """把原生 QToolTip 换成 Fluent 气泡：更紧凑、带 150ms 淡入，不再硬跳出来。

    列表/表格内部（QAbstractItemView）仍走 Qt 自己的单元格提示，避免和代理冲突。
    """
    try:
        from PySide6.QtWidgets import QAbstractItemView, QWidget
        from qfluentwidgets import ToolTipFilter as _Filter
        from qfluentwidgets import ToolTipPosition
    except Exception:      # noqa: BLE001 —— 未安装 Fluent 时保留原生提示
        return 0

    class _CompactFilter(_Filter):
        """内边距收紧一圈：默认 12/8 + 8/6 太大，看着像一块面板。"""

        def _canShowToolTip(self):
            # 主程序里禁用状态的按钮也带说明，原实现会直接吞掉提示。
            parent = self.parent()
            return bool(parent.isWidgetType() and parent.toolTip())

        def _createToolTip(self):
            tip = super()._createToolTip()
            try:
                tip.layout().setContentsMargins(4, 2, 4, 4)
                tip.containerLayout.setContentsMargins(7, 4, 7, 4)
                tip.label.setStyleSheet("font-size:12px;")
                tip.adjustSize()
            except Exception:      # noqa: BLE001
                pass
            return tip

    installed = 0
    for widget in root.findChildren(QWidget):
        if not widget.toolTip() or isinstance(widget, QAbstractItemView):
            continue
        if widget.property("fluentToolTip"):
            continue
        widget.setProperty("fluentToolTip", True)
        widget.installEventFilter(_CompactFilter(widget, show_delay, ToolTipPosition.TOP))
        installed += 1
    return installed


def flyout_show(anchor, title: str, body: str) -> bool:
    """点一下就地的说明浮层（不跳页）；库不可用时返回 False。"""
    try:
        from PySide6.QtWidgets import QVBoxLayout
        from qfluentwidgets import BodyLabel, Flyout, FlyoutViewBase, StrongBodyLabel

        class _View(FlyoutViewBase):
            def __init__(self, parent=None):
                super().__init__(parent)
                layout = QVBoxLayout(self)
                layout.setContentsMargins(18, 14, 18, 14)
                layout.setSpacing(8)
                layout.addWidget(StrongBodyLabel(title))
                note = BodyLabel(body)
                note.setWordWrap(True)
                layout.addWidget(note)

            def sizeHint(self):
                return self.layout().sizeHint()

        Flyout(_View(), anchor, isDeleteOnClose=True).show()
        return True
    except Exception:      # noqa: BLE001
        return False


def smooth_scroll_area():
    """带平滑滚动的滚动区；库不可用时退回普通 QScrollArea。"""
    try:
        from qfluentwidgets import SmoothScrollArea
        return SmoothScrollArea()
    except Exception:      # noqa: BLE001
        from PySide6.QtWidgets import QScrollArea
        return QScrollArea()
