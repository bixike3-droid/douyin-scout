"""Thread-safe, per-operation steering channel from Qt to the active event loop."""
import asyncio
import threading


class RunControl:
    def __init__(self):
        self.lock = threading.Lock()
        self.loop = self.handler = None
        self.pending = set()

    def activate(self, handler):
        with self.lock:
            self.loop, self.handler = asyncio.get_running_loop(), handler

    def submit(self, text):
        with self.lock:
            loop, handler = self.loop, self.handler
            if loop is None or handler is None or loop.is_closed():
                return False
            future = asyncio.run_coroutine_threadsafe(handler(text), loop)
            self.pending.add(future)
        future.add_done_callback(self._done)
        return True

    def _done(self, future):
        with self.lock:
            self.pending.discard(future)
        # Retrieve exceptions; the host handler publishes a user-visible outcome.
        if not future.cancelled():
            future.exception()

    async def close(self):
        with self.lock:
            self.loop = self.handler = None
            pending = list(self.pending)
        for future in pending:
            future.cancel()
        if pending:
            await asyncio.gather(*(asyncio.wrap_future(f) for f in pending), return_exceptions=True)
