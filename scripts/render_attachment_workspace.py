"""Render an existing account-local material workspace without calling a model."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
import argparse
import json
import time

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QThreadPool
from scout.paths import Paths
from scout.db.connect import Database
from scout.store.attachments import Attachments
from scout.desktop.attachments import WorkspaceDialog
from scout.desktop.theme import apply_theme


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    data_dir = Path(report["data_dir"])
    paths = Paths.build(root=Path(__file__).resolve().parents[1], data_dir=data_dir.parent.parent, account=data_dir.name)
    with Database.open(paths.db_path, read_only=True) as db:
        row = db.query_one("SELECT conversation_id FROM attachments WHERE id=?", (report["attachment_id"],))
        item = Attachments(db).get(report["attachment_id"], row[0])
    app = QApplication.instance() or QApplication([])
    apply_theme(app, "light")
    dialog = WorkspaceDialog(item, paths)
    dialog.show()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    dialog.grab().save(args.output)
    dialog.close()
    QThreadPool.globalInstance().waitForDone(30000)
    print(args.output)


if __name__ == "__main__":
    main()
