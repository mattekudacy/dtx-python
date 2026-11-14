"""Standard MIDI file -> Chart."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import mido

from drumgame.chart.model import Chart, Note, Section, TempoEvent, TimeSigEvent

DRUM_CHANNEL = 9  # MIDI channel 10; mido counts from 0

# General MIDI percussion, plus the extra hi-hat notes (22, 26) that Roland
# modules and many Guitar Pro exports use.
GM_DRUM_MAP: dict[int, str] = {
    35: "kick", 36: "kick",
    37: "snare", 38: "snare", 39: "snare", 40: "snare",
    41: "tom_floor", 43: "tom_floor",
    45: "tom_mid", 47: "tom_mid",
    48: "tom_hi", 50: "tom_hi",
    22: "hihat", 26: "hihat", 42: "hihat", 46: "hihat",
    44: "hh_pedal",
    49: "crash_l", 55: "crash_l",
    52: "crash_r", 57: "crash_r",
    51: "ride", 53: "ride", 59: "ride",
}  # fmt: skip


@dataclass
class MidiImport:
    chart: Chart
    warnings: list[str] = field(default_factory=list)


def import_midi(
    path: str | Path,
    note_map: dict[int, str] | None = None,
    ghost_velocity: int = 0,
) -> MidiImport:
    """Read the drum part of a MIDI file.

    Ticks are kept exactly as in the file (the chart takes the file's
    resolution), so nothing is re-quantized. Notes with velocity at or below
    `ghost_velocity` are flagged as ghosts; 0 disables that.
    """
    path = Path(path)
    note_map = GM_DRUM_MAP if note_map is None else note_map
    mid = mido.MidiFile(path)
    if mid.ticks_per_beat <= 0:
        raise ValueError("SMPTE-timed MIDI files are not supported")
    if mid.type == 2:
        raise ValueError("type 2 (multi-song) MIDI files are not supported")

    warnings: list[str] = []
    tempos: dict[int, float] = {}
    sigs: dict[int, TimeSigEvent] = {}
    sections: list[Section] = []
    title = ""
    hits: list[tuple[int, int, int, int]] = []  # tick, note, velocity, channel

    for index, track in enumerate(mid.tracks):
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "set_tempo":
                tempos[tick] = mido.tempo2bpm(msg.tempo)
            elif msg.type == "time_signature":
                sigs[tick] = TimeSigEvent(tick, msg.numerator, msg.denominator)
            elif msg.type == "marker":
                sections.append(Section(tick, msg.text.strip()))
            elif msg.type == "track_name" and index == 0 and not title:
                title = msg.name.strip()
            elif msg.type == "note_on" and msg.velocity > 0:
                hits.append((tick, msg.note, msg.velocity, msg.channel))

    drum_hits = [h for h in hits if h[3] == DRUM_CHANNEL]
    if not drum_hits and hits:
        warnings.append(
            "no notes on MIDI channel 10; treating every channel as drums, "
            "so melodic parts may show up as hits"
        )
        drum_hits = hits
    if not drum_hits:
        warnings.append("the file contains no notes")

    notes: dict[tuple[int, str], Note] = {}
    unmapped: dict[int, int] = {}
    for tick, note, velocity, _ in drum_hits:
        lane = note_map.get(note)
        if lane is None:
            unmapped[note] = unmapped.get(note, 0) + 1
            continue
        ghost = velocity <= ghost_velocity
        prev = notes.get((tick, lane))
        if prev is None or (prev.ghost and not ghost):
            notes[(tick, lane)] = Note(tick, lane, ghost)
    if unmapped:
        detail = ", ".join(f"{n} (x{c})" for n, c in sorted(unmapped.items()))
        warnings.append(f"skipped notes with no lane mapping: {detail}")

    chart = Chart(
        title=title or path.stem,
        resolution=mid.ticks_per_beat,
        tempos=[TempoEvent(t, bpm) for t, bpm in sorted(tempos.items())]
        or [TempoEvent(0, 120.0)],
        time_signatures=[sigs[t] for t in sorted(sigs)] or [TimeSigEvent(0, 4, 4)],
        notes=sorted(notes.values(), key=lambda n: (n.tick, n.lane)),
        sections=sorted(sections, key=lambda s: s.tick),
    )
    return MidiImport(chart, warnings)
