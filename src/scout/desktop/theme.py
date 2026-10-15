"""Desktop palette, typography and small vector icons."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPen, QPixmap

STYLE = """
QMainWindow, QWidget#workspace, QWidget#overviewBody { background: #191D24; }
QWidget { color: #D8DCE6; background: #1B2028; font-size: 13px; }
QLabel { background: transparent; }
QWidget#titleBar { background: #161A20; border-bottom: 1px solid #30353F; }
QLabel#appTitle { color: #F0F1F7; font-size: 15px; font-weight: 600; }
QWidget#sidebar { background: #171B21; border-right: 1px solid #30353F; }
QLabel#brand { color: #F2F2FA; font-size: 19px; font-weight: 700; }
QLabel#brandMark { color: #77D6B7; font-size: 22px; font-weight: 700; }
QLabel#sidebarCaption, QLabel#sidebarFooter { color: #8F97A8; font-size: 12px; }
QListWidget#navigation { background: transparent; border: none; outline: none; color: #BEC5D3; }
QListWidget#navigation::item { padding: 12px 10px; margin: 3px 0; border-radius: 8px; }
QListWidget#navigation::item:selected { color: #F0EAFF; background: #332B57; }
QListWidget#navigation::item:hover:!selected { background: #222730; }
QListWidget#recentTasks { background: transparent; border: none; outline: none; }
QListWidget#recentTasks::item { border-radius: 9px; padding: 2px; margin: 4px 0; }
QListWidget#recentTasks::item:selected { background: #332B57; }
QListWidget#recentTasks::item:hover:!selected { background: #242932; }
QLabel#heading { color: #F4F3FA; font-size: 25px; font-weight: 700; }
QLabel#taskHeading { color: #F4F3FA; font-size: 20px; font-weight: 700; }
QLabel#planHeading { color: #F5F4FB; font-size: 25px; font-weight: 700; }
QLabel#subtitle, QLabel#muted, QLabel#composerHint { color: #929BAE; font-size: 12px; }
QLabel#sectionTitle, QLabel#speaker { color: #EFF0F7; font-size: 14px; font-weight: 600; }
QLabel#topicTitle { color: #F0F0F8; font-size: 16px; font-weight: 600; }
QLabel#bodyText { color: #C3C9D6; font-size: 13px; }
QLabel#metricValue { color: #EEE9FC; font-size: 34px; font-weight: 700; }
QLabel#metricTitle { color: #B3BCCB; font-size: 12px; }
QLabel#metricNote { color: #8D98AB; font-size: 11px; }
QLabel#pill { background: #2D2745; color: #BAA2FF; padding: 5px 9px; border-radius: 8px; font-size: 11px; }
QFrame#card, QFrame#detailCard { background: #20252E; border: 1px solid #343B49; border-radius: 10px; }
QWidget#conversationPane, QWidget#conversationBody { background: #1B2028; }
QWidget#resultPane, QWidget#resultBody { background: #191E25; }
QLabel#userBubble { background: #292F39; color: #E4E6EE; border-radius: 9px; padding: 14px; font-size: 14px; }
QLabel#assistantBubble { background: #252B35; color: #D4D8E3; border-radius: 9px; padding: 15px; }
QLabel#userAvatar { background: #8054F5; border-radius: 17px; }
QLabel#aiAvatar { background: #20232E; border: 1px solid #8464C5; border-radius: 17px; }
QLabel#agentAvatar { background: transparent; border: none; }
QLabel#agentName { color: #98A2B5; font-size: 12px; }
QPushButton#suggestionChip { background: #232936; border: 1px dashed #3E4859; border-radius: 15px; padding: 7px 14px; color: #B7C0D2; font-size: 12px; }
QPushButton#suggestionChip:hover { border-color: #9F7DEF; color: #E6DDFF; background: #2A3040; }
QFrame#stageCard { background: #202630; border: 1px solid #363F4D; border-radius: 9px; }
QPushButton#stageToggle { background: transparent; border: none; padding: 1px 0; text-align: left; color: #E1E4EF; font-weight: 600; }
QPushButton#stageToggle:hover { color: #C9D3E4; }
QPushButton#msgAction { background: transparent; border: none; padding: 0; }
QPushButton#msgAction:hover { background: #2C3442; border-radius: 6px; }
QPushButton#retryAction { background: #2A3140; border: 1px solid #4A5568; color: #C9D3E4; padding: 4px 14px; border-radius: 6px; font-size: 12px; }
QPushButton#retryAction:hover { border-color: #9F7DEF; background: #313A4B; }
QPushButton#scrollBottom { background: #2A3140; border: 1px solid #46516A; color: #C7D0E2; padding: 6px 14px; border-radius: 15px; font-size: 12px; }
QPushButton#scrollBottom:hover { background: #333D50; border-color: #5A6580; }
QLabel#stepBadge { background: #272E39; color: #B0B8CA; border: 1px solid #475063; border-radius: 18px; font-size: 16px; }
QLabel#stepBadge[active="true"] { background: #8054F5; border-color: #AD8AFF; color: white; }
QLabel#stepTitle { color: #B9C0D0; font-size: 13px; }
QLabel#stepTitle[active="true"] { color: #B49AFF; font-weight: 600; }
QFrame#stepLine { background: #424B5E; }
QFrame#composerBox { background: #202630; border: 1px solid #3D4554; border-radius: 11px; }
QPlainTextEdit#composer { background: transparent; padding: 2px; color: #DEE1EB; }
QFrame#topicCard { background: #1F252E; border: 1px solid #303844; border-radius: 9px; }
QFrame#reasoningPanel { background: #1E242D; border: 1px solid #2C3441; border-radius: 9px; }
QPushButton#reasoningToggle { background: transparent; border: none; padding: 1px 0; text-align: left; color: #9AA6B8; font-size: 12px; font-weight: 600; }
QPushButton#reasoningToggle:hover { color: #C9D3E4; }
QPlainTextEdit#reasoningText { background: transparent; color: #8B96A9; font-size: 12px; padding: 0; }
QLabel#sourceCard { background: #272E38; color: #AAB3C5; border-radius: 8px; padding: 12px; font-size: 12px; }
QLabel#warningCard { background: #342B1E; color: #E4BB76; border: 1px solid #755A30; border-radius: 8px; padding: 12px; font-size: 12px; }
QLabel#materialPlaceholder { background: #242B35; color: #68758A; border: 1px dashed #434B59; border-radius: 7px; font-size: 11px; }
QFrame#emptyPlan { border: 1px dashed #37404E; border-radius: 10px; background: #1D232B; }
QLabel#emptyHeading { color: #AAB4C6; font-size: 17px; }
QLineEdit { background: #222832; border: 1px solid #3B4453; border-radius: 7px; padding: 10px 12px; selection-background-color: #7253D7; }
QLineEdit:focus { border-color: #946CF2; }
QLineEdit:disabled { color: #6D778A; background: #1F252D; }
QComboBox, QSpinBox { background: #222832; border: 1px solid #3B4453; border-radius: 7px; padding: 8px 10px; min-height: 20px; }
QComboBox:hover, QSpinBox:hover { border-color: #57627A; }
QComboBox:focus, QSpinBox:focus { border-color: #946CF2; }
QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button { border: none; width: 18px; }
QComboBox QAbstractItemView { background: #222832; selection-background-color: #46366C; color: #DFE1EA; }
QCheckBox { color: #ABB4C6; }
QPushButton { background: #20262F; border: 1px solid #485265; border-radius: 7px; padding: 9px 12px; color: #CED4E2; }
QPushButton:hover { border-color: #9F7DEF; background: #2B2B3E; }
QPushButton:pressed { background: #39314F; }
QPushButton:disabled { background: #20252C; color: #667082; border-color: #333B48; }
QPushButton#primary { background: #8054F5; border-color: #9870FC; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #9268FF; }
QPushButton#primary:pressed { background: #6840D6; }
QPushButton#primary:disabled { background: #443662; border-color: #51416E; color: #8B80A4; }
QPushButton#linkButton { background: transparent; border: none; color: #AF99E8; padding: 5px 3px; text-align: left; }
QPushButton#windowControl { background: transparent; border: none; border-radius: 0; padding: 0; color: #ABB2C0; }
QPushButton#windowControl:hover { background: #303641; color: white; }
QPushButton#closeControl { background: transparent; border: none; border-radius: 0; padding: 0; color: #ABB2C0; }
QPushButton#closeControl:hover { background: #A44357; color: white; }
QTableView { background: #202630; alternate-background-color: #242B35; border: 1px solid #354050; border-radius: 8px; gridline-color: #303949; selection-background-color: #393153; selection-color: #D8C8FF; outline: none; }
QTableView::item { padding: 9px 8px; border-bottom: 1px solid #303746; }
QTableView::item:hover { background: #2A3240; }
QHeaderView { background: #202630; }
QHeaderView::section { background: #262D38; color: #A6B2C6; border: none; border-bottom: 1px solid #3A4352; padding: 12px 8px; font-size: 12px; }
QTableView QTableCornerButton::section { background: #262D38; border: none; }
QPlainTextEdit, QTextBrowser { background: #202630; border: none; color: #C2CCDC; padding: 8px; selection-background-color: #514173; }
QPlainTextEdit#recordDetail { color: #C2CCDC; font-size: 13px; }
QPlainTextEdit#enterpriseField { border: 1px solid #3B4453; border-radius: 7px; padding: 10px 12px; }
QScrollArea, QScrollArea > QWidget { background: transparent; border: none; }
QDialog { background: #1B2028; }
QScrollBar:vertical { width: 8px; background: transparent; margin: 4px 0; }
QScrollBar::handle:vertical { background: #4A566E; border-radius: 3px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { height: 8px; background: transparent; }
QScrollBar::handle:horizontal { background: #4A566E; border-radius: 3px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QSplitter::handle { background: #323945; }
QSplitter::handle:hover { background: #4A5568; }
QStatusBar { background: #171C23; color: #8793A8; border-top: 1px solid #303846; font-size: 11px; }
QStatusBar::item { border: none; }
QProgressBar { background: #2A303F; border: none; border-radius: 3px; height: 4px; }
QProgressBar::chunk { background: #8A60FA; border-radius: 3px; }
QMenuBar { background: #171C23; color: #A5AFBE; }
QMenuBar::item:selected { background: #332D49; }
QMenu { background: #222A35; border: 1px solid #465164; padding: 5px; }
QMenu::item { padding: 8px 24px; }
QMenu::item:selected { background: #40325F; color: #E3D6FF; }
QToolTip { background: #313B4A; color: white; border: 1px solid #52607A; padding: 7px; }
QTabWidget::pane { border: none; background: transparent; padding-top: 8px; }
QTabBar::tab { background: transparent; color: #A7B0C1; padding: 12px 12px; border-bottom: 2px solid #303845; }
QTabBar::tab:hover { color: #C6CFE0; }
QTabBar::tab:selected { color: #B49AFF; border-bottom: 2px solid #9266F8; }
"""



def apply_theme(app):
    app.setStyle("Fusion")
    # The offscreen platform has no system font inventory on Windows.
    if not QFontDatabase.families() and os.name == "nt":
        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
        symbols = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "seguisym.ttf"
        if symbols.exists():
            QFontDatabase.addApplicationFont(str(symbols))
    app.setFont(QFont("Microsoft YaHei UI" if os.name == "nt" else "Sans Serif", 10))
    app.setStyleSheet(STYLE)


def icon(name, color="#9CB0D0", size=22):
    result = QIcon()
    for mode, shade in ((QIcon.Mode.Normal, color), (QIcon.Mode.Selected, "#FFFFFF")):
        pixmap = QPixmap(size * 2, size * 2)
        pixmap.setDevicePixelRatio(2)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(size / 24, size / 24)
        p.setPen(QPen(QColor(shade), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if name == "sparkles":
            from PySide6.QtCore import QPointF
            from PySide6.QtGui import QPolygonF
            for cx, cy, radius in ((9, 12, 7), (19, 5, 3), (20, 18, 3)):
                p.drawPolygon(QPolygonF([QPointF(cx,cy-radius),QPointF(cx+radius*.3,cy-radius*.3),
                    QPointF(cx+radius,cy),QPointF(cx+radius*.3,cy+radius*.3),QPointF(cx,cy+radius),
                    QPointF(cx-radius*.3,cy+radius*.3),QPointF(cx-radius,cy),QPointF(cx-radius*.3,cy-radius*.3)]))
        elif name == "send":
            p.drawLine(3, 11, 21, 3)
            p.drawLine(21, 3, 15, 21)
            p.drawLine(15, 21, 10, 14)
            p.drawLine(10, 14, 3, 11)
            p.drawLine(10, 14, 21, 3)
        elif name == "attach":
            p.drawArc(QRectF(6, 3, 10, 17), 200*16, 300*16)
            p.drawLine(9, 14, 15, 7)
        elif name == "overview":
            for x, y in ((4, 4), (14, 4), (4, 14), (14, 14)):
                p.drawRoundedRect(QRectF(x, y, 6, 6), 1.2, 1.2)
        elif name == "enterprise":
            p.drawRoundedRect(QRectF(4, 4, 16, 17), 2, 2)
            p.drawLine(8, 16, 8, 12)
            p.drawLine(12, 16, 12, 8)
            p.drawLine(16, 16, 16, 10)
        elif name == "works":
            p.drawRoundedRect(QRectF(3, 5, 18, 14), 2, 2)
            p.drawLine(8, 5, 8, 19)
            p.drawLine(16, 5, 16, 19)
            p.drawLine(3, 10, 8, 10)
            p.drawLine(16, 14, 21, 14)
        elif name == "users":
            p.drawEllipse(QRectF(8, 4, 7, 7))
            p.drawArc(QRectF(4, 13, 15, 13), 0, 180 * 16)
            p.drawArc(QRectF(16, 5, 5, 6), -80 * 16, 160 * 16)
            p.drawArc(QRectF(17, 14, 8, 9), 30 * 16, 100 * 16)
        elif name == "analyses":
            p.drawRoundedRect(QRectF(5, 3, 14, 18), 2, 2)
            for y, end in ((8, 15), (12, 15), (16, 12)):
                p.drawLine(9, y, end, y)
        elif name == "tasks":
            p.drawRoundedRect(QRectF(4, 4, 16, 17), 2, 2)
            p.drawLine(8, 9, 10, 11)
            p.drawLine(10, 11, 15, 7)
            p.drawLine(8, 15, 16, 15)
        elif name == "settings":
            for y, x in ((6, 9), (12, 16), (18, 7)):
                p.drawLine(4, y, 20, y)
                p.setBrush(QColor("#17233B"))
                p.drawEllipse(QRectF(x - 2, y - 2, 4, 4))
        elif name == "refresh":
            p.drawArc(QRectF(5, 5, 14, 14), 30 * 16, 290 * 16)
            p.drawLine(19, 4, 19, 10)
            p.drawLine(14, 10, 19, 10)
        elif name == "folder":
            p.drawRoundedRect(QRectF(3, 7, 18, 13), 2, 2)
            p.drawLine(4, 7, 4, 4)
            p.drawLine(4, 4, 10, 4)
            p.drawLine(10, 4, 13, 7)
        elif name == "copy":
            p.drawRoundedRect(QRectF(8, 3, 12, 14), 2, 2)
            p.drawRoundedRect(QRectF(4, 7, 12, 14), 2, 2)
        elif name == "stop":
            p.setBrush(QColor(shade))
            p.drawRoundedRect(QRectF(7, 7, 10, 10), 2.5, 2.5)
        elif name == "arrowDown":
            p.drawLine(12, 5, 12, 19)
            p.drawLine(6.4, 13.4, 12, 19)
            p.drawLine(17.6, 13.4, 12, 19)
        p.end()
        result.addPixmap(pixmap, mode)
    return result


def _paint_glyph(p, name):
    """24×24 坐标系下的线条图标；调用方负责缩放、描边颜色与粗细。"""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPolygonF
    if name == "hub":
        # 总管：中心节点 + 四向连接（派活/协调）
        p.drawEllipse(QRectF(9.4, 9.4, 5.2, 5.2))
        for cx, cy in ((5, 5), (19, 5), (5, 19), (19, 19)):
            p.drawEllipse(QRectF(cx - 2.0, cy - 2.0, 4.0, 4.0))
        for x1, y1, x2, y2 in ((13.9, 13.9, 17.4, 17.4), (10.1, 13.9, 6.6, 17.4),
                               (13.9, 10.1, 17.4, 6.6), (10.1, 10.1, 6.6, 6.6)):
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    elif name == "database":
        # 数据管家：数据库柱体
        p.drawEllipse(QRectF(5, 3.5, 14, 5.6))
        p.drawLine(QPointF(5, 6.3), QPointF(5, 18.0))
        p.drawLine(QPointF(19, 6.3), QPointF(19, 18.0))
        p.drawArc(QRectF(5, 6.0, 14, 5.6), 0, -180 * 16)
        p.drawArc(QRectF(5, 14.4, 14, 5.6), 0, -180 * 16)
    elif name == "focus":
        # 受众分析师：同心环（追踪/洞察人群）
        p.drawEllipse(QRectF(2.8, 2.8, 18.4, 18.4))
        p.drawEllipse(QRectF(6.2, 6.2, 11.6, 11.6))
        p.drawEllipse(QRectF(9.6, 9.6, 4.8, 4.8))
    elif name == "video":
        # 内容分析师：屏幕 + 播放键
        p.drawRoundedRect(QRectF(3.5, 4.5, 17, 12.6), 2, 2)
        p.drawPolygon(QPolygonF([QPointF(10.2, 7.8), QPointF(10.2, 13.8), QPointF(15.2, 10.8)]))
        p.drawLine(QPointF(12, 17.1), QPointF(12, 20.4))
        p.drawLine(QPointF(9, 20.4), QPointF(15, 20.4))
    elif name == "target":
        # 传播策略师：靶心（定位/策略）
        p.drawEllipse(QRectF(3.5, 3.5, 17, 17))
        p.drawEllipse(QRectF(7.4, 7.4, 9.2, 9.2))
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(10.8, 10.8, 2.4, 2.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
    elif name == "history":
        # 复盘顾问：时钟回看
        p.drawEllipse(QRectF(5, 5, 14, 14))
        p.drawLine(QPointF(12, 12), QPointF(12, 7.4))
        p.drawLine(QPointF(12, 12), QPointF(8.6, 13.8))


def agent_badge(color, icon_name, size=34):
    """发言人徽标：色底圆 + 白色矢量图标（不使用字体符号或表情）。"""
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QRectF(0.5, 0.5, size - 1, size - 1))
    glyph = size * 0.60
    p.translate((size - glyph) / 2, (size - glyph) / 2)
    p.scale(glyph / 24, glyph / 24)
    p.setPen(QPen(QColor("#FFFFFF"), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    _paint_glyph(p, icon_name)
    p.end()
    result = QIcon()
    result.addPixmap(pixmap)
    return result
