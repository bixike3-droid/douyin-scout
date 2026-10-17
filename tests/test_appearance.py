"""Appearance changes preserve working state and remain readable in both modes."""
import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

from test_desktop import qt_app, pump
from test_enterprise_gui import settled
from scout.desktop.appearance import THEMES, color
from scout.desktop.components import ElidedLabel
from scout.desktop.service import DesktopService
from scout.store.conversation import Conversations


def luminance(hex_color):
    color = QColor(hex_color)
    channels = [color.redF(), color.greenF(), color.blueF()]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
    return sum(weight * value for weight, value in zip((0.2126, 0.7152, 0.0722), linear))


def contrast(first, second):
    values = sorted((luminance(first), luminance(second)))
    return (values[1] + .05) / (values[0] + .05)


def test_both_palettes_keep_body_secondary_and_status_text_readable():
    assert set(THEMES) == {"light", "dark"}
    for theme in THEMES.values():
        for surface in ("surface", "window", "toolbar", "sidebar", "assistant", "user"):
            assert contrast(theme["text"], theme[surface]) >= 4.5
            assert contrast(theme["muted"], theme[surface]) >= 4.5
        for foreground, background in (("success", "success_bg"), ("warning", "warning_bg"), ("danger", "danger_bg")):
            assert contrast(theme[foreground], theme[background]) >= 4.5


def test_theme_switch_preserves_drafts_history_and_existing_sections(qt_app, ctx):
    from scout.desktop.window import MainWindow, PAGES
    from scout.desktop.harness import SafeMessageBrowser
    store = Conversations(ctx.db)
    conversation_id = store.create("用于验证切换主题时保留历史")
    store.add(conversation_id, "user", "保留这条消息")
    store.add(conversation_id, "assistant", "保留已有结论", agent="audience")
    window = MainWindow(DesktopService(ctx.paths))
    window.show()
    try:
        pump(qt_app, lambda: window.initialized and settled(window))
        pane = window.enterprise
        pane.apply_conversation(store.get(conversation_id))
        pane.composer.setPlainText("尚未发送的下一条需求")
        contents = [bubble.toPlainText() for bubble in pane.transcript.findChildren(SafeMessageBrowser)]
        pane.fields["features"].setPlainText("尚未保存的企业资料")
        window.key_input.setText("未保存的输入")
        window.appearance_button.click()
        assert window.appearance_mode == "dark" and window.appearance_combo.currentData() == "dark"
        assert window.palette().color(QPalette.ColorRole.Window).name() == THEMES["dark"]["window"].lower()
        assert pane.composer.toPlainText() == "尚未发送的下一条需求"
        assert pane.fields["features"].toPlainText() == "尚未保存的企业资料" and pane.profile_dirty
        assert window.key_input.text() == "未保存的输入"
        assert pane.conversation_id == conversation_id
        assert [bubble.toPlainText() for bubble in pane.transcript.findChildren(SafeMessageBrowser)] == contents
        assert [window.nav.item(i).text() for i in range(window.nav.count())] == [name for name, _ in PAGES]
        assert [pane.right_tabs.tabText(i) for i in range(pane.right_tabs.count())] == ["抖音热点", "内容方案"]
        window.appearance_combo.setCurrentIndex(window.appearance_combo.findData("light"))
        assert window.appearance_mode == "light" and window.appearance_button.text() == "浅色"
        assert pane.composer.toPlainText() == "尚未发送的下一条需求"
    finally:
        pane.profile_dirty = False
        window.close()
        pump(qt_app, lambda: not window.isVisible())


def test_appearance_preference_survives_restart_and_icons_follow_palette(qt_app, ctx):
    from scout.desktop.window import MainWindow
    from scout.desktop.theme import icon
    window = MainWindow(DesktopService(ctx.paths))
    window.show()
    try:
        pump(qt_app, lambda: window.initialized and settled(window))
        shared_icon = icon("copy", size=20)
        light = shared_icon.pixmap(20, 20).toImage()
        window._set_appearance("dark")
        dark = shared_icon.pixmap(20, 20).toImage()
        assert light != dark
        assert color("text") == THEMES["dark"]["text"]
    finally:
        window.close()
        pump(qt_app, lambda: not window.isVisible())
    restarted = MainWindow(DesktopService(ctx.paths))
    restarted.show()
    try:
        pump(qt_app, lambda: restarted.initialized and settled(restarted))
        assert restarted.appearance_mode == "dark"
        assert restarted.appearance_combo.count() == 3 and restarted.appearance_combo.currentData() == "dark"
    finally:
        restarted.close()
        pump(qt_app, lambda: not restarted.isVisible())


def test_long_titles_fit_visually_while_preserving_full_text(qt_app):
    title = "借势分析：" + "很长的任务标题，需要保留完整内容" * 12
    label = ElidedLabel(title, "historyTitle")
    label.resize(180, 28)
    label.show()
    qt_app.processEvents()
    try:
        assert label.text() == title and label.toolTip() == title
        assert label.minimumSizeHint().width() == 0
        assert label.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, label.width()) != title
        assert not label.grab().isNull()
    finally:
        label.close()
