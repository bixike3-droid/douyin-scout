"""Windows 原生窗口效果：DWM 材质 / 边框色 / 合成器同步 / 系统动画偏好。

所有函数在非 Windows 或离屏平台下安全空转（返回 False / 默认值），
调用方无需再写平台判断。
"""
from __future__ import annotations

import ctypes
import sys

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMWA_MICA_EFFECT = 1029          # Win11 21H2 的过渡期属性
DWMSBT_MAINWINDOW_MICA = 2
SPI_GETANIMATION = 0x0048


def available() -> bool:
    """真实 Windows 窗口环境（离屏测试平台返回 False）。"""
    if sys.platform != "win32":
        return False
    try:
        from PySide6.QtWidgets import QApplication
        application = QApplication.instance()
        return application is not None and application.platformName() == "windows"
    except Exception:
        return False


def windows_build() -> int:
    if sys.platform != "win32":
        return 0
    try:
        return sys.getwindowsversion().build
    except Exception:
        return 0


def backdrop_supported(build: int | None = None) -> bool:
    """Mica 背景板需 Win11 22H2（22621+）才可靠。"""
    return (windows_build() if build is None else build) >= 22621


def border_colorref(hex_color: str) -> int:
    """#RRGGBB → Windows COLORREF（0x00BBGGRR）。"""
    value = hex_color.lstrip("#")
    r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return (b << 16) | (g << 8) | r


def apply_backdrop(hwnd: int) -> bool:
    """把 DWM 背景板（Mica）铺满整个窗口；失败返回 False（界面保持纯色）。"""
    if not available() or not backdrop_supported():
        return False
    try:
        class MARGINS(ctypes.Structure):
            _fields_ = [("left", ctypes.c_int), ("right", ctypes.c_int),
                        ("top", ctypes.c_int), ("bottom", ctypes.c_int)]

        margins = MARGINS(-1, -1, -1, -1)
        if ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins)) != 0:
            return False
        value = ctypes.c_int(DWMSBT_MAINWINDOW_MICA)
        if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_SYSTEMBACKDROP_TYPE, ctypes.byref(value), ctypes.sizeof(value)) == 0:
            return True
        legacy = ctypes.c_int(1)
        return ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_MICA_EFFECT, ctypes.byref(legacy), ctypes.sizeof(legacy)) == 0
    except Exception:
        return False


def set_border_color(hwnd: int, hex_color: str) -> bool:
    if sys.platform != "win32":
        return False
    try:
        value = ctypes.c_uint(border_colorref(hex_color))
        return ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_BORDER_COLOR, ctypes.byref(value), ctypes.sizeof(value)) == 0
    except Exception:
        return False


def set_dark_titlebar(hwnd: int, dark: bool) -> None:
    if sys.platform != "win32":
        return
    try:
        value = ctypes.c_int(1 if dark else 0)
        if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value)) != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 19, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


def dwm_flush() -> None:
    """等待合成器画完当前帧（截图/预览前调用，避免抓到半帧）。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.dwmapi.DwmFlush()
    except Exception:
        pass


def system_animations_enabled() -> bool:
    """SPI_GETANIMATION：系统是否启用最小化 / 最大化窗口动画（默认启用）。

    只在真实 Windows 窗口环境下读取；离屏 / 其它平台一律返回 True。
    """
    if not available():
        return True
    try:
        class ANIMATIONINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("iMinAnimate", ctypes.c_int)]

        info = ANIMATIONINFO(ctypes.sizeof(ANIMATIONINFO), 0)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETANIMATION, info.cbSize, ctypes.byref(info), 0)
        return bool(info.iMinAnimate) if ok else True
    except Exception:
        return True
