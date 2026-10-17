"""Desktop persistence, bounded queries and Qt worker lifecycle."""
from __future__ import annotations

import json
import threading
import time

import pytest

from scout.config import load_config
from scout.desktop.runtime import prepare_runtime
from scout.desktop.service import DesktopService
from scout.store.desktop import DesktopStore


def test_configuration_survives_restart_and_bundle_change(tmp_path, monkeypatch):
    import sys
    from pathlib import Path
    defaults = Path(__file__).resolve().parents[1] / "config" / "default.yaml"
    for name in ("bundle-one", "bundle-two"):
        bundle = tmp_path / name
        (bundle / "config").mkdir(parents=True)
        (bundle / "config" / "default.yaml").write_bytes(defaults.read_bytes())
    for key in ("SCOUT_ROOT", "SCOUT_DATA_DIR", "SCOUT_CONFIG_DIR", "SCOUT_ACCOUNT"):
        # Record even absent variables so prepare_runtime's writes are restored.
        monkeypatch.setenv(key, "main" if key == "SCOUT_ACCOUNT" else "")
    monkeypatch.setattr(sys, "_MEIPASS", tmp_path / "bundle-one", raising=False)
    paths = prepare_runtime(tmp_path / "userdata")
    service = DesktopService(paths)
    service.initialize()
    result = service.save_settings("sk-local-test-abcdefghijkl", "test-model")
    assert "sk-local-test-abcdefghijkl" not in json.dumps(result)
    monkeypatch.setattr(sys, "_MEIPASS", tmp_path / "bundle-two")
    restarted = prepare_runtime(tmp_path / "userdata")
    assert restarted.db_path == paths.db_path
    assert load_config(restarted).llm.api_key == "sk-local-test-abcdefghijkl"
    assert load_config(restarted).llm.model == "test-model"
    DesktopService(restarted).save_settings("", "changed-model")
    assert load_config(restarted).llm.api_key == "sk-local-test-abcdefghijkl"
    assert not (tmp_path / "bundle-one" / "config" / "llm.local.yaml").exists()
    assert not (tmp_path / "bundle-two" / "config" / "llm.local.yaml").exists()


def test_desktop_queries_page_and_search_literal_text(ctx):
    for index in range(105):
        ctx.works.upsert({"aweme_id": f"mine-{index}", "description": f"作品 {index}", "is_mine": 1})
    ctx.works.upsert({"aweme_id": "other", "description": "别人的作品"})
    ctx.works.upsert({"aweme_id": "literal", "description": "100%_真实", "is_mine": 1})
    store = DesktopStore(ctx.db)
    first = store.page("works")
    second = store.page("works", page=1)
    assert first["total"] == 106
    assert len(first["rows"]) == 100 and len(second["rows"]) == 6
    assert not ({r["aweme_id"] for r in first["rows"]} & {r["aweme_id"] for r in second["rows"]})
    assert store.page("works", "%_")["total"] == 1
    assert store.page("works", "' OR 1=1 --")["total"] == 0
    assert store.overview()["works"] == 106
    with pytest.raises(KeyError):
        store.page("untrusted-table")


def test_records_scope_links_likes_to_their_work(ctx):
    """互动数据按作品归口：人是互动作品列表，作品是已采点赞人列表。"""
    ctx.works.upsert({"aweme_id": "w1", "description": "校园视频", "is_mine": 1, "digg_count": 30})
    ctx.works.upsert({"aweme_id": "w2", "description": "食堂视频", "is_mine": 1, "digg_count": 5})
    ctx.users.upsert({"sec_uid": "u1", "nickname": "观众甲"})
    ctx.like_edges.add_many([
        {"sec_uid": "u1", "aweme_id": "w1", "notice_id": "n1"},
        {"sec_uid": "u1", "aweme_id": "w1", "notice_id": "api:w1"},  # 同一人同一作品：通知 + 接口
        {"sec_uid": "u1", "aweme_id": "w2", "notice_id": "n2"},
    ])
    store = DesktopStore(ctx.db)
    user = next(r for r in store.page("users")["rows"] if r["sec_uid"] == "u1")
    assert user["links"]["total"] == 2
    assert {i["id"] for i in user["links"]["items"]} == {"w1", "w2"}
    assert {i["label"] for i in user["links"]["items"]} == {"校园视频", "食堂视频"}
    work = next(r for r in store.page("works")["rows"] if r["aweme_id"] == "w1")
    assert work["links"]["total"] == 1                 # 两条边只算一个人
    assert work["links"]["items"][0]["label"] == "观众甲"


def test_records_detail_shows_linked_records(qt_app, ctx):
    """详情面板双向可查：互动者看到赞过的作品，作品看到点赞人。"""
    from scout.desktop.window import RecordsPage
    ctx.works.upsert({"aweme_id": "w1", "description": "校园视频", "is_mine": 1, "digg_count": 30})
    ctx.users.upsert({"sec_uid": "u1", "nickname": "观众甲"})
    ctx.like_edges.add_many([{"sec_uid": "u1", "aweme_id": "w1", "notice_id": "n1"}])
    store = DesktopStore(ctx.db)
    users_page = RecordsPage("users", lambda: None)
    users_page.apply(store.page("users"))
    users_page.table.selectRow(0)
    text = users_page.detail.toPlainText()
    assert "互动作品" in text and "校园视频" in text
    works_page = RecordsPage("works", lambda: None)
    works_page.apply(store.page("works"))
    works_page.table.selectRow(0)
    text = works_page.detail.toPlainText()
    assert "已采点赞人" in text and "观众甲" in text


def test_work_detail_offers_comment_collection(qt_app, ctx):
    """作品详情：选中即请求评论区数据，按钮可触发采集（信号）。"""
    from scout.desktop.window import RecordsPage
    ctx.works.upsert({"aweme_id": "w1", "description": "校园视频", "is_mine": 1, "comment_count": 30})
    page = RecordsPage("works", lambda: None)
    requested, collected = [], []
    page.work_selected.connect(requested.append)
    page.collect_comments_requested.connect(collected.append)
    page.apply(DesktopStore(ctx.db).page("works"))
    assert page.comments_button.isHidden()
    page.table.selectRow(0)
    assert requested == ["w1"] and not page.comments_button.isHidden()
    page.comments_button.click()
    assert collected == ["w1"]
    page.apply_comments({"aweme_id": "w1", "items": [
        {"text": "好评", "digg_count": 3, "reply_count": 1, "sec_uid": "u1"}]})
    text = page.detail.toPlainText()
    assert "评论区" in text and "好评" in text


def test_latest_analysis_is_unique_when_timestamps_tie(ctx):
    for digest in ("first", "second"):
        ctx.llm_results.save(subject_kind="user", subject_id="a", task="profile",
            prompt_version="v1", model="test", input_digest=digest, input_summary="test",
            output_json="{}", raw_text="{}")
    ctx.db.execute("UPDATE llm_results SET created_at='2026-10-11T00:00:00Z'")
    data = DesktopStore(ctx.db).page("analyses")
    assert data["total"] == 1
    assert data["rows"][0]["input_digest"] == "second"


def test_invalid_user_configuration_is_not_overwritten(paths):
    target = paths.config_dir / "llm.local.yaml"
    target.write_text("- broken\n", encoding="utf-8")
    with pytest.raises(ValueError):
        DesktopService(paths).save_settings("new", "model")
    assert target.read_text(encoding="utf-8") == "- broken\n"


@pytest.fixture
def qt_app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication, QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    app = QApplication.instance() or QApplication([])
    return app


def pump(app, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    stable_since = None
    while time.monotonic() < deadline:
        app.processEvents()
        # Qt may queue a refresh after a worker's finished signal. Wait for
        # the requested state to remain true across multiple event cycles.
        if predicate():
            stable_since = stable_since or time.monotonic()
            if time.monotonic() - stable_since >= 0.03:
                return
        else:
            stable_since = None
        time.sleep(0.005)
    assert predicate(), "Qt operation did not finish"


def test_frameless_window_restores_native_frame_messages(qt_app, ctx):
    """无边框窗口补回系统框架样式后，WM_NCCALCSIZE 仍保持客户区为整个窗口。"""
    import sys
    if sys.platform != "win32":
        pytest.skip("原生框架样式仅 Windows")
    import ctypes
    from ctypes import wintypes
    from scout.desktop.window import MainWindow
    window = MainWindow(DesktopService(ctx.paths))
    window.show()
    try:
        pump(qt_app, lambda: window.initialized and not window.jobs.busy)
        msg = wintypes.MSG()
        msg.message = 0x0083  # WM_NCCALCSIZE
        msg.wParam = 1
        handled, result = window.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg))
        assert handled and result == 0
    finally:
        window.close()


def test_records_model_reuses_same_length_rows(qt_app):
    """同长度刷新不重置模型：避免整表闪变，保留选中/滚动状态。"""
    from scout.desktop.window import RecordsModel
    model = RecordsModel([("名称", "name")], None)
    model.replace([{"name": "甲"}, {"name": "乙"}])
    resets = []
    model.modelReset.connect(lambda: resets.append(1))
    model.replace([{"name": "甲"}, {"name": "丙"}])
    assert resets == [] and model.index(1, 0).data() == "丙"
    model.replace([{"name": "甲"}])
    assert resets == [1]


def test_window_registers_keyboard_shortcuts(qt_app, ctx):
    from PySide6.QtGui import QKeySequence
    from scout.desktop.window import MainWindow
    window = MainWindow(DesktopService(ctx.paths))
    window.show()
    try:
        pump(qt_app, lambda: window.initialized and not window.jobs.busy and not window.pending)
        keys = {shortcut.key().toString() for shortcut in window._shortcuts}
        assert {"Ctrl+N", "Ctrl+R", "Ctrl+1", "Ctrl+7"} <= keys
        switch = next(shortcut for shortcut in window._shortcuts if shortcut.key() == QKeySequence("Ctrl+2"))
        switch.activated.emit()
        assert window.nav.currentRow() == 1
    finally:
        window.close()


def test_native_window_reads_records_and_selection(qt_app, ctx):
    from scout.desktop.window import MainWindow
    ctx.works.upsert({"aweme_id": "mine", "description": "测试作品", "is_mine": 1, "digg_count": 12})
    window = MainWindow(DesktopService(ctx.paths))
    window.show()
    try:
        pump(qt_app, lambda: window.initialized and not window.jobs.busy)
        assert window.metrics["works"].text() == "1"
        window.nav.setCurrentRow(1)
        pump(qt_app, lambda: not window.jobs.busy)
        pane = window.records["works"]
        assert pane.model.rowCount() == 1
        pane.table.selectRow(0)
        assert "测试作品" in pane.detail.toPlainText()
        pane.search.setText("不存在")
        pump(qt_app, lambda: pane.model.rowCount() == 0 and not window.jobs.busy)
        assert pane.count.text() == "暂无记录"
    finally:
        pump(qt_app, lambda: not window.jobs.busy)
        window.close()


def test_worker_is_off_gui_thread_serial_and_recovers(qt_app):
    from scout.desktop.jobs import Jobs
    jobs = Jobs()
    results, errors = [], []
    jobs.succeeded.connect(results.append)
    jobs.failed.connect(errors.append)
    gui_thread = threading.get_ident()
    assert jobs.submit(threading.get_ident)
    assert not jobs.submit(lambda: None)
    pump(qt_app, lambda: not jobs.busy)
    assert results and results[0] != gui_thread
    def fail():
        raise ValueError("expected failure")
    assert jobs.submit(fail)
    pump(qt_app, lambda: not jobs.busy)
    assert "expected failure" in errors[0]
    assert jobs.submit(lambda: "recovered")
    pump(qt_app, lambda: not jobs.busy)
    assert results[-1] == "recovered"


def test_close_waits_for_pending_operation(qt_app, paths):
    from scout.desktop.window import MainWindow
    service = DesktopService(paths)
    original = service.initialize
    release = threading.Event()
    def slow_initialize():
        release.wait(2)
        return original()
    service.initialize = slow_initialize
    window = MainWindow(service)
    window.show()
    qt_app.processEvents()
    assert window.jobs.busy
    window.close()
    assert window.isVisible()
    release.set()
    pump(qt_app, lambda: not window.isVisible())


def test_compact_overview_keeps_task_counts_legible(qt_app, ctx):
    from scout.desktop.window import MainWindow
    ctx.tasks.enqueue("fetch_self", "self", "a")
    window = MainWindow(DesktopService(ctx.paths))
    window.resize(1100, 760)
    window.show()
    try:
        pump(qt_app, lambda: window.initialized and not window.jobs.busy)
        assert window.task_summary.rows["pending"].text() == "1"
        for widget in window.task_summary.rows.values():
            assert widget.height() >= widget.fontMetrics().height()
    finally:
        window.close()


def test_operation_buttons_are_connected(qt_app, ctx, monkeypatch):
    from scout.desktop.window import MainWindow
    window = MainWindow(DesktopService(ctx.paths))
    window.show()
    captured = []
    try:
        pump(qt_app, lambda: window.initialized and not window.jobs.busy)
        monkeypatch.setattr(window, "_start_operation", captured.append)
        assert window.login_button.text() == "登录抖音"
        window.login_button.click()
        for button in window.operation_buttons:
            button.click()
        assert captured == ["login", "collect", "profile", "review", "plan"]
    finally:
        window.close()


def test_long_operation_cancel_on_close(qt_app, ctx, monkeypatch):
    import asyncio
    import scout.desktop.operations as operations
    from scout.desktop.window import MainWindow
    started, cleaned = threading.Event(), threading.Event()
    async def fake_execute(*args):
        started.set()
        try:
            await asyncio.sleep(30)
        finally:
            cleaned.set()
    monkeypatch.setattr(operations, "execute", fake_execute)
    window = MainWindow(DesktopService(ctx.paths))
    window.show()
    pump(qt_app, lambda: window.initialized and not window.jobs.busy)
    window.login_button.click()
    pump(qt_app, started.is_set)
    assert not window.operations.start("collect")
    window.close()
    pump(qt_app, lambda: not window.isVisible())
    assert cleaned.is_set() and not window.operations.busy


def test_queued_refresh_cannot_restart_work_after_close(qt_app, ctx):
    from PySide6.QtCore import QTimer
    from scout.desktop.window import MainWindow
    window = MainWindow(DesktopService(ctx.paths))
    window.show()
    pump(qt_app, lambda: window.initialized and not window.jobs.busy)
    QTimer.singleShot(0, window.refresh)
    window.close()
    qt_app.processEvents()
    assert window.closing and not window.isVisible() and not window.jobs.busy


def test_audience_filters_are_reversible_and_do_not_remove_quiet_viewer(qt_app,ctx):
    from scout.desktop.window import MainWindow
    ctx.cursors.set("self_sec_uid","owner")
    ctx.works.upsert({"aweme_id":"1","author_sec_uid":"owner","is_mine":1})
    ctx.works.upsert({"aweme_id":"2","author_sec_uid":"other"})
    for uid in ("quiet","foreign"):
        ctx.users.upsert({"sec_uid":uid,"nickname":uid,"follower_count":0})
    ctx.like_edges.add_many([{"sec_uid":"quiet","aweme_id":"1"},{"sec_uid":"foreign","aweme_id":"2"}])
    window=MainWindow(DesktopService(ctx.paths))
    window.show()
    try:
        pump(qt_app,lambda:window.initialized and not window.jobs.busy)
        window.nav.setCurrentRow(2)
        pane=window.records["users"]
        pump(qt_app,lambda:not window.jobs.busy and pane.model.rowCount()==1)
        assert pane.model.rows[0]["sec_uid"] == "quiet"
        window.audience_filter.setCurrentIndex(4)
        pump(qt_app,lambda:not window.jobs.busy and pane.model.rowCount()==2)
        assert ctx.like_edges.stats()["total"] == 2
    finally:
        window.close()
