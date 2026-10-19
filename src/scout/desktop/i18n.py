"""Qt 内置文案中文化。

右键菜单（撤销/复制/粘贴/全选）、文件对话框、消息框按钮这些字符串都在 Qt 自己
的翻译文件里，装一个 QTranslator 就能整体变成中文，不用逐处改代码。
"""
from __future__ import annotations

from pathlib import Path

_TRANSLATOR = None
_INSTALLED = False


def translations_dir() -> Path | None:
    """找到 PySide6 自带的翻译目录（打包后走 sys._MEIPASS 下的 PySide6）。"""
    try:
        from PySide6.QtCore import QLibraryInfo
        candidates = [Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))]
    except Exception:      # noqa: BLE001
        candidates = []
    try:
        import PySide6
        candidates.append(Path(PySide6.__file__).resolve().parent / "translations")
    except Exception:      # noqa: BLE001
        pass
    for path in candidates:
        if (path / "qtbase_zh_CN.qm").exists():
            return path
    return None


def install_chinese_ui(app=None) -> bool:
    """把 Qt 自带文案切成简体中文；失败时保持默认（不影响程序运行）。"""
    global _TRANSLATOR, _INSTALLED
    if _INSTALLED:
        return _TRANSLATOR is not None
    _INSTALLED = True
    try:
        from PySide6.QtCore import QTranslator
        from PySide6.QtWidgets import QApplication
        target = app or QApplication.instance()
        if target is None:
            return False
        path = translations_dir()
        if path is None:
            return False
        translator = QTranslator(target)
        if not translator.load("qtbase_zh_CN", str(path)):
            return False
        target.installTranslator(translator)
        _TRANSLATOR = translator      # 保持引用，否则会被回收
        return True
    except Exception:      # noqa: BLE001
        return False
