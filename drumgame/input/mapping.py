"""MIDI note -> lane mapping helpers, learn mode and per-lane debounce."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from drumgame.lanes import LANES


def parse_note_map(raw: Mapping[str, str]) -> dict[int, str]:
    """Turn a TOML table like {"36": "kick"} into {36: "kick"}.

    An empty lane string disables a note, so a user config can switch off an
    entry of the default map.
    """
    out: dict[int, str] = {}
    for key, lane in raw.items():
        note = int(key)
        if not 0 <= note <= 127:
            raise ValueError(f"MIDI note out of range: {key}")
        if lane == "":
            continue
        if lane not in LANES:
            raise ValueError(f"unknown lane {lane!r} for MIDI note {key}")
        out[note] = lane
    return out


class Debouncer:
    """Drops hits that follow an accepted hit in the same lane too closely.

    Guards against double triggers and pad crosstalk. Not thread-safe: give
    each input thread its own instance.
    """

    def __init__(self, window_s: float = 0.030) -> None:
        self.window_s = window_s
        self._last: dict[str, float] = {}

    def accept(self, lane: str, t: float) -> bool:
        last = self._last.get(lane)
        if last is not None and t - last < self.window_s:
            return False
        self._last[lane] = t
        return True


@dataclass(frozen=True, slots=True)
class LearnStep:
    lane: str
    name: str
    hint: str


LEARN_STEPS: tuple[LearnStep, ...] = (
    LearnStep("kick", "Kick", "Play the kick pedal a few times."),
    LearnStep("snare", "Snare", "Hit the head and the rim, and play a cross-stick."),
    LearnStep("tom_hi", "Tom 1", "Hit the head and the rim."),
    LearnStep("tom_mid", "Tom 2", "Hit the head and the rim."),
    LearnStep("tom_floor", "Floor tom", "Hit the head and the rim."),
    LearnStep("hihat", "Hi-hat", "Hit the bow and the edge, with the pedal open and then closed."),
    LearnStep("hh_pedal", "Hi-hat pedal", "Close the pedal with your foot, without a stick."),
    LearnStep("crash_l", "Crash 1 (left)", "Hit the bow and the edge."),
    LearnStep("crash_r", "Crash 2 (right)", "Hit the bow and the edge."),
    LearnStep("ride", "Ride", "Hit the bow, the edge and the bell."),
)

# Softer notes are ignored while learning: a firm hit on one pad can make its
# neighbours send quiet notes of their own (crosstalk).
MIN_LEARN_VELOCITY = 25


class LearnSession:
    """Walks through the pads one at a time and records the notes each sends.

    Pure logic: feed it note numbers, move with next/back, read `result`.
    """

    def __init__(
        self, steps: Sequence[LearnStep] = LEARN_STEPS, min_velocity: int = MIN_LEARN_VELOCITY
    ) -> None:
        self.steps = tuple(steps)
        self.min_velocity = min_velocity
        self.index = 0
        self.notes: dict[str, list[int]] = {step.lane: [] for step in self.steps}

    @property
    def done(self) -> bool:
        return self.index >= len(self.steps)

    @property
    def current(self) -> LearnStep | None:
        return None if self.done else self.steps[self.index]

    def feed(self, note: int, velocity: int) -> str:
        """Record a note for the current pad. Returns what happened:
        "added", "repeat", "soft", "moved:<lane it was taken from>" or "done".
        """
        step = self.current
        if step is None:
            return "done"
        if velocity < self.min_velocity:
            return "soft"
        if note in self.notes[step.lane]:
            return "repeat"
        status = "added"
        for lane, notes in self.notes.items():
            if note in notes:  # the latest pad to send a note keeps it
                notes.remove(note)
                status = f"moved:{lane}"
        self.notes[step.lane].append(note)
        return status

    def next(self) -> None:
        """Go to the next pad. A pad left with no notes is simply not mapped."""
        if not self.done:
            self.index += 1

    def back(self) -> None:
        if self.index > 0:
            self.index -= 1

    def clear(self) -> None:
        """Forget the notes of the current pad, to hit it again."""
        step = self.current
        if step is not None:
            self.notes[step.lane].clear()

    def result(self) -> dict[int, str]:
        return {note: lane for lane, notes in self.notes.items() for note in notes}
