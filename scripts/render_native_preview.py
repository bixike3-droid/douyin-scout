"""Render native pages against an existing DB, without collection or API calls."""
from __future__ import annotations

import argparse
import os
import time
import sqlite3
import tempfile
import shutil
from contextlib import closing
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--width", default=1440, type=int)
    parser.add_argument("--height", default=940, type=int)
    parser.add_argument("--appearance", choices=("light", "dark"), default="light")
    parser.add_argument("--conversation-id", type=int, help="Show a saved conversation in the workspace preview")
    args = parser.parse_args()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QAbstractAnimation
    from scout.desktop.service import DesktopService
    from scout.desktop.window import MainWindow, PAGES
    from scout.desktop.winapi import dwm_flush
    from scout.paths import Paths

    app = QApplication([])
    source = Paths.build(root=args.data_dir, data_dir=args.data_dir / "data")
    if not source.db_path.is_file():
        raise SystemExit(f"Database not found: {source.db_path}")
    # Migrate only a private snapshot, never the existing user database.
    snapshot = tempfile.TemporaryDirectory(prefix="scout-preview-")
    defaults = Path(__file__).resolve().parents[1] / "config" / "default.yaml"
    snapshot_config = Path(snapshot.name) / "config"
    snapshot_config.mkdir()
    shutil.copyfile(defaults, snapshot_config / "default.yaml")
    paths = Paths.build(root=Path(snapshot.name)).ensure()
    with closing(sqlite3.connect(f"file:{source.db_path.as_posix()}?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(paths.db_path)) as target:
            original.backup(target)
    service = DesktopService(paths)
    window = MainWindow(service)
    window._set_appearance(args.appearance)
    window.motion_enabled = False
    window.enterprise.set_motion(False)
    window.resize(args.width, args.height)
    window.show()
    args.output.mkdir(parents=True, exist_ok=True)
    def settle():
        deadline = time.monotonic() + 10
        stable_since = None
        while time.monotonic() < deadline:
            app.processEvents()
            ready = window.initialized and not window.jobs.busy and not window.pending
            animation = getattr(window.stack.currentWidget(), "_fade", None)
            if animation and animation.state() == QAbstractAnimation.State.Running:
                ready = False
            if ready:
                stable_since = stable_since or time.monotonic()
                if time.monotonic() - stable_since >= 0.05:
                    return
            else:
                stable_since = None
            time.sleep(0.01)
        raise RuntimeError("Preview timed out while waiting for native state")
    try:
        for index, (_, key) in enumerate(PAGES):
            window.nav.setCurrentRow(index)
            settle()
            if key == "enterprise" and args.conversation_id:
                conversation = service.conversation(args.conversation_id)
                window.enterprise.apply_conversation(conversation)
                if conversation.get("report_id"):
                    window.enterprise.apply_report(service.enterprise_report(conversation["report_id"]))
                    window.enterprise.right_tabs.setCurrentIndex(1)
                settle()
            if key in window.records and window.records[key].model.rowCount():
                window.records[key].table.selectRow(0)
            app.processEvents()
            dwm_flush()
            target = args.output / f"desktop-{key}.png"
            if not window.grab().save(str(target)):
                raise RuntimeError(f"Cannot save preview: {target}")
            if key == "enterprise":
                for tab, name in ((1, "decisions"), (2, "metrics")):
                    getattr(window.enterprise, "right_tabs", window.enterprise.tabs).setCurrentIndex(tab)
                    settle()
                    dwm_flush()
                    target = args.output / f"desktop-enterprise-{name}.png"
                    if not window.grab().save(str(target)):
                        raise RuntimeError(f"Cannot save preview: {target}")
                getattr(window.enterprise, "right_tabs", window.enterprise.tabs).setCurrentIndex(0)
        print(f"Rendered {len(PAGES)} native pages to {args.output}")
    finally:
        window.close()
        window.jobs.pool.waitForDone(10000)
        app.processEvents()
        window.close()
        snapshot.cleanup()


if __name__ == "__main__":
    main()
