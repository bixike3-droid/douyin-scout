"""Source preview: reload on code changes only when user work is safely saved."""
import sys
import time
from pathlib import Path
from PySide6.QtCore import QObject, QTimer, QProcess


class DevReload(QObject):
    def __init__(self, window, root):
        super().__init__(window)
        self.window, self.root = window, Path(root)
        self.pending_since = None
        self.baseline = self.fingerprint()
        self.observed = self.baseline
        self.timer = QTimer(self)
        self.timer.setInterval(1200)
        self.timer.timeout.connect(self.check)
        self.timer.start()
        window.setWindowTitle("源镜 · 开发预览")
        window.title_bar.brand.setText("源镜 · 开发预览")
        window.statusBar().showMessage("源码预览：修改后自动重载；运行中或未保存的输入会等待。", 10000)

    def files(self):
        return sorted(list((self.root / "src/scout").rglob("*.py")) + [self.root / "desktop/app.py", self.root / "config/default.yaml"])

    def fingerprint(self):
        return tuple((str(p), p.stat().st_mtime_ns) for p in self.files() if p.exists())

    def safe(self):
        w = self.window
        return (w.initialized and not w.closing and not w.jobs.busy and not w.operations.busy
                and not w.enterprise.profile_dirty and not w.enterprise.report_dirty
                and not w.enterprise.composer.toPlainText().strip() and not w.key_input.text()
                and w.model_input.text() == getattr(w, "saved_model", ""))

    def check(self):
        current = self.fingerprint()
        if current != self.observed:
            self.observed = current
            self.pending_since = time.monotonic()
        if current == self.baseline or self.pending_since is None:
            return
        if not self.safe():
            self.window.statusBar().showMessage("代码已更新：等待当前任务结束或保存/清空未保存输入，再自动重载。")
            return
        if time.monotonic() - self.pending_since < 1.0:
            return
        try:
            for path in self.files():
                if path.suffix == ".py":
                    compile(path.read_bytes(), str(path), "exec")
        except (OSError, SyntaxError) as exc:
            self.window.statusBar().showMessage(f"源码暂未通过检查，保留当前窗口：{exc}")
            return
        self.timer.stop()
        args = [str(self.root / "desktop/app.py"), "--data-dir", str(self.window.service.paths.root), "--dev-mode"]
        started, pid = QProcess.startDetached(sys.executable, args, str(self.root))
        if started:
            self.window.close()
        else:
            self.window.statusBar().showMessage("自动重载启动失败，可重新点击开发预览快捷方式。")
            self.timer.start()
