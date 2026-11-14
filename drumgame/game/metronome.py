"""Metronome click: schedule from the beat grid, rendered to one PCM buffer.

The whole click track is rendered up front and started together with the
song clock, so clicks are sample-accurate instead of jittering with frames.
No pygame in here.
"""

from __future__ import annotations

import math
from array import array
from typing import Sequence

from drumgame.chart.model import Chart
from drumgame.chart.timing import TempoMap, beat_grid

Click = tuple[float, bool]  # (song time in seconds, accented)


def click_schedule(
    chart: Chart, tempo_map: TempoMap, count_in_beats: int = 4
) -> tuple[float, list[Click]]:
    """Return (lead_in_seconds, clicks). Count-in clicks have negative times."""
    beats = beat_grid(chart.resolution, chart.time_signatures, chart.end_tick)
    clicks: list[Click] = [(tempo_map.tick_to_seconds(b.tick), b.beat == 0) for b in beats]
    first_sig = min(chart.time_signatures, key=lambda s: s.tick)
    beat_s = tempo_map.tick_to_seconds(chart.resolution * 4 / first_sig.denominator)
    lead_in = count_in_beats * beat_s
    count_in = [(-k * beat_s, k == count_in_beats) for k in range(count_in_beats, 0, -1)]
    return lead_in, count_in + clicks


def _click_samples(freq: float, sample_rate: int, length_s: float = 0.03) -> array:
    n = int(sample_rate * length_s)
    return array(
        "h",
        (
            int(14000 * math.sin(2 * math.pi * freq * i / sample_rate) * math.exp(-6 * i / n))
            for i in range(n)
        ),
    )


def render_click_track(
    clicks: Sequence[Click],
    lead_in_s: float,
    sample_rate: int = 44100,
    channels: int = 2,
    tail_s: float = 0.5,
) -> bytes:
    """Signed 16-bit interleaved PCM; sample 0 is song time -lead_in_s."""
    if not clicks:
        return b""
    total = int((max(t for t, _ in clicks) + lead_in_s + tail_s) * sample_rate)
    mono = array("h", bytes(2 * total))
    sounds = {True: _click_samples(1760.0, sample_rate), False: _click_samples(880.0, sample_rate)}
    for t, accent in clicks:
        start = round((t + lead_in_s) * sample_rate)
        if start < 0 or start >= total:
            continue
        snd = sounds[accent][: total - start]
        mono[start : start + len(snd)] = snd
    if channels == 1:
        return mono.tobytes()
    out = array("h", bytes(2 * total * channels))
    for c in range(channels):
        out[c::channels] = mono
    return out.tobytes()
