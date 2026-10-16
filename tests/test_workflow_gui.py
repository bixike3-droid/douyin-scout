"""Exercise workflow progress, continuation and stop through actual Qt signals."""
import asyncio
import json

from test_desktop import qt_app, pump
from test_enterprise_gui import settled
from test_workflow import WorkflowClient, seed_data
from scout.desktop.service import DesktopService


def workflow_window(ctx, monkeypatch, client):
    import scout.llm
    from scout.desktop.window import MainWindow
    seed_data(ctx)
    service = DesktopService(ctx.paths)
    service.save_settings("sk-test-never-sent", "test-model")
    monkeypatch.setattr(scout.llm, "DeepSeekClient", lambda cfg: client)
    window = MainWindow(service)
    window.show()
    return window


def test_workflow_card_resumes_failed_stage_and_shows_readable_evidence(qt_app, ctx, monkeypatch):
    from PySide6.QtWidgets import QTextBrowser
    client = WorkflowClient()
    client.fail_stage = "strategy"
    window = workflow_window(ctx, monkeypatch, client)
    try:
        pump(qt_app, lambda: window.initialized and settled(window))
        pane = window.enterprise
        pane.composer.setPlainText("仅用已有数据，分析受众和作品，给我三个下周选题")
        pane.generate_button.click()
        pump(qt_app, lambda: settled(window) and pane.workflow_card.run is not None, timeout=10)
        card = pane.workflow_card
        assert card.run["status"] == "failed" and card.resume.isEnabled()
        assert "传播策略师" in card.steps.text() and "失败" in card.steps.text()
        client.fail_stage = None
        card.resume.click()
        pump(qt_app, lambda: settled(window) and card.run["status"] == "complete", timeout=10)
        assert [c[1]["stage"] for c in client.calls] == ["audience", "content", "strategy", "strategy"]
        assert not card.resume.isVisible() and card.rerun.isEnabled()
        assert pane.current_report is not None and len(pane.current_report["output"]["topics"]) == 3
        card.details.click()
        assert card.dialog.isVisible()
        detail = card.dialog.findChild(QTextBrowser).toPlainText()
        assert "数据冻结时间" in detail and "W1" in detail and "受众分析" in detail
        assert '"evidence_ids"' not in detail
        card.dialog.close()
        # Reloading the conversation must restore the complete task card.
        pane.apply_conversation(window.service.conversation(pane.conversation_id))
        assert card.run["status"] == "complete"
    finally:
        window.close()
        pump(qt_app, lambda: not window.isVisible())


def test_stop_workflow_keeps_previous_artifacts_and_can_continue(qt_app, ctx, monkeypatch):
    class Waiting(WorkflowClient):
        waiting = True

        async def chat(self, system, user, **kwargs):
            try:
                stage = json.loads(user).get("stage")
            except ValueError:
                stage = None
            if stage == "strategy" and self.waiting:
                await asyncio.Event().wait()
            return await super().chat(system, user, **kwargs)

    client = Waiting()
    window = workflow_window(ctx, monkeypatch, client)
    try:
        pump(qt_app, lambda: window.initialized and settled(window))
        pane = window.enterprise
        pane.composer.setPlainText("仅用已有数据，生成三个选题")
        pane.generate_button.click()
        card = pane.workflow_card
        pump(qt_app, lambda: card.run is not None and len(card.run["artifacts"]) == 3 and card.run["steps"][3]["status"] == "running", timeout=10)
        assert pane.generate_button.text() == "停止" and not card.resume.isEnabled()
        pane.generate_button.click()
        pump(qt_app, lambda: settled(window) and card.run["status"] == "cancelled", timeout=10)
        assert len(card.run["artifacts"]) == 3
        client.waiting = False
        card.resume.click()
        pump(qt_app, lambda: settled(window) and card.run["status"] == "complete", timeout=10)
        assert card.run["steps"][0]["attempts"] == card.run["steps"][1]["attempts"] == 1
    finally:
        window.close()
        pump(qt_app, lambda: not window.isVisible())
