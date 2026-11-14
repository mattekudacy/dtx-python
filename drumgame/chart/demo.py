"""A hardcoded rock beat, so the game is playable with no chart files."""

from __future__ import annotations

from drumgame.chart.model import Chart, Note, Section, TempoEvent, TimeSigEvent


def rock_beat(bars: int = 8, bpm: float = 100.0) -> Chart:
    res = 480
    eighth, bar_len = res // 2, res * 4
    notes: list[Note] = []
    for b in range(bars):
        base = b * bar_len
        last = b == bars - 1
        for e in range(8):
            if last and e >= 6:
                break  # room for the fill
            lane = "crash_l" if (b == 0 and e == 0) else "hihat"
            notes.append(Note(base + e * eighth, lane))
        notes += [Note(base, "kick"), Note(base + 2 * res, "kick")]
        notes.append(Note(base + res, "snare"))
        if not last:
            notes.append(Note(base + 3 * res, "snare"))
    # Sixteenth-note fill down the toms on the last beat, then a final crash.
    fill = (bars - 1) * bar_len + 3 * res
    for i, lane in enumerate(("tom_hi", "tom_mid", "tom_floor", "tom_floor")):
        notes.append(Note(fill + i * res // 4, lane))
    notes += [Note(bars * bar_len, "crash_r"), Note(bars * bar_len, "kick")]
    return Chart(
        title="Rock Beat (built-in)",
        artist="drumgame",
        resolution=res,
        tempos=[TempoEvent(0, bpm)],
        time_signatures=[TimeSigEvent(0, 4, 4)],
        notes=sorted(notes, key=lambda n: n.tick),
        sections=[Section(0, "Groove"), Section(fill, "Fill")],
    )
