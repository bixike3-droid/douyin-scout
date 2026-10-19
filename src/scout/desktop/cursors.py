"""Pointing-hand cursor wherever the pointer is over something clickable.

Qt only shows the hand where code sets it, so clickable controls used to depend
on whoever remembered to call ``setCursor``. Instead we install one
application-level filter: when the pointer enters a clickable widget (or a child
of one, like the icon inside a button) it gets the hand; disabled widgets, plain
labels, text editors and scroll bars keep the arrow.

Custom clickable widgets (not covered by the built-in types) opt in with
``widget.setProperty("clickable", True)``.
"""
from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QMenu,
    QMenuBar,
    QPlainTextEdit,
    QTabBar,
    QTextBrowser,
    QWidget,
)

HAND = Qt.CursorShape.PointingHandCursor
MARK = "scoutPointer"

_CLICKABLE_TYPES = (
    QAbstractButton,
    QComboBox,
    QTabBar,
    QMenu,
    QMenuBar,
    QAbstractItemView,
)

# Interactive controls that must keep their own cursor and never inherit the
# hand from a clickable ancestor (scroll bars inside a table, text cursors...).
_BARRIER_TYPES = (
    QAbstractSlider,
    QAbstractSpinBox,
    QLineEdit,
    QPlainTextEdit,
    QTextBrowser,
)

_ANCESTOR_DEPTH = 4


_ANCHOR = re.compile(r"<\s*a\s+[^>]*href", re.IGNORECASE)


def _has_links(widget: QWidget) -> bool:
    # QLabel defaults to LinksAccessibleByMouse, so the flag alone would make
    # every label look clickable; require an actual anchor in the text.
    text = getattr(widget, "text", None)
    if not callable(text):
        return False
    if not _ANCHOR.search(text() or ""):
        return False
    try:
        return bool(widget.textInteractionFlags() & Qt.TextInteractionFlag.LinksAccessibleByMouse)
    except (AttributeError, TypeError):
        return False


def _clickable(widget: QWidget) -> bool:
    if not widget.isEnabled() or not widget.isVisible():
        return False
    if isinstance(widget, _CLICKABLE_TYPES):
        return True
    if isinstance(widget, QLabel):
        return _has_links(widget)
    return bool(widget.property("clickable"))


class PointerCursorFilter(QObject):
    """Give the hand to clickable widgets on Enter; give it back when disabled."""

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.Type.Enter:
            self._enter(watched)
        elif kind == QEvent.Type.EnabledChange and isinstance(watched, QWidget):
            if not watched.isEnabled():
                self._release(watched)
        return False

    def _enter(self, watched):
        if not isinstance(watched, QWidget):
            return
        if isinstance(watched, _BARRIER_TYPES) and not _has_links(watched):
            return
        target = watched if _clickable(watched) else self._clickable_ancestor(watched)
        if target is not None:
            if target.cursor().shape() != HAND:
                target.setCursor(HAND)
                target.setProperty(MARK, True)
        elif watched.property(MARK):
            self._release(watched)

    @staticmethod
    def _clickable_ancestor(widget: QWidget) -> QWidget | None:
        node = widget.parentWidget()
        for _ in range(_ANCESTOR_DEPTH):
            if node is None:
                return None
            if isinstance(node, _BARRIER_TYPES):
                return None
            if _clickable(node):
                return node
            node = node.parentWidget()
        return None

    @staticmethod
    def _release(widget: QWidget) -> None:
        if widget.property(MARK):
            widget.unsetCursor()
            widget.setProperty(MARK, False)


def install_pointer_cursors(app=None) -> PointerCursorFilter | None:
    """Install the filter once per application; safe to call repeatedly."""
    app = app or QApplication.instance()
    if app is None:
        return None
    existing = getattr(app, "_scout_pointer_filter", None)
    if existing is not None:
        return existing
    watcher = PointerCursorFilter(app)
    app.installEventFilter(watcher)
    setattr(app, "_scout_pointer_filter", watcher)
    return watcher
