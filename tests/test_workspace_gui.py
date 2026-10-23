from test_desktop import qt_app
from scout.desktop.harness import HarnessPage
from PySide6.QtCore import QCoreApplication, QEvent

_application = None


def dispose(widget, app):
    global _application
    _application = app  # Keep QApplication alive across modules with native widgets.
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_active_codex_composer_steers_without_clearing_unaccepted_input(qt_app):
    pane = HarnessPage()
    requests, ordinary, cancelled = [], [], []
    pane.steer_requested.connect(requests.append)
    pane.task_requested.connect(lambda *args: ordinary.append(args))
    pane.cancel_requested.connect(lambda: cancelled.append(True))
    try:
        pane.set_processing(True)
        pane.set_controls_enabled(False)
        pane.set_codex_ready(True)
        pane.composer.setPlainText("优先处理视频")
        pane._generate()
        assert requests == ["优先处理视频"] and not ordinary
        assert pane.composer.isEnabled() and not pane.attach_button.isEnabled()
        assert pane.composer.toPlainText() == "优先处理视频"
        pane.steer_result({"accepted": False, "error": "try later"})
        assert pane.composer.toPlainText() == "优先处理视频"
        pane._generate()
        pane.steer_result({"accepted": True, "text": "优先处理视频", "message_id": 2})
        assert not pane.composer.toPlainText()
        pane._on_generate()
        assert cancelled == [True]
        pane.set_processing(False)
        assert not pane.codex_ready
    finally:
        dispose(pane, qt_app)


def test_session_menu_is_visible_only_for_codex_history(qt_app):
    pane = HarnessPage()
    actions = []
    pane.session_action_requested.connect(actions.append)
    data = {"id": 1, "title": "test", "created_at": "2026-10-22T12:00:00+08:00", "messages": [], "codex": True}
    try:
        pane.apply_conversation(data)
        assert not pane.session_button.isHidden()
        pane.session_button.menu().actions()[0].trigger()
        assert actions == ["fork"]
        pane.session_button.menu().actions()[1].trigger()
        assert actions == ["fork", "compact"]
        pane.new_task()
        assert pane.session_button.isHidden()
    finally:
        dispose(pane, qt_app)


def test_generated_image_tile_resolves_workspace_path(qt_app, ctx):
    from PIL import Image
    from scout.tools import workspace
    from scout.store.conversation import Conversations
    from scout.desktop.attachments import AttachmentTile
    ctx.tool_conversation_id = Conversations(ctx.db).create("generated")
    path = workspace.root(ctx) / "result.png"
    Image.new("RGB", (80, 50), "red").save(path)
    item = workspace.artifact_metadata(workspace.scan_artifacts(ctx)[0])
    tile = AttachmentTile(item, ctx.paths)
    try:
        assert tile.path == path and not tile.preview.isNull()
    finally:
        dispose(tile, qt_app)
