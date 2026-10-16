"""Desktop palette, typography and small vector icons."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QIconEngine, QPainter, QPen, QPixmap

from .appearance import THEMES, color, style_sheet, theme_name

STYLE = style_sheet("light")


def apply_theme(app, mode="light"):
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QWidget
    mode = mode if mode in THEMES else "light"
    app.setProperty("scoutTheme", mode)
    app.setStyle("Fusion")
    if not QFontDatabase.families() and os.name == "nt":
        for filename in ("msyh.ttc", "seguisym.ttf"):
            font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename
            if font.exists():
                QFontDatabase.addApplicationFont(str(font))
    families = QFontDatabase.families()
    candidates = ("SF Pro Text", "PingFang SC", "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI")
    family = next((name for name in candidates if name in families), "Sans Serif")
    app.setFont(QFont(family, 10))
    palette = QPalette()
    roles = {"Window": "window", "WindowText": "text", "Base": "surface", "AlternateBase": "subtle",
             "Text": "text", "Button": "surface", "ButtonText": "text", "Highlight": "accent",
             "HighlightedText": "on_accent", "ToolTipBase": "surface", "ToolTipText": "text",
             "Link": "accent", "PlaceholderText": "muted", "BrightText": "on_accent"}
    for role, name in roles.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(color(name, mode)))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(color("disabled", mode)))
    app.setPalette(palette)
    app.setStyleSheet(style_sheet(mode))
    for widget in app.allWidgets():
        glyph = widget.property("themeGlyph")
        if glyph:
            size = widget.property("themeGlyphSize") or 22
            widget.setPixmap(icon(glyph, size=size).pixmap(size, size))
        agent_glyph = widget.property("agentGlyph")
        if agent_glyph:
            size = widget.property("agentGlyphSize") or 20
            widget.setPixmap(agent_badge(None, agent_glyph, size).pixmap(size, size))
        QWidget.update(widget)
    return mode


def _render_icon(name, color, size=22):
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
        elif name == "source":
            p.setPen(Qt.PenStyle.NoPen)
            for x, y in ((5, 3), (11, 5), (9, 11), (3, 9)):
                petal = QColor(shade)
                petal.setAlphaF(0.85)
                p.setBrush(petal)
                p.drawEllipse(QRectF(x, y, 10, 10))
            p.setBrush(QColor(THEMES[theme_name()]["surface"]))
            p.drawEllipse(QRectF(9, 9, 6, 6))
        elif name == "send":
            p.drawLine(12, 19, 12, 5)
            p.drawLine(6, 11, 12, 5)
            p.drawLine(18, 11, 12, 5)
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
                p.setBrush(QColor(THEMES[theme_name()]["surface"]))
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



class _AdaptiveIconEngine(QIconEngine):
    def __init__(self, name, fixed_color=None, size=22):
        super().__init__()
        self.name, self.fixed_color, self.size = name, fixed_color, size

    def clone(self):
        return _AdaptiveIconEngine(self.name, self.fixed_color, self.size)

    def paint(self, painter, rect, mode, state):
        shade = self.fixed_color or color("muted")
        _render_icon(self.name, shade, max(rect.width(), rect.height())).paint(painter, rect, Qt.AlignmentFlag.AlignCenter, mode, state)

    def pixmap(self, size, mode, state):
        shade = self.fixed_color or color("muted")
        return _render_icon(self.name, shade, max(size.width(), size.height())).pixmap(size, mode, state)


def icon(name, color=None, size=22):
    return QIcon(_AdaptiveIconEngine(name, color, size))

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
    """Theme-aware member glyphs share the desktop accent and a quiet backing."""
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(THEMES[theme_name()]["accent_soft"]))
    p.drawEllipse(QRectF(0.5, 0.5, size - 1, size - 1))
    glyph = size * 0.60
    p.translate((size - glyph) / 2, (size - glyph) / 2)
    p.scale(glyph / 24, glyph / 24)
    p.setPen(QPen(QColor(THEMES[theme_name()]["accent"]), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    _paint_glyph(p, icon_name)
    p.end()
    result = QIcon()
    result.addPixmap(pixmap)
    return result
