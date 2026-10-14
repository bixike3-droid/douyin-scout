"""Check browser startup and cancellation in an isolated, unauthenticated profile."""
import asyncio
import argparse
import json
import os
import tempfile
import time
from pathlib import Path

from scout.app import AppContext
from scout.config import load_config
from scout.desktop.actions import login
from scout.desktop.runtime import prepare_runtime
from scout.session.lock import ProfileLock


async def check():
    root = Path(tempfile.mkdtemp(prefix="login-smoke-"))
    paths = prepare_runtime(root)
    ctx = AppContext.create(load_config(paths))
    ready = asyncio.Event()
    def emit(event):
        if "请在打开的浏览器" in event.get("message", ""):
            ready.set()
    task = asyncio.create_task(login(ctx, emit))
    try:
        await asyncio.wait_for(ready.wait(), 20)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        ctx.close()
    profile = ctx.config.tier("a").resolved_profile_dir(paths)
    result = {"browser_navigation_ready": ready.is_set(),
              "profile_lock_released": not ProfileLock.status(profile)["locked"],
              "login_state_exported": (paths.state_dir / "tier_a_storage.json").exists()}
    print(json.dumps(result))
    assert result["browser_navigation_ready"] and result["profile_lock_released"]
    assert not result["login_state_exported"]


def check_native():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication, QMessageBox
    from scout.desktop.service import DesktopService
    from scout.desktop.window import MainWindow

    app = QApplication([])
    QMessageBox.warning = lambda *args: QMessageBox.StandardButton.Ok
    root = Path(tempfile.mkdtemp(prefix="native-login-smoke-"))
    paths = prepare_runtime(root)
    window = MainWindow(DesktopService(paths))
    errors = []
    window.operations.failed.connect(errors.append)
    window.show()

    def wait(predicate, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            if predicate():
                return True
            time.sleep(0.01)
        return False

    try:
        assert wait(lambda: window.initialized and not window.jobs.busy, 10)
        window.login_button.click()
        assert wait(lambda: "请在打开的浏览器" in window.operation_message.text() or bool(errors), 25)
        assert not errors, errors
        window.operations.cancel()
        assert wait(lambda: not window.operations.busy, 10)
        profile = load_config(paths).tier("a").resolved_profile_dir(paths)
        assert not ProfileLock.status(profile)["locked"]
        assert not (paths.state_dir / "tier_a_storage.json").exists()
        print(json.dumps({"native_login_button_started_browser": True, "cancelled_and_released": True}))
    finally:
        window.operations.cancel()
        wait(lambda: not window.operations.busy, 10)
        window.close()
        wait(lambda: not window.isVisible() and not window.jobs.busy, 10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", action="store_true")
    args = parser.parse_args()
    check_native() if args.native else asyncio.run(check())
