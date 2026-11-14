#!/usr/bin/env python3
"""Send a rock beat as MIDI drum notes on channel 10, to test without a kit.

Terminal 1:  python -m drumgame.main --virtual-port
Terminal 2:  python tools/send_test_notes.py --port drumgame

Start this script right after the game's count-in begins; it plays its own
count-in length of silence first so the beat lands roughly in time. It is a
plumbing test, not a timing benchmark.
"""

from __future__ import annotations

import argparse
import sys
import time

import mido

from drumgame.chart.demo import rock_beat
from drumgame.chart.timing import chart_tempo_map, resolve_notes

DRUM_CHANNEL = 9  # MIDI channel 10
LANE_NOTE = {
    "kick": 36, "snare": 38, "hihat": 42, "hh_pedal": 44, "tom_hi": 48, "tom_mid": 45,
    "tom_floor": 43, "crash_l": 49, "crash_r": 57, "ride": 51,
}  # fmt: skip


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", default="drumgame", help="substring of the output port name")
    ap.add_argument("--list", action="store_true", help="list output ports and exit")
    ap.add_argument("--delay", type=float, default=2.4, help="seconds to wait before the beat")
    args = ap.parse_args()

    names = mido.get_output_names()
    if args.list:
        print("\n".join(names) or "no MIDI output ports found")
        return 0
    matches = [n for n in names if args.port.lower() in n.lower()]
    if not matches:
        print(f"no output port matching {args.port!r}; found: {names}", file=sys.stderr)
        return 1

    chart = rock_beat()
    notes = resolve_notes(chart.notes, chart_tempo_map(chart))
    with mido.open_output(matches[0]) as out:
        print(f"sending {len(notes)} notes to {matches[0]!r}")
        start = time.perf_counter() + args.delay
        for n in notes:
            wait = start + n.time - time.perf_counter()
            if wait > 0:
                time.sleep(wait)
            out.send(mido.Message("note_on", channel=DRUM_CHANNEL, note=LANE_NOTE[n.lane], velocity=100))
            out.send(mido.Message("note_off", channel=DRUM_CHANNEL, note=LANE_NOTE[n.lane]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
