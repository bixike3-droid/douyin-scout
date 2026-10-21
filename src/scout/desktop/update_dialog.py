"""更新弹窗：发现新版本时的对话框（与主界面同一套配色）。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout


class UpdateDialog(QDialog):
    update_requested = Signal()
    skip_requested = Signal()
    open_page_requested = Signal()

    def __init__(self, info: dict, current: str, parent=None):
        super().__init__(parent)
        self.setObjectName("updateDialog")
        self.setWindowTitle("发现新版本")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(12)

        title = QLabel(f"发现新版本 v{info.get('version') or '?'}")
        title.setObjectName("updateTitle")
        layout.addWidget(title)

        size = info.get("zip_size") or 0
        from .update import friendly_size
        meta = f"当前版本 v{current}"
        if size:
            meta += f" · 更新包约 {friendly_size(size)}"
        meta += " · 更新会重启程序"
        subtitle = QLabel(meta)
        subtitle.setObjectName("updateMeta")
        layout.addWidget(subtitle)

        notes = QTextBrowser()
        notes.setObjectName("updateNotes")
        notes.setOpenExternalLinks(False)
        notes.setMinimumHeight(150)
        notes.setMaximumHeight(220)
        body = (info.get("notes") or "").strip() or "（这次发布没有写更新说明）"
        try:
            notes.setMarkdown(body[:1600])
        except Exception:      # noqa: BLE001 —— 老版本 Qt 不支持 markdown 时退回纯文本
            notes.setPlainText(body[:1600])
        layout.addWidget(notes)

        self.hint = QLabel("")
        self.hint.setObjectName("updateMeta")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        page_button = QPushButton("查看发布页")
        page_button.clicked.connect(self.open_page_requested.emit)
        row.addWidget(page_button)
        row.addStretch()
        skip_button = QPushButton("跳过此版本")
        skip_button.clicked.connect(self._skip)
        row.addWidget(skip_button)
        later_button = QPushButton("稍后")
        later_button.clicked.connect(self.reject)
        row.addWidget(later_button)
        self.update_button = QPushButton("立即更新")
        self.update_button.setObjectName("primary")
        self.update_button.setDefault(True)
        self.update_button.clicked.connect(self._update)
        row.addWidget(self.update_button)
        layout.addLayout(row)

    def _update(self) -> None:
        self.update_button.setEnabled(False)
        self.hint.setText("正在下载更新包…")
        self.update_requested.emit()

    def _skip(self) -> None:
        self.skip_requested.emit()
        self.accept()

    def set_progress(self, text: str) -> None:
        self.hint.setText(text)

    def download_failed(self, message: str) -> None:
        self.update_button.setEnabled(True)
        self.hint.setText(message)
