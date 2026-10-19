"""Theme switching cross-fades the old look instead of jumping."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtGui import QPalette

from test_desktop import pump, qt_app  # noqa: F401  (qt_app is a fixture)
from test_enterprise_gui import settled
from scout.desktop.appearance import THEMES
from scout.desktop.service import DesktopService
from scout.desktop.window import MainWindow


def _ready(qt_app, ctx):
    window = MainWindow(DesktopService(ctx.paths))
    window.show()
    pump(qt_app, lambda: window.initialized and settled(window))
    return window


def test_theme_switch_shows_old_snapshot_then_fades(qt_app, ctx):
    window = _ready(qt_app, ctx)
    try:
        window.motion_enabled = True
        window._set_appearance("dark")
        overlay = window._theme_overlay
        assert overlay is not None and overlay.isVisible()
        assert overlay.pixmap() is not None and not overlay.pixmap().isNull()
        assert window.palette().color(QPalette.ColorRole.Window).name() == THEMES["dark"]["window"].lower()
        pump(qt_app, lambda: window._theme_overlay is None, timeout=3)
    finally:
        window.close()
        pump(qt_app, lambda: not window.isVisible())


def test_theme_switch_without_motion_applies_directly(qt_app, ctx):
    window = _ready(qt_app, ctx)
    try:
        window.motion_enabled = False
        window._set_appearance("dark")
        assert window._theme_overlay is None
        assert window.palette().color(QPalette.ColorRole.Window).name() == THEMES["dark"]["window"].lower()
    finally:
        window.close()
        pump(qt_app, lambda: not window.isVisible())


def test_rapid_theme_toggles_keep_single_overlay(qt_app, ctx):
    window = _ready(qt_app, ctx)
    try:
        window.motion_enabled = True
        window._set_appearance("dark")
        first = window._theme_overlay
        window._set_appearance("light")
        second = window._theme_overlay
        assert second is not None and second is not first
        pump(qt_app, lambda: window._theme_overlay is None, timeout=3)
    finally:
        window.close()
        pump(qt_app, lambda: not window.isVisible())
