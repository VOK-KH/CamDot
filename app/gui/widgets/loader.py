"""Centered overlay while Extract / Link Grabber syncs links into Grabber."""
import os

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core import icons, theme

BOTTY_LOAD = "load.webm"
BOTTY_DONE = "done.webm"
BOTTY_SIZE = 64


def botty_clip_path(name):
    return os.path.join(icons.images_dir(), "botty", name)


def botty_load_path():
    return botty_clip_path(BOTTY_LOAD)


class BottyClip(QWidget):
    """Looping botty WebM mascot, with a PNG fallback if the clip cannot play."""

    def __init__(self, parent=None, *, clip=BOTTY_LOAD, fallback="robot_info"):
        super().__init__(parent)
        self.setObjectName("extractLoaderMascot")
        self.setFixedSize(BOTTY_SIZE, BOTTY_SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._clip = clip
        self._fallback_name = fallback
        self._frame = QPixmap()
        self._fallback = QPixmap()
        self._player = None
        self._sink = None
        self._audio = None
        self._load_fallback()

    def _load_fallback(self):
        pixmap = icons.art("botty", self._fallback_name, BOTTY_SIZE)
        if pixmap.isNull():
            pixmap = icons.png("wait", 32)
        self._fallback = pixmap

    def _build_player(self):
        path = botty_clip_path(self._clip)
        if not os.path.isfile(path):
            return
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
        except ImportError:
            return
        player = QMediaPlayer(self)
        audio = QAudioOutput(self)
        audio.setMuted(True)
        player.setAudioOutput(audio)
        sink = QVideoSink(self)
        player.setVideoSink(sink)
        sink.videoFrameChanged.connect(self._on_frame)
        player.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
        player.setLoops(QMediaPlayer.Loops.Infinite)
        self._player = player
        self._audio = audio
        self._sink = sink

    def _on_frame(self, frame):
        if not frame.isValid():
            return
        image = frame.toImage()
        if image.isNull():
            return
        self._frame = QPixmap.fromImage(
            image.scaled(
                BOTTY_SIZE, BOTTY_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pixmap = self._frame if not self._frame.isNull() else self._fallback
        if pixmap.isNull():
            return
        x = (self.width() - pixmap.width()) // 2
        y = (self.height() - pixmap.height()) // 2
        painter.drawPixmap(x, y, pixmap)

    def start(self):
        if self._player is None:
            self._build_player()
        if self._player is not None:
            self._player.play()

    def stop(self):
        if self._player is not None:
            self._player.stop()
        self._frame = QPixmap()
        self.update()

    def is_playing(self):
        if self._player is None:
            return False
        from PySide6.QtMultimedia import QMediaPlayer
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState


class LoopLoader(QWidget):
    """Indeterminate bar: a rounded chunk slides through the track on a loop."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("loopLoader")
        self.setFixedHeight(6)
        self._shift = 0.0
        self._anim = QPropertyAnimation(self, b"shift", self)
        self._anim.setDuration(1400)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)

    def get_shift(self):
        return self._shift

    def set_shift(self, value):
        self._shift = float(value)
        self.update()

    shift = Property(float, get_shift, set_shift)

    def is_looping(self):
        return self._anim.state() == QPropertyAnimation.State.Running

    def start(self):
        if not self.is_looping():
            self._anim.start()

    def stop(self):
        self._anim.stop()
        self._shift = 0.0
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if track.width() <= 1 or track.height() <= 1:
            return
        radius = track.height() / 2
        accent = QColor(theme.primary_color())
        well = QColor(accent)
        well.setAlpha(48)
        path = QPainterPath()
        path.addRoundedRect(track, radius, radius)
        painter.fillPath(path, well)
        painter.setClipPath(path)
        chunk_w = max(28.0, track.width() * 0.34)
        span = track.width() + chunk_w
        x = track.x() - chunk_w + span * self._shift
        chunk = QRectF(x, track.y(), chunk_w, track.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(chunk, radius, radius)


class ExtractLoader(QFrame):
    """Dim the Grabber table and show a botty wait card while links stream in."""

    aborted = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("extractLoader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.addStretch(1)

        row = QHBoxLayout()
        row.addStretch(1)
        card = QFrame()
        card.setObjectName("extractLoaderCard")
        card.setMinimumWidth(280)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(18, 16, 18, 14)
        inner.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(12)
        self.mascot = BottyClip()
        self.title = QLabel("Extracting links")
        self.title.setObjectName("extractLoaderTitle")
        self.title.setWordWrap(True)
        self.detail = QLabel("Looking for links…")
        self.detail.setObjectName("extractLoaderDetail")
        self.detail.setWordWrap(True)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self.title)
        text.addWidget(self.detail)
        head.addWidget(self.mascot, 0, Qt.AlignmentFlag.AlignTop)
        head.addLayout(text, 1)
        inner.addLayout(head)

        self.count = QLabel("0 listed")
        self.count.setObjectName("extractLoaderCount")
        inner.addWidget(self.count)

        self.bar = LoopLoader()
        inner.addWidget(self.bar)

        self.abort_btn = QPushButton("Cancel")
        self.abort_btn.setObjectName("extractLoaderAbort")
        self.abort_btn.setProperty("iconName", "cancel")
        self.abort_btn.setIcon(icons.icon("cancel", "#1c1e21", 14))
        self.abort_btn.clicked.connect(self.aborted.emit)
        inner.addWidget(self.abort_btn, alignment=Qt.AlignmentFlag.AlignRight)

        row.addWidget(card)
        row.addStretch(1)
        column.addLayout(row)
        column.addStretch(1)
        self.hide()

    def show_busy(self, title, detail="", count=""):
        self.title.setText(title)
        self.detail.setText(detail or "Looking for links…")
        self.detail.setToolTip(detail)
        if count:
            self.count.setText(count)
        self.abort_btn.setEnabled(True)
        if self.isHidden():
            self.show()
        self.raise_()
        self.bar.start()
        self.mascot.start()

    def hideEvent(self, event):
        self.bar.stop()
        self.mascot.stop()
        super().hideEvent(event)

    def set_count(self, listed):
        self.count.setText(f"{listed} listed")
