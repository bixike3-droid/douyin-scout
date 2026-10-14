"""Cancellable long operations, independent from short database reads."""
from __future__ import annotations

import asyncio
import threading
from PySide6.QtCore import QObject, QThread, Signal, Slot

from .actions import execute


class OperationThread(QThread):
    event = Signal(object)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, paths, kind, options):
        super().__init__()
        self.paths, self.kind, self.options = paths, kind, options
        self.cancelled = threading.Event()
        self.loop = self.task = None

    def cancel(self):
        if self.cancelled.is_set():
            return
        self.cancelled.set()
        if self.loop and self.task:
            try:
                self.loop.call_soon_threadsafe(self.task.cancel)
            except RuntimeError:
                pass

    async def _run(self):
        self.loop = asyncio.get_running_loop()
        self.task = asyncio.current_task()
        if self.cancelled.is_set():
            raise asyncio.CancelledError
        return await execute(self.paths, self.kind, self.event.emit, self.options)

    def run(self):
        try:
            result = asyncio.run(self._run())
            self.succeeded.emit({"kind": self.kind, **result})
        except asyncio.CancelledError:
            self.succeeded.emit({"kind": self.kind, "cancelled": True, "message": "操作已取消"})
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}：{exc}")
        finally:
            self.loop = self.task = None


class Operations(QObject):
    event = Signal(object)
    succeeded = Signal(object)
    failed = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.thread = None

    @property
    def busy(self):
        return self.thread is not None

    def start(self, kind, options=None):
        if self.busy:
            return False
        thread = OperationThread(self.paths, kind, options or {})
        self.thread = thread
        thread.event.connect(self.event)
        thread.succeeded.connect(self.succeeded)
        thread.failed.connect(self.failed)
        thread.finished.connect(self._finished)
        self.busy_changed.emit(True)
        thread.start()
        return True

    def cancel(self):
        if self.thread:
            self.thread.cancel()

    @Slot()
    def _finished(self):
        thread = self.thread
        self.thread = None
        thread.deleteLater()
        self.busy_changed.emit(False)
