"""Exercise the native buttons through background generation and export."""
import json

from test_desktop import qt_app, pump
from test_enterprise import FakeClient, brief, add_work
from scout.desktop.service import DesktopService
from scout.store.enterprise import EnterpriseStore


def settled(window):
    return not window.jobs.busy and not window.operations.busy and not window.pending


def test_native_enterprise_complete_flow_and_feedback(qt_app, ctx, monkeypatch, tmp_path):
    import scout.llm
    from PySide6.QtWidgets import QFileDialog
    from scout.desktop.window import MainWindow
    add_work(ctx)
    from test_workflow import WorkflowClient
    client = WorkflowClient()
    monkeypatch.setattr(scout.llm, "DeepSeekClient", lambda cfg: client)
    service = DesktopService(ctx.paths)
    service.save_settings("sk-test-never-sent", "test-model")
    window = MainWindow(service)
    window.show()
    try:
        pump(qt_app, lambda: window.initialized and window.enterprise.loaded and settled(window))
        pane = window.enterprise
        assert window.nav.currentRow() == 0 and "源镜" in window.windowTitle()
        pane.fields["features"].setPlainText(brief()["features"])
        pane.fields["offer"].setPlainText(brief()["offer"])
        pane.fields["source"].setText(brief()["source"])
        pane.account_confirmed.setChecked(True)
        pane.generate_button.click()
        assert not client.calls and pane.tabs.currentIndex() == 0
        pane.save_profile_button.click()
        pump(qt_app, lambda: not pane.profile_dirty and settled(window))
        pane.metric_fields["play_count"].setText("0")
        pane.metric_source.setText("模拟后台截图")
        pane.metric_date.setText("2026-10-10")
        pane.metrics_button.click()
        pump(qt_app, lambda: "模拟后台截图" in pane.metric_history.toPlainText() and settled(window))
        window.nav.setCurrentRow(1)
        pump(qt_app, lambda: window.records["works"].model.rowCount() == 1 and settled(window))
        assert window.records["works"].model.rows[0]["play_count"] == 0
        assert "人工补录" in window.records["works"].model.rows[0]["metric_note"]
        window.nav.setCurrentRow(0)
        pump(qt_app, lambda: settled(window))
        pane.composer.setPlainText("仅用已有数据，为企业生成周末散客传播方案")
        pane.generate_button.click()
        pump(qt_app, lambda: pane.current_report is not None and settled(window))
        assert "个性化选题" in pane.editor.toPlainText()
        assert "W1" in pane.evidence.toPlainText()
        first_id = pane.current_report["id"]
        pane.editor.appendPlainText("\n人工修改：预约渠道待运营方确认。")
        pane.reason.setText("模拟复核：产品信息已检查，渠道仍待确认")
        pane.reviewed.setChecked(True)
        pane.save_revision_button.click()
        pump(qt_app, lambda: not pane.report_dirty and settled(window))
        target = tmp_path / "决策记录.md"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(target), "Markdown (*.md)"))
        pane.export_button.click()
        assert "人工修改" in target.read_text(encoding="utf-8")
        assert "原始模型建议" in target.read_text(encoding="utf-8")
        pane.generate_button.click()
        pump(qt_app, lambda: settled(window))
        assert len(client.calls) == 2 and pane.current_report["id"] == first_id
        pane.fields["feedback"].setPlainText("模拟复盘：已执行报告1的选题，未获得到店记录")
        pane.feedback_report.setCurrentIndex(pane.feedback_report.findData(first_id))
        pane.save_profile_button.click()
        pump(qt_app, lambda: not pane.profile_dirty and settled(window))
        pane.workflow_card.rerun.click()
        pump(qt_app, lambda: pane.current_report is not None and pane.current_report["id"] != first_id and settled(window))
        assert len(client.calls) == 4
        assert "E2" in pane.evidence.toPlainText()
        assert "E3" in pane.evidence.toPlainText()
        assert ctx.db.scalar("SELECT COUNT(*) FROM enterprise_revisions") == 1
        # Previously edited report remains available and the raw metrics stay unchanged.
        pane.report_select.setCurrentIndex(pane.report_select.findData(first_id))
        pump(qt_app, lambda: pane.current_report["id"] == first_id and settled(window))
        assert "人工修改" in pane.editor.toPlainText()
        assert ctx.db.scalar("SELECT play_count FROM works WHERE aweme_id='mine'") is None
    finally:
        window.close()


def test_enterprise_drafts_survive_refresh_and_review_is_invalidated_on_edit(qt_app, ctx):
    from scout.desktop.enterprise import EnterprisePage
    pane = EnterprisePage()
    store = EnterpriseStore(ctx.db)
    pane.apply_workspace(store.workspace())
    pane.fields["goal"].setText("未保存的本轮目标")
    pane.apply_workspace(store.workspace())
    assert pane.fields["goal"].text() == "未保存的本轮目标"
    pane.current_report = {"id": 1}
    pane.reviewed.setChecked(True)
    pane.editor.setPlainText("重新编辑的稿件")
    assert pane.report_dirty and not pane.reviewed.isChecked()


def test_close_preserves_unsaved_enterprise_brief_until_discard_is_selected(qt_app, ctx, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from scout.desktop.window import MainWindow
    window = MainWindow(DesktopService(ctx.paths))
    window.show()
    pump(qt_app, lambda: window.initialized and settled(window))
    window.enterprise.fields["goal"].setText("尚未保存的目标")
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    window.close()
    assert window.isVisible() and not window.closing
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.close()
    assert not window.isVisible() and window.closing
