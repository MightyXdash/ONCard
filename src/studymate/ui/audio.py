from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl

try:
    from PySide6.QtMultimedia import QSoundEffect
except ImportError:  # pragma: no cover
    QSoundEffect = None  # type: ignore[assignment]


class UiSoundBank:
    def __init__(self, sfx_root: Path) -> None:
        self._pools: dict[str, list[QSoundEffect]] = {}
        self._indices: dict[str, int] = {}
        if QSoundEffect is None:
            return
        self._create_pool("woosh", sfx_root / "woosh.wav", pool_size=3, volume=0.38)
        self._create_pool("click", sfx_root / "click.wav", pool_size=4, volume=0.32)

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

    def play(self, name: str) -> None:
        pool = self._pools.get(name)
        if not pool:
            return
        index = self._indices.get(name, 0) % len(pool)
        effect = pool[index]
        self._indices[name] = index + 1
        effect.play()
