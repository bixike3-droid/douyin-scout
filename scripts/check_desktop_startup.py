"""启动冒烟：离屏构建主窗口并短暂显示，验证源码模式启动不崩溃。

数据根目录使用系统临时目录，不向仓库写入任何产物。
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from scout.desktop.runtime import prepare_runtime  # noqa: E402
from scout.desktop.service import DesktopService  # noqa: E402
from scout.desktop.window import MainWindow  # noqa: E402

app = QApplication(sys.argv)
paths = prepare_runtime(Path(tempfile.mkdtemp(prefix="desktop-startup-")))
window = MainWindow(DesktopService(paths))
window.show()
QTimer.singleShot(1200, app.quit)
app.exec()
print("startup smoke OK")
