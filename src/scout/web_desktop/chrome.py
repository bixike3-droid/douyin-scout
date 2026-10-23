"""Native Windows frame behavior around the HTML title bar, scoped to our HWND."""
import ctypes
from ctypes import wintypes


class NativeChrome:
    def __init__(self, window):
        self.window = window
        self.hwnd = int(window.native.Handle.ToInt64())
        self.user = ctypes.windll.user32
        self.controls = ctypes.windll.comctl32
        self.callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
            wintypes.WPARAM, wintypes.LPARAM, ctypes.c_size_t, ctypes.c_size_t)
        self.callback = self.callback_type(self._message)
        self.controls.SetWindowSubclass.argtypes = [wintypes.HWND, self.callback_type, ctypes.c_size_t, ctypes.c_size_t]
        self.controls.SetWindowSubclass.restype = wintypes.BOOL
        self.controls.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.controls.DefSubclassProc.restype = ctypes.c_ssize_t
        self.controls.RemoveWindowSubclass.argtypes = [wintypes.HWND, self.callback_type, ctypes.c_size_t]
        self.user.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        self.user.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        self.user.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        self.user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self.user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user.GetDpiForWindow.argtypes = [wintypes.HWND]
        self.user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        self.user.MonitorFromWindow.restype = wintypes.HMONITOR
        self.user.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
        if not self.controls.SetWindowSubclass(self.hwnd, self.callback, 1, 0):
            raise ctypes.WinError()
        style = self.user.GetWindowLongPtrW(self.hwnd, -16)
        # Restore standard minimize/maximize/Snap and resize semantics while
        # WM_NCCALCSIZE lets the HTML occupy the native title-bar area.
        self.user.SetWindowLongPtrW(self.hwnd, -16, (style | 0x00CF0000) & ~0x80000000)
        self.user.SetWindowPos(self.hwnd, None, 0, 0, 0, 0, 0x0037)
        rounded = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(self.hwnd), 33, ctypes.byref(rounded), 4)

    def _message(self, hwnd, message, wparam, lparam, identifier, data):
        if message == 0x0083 and wparam:  # WM_NCCALCSIZE
            return 0
        if message == 0x0084:  # WM_NCHITTEST
            rectangle = wintypes.RECT()
            self.user.GetWindowRect(hwnd, ctypes.byref(rectangle))
            scale = (self.user.GetDpiForWindow(hwnd) or 96) / 96
            x = (ctypes.c_short(lparam & 0xffff).value - rectangle.left) / scale
            y = (ctypes.c_short((lparam >> 16) & 0xffff).value - rectangle.top) / scale
            width, height = (rectangle.right - rectangle.left) / scale, (rectangle.bottom - rectangle.top) / scale
            if not self.user.IsZoomed(wintypes.HWND(hwnd)):
                left, right, top, bottom = x < 6, x >= width - 6, y < 6, y >= height - 6
                if top and left: return 13
                if top and right: return 14
                if bottom and left: return 16
                if bottom and right: return 17
                if left: return 10
                if right: return 11
                if top: return 12
                if bottom: return 15
            if y < 44 and x < width - 138:
                return 2  # HTCAPTION: move, double-click, and drag-to-Snap
            return 1
        if message == 0x0024:  # WM_GETMINMAXINFO: maximize to the monitor work area
            class MinMax(ctypes.Structure):
                _fields_ = [(name, wintypes.POINT) for name in ("reserved", "max_size", "max_position", "min_track", "max_track")]
            class Monitor(ctypes.Structure):
                _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT), ("work", wintypes.RECT), ("flags", wintypes.DWORD)]
            monitor = Monitor()
            monitor.size = ctypes.sizeof(monitor)
            if self.user.GetMonitorInfoW(self.user.MonitorFromWindow(hwnd, 2), ctypes.byref(monitor)):
                info = MinMax.from_address(lparam)
                info.max_position.x, info.max_position.y = monitor.work.left - monitor.monitor.left, monitor.work.top - monitor.monitor.top
                info.max_size.x, info.max_size.y = monitor.work.right - monitor.work.left, monitor.work.bottom - monitor.work.top
                scale = (self.user.GetDpiForWindow(hwnd) or 96) / 96
                info.min_track.x, info.min_track.y = int(1040 * scale), int(680 * scale)
                return 0
        if message == 0x0082:  # WM_NCDESTROY
            self.controls.RemoveWindowSubclass(hwnd, self.callback, 1)
        return self.controls.DefSubclassProc(hwnd, message, wparam, lparam)
