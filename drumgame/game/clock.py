"""The song clock, anchored to time.perf_counter()."""

from __future__ import annotations

import time
from typing import Callable


class SongClock:
    """Song time = perf_counter time since the anchor, plus an offset.

    `offset_s` is the calibration offset: positive values make the game
    treat everything (hits and visuals) as happening later in the song.
    """

    def __init__(
        self, offset_s: float = 0.0, time_fn: Callable[[], float] = time.perf_counter
    ) -> None:
        self.offset_s = offset_s
        self._time_fn = time_fn
        self._anchor: float | None = None
        self._paused_at: float | None = None  # perf time when paused

    @property
    def running(self) -> bool:
        return self._anchor is not None and self._paused_at is None

    @property
    def paused(self) -> bool:
        return self._paused_at is not None

    def start(self, start_at: float = 0.0) -> None:
        """Start now, with the song at `start_at` seconds (negative = lead-in)."""
        self._anchor = self._time_fn() - start_at
        self._paused_at = None

    def to_song_time(self, perf_time: float) -> float:
        """Convert a perf_counter stamp (e.g. a HitEvent time) to song time."""
        if self._anchor is None:
            raise RuntimeError("clock not started")
        return perf_time - self._anchor + self.offset_s

    def now(self) -> float:
        if self._paused_at is not None:
            return self.to_song_time(self._paused_at)
        return self.to_song_time(self._time_fn())

    def pause(self) -> None:
        if self.running:
            self._paused_at = self._time_fn()

    def resume(self) -> None:
        if self._paused_at is not None and self._anchor is not None:
            self._anchor += self._time_fn() - self._paused_at
            self._paused_at = None
