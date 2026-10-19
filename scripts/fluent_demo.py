"""Fluent 组件示例窗口（编号版）。

用法：
    python scripts/fluent_demo.py

里面放的是「还没进主程序」的候选组件：
  01 CardWidget        普通卡片
  02 SimpleCardWidget  简洁卡片
  03 ElevatedCardWidget 悬浮卡片（我原本要换首页指标卡的那一个）
  04 Flyout            浮层详情（点按钮弹出，不跳页）
  05 CommandBar        操作条（表格上方那种）
  06 MessageBox        统一对话框
  07 InfoBar           消息条
"""
from __future__ import annotations

import faulthandler
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QColor, QPalette
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QVBoxLayout, QWidget,
)

import qfluentwidgets as q


class FlyoutView(q.FlyoutViewBase):
    """Flyout 里显示的内容：标题 + 几句说明 + 关闭按钮。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)
        layout.addWidget(q.StrongBodyLabel("这条热点为什么值得跟"))
        layout.addWidget(q.BodyLabel(
            "热榜数据显示它在涨；跟你的客群（本地周末散客）相关；\n"
            "且话题本身不涉灾情、不涉争议。"))
        close = q.PushButton("知道了")
        close.clicked.connect(self.window().close)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)

    def sizeHint(self):
        return self.layout().sizeHint()


class Demo(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Fluent 候选组件示例（下拉清单之外 · 1019 修复版）")
        self.resize(1060, 820)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 14, 20, 14)
        header_layout.addWidget(q.StrongBodyLabel("候选组件示例　—　看完告诉我编号"))
        header_layout.addStretch()
        toggle = q.PushButton("切到深色")
        toggle.clicked.connect(lambda: self._toggle(toggle))
        header_layout.addWidget(toggle)
        root.addWidget(header)

        # 原生的 QScrollArea / QLabel 不吃 Fluent 主题：深色下会变成浅底浅字。
        # 换成 SmoothScrollArea + Fluent 标签，并把页面背景让给窗口自己画。
        scroll = q.SmoothScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # SmoothScrollArea 自己会盖一层浅底，不透明的话深色主题下就变灰底白字。
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        scroll.viewport().setAutoFillBackground(False)
        page = QWidget()
        page.setObjectName("demoPage")
        page.setStyleSheet("QWidget#demoPage{background:transparent;}")
        self.body = QVBoxLayout(page)
        self.body.setContentsMargins(24, 10, 24, 28)
        self.body.setSpacing(12)
        scroll.setWidget(page)
        root.addWidget(scroll, 1)

        self._cards()
        self._flyout()
        self._command_bar()
        self._dialogs()
        self.body.addStretch()
        self._paint_background()

    def _paint_background(self):
        """裸 QWidget 不会跟 Fluent 主题走背景，这里自己填。"""
        color = "#202020" if getattr(self, "dark", False) else "#f6f7fb"
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(color))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

    def _caption(self, text):
        self.body.addWidget(q.CaptionLabel(text))

    def _cards(self):
        self._caption("卡片对比（同一份内容，三种层次）")
        row = QHBoxLayout()
        row.setSpacing(14)
        for index, (cls, name) in enumerate((
                (q.CardWidget, "01　CardWidget"),
                (q.SimpleCardWidget, "02　SimpleCardWidget"),
                (q.ElevatedCardWidget, "03　ElevatedCardWidget"))):
            card = cls()
            card.setMinimumHeight(140)
            card.setMinimumWidth(280)
            layout = QVBoxLayout(card)
            layout.setContentsMargins(16, 14, 16, 14)
            layout.setSpacing(6)
            layout.addWidget(q.StrongBodyLabel(name.split("　")[1]))
            layout.addWidget(q.CaptionLabel("本周播放 12,840 / 点赞 632 / 新增互动者 27"))
            note = q.BodyLabel("用于首页指标卡、热点卡、报告摘要，重点看层次和投影。")
            note.setWordWrap(True)
            layout.addWidget(note)
            row.addWidget(card, 1)
        self.body.addLayout(row)

    def _flyout(self):
        self._caption("Flyout 浮层（不跳页就地看详情）")
        button = q.PushButton("点我看热点详情浮层")

        def show():
            view = FlyoutView(self)
            flyout = q.Flyout(view, self, isDeleteOnClose=True)
            flyout.show()

        button.clicked.connect(show)
        self.body.addWidget(button)

    def _command_bar(self):
        self._caption("CommandBar 操作条（作品表 / 互动者表上方）")
        bar = q.CommandBar()
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        bar.addAction(q.Action(q.FluentIcon.ADD, "采集评论", triggered=lambda: None))
        bar.addAction(q.Action(q.FluentIcon.SAVE, "补录指标", triggered=lambda: None))
        bar.addAction(q.Action(q.FluentIcon.SYNC, "刷新数据", triggered=lambda: None))
        bar.addSeparator()
        bar.addAction(q.Action(q.FluentIcon.DELETE, "清理缓存", triggered=lambda: None))
        self.body.addWidget(bar)

    def _dialogs(self):
        self._caption("对话框与消息条")
        row = QHBoxLayout()
        row.setSpacing(10)

        dialog_button = q.PushButton("06　打开 MessageBox")

        def open_dialog():
            box = q.MessageBox("确认删除", "删除后本地记录不可恢复。", self)
            box.yesButton.setText("删除")
            box.cancelButton.setText("取消")
            box.exec()

        dialog_button.clicked.connect(open_dialog)
        row.addWidget(dialog_button)

        info_button = q.PushButton("07　弹出 InfoBar")

        def open_info():
            q.InfoBar.success("采集完成", "本轮新增 11 条作品、27 位互动者",
                              orient=Qt.Orientation.Horizontal, isClosable=True,
                              position=q.InfoBarPosition.TOP_RIGHT, duration=3000, parent=self)

        info_button.clicked.connect(open_info)
        row.addWidget(info_button)
        row.addStretch()
        self.body.addLayout(row)

    def _toggle(self, button):
        self.dark = not getattr(self, "dark", False)
        button.setText("切到浅色" if self.dark else "切到深色")
        # 关键：不能在按钮自己的 clicked 处理里换全局样式表。
        # 那样会在鼠标事件分发途中把所有控件重刷一遍，Qt 侧容易直接崩。
        # 交给下一轮事件循环做，处理完再恢复按钮。
        button.setEnabled(False)
        QTimer.singleShot(0, lambda: self._apply_theme(button))

    def _apply_theme(self, button):
        try:
            q.setTheme(q.Theme.DARK if self.dark else q.Theme.LIGHT)
            self._paint_background()
        except Exception as error:  # noqa: BLE001 - 示例脚本需要兜底而不是直接退出
            log_error("setTheme failed", error)
        finally:
            button.setEnabled(True)


def log_error(title: str, error: BaseException | None = None) -> None:
    path = Path(tempfile.gettempdir()) / "fluent_demo_error.log"
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {title}\n")
            if error is not None:
                traceback.print_exception(type(error), error, error.__traceback__, file=handle)
    except OSError:
        pass


def install_crash_log() -> None:
    """原生崩溃也要留下现场：faulthandler + 未捕获异常都写文件。"""
    path = Path(tempfile.gettempdir()) / "fluent_demo_error.log"
    try:
        handle = path.open("a", encoding="utf-8")
    except OSError:
        return
    faulthandler.enable(handle, all_threads=True)
    globals()["_CRASH_LOG"] = handle

    def hook(exc_type, exc, tb):
        with path.open("a", encoding="utf-8") as stream:
            stream.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] uncaught\n")
            traceback.print_exception(exc_type, exc, tb, file=stream)
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


def main():
    install_crash_log()
    app = QApplication(sys.argv)
    q.setTheme(q.Theme.LIGHT)
    window = Demo()
    window.show()
    window.raise_()
    window.activateWindow()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

