"""MIDI note -> lane mapping helpers and per-lane debounce."""

from __future__ import annotations

from typing import Mapping

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
