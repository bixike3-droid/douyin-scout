"""Serial background operations with queued Qt signals."""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class Signals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.signals = Signals()

    @Slot()
    def run(self):
        try:
            self.signals.succeeded.emit(self.operation())
        except Exception as exc:
            self.signals.failed.emit(f"{type(exc).__name__}：{exc}")
        finally:
            self.signals.finished.emit()


class Jobs(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.worker = None

    @property
    def busy(self):
        return self.worker is not None

    def submit(self, operation):
        if self.busy:
            return False
        worker = Worker(operation)
        self.worker = worker
        worker.signals.succeeded.connect(self.succeeded)
        worker.signals.failed.connect(self.failed)
        worker.signals.finished.connect(self._finished)
        self.busy_changed.emit(True)
        self.pool.start(worker)
        return True

    @Slot()
    def _finished(self):
        self.worker = None
        self.busy_changed.emit(False)
