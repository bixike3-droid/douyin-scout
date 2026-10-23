"""Drag/drop, compact tiles, previews and real send wiring through Qt."""
from pathlib import Path

from PySide6.QtCore import Qt, QMimeData, QUrl, QPointF, QPoint
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QEnterEvent, QImage
from PySide6.QtTest import QTest
from PIL import Image

from test_desktop import qt_app, pump
from test_enterprise_gui import settled
from test_workflow_gui import workflow_window
from test_attachments import FileClient
from scout.desktop.attachments import AttachmentTray, AttachmentTile, AttachmentGroup
from scout.desktop.harness import Composer


def test_composer_drop_and_paste_files_preserve_typed_text(qt_app, tmp_path):
    source = tmp_path / "brief.txt"
    source.write_text("brief", encoding="utf-8")
    composer = Composer()
    composer.show()
    composer.setPlainText("保留正在输入的需求")
    received = []
    composer.files_added.connect(received.extend)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(source))])
    enter = QDragEnterEvent(QPoint(8, 8), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    composer.dragEnterEvent(enter)
    assert enter.isAccepted()
    drop = QDropEvent(QPointF(8, 8), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    composer.dropEvent(drop)
    composer.insertFromMimeData(mime)
    assert list(map(Path, received)) == [source, source]
    assert composer.toPlainText() == "保留正在输入的需求"
    composer.close()


def test_tray_is_one_horizontal_row_and_hover_remove_works(qt_app, tmp_path):
    image = tmp_path / "image.png"
    Image.new("RGB", (160, 90), "teal").save(image)
    document = tmp_path / "需求说明.txt"
    document.write_text("需求", encoding="utf-8")
    tray = AttachmentTray()
    tray.resize(480, 96)
    tray.show()
    errors = []
    tray.error.connect(errors.append)
    tray.add_files([str(image), str(document), str(image)])
    pump(qt_app, lambda: tray.isVisible())
    tiles = tray.findChildren(AttachmentTile)
    assert len(tiles) == 2 and tray.height() == 96
    assert tiles[0].kind == "image" and tiles[0].width() == 82
    assert tiles[1].kind == "document" and tiles[1].height() == 72
    from PySide6.QtCore import QEvent
    tiles[0].leaveEvent(QEvent(QEvent.Type.Leave))
    assert not tiles[0].remove_button.isVisible()
    tiles[0].enterEvent(QEnterEvent(QPointF(10, 10), QPointF(10, 10), QPointF(10, 10)))
    assert tiles[0].remove_button.isVisible()
    QTest.mouseClick(tiles[0].remove_button, Qt.MouseButton.LeftButton)
    assert tray.paths == [str(document)]
    tray.add_files([str(tmp_path)])
    assert errors and tray.paths == [str(document)]
    tray.clear()
    assert not tray.isVisible()
    tray.close()


def test_real_chat_sends_dropped_files_and_restores_attachment_group(qt_app, ctx, monkeypatch, tmp_path):
    source = tmp_path / "预算说明.txt"
    source.write_text("固定预算 5000 元", encoding="utf-8")
    client = FileClient()
    window = workflow_window(ctx, monkeypatch, client)
    try:
        pump(qt_app, lambda: window.initialized and settled(window))
        pane = window.enterprise
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(source))])
        pane.composer.insertFromMimeData(mime)
        assert pane.pending_attachment_paths() == [str(source)]
        window._set_appearance("dark")
        assert pane.pending_attachment_paths() == [str(source)]
        assert not pane.attachment_tray.grab().isNull()
        window._set_appearance("light")
        pane.generate_button.click()
        pump(qt_app, lambda: settled(window) and pane.conversation_data is not None, timeout=10)
        assert "固定预算 5000" in str(client.message_calls[-1])
        assert pane.conversation_data["messages"][0]["attachments"][0]["name"] == source.name
        assert not pane.attachment_tray.paths
        assert pane.transcript.findChildren(AttachmentGroup)
        pane.apply_conversation(window.service.conversation(pane.conversation_id))
        assert pane.transcript.findChildren(AttachmentTile)[0].kind == "document"
    finally:
        window.close()
        pump(qt_app, lambda: not window.isVisible())


def test_image_tile_opens_preview_and_document_flow_wraps(qt_app, ctx, tmp_path):
    source = tmp_path / "image.png"
    Image.new("RGB", (200, 100), "teal").save(source)
    group = AttachmentGroup([{"name": source.name, "source_path": str(source), "size": 100, "status": "ready"}] * 3, ctx.paths)
    group.resize(390, 300)
    group.show()
    tiles = group.findChildren(AttachmentTile)
    pump(qt_app, lambda: tiles[2].y() > tiles[0].y())
    assert group.layout().heightForWidth(390) == 272
    QTest.mouseClick(tiles[0], Qt.MouseButton.LeftButton)
    assert tiles[0].preview_dialog.isVisible()
    tiles[0].preview_dialog.close()
    group.close()


def test_pasted_bitmap_becomes_image_tile_and_url_remains_text(qt_app):
    from scout.desktop.harness import HarnessPage
    page = HarnessPage()
    try:
        page.show()
        image = QImage(120, 90, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.cyan)
        mime = QMimeData()
        mime.setImageData(image)
        page.composer.insertFromMimeData(mime)
        assert len(page.attachment_tray.paths) == 1
        assert Path(page.attachment_tray.paths[0]).is_file()
        assert page.attachment_tray.findChildren(AttachmentTile)[0].kind == "image"
        link = QMimeData()
        link.setUrls([QUrl("https://example.com")])
        link.setText("https://example.com")
        page.composer.insertFromMimeData(link)
        assert "https://example.com" in page.composer.toPlainText()
    finally:
        page.close()


def test_video_tile_opens_local_player_and_stops_on_close(qt_app, tmp_path, monkeypatch):
    from scout.desktop.video import VideoCard
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"preview placeholder")
    calls = []
    monkeypatch.setattr(VideoCard, "play_file", lambda self, path: calls.append(("play", path)))
    monkeypatch.setattr(VideoCard, "stop", lambda self: calls.append(("stop", None)))
    tile = AttachmentTile({"name": source.name, "source_path": str(source), "status": "ready"})
    tile.show()
    QTest.mouseClick(tile, Qt.MouseButton.LeftButton)
    assert tile.preview_dialog.isVisible() and calls[0] == ("play", source)
    tile.preview_dialog.close()
    assert calls[-1] == ("stop", None)
    tile.close()


def test_zip_tile_previews_directory_and_binary_file_is_not_launched(qt_app, tmp_path, monkeypatch):
    import zipfile
    from PySide6.QtWidgets import QPlainTextEdit
    from PySide6.QtGui import QDesktopServices
    source = tmp_path / "素材.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("目录/需求.txt", "活动需求")
    tile = AttachmentTile({"name": source.name, "source_path": str(source), "size": source.stat().st_size})
    tile.show()
    QTest.mouseClick(tile, Qt.MouseButton.LeftButton)
    browser = tile.preview_dialog.findChild(QPlainTextEdit)
    pump(qt_app, lambda: "目录/需求.txt" in browser.toPlainText())
    tile.preview_dialog.close()
    tile.close()
    executable = tmp_path / "program.exe"
    executable.write_bytes(b"\x00\x01\x02")
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url))
    tile = AttachmentTile({"name": executable.name, "source_path": str(executable), "size": 3})
    tile.show()
    QTest.mouseClick(tile, Qt.MouseButton.LeftButton)
    assert tile.preview_dialog.isVisible() and not opened
    tile.preview_dialog.close()
    tile.close()


def test_material_workspace_shows_all_assets_search_and_original_preview(qt_app, ctx, tmp_path):
    from test_attachment_workspace import image_archive, VisionClient
    from scout.analyze.conversation import send
    from scout.desktop.attachments import WorkspaceDialog
    import asyncio
    source = tmp_path / "素材工作区.zip"
    image_archive(source, 29)
    result = asyncio.run(send(ctx, VisionClient(), "总览", agent_id="steward", attachment_paths=[str(source)]))
    item = result["conversation"]["messages"][0]["attachments"][0]
    dialog = WorkspaceDialog(item, ctx.paths)
    dialog.show()
    try:
        pump(qt_app, lambda: dialog.isVisible())
        assert "29/29" in dialog.summary.text() and len(dialog.scroll.widget().findChildren(AttachmentTile)) == 29
        dialog.search.setText("image-028")
        tiles = dialog.scroll.widget().findChildren(AttachmentTile)
        assert len(tiles) == 1
        QTest.mouseClick(tiles[0], Qt.MouseButton.LeftButton)
        assert tiles[0].preview_dialog.isVisible()
        tiles[0].preview_dialog.close()
        assert not dialog.continue_button.isEnabled()
    finally:
        dialog.close()
