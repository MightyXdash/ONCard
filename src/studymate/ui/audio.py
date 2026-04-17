from __future__ import annotations

import ctypes
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QUrl

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QSoundEffect
except ImportError:  # pragma: no cover
    QAudioOutput = None  # type: ignore[assignment]
    QMediaPlayer = None  # type: ignore[assignment]
    QSoundEffect = None  # type: ignore[assignment]

from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSpinBox,
    QComboBox,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QTabBar,
    QTextEdit,
    QWidget,
)


class UiSoundBank:
    def __init__(self, sfx_root: Path) -> None:
        self._sfx_root = sfx_root
        self._pools: dict[str, list[QSoundEffect]] = {}
        self._media_pools: dict[str, list[tuple[QMediaPlayer, QAudioOutput]]] = {}
        self._indices: dict[str, int] = {}
        self._volumes: dict[str, float] = {}
        self._audio_enabled = True
        self._click_enabled = True
        self._click_sound = "click3"
        self._transition_enabled = True
        self._transition_sound = "woosh"
        self._notification_sound = "windows"
        if QSoundEffect is not None:
            self._create_pool("woosh", sfx_root / "woosh.wav", pool_size=3, volume=0.68)
            for name in ("click", "click3", "click4", "click5"):
                self._create_pool(name, sfx_root / f"{name}.wav", pool_size=4, volume=0.82)
        if QMediaPlayer is not None and QAudioOutput is not None:
            self._create_media_pool("notify1", sfx_root / "notify1.mp3", pool_size=2, volume=0.88)
            self._create_media_pool("notify2", sfx_root / "notify2.mp3", pool_size=2, volume=0.88)

    def configure(self, setup: dict) -> None:
        audio = dict((setup or {}).get("audio", {}))
        self._audio_enabled = bool(audio.get("enabled", True))
        self._click_enabled = bool(audio.get("click_enabled", True))
        self._click_sound = self._valid_sound(str(audio.get("click_sound", "click3")), fallback="click3")
        self._transition_enabled = bool(audio.get("transition_enabled", True))
        self._transition_sound = self._valid_sound(str(audio.get("transition_sound", "woosh")), fallback="woosh")
        notification = str(audio.get("notification_sound", "windows")).strip().lower()
        self._notification_sound = notification if notification in {"windows", "notify1", "notify2"} else "windows"

    @staticmethod
    def _valid_sound(name: str, *, fallback: str) -> str:
        clean = str(name or "").strip().lower()
        allowed = {"click", "click3", "click4", "click5", "woosh"}
        return clean if clean in allowed else fallback

    def _create_pool(self, name: str, path: Path, *, pool_size: int, volume: float) -> None:
        if not path.exists() or QSoundEffect is None:
            return
        source = QUrl.fromLocalFile(str(path.resolve()))
        pool: list[QSoundEffect] = []
        for _ in range(pool_size):
            effect = QSoundEffect()
            effect.setSource(source)
            effect.setLoopCount(1)
            effect.setVolume(volume)
            effect.setMuted(False)
            pool.append(effect)
        self._pools[name] = pool
        self._indices[name] = 0
        self._volumes[name] = volume

    def _create_media_pool(self, name: str, path: Path, *, pool_size: int, volume: float) -> None:
        if not path.exists() or QMediaPlayer is None or QAudioOutput is None:
            return
        source = QUrl.fromLocalFile(str(path.resolve()))
        pool: list[tuple[QMediaPlayer, QAudioOutput]] = []
        for _ in range(pool_size):
            output = QAudioOutput()
            output.setVolume(volume)
            player = QMediaPlayer()
            player.setAudioOutput(output)
            player.setSource(source)
            pool.append((player, output))
        self._media_pools[name] = pool
        self._indices[name] = 0
        self._volumes[name] = volume

    def play(self, name: str, *, volume_scale: float = 1.0) -> None:
        if not self._audio_enabled:
            return
        if name == "click":
            if not self._click_enabled:
                return
            name = self._click_sound
        elif name == "woosh":
            if not self._transition_enabled:
                return
            name = self._transition_sound
        pool = self._pools.get(name)
        if not pool:
            return
        index = self._indices.get(name, 0) % len(pool)
        effect = pool[index]
        self._indices[name] = index + 1
        base_volume = self._volumes.get(name, 1.0)
        effect.setVolume(self._scaled_volume(base_volume, volume_scale))
        effect.play()

    def play_notification(self, sound: str = "", *, volume_scale: float = 1.0) -> None:
        if not self._audio_enabled:
            return
        name = str(sound or self._notification_sound).strip().lower()
        if name == "windows":
            return
        media_pool = self._media_pools.get(name)
        if media_pool:
            index = self._indices.get(name, 0) % len(media_pool)
            player, output = media_pool[index]
            self._indices[name] = index + 1
            output.setVolume(self._scaled_volume(self._volumes.get(name, 1.0), volume_scale))
            player.stop()
            player.setPosition(0)
            player.play()
            return
        self.play(name, volume_scale=volume_scale)

    def notification_sound(self) -> str:
        return self._notification_sound

    def play_slider_click(self, *, volume_scale: float = 1.0) -> None:
        if not self._audio_enabled or not self._click_enabled:
            return
        pool = self._pools.get("click3")
        if not pool:
            return
        index = self._indices.get("click3", 0) % len(pool)
        effect = pool[index]
        self._indices["click3"] = index + 1
        effect.setVolume(self._scaled_volume(self._volumes.get("click3", 1.0), volume_scale))
        effect.play()

    def _scaled_volume(self, base_volume: float, volume_scale: float) -> float:
        return max(0.0, min(1.0, float(base_volume) * float(volume_scale) * self._system_volume_compensation()))

    @staticmethod
    def _system_volume_compensation() -> float:
        level = _windows_wave_volume_percent()
        if level <= 0:
            return 1.0
        return 5.0 / max(5.0, min(100.0, level))


def _windows_wave_volume_percent() -> float:
    try:
        volume = ctypes.c_uint32()
        result = ctypes.windll.winmm.waveOutGetVolume(0, ctypes.byref(volume))  # type: ignore[attr-defined]
        if result != 0:
            return 0.0
        left = volume.value & 0xFFFF
        right = (volume.value >> 16) & 0xFFFF
        return max(0.0, min(100.0, ((left + right) / 2.0) * 100.0 / 0xFFFF))
    except Exception:
        return 0.0


class ClickSoundFilter(QObject):
    DEFAULT_CLICK_VOLUME_SCALE = 0.88

    def __init__(self, sounds: UiSoundBank, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.sounds = sounds

    def eventFilter(self, watched, event) -> bool:
        if not isinstance(watched, QWidget):
            return False
        if bool(watched.property("skipClickSfx")):
            return False

        if event.type() == QEvent.MouseButtonPress and self._is_click_target(watched):
            self.sounds.play("click", volume_scale=self.DEFAULT_CLICK_VOLUME_SCALE)
        elif (
            event.type() == QEvent.KeyPress
            and event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space)
            and self._is_key_click_target(watched)
        ):
            self.sounds.play("click", volume_scale=self.DEFAULT_CLICK_VOLUME_SCALE)
        return False

    def _is_click_target(self, widget: QWidget) -> bool:
        if isinstance(
            widget,
            (
                QAbstractButton,
                QAbstractSpinBox,
                QComboBox,
                QLineEdit,
                QTextEdit,
                QPlainTextEdit,
                QTabBar,
                QMenu,
            ),
        ):
            return True
        return self._item_view_for(widget) is not None

    @staticmethod
    def _is_key_click_target(widget: QWidget) -> bool:
        return isinstance(widget, (QAbstractButton, QAbstractSpinBox, QComboBox, QTabBar))

    @staticmethod
    def _item_view_for(widget: QWidget) -> QAbstractItemView | None:
        current: QWidget | None = widget
        while current is not None:
            if isinstance(current, QAbstractItemView):
                return current
            current = current.parentWidget()
        return None
