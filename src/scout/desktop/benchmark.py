"""对标账号页：登记名单、检查更新、查看最近作品。

只负责展示与收集用户动作；数据读写走 DesktopService，不在界面里写 SQL。
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QSplitter, QVBoxLayout, QWidget)

from .components import ElidedLabel, text


def _work_line(work) -> str:
    parts: list[str] = []
    stamp = work.get("create_time")
    try:
        parts.append(datetime.fromtimestamp(int(stamp)).strftime("%Y-%m-%d"))
    except (TypeError, ValueError, OSError):
        parts.append("日期未知")
    if work.get("digg_count") is not None:
        parts.append(f"赞 {work['digg_count']}")
    title = (work.get("description") or "").strip() or "（无标题）"
    parts.append(title[:36])
    return "  ·  ".join(parts)


def _checked_line(account) -> str:
    stamp = account.get("last_checked_at") or ""
    if stamp:
        try:
            checked = datetime.fromisoformat(stamp).strftime("%m-%d %H:%M")
        except ValueError:
            checked = stamp[:16]
    else:
        checked = "从未"
    line = f"检查 {checked} · 新增 {account.get('last_new_count', 0)} · 作品 {account.get('works_count', 0)}"
    if account.get("last_error"):
        line += " · 上次有错"
    return line


class BenchmarkPage(QWidget):
    check_requested = Signal(str)   # sec_uid；空串 = 检查全部
    add_requested = Signal(str)
    remove_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.accounts: list[dict] = []
        self._selected: str | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 12, 28, 20)
        layout.setSpacing(12)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("粘贴对标账号的主页链接（douyin.com/user/…）或 sec_uid，回车添加")
        self.input.returnPressed.connect(self._emit_add)
        row.addWidget(self.input, 1)
        self.add_button = QPushButton("添加")
        self.add_button.setObjectName("primary")
        self.add_button.clicked.connect(self._emit_add)
        row.addWidget(self.add_button)
        self.check_all_button = QPushButton("检查全部更新")
        self.check_all_button.clicked.connect(lambda: self.check_requested.emit(""))
        row.addWidget(self.check_all_button)
        layout.addLayout(row)

        splitter = QSplitter()
        self.accounts_list = QListWidget()
        self.accounts_list.setObjectName("recentTasks")
        self.accounts_list.currentItemChanged.connect(self._select)
        splitter.addWidget(self.accounts_list)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 0, 0, 0)
        right_layout.setSpacing(8)
        self.detail_title = ElidedLabel("选择左侧账号查看最近作品", "sectionTitle")
        right_layout.addWidget(self.detail_title)
        self.detail_meta = text("", "muted")
        right_layout.addWidget(self.detail_meta)
        buttons = QHBoxLayout()
        self.check_button = QPushButton("检查更新")
        self.check_button.clicked.connect(self._emit_check_selected)
        buttons.addWidget(self.check_button)
        self.remove_button = QPushButton("移出名单")
        self.remove_button.clicked.connect(self._emit_remove)
        buttons.addWidget(self.remove_button)
        buttons.addStretch()
        right_layout.addLayout(buttons)
        self.works_list = QListWidget()
        self.works_list.setObjectName("recentTasks")
        right_layout.addWidget(self.works_list, 1)
        splitter.addWidget(right)
        splitter.setSizes([320, 780])
        layout.addWidget(splitter, 1)
        self._refresh_detail()

    # ── 数据 ────────────────────────────────────────────────

    def apply(self, accounts):
        previous = self._selected
        self.accounts = list(accounts or [])
        self.accounts_list.blockSignals(True)
        self.accounts_list.clear()
        for account in self.accounts:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, account["sec_uid"])
            item.setSizeHint(QSize(240, 56))
            panel = QWidget()
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(10, 7, 10, 7)
            panel_layout.setSpacing(2)
            name = ElidedLabel(account.get("display_name") or account["sec_uid"][:16], "historyTitle")
            name.setToolTip(account["sec_uid"])
            panel_layout.addWidget(name)
            panel_layout.addWidget(text(_checked_line(account), "historyMeta"))
            self.accounts_list.addItem(item)
            self.accounts_list.setItemWidget(item, panel)
        self.accounts_list.blockSignals(False)
        target = previous if any(a["sec_uid"] == previous for a in self.accounts) else (
            self.accounts[0]["sec_uid"] if self.accounts else None)
        self._selected = target
        if target is not None:
            row = next(i for i, a in enumerate(self.accounts) if a["sec_uid"] == target)
            self.accounts_list.setCurrentRow(row)
        else:
            self._refresh_detail()

    # ── 交互 ────────────────────────────────────────────────

    def _emit_add(self):
        value = self.input.text().strip()
        if value:
            self.add_requested.emit(value)

    def _emit_check_selected(self):
        if self._selected:
            self.check_requested.emit(self._selected)

    def _emit_remove(self):
        if self._selected:
            self.remove_requested.emit(self._selected)

    def _select(self, current, previous=None):
        self._selected = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        self._refresh_detail()

    def _refresh_detail(self):
        account = next((a for a in self.accounts if a["sec_uid"] == self._selected), None)
        self.works_list.clear()
        self.check_button.setEnabled(account is not None)
        self.remove_button.setEnabled(account is not None)
        if account is None:
            self.detail_title.setText("选择左侧账号查看最近作品" if self.accounts else "还没有对标账号，先在上方添加")
            self.detail_meta.setText("")
            return
        self.detail_title.setText(account.get("display_name") or account["sec_uid"][:16])
        self.detail_meta.setText(f"{account['sec_uid']} · {_checked_line(account)}")
        self.detail_meta.setToolTip(account.get("last_error") or "")
        works = account.get("works") or []
        for work in works:
            item = QListWidgetItem(_work_line(work))
            item.setToolTip((work.get("description") or "").strip())
            self.works_list.addItem(item)
        if not works:
            self.works_list.addItem("尚无已采集作品；点「检查更新」抓取最近一页。")
