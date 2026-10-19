"""对话内联视频卡：封面/播放/进度/音量，播放的是本地缓存文件。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout


def _clock(ms: int) -> str:
    seconds = max(0, int(ms // 1000))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class ImageCard(QFrame):
    """图文作品的卡：图片翻页 + 音乐说明，没有视频轨就不放播放器。"""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("videoCard")
        self.setMaximumWidth(380)
        self._paths: list[Path] = []
        self._index = 0
        self._pixmaps = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)

        heading = QLabel(title or "抖音图文")
        heading.setObjectName("videoTitle")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        self.image = QLabel("加载中…")
        self.image.setObjectName("videoStatus")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(300, 360)
        self.image.setMaximumHeight(420)
        layout.addWidget(self.image)

        self.status = QLabel("")
        self.status.setObjectName("videoStatus")
        layout.addWidget(self.status)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.prev_button = QPushButton("上一张")
        self.prev_button.setObjectName("videoControl")
        self.next_button = QPushButton("下一张")
        self.next_button.setObjectName("videoControl")
        self.counter = QLabel("0 / 0")
        self.counter.setObjectName("videoStatus")
        controls.addWidget(self.prev_button)
        controls.addWidget(self.next_button)
        controls.addStretch()
        controls.addWidget(self.counter)
        layout.addLayout(controls)

        self.prev_button.clicked.connect(lambda: self._step(-1))
        self.next_button.clicked.connect(lambda: self._step(1))

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def set_text_only(self, message: str) -> None:
        """纯文本作品：不显示图片区与翻页控件，只留一句说明。"""
        self.image.hide()
        self.prev_button.hide()
        self.next_button.hide()
        self.counter.hide()
        self.status.setText(message)
        self.setMaximumWidth(360)

    def set_images(self, paths) -> None:
        from PySide6.QtGui import QPixmap
        self._pixmaps = []
        self._paths = []
        for path in paths:
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self._paths.append(Path(path))
                self._pixmaps.append(pixmap)
        if not self._pixmaps:
            self.image.setText("图片下载失败")
            self.status.setText("可以重新采集这条作品再试")
            self.counter.setText("0 / 0")
            return
        self._index = 0
        self.status.setText(f"共 {len(self._pixmaps)} 张（图文作品没有视频轨）")
        self._render()

    def _step(self, delta: int) -> None:
        if not self._pixmaps:
            return
        self._index = (self._index + delta) % len(self._pixmaps)
        self._render()

    def _render(self) -> None:
        from PySide6.QtCore import Qt as _Qt
        pixmap = self._pixmaps[self._index]
        available = 320
        scaled = pixmap.scaled(available, 420, _Qt.AspectRatioMode.KeepAspectRatio,
                               _Qt.TransformationMode.SmoothTransformation)
        self.image.setText("")
        self.image.setPixmap(scaled)
        self.counter.setText(f"{self._index + 1} / {len(self._pixmaps)}")


class VideoCard(QFrame):
    """一条作品的内联播放卡。

    先显示封面/状态，等外部把 mp4 下载好再 ``play_file()``；
    竖屏视频按 9:16 限高，不撑破气泡。
    """

    closed = Signal()

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("videoCard")
        self._duration = 0
        self.setMaximumWidth(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)

        heading = QLabel(title or "抖音视频")
        heading.setObjectName("videoTitle")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        self.video = QVideoWidget()
        self.video.setMinimumSize(300, 400)
        self.video.setMaximumHeight(420)
        self.video.setStyleSheet("background:#111318; border-radius:10px;")
        layout.addWidget(self.video)

        self.status = QLabel("准备中…")
        self.status.setObjectName("videoStatus")
        layout.addWidget(self.status)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.play_button = QPushButton("暂停")
        self.play_button.setObjectName("videoControl")
        self.play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        controls.addWidget(self.play_button)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        controls.addWidget(self.slider, 1)

        self.clock = QLabel("00:00 / 00:00")
        self.clock.setObjectName("videoStatus")
        controls.addWidget(self.clock)

        self.mute_button = QPushButton("静音")
        self.mute_button.setObjectName("videoControl")
        self.mute_button.setCursor(Qt.CursorShape.PointingHandCursor)
        controls.addWidget(self.mute_button)
        layout.addLayout(controls)

        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.85)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.errorOccurred.connect(lambda *_: self.status.setText("播放失败：文件可能已损坏，重新播放会重新下载"))

        self.play_button.clicked.connect(self._toggle)
        self.mute_button.clicked.connect(self._toggle_mute)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self._playing = False

    # ── 外部接口 ────────────────────────────────────────────
    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def play_file(self, path: Path) -> None:
        target = str(Path(path))
        if self.player.source().toLocalFile() != target:
            self.player.setSource(QUrl.fromLocalFile(target))
        self.status.setText(Path(path).name)
        self.player.play()
        self._playing = True
        self.play_button.setText("暂停")

    def stop(self) -> None:
        self.player.stop()
        self._playing = False
        self.play_button.setText("播放")

    # ── 播放器回调 ──────────────────────────────────────────
    def _toggle(self):
        if not self.player.source().isValid():
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.play_button.setText("播放")
        else:
            self.player.play()
            self.play_button.setText("暂停")

    def _toggle_mute(self):
        muted = not self.audio.isMuted()
        self.audio.setMuted(muted)
        self.mute_button.setText("取消静音" if muted else "静音")

    def _on_position(self, position):
        if not self.slider.isSliderDown():
            self.slider.setValue(int(position))
        self.clock.setText(f"{_clock(position)} / {_clock(self._duration)}")

    def _on_duration(self, duration):
        self._duration = int(duration or 0)
        self.slider.setRange(0, self._duration)

    def _on_state(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_button.setText("暂停")
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self.play_button.setText("播放")
