"""Compact media tiles and file chips shared by the composer and transcript."""
import hashlib
from pathlib import Path
import re
import tempfile

from PySide6.QtCore import Qt, QUrl, Signal, QSize, QRectF, QPointF, QObject, QRunnable, QThreadPool
from PySide6.QtGui import QDesktopServices, QImageReader, QPixmap, QPainter, QColor, QPen, QPainterPath, QPolygonF, QFont
from PySide6.QtWidgets import QWidget, QPushButton, QScrollArea, QFrame, QHBoxLayout, QLayout

from ..attachments import validate_files, managed_path, IMAGES, VIDEOS, _run_ffmpeg
from ..attachment_archives import ARCHIVES
from .appearance import color


def file_size(size):
    return f"{size / 1024 / 1024:.1f} MB" if size >= 1024 * 1024 else f"{max(1, size // 1024)} KB"


def thumbnail(path, size=QSize(360, 240)):
    reader = QImageReader(str(path))
    original = reader.size()
    reader.setAutoTransform(True)
    if original.isValid():
        reader.setScaledSize(original.scaled(size, Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    if image.isNull() and Path(path).suffix.lower() in (".heic", ".heif", ".avif"):
        from PIL import Image, ImageOps
        from pillow_heif import register_heif_opener
        from PySide6.QtGui import QImage
        register_heif_opener()
        try:
            with Image.open(path) as source:
                source = ImageOps.exif_transpose(source).convert("RGB")
                source.thumbnail((size.width(), size.height()))
                image = QImage(source.tobytes(), source.width, source.height, source.width * 3, QImage.Format.Format_RGB888).copy()
        except Exception:
            return QPixmap()
    pixmap = QPixmap.fromImage(image)
    if pixmap.width() > size.width() or pixmap.height() > size.height():
        pixmap = pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return pixmap


class _PreviewSignals(QObject):
    ready = Signal(str, str)
    text_ready = Signal(str)


class _FilePreview(QRunnable):
    def __init__(self, path, name):
        super().__init__()
        self.path, self.name = path, name
        self.signals = _PreviewSignals()

    def run(self):
        try:
            if Path(self.name).suffix.lower() in ARCHIVES:
                from ..attachment_archives import Archive, listing
                with Archive(self.path, self.name) as archive:
                    text = listing(archive.entries)
            else:
                from ..attachment_documents import decode_text
                with self.path.open("rb") as source:
                    text = decode_text(source.read(12000))
        except Exception as exc:
            text = "文件已保留。\n" + str(exc)
        try:
            self.signals.text_ready.emit(text)
        except RuntimeError:
            pass


class _VideoPreview(QRunnable):
    def __init__(self, path):
        super().__init__()
        self.path = path
        self.signals = _PreviewSignals()

    def run(self):
        output, duration = "", ""
        try:
            stat = self.path.stat()
            key = hashlib.sha256(f"{self.path}:{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()
            cache = Path(tempfile.gettempdir()) / "scout-attachment-previews"
            cache.mkdir(exist_ok=True)
            poster = cache / (key + ".jpg")
            info = _run_ffmpeg(["-i", str(self.path), "-t", "0", "-f", "null", "-"], timeout=10)
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)", info.stderr.decode("utf-8", "replace"))
            if match:
                seconds = int(match[1]) * 3600 + int(match[2]) * 60 + int(match[3])
                duration = f"{seconds // 60}:{seconds % 60:02d}"
            if not poster.is_file():
                _run_ffmpeg(["-i", str(self.path), "-frames:v", "1", "-vf", "scale=360:240:force_original_aspect_ratio=decrease", "-y", str(poster)], timeout=15)
            if poster.is_file():
                output = str(poster)
        except Exception:
            pass
        try:
            self.signals.ready.emit(output, duration)
        except RuntimeError:
            pass  # The application may close while a local preview is decoding.


class AttachmentTile(QPushButton):
    removed = Signal(str)
    analysis_requested = Signal(str)

    def __init__(self, item, paths=None, *, compact=True, removable=False, parent=None):
        super().__init__(parent)
        self.item, self.compact = item, compact
        self.account_paths = paths
        self.setObjectName("attachmentTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        from ..tools.workspace import artifact_path
        resolve = artifact_path if item.get("generated") else managed_path
        try:
            self.path = resolve(paths, item["relative_path"]) if item.get("relative_path") and paths else Path(item["source_path"])
        except (KeyError, ValueError):
            self.path = None
        ext = Path(item["name"]).suffix.lower()
        self.kind = "image" if ext in IMAGES else "video" if ext in VIDEOS else "document"
        self.preview = QPixmap()
        self.duration = ""
        self.setFixedSize(QSize(82, 82) if compact and self.kind == "image" else
                          QSize(128, 82) if compact and self.kind == "video" else
                          QSize(180, 132) if self.kind == "image" else
                          QSize(216, 132) if self.kind == "video" else QSize(224, 72))
        states = {"ready": "已读取", "processing": "识别中", "partial": "部分读取", "failed": "读取失败", "pending": "待发送"}
        self.setToolTip("\n".join(p for p in (item["name"], file_size(item.get("size", 0)), states.get(item.get("status"), ""), item.get("limitations")) if p))
        self.setAccessibleName(item["name"])
        self.clicked.connect(self.open_file)
        self.remove_button = QPushButton("×", self)
        self.remove_button.setObjectName("attachmentRemove")
        self.remove_button.setFixedSize(20, 20)
        self.remove_button.move(self.width() - 24, 4)
        self.remove_button.setToolTip("移除 " + item["name"])
        self.remove_button.setAccessibleName("移除 " + item["name"])
        self.remove_button.clicked.connect(lambda: self.removed.emit(str(self.path)))
        self.remove_button.hide()
        self.removable = removable
        if self.path and self.kind == "image":
            preview_path = item.get("thumbnail_relative_path")
            self.preview = thumbnail(resolve(paths, preview_path) if preview_path and paths else self.path)
        elif self.path and self.kind == "video":
            preview_path = item.get("preview_relative_path")
            if preview_path and paths:
                self.preview = thumbnail(resolve(paths, preview_path))
            job = _VideoPreview(self.path)
            self._preview_job = job
            job.signals.ready.connect(self._preview_ready)
            QThreadPool.globalInstance().start(job)

    def _preview_ready(self, path, duration):
        if path:
            self.preview = thumbnail(Path(path))
        self.duration = duration
        self.update()

    def open_file(self):
        if not self.path or not self.path.is_file():
            return
        if self.item.get("id") and self.item.get("workspace", {}).get("total") and self.item.get("kind") == "archive":
            dialog = WorkspaceDialog(self.item, self.account_paths, self.window())
            dialog.analysis_requested.connect(self.analysis_requested)
            self.preview_dialog = dialog
            dialog.show()
            return
        if self.kind == "image":
            from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel
            dialog = QDialog(self.window())
            dialog.setWindowTitle(self.item["name"])
            dialog.resize(880, 650)
            layout = QVBoxLayout(dialog)
            image = QLabel()
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image.setPixmap(thumbnail(self.path, QSize(840, 590)))
            layout.addWidget(image)
            self.preview_dialog = dialog
            dialog.show()
        elif self.kind == "video":
            try:
                from .video import VideoCard
            except ImportError:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path)))
                return
            from PySide6.QtWidgets import QDialog, QVBoxLayout
            dialog = QDialog(self.window())
            dialog.setWindowTitle(self.item["name"])
            dialog.resize(680, 470)
            layout = QVBoxLayout(dialog)
            player = VideoCard(self.item["name"])
            player.setMaximumWidth(16777215)
            player.video.setMinimumSize(480, 270)
            player.player.errorOccurred.connect(lambda *_: player.set_status("无法播放该视频，请检查格式或文件完整性"))
            layout.addWidget(player)
            dialog.finished.connect(player.stop)
            self.preview_dialog = dialog
            dialog.show()
            player.play_file(self.path)
        elif self.path.suffix.lower() in {".pdf", ".docx", ".xlsx", ".pptx", ".xls", ".rtf", ".odt", ".ods", ".odp", ".epub"}:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path)))
        else:
            from PySide6.QtWidgets import QDialog, QVBoxLayout, QPlainTextEdit
            dialog = QDialog(self.window())
            dialog.setWindowTitle(self.item["name"])
            dialog.resize(720, 500)
            layout = QVBoxLayout(dialog)
            browser = QPlainTextEdit()
            browser.setReadOnly(True)
            browser.setPlainText(self.item.get("preview_text") or "正在读取文件信息…")
            layout.addWidget(browser)
            self.preview_dialog = dialog
            dialog.show()
            if not self.item.get("preview_text"):
                job = _FilePreview(self.path, self.item["name"])
                self._file_preview_job = job
                job.signals.text_ready.connect(browser.setPlainText)
                QThreadPool.globalInstance().start(job)

    def enterEvent(self, event):
        if self.removable:
            self.remove_button.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.remove_button.hide()
        super().leaveEvent(event)

    def focusInEvent(self, event):
        if self.removable:
            self.remove_button.show()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        if not self.underMouse():
            self.remove_button.hide()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        if self.removable and event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.removed.emit(str(self.path))
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 11, 11)
        painter.setClipPath(clip)
        painter.fillRect(rect, QColor(color("hover" if self.underMouse() else "subtle")))
        if self.kind in ("image", "video"):
            if not self.preview.isNull():
                scaled = self.preview.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                painter.drawPixmap((self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2, scaled)
            else:
                painter.setPen(QColor(color("faint")))
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "VIDEO" if self.kind == "video" else "IMAGE")
            if self.kind == "video":
                center = QPointF(self.width() / 2, self.height() / 2)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(0, 0, 0, 115))
                painter.drawEllipse(center, 15, 15)
                painter.setBrush(QColor("white"))
                painter.drawPolygon(QPolygonF([center + QPointF(-3, -6), center + QPointF(-3, 6), center + QPointF(6, 0)]))
                if self.duration:
                    painter.setBrush(QColor(0, 0, 0, 155))
                    painter.drawRoundedRect(QRectF(6, self.height() - 23, 40, 17), 4, 4)
                    painter.setPen(QColor("white"))
                    painter.setFont(QFont(self.font().family(), 8))
                    painter.drawText(QRectF(6, self.height() - 23, 40, 17), Qt.AlignmentFlag.AlignCenter, self.duration)
        else:
            ext = Path(self.item["name"]).suffix.lstrip(".").upper() or "FILE"
            shade = QColor({"PDF": "#D95252", "DOCX": "#4B7AC0", "XLSX": "#3A936F", "PPTX": "#C87544", "ZIP": "#B38B45", "7Z": "#B38B45", "RAR": "#B38B45"}.get(ext, "#79818D"))
            painter.setPen(Qt.PenStyle.NoPen)
            tint = QColor(shade)
            tint.setAlpha(25)
            painter.setBrush(tint)
            painter.drawRoundedRect(QRectF(10, 14, 36, 44), 7, 7)
            painter.setPen(QPen(shade, 1.6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(20, 23, 16, 23), 2, 2)
            painter.drawLine(QPointF(24, 31), QPointF(32, 31))
            painter.drawLine(QPointF(24, 36), QPointF(32, 36))
            font = QFont(self.font())
            font.setPixelSize(12)
            font.setWeight(QFont.Weight.Medium)
            painter.setFont(font)
            painter.setPen(QColor(color("text")))
            filename = painter.fontMetrics().elidedText(self.item["name"], Qt.TextElideMode.ElideMiddle, 155)
            painter.drawText(QRectF(57, 16, 155, 20), Qt.AlignmentFlag.AlignVCenter, filename)
            font.setPixelSize(10)
            font.setWeight(QFont.Weight.Normal)
            painter.setFont(font)
            painter.setPen(QColor(color("muted")))
            painter.drawText(QRectF(57, 38, 155, 18), Qt.AlignmentFlag.AlignVCenter, ext + " · " + file_size(self.item.get("size", 0)))
        if self.item.get("status") in ("partial", "failed", "processing"):
            painter.setBrush(QColor(color("danger" if self.item["status"] == "failed" else "warning")))
            painter.setPen(QPen(QColor(color("surface")), 2))
            painter.drawEllipse(QPointF(self.width() - 9, self.height() - 9), 4, 4)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(color("accent")) if self.hasFocus() else QColor(127, 127, 127, 35), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 11, 11)


class AttachmentTray(QScrollArea):
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.paths = []
        self.setObjectName("attachmentTray")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(96)
        self.body = QWidget()
        self.rows = QHBoxLayout(self.body)
        self.rows.setContentsMargins(2, 3, 2, 7)
        self.rows.setSpacing(8)
        self.setWidget(self.body)
        self.hide()

    def add_files(self, values):
        if not self.isEnabled():
            return
        seen = set(self.paths)
        for value in values:
            try:
                path = str(validate_files([value])[0])
                if path not in seen:
                    self.paths.append(path)
                    seen.add(path)
            except (ValueError, OSError) as exc:
                self.error.emit(str(exc))
        self.render()

    def clear(self):
        self.paths = []
        self.render()

    def remove(self, path):
        self.paths = [p for p in self.paths if p != path]
        self.render()

    def wheelEvent(self, event):
        bar = self.horizontalScrollBar()
        if bar.maximum() > 0:
            delta = event.pixelDelta().x() or event.pixelDelta().y() or event.angleDelta().x() or event.angleDelta().y()
            bar.setValue(bar.value() - delta)
            event.accept()
        else:
            event.ignore()

    def render(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        for value in self.paths:
            path = Path(value)
            tile = AttachmentTile({"name": path.name, "source_path": value,
                                   "size": path.stat().st_size if path.is_file() else 0, "status": "pending"}, removable=True)
            tile.removed.connect(self.remove)
            self.rows.addWidget(tile, 0, Qt.AlignmentFlag.AlignVCenter)
        self.rows.addStretch()
        self.setVisible(bool(self.paths))


class AttachmentFlow(QLayout):
    def __init__(self, parent):
        super().__init__(parent)
        self.items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(8)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(QRectF(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(QRectF(rect), False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _layout(self, rect, test):
        from PySide6.QtCore import QRect
        x, y, height = int(rect.x()), int(rect.y()), 0
        for item in self.items:
            size = item.sizeHint()
            if x > rect.x() and x + size.width() > rect.right() + 1:
                x, y, height = int(rect.x()), y + height + self.spacing(), 0
            if not test:
                item.setGeometry(QRect(x, y, size.width(), size.height()))
            x += size.width() + self.spacing()
            height = max(height, size.height())
        return int(y + height - rect.y())


class AttachmentGroup(QWidget):
    analysis_requested = Signal(str)
    def __init__(self, items, paths, parent=None):
        super().__init__(parent)
        layout = AttachmentFlow(self)
        for item in items:
            tile = AttachmentTile(item, paths, compact=False)
            tile.account_paths = paths
            tile.analysis_requested.connect(self.analysis_requested)
            layout.addWidget(tile)


from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit


class WorkspaceDialog(QDialog):
    analysis_requested = Signal(str)

    def __init__(self, item, paths, parent=None):
        super().__init__(parent)
        self.item = item
        self.paths = paths
        self.setWindowTitle("素材工作区 · " + item["name"])
        self.resize(1000, 740)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索文件名、编号或已识别的画面内容")
        self.search.textChanged.connect(self.render_assets)
        layout.addWidget(self.search)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll, 1)
        footer = QHBoxLayout()
        self.continue_button = QPushButton("继续分析未完成素材")
        self.continue_button.clicked.connect(lambda: self.analysis_requested.emit(item["id"]))
        footer.addWidget(self.continue_button)
        footer.addStretch()
        footer.addWidget(QLabel("点击图片查看原图；视频可播放。总览、细看分别记录。"))
        layout.addLayout(footer)
        self.assets = []
        if self.paths:
            from ..db.connect import Database
            from ..store.attachment_workspace import AssetStore
            with Database.open(self.paths.db_path, read_only=True) as db:
                store = AssetStore(db)
                self.assets = store.assets(item["id"])
                progress = store.progress(item["id"])
            self.summary.setText(f"共 {progress['total']} 项 · 图片 {progress['images']} · 视频 {progress['videos']}\n缩略图 {progress['thumbnails']}/{progress['visual_total']} · 总览 {progress['overviewed']}/{progress['visual_total']} · 细看 {progress['inspected']} · 失败 {progress['failed']}")
            self.continue_button.setEnabled(progress["overviewed"] < progress["visual_total"] or bool(progress["failed"]))
        self.render_assets()

    def render_assets(self):
        body = QWidget()
        flow = AttachmentFlow(body)
        query = self.search.text().casefold()
        for asset in self.assets:
            if asset["state"] == "directory":
                continue
            if query and query not in (asset["name"] + asset["asset_id"] + asset["observation"]).casefold():
                continue
            box = QWidget()
            column = QVBoxLayout(box)
            column.setContentsMargins(0, 0, 0, 8)
            metadata = {"name": asset["name"], "relative_path": asset["source_path"], "size": asset["size"] or 0,
                        "preview_relative_path": asset["thumbnail_path"], "thumbnail_relative_path": asset["thumbnail_path"],
                        "status": "ready" if asset["observation"] else "failed" if asset["error"] else "processing",
                        "limitations": asset["error"] or asset["observation"], "preview_text": asset["metadata"].get("text", "")[:12000]}
            tile = AttachmentTile(metadata, self.paths, compact=False)
            column.addWidget(tile)
            caption = QLabel(asset["asset_id"] + " · " + Path(asset["name"]).name)
            caption.setTextFormat(Qt.TextFormat.PlainText)
            caption.setFixedWidth(tile.width())
            caption.setWordWrap(True)
            column.addWidget(caption)
            flow.addWidget(box)
        previous = self.scroll.takeWidget()
        if previous:
            previous.deleteLater()
        self.scroll.setWidget(body)
