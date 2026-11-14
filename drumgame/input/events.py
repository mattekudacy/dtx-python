from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HitEvent:
    """One pad hit. `time` is a `time.perf_counter()` stamp taken at the source."""

    time: float
    lane: str
    velocity: int
    source: str  # "midi" or "keyboard"
