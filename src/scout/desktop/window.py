"""Qt Widgets desktop shell and native data views."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, QUrl, QSize, QEvent, QSettings, Signal
from PySide6.QtGui import QAction, QDesktopServices, QColor, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSplitter, QStackedWidget, QTableView,
    QVBoxLayout, QWidget, QHeaderView, QListWidgetItem, QScrollArea, QComboBox, QSpinBox, QCheckBox, QSizeGrip, QTabWidget,
)

from .jobs import Jobs
from ..util import local_tz, parse_iso
from .components import MetricCard, TaskSummary, ElidedLabel, card, text
from .theme import apply_theme, icon
from .appearance import THEMES, color
from .operations import Operations
from .benchmark import BenchmarkPage
from .harness import HarnessPage, TitleBar
from .enterprise import report_time
from .motion import fade_in
from .taskbar import TaskbarProgress

LABELS = {
    "pending": "待处理", "running": "执行中", "done": "已完成", "failed": "失败",
    "blocked": "已暂停", "profile": "互动者画像", "review": "作品评价", "plan": "内容计划",
    "fetch_self": "识别账号", "fetch_notice": "互动通知", "fetch_likers": "点赞人名单",
    "fetch_comments": "评论区", "fetch_user_works": "用户作品", "fetch_profile": "公开资料", "fetch_works": "作品列表",
    "full": "已触底", "sampled": "采样完成", "partial": "部分完成", "empty": "正常为空", "error": "异常",
}
PAGES = [("传播工作台", "enterprise"), ("作品数据", "works"), ("互动者", "users"),
         ("历史分析", "analyses"), ("采集任务", "tasks"), ("对标账号", "benchmark"),
         ("设置", "settings"), ("数据概览", "overview")]
COLUMNS = {
    "works": [("作品标题", "description"), ("播放", "play_count"), ("点赞", "digg_count"), ("评论", "comment_count"),
              ("转发", "share_count"), ("发布时间", "create_time")],
    "users": [("昵称", "nickname"), ("互动作品", "interaction_works"), ("作品样本", "sample_count"),
              ("资料状态", "data_status"), ("粉丝", "follower_count"), ("最近采集", "last_seen_at")],
    "analyses": [("分析对象", "input_summary"), ("报告类型", "task"), ("模型", "model"),
                 ("版本", "prompt_version"), ("生成时间", "created_at")],
    "tasks": [("任务", "kind"), ("状态", "state"), ("范围", "collection_state"), ("目标", "target"),
              ("尝试次数", "attempts"), ("更新时间", "updated_at"), ("最近错误", "last_error")],
}
DESCRIPTIONS = {
    "works": "自己账号的作品与已采集统计；选择一行查看详情。",
    "users": "曾与作品互动的用户及其公开资料，包含历史互动记录。",
    "analyses": "查看已有分析，每个对象和报告类型显示最新一份结果。",
    "tasks": "查看现有采集任务的状态、尝试次数和错误记录。",
}


def label(text):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    return widget


def display_value(key, value):
    if value is None or value == "":
        if key == "play_count":
            return "未获取"
        return "—"
    try:
        if key == "create_time":
            return datetime.fromtimestamp(int(value), local_tz()).strftime("%Y-%m-%d %H:%M")
        if key.endswith("_at"):
            return parse_iso(str(value)).astimezone(local_tz()).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OSError, OverflowError):
        pass
    return LABELS.get(str(value), str(value)) if key in ("state", "kind", "task", "collection_state") else str(value)


class RecordsModel(QAbstractTableModel):
    def __init__(self, columns, parent=None):
        super().__init__(parent)
        self.columns = columns
        self.rows = []

    def replace(self, rows):
        rows = list(rows)
        if len(rows) == len(self.rows):
            # 同长度（刷新/翻页）：不重置模型，避免整表闪变并保留选中状态。
            self.rows = rows
            if rows:
                self.dataChanged.emit(self.index(0, 0), self.index(len(rows) - 1, self.columnCount() - 1))
        else:
            self.beginResetModel()
            self.rows = rows
            self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.columns[section][0]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        key = self.columns[index.column()][1]
        value = self.rows[index.row()].get(key)
        numbers = {"play_count", "digg_count", "comment_count", "share_count", "follower_count", "attempts", "interaction_works", "sample_count"}
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int((Qt.AlignmentFlag.AlignRight if key in numbers else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole and key == "state":
            shade = {"done": "success", "pending": "warning", "failed": "danger", "running": "accent"}.get(value)
            return QColor(color(shade)) if shade else None
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None
        if key in numbers and isinstance(value, int):
            return f"{value:,}"
        return display_value(key, value)


class RecordsPage(QWidget):
    work_selected = Signal(str)
    collect_comments_requested = Signal(str)

    def __init__(self, key, request, parent=None):
        super().__init__(parent)
        self.key = key
        self.page = 0
        self.total = 0
        self.selected_id = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        description = label(DESCRIPTIONS[key])
        description.setObjectName("muted")
        layout.addWidget(description)
        layout.setSpacing(16)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索名称或标识…")
        self.search.setClearButtonEnabled(True)
        search_row = QHBoxLayout()
        search_row.addWidget(self.search, 1)
        self.detail_toggle = QPushButton("详情面板")
        self.detail_toggle.setCheckable(True)
        self.detail_toggle.setChecked(True)
        search_row.addWidget(self.detail_toggle)
        layout.addLayout(search_row)
        self.model = RecordsModel(COLUMNS[key], self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.horizontalHeader().setFixedHeight(36)
        self.table.horizontalHeader().setMinimumSectionSize(60)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        stretch_key = {"works": "description", "users": "nickname", "analyses": "input_summary", "tasks": "target"}[key]
        for index, (_, column) in enumerate(COLUMNS[key]):
            width = 140 if column.endswith("_at") or column == "create_time" else 120
            if column in ("play_count", "digg_count", "comment_count", "share_count", "follower_count", "attempts", "prompt_version", "interaction_works", "sample_count"):
                width = 70
            if column == "state":
                width = 85
            self.table.setColumnWidth(index, width)
            self.table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch if column == stretch_key else QHeaderView.ResizeMode.Interactive)
        self.table.setWordWrap(False)
        self.empty = QLabel("正在读取本地数据…", self.table.viewport())
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.table.viewport().installEventFilter(self)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setObjectName("recordDetail")
        self.detail.setPlaceholderText("选择一行查看完整记录")
        detail_card, detail_layout = card("记录详情", "选择左侧记录，查看内容与数据来源。")
        detail_card.setMinimumWidth(260)
        detail_layout.addWidget(self.detail, 1)
        self.comments_button = QPushButton("采集评论区")
        self.comments_button.setToolTip("按抽样预算采集这条作品的评论区（需登录态）")
        self.comments_button.setVisible(False)
        self.comments_button.clicked.connect(self._collect_comments)
        detail_layout.addWidget(self.comments_button)
        self.detail_toggle.toggled.connect(detail_card.setVisible)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.table)
        splitter.addWidget(detail_card)
        splitter.setSizes([700, 300])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setHandleWidth(6)
        layout.addWidget(splitter, 1)
        controls = QHBoxLayout()
        self.count = label("正在读取…")
        self.count.setObjectName("muted")
        self.previous = QPushButton("上一页")
        self.next = QPushButton("下一页")
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        controls.addWidget(self.count, 1)
        controls.addWidget(self.previous)
        controls.addWidget(self.next)
        layout.addLayout(controls)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(300)
        self.timer.timeout.connect(request)
        self.search.textChanged.connect(self._search_changed)
        self.previous.clicked.connect(lambda: self._move(-1, request))
        self.next.clicked.connect(lambda: self._move(1, request))
        self.table.selectionModel().selectionChanged.connect(self._selection)

    def _search_changed(self):
        self.page = 0
        self.table.scrollToTop()
        self.timer.start()

    def eventFilter(self, watched, event):
        if watched is self.table.viewport() and event.type() == QEvent.Type.Resize:
            self.empty.setGeometry(self.table.viewport().rect())
        return super().eventFilter(watched, event)

    def _move(self, delta, request):
        self.page = max(0, self.page + delta)
        self.table.scrollToTop()
        request()

    def apply(self, data):
        self.page = data["page"]
        self.selected_id = None
        self.comments_button.setVisible(False)
        self.model.replace(data["rows"])
        self.empty.setText("没有匹配的记录\n试试其他名称或标识。" if self.search.text() else "这里还没有记录\n采集或导入后，数据会显示在这里。")
        self.empty.setVisible(not data["rows"])
        self.detail.clear()
        total, size = data["total"], data["page_size"]
        self.total = total
        pages = max(1, (total + size - 1) // size)
        self.count.setText(f"共 {total:,} 条 · 第 {self.page + 1}/{pages} 页" if total else "暂无记录")
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled((self.page + 1) * size < total)

    def _selection(self):
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            self.selected_id = None
            self.comments_button.setVisible(False)
            self.detail.clear()
            return
        record = dict(self.model.rows[selected[0].row()])
        if self.key == "works":
            self.selected_id = str(record.get("aweme_id") or "") or None
            self.comments_button.setVisible(bool(self.selected_id))
            if self.selected_id:
                self.work_selected.emit(self.selected_id)
        lines = [f"{title}：{display_value(key, record.get(key))}" for title, key in COLUMNS[self.key]]
        extra = {
            "works": [("统计采集时间", "stats_fetched_at"), ("作品标识", "aweme_id"), ("收藏", "collect_count"), ("统计备注", "stats_anomaly"), ("指标来源与时间", "metric_note")],
            "users": [("筛选依据", "priority_reason"), ("数据质量说明", "quality_reason"),
                      ("抖音号", "douyin_id"), ("公开简介", "signature"), ("用户标识", "sec_uid"),
                      ("公开地区", "region"), ("作品数参考", "aweme_count")],
            "tasks": [("开始时间", "claimed_at"), ("结束时间", "finished_at")],
            "analyses": [],
        }
        lines.extend(f"{title}：{display_value(key, record.get(key))}" for title, key in extra[self.key])
        links = record.get("links")
        if isinstance(links, dict) and self.key in ("users", "works"):
            items = links.get("items") or []
            lines.append("")
            if self.key == "users":
                lines.append(f"互动作品：共 {links.get('total', 0)} 条，展示最近 {len(items)} 条")
            else:
                lines.append(f"已采点赞人：共 {links.get('total', 0)} 人，展示最近 {len(items)} 人")
            for item in items:
                if self.key == "users":
                    title = item.get("label") or (f"作品 {item.get('id')}" if item.get("id") else "未关联作品")
                else:
                    title = item.get("label") or (str(item.get("id") or "")[:14] or "未知用户")
                lines.append(f"· {display_value('discovered_at', item.get('at'))}　{title}")
            if not items:
                lines.append("· 暂无关联记录")
        if "output_json" in record:
            try:
                output = json.loads(record["output_json"])
                names = {"content_domains": "内容领域", "persona": "公开内容画像", "audience": "内容受众",
                         "activity_level": "活跃度", "activity_reason": "活跃依据", "relevance_score": "相关性评分",
                         "relevance_reason": "评分依据", "recommended_action": "互动建议", "summary": "结论",
                         "score": "作品评分", "overall": "整体评价", "strengths": "优势", "problems": "问题",
                         "audience_match": "受众匹配", "actions": "建议", "positioning": "定位建议",
                         "topics": "选题", "cadence": "发布节奏", "engagement": "互动策略",
                         "avoid": "注意事项", "next_7_days": "未来七天计划"}
                names["confidence"] = "证据把握"
                names["data_quality"] = "输入质量说明"
                lines.append("\n报告内容")
                if isinstance(output, dict):
                    for key, value in output.items():
                        if value is None:
                            value = "无法判断（证据不足）"
                        if isinstance(value, (list, dict)):
                            if isinstance(value, list):
                                items = []
                                for item in value:
                                    if isinstance(item, dict):
                                        item = " · ".join(str(v) for v in item.values())
                                    items.append(f"• {item}")
                                value = "\n" + "\n".join(items)
                            else:
                                value = "\n" + "\n".join(f"{k}：{v}" for k, v in value.items())
                        lines.append(f"{names.get(key, key)}：{value}")
                else:
                    lines.append(json.dumps(output, ensure_ascii=False, indent=2))
            except (TypeError, ValueError):
                lines.append("报告内容无法解析，请检查原始分析结果。")
        self.detail.setPlainText("\n\n".join(lines))

    def _collect_comments(self):
        if self.selected_id:
            self.collect_comments_requested.emit(self.selected_id)

    def apply_comments(self, data):
        """评论区数据回填详情（选中作品未被切走时生效）。"""
        if self.key != "works" or not self.selected_id:
            return
        if str(data.get("aweme_id") or "") != self.selected_id:
            return
        items = data.get("items") or []
        lines = ["", f"评论区：已采 {len(items)} 条（按点赞排序）" if items else "评论区：尚未采集"]
        for row in items[:10]:
            text = str(row.get("text") or "").replace("\n", " ").strip()[:60]
            lines.append(f"· 赞 {row.get('digg_count') or 0} · 回复 {row.get('reply_count') or 0} · {text}")
        self.detail.appendPlainText("\n".join(lines))


class MainWindow(QMainWindow):
    def __init__(self, service):
        super().__init__()
        self.service = service
        self.ui_preferences = QSettings(str(service.paths.root / "desktop-ui.ini"), QSettings.Format.IniFormat)
        appearance = str(self.ui_preferences.value("appearance", "light"))
        self.appearance_pref = appearance if appearance in ("light", "dark", "auto") else "light"
        self.appearance_mode = self._system_appearance() if self.appearance_pref == "auto" else self.appearance_pref
        # Mica 背景板暂缓启用（2026-10-17 真机验证）：WA_TranslucentBackground 会把窗口
        # 变成分层窗口（WS_EX_LAYERED），标题栏拖动 / 系统命中链路失效。
        # winapi.apply_backdrop 保留，待找到不破坏输入链路的方案后再接回（默认关）。
        self._backdrop_enabled = False
        apply_theme(QApplication.instance(), self.appearance_mode, self._backdrop_enabled)
        try:
            QApplication.instance().styleHints().colorSchemeChanged.connect(self._system_scheme_changed)
        except Exception:
            pass
        self.initialized = False
        self.pending = False
        self.closing = False
        self._native_frame_applied = False
        self._recent_fingerprint = None
        self.setWindowTitle("源镜 · 传播工作台")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setWindowIcon(icon("sparkles", size=32))
        self.resize(1480, 960)
        self.setMinimumSize(1060, 720)
        self.jobs = Jobs(self)
        self.jobs.succeeded.connect(self._result)
        self.jobs.failed.connect(self._error)
        self.jobs.busy_changed.connect(self._busy)
        self.operations = Operations(service.paths, self)
        self.operations.event.connect(self._operation_event)
        self.operations.succeeded.connect(self._operation_result)
        self.operations.failed.connect(self._error)
        self.operations.busy_changed.connect(self._operation_busy)
        self.login_saved = False
        self.has_key = False
        self.enterprise_report_id = None
        self.conversation_to_load = None
        self.start_enterprise_after_save = None
        self.motion_enabled = self.ui_preferences.value("motionEnabled", True, type=bool)
        # 首次使用（未显式设置过）时，动效默认跟随系统「窗口动画」开关。
        if self.ui_preferences.value("motionEnabled") is None:
            try:
                from .winapi import system_animations_enabled
                self.motion_enabled = system_animations_enabled()
            except Exception:
                self.motion_enabled = True
        self.conversation_to_load = self.ui_preferences.value("lastConversation", 0, type=int) or None
        # 边缘缩放过滤器只在真实的 Windows 原生窗口上启用；离屏/测试平台没有原生窗口，
        # 系统缩放/光标调用会连带影响 Qt 状态（测试中出现过 QLabel 构造级联失败）。
        self._resize_filter_active = (sys.platform == "win32"
                                      and QApplication.instance() is not None
                                      and QApplication.instance().platformName() == "windows")
        self._ncm_tracked = False
        self.taskbar = TaskbarProgress(self)
        self._build()
        if self._resize_filter_active:
            QApplication.instance().installEventFilter(self)
        QTimer.singleShot(0, self.refresh)

    def _build(self):
        self.refresh_action = QAction("刷新", self)
        self.refresh_action.setShortcut("Ctrl+R")
        self.refresh_action.triggered.connect(self.refresh)
        folder = QAction("打开数据目录", self)
        folder.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.paths.root))))
        file_menu = self.menuBar().addMenu("文件")
        file_menu.addAction(folder)
        exit_action = file_menu.addAction("退出")
        exit_action.triggered.connect(self.close)
        self.menuBar().addMenu("视图").addAction(self.refresh_action)
        about = self.menuBar().addMenu("帮助").addAction("关于")
        about.triggered.connect(lambda: QMessageBox.about(self, "源镜",
            "源镜 · 传播工作台\n\n结合企业资料与作品表现，生成传播诊断、内容优化和个性化选题。\n"
            "支持人工复核、导出决策记录；保留抖音登录、采集和历史分析。"))
        account_menu = self.menuBar().addMenu("账号")
        self.login_action = account_menu.addAction("登录抖音")
        self.login_action.triggered.connect(lambda: self._start_operation("login"))
        self.menuBar().hide()
        root = QWidget()
        root.setObjectName("workspace")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.title_bar = TitleBar(self)
        self.title_bar.brand.clicked.connect(about.trigger)
        self.connection_state = text("登录未保存", "statusChip")
        self.connection_state.setWordWrap(False)
        self.title_bar.row.addWidget(self.connection_state)
        folder_button = QPushButton()
        folder_button.setObjectName("toolbarButton")
        folder_button.setFixedSize(32, 32)
        folder_button.setIcon(icon("folder", size=18))
        folder_button.setToolTip("打开数据目录")
        folder_button.setAccessibleName("打开数据目录")
        folder_button.clicked.connect(folder.trigger)
        self.title_bar.row.addWidget(folder_button)
        self.refresh_button = QPushButton()
        self.refresh_button.setObjectName("toolbarButton")
        self.refresh_button.setFixedSize(32, 32)
        self.refresh_button.setIcon(icon("refresh", size=18))
        self.refresh_button.setToolTip("刷新本地数据")
        self.refresh_button.setAccessibleName("刷新本地数据")
        self.refresh_button.clicked.connect(self.refresh)
        self.title_bar.row.addWidget(self.refresh_button)
        self.login_button = QPushButton("登录抖音")
        self.login_button.setObjectName("toolbarAccent")
        self.login_button.setIcon(icon("users", size=18))
        self.login_button.clicked.connect(lambda: self._start_operation("login"))
        self.title_bar.row.addWidget(self.login_button)
        appearance_labels = {"light": "浅色", "dark": "深色", "auto": "自动"}
        self.appearance_button = QPushButton(appearance_labels.get(self.appearance_pref, "浅色"))
        self.appearance_button.setObjectName("appearanceToggle")
        self.appearance_button.setToolTip("切换明暗外观")
        self.appearance_button.setAccessibleName("切换明暗外观")
        self.appearance_button.clicked.connect(lambda: self._set_appearance("dark" if self.appearance_mode == "light" else "light"))
        self.title_bar.row.addWidget(self.appearance_button)
        self.title_bar.add_controls()
        root_layout.addWidget(self.title_bar)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(216)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(12, 18, 12, 16)
        side_layout.setSpacing(12)
        self.new_task_button = QPushButton("＋  新建任务")
        self.new_task_button.setObjectName("sidebarNewTask")
        self.new_task_button.setMinimumHeight(40)
        self.new_task_button.clicked.connect(self._new_enterprise_task)
        side_layout.addWidget(self.new_task_button)
        self.nav = QListWidget()
        self.nav.setObjectName("navigation")
        self.nav.setIconSize(QSize(20, 20))
        for name, key in PAGES:
            self.nav.addItem(QListWidgetItem(icon(key), name))
        self.nav.setFixedHeight(352)
        side_layout.addWidget(self.nav)
        profile_button = QPushButton("企业资料    ›")
        profile_button.setObjectName("linkButton")
        profile_button.clicked.connect(lambda: self.enterprise.open_forms(0))
        side_layout.addWidget(profile_button)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        side_layout.addWidget(line)
        side_layout.addWidget(text("最近的任务", "sidebarCaption"))
        self.recent_tasks = QListWidget()
        self.recent_tasks.setObjectName("recentTasks")
        self.recent_tasks.setMinimumHeight(60)
        self.recent_tasks.currentItemChanged.connect(self._select_recent_task)
        side_layout.addWidget(self.recent_tasks, 1)
        self.empty_history = text("暂无传播任务", "muted")
        side_layout.addWidget(self.empty_history)
        self.side_account = text("本地工作空间", "sidebarFooter")
        side_layout.addWidget(self.side_account)
        side_layout.addWidget(text("数据保存在本机", "sidebarCaption"))
        body.addWidget(sidebar)
        content_widget = QWidget()
        content = QVBoxLayout(content_widget)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        self.page_header = QWidget()
        header = QVBoxLayout(self.page_header)
        header.setContentsMargins(28, 24, 28, 12)
        self.heading = label("传播工作台")
        self.heading.setObjectName("heading")
        self.subtitle = text("", "subtitle")
        header.addWidget(self.heading)
        header.addWidget(self.subtitle)
        content.addWidget(self.page_header)
        self.operation_panel, operation_layout = card()
        operation_layout.setContentsMargins(16, 8, 16, 8)
        operation_row = QHBoxLayout()
        self.operation_message = text("", "muted")
        operation_row.addWidget(self.operation_message, 1)
        self.cancel_button = QPushButton("停止操作")
        self.cancel_button.clicked.connect(self.operations.cancel)
        operation_row.addWidget(self.cancel_button)
        operation_layout.addLayout(operation_row)
        self.operation_panel.hide()
        content.addWidget(self.operation_panel)
        self.stack = QStackedWidget()
        content.addWidget(self.stack, 1)
        body.addWidget(content_widget, 1)
        root_layout.addLayout(body, 1)
        self.setCentralWidget(root)
        self.enterprise = HarnessPage()
        self.enterprise.set_motion(self.motion_enabled)
        self.enterprise.task_requested.connect(self._submit_enterprise_task)
        self.enterprise.cancel_requested.connect(self._cancel_chat)
        self.enterprise.workflow_requested.connect(self._submit_workflow)
        self.enterprise.navigate_requested.connect(self._navigate_key)
        self.enterprise.history_changed.connect(self._update_recent_tasks)
        self.enterprise.report_selected.connect(self._highlight_recent_task)
        self.enterprise.conversation_selected.connect(self._highlight_conversation)
        self.enterprise.confirmation_answered.connect(self._confirmation_answered)
        self.enterprise.hot_refresh_requested.connect(self._refresh_hot_board)
        self.enterprise.save_requested.connect(self._save_enterprise)
        self.enterprise.generate_requested.connect(lambda force: self._start_operation("enterprise", {"force": force}))
        self.enterprise.report_requested.connect(self._request_enterprise_report)
        self.enterprise.revision_requested.connect(self._save_enterprise_revision)
        self.enterprise.metrics_requested.connect(self._save_enterprise_metrics)
        self.enterprise.notice.connect(lambda message: self.statusBar().showMessage(message, 10000))
        self.stack.addWidget(self.enterprise)
        self.records = {}
        for key in ("works", "users", "analyses", "tasks"):
            pane = RecordsPage(key, self.refresh)
            pane.layout().setContentsMargins(28, 12, 28, 20)
            self.records[key] = pane
            self.stack.addWidget(pane)
        self.records["works"].work_selected.connect(self._load_work_comments)
        self.records["works"].collect_comments_requested.connect(self._collect_work_comments)
        self.benchmark = BenchmarkPage()
        self.benchmark.check_requested.connect(self._check_benchmarks)
        self.benchmark.add_requested.connect(self._add_benchmark)
        self.benchmark.remove_requested.connect(self._remove_benchmark)
        self.stack.addWidget(self.benchmark)
        self._build_operation_controls()
        self.stack.addWidget(self._settings_page())
        self.stack.addWidget(self._overview_page())
        self.nav.currentRowChanged.connect(self._navigate)
        self.nav.setCurrentRow(0)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(120)
        self.progress.setRange(0, 0)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().addPermanentWidget(QSizeGrip(self))
        self.statusBar().showMessage("正在初始化本地数据…")
        self._shortcuts = []
        for key, slot in (("Ctrl+N", self._new_enterprise_task), ("Ctrl+R", self.refresh_button.click)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(slot)
            self._shortcuts.append(shortcut)
        for position in range(len(PAGES)):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{position + 1}"), self)
            shortcut.activated.connect(lambda index=position: self.nav.setCurrentRow(index))
            self._shortcuts.append(shortcut)

    def _overview_page(self):
        page = QWidget()
        page.setObjectName("overviewBody")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 8, 28, 20)
        layout.setSpacing(20)
        self.account = label("正在读取账号资料…")
        self.account.setObjectName("muted")
        self.quality_summary = text("", "muted")
        intro = QHBoxLayout()
        intro.addWidget(self.account, 1)
        intro.addWidget(text("本地数据概览", "pill"))
        layout.addLayout(intro)
        layout.addWidget(self.quality_summary)
        grid = QGridLayout()
        grid.setSpacing(16)
        self.metrics = {}
        for i, (key, title, note, symbol) in enumerate([
            ("works", "我的作品", "已归档的本人作品", "works"),
            ("users", "互动人数", "去重后的历史互动者", "users"),
            ("analyses", "分析历史", "已保存的报告总数", "analyses"),
            ("pending", "待处理任务", "本地队列中的待办", "tasks")]):
            box = MetricCard(title, note, symbol)
            self.metrics[key] = box.value
            grid.addWidget(box, 0, i)
        layout.addLayout(grid)
        middle = QHBoxLayout()
        middle.setSpacing(16)
        works_card, works_layout = card()
        works_card.setMinimumHeight(320)
        section = QHBoxLayout()
        section.addWidget(text("最近作品", "sectionTitle"), 1)
        see_all = QPushButton("查看全部")
        see_all.clicked.connect(lambda: self.nav.setCurrentRow(1))
        section.addWidget(see_all)
        works_layout.addLayout(section)
        self.recent_model = RecordsModel([("作品标题", "description"), ("点赞", "digg_count"), ("发布时间", "create_time")], self)
        self.recent_table = QTableView()
        self.recent_table.setModel(self.recent_model)
        self.recent_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.recent_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.recent_table.setShowGrid(False)
        self.recent_table.verticalHeader().hide()
        self.recent_table.verticalHeader().setDefaultSectionSize(48)
        self.recent_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.recent_table.setColumnWidth(1, 70)
        self.recent_table.setColumnWidth(2, 150)
        works_layout.addWidget(self.recent_table, 1)
        self.recent_empty = text("还没有作品记录。采集或导入后，作品会显示在这里。", "muted")
        works_layout.addWidget(self.recent_empty)
        middle.addWidget(works_card, 3)
        tasks_card, tasks_layout = card("任务概况", "现有任务的实际状态分布")
        tasks_card.setMinimumHeight(320)
        self.task_summary = TaskSummary()
        tasks_layout.addWidget(self.task_summary)
        tasks_layout.addStretch()
        inspect_tasks = QPushButton("查看任务记录")
        inspect_tasks.clicked.connect(lambda: self.nav.setCurrentRow(4))
        tasks_layout.addWidget(inspect_tasks)
        middle.addWidget(tasks_card, 1)
        layout.addLayout(middle, 3)
        events_card, events_layout = card("最近活动")
        events_card.setFixedHeight(190)
        self.events = QPlainTextEdit()
        self.events.setReadOnly(True)
        events_layout.addWidget(self.events, 1)
        layout.addWidget(events_card, 2)
        self.location = label("")
        self.location.setObjectName("muted")
        self.location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.location)
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setWidget(page)
        return scroller

    def _settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 8, 28, 24)
        settings_card, form = card("分析服务", "配置自己的 DeepSeek 服务，用于后续受众与作品分析。")
        settings_card.setMaximumWidth(800)
        self.key_state = label("正在读取…")
        self.key_state.setWordWrap(False)
        self.key_state.setObjectName("pill")
        form.addWidget(self.key_state, alignment=Qt.AlignmentFlag.AlignLeft)
        self.browser_state = text("", "muted")
        form.addWidget(self.browser_state)
        form.addSpacing(10)
        form.addWidget(text("API Key", "sectionTitle"))
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText("输入新的 API Key；留空保留已保存的 Key")
        form.addWidget(self.key_input)
        form.addWidget(text("模型名称", "sectionTitle"))
        self.model_input = QLineEdit("deepseek-chat")
        form.addWidget(self.model_input)
        self.save_button = QPushButton("保存设置")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self._save)
        form.addSpacing(10)
        form.addWidget(self.save_button, alignment=Qt.AlignmentFlag.AlignLeft)
        form.addWidget(text("保存仅写入本地配置，不会验证或发起付费调用。\n"
                           "生成分析时，所选公开资料和作品摘要会发送至 DeepSeek。", "muted"))
        self.config_location = label("")
        self.config_location.setObjectName("muted")
        self.config_location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addWidget(self.config_location)
        layout.addWidget(settings_card)
        storage_card, storage_layout = card("数据与使用范围")
        storage_card.setMaximumWidth(800)
        storage_layout.addWidget(text("作品、互动者与历史报告保存在本机。窗口顶部可登录抖音，任务记录中可启动采集，分析报告中可生成画像、评价和计划。", "muted"))
        layout.addWidget(storage_card)
        appearance_card, appearance_layout = card("外观", "为整个工作空间选择明暗外观；跟随系统会随 Windows 主题自动切换。")
        appearance_card.setMaximumWidth(800)
        self.appearance_combo = QComboBox()
        self.appearance_combo.setAccessibleName("界面外观")
        self.appearance_combo.addItem("浅色", "light")
        self.appearance_combo.addItem("深色", "dark")
        self.appearance_combo.addItem("跟随系统", "auto")
        self.appearance_combo.setCurrentIndex(self.appearance_combo.findData(self.appearance_pref))
        self.appearance_combo.currentIndexChanged.connect(lambda index: self._set_appearance(self.appearance_combo.itemData(index)))
        appearance_layout.addWidget(self.appearance_combo)
        layout.addWidget(appearance_card)
        motion_card, motion_layout = card("交互动效", "展开、页面切换和处理中状态使用轻量动画。")
        self.motion_toggle = QCheckBox("启用界面动效")
        self.motion_toggle.setChecked(self.motion_enabled)
        self.motion_toggle.toggled.connect(self._set_motion)
        motion_layout.addWidget(self.motion_toggle)
        layout.addWidget(motion_card)
        layout.setSpacing(20)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.settings_tabs = QTabWidget()
        self.settings_tabs.addTab(scroll, "模型与外观")
        self.settings_tabs.addTab(self.enterprise.tabs, "企业资料与指标")
        return self.settings_tabs

    def _navigate(self, index):
        self.heading.setText(PAGES[index][0])
        subtitles = ["结合企业特色与作品表现，制定下一步传播动作。", "查看当前账号作品，缺失指标可在推广页补录。",
                     "了解与作品互动的人，资料来自已采集的公开信息。", "阅读已有画像、作品评价与内容计划。",
                     "追踪任务状态，定位采集过程中的问题。", "登记对标账号，检查他们的最新作品。",
                     "管理分析服务与本地工作空间。", "查看原始账号数据、采集质量和运行记录。"]
        self.subtitle.setText(subtitles[index])
        self.stack.setCurrentIndex(index)
        self.page_header.setVisible(index != 0)
        fade_in(self.stack.currentWidget(), self.motion_enabled)
        # During construction, wait until all widgets are ready.
        if hasattr(self, "progress"):
            self.refresh()

    def _build_operation_controls(self):
        self.operation_buttons = []
        collection = QHBoxLayout()
        self.collect_kind = QComboBox()
        for title, kind in [("快速采集", "quick"), ("重点深采", "deep"), ("账号资料", "fetch_self"), ("互动通知", "fetch_notice"),
                            ("点赞人名单", "fetch_likers"), ("互动者作品", "fetch_user_works")]:
            self.collect_kind.addItem(title, kind)
        collection.addWidget(self.collect_kind)
        collection.addWidget(text("本轮任务上限", "muted"))
        self.collect_limit = QSpinBox()
        self.collect_limit.setRange(1, 200)
        self.collect_limit.setValue(40)
        collection.addWidget(self.collect_limit)
        self.collect_force = QCheckBox("强制刷新缓存")
        collection.addWidget(self.collect_force)
        collection.addStretch()
        start_collection = QPushButton("开始采集")
        start_collection.setObjectName("primary")
        start_collection.clicked.connect(lambda: self._start_operation("collect"))
        collection.addWidget(start_collection)
        self.operation_buttons.append(start_collection)
        self.records["tasks"].layout().insertLayout(0, collection)
        self.records["tasks"].layout().insertWidget(1, text("快速采集：作品与点赞名单；重点深采：为多作品互动者补充样本。已有通知入口仍可单独使用。", "muted"))

        audience = QHBoxLayout()
        self.audience_filter = QComboBox()
        for title, value in [("有效互动者", "active"), ("多作品互动", "repeated"), ("资料待补", "incomplete"),
                             ("暂无作品样本", "unsampled"), ("原始关联记录", "raw")]:
            self.audience_filter.addItem(title, value)
        self.audience_filter.currentIndexChanged.connect(self._audience_changed)
        audience.addWidget(self.audience_filter)
        audience.addStretch()
        self.sample_depth = QComboBox()
        self.sample_depth.addItem("补充12条样本", 12)
        self.sample_depth.addItem("按配置深采", None)
        audience.addWidget(self.sample_depth)
        enrich = QPushButton("补充所选作品")
        enrich.clicked.connect(self._enrich_selected)
        audience.addWidget(enrich)
        self.operation_buttons.append(enrich)
        self.records["users"].layout().insertLayout(0, audience)

        analysis = QHBoxLayout()
        analysis.addWidget(text("画像人数上限", "muted"))
        self.analysis_limit = QSpinBox()
        self.analysis_limit.setRange(1, 200)
        self.analysis_limit.setValue(30)
        analysis.addWidget(self.analysis_limit)
        self.analysis_force = QCheckBox("重新生成已有结果")
        analysis.addWidget(self.analysis_force)
        analysis.addStretch()
        for title, kind in [("分析互动者", "profile"), ("评价我的作品", "review"), ("生成内容计划", "plan")]:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, operation=kind: self._start_operation(operation))
            analysis.addWidget(button)
            self.operation_buttons.append(button)
        self.records["analyses"].layout().insertLayout(0, analysis)
        self.records["analyses"].layout().insertWidget(1, text("生成分析会使用已配置的 DeepSeek 服务并产生调用费用；默认复用未变化的结果。", "muted"))

    def _audience_changed(self):
        self.records["users"].page = 0
        self.refresh()

    def _enrich_selected(self):
        pane = self.records["users"]
        selected = pane.table.selectionModel().selectedRows()
        if not selected:
            self.statusBar().showMessage("请先选择一个互动者")
            return
        uid = pane.model.rows[selected[0].row()]["sec_uid"]
        self._start_operation("collect", {"kinds": "deep", "targets": [uid], "limit": 3,
                                          "works_limit": self.sample_depth.currentData(), "force": False})

    def _start_operation(self, kind, override=None):
        if self.closing or not self.initialized or self.jobs.busy or self.operations.busy:
            self.statusBar().showMessage("请等待当前操作结束")
            return
        if kind in ("profile", "review", "plan", "enterprise", "chat") and not self.has_key:
            self.nav.setCurrentRow(6)
            self.statusBar().showMessage("请先配置自己的 DeepSeek Key")
            return
        if kind in ("collect", "benchmark", "comments") and not self.login_saved:
            self.statusBar().showMessage("请先点击窗口顶部的「登录抖音」")
            self.login_button.setFocus()
            return
        options = {}
        if kind == "collect":
            options = {"kinds": self.collect_kind.currentData(), "limit": self.collect_limit.value(),
                       "force": self.collect_force.isChecked()}
        elif kind in ("profile", "review", "plan"):
            options = {"limit": self.analysis_limit.value(), "force": self.analysis_force.isChecked()}
        if override:
            options.update(override)
        self.operation_message.setText("正在启动操作…")
        if not self.operation_panel.isVisible():
            self.operation_panel.show()
            fade_in(self.operation_panel, self.motion_enabled)
        self.operations.start(kind, options)

    def _operation_event(self, event):
        message = event.get("message")
        if event.get("conversation_id"):
            self.enterprise.conversation_id = event["conversation_id"]
        if event.get("type") == "workflow":
            self.enterprise.workflow_card.apply(event["workflow"], self.operations.busy)
            self.enterprise._scroll_chat_bottom(smooth=False)
            return
        if event.get("type") == "thinking":
            self.enterprise.append_reasoning(event.get("delta") or "")
            return
        if event.get("type") == "answering":
            self.enterprise.mark_answering()
            return
        if event.get("type") == "assigned":
            self.enterprise.set_processing(True, f"「{event.get('name') or '成员'}」接手，正在处理…")
            return
        if event.get("type") == "tool":
            phase = event.get("phase")
            if phase == "confirm":
                self.enterprise.show_confirmation(event)
                waiting = f"等待你确认：「{event.get('name') or event.get('tool')}」"
                self.enterprise.set_processing(True, waiting)
                self.operation_message.setText(waiting)
                self.statusBar().showMessage(waiting)
                return
            if phase == "confirm_done":
                self.enterprise.resolve_confirmation(event)
                self.enterprise.set_processing(True,
                                               "已允许，继续执行…" if event.get("approved") else "已拒绝，继续对话…")
                return
            if phase == "start":
                self.enterprise.set_processing(True, f"{event.get('name') or event.get('tool')} 执行中…")
            else:
                summary = str(event.get("summary") or "")
                self.enterprise.set_processing(True, summary or "工具执行完成")
            return
        if self.enterprise.processing and "phase" not in event and message:
            self.enterprise.set_processing(True, message)
        if "phase" in event:
            self.enterprise.phase(event["phase"], message or "")
        if event.get("type") == "start_item":
            message = f"正在分析互动者 {event['index']}/{event['total']}…"
        elif event.get("type") == "task":
            state = LABELS.get(event.get("collection_state")) or ("成功" if event.get("ok") else ("暂停" if event.get("blocked") else "失败"))
            message = f"第 {event.get('attempted', 0)} 个任务 · {LABELS.get(event.get('kind'), event.get('kind'))}：{state}"
        if message:
            self.operation_message.setText(str(message))
            self.statusBar().showMessage(str(message))

    def _operation_result(self, result):
        self.operation_message.setText(result["message"])
        if result.get("kind") == "enterprise" and result.get("report_id"):
            self.enterprise_report_id = result["report_id"]
            self.enterprise.right_tabs.setCurrentIndex(1)
        if result.get("kind") == "enterprise":
            self.enterprise.set_processing(False, result["message"])
        if result.get("kind") == "chat":
            if result.get("cancelled"):
                # 停止时不丢弃已产生的思考过程，保留为"思考已停止"供回看。
                self.enterprise.end_reasoning(stopped=True)
                if self.enterprise.conversation_id:
                    self.conversation_to_load = self.enterprise.conversation_id
            elif result.get("conversation"):
                self.enterprise.apply_conversation(result["conversation"])
                self.ui_preferences.setValue("lastConversation", result["conversation"]["id"])
            if result.get("report_id"):
                self.enterprise_report_id = result["report_id"]
                self.enterprise.right_tabs.setCurrentIndex(1)
            self.enterprise.set_processing(False)
        self.pending = True
        QTimer.singleShot(3000, self._hide_operation_panel)

    def _hide_operation_panel(self):
        # 操作结束后收起顶部操作条；失败信息由 _error 保留显示。
        if not self.operations.busy and self.operation_panel.isVisible():
            self.operation_panel.hide()

    def _confirmation_answered(self, request_id, approved):
        # 界面里的用户点了允许/拒绝 → 回送给 worker 线程里等待的确认请求
        self.operations.broker.resolve(request_id, approved)

    def _load_hot_board(self):
        panel = self.enterprise.hot_panel
        if os.environ.get("QT_QPA_PLATFORM", "").startswith("offscreen"):
            return  # 离屏模式（测试 / 预览截图）不自动拉热点
        if self.closing or not self.initialized or self.jobs.busy or self.operations.busy:
            return
        panel.loaded_once = True
        panel.set_loading()
        self.jobs.submit(lambda: ("hotboard", None, self.service.hot_board()))

    def _refresh_hot_board(self):
        if self.jobs.busy or self.operations.busy:
            self.statusBar().showMessage("请等待当前操作结束")
            return
        self.enterprise.hot_panel.set_loading()
        self.jobs.submit(lambda: ("hotboard", None, self.service.hot_board()))

    def _operation_busy(self, busy):
        self.cancel_button.setEnabled(busy)
        self.taskbar.set_state("busy" if busy else "idle")
        if busy and self.operations.thread.kind in ("enterprise", "chat"):
            self.enterprise.set_processing(True, "正在准备本次传播任务…")
        elif not busy and self.enterprise.processing:
            self.enterprise.set_processing(False)
        self._busy(self.jobs.busy)

    def refresh(self):
        if self.closing:
            return
        if self.jobs.busy:
            self.pending = True
            return
        if not self.initialized:
            self.jobs.submit(lambda: ("overview", None, self.service.initialize()))
            return
        key = PAGES[self.nav.currentRow()][1]
        if key == "enterprise":
            if self.conversation_to_load is not None:
                conversation_id = self.conversation_to_load
                self.conversation_to_load = None
                self.jobs.submit(lambda: ("conversation", None, self.service.conversation(conversation_id)))
            elif self.enterprise_report_id is not None:
                report_id = self.enterprise_report_id
                self.enterprise_report_id = None
                self.jobs.submit(lambda: ("enterprise_report", None, self.service.enterprise_report(report_id)))
            else:
                self.jobs.submit(lambda: ("enterprise", None, self.service.enterprise_workspace()))
        elif key in self.records:
            pane = self.records[key]
            search, page = pane.search.text(), pane.page
            if key == "users":
                segment = self.audience_filter.currentData()
                self.jobs.submit(lambda: (key, search, self.service.page(key, search, page, segment)))
            else:
                self.jobs.submit(lambda: (key, search, self.service.page(key, search, page)))
        elif key == "benchmark":
            self.jobs.submit(lambda: ("benchmark", None, self.service.benchmarks()))
        else:
            self.jobs.submit(lambda: ("overview", None, self.service.overview()))

    def _save(self):
        key, model = self.key_input.text(), self.model_input.text()
        self.jobs.submit(lambda: ("settings", None, self.service.save_settings(key, model)))

    def _save_enterprise(self, profile):
        self.jobs.submit(lambda: ("enterprise_saved", None, self.service.save_enterprise(profile)))

    def _request_enterprise_report(self, report_id):
        self.enterprise_report_id = report_id
        if self.jobs.busy:
            self.pending = True
        else:
            self.refresh()

    def _save_enterprise_revision(self, data):
        self.jobs.submit(lambda: ("enterprise_revision", None, self.service.revise_enterprise(**data)))

    def _save_enterprise_metrics(self, data):
        self.jobs.submit(lambda: ("enterprise", None, self.service.save_enterprise_metrics(data)))

    def _submit_enterprise_task(self, request, force):
        if self.closing or not self.initialized or self.jobs.busy or self.operations.busy:
            return
        if not self.has_key:
            self.enterprise.show_chat_error("尚未配置模型密钥。请在设置的“模型与外观”中保存 DeepSeek Key，再发送消息。")
            return
        self.enterprise.append_pending(request)
        self._start_operation("chat", {"request": request, "conversation_id": self.enterprise.conversation_id, "want_plan": force})

    def _cancel_chat(self):
        if self.operations.busy:
            self.operations.cancel()
            self.statusBar().showMessage("正在停止…")

    def _submit_workflow(self, run_id, rerun):
        if self.closing or not self.initialized or self.jobs.busy or self.operations.busy:
            return
        run = self.enterprise.workflow_card.run
        if not run or run["id"] != run_id or not self.has_key:
            return
        self.enterprise.set_processing(True, "正在按最新数据重做…" if rerun else "正在继续未完成步骤…")
        self.enterprise.begin_reasoning()
        self._start_operation("chat", {"request": run["request"], "conversation_id": self.enterprise.conversation_id,
                                       "workflow_run_id": run_id, "rerun": rerun})

    def _navigate_key(self, key):
        self.nav.setCurrentRow(next(i for i, item in enumerate(PAGES) if item[1] == key))

    def _load_work_comments(self, aweme_id):
        if self.closing or not self.initialized or self.jobs.busy or self.operations.busy:
            return
        self.jobs.submit(lambda: ("work_comments", aweme_id, self.service.comments(aweme_id)))

    def _collect_work_comments(self, aweme_id):
        self._start_operation("comments", {"aweme_id": aweme_id})

    def _check_benchmarks(self, sec_uid):
        self._start_operation("benchmark", {"sec_uid": sec_uid or None})

    def _add_benchmark(self, text):
        try:
            result = self.service.add_benchmark(text)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc), 8000)
            return
        self.statusBar().showMessage("已添加对标账号" if result["created"] else "该账号已在名单中", 6000)
        if self.nav.currentRow() == 5:
            self.refresh()

    def _remove_benchmark(self, sec_uid):
        account = next((a for a in self.benchmark.accounts if a["sec_uid"] == sec_uid), None)
        name = (account or {}).get("display_name") or sec_uid[:14]
        answer = QMessageBox.question(
            self, "移出对标名单", f"将「{name}」移出对标名单？已采集的作品数据不受影响。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.service.remove_benchmark(sec_uid)
        if self.nav.currentRow() == 5:
            self.refresh()

    def _new_enterprise_task(self):
        self.nav.setCurrentRow(0)
        self.enterprise.new_task()
        self.ui_preferences.remove("lastConversation")
        self._highlight_recent_task(-1)

    def _update_recent_tasks(self, reports):
        fingerprint = tuple((report.get("kind", "report"), report["id"], report["title"],
                             report.get("reviewed"), report["created_at"]) for report in reports)
        if fingerprint != self._recent_fingerprint:
            # 内容没变就不重建列表，避免每次保存/刷新都闪一下。
            self._recent_fingerprint = fingerprint
            self.recent_tasks.blockSignals(True)
            self.recent_tasks.clear()
            for report in reports:
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, (report.get("kind", "report"), report["id"]))
                item.setSizeHint(QSize(178, 66))
                panel = QWidget()
                panel.setStyleSheet("background: transparent;")
                layout = QVBoxLayout(panel)
                layout.setContentsMargins(10, 8, 10, 8)
                layout.setSpacing(4)
                title = ElidedLabel(report["title"], "historyTitle")
                title.setFixedHeight(22)
                layout.addWidget(title)
                state = "对话" if report.get("kind") == "conversation" else ("已复核" if report.get("reviewed") else "待复核")
                metadata = ElidedLabel(state + " · " + report_time(report["created_at"]), "historyMeta")
                layout.addWidget(metadata)
                panel.setToolTip(report["title"])
                self.recent_tasks.addItem(item)
                self.recent_tasks.setItemWidget(item, panel)
            self.empty_history.setVisible(not reports)
            self.recent_tasks.blockSignals(False)
        if self.enterprise.conversation_id:
            self._highlight_conversation(self.enterprise.conversation_id)
        elif self.enterprise.current_report:
            self._highlight_recent_task(self.enterprise.current_report["id"])

    def _select_recent_task(self, current, previous=None):
        if current is None:
            return
        kind, record_id = current.data(Qt.ItemDataRole.UserRole)
        if self.enterprise.report_dirty and not self.enterprise._discard_report_changes():
            self._highlight_recent_task(self.enterprise.current_report["id"])
            return
        self.enterprise.report_dirty = False
        self.enterprise.new_task_mode = False
        self.nav.setCurrentRow(0)
        if kind == "conversation":
            self.conversation_to_load = record_id
            self.refresh()
        else:
            self.enterprise.conversation_id = None
            self.enterprise.conversation_data = None
            self.enterprise.workflow_card.apply(None)
            self._request_enterprise_report(record_id)

    def _highlight_recent_task(self, report_id):
        self.recent_tasks.blockSignals(True)
        self.recent_tasks.setCurrentRow(-1)
        for index in range(self.recent_tasks.count()):
            if self.recent_tasks.item(index).data(Qt.ItemDataRole.UserRole) == ("report", report_id):
                self.recent_tasks.setCurrentRow(index)
                break
        self.recent_tasks.blockSignals(False)

    def _highlight_conversation(self, conversation_id):
        self.recent_tasks.blockSignals(True)
        self.recent_tasks.setCurrentRow(-1)
        for index in range(self.recent_tasks.count()):
            if self.recent_tasks.item(index).data(Qt.ItemDataRole.UserRole) == ("conversation", conversation_id):
                self.recent_tasks.setCurrentRow(index)
                break
        self.recent_tasks.blockSignals(False)

    def _system_appearance(self):
        """跟随系统：Windows 深色主题返回 dark，其余（含未知）返回 light。"""
        try:
            scheme = QApplication.styleHints().colorScheme()
        except Exception:
            return "light"
        return "dark" if scheme == Qt.ColorScheme.Dark else "light"

    def _system_scheme_changed(self, *_args):
        if getattr(self, "appearance_pref", "light") == "auto":
            self._set_appearance("auto")

    def _set_appearance(self, mode):
        if mode not in ("light", "dark", "auto"):
            return
        resolved = self._system_appearance() if mode == "auto" else mode
        self.appearance_pref = mode
        self.appearance_mode = resolved
        self.ui_preferences.setValue("appearance", mode)
        if QApplication.instance().property("scoutTheme") != resolved:
            apply_theme(QApplication.instance(), resolved, self._backdrop_enabled)
            if self.isVisible():
                fade_in(self, self.motion_enabled, start=0.7, duration=150)
            if self._native_frame_applied:
                self._sync_dwm_theme()
        labels = {"light": "浅色", "dark": "深色", "auto": "自动"}
        self.appearance_button.setText(labels[mode])
        self.appearance_button.setToolTip("切换明暗外观" if mode != "auto" else "跟随系统外观")
        self.appearance_combo.blockSignals(True)
        self.appearance_combo.setCurrentIndex(self.appearance_combo.findData(mode))
        self.appearance_combo.blockSignals(False)
        for page in self.records.values():
            if page.model.rowCount():
                page.model.dataChanged.emit(page.model.index(0, 0), page.model.index(page.model.rowCount() - 1, page.model.columnCount() - 1))
        names = {"light": "浅色", "dark": "深色", "auto": "自动（跟随系统）"}
        self.statusBar().showMessage(f"已切换为{names[mode]}外观", 3000)

    def _set_motion(self, enabled):
        self.motion_enabled = enabled
        self.ui_preferences.setValue("motionEnabled", enabled)
        self.ui_preferences.sync()
        self.enterprise.set_motion(enabled)
        if not enabled:
            for index in range(self.stack.count()):
                fade_in(self.stack.widget(index), False)

    def _settings(self, data):
        self.has_key = data["configured"]
        self.saved_model = data["model"]
        limit = max(1, data.get("quick_works_limit", 12))
        self.sample_depth.setItemText(0, f"补充{limit}条样本")
        self.sample_depth.setItemData(0, limit)
        self.key_state.setText(f"密钥已配置 · {data['masked']}" if data["configured"] else "尚未配置密钥")
        self.browser_state.setText(f"采集浏览器：{data['browser']}")
        self.model_input.setText(data["model"])
        self.config_location.setText(f"配置位置：{data['config_file']}")
        self.connection_state.setText(("模型已配置" if self.has_key else "模型未配置") + " · " + ("抖音登录态已保存" if self.login_saved else "抖音未登录"))

    def _result(self, result):
        key, search, data = result
        if key == "overview":
            self.initialized = True
            for name, widget in self.metrics.items():
                widget.setText(f"{data[name]:,}")
            nickname = data["self"].get("nickname")
            self.account.setText(f"已有账号资料：{nickname}" if nickname else "尚未采集账号资料")
            self.side_account.setText(nickname or "本地工作空间")
            self.login_saved = data["login"]["saved"]
            self.connection_state.setText("登录态已保存 · 待验证" if self.login_saved else "登录未保存")
            self.login_button.setText("重新登录" if self.login_saved else "登录抖音")
            self.login_button.setToolTip(data["login"]["message"])
            if self.login_saved:
                self.account.setText(f"已保存登录态 · {nickname or '你的抖音账号'}（使用前会验证）")
            self.task_summary.update_counts(data["task_counts"])
            quality = data["quality"]
            self.quality_summary.setText(f"质量检查 · 有效互动者 {quality['active_users']} · 多作品互动 {quality['repeated_users']} · "
                f"待补资料 {quality['incomplete_profiles']} · 去重关系 {quality['valid_edges']} · 待核验关联 {quality['invalid_edges']}")
            self.recent_model.replace(data["recent_works"])
            self.recent_empty.setVisible(not data["recent_works"])
            self.recent_table.setVisible(bool(data["recent_works"]))
            self.events.setPlainText("\n\n".join(f"{display_value('created_at', e['ts'])}  ·  {e['message']}" for e in data["events"][:5])
                                     or "暂无运行记录。已有数据将在采集或导入后出现在这里。")
            self.location.setText(f"数据目录：{data['paths']['root']}")
            self._settings(data["settings"])
            if self.nav.currentRow() == 0 and "enterprise" in data:
                self.enterprise.apply_workspace(data["enterprise"])
                if self.conversation_to_load:
                    ids = {c["id"] for c in data["enterprise"].get("conversations", [])}
                    if self.conversation_to_load in ids:
                        self.pending = True
                    else:
                        self.conversation_to_load = None
                        self.ui_preferences.remove("lastConversation")
            elif self.nav.currentRow() not in (6, 7):
                self.pending = True
            if not self.enterprise.hot_panel.loaded_once:
                QTimer.singleShot(300, self._load_hot_board)
        elif key in ("enterprise", "enterprise_saved", "enterprise_submit"):
            self.enterprise.apply_workspace(data, saved=key in ("enterprise_saved", "enterprise_submit"))
            if key == "enterprise_submit":
                self.start_enterprise_after_save = bool(search)
        elif key in ("enterprise_report", "enterprise_revision"):
            self.enterprise.apply_report(data)
            if key == "enterprise_report":
                self.pending = True
        elif key == "conversation":
            self.enterprise.apply_conversation(data)
            self.ui_preferences.setValue("lastConversation", data["id"])
            if data.get("report_id"):
                self.enterprise_report_id = data["report_id"]
            else:
                self.enterprise.current_report = None
                self.enterprise._empty_plan()
            self.pending = True
        elif key == "settings":
            self.key_input.clear()
            self._settings(data)
        elif key == "hotboard":
            self.enterprise.hot_panel.apply(data)
            return
        elif key == "benchmark":
            self.benchmark.apply(data)
        elif key == "work_comments":
            self.records["works"].apply_comments(data)
        elif self.records[key].search.text() == search:
            self.records[key].apply(data)
        else:
            self.pending = True
        self.statusBar().showMessage("设置已保存（尚未验证连通性）" if key == "settings" else "本地数据已更新", 6000)

    def _error(self, error):
        self.start_enterprise_after_save = None
        if self.enterprise.processing:
            self.enterprise.set_processing(False, "本次任务未完成：" + error)
        if self.operations.busy:
            self.operation_message.setText(error)
        self.statusBar().showMessage("操作失败，可刷新重试")
        is_chat = self.operations.busy and self.operations.thread.kind == "chat"
        if is_chat:
            self.enterprise.show_chat_error(error)
        elif not self.closing:
            QMessageBox.warning(self, "操作失败", error)

    def _busy(self, busy):
        active = busy or self.operations.busy
        # 对话场景的等待进度由聊天框里的"思考中"面板承担，不再用右下角进度条。
        chat_running = self.operations.busy and self.operations.thread is not None and self.operations.thread.kind == "chat"
        self.enterprise.set_controls_enabled(self.initialized and not active)
        self.new_task_button.setEnabled(self.initialized and not active)
        self.recent_tasks.setEnabled(self.initialized and not active)
        self.benchmark.setEnabled(self.initialized and not active)
        self.refresh_action.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy)
        self.save_button.setEnabled(not active)
        self.key_input.setEnabled(not active)
        self.model_input.setEnabled(not active)
        self.login_button.setEnabled(self.initialized and not active)
        self.login_action.setEnabled(self.initialized and not active)
        for button in self.operation_buttons:
            button.setEnabled(self.initialized and not active)
        self.progress.setVisible(active and not chat_running)
        for pane in self.records.values():
            pane.previous.setEnabled(not busy and pane.page > 0)
            pane.next.setEnabled(not busy and (pane.page + 1) * 100 < pane.total)
        if busy:
            self.statusBar().showMessage("正在处理…")
        elif self.closing and not self.operations.busy:
            QTimer.singleShot(0, self.close)
        elif not active and self.start_enterprise_after_save is not None:
            force = self.start_enterprise_after_save
            self.start_enterprise_after_save = None
            QTimer.singleShot(0, lambda: self._start_operation("enterprise", {"force": force}))
        elif self.pending:
            self.pending = False
            QTimer.singleShot(0, self.refresh)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._native_frame_applied:
            self._native_frame_applied = True
            self._apply_native_frame()
            self._sync_dwm_theme()

    def _apply_native_frame(self):
        """Windows：补回 WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX。

        无边框窗口（FramelessWindowHint）会连同这些样式一起移除：没有
        最小化 / 最大化标记时，系统连最小化、还原的过渡动画都不会提供，
        缩放也只能靠状态栏角落的 QSizeGrip、而且没有系统阴影。
        恢复样式后，边缘/角落拖拽缩放、缩放光标、贴边分屏、最小化与还原
        动画都交回系统处理；nativeEvent 里的 WM_NCCALCSIZE 返回 0，保证
        客户区仍是整个窗口矩形，界面不会因此多出边框。
        最后向 Windows 11 请求标准窗口圆角（DWMWA_WINDOW_CORNER_PREFERENCE，
        最大化时系统自动切直角），旧系统不认识该属性，返回错误码即可忽略。
        非 Windows 平台保留 QSizeGrip 兜底。
        """
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            gwl_style = -16
            ws_caption, ws_thickframe = 0x00C00000, 0x00040000
            ws_minimizebox, ws_maximizebox = 0x00020000, 0x00010000
            style = user32.GetWindowLongW(hwnd, gwl_style)
            user32.SetWindowLongW(hwnd, gwl_style,
                                  style | ws_caption | ws_thickframe | ws_minimizebox | ws_maximizebox)
            # 让系统按新样式重算窗口框架：不移动/不改尺寸/不换层/不激活。
            swp_nosize, swp_nomove, swp_nozorder, swp_noactivate, swp_framechanged = 0x0001, 0x0002, 0x0004, 0x0010, 0x0020
            user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                                swp_nosize | swp_nomove | swp_nozorder | swp_noactivate | swp_framechanged)
            # Windows 11 圆角：2 = DWMWCP_ROUND（系统标准半径）。
            preference = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(preference), ctypes.sizeof(preference))
            # Win11 22H2+：Mica 背景板铺满整窗（失败自动保持纯色）。
            if getattr(self, "_backdrop_enabled", False):
                from .winapi import apply_backdrop
                apply_backdrop(hwnd)
        except Exception:
            pass

    def nativeEvent(self, eventType, message):
        if sys.platform == "win32" and bytes(eventType) == b"windows_generic_MSG":
            try:
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0083 and msg.wParam:  # WM_NCCALCSIZE（wParam=TRUE）
                    # 客户区 = 整个窗口矩形；补回的框架样式不缩小界面，也不产生可见标题栏。
                    return True, 0
                if msg.message == 0x0084:  # WM_NCHITTEST
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                    # 最大化键交给系统命中：Win11 悬停弹出 Snap 布局浮层，
                    # 点击由 DefWindowProc 按系统命令处理（带原生动画）。
                    if self._caption_button_code(x, y):
                        return True, 9  # HTMAXBUTTON
                    # 客户区铺满整窗口后，边缘缩放命中要自己交回系统。
                    if not (self.isMaximized() or self.isFullScreen()):
                        code = self._resize_hit(x, y)
                        if code:
                            return True, code
                elif msg.message == 0x00A0:  # WM_NCMOUSEMOVE：维护最大化键悬停态
                    self._track_max_button_hover(bool(msg.wParam == 9))
                elif msg.message == 0x02A3:  # WM_NCMOUSELEAVE
                    self._ncm_tracked = False
                    self._track_max_button_hover(False, pressed=False)
                elif msg.message in (0x00A1, 0x00A2) and msg.wParam == 9:
                    # 按下/抬起只更新视觉，不腰断消息：让 DefWindowProc 走系统命令
                    self._track_max_button_hover(True, pressed=msg.message == 0x00A1)
            except Exception:
                pass
        return super().nativeEvent(eventType, message)

    def _resize_hit(self, screen_x, screen_y):
        """WM_NCHITTEST 通道：把屏幕物理坐标换成 Win32 命中码，不在边缘返回 None。"""
        from PySide6.QtCore import QPoint
        ratio = self.devicePixelRatioF() or 1.0
        edges = self._hit_edges(QPoint(round(screen_x / ratio), round(screen_y / ratio)))
        if edges is None:
            return None
        if edges & Qt.Edge.LeftEdge and edges & Qt.Edge.TopEdge:
            return 13  # HTTOPLEFT
        if edges & Qt.Edge.RightEdge and edges & Qt.Edge.TopEdge:
            return 14  # HTTOPRIGHT
        if edges & Qt.Edge.LeftEdge and edges & Qt.Edge.BottomEdge:
            return 16  # HTBOTTOMLEFT
        if edges & Qt.Edge.RightEdge and edges & Qt.Edge.BottomEdge:
            return 17  # HTBOTTOMRIGHT
        if edges & Qt.Edge.LeftEdge:
            return 10  # HTLEFT
        if edges & Qt.Edge.RightEdge:
            return 11  # HTRIGHT
        if edges & Qt.Edge.TopEdge:
            return 12  # HTTOP
        return 15  # HTBOTTOM

    def _caption_button_code(self, screen_x: int, screen_y: int):
        """屏幕物理坐标是否落在最大化键上（HTMAXBUTTON → Win11 Snap 布局悬停浮层）。"""
        if self.isFullScreen():
            return None
        button = getattr(self.title_bar, "max_button", None)
        if button is None or not button.isVisible():
            return None
        from PySide6.QtCore import QPoint
        ratio = self.devicePixelRatioF() or 1.0
        pos = QPoint(round(screen_x / ratio), round(screen_y / ratio))
        return True if button.rect().contains(button.mapFromGlobal(pos)) else None

    def _track_max_button_hover(self, hover: bool, pressed=None):
        """最大化键转入非客户区后，悬停 / 按压态由属性选择器维护。"""
        button = getattr(self.title_bar, "max_button", None)
        if button is None:
            return
        if hover and not self._ncm_tracked:
            self._ncm_tracked = True
            try:
                import ctypes
                from ctypes import wintypes

                class TRACKMOUSEEVENT(ctypes.Structure):
                    _fields_ = [("cbSize", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                                ("hwndTrack", wintypes.HWND), ("dwHoverTime", wintypes.DWORD)]

                track = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), 0x0002 | 0x0010,
                                        wintypes.HWND(int(self.winId())), 0)
                ctypes.windll.user32.TrackMouseEvent(ctypes.byref(track))
            except Exception:
                pass
        changes = {}
        if button.property("nativeHover") != bool(hover):
            changes["nativeHover"] = bool(hover)
        if pressed is not None and button.property("nativePressed") != bool(pressed):
            changes["nativePressed"] = bool(pressed)
        if not changes:
            return
        for name, value in changes.items():
            button.setProperty(name, value)
        style = button.style()
        style.unpolish(button)
        style.polish(button)

    def _sync_dwm_theme(self):
        """Win11：窗口边框色与深色标记跟随应用主题（不支持的系统静默忽略）。"""
        if sys.platform != "win32":
            return
        try:
            from .appearance import color, theme_name
            from .winapi import available, set_border_color, set_dark_titlebar
            if not available():
                return  # 离屏 / 测试平台没有真实 HWND，不能碰 DWM
            hwnd = int(self.winId())
            set_border_color(hwnd, color("border"))
            set_dark_titlebar(hwnd, theme_name() == "dark")
        except Exception:
            pass

    def _hit_edges(self, global_pos):
        """全局逻辑坐标是否落在窗口边缘缩放带（6px）；命中返回 Qt.Edge 组合，否则 None。"""
        if self.isMaximized() or self.isFullScreen():
            return None
        pos = self.mapFromGlobal(global_pos)
        border = 6
        left = pos.x() < border
        right = pos.x() >= self.width() - border
        top = pos.y() < border
        bottom = pos.y() >= self.height() - border
        if left and top:
            return Qt.Edge.LeftEdge | Qt.Edge.TopEdge
        if right and top:
            return Qt.Edge.RightEdge | Qt.Edge.TopEdge
        if left and bottom:
            return Qt.Edge.LeftEdge | Qt.Edge.BottomEdge
        if right and bottom:
            return Qt.Edge.RightEdge | Qt.Edge.BottomEdge
        if left:
            return Qt.Edge.LeftEdge
        if right:
            return Qt.Edge.RightEdge
        if top:
            return Qt.Edge.TopEdge
        if bottom:
            return Qt.Edge.BottomEdge
        return None

    def eventFilter(self, watched, event):
        """鼠标靠近窗口边缘时给缩放光标，按下就交给系统开始缩放。

        无边框窗口客户区铺满整窗，系统自带的边缘命中被绕开；
        这里用 Qt 官方的 startSystemResize 作为原生命中通道之外的保险。
        """
        if getattr(self, "_resize_filter_active", False) and not self.closing:
            kind = event.type()
            if kind in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.Leave):
                widget = watched if isinstance(watched, QWidget) else None
                if widget is not None and widget.window() is self:
                    if kind is QEvent.Type.Leave or self.isMaximized() or self.isFullScreen():
                        self._clear_edge_cursor()
                    else:
                        edges = self._hit_edges(event.globalPosition().toPoint())
                        if edges is None:
                            self._clear_edge_cursor()
                        elif kind is QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                            self.windowHandle().startSystemResize(edges)
                            return True
                        else:
                            self._set_edge_cursor(widget, edges)
        return super().eventFilter(watched, event)

    def _set_edge_cursor(self, widget, edges):
        left = bool(edges & Qt.Edge.LeftEdge)
        right = bool(edges & Qt.Edge.RightEdge)
        top = bool(edges & Qt.Edge.TopEdge)
        bottom = bool(edges & Qt.Edge.BottomEdge)
        if (left and top) or (right and bottom):
            shape = Qt.CursorShape.SizeFDiagCursor
        elif (right and top) or (left and bottom):
            shape = Qt.CursorShape.SizeBDiagCursor
        elif left or right:
            shape = Qt.CursorShape.SizeHorCursor
        else:
            shape = Qt.CursorShape.SizeVerCursor
        held = getattr(self, "_edge_cursor_widget", None)
        if held is not None and held is not widget:
            self._clear_edge_cursor()
        self._edge_cursor_widget = widget
        if widget.cursor().shape() != shape:
            widget.setCursor(shape)

    def _clear_edge_cursor(self):
        held = getattr(self, "_edge_cursor_widget", None)
        if held is not None:
            held.unsetCursor()
            self._edge_cursor_widget = None

    def closeEvent(self, event):
        if not self.closing and (self.enterprise.profile_dirty or self.enterprise.report_dirty):
            answer = QMessageBox.question(self, "有未保存的修改", "企业资料或人工稿尚未保存。是否放弃修改并退出？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.closing = True
        if self.jobs.busy or self.operations.busy:
            self.setEnabled(False)
            self.operations.cancel()
            self.statusBar().showMessage("正在完成当前操作后退出…")
            event.ignore()
        else:
            self.pending = False
            if self.enterprise.forms_dialog:
                self.enterprise.forms_dialog.hide()
            super().closeEvent(event)
