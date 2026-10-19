"""Shared light and dark colors for the native desktop interface."""
from __future__ import annotations

from string import Template

from PySide6.QtWidgets import QApplication


THEMES = {
    "light": {
        "window": "#E9EAEE", "window_top": "#EEEFF3", "window_bottom": "#E5E6EB",
        "surface": "#FFFFFF", "sidebar": "#E3E4EA", "sidebar_end": "#DCDDE5",
        "toolbar": "#F4F5F7", "subtle": "#F1F1F5", "hover": "#E7E8EE", "pressed": "#DBDCE3",
        "text": "#1D1D1F", "muted": "#5B5B63", "faint": "#7C7C84", "border": "rgba(17, 24, 39, 0.08)",
        "divider": "rgba(17, 24, 39, 0.055)", "header": "#F7F7FA",
        "accent": "#007AFF", "accent_hover": "#0071E3", "accent_pressed": "#005FCC", "on_accent": "#FFFFFF",
        "accent_soft": "#E8F2FF", "selection": "#D9E7FB", "disabled": "#A5A5AA", "disabled_bg": "#EFEFF2",
        "user": "#E4F0FF", "assistant": "#F2F2F7", "scroll": "#C3C3CA", "success": "#1E7A3C",
        "warning": "#995700", "warning_bg": "#FFF4E0", "danger": "#D70015", "danger_bg": "#FFECEE",
        "success_bg": "#E9F7EE", "shadow": "#D5D8DF", "code": "#F2F2F7",
        "composer_bg": "rgba(255, 255, 255, 0.86)",
        "composer_border": "rgba(17, 24, 39, 0.10)",
        "composer_ring": "rgba(29, 29, 31, 0.45)",
    },
    "dark": {
        "window": "#17171A", "window_top": "#1A1A1E", "window_bottom": "#151518",
        "surface": "#232327", "sidebar": "#1D1D21", "sidebar_end": "#19191D",
        "toolbar": "#1F1F23", "subtle": "#2A2A2F", "hover": "#323238", "pressed": "#3C3C44",
        "text": "#F5F5F7", "muted": "#A9A9B2", "faint": "#8E8E97", "border": "rgba(255, 255, 255, 0.10)",
        "divider": "rgba(255, 255, 255, 0.06)", "header": "#26262B",
        "accent": "#0A84FF", "accent_hover": "#3395FF", "accent_pressed": "#006BDD", "on_accent": "#FFFFFF",
        "accent_soft": "#26374E", "selection": "#3A5378", "disabled": "#788496", "disabled_bg": "#2D2D33",
        "user": "#263D59", "assistant": "#26262A", "scroll": "#565660", "success": "#6DD5A5",
        "warning": "#F0C674", "warning_bg": "#3B3323", "danger": "#FF9BAC", "danger_bg": "#442C34",
        "success_bg": "#253E35", "shadow": "#101014", "code": "#2E2E33",
        "composer_bg": "rgba(56, 56, 62, 0.82)",
        "composer_border": "rgba(255, 255, 255, 0.14)",
        "composer_ring": "rgba(255, 255, 255, 0.45)",
    },
}


def theme_name():
    app = QApplication.instance()
    value = app.property("scoutTheme") if app else "light"
    return value if value in THEMES else "light"


def color(name, mode=None):
    return THEMES[mode if mode in THEMES else theme_name()][name]


def _rgba(hex_color, alpha):
    value = hex_color.lstrip("#")
    r, g, b = (int(value[index:index + 2], 16) for index in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {round(alpha * 255)})"


def _combo_arrow(mode):
    """下拉箭头：QSS 一旦接管 drop-down，原生箭头就不再绘制，得自己给图。"""
    import tempfile
    from pathlib import Path
    target = Path(tempfile.gettempdir()) / f"scout-combo-arrow-{mode}.png"
    try:
        if target.is_file() and target.stat().st_size > 0:
            return target.as_posix()
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(THEMES[mode]["muted"]), 2.0,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(QPointF(7, 9.5), QPointF(12, 14.5))
        painter.drawLine(QPointF(12, 14.5), QPointF(17, 9.5))
        painter.end()
        pixmap.save(str(target), "PNG")
        return target.as_posix()
    except Exception:      # noqa: BLE001 —— 没 APP/写不了临时目录时退化为无图标
        return ""


def style_sheet(mode="light", backdrop=False):
    """backdrop=True 时把窗口底色交给 DWM 材质（Mica）：根背景透明、侧栏/工具栏半透明。"""
    values = dict(THEMES[mode if mode in THEMES else "light"])
    values["window_surface"] = "transparent" if backdrop else values["window"]
    values["window_canvas"] = "transparent" if backdrop else (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {top}, stop:1 {bottom})".format(
            top=values["window_top"], bottom=values["window_bottom"]))
    values["sidebar_surface"] = _rgba(values["sidebar"], 0.62) if backdrop else values["sidebar"]
    values["toolbar_surface"] = _rgba(values["toolbar"], 0.55) if backdrop else values["toolbar"]
    values["combo_arrow"] = _combo_arrow(mode if mode in THEMES else "light")
    return Template(_STYLE).substitute(values)


_STYLE = """
QWidget { color: $text; background: transparent; font-size: 13px; }
QMainWindow { background: $window_surface; }
QWidget#workspace, QWidget#overviewBody { background: $window_canvas; }
QWidget#titleBar { background: $toolbar_surface; border-bottom: 1px solid $border; }
QPushButton#appBrand { background: transparent; border: none; color: $text; font-size: 15px; font-weight: 600; padding: 3px 8px; }
QWidget#sidebar { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $sidebar, stop:1 $sidebar_end); }
QLabel { background: transparent; }
QLabel#heading { font-size: 27px; font-weight: 700; color: $text; }
QLabel#taskHeading { font-size: 22px; font-weight: 600; color: $text; }
QLabel#planHeading { font-size: 22px; font-weight: 600; color: $text; }
QLabel#sectionTitle, QLabel#speaker { font-size: 13px; font-weight: 600; color: $text; }
QLabel#topicTitle { font-size: 16px; font-weight: 600; color: $text; }
QLabel#bodyText { color: $text; font-size: 13px; }
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
QLabel#pill { background: $accent_soft; color: $accent; padding: 4px 11px; border-radius: 999px; font-size: 12px; }
QListWidget#navigation { background: transparent; border: none; outline: none; color: $text; }
QListWidget#navigation::item { padding: 8px 10px; margin: 2px 6px; border-radius: 9px; }
QListWidget#navigation::item:selected { background: $selection; color: $accent; }
QListWidget#navigation::item:hover:!selected { background: $hover; }
QListWidget#recentTasks { background: transparent; border: none; outline: none; }
QListWidget#recentTasks::item { padding: 2px; margin: 2px 0; border-radius: 8px; }
QListWidget#recentTasks::item:selected { background: $selection; }
QListWidget#recentTasks::item:hover:!selected { background: $hover; }
QPushButton { background: $surface; color: $text; border: 1px solid $border; border-radius: 8px; padding: 7px 13px; }
QPushButton:hover { background: $hover; border-color: $scroll; }
QPushButton:pressed { background: $pressed; }
QPushButton:focus { border-color: $accent; }
QPushButton:disabled { color: $disabled; background: $disabled_bg; border-color: $border; }
QPushButton#primary, QPushButton#sendButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2B8CFF, stop:1 $accent); border: 1px solid $accent; color: $on_accent; font-weight: 600; }
QPushButton#primary:hover, QPushButton#sendButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3D95FF, stop:1 $accent_hover); border-color: $accent_hover; }
QPushButton#primary:pressed, QPushButton#sendButton:pressed { background: $accent_pressed; border-color: $accent_pressed; }
QPushButton#primary:disabled, QPushButton#sendButton:disabled { background: $disabled_bg; border-color: $border; color: $disabled; }
QPushButton#sidebarNewTask { background: $surface; text-align: left; border: 1px solid $border; border-radius: 6px; padding: 9px 12px; font-size: 13px; font-weight: 500; }
QPushButton#sidebarNewTask:hover { background: $hover; }
QPushButton#linkButton { background: transparent; border: none; color: $accent; padding: 4px 1px; text-align: left; }
QPushButton#linkButton:hover { color: $accent_hover; }
QPushButton#toolbarButton { background: transparent; border: none; border-radius: 6px; padding: 5px; }
QPushButton#toolbarButton:hover { background: $hover; }
QPushButton#appearanceToggle { background: $subtle; border: 1px solid $border; border-radius: 6px; padding: 4px 10px; font-size: 12px; }
QPushButton#windowControl, QPushButton#closeControl { background: transparent; border: none; border-radius: 6px; padding: 0; color: $muted; font-size: 15px; }
QPushButton#windowControl:hover { background: $hover; color: $text; }
QPushButton#windowControl:pressed { background: $pressed; color: $text; }
QPushButton#windowControl[nativeHover="true"] { background: $hover; color: $text; }
QPushButton#windowControl[nativePressed="true"] { background: $pressed; color: $text; }
QPushButton#closeControl:hover { background: #FF3B30; color: #FFFFFF; }
QPushButton#closeControl:pressed { background: #E0342B; color: #FFFFFF; }
QLabel#statusChip { background: $subtle; color: $muted; border-radius: 999px; padding: 4px 11px; font-size: 11px; }
QPushButton#toolbarAccent { background: $accent_soft; color: $accent; border: none; border-radius: 6px; padding: 6px 12px; font-weight: 600; }
QPushButton#toolbarAccent:hover { background: $selection; }
QFrame#card, QFrame#detailCard { background: $surface; border: 1px solid $border; border-radius: 16px; }
QFrame#conversationPane { background: $surface; border: 1px solid $border; border-radius: 18px; }
QWidget#conversationShell { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $sidebar, stop:1 $toolbar); }
QWidget#conversationBody { background: $surface; }
QWidget#resultPane { background: $toolbar; }
QWidget#resultBody { background: $surface; }
QFrame#composerBox { background: $composer_bg; border: 1px solid $composer_border; border-radius: 24px; }
QPlainTextEdit#composer { background: transparent; border: none; color: $text; font-size: 13px; padding: 2px 4px; }
QPushButton#sendCircle { background: $accent; border: none; border-radius: 19px; }
QPushButton#sendCircle:hover { background: $accent_hover; }
QPushButton#sendCircle:pressed { background: $accent_pressed; }
QPushButton#sendCircle:disabled { background: $subtle; }
QFrame#workflowCard { background: $assistant; border: 1px solid $border; border-radius: 14px; }
QLabel#workflowTitle { color: $text; font-size: 13px; font-weight: 600; }
QLabel#workflowSteps { color: $muted; font-size: 12px; }
QLabel#userBubble { background: $user; color: $text; border-radius: 16px; padding: 14px; }
QLabel#assistantBubble { background: transparent; color: $text; padding: 8px 0; font-size: 14px; }
QTextBrowser#messageBubble { background: transparent; color: $text; border: none; border-radius: 16px; padding: 12px 14px; font-size: 13px; }
QTextBrowser#messageBubble[messageRole="user"] { background: $user; }
QTextBrowser#messageBubble[messageRole="error"] { background: $danger_bg; color: $danger; }
QLabel#agentAvatar, QWidget#messageBlock, QWidget#messageToolbar { background: transparent; }
QPushButton#suggestionChip { background: $subtle; border: none; border-radius: 999px; padding: 8px 14px; color: $text; font-size: 12px; text-align:left; }
QPushButton#suggestionChip:hover { background: $accent_soft; }
QFrame#stageCard { background: $surface; border: 1px solid $border; border-radius: 14px; }
QPushButton#stageToggle { background: transparent; border: none; padding: 1px 0; text-align: left; color: $text; font-weight: 600; font-size: 13px; }
QPushButton#stageToggle:hover { color: $accent; }
QPushButton#msgAction { background: transparent; border: none; border-radius: 5px; padding: 0; }
QPushButton#msgAction:hover { background: $hover; }
QPushButton#retryAction { background: $surface; border: 1px solid $border; color: $accent; padding: 4px 12px; font-size: 12px; }
QPushButton#scrollBottom { background: $surface; border: 1px solid $border; color: $muted; padding: 6px 12px; border-radius: 999px; font-size: 12px; }
QFrame#hotRow { background: $surface; border: 1px solid $border; border-radius: 12px; }
QFrame#hotRow:hover { background: $hover; border-color: $scroll; }
QLabel#hotRank { color: $muted; font-size: 12px; font-weight: 600; }
QLabel#hotBadge { background: $subtle; color: $muted; border-radius: 999px; padding: 3px 8px; font-size: 11px; }
QLabel#hotBadge[mark="可用"] { background: $success_bg; color: $success; }
QLabel#hotBadge[mark="参考"] { background: $warning_bg; color: $warning; }
QFrame#diagramCard, QFrame#confirmCard { background: $surface; border: 1px solid $border; border-radius: 14px; }
QFrame#videoCard { background: $surface; border: 1px solid $border; border-radius: 14px; }
QLabel#videoTitle { font-size: 13px; font-weight: 600; color: $text; }
QLabel#videoStatus { font-size: 11px; color: $muted; }
QPushButton#videoControl { background: $subtle; border: 1px solid $border; border-radius: 8px; padding: 4px 10px; font-size: 11px; color: $text; }
QPushButton#videoControl:hover { background: $hover; }
QSlider#videoSlider::groove:horizontal { height: 4px; background: $subtle; border-radius: 2px; }
QSlider#videoSlider::handle:horizontal { width: 12px; margin: -4px 0; border-radius: 6px; background: $accent; }
QFrame#choiceCard { background: $surface; border: 1px solid $border; border-radius: 14px; }
QLabel#choiceOption:hover { background: $accent_soft; }
QLabel#choiceOption[checked="true"] { background: $accent_soft; border-color: $accent; color: $accent; }
QLabel#choiceOption:disabled { color: $muted; }
QPushButton#choiceConfirm { background: $accent; color: #FFFFFF; border: none; border-radius: 999px; padding: 7px 16px; font-size: 12px; }
QPushButton#choiceConfirm:disabled { background: $subtle; color: $muted; }
QLabel#diagramImage { color: $muted; }
QFrame#topicCard { background: $surface; border: none; border-top: 1px solid $border; border-radius: 0; }
QFrame#reasoningPanel { background: $subtle; border: 1px solid $border; border-radius: 8px; }
QPushButton#reasoningToggle { background: transparent; border: none; padding: 1px 0; color: $muted; text-align: left; font-size: 12px; }
QPushButton#reasoningToggle:hover { color: $accent; }
QPlainTextEdit#reasoningText { background: transparent; color: $muted; font-size: 12px; padding: 0; }
QLabel#sourceCard { background: $subtle; color: $muted; border-radius: 6px; padding: 11px; font-size: 12px; }
QLabel#warningCard { background: $warning_bg; color: $warning; border: none; border-radius: 6px; padding: 12px; font-size: 12px; }
QLabel#materialPlaceholder { background: $subtle; color: $muted; border: 1px solid $border; border-radius: 7px; font-size: 11px; }
QFrame#emptyPlan { border: 1px solid $border; border-radius: 12px; background: $surface; }
QLabel#emptyHeading { color: $text; font-size: 20px; font-weight: 500; }
QLabel#stepBadge { background: $subtle; color: $muted; border: 1px solid $border; border-radius: 18px; font-size: 16px; }
QLabel#stepBadge[active="true"] { background: $accent; color: $on_accent; border-color: $accent; }
QLabel#stepTitle { color: $muted; font-size: 13px; }
QLabel#stepTitle[active="true"] { color: $accent; }
QFrame#stepLine { background: $border; }
QLineEdit, QComboBox, QSpinBox { background: $surface; color: $text; border: 1px solid $border; border-radius: 8px; padding: 8px 11px; min-height: 20px; selection-background-color: $selection; selection-color: $text; }
QComboBox::drop-down { border: none; background: transparent; width: 26px; subcontrol-origin: padding; subcontrol-position: center right; }
QComboBox::down-arrow { image: url($combo_arrow); width: 12px; height: 12px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid $accent; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: $disabled; background: $disabled_bg; }
QComboBox QAbstractItemView { background: transparent; color: $text; selection-background-color: $accent; selection-color: $on_accent; border: none; border-radius: 10px; padding: 4px; outline: none; }
QComboBox QAbstractItemView::item { padding: 6px 10px; border-radius: 6px; min-height: 22px; }
QFrame#comboPopup { background: $surface; border: 1px solid $border; border-radius: 12px; }
QCheckBox { color: $text; spacing: 8px; }
QCheckBox::indicator { width: 15px; height: 15px; }
QTableView { background: $surface; alternate-background-color: transparent; border: 1px solid $border; border-radius: 14px; gridline-color: transparent; selection-background-color: $selection; selection-color: $text; outline: none; }
QTableView::item { padding: 8px 8px; border: none; border-bottom: 1px solid $divider; }
QTableView::item:hover:!selected { background: $hover; }
QTableView::item:selected { background: $selection; color: $text; }
QHeaderView { background: transparent; }
QHeaderView::section { background: $header; color: $muted; border: none; border-bottom: 1px solid $border; padding: 9px 10px; font-size: 11px; font-weight: 600; }
QTableView QTableCornerButton::section { background: $header; border: none; }
QFrame#card QTableView { border: none; border-radius: 10px; }
QPlainTextEdit, QTextBrowser { background: $surface; color: $text; border: none; padding: 9px; selection-background-color: $selection; selection-color: $text; }
QPlainTextEdit#recordDetail { color: $text; font-size: 13px; }
QPlainTextEdit#enterpriseField { border: 1px solid $border; border-radius: 6px; padding: 10px 12px; }
QDialog, QMessageBox { background: $window; }
QScrollArea, QScrollArea > QWidget { background: transparent; border: none; }
QScrollBar:vertical { width: 8px; background: transparent; margin: 2px 0; }
QScrollBar::handle:vertical { background: $scroll; border-radius: 4px; min-height: 36px; }
QScrollBar::handle:vertical:hover { background: $muted; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { height: 0; background: transparent; }
QScrollBar:horizontal { height: 8px; background: transparent; }
QScrollBar::handle:horizontal { background: $scroll; border-radius: 4px; min-width: 36px; }
QScrollBar::handle:horizontal:hover { background: $muted; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal, QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { width: 0; background: transparent; }
QSplitter::handle { background: $toolbar; }
QSplitter::handle:hover { background: $border; }
QStatusBar { background: $window_surface; color: $muted; border-top: none; font-size: 11px; }
QStatusBar::item { border: none; }
QProgressBar { background: $subtle; border: none; border-radius: 3px; height: 4px; }
QProgressBar::chunk { background: $accent; border-radius: 3px; }
QMenuBar, QMenu { background: $surface; color: $text; }
QMenu { border: 1px solid $border; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 6px 14px; margin: 0 4px; border-radius: 6px; }
QMenu::item:selected, QMenuBar::item:selected { background: $accent; color: $on_accent; }
QToolTip { background: $surface; color: $text; border: 1px solid $border; border-radius: 7px; padding: 5px 8px; font-size: 12px; }
QTabWidget::pane { border: none; background: transparent; padding-top: 10px; }
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab { background: transparent; color: $muted; padding: 6px 14px; border: 1px solid transparent; border-radius: 6px; margin-right: 2px; font-size: 12px; }
QTabBar::tab:hover { background: $hover; color: $text; }
QTabBar::tab:selected { background: $surface; border: 1px solid $border; border-radius: 8px; color: $text; }
"""
