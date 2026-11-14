"""Command-line entry point."""

from __future__ import annotations

import argparse
import queue
import sys
import time
from pathlib import Path

from drumgame.chart.model import Chart
from drumgame.config import Config, load_config
from drumgame.input.mapping import Debouncer
from drumgame.input.midi_in import MidiInput, list_input_ports

VIRTUAL_PORT_NAME = "drumgame"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="drumgame", description="A rhythm game for electronic drums over MIDI."
    )
    p.add_argument(
        "chart", nargs="?", help="chart .json or MIDI file (.mid); default: built-in rock beat"
    )
    p.add_argument("--config", help="config TOML file (default: ~/.config/drumgame/config.toml)")
    p.add_argument("--port", help="substring of the MIDI input port name to open")
    p.add_argument(
        "--virtual-port",
        action="store_true",
        help=f"create a virtual MIDI input port named {VIRTUAL_PORT_NAME!r} instead",
    )
    p.add_argument("--no-midi", action="store_true", help="keyboard only")
    p.add_argument("--layout", choices=["full", "compact"], help="lane layout")
    p.add_argument("--fullscreen", action="store_true", help="start fullscreen (F11 toggles)")
    p.add_argument(
        "--ui-scale", type=float, metavar="N", help="UI size multiplier, 0.5 to 2.0 (default 1.0)"
    )
    p.add_argument(
        "--no-fail", action="store_true", help="keep playing when the gauge empties (practice)"
    )
    p.add_argument("--no-click", action="store_true", help="turn the metronome off")
    p.add_argument("--list-ports", action="store_true", help="list MIDI input ports and exit")
    p.add_argument(
        "--monitor", action="store_true", help="print incoming MIDI hits (no game window)"
    )
    p.add_argument(
        "--save-chart", metavar="OUT.json", help="write the loaded chart as JSON and exit"
    )
    return p


def load_chart(path: str | None) -> Chart:
    if path is None:
        from drumgame.chart.demo import rock_beat

        return rock_beat()
    if Path(path).suffix.lower() in (".mid", ".midi"):
        from drumgame.chart.importers.midi import import_midi

        result = import_midi(path)
        for warning in result.warnings:
            print(f"warning: {warning}", file=sys.stderr)
        return result.chart
    return Chart.load(path)


def open_midi(config: Config, args, hits, listener=None) -> MidiInput:
    midi = MidiInput(
        hits, config.midi_map, Debouncer(config.debounce_s), config.midi_channel, listener
    )
    midi.open(
        args.port if args.port is not None else config.midi_port,
        VIRTUAL_PORT_NAME if args.virtual_port else None,
    )
    return midi


def monitor(config: Config, args) -> int:
    hits: queue.Queue = queue.Queue()
    start = time.perf_counter()

    def listener(note, velocity, channel, lane, status):
        print(
            f"{time.perf_counter() - start:9.3f}s  ch {channel + 1:2}  note {note:3}  "
            f"vel {velocity:3}  {lane or '-':10} {status}",
            flush=True,
        )

    midi = open_midi(config, args, hits, listener)
    if midi.port_name is None:
        print(f"could not open a MIDI input: {midi.error}", file=sys.stderr)
        return 1
    print(f"listening on {midi.port_name!r}; hit pads, Ctrl-C to stop")
    try:
        while True:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        midi.close()
    return 0


def play(config: Config, args, chart: Chart) -> int:
    import pygame

    from drumgame.game.display import open_display
    from drumgame.game.screens.play import PlayScreen
    from drumgame.input.keyboard_in import KeyboardInput, keymap_from_names

    # A small mixer buffer keeps audio latency low; it must be set before init.
    pygame.mixer.pre_init(config.sample_rate, -16, 2, config.audio_buffer)
    pygame.init()
    hits: queue.Queue = queue.Queue()
    midi = None
    try:
        screen = open_display(config.width, config.height, config.fullscreen)
        pygame.display.set_caption(f"drumgame - {chart.title}")
        if args.no_midi:
            status = "Keyboard only (MIDI off)"
        else:
            midi = open_midi(config, args, hits)
            if midi.port_name is not None:
                status = f"MIDI: {midi.port_name}"
            else:
                status = "Keyboard only: no MIDI device found"
                print(f"MIDI unavailable ({midi.error}); using the keyboard", file=sys.stderr)
        keyboard = KeyboardInput(hits, keymap_from_names(config.keyboard))
        connected = midi is not None and midi.port_name is not None
        stats = PlayScreen(screen, chart, config, hits, keyboard, status, connected).run()
        print(
            f"score {stats.score}  perfect {stats.perfect}  good {stats.good}  "
            f"miss {stats.miss}  stray {stats.stray}  max combo {stats.max_combo}"
        )
    finally:
        if midi is not None:
            midi.close()
        pygame.quit()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_ports:
        try:
            names = list_input_ports()
        except Exception as exc:
            print(f"MIDI backend unavailable: {exc}", file=sys.stderr)
            return 1
        print("\n".join(names) if names else "no MIDI input ports found")
        return 0

    overrides: dict = {}
    if args.layout:
        overrides["video"] = {"layout": args.layout, "lane_order": []}
    if args.fullscreen:
        overrides.setdefault("video", {})["fullscreen"] = True
    if args.ui_scale is not None:
        overrides.setdefault("video", {})["ui_scale"] = args.ui_scale
    if args.no_fail:
        overrides["judge"] = {"can_fail": False}
    if args.no_click:
        overrides["audio"] = {"metronome": False}
    try:
        config = load_config(args.config, overrides)
    except (OSError, ValueError, KeyError) as exc:
        print(f"bad config: {exc}", file=sys.stderr)
        return 2

    if args.monitor:
        return monitor(config, args)

    try:
        chart = load_chart(args.chart)
    except (OSError, ValueError, KeyError) as exc:
        print(f"could not load {args.chart}: {exc}", file=sys.stderr)
        return 2
    if args.save_chart:
        chart.save(args.save_chart)
        print(f"wrote {args.save_chart} ({len(chart.notes)} notes)")
        return 0
    return play(config, args, chart)


if __name__ == "__main__":
    sys.exit(main())
