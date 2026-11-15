"""Latency calibration: how far the player's hits land from a steady click.

Pure logic; the screen that drives it is in screens/calibrate.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Sequence

MIN_HITS = 8


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    count: int
    median_s: float  # positive = hits land after the click
    spread_s: float  # typical distance of a hit from the median

    @property
    def offset_ms(self) -> float:
        """The audio.offset_ms that cancels the measured lag."""
        return round(-self.median_s * 1000, 1)


class Calibration:
    def __init__(self, click_times: Sequence[float], max_error_s: float = 0.25) -> None:
        self.click_times = sorted(click_times)
        self.max_error_s = max_error_s
        self._deltas: dict[int, float] = {}  # click index -> hit time - click time

    def add_hit(self, t: float) -> float | None:
        """Pair a hit with its nearest click. Returns the delta, or None when
        the hit is too far from any click to count. A click keeps only its
        closest hit, so a double trigger does not count twice."""
        if not self.click_times:
            return None
        i = min(range(len(self.click_times)), key=lambda k: abs(t - self.click_times[k]))
        delta = t - self.click_times[i]
        if abs(delta) > self.max_error_s:
            return None
        if i not in self._deltas or abs(delta) < abs(self._deltas[i]):
            self._deltas[i] = delta
        return delta

    @property
    def deltas(self) -> list[float]:
        return [self._deltas[i] for i in sorted(self._deltas)]

    @property
    def hit_clicks(self) -> set[int]:
        """Indexes of the clicks that have a hit."""
        return set(self._deltas)

    @property
    def count(self) -> int:
        return len(self._deltas)

    def result(self) -> CalibrationResult | None:
        """None until enough clicks have a hit to trust the answer."""
        if self.count < MIN_HITS:
            return None
        deltas = self.deltas
        mid = median(deltas)
        # Median absolute deviation, scaled to match a standard deviation.
        spread = 1.4826 * median(abs(d - mid) for d in deltas)
        return CalibrationResult(len(deltas), mid, spread)
