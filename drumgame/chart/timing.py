"""Tick <-> seconds conversion through a tempo map, and the beat grid."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Iterable, Sequence

from drumgame.chart.model import Chart, Note, TempoEvent, TimedNote, TimeSigEvent

DEFAULT_BPM = 120.0  # what a MIDI file means when it sets no tempo


class TempoMap:
    def __init__(self, resolution: int, tempos: Iterable[TempoEvent]) -> None:
        if resolution <= 0:
            raise ValueError("resolution must be positive")
        by_tick: dict[int, float] = {}
        for ev in sorted(tempos, key=lambda e: e.tick):
            if ev.bpm <= 0:
                raise ValueError(f"bad tempo {ev}")
            by_tick[ev.tick] = ev.bpm  # several at one tick: the last wins
        if 0 not in by_tick:
            by_tick[0] = DEFAULT_BPM
        self.resolution = resolution
        self._ticks: list[int] = []
        self._secs: list[float] = []
        self._spt: list[float] = []  # seconds per tick in each segment
        t = 0.0
        for tick in sorted(by_tick):
            if self._ticks:
                t += (tick - self._ticks[-1]) * self._spt[-1]
            self._ticks.append(tick)
            self._secs.append(t)
            self._spt.append(60.0 / (by_tick[tick] * resolution))

    def tick_to_seconds(self, tick: float) -> float:
        """Ticks before 0 extrapolate backwards at the first tempo."""
        i = max(bisect_right(self._ticks, tick) - 1, 0)
        return self._secs[i] + (tick - self._ticks[i]) * self._spt[i]

    def seconds_to_tick(self, seconds: float) -> float:
        i = max(bisect_right(self._secs, seconds) - 1, 0)
        return self._ticks[i] + (seconds - self._secs[i]) / self._spt[i]


def resolve_notes(notes: Iterable[Note], tempo_map: TempoMap) -> list[TimedNote]:
    """Convert notes to seconds, sorted by time."""
    out = [TimedNote(tempo_map.tick_to_seconds(n.tick), n.lane, n.ghost) for n in notes]
    out.sort(key=lambda n: n.time)
    return out


@dataclass(frozen=True, slots=True)
class Beat:
    tick: int
    bar: int  # 0-based
    beat: int  # 0-based within the bar; 0 is the downbeat


def beat_grid(
    resolution: int, time_signatures: Sequence[TimeSigEvent], end_tick: int
) -> list[Beat]:
    """Every beat from tick 0 through `end_tick`.

    A beat is one denominator unit (an eighth in 7/8). A time-signature
    change always starts a new bar, even if the previous bar was incomplete.
    """
    by_tick = {ts.tick: ts for ts in sorted(time_signatures, key=lambda e: e.tick)}
    if 0 not in by_tick:
        by_tick[0] = TimeSigEvent(0, 4, 4)
    sigs = [by_tick[t] for t in sorted(by_tick)]
    beats: list[Beat] = []
    bar = 0
    for i, sig in enumerate(sigs):
        last = i == len(sigs) - 1
        seg_end = end_tick if last else min(sigs[i + 1].tick, end_tick + 1)
        step = resolution * 4 / sig.denominator
        k = 0
        while True:
            tick = round(sig.tick + k * step)
            if tick > seg_end or (not last and tick >= seg_end):
                break
            beats.append(Beat(tick, bar + k // sig.numerator, k % sig.numerator))
            k += 1
        bar += -(-k // sig.numerator)  # ceil: a partial bar still counts
    return beats


def chart_tempo_map(chart: Chart) -> TempoMap:
    return TempoMap(chart.resolution, chart.tempos)
