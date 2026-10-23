"""Private loopback carrier shared by the native desktop shells."""
import socket
import threading
import time


class Server:
    def __init__(self, app, port=0):
        import uvicorn
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", port))
        self.port = self.socket.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=self.port, access_log=False,
            log_config=None, log_level="warning", ws="websockets-sansio",
            timeout_graceful_shutdown=5,
        ))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True)

    def start(self):
        self.thread.start()
        deadline = time.monotonic() + 15
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("本地服务启动失败，请查看 html-desktop.log")
            time.sleep(.02)

    def close(self):
        self.server.should_exit = True
        self.thread.join(timeout=10)
        self.socket.close()
