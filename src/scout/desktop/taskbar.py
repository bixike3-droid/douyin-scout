"""任务栏进度：长任务进行中在任务栏按钮上显示系统进度动画。

只用「不确定进度」（TBPF_INDETERMINATE，系统自带滚动动画）——
与项目原则一致：不伪造具体百分比。非 Windows / 离屏环境整体空转。
"""
from __future__ import annotations

import ctypes
import sys

TBPF_NOPROGRESS = 0
TBPF_INDETERMINATE = 0x1
TBPF_NORMAL = 0x2
TBPF_ERROR = 0x4
TBPF_PAUSED = 0x8

_STATES = {
    "idle": TBPF_NOPROGRESS,
    "busy": TBPF_INDETERMINATE,
    "paused": TBPF_PAUSED,
    "error": TBPF_ERROR,
}


def state_code(state: str) -> int:
    """任务状态 → TBPFLAG（未知状态按 idle 处理）。"""
    return _STATES.get(state, TBPF_NOPROGRESS)


def _com_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        from .winapi import available
        return available()
    except Exception:
        return False


class TaskbarProgress:
    """包一层 ITaskbarList3；环境不支持时所有调用为空操作。"""

    def __init__(self, window):
        self.window = window
        self._com = None
        self._last = None
        if not _com_available():
            return
        try:
            self._com = self._create_interface()
        except Exception:
            self._com = None

    @staticmethod
    def _create_interface():
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        def guid(d1, d2, d3, d4):
            return GUID(d1, d2, d3, (ctypes.c_ubyte * 8)(*d4))

        clsid = guid(0x56FDF344, 0xFD6D, 0x11D0,
                     (0x95, 0x8A, 0x00, 0x60, 0x97, 0xC9, 0xA0, 0x90))
        iid = guid(0xEA1AFB91, 0x9E28, 0x4B86,
                   (0x90, 0xE9, 0x9E, 0x9F, 0x8A, 0x5E, 0xEA, 0x84))
        ole32 = ctypes.windll.ole32
        ole32.CoInitializeEx(None, 0x2)  # APARTMENTTHREADED；RPC_E_CHANGED_MODE 无妨
        instance = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(clsid), None, 0x17,
                                    ctypes.byref(iid), ctypes.byref(instance))
        if hr != 0 or not instance:
            raise OSError(f"CoCreateInstance failed: 0x{hr & 0xFFFFFFFF:08X}")
        vtable = ctypes.cast(instance, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        hr_init = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtable[3])
        if hr_init(instance) != 0:
            raise OSError("ITaskbarList::HrInit failed")
        # ITaskbarList3：SetProgressValue=9、SetProgressState=10（含 IUnknown 槽位）
        set_state = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                       ctypes.c_void_p, ctypes.c_int)(vtable[10])
        return set_state, instance

    def set_state(self, state: str) -> None:
        code = state_code(state)
        if self._com is None or code == self._last:
            return
        try:
            set_state, instance = self._com
            hwnd = int(self.window.winId()) if self.window is not None else 0
            if not hwnd:
                return
            set_state(instance, ctypes.c_void_p(hwnd), code)
            self._last = code
        except Exception:
            self._com = None
