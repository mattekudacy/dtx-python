"""Configuration: bundled defaults, overlaid with the user's TOML file."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from drumgame.game.judge import HitWindows
from drumgame.input.mapping import parse_note_map
from drumgame.lanes import LANES, LAYOUTS, Layout
from drumgame.saved import load_saved


# The UI scales to the window, but below this the text is too small to read.
MIN_WIDTH, MIN_HEIGHT = 640, 360


def user_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "drumgame" / "config.toml"


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


@dataclass
class Config:
    midi_port: str
    midi_channel: int | None  # 0-based index, None = any
    debounce_s: float
    keyboard: dict[str, str]  # key name -> lane
    midi_map: dict[int, str]
    windows: HitWindows
    can_fail: bool
    sample_rate: int
    audio_buffer: int
    audio_offset_s: float
    metronome: bool
    width: int
    height: int
    fps: int
    fullscreen: bool
    ui_scale: float
    scroll_seconds: float
    reduce_motion: bool
    layout: Layout

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Config":
        inp, judge, audio, video = d["input"], d["judge"], d["audio"], d["video"]
        channel = int(inp["midi_channel"])
        if not 0 <= channel <= 16:
            raise ValueError("input.midi_channel must be 0 (any) or 1-16")
        keyboard = {k: v for k, v in inp["keyboard"].items() if v != ""}
        for key, lane in keyboard.items():
            if lane not in LANES:
                raise ValueError(f"unknown lane {lane!r} for key {key!r}")
        if video["layout"] not in LAYOUTS:
            raise ValueError(f"video.layout must be one of {sorted(LAYOUTS)}")
        if int(video["width"]) < MIN_WIDTH or int(video["height"]) < MIN_HEIGHT:
            raise ValueError(f"video size must be at least {MIN_WIDTH}x{MIN_HEIGHT}")
        if not 0.5 <= float(video["ui_scale"]) <= 2.0:
            raise ValueError("video.ui_scale must be between 0.5 and 2.0")
        if float(video["scroll_seconds"]) <= 0:
            raise ValueError("video.scroll_seconds must be positive")
        layout = LAYOUTS[video["layout"]]
        if video.get("lane_order"):
            layout = layout.with_order(tuple(video["lane_order"]))
        return cls(
            midi_port=str(inp["midi_port"]),
            midi_channel=channel - 1 if channel else None,
            debounce_s=float(inp["debounce_ms"]) / 1000,
            keyboard=keyboard,
            midi_map=parse_note_map(d["midi_map"]),
            windows=HitWindows(
                float(judge["perfect_ms"]) / 1000, float(judge["good_ms"]) / 1000
            ),
            can_fail=bool(judge["can_fail"]),
            sample_rate=int(audio["sample_rate"]),
            audio_buffer=int(audio["buffer"]),
            audio_offset_s=float(audio["offset_ms"]) / 1000,
            metronome=bool(audio["metronome"]),
            width=int(video["width"]),
            height=int(video["height"]),
            fps=int(video["fps"]),
            fullscreen=bool(video["fullscreen"]),
            ui_scale=float(video["ui_scale"]),
            scroll_seconds=float(video["scroll_seconds"]),
            reduce_motion=bool(video["reduce_motion"]),
            layout=layout,
        )


def default_dict() -> dict[str, Any]:
    text = resources.files("drumgame").joinpath("data/default.toml").read_text("utf-8")
    return tomllib.loads(text)


def load_config(path: str | Path | None = None, overrides: dict[str, Any] | None = None) -> Config:
    """Layers, later ones winning: bundled defaults, the user file (`path`, or
    the XDG location if it exists), what the game saved itself (learned note
    map, calibration), then `overrides` from the command line."""
    data = default_dict()
    if path is not None:
        data = _merge(data, tomllib.loads(Path(path).read_text("utf-8")))
    elif user_config_path().is_file():
        data = _merge(data, tomllib.loads(user_config_path().read_text("utf-8")))
    saved = load_saved()
    if isinstance(saved.get("midi_map"), dict):
        # A learned map describes the whole kit: it replaces the map rather
        # than being laid over the unverified default one.
        data["midi_map"] = saved["midi_map"]
    if isinstance(saved.get("audio"), dict) and "offset_ms" in saved["audio"]:
        data["audio"]["offset_ms"] = saved["audio"]["offset_ms"]
    if overrides:
        data = _merge(data, overrides)
    return Config.from_dict(data)
