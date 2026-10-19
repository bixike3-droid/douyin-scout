"""Fluent 组件预览（带编号）。

用法：
    python scripts/fluent_gallery.py

页面上每个组件上方都有「编号 + 中文名 + 类名」，
看中哪个直接说编号（例如「要 ③⑦ ⑫」），我就按编号对应的类去替换。
只读脚本，不依赖也不修改桌面主程序。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy,
    QTableView, QVBoxLayout, QWidget,
)

import qfluentwidgets as q


class Gallery(QWidget):
    def __init__(self):
        super().__init__()
        self.number = 0
        self.dark = False
        self.failures = []
        self.setObjectName("galleryRoot")
        self.setWindowTitle("Fluent 组件预览（编号版）")
        self.resize(920, 900)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 12, 18, 12)
        title = QLabel("Fluent 组件预览　—　告诉 Copilot 你要的编号即可")
        title.setStyleSheet("font-size:13px; font-weight:600;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        self.toggle = q.PushButton("切到深色")
        self.toggle.clicked.connect(self._toggle_theme)
        header_layout.addWidget(self.toggle)
        root.addWidget(header)

        scroll = q.SmoothScrollArea()
        scroll.setWidgetResizable(True)
        # 滚动区自带浅底，不透明的话深色主题下会变成灰底白字
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        scroll.viewport().setAutoFillBackground(False)
        page = QWidget()
        page.setObjectName("galleryPage")
        page.setStyleSheet("QWidget#galleryPage{background:transparent;}")
        self.layout_ = QVBoxLayout(page)
        self.layout_.setContentsMargins(24, 12, 24, 32)
        self.layout_.setSpacing(10)
        scroll.setWidget(page)
        root.addWidget(scroll, 1)

        self._build()
        self.layout_.addStretch()
        self._apply_background("light")
        if self.failures:
            print("以下组件未能演示：")
            for line in self.failures:
                print("  " + line)

    # ── 组装 ────────────────────────────────────────────────

    def _section(self, name):
        label = QLabel(name)
        label.setStyleSheet("font-size:12px; font-weight:600; margin-top:14px; color:#666;")
        self.layout_.addWidget(label)

    def _add(self, cn, cls, factory, *, note=""):
        self.number += 1
        caption = QLabel(f"{self.number:02d}　{cn}　　{cls}" + (f"　—　{note}" if note else ""))
        caption.setStyleSheet("font-size:12px; color:#7a7a82;")
        self.layout_.addWidget(caption)
        try:
            widget = factory()
        except Exception as exc:      # noqa: BLE001 —— 某个组件构造失败不影响整页
            self.failures.append(f"{self.number:02d} {cn} ({cls}): {type(exc).__name__}: {exc}")
            widget = QLabel(f"（当前版本无法直接演示：{type(exc).__name__}: {exc}）")
            widget.setStyleSheet("color:#c0392b; font-size:12px;")
        self.layout_.addWidget(widget)

    def _build(self):
        # 按钮
        self._section("按钮")
        self._add("主按钮", "PrimaryPushButton", lambda: q.PrimaryPushButton("开始采集"))
        self._add("次按钮", "PushButton", lambda: q.PushButton("取消"))
        self._add("透明按钮", "TransparentPushButton", lambda: q.TransparentPushButton("查看详情"))
        self._add("开关型按钮", "TogglePushButton", lambda: q.TogglePushButton("关注"))
        self._add("胶囊按钮", "PillPushButton", lambda: q.PillPushButton("热榜"))
        self._add("链接按钮", "HyperlinkButton",
                  lambda: self._hyperlink())
        self._add("下拉按钮", "DropDownPushButton", lambda: self._dropdown())
        self._add("图标按钮", "ToolButton",
                  lambda: self._tool_button())
        self._add("主图标按钮", "PrimaryToolButton",
                  lambda: q.PrimaryToolButton(q.FluentIcon.SEND))
        # 输入
        self._section("输入")
        self._add("输入框", "LineEdit", lambda: self._line_edit())
        self._add("搜索框", "SearchLineEdit", lambda: q.SearchLineEdit())
        self._add("密码框", "PasswordLineEdit", lambda: q.PasswordLineEdit())
        self._add("下拉框", "ComboBox", lambda: self._combo())
        self._add("可编辑下拉", "EditableComboBox", lambda: self._editable_combo())
        self._add("数字框", "SpinBox", lambda: self._spin())
        self._add("复选框", "CheckBox", lambda: q.CheckBox("允许用于企业分析"))
        self._add("开关", "SwitchButton", lambda: self._switch())
        self._add("滑块", "Slider", lambda: self._slider())
        self._add("多行文本", "TextEdit", lambda: self._text_edit())

        # 卡片
        self._section("卡片")
        self._add("普通卡片", "CardWidget", lambda: self._card(q.CardWidget, "卡片标题", "卡片说明文字"))
        self._add("简洁卡片", "SimpleCardWidget", lambda: self._card(q.SimpleCardWidget, "简洁卡片", "无边框投影"))
        self._add("悬浮卡片", "ElevatedCardWidget", lambda: self._card(q.ElevatedCardWidget, "悬浮卡片", "带投影"))
        self._add("标题卡片", "HeaderCardWidget", lambda: self._header_card())

        # 文本
        self._section("文本标签")
        self._add("大标题", "TitleLabel", lambda: q.TitleLabel("源镜"))
        self._add("副标题", "SubtitleLabel", lambda: q.SubtitleLabel("传播工作台"))
        self._add("强调正文", "StrongBodyLabel", lambda: q.StrongBodyLabel("本周播放量环比 +18%"))
        self._add("正文", "BodyLabel", lambda: q.BodyLabel("这是一段普通正文示例。"))
        self._add("辅助说明", "CaptionLabel", lambda: q.CaptionLabel("数据更新于 2026-10-19 10:20"))

        # 导航
        self._section("导航与切换")
        self._add("分段控件", "SegmentedWidget", lambda: self._segmented())
        self._add("标签页", "TabBar", lambda: self._tabbar())
        self._add("面包屑", "BreadcrumbBar", lambda: self._breadcrumb())

        # 数据
        self._section("数据展示")
        self._add("表格", "TableView", lambda: self._table())
        self._add("列表", "ListWidget", lambda: self._list())
        self._add("树", "TreeWidget", lambda: self._tree())

        # 反馈
        self._section("进度与反馈")
        self._add("进度条", "ProgressBar", lambda: self._progress())
        self._add("不确定进度条", "IndeterminateProgressBar", lambda: self._indeterminate())
        self._add("进度环", "ProgressRing", lambda: self._ring())
        self._add("消息条", "InfoBar", lambda: self._info_button())
        self._add("状态提示", "StateToolTip", lambda: self._state_tip())
        self._add("提示气泡", "ToolTip", lambda: self._tooltip_button())
        self._add("对话框", "MessageBox", lambda: self._message_button())

        # 设置卡
        self._section("设置卡")
        self._add("开关设置卡", "SwitchSettingCard", lambda: self._switch_card())
        self._add("按钮设置卡", "PushSettingCard", lambda: self._push_card())

        # 菜单
        self._section("菜单")
        self._add("圆角菜单", "RoundMenu", lambda: self._menu_button())

    # ── 具体构造 ────────────────────────────────────────────

    def _hyperlink(self):
        link = q.HyperlinkButton()
        link.setText("打开抖音")
        link.setUrl("https://www.douyin.com")
        return link

    def _tool_button(self):
        button = q.ToolButton()
        button.setIcon(q.FluentIcon.SETTING)
        button.setToolTip("设置")
        return button

    def _line_edit(self):
        edit = q.LineEdit()
        edit.setPlaceholderText("请输入关键词")
        return edit

    def _dropdown(self):
        button = q.DropDownPushButton("更多操作")
        menu = q.RoundMenu(parent=button)
        menu.addAction(q.Action(q.FluentIcon.ADD, "新建任务"))
        menu.addAction(q.Action(q.FluentIcon.SAVE, "导出报告"))
        button.setMenu(menu)
        return button

    def _combo(self):
        combo = q.ComboBox()
        combo.addItems(["deepseek-flash", "deepseek-v4-pro"])
        return combo

    def _editable_combo(self):
        combo = q.EditableComboBox()
        combo.addItems(["自定义：海边", "自定义：雨天", "自定义：夜市"])
        return combo

    def _spin(self):
        spin = q.SpinBox()
        spin.setRange(1, 200)
        spin.setValue(40)
        return spin

    def _switch(self):
        switch = q.SwitchButton("启用界面动效")
        switch.setChecked(True)
        return switch

    def _slider(self):
        slider = q.Slider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(62)
        return slider

    def _text_edit(self):
        edit = q.TextEdit()
        edit.setPlaceholderText("输入要交给团队的问题…")
        edit.setFixedHeight(84)
        return edit

    def _card(self, cls, title, body):
        card = cls()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.addWidget(q.StrongBodyLabel(title))
        layout.addWidget(q.CaptionLabel(body))
        return card

    def _header_card(self):
        card = q.HeaderCardWidget()
        try:
            card.setTitle("本周概览")
        except Exception:
            pass
        # HeaderCardWidget 自带布局，直接往里加内容
        card.layout().addWidget(q.BodyLabel("标题栏 + 内容区，适合放数据块。"))
        return card

    def _segmented(self):
        widget = q.SegmentedWidget()
        widget.addItem("hot", "抖音热点")
        widget.addItem("plan", "内容方案")
        widget.addItem("data", "数据概览")
        widget.setCurrentItem("hot")
        return widget

    def _tabbar(self):
        bar = q.TabBar()
        bar.addTab("hot", "抖音热点")
        bar.addTab("plan", "内容方案")
        bar.setCurrentTab("hot")
        return bar

    def _breadcrumb(self):
        bar = q.BreadcrumbBar()
        bar.addItem("home", "工作台")
        bar.addItem("enterprise", "企业分析")
        bar.addItem("report", "本周报告")
        return bar

    def _table(self):
        model = QStandardItemModel(4, 3)
        model.setHorizontalHeaderLabels(["作品", "点赞", "评论"])
        rows = [("秋雨降温，进村前先看这 3 条", "1,284", "36"),
                ("雨天的竹梦村，声音比晴天好听", "976", "21"),
                ("这道菜几年没调过价", "2,015", "58"),
                ("周末散客到店路径拆解", "644", "12")]
        for r, values in enumerate(rows):
            for c, value in enumerate(values):
                model.setItem(r, c, QStandardItem(value))
        table = q.TableView()
        table.setModel(model)
        table.setFixedHeight(190)
        return table

    def _list(self):
        widget = q.ListWidget()
        for index, name in enumerate(["借势分析：今日重阳节", "看看最近谁在点赞我的视频", "竹梦村周末引流方案"]):
            item = q.QListWidgetItem(name) if hasattr(q, "QListWidgetItem") else None
            if item is None:
                from PySide6.QtWidgets import QListWidgetItem
                item = QListWidgetItem(name)
            widget.addItem(item)
        widget.setFixedHeight(150)
        return widget

    def _tree(self):
        tree = q.TreeWidget()
        tree.setHeaderLabels(["目标", "状态"])
        root = None
        from PySide6.QtWidgets import QTreeWidgetItem
        for name, state in (("本人作品", "已完成"), ("点赞人名单", "进行中"), ("互动者资料", "待处理")):
            item = QTreeWidgetItem([name, state])
            tree.addTopLevelItem(item)
        tree.expandAll()
        tree.setFixedHeight(160)
        return tree

    def _progress(self):
        bar = q.ProgressBar()
        bar.setValue(62)
        return bar

    def _indeterminate(self):
        bar = q.IndeterminateProgressBar(self)
        bar.start()
        return bar

    def _ring(self):
        ring = q.ProgressRing(useAni=True)
        ring.setFixedSize(56, 56)
        return ring

    def _info_button(self):
        button = q.PushButton("点我弹消息条")

        def show():
            q.InfoBar.success("采集完成", "本轮新增 11 条作品、27 位互动者",
                              orient=Qt.Orientation.Horizontal, isClosable=True,
                              position=q.InfoBarPosition.TOP, duration=3000, parent=self)
        button.clicked.connect(show)
        return button

    def _state_tip(self):
        button = q.PushButton("点我显示状态提示")
        holder = {}

        def show():
            tip = q.StateToolTip("正在采集评论…", "预计 40 秒", self)
            tip.show()
            tip.move(self.width() // 2 - 140, 80)
            holder["tip"] = tip
        button.clicked.connect(show)
        return button

    def _tooltip_button(self):
        button = q.PushButton("鼠标悬停看提示")
        q.ToolTip("这是 Fluent 的提示气泡", button)
        return button

    def _message_button(self):
        button = q.PushButton("点我打开对话框")

        def show():
            box = q.MessageBox("确认删除", "删除后本地记录不可恢复。", self)
            box.yesButton.setText("删除")
            box.cancelButton.setText("取消")
            box.exec()
        button.clicked.connect(show)
        return button

    def _switch_card(self):
        card = q.SwitchSettingCard(q.FluentIcon.MOVIE, "界面动效", "关闭后所有过渡直接切换", parent=self)
        card.switchButton.setChecked(True)
        return card

    def _combo_card(self):
        return None

    def _push_card(self):
        return q.PushSettingCard("打开目录", q.FluentIcon.FOLDER, "本地数据", "查看原始响应与数据库", self)

    def _menu_button(self):
        button = q.PushButton("点我打开圆角菜单")
        menu = q.RoundMenu(parent=button)
        menu.addAction(q.Action(q.FluentIcon.ADD, "新建任务"))
        menu.addAction(q.Action(q.FluentIcon.SYNC, "刷新数据"))
        menu.addSeparator()
        menu.addAction(q.Action(q.FluentIcon.DELETE, "清空记录"))
        button.clicked.connect(lambda: menu.exec(button.mapToGlobal(button.rect().bottomLeft())))
        return button

    # ── 主题 ────────────────────────────────────────────────

    def _toggle_theme(self):
        self.dark = not getattr(self, "dark", False)
        q.setTheme(q.Theme.DARK if self.dark else q.Theme.LIGHT)
        q.setThemeColor("#0A84FF" if self.dark else "#007AFF")
        self.toggle.setText("切到浅色" if self.dark else "切到深色")
        self._apply_background("dark" if self.dark else "light")

    def _apply_background(self, mode):
        shade = "#1E1E22" if mode == "dark" else "#F5F6F8"
        from PySide6.QtGui import QColor, QPalette
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(shade))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self.setStyleSheet(f"QWidget#galleryRoot {{ background:{shade}; }}")


def main():
    app = QApplication(sys.argv)
    q.setTheme(q.Theme.LIGHT)
    q.setThemeColor("#007AFF")
    gallery = Gallery()
    gallery.show()
    gallery.raise_()
    gallery.activateWindow()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
