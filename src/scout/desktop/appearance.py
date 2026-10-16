"""Shared light and dark colors for the native desktop interface."""
from __future__ import annotations

from string import Template

from PySide6.QtWidgets import QApplication


THEMES = {
    "light": {
        "window": "#F6F7FA", "surface": "#FFFFFF", "sidebar": "#E9EEF5", "sidebar_end": "#E2E8F0",
        "toolbar": "#F8F9FC", "subtle": "#F3F5F8", "hover": "#EAF0F8", "pressed": "#DEE7F3",
        "text": "#202632", "muted": "#596575", "faint": "#626D7B", "border": "#DCE2EA",
        "accent": "#007AFF", "accent_hover": "#0069E0", "accent_pressed": "#0058BD", "on_accent": "#FFFFFF",
        "accent_soft": "#EAF3FF", "selection": "#DCE9FA", "disabled": "#A2AAB6", "disabled_bg": "#EDF0F4",
        "user": "#EAF3FF", "assistant": "#F7F9FC", "scroll": "#BCC5D2", "success": "#12754E",
        "warning": "#946000", "warning_bg": "#FFF5DE", "danger": "#BD3850", "danger_bg": "#FFF0F2",
        "success_bg": "#E8F5EE", "shadow": "#D7E0EC", "code": "#EDF1F6",
    },
    "dark": {
        "window": "#1D1F23", "surface": "#24272D", "sidebar": "#252B34", "sidebar_end": "#20252D",
        "toolbar": "#292D34", "subtle": "#2D323A", "hover": "#343D4B", "pressed": "#3D485A",
        "text": "#EDF1F7", "muted": "#ADB7C7", "faint": "#96A3B6", "border": "#3B424E",
        "accent": "#0A84FF", "accent_hover": "#3197FF", "accent_pressed": "#006BDD", "on_accent": "#FFFFFF",
        "accent_soft": "#243C59", "selection": "#314D70", "disabled": "#788496", "disabled_bg": "#2D323B",
        "user": "#263D59", "assistant": "#2A2F37", "scroll": "#556174", "success": "#6DD5A5",
        "warning": "#F0C674", "warning_bg": "#3B3323", "danger": "#FF9BAC", "danger_bg": "#442C34",
        "success_bg": "#253E35", "shadow": "#15181E", "code": "#303743",
    },
}


def theme_name():
    app = QApplication.instance()
    value = app.property("scoutTheme") if app else "light"
    return value if value in THEMES else "light"


def color(name, mode=None):
    return THEMES[mode if mode in THEMES else theme_name()][name]


def style_sheet(mode="light"):
    return Template(_STYLE).substitute(THEMES[mode if mode in THEMES else "light"])


_STYLE = """
QWidget { color: $text; background: transparent; font-size: 14px; }
QMainWindow, QWidget#workspace, QWidget#overviewBody { background: $window; }
QWidget#titleBar { background: $toolbar; border-bottom: 1px solid $border; }
QPushButton#appBrand { background: transparent; border: none; color: $text; font-size: 15px; font-weight: 600; padding: 3px 8px; }
QWidget#sidebar { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 $sidebar,stop:1 $sidebar_end); border-right: 1px solid $border; }
QLabel { background: transparent; }
QLabel#heading { font-size: 27px; font-weight: 600; color: $text; }
QLabel#taskHeading { font-size: 24px; font-weight: 600; color: $text; }
QLabel#planHeading { font-size: 25px; font-weight: 600; color: $text; }
QLabel#sectionTitle, QLabel#speaker { font-size: 14px; font-weight: 600; color: $text; }
QLabel#topicTitle { font-size: 17px; font-weight: 600; color: $text; }
QLabel#bodyText { color: $text; font-size: 14px; }
QLabel#muted, QLabel#subtitle, QLabel#composerHint, QLabel#agentName, QLabel#metricNote { color: $muted; font-size: 12px; }
QLabel#sidebarCaption { color: $muted; font-size: 11px; }
QLabel#sidebarFooter { color: $text; font-size: 12px; font-weight: 600; }
QLabel#historyTitle { color: $text; font-size: 12px; font-weight: 500; }
QLabel#historyMeta { color: $muted; font-size: 11px; }
QLabel#metricValue { color: $text; font-size: 32px; font-weight: 600; }
QLabel#metricTitle { color: $muted; font-size: 12px; }
QLabel#statusDot { background: $muted; border-radius: 4px; }
QLabel#statusDot[status="done"] { background: $success; }
QLabel#statusDot[status="pending"] { background: $warning; }
QLabel#statusDot[status="running"] { background: $accent; }
QLabel#statusDot[status="failed"] { background: $danger; }
QLabel#pill { background: $accent_soft; color: $accent; padding: 5px 9px; border-radius: 6px; font-size: 12px; }
QListWidget#navigation { background: transparent; border: none; outline: none; color: $text; }
QListWidget#navigation::item { padding: 9px 10px; margin: 1px 0; border-radius: 7px; }
QListWidget#navigation::item:selected { background: $accent; color: $on_accent; }
QListWidget#navigation::item:hover:!selected { background: $hover; }
QListWidget#recentTasks { background: transparent; border: none; outline: none; }
QListWidget#recentTasks::item { padding: 1px; margin: 2px 0; border-radius: 7px; }
QListWidget#recentTasks::item:selected { background: $selection; }
QListWidget#recentTasks::item:hover:!selected { background: $hover; }
QPushButton { background: $surface; color: $text; border: 1px solid $border; border-radius: 7px; padding: 7px 12px; }
QPushButton:hover { background: $hover; border-color: $scroll; }
QPushButton:pressed { background: $pressed; }
QPushButton:disabled { color: $disabled; background: $disabled_bg; border-color: $border; }
QPushButton#primary, QPushButton#sendButton { background: $accent; border: 1px solid $accent; color: $on_accent; font-weight: 600; }
QPushButton#primary:hover, QPushButton#sendButton:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton#primary:pressed, QPushButton#sendButton:pressed { background: $accent_pressed; border-color: $accent_pressed; }
QPushButton#primary:disabled, QPushButton#sendButton:disabled { background: $disabled_bg; border-color: $border; color: $disabled; }
QPushButton#sidebarNewTask { background: $surface; text-align: left; border: 1px solid $border; border-radius: 8px; padding: 9px 12px; font-size: 13px; font-weight: 500; }
QPushButton#sidebarNewTask:hover { background: $hover; }
QPushButton#linkButton { background: transparent; border: none; color: $accent; padding: 4px 1px; text-align: left; }
QPushButton#linkButton:hover { color: $accent_hover; }
QPushButton#toolbarButton { background: transparent; border: none; border-radius: 7px; padding: 5px; }
QPushButton#toolbarButton:hover { background: $hover; }
QPushButton#appearanceToggle { background: $subtle; border: 1px solid $border; border-radius: 7px; padding: 4px 10px; font-size: 12px; }
QPushButton#windowClose, QPushButton#windowMinimize, QPushButton#windowMaximize { border: 1px solid $border; border-radius: 7px; padding: 0; color: transparent; font-size: 12px; }
QPushButton#windowClose { background: #FF6058; border-color: #E34F48; }
QPushButton#windowMinimize { background: #FEBD2E; border-color: #DEAA27; }
QPushButton#windowMaximize { background: #28C840; border-color: #26AA36; }
QPushButton#windowClose:hover, QPushButton#windowMinimize:hover, QPushButton#windowMaximize:hover { color: #4A4241; }
QFrame#card, QFrame#detailCard { background: $surface; border: 1px solid $border; border-radius: 12px; }
QWidget#conversationPane, QWidget#conversationBody { background: $surface; }
QWidget#resultPane { background: $toolbar; border-left: 1px solid $border; }
QWidget#resultBody { background: $surface; }
QFrame#composerBox { background: $surface; border: 1px solid $border; border-radius: 17px; }
QPlainTextEdit#composer { background: transparent; border: none; color: $text; font-size: 14px; padding: 3px; }
QFrame#workflowCard { background: $assistant; border: 1px solid $border; border-radius: 12px; }
QLabel#workflowTitle { color: $text; font-size: 13px; font-weight: 600; }
QLabel#workflowSteps { color: $muted; font-size: 12px; }
QLabel#userBubble { background: $user; color: $text; border-radius: 12px; padding: 16px; }
QLabel#assistantBubble { background: transparent; color: $text; padding: 8px 0; font-size: 15px; }
QTextBrowser#messageBubble { background: transparent; color: $text; border: none; border-radius: 13px; padding: 14px; font-size: 14px; }
QTextBrowser#messageBubble[messageRole="user"] { background: $user; }
QTextBrowser#messageBubble[messageRole="error"] { background: $danger_bg; color: $danger; }
QLabel#agentAvatar, QWidget#messageBlock, QWidget#messageToolbar { background: transparent; }
QPushButton#suggestionChip { background: $subtle; border: 1px solid $border; border-radius: 8px; padding: 8px 11px; color: $text; font-size: 12px; text-align:left; }
QPushButton#suggestionChip:hover { background: $accent_soft; border-color: $accent; }
QFrame#stageCard { background: $surface; border: 1px solid $border; border-radius: 10px; }
QPushButton#stageToggle { background: transparent; border: none; padding: 1px 0; text-align: left; color: $text; font-weight: 600; font-size: 13px; }
QPushButton#stageToggle:hover { color: $accent; }
QPushButton#msgAction { background: transparent; border: none; border-radius: 5px; padding: 0; }
QPushButton#msgAction:hover { background: $hover; }
QPushButton#retryAction { background: $surface; border: 1px solid $border; color: $accent; padding: 4px 12px; font-size: 12px; }
QPushButton#scrollBottom { background: $surface; border: 1px solid $border; color: $muted; padding: 6px 12px; border-radius: 14px; font-size: 12px; }
QFrame#hotRow { background: $surface; border: 1px solid $border; border-radius: 10px; }
QFrame#hotRow:hover { background: $hover; border-color: $scroll; }
QLabel#hotRank { color: $muted; font-size: 12px; font-weight: 600; }
QLabel#hotBadge { background: $subtle; color: $muted; border-radius: 5px; padding: 3px 7px; font-size: 11px; }
QLabel#hotBadge[mark="可用"] { background: $success_bg; color: $success; }
QLabel#hotBadge[mark="参考"] { background: $warning_bg; color: $warning; }
QFrame#diagramCard, QFrame#confirmCard { background: $surface; border: 1px solid $border; border-radius: 10px; }
QLabel#diagramImage { color: $muted; }
QFrame#topicCard { background: $surface; border: none; border-top: 1px solid $border; border-radius: 0; }
QFrame#reasoningPanel { background: $subtle; border: 1px solid $border; border-radius: 9px; }
QPushButton#reasoningToggle { background: transparent; border: none; padding: 1px 0; color: $muted; text-align: left; font-size: 12px; }
QPushButton#reasoningToggle:hover { color: $accent; }
QPlainTextEdit#reasoningText { background: transparent; color: $muted; font-size: 12px; padding: 0; }
QLabel#sourceCard { background: $subtle; color: $muted; border-radius: 6px; padding: 11px; font-size: 12px; }
QLabel#warningCard { background: $warning_bg; color: $warning; border: none; border-radius: 7px; padding: 12px; font-size: 12px; }
QLabel#materialPlaceholder { background: $subtle; color: $muted; border: 1px solid $border; border-radius: 7px; font-size: 11px; }
QFrame#emptyPlan { border: 1px solid $border; border-radius: 12px; background: $surface; }
QLabel#emptyHeading { color: $text; font-size: 20px; font-weight: 500; }
QLabel#stepBadge { background: $subtle; color: $muted; border: 1px solid $border; border-radius: 18px; font-size: 16px; }
QLabel#stepBadge[active="true"] { background: $accent; color: $on_accent; border-color: $accent; }
QLabel#stepTitle { color: $muted; font-size: 13px; }
QLabel#stepTitle[active="true"] { color: $accent; }
QFrame#stepLine { background: $border; }
QLineEdit, QComboBox, QSpinBox { background: $surface; color: $text; border: 1px solid $border; border-radius: 7px; padding: 8px 11px; min-height: 20px; selection-background-color: $selection; selection-color: $text; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid $accent; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: $disabled; background: $disabled_bg; }
QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button { border: none; width: 20px; }
QComboBox QAbstractItemView { background: $surface; color: $text; selection-background-color: $accent; selection-color: $on_accent; border: 1px solid $border; }
QCheckBox { color: $text; spacing: 8px; }
QCheckBox::indicator { width: 15px; height: 15px; }
QTableView { background: $surface; alternate-background-color: $subtle; border: 1px solid $border; border-radius: 8px; gridline-color: $border; selection-background-color: $accent; selection-color: $on_accent; outline: none; }
QTableView::item { padding: 8px; border: none; }
QTableView::item:hover:!selected { background: $hover; }
QTableView::item:selected { background: $accent; color: $on_accent; }
QHeaderView { background: $toolbar; }
QHeaderView::section { background: $toolbar; color: $muted; border: none; border-bottom: 1px solid $border; padding: 10px 8px; font-size: 12px; }
QTableView QTableCornerButton::section { background: $toolbar; border: none; }
QPlainTextEdit, QTextBrowser { background: $surface; color: $text; border: none; padding: 9px; selection-background-color: $selection; selection-color: $text; }
QPlainTextEdit#recordDetail { color: $text; font-size: 13px; }
QPlainTextEdit#enterpriseField { border: 1px solid $border; border-radius: 7px; padding: 10px 12px; }
QDialog, QMessageBox { background: $window; }
QScrollArea, QScrollArea > QWidget { background: transparent; border: none; }
QScrollBar:vertical { width: 7px; background: transparent; margin: 4px 0; }
QScrollBar::handle:vertical { background: $scroll; border-radius: 3px; min-height: 32px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { height: 0; background: transparent; }
QScrollBar:horizontal { height: 7px; background: transparent; }
QScrollBar::handle:horizontal { background: $scroll; border-radius: 3px; min-width: 32px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal, QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { width: 0; background: transparent; }
QSplitter::handle { background: $border; }
QSplitter::handle:hover { background: $scroll; }
QStatusBar { background: $toolbar; color: $muted; border-top: 1px solid $border; font-size: 11px; }
QStatusBar::item { border: none; }
QProgressBar { background: $subtle; border: none; border-radius: 3px; height: 4px; }
QProgressBar::chunk { background: $accent; border-radius: 3px; }
QMenuBar, QMenu { background: $surface; color: $text; }
QMenu { border: 1px solid $border; padding: 5px; }
QMenu::item { padding: 7px 24px; }
QMenu::item:selected, QMenuBar::item:selected { background: $accent; color: $on_accent; }
QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: 7px; }
QTabWidget::pane { border: none; background: transparent; padding-top: 10px; }
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab { background: $subtle; color: $muted; padding: 7px 15px; border: 1px solid transparent; border-radius: 7px; margin-right: 3px; font-size: 12px; }
QTabBar::tab:hover { background: $hover; color: $text; }
QTabBar::tab:selected { background: $surface; border: 1px solid $border; color: $text; }
"""
