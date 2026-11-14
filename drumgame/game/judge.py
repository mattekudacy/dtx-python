"""Hit judging, scoring and combo. No pygame in here."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from drumgame.chart.model import TimedNote


class Judgement(Enum):
    PERFECT = "perfect"
    GOOD = "good"
    MISS = "miss"
    STRAY = "stray"  # a hit with no note close enough


@dataclass(frozen=True, slots=True)
class HitWindows:
    perfect_s: float = 0.050
    good_s: float = 0.100

    def __post_init__(self) -> None:
        if not 0 < self.perfect_s <= self.good_s:
            raise ValueError("need 0 < perfect <= good")


@dataclass(frozen=True, slots=True)
class JudgeResult:
    judgement: Judgement
    lane: str
    time: float  # hit time, or the note's time for a miss
    note_index: int | None = None  # into Judge.notes; None for a stray
    delta_s: float | None = None  # hit time - note time; negative = early


SCORE = {Judgement.PERFECT: 100, Judgement.GOOD: 50}


@dataclass
class Stats:
    total: int = 0
    perfect: int = 0
    good: int = 0
    miss: int = 0
    stray: int = 0
    combo: int = 0
    max_combo: int = 0
    score: int = 0

    @property
    def accuracy(self) -> float:
        """Share of the maximum score earned so far, over judged notes."""
        judged = self.perfect + self.good + self.miss
        return self.score / (judged * SCORE[Judgement.PERFECT]) if judged else 1.0


GRADES = ((0.95, "S"), (0.90, "A"), (0.80, "B"), (0.70, "C"))


def grade(accuracy: float) -> str:
    for threshold, letter in GRADES:
        if accuracy >= threshold:
            return letter
    return "D"


class Gauge:
    """A 0..1 meter of recent form: hits fill it, misses drain it faster.

    When it reaches zero the run has failed; whether that ends the song is
    up to the caller.
    """

    CHANGE = {Judgement.PERFECT: 0.02, Judgement.GOOD: 0.01, Judgement.MISS: -0.06}

    def __init__(self, value: float = 0.5) -> None:
        self.value = value

    @property
    def empty(self) -> bool:
        return self.value <= 0.0

    def apply(self, judgement: Judgement) -> None:
        self.value = min(1.0, max(0.0, self.value + self.CHANGE.get(judgement, 0.0)))


class Judge:
    def __init__(self, notes: Iterable[TimedNote], windows: HitWindows = HitWindows()) -> None:
        self.notes: list[TimedNote] = sorted(notes, key=lambda n: n.time)
        self.windows = windows
        self.results: list[Judgement | None] = [None] * len(self.notes)
        self.stats = Stats(total=len(self.notes))
        self.gauge = Gauge()
        self._by_lane: dict[str, list[int]] = {}
        for i, n in enumerate(self.notes):
            self._by_lane.setdefault(n.lane, []).append(i)
        self._head: dict[str, int] = {lane: 0 for lane in self._by_lane}
        self._miss_cursor = 0

    @property
    def finished(self) -> bool:
        return self._miss_cursor >= len(self.notes) or all(
            r is not None for r in self.results[self._miss_cursor :]
        )

    def hit(self, lane: str, t: float) -> JudgeResult:
        """Judge a hit at song time `t` against the nearest unjudged note in its lane."""
        good = self.windows.good_s
        idxs = self._by_lane.get(lane, [])
        head = self._head.get(lane, 0)
        while head < len(idxs) and self.results[idxs[head]] is not None:
            head += 1
        if idxs:
            self._head[lane] = head
        best: int | None = None
        best_delta = 0.0
        for k in range(head, len(idxs)):
            i = idxs[k]
            if self.results[i] is not None:
                continue
            delta = t - self.notes[i].time
            if delta < -good:
                break  # this note and all later ones are too far ahead
            if delta <= good and (best is None or abs(delta) < abs(best_delta)):
                best, best_delta = i, delta
        if best is None:
            self.stats.stray += 1
            return JudgeResult(Judgement.STRAY, lane, t)
        judgement = (
            Judgement.PERFECT if abs(best_delta) <= self.windows.perfect_s else Judgement.GOOD
        )
        self.results[best] = judgement
        self.gauge.apply(judgement)
        s = self.stats
        if judgement is Judgement.PERFECT:
            s.perfect += 1
        else:
            s.good += 1
        s.score += SCORE[judgement]
        s.combo += 1
        s.max_combo = max(s.max_combo, s.combo)
        return JudgeResult(judgement, lane, t, best, best_delta)

    def update(self, now: float) -> list[JudgeResult]:
        """Mark notes whose window has fully passed as misses. Call after
        feeding this frame's hits."""
        missed: list[JudgeResult] = []
        good = self.windows.good_s
        while self._miss_cursor < len(self.notes):
            i = self._miss_cursor
            note = self.notes[i]
            if note.time + good >= now:
                break
            if self.results[i] is None:
                self.results[i] = Judgement.MISS
                self.stats.miss += 1
                self.stats.combo = 0
                self.gauge.apply(Judgement.MISS)
                missed.append(JudgeResult(Judgement.MISS, note.lane, note.time, i))
            self._miss_cursor += 1
        return missed
