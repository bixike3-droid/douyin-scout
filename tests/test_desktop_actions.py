"""Restore desktop operations without real account access or paid API calls."""
import asyncio
import json
import time

import pytest

from scout.desktop.actions import export_state, login, login_status, save_identity
from scout.session.lock import ProfileLock


PAYLOAD = {"status_code": 0, "user": {"sec_uid": "owner", "nickname": "测试账号"}}


class Page:
    def __init__(self, payload):
        self.payload = payload

    async def goto(self, *args, **kwargs):
        pass

    def is_closed(self):
        return False

    async def evaluate(self, *args):
        return self.payload


class BrowserContext:
    def __init__(self, payload):
        self.pages = [Page(payload)]
        self.closed = False

    async def cookies(self):
        return []

    async def storage_state(self, path):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"cookies": [{"name": "sessionid", "domain": ".douyin.com", "value": "private",
                                    "expires": time.time() + 3600}], "origins": []}, handle)

    async def close(self):
        self.closed = True


def fake_playwright(monkeypatch, payload):
    import playwright.async_api
    context = BrowserContext(payload)
    class Manager:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        @property
        def chromium(self):
            return self
        async def launch_persistent_context(self, **kwargs):
            assert kwargs["headless"] is False
            return context
    monkeypatch.setattr(playwright.async_api, "async_playwright", Manager)
    return context


def test_login_saves_identity_state_and_releases_browser(ctx, monkeypatch):
    context = fake_playwright(monkeypatch, PAYLOAD)
    result = asyncio.run(login(ctx, lambda event: None))
    assert result["nickname"] == "测试账号"
    assert ctx.cursors.get("self_sec_uid") == "owner"
    assert ctx.users.get("owner")["nickname"] == "测试账号"
    assert login_status(ctx.paths)["saved"]
    assert context.closed
    assert not ProfileLock.status(ctx.config.tier("a").resolved_profile_dir(ctx.paths))["locked"]


def test_login_rejects_other_account_without_overwriting_state(ctx, monkeypatch):
    ctx.cursors.set("self_sec_uid", "original")
    target = ctx.paths.state_dir / "tier_a_storage.json"
    target.write_text('{"original": true}', encoding="utf-8")
    context = fake_playwright(monkeypatch, PAYLOAD)
    with pytest.raises(ValueError, match="另一抖音账号"):
        asyncio.run(login(ctx, lambda event: None))
    assert ctx.cursors.get("self_sec_uid") == "original"
    assert json.loads(target.read_text(encoding="utf-8")) == {"original": True}
    assert context.closed


def test_login_timeout_and_cancellation_release_resources(ctx, monkeypatch):
    context = fake_playwright(monkeypatch, None)
    with pytest.raises(TimeoutError):
        asyncio.run(login(ctx, lambda event: None, timeout=0.01, poll_interval=0.001))
    assert context.closed
    context = fake_playwright(monkeypatch, None)
    async def cancel():
        task = asyncio.create_task(login(ctx, lambda event: None, poll_interval=0.001))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(cancel())
    assert context.closed
    assert not ProfileLock.status(ctx.config.tier("a").resolved_profile_dir(ctx.paths))["locked"]


def test_export_failure_keeps_previous_state(paths):
    target = paths.state_dir / "tier_a_storage.json"
    target.write_text("previous", encoding="utf-8")
    class BrokenContext:
        async def storage_state(self, path):
            raise OSError("export failed")
    with pytest.raises(OSError):
        asyncio.run(export_state(BrokenContext(), target))
    assert target.read_text(encoding="utf-8") == "previous"
    assert not list(target.parent.glob(".login-*.json"))


def test_saved_state_status_handles_expired_foreign_and_malformed_files(paths):
    target = paths.state_dir / "tier_a_storage.json"
    for data in ([], {"cookies": [{"name": "sessionid", "domain": ".douyin.com", "expires": 1}]},
                 {"cookies": [{"name": "sessionid", "domain": "other.example", "expires": -1}]}):
        target.write_text(json.dumps(data), encoding="utf-8")
        assert not login_status(paths)["saved"]


def test_identity_validation_does_not_mix_account_data(ctx):
    ctx.cursors.set("self_sec_uid", "original")
    with pytest.raises(ValueError):
        save_identity(ctx, PAYLOAD)
    assert ctx.users.get("owner") is None


def test_failed_session_start_is_closed(ctx, monkeypatch):
    import scout.session.manager
    closed = []
    class FailedManager:
        def __init__(self, *args, **kwargs):
            pass
        async def start(self):
            raise OSError("browser not available")
        async def stop(self):
            closed.append(True)
    monkeypatch.setattr(scout.session.manager, "SessionManager", FailedManager)
    with pytest.raises(OSError):
        asyncio.run(ctx.open_session())
    assert closed and ctx.session is None


def test_collection_operation_dispatches_engine_and_closes_session(ctx, monkeypatch):
    import scout.desktop.actions as actions
    import scout.schedule
    from scout.schedule.engine import RoundReport
    observed = []
    class Session:
        async def goto(self, *args):
            return Page(PAYLOAD)
        async def stop(self):
            observed.append("closed")
    ctx.session = Session()
    class Engine:
        def __init__(self, context):
            assert context.config.tier("a").use_storage_state
            assert context.cursors.get("self_sec_uid") == "owner"
        def seed(self):
            observed.append("seed")
            return {}
        async def run_round(self, **kwargs):
            assert kwargs["kinds"] == ["fetch_likers"]
            assert kwargs["max_tasks"] == 5
            return RoundReport(ok=1, attempted=1)
    monkeypatch.setattr(scout.schedule, "Engine", Engine)
    monkeypatch.setattr(actions, "login_status", lambda paths: {"saved": True})
    monkeypatch.setattr(actions.AppContext, "create", lambda *args: ctx)
    result = asyncio.run(actions.execute(ctx.paths, "collect", lambda event: None, {"kinds": "fetch_likers", "limit": 5}))
    assert result["report"]["ok"] == 1
    assert observed == ["seed", "closed"]


@pytest.mark.parametrize("kind", ["profile", "review", "plan"])
def test_analysis_operations_dispatch_without_real_api_calls(ctx, monkeypatch, kind):
    import scout.desktop.actions as actions
    import scout.analyze.ai as ai
    import scout.analyze.creator as creator
    import scout.llm
    from scout.analyze.ai import AnalysisResult
    visited = []
    monkeypatch.setattr(scout.llm, "DeepSeekClient", lambda cfg: object())
    monkeypatch.setattr(ai, "pending_targets", lambda *args, **kwargs: ["owner"])
    async def many(context, client, targets, **kwargs):
        visited.append("profile")
        assert targets == ["owner"] and kwargs["force"]
        return [{"ok": True}]
    async def review(context, client, **kwargs):
        visited.append("review")
        assert kwargs["force"]
        return AnalysisResult(ok=True, subject_id="me")
    async def plan(context, client, **kwargs):
        visited.append("plan")
        assert kwargs["force"]
        return AnalysisResult(ok=True, subject_id="me")
    monkeypatch.setattr(ai, "analyze_many", many)
    monkeypatch.setattr(creator, "analyze_review", review)
    monkeypatch.setattr(creator, "analyze_plan", plan)
    monkeypatch.setattr(actions.AppContext, "create", lambda *args: ctx)
    result = asyncio.run(actions.execute(ctx.paths, kind, lambda event: None, {"force": True}))
    assert result["message"] and visited == [kind]
