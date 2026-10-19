"""Hover cursor: everything clickable gets the pointing hand."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QLabel, QListWidget, QPushButton

from test_desktop import qt_app  # noqa: F401  (pytest fixture)


def test_buttons_get_hand_on_enter(qt_app):
    from scout.desktop.cursors import install_pointer_cursors

    install_pointer_cursors(qt_app)
    button = QPushButton("采集")
    button.show()
    qt_app.sendEvent(button, QEvent(QEvent.Type.Enter))
    assert button.cursor().shape() == Qt.CursorShape.PointingHandCursor
    button.close()


def test_disabled_button_keeps_arrow(qt_app):
    from scout.desktop.cursors import install_pointer_cursors

    install_pointer_cursors(qt_app)
    button = QPushButton("不可用")
    button.setEnabled(False)
    button.show()
    qt_app.sendEvent(button, QEvent(QEvent.Type.Enter))
    assert button.cursor().shape() == Qt.CursorShape.ArrowCursor
    button.close()


def test_item_view_rows_get_hand_on_enter(qt_app):
    from scout.desktop.cursors import install_pointer_cursors

    install_pointer_cursors(qt_app)
    view = QListWidget()
    view.addItem("最近的任务")
    view.show()
    viewport = view.viewport()
    qt_app.sendEvent(viewport, QEvent(QEvent.Type.Enter))
    assert view.cursor().shape() == Qt.CursorShape.PointingHandCursor
    view.close()


def test_plain_label_keeps_arrow_but_link_label_gets_hand(qt_app):
    from scout.desktop.cursors import install_pointer_cursors

    install_pointer_cursors(qt_app)
    plain = QLabel("说明文字")
    plain.show()
    qt_app.sendEvent(plain, QEvent(QEvent.Type.Enter))
    assert plain.cursor().shape() == Qt.CursorShape.ArrowCursor

    link = QLabel('<a href="https://example.com">来源</a>')
    link.setTextFormat(Qt.TextFormat.RichText)
    link.setOpenExternalLinks(True)
    link.show()
    qt_app.sendEvent(link, QEvent(QEvent.Type.Enter))
    assert link.cursor().shape() == Qt.CursorShape.PointingHandCursor
    plain.close()
    link.close()
