from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QUrl

try:
    from PySide6.QtMultimedia import QSoundEffect
except ImportError:  # pragma: no cover
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
        self._pools: dict[str, list[QSoundEffect]] = {}
        self._indices: dict[str, int] = {}
        self._volumes: dict[str, float] = {}
        if QSoundEffect is None:
            return
        self._create_pool("woosh", sfx_root / "woosh.wav", pool_size=3, volume=0.38)
        self._create_pool("click", sfx_root / "click.wav", pool_size=4, volume=0.24)

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

    def play(self, name: str, *, volume_scale: float = 1.0) -> None:
        pool = self._pools.get(name)
        if not pool:
            return
        index = self._indices.get(name, 0) % len(pool)
        effect = pool[index]
        self._indices[name] = index + 1
        base_volume = self._volumes.get(name, 1.0)
        effect.setVolume(max(0.0, min(1.0, base_volume * float(volume_scale))))
        effect.play()


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
