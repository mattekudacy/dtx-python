"""The one internal chart format. Musical time is in ticks plus a tempo map."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from drumgame.lanes import LANES

DEFAULT_RESOLUTION = 480  # ticks per quarter note; divisible by 3 and by 8


@dataclass(frozen=True, slots=True)
class Note:
    tick: int
    lane: str
    ghost: bool = False


@dataclass(frozen=True, slots=True)
class TempoEvent:
    tick: int
    bpm: float


@dataclass(frozen=True, slots=True)
class TimeSigEvent:
    tick: int
    numerator: int
    denominator: int


@dataclass(frozen=True, slots=True)
class Section:
    tick: int
    name: str


@dataclass(frozen=True, slots=True)
class AudioRef:
    file: str
    offset_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class TimedNote:
    """A note resolved to seconds, ready for judging and drawing."""

    time: float
    lane: str
    ghost: bool = False


@dataclass
class Chart:
    title: str = "Untitled"
    artist: str = ""
    resolution: int = DEFAULT_RESOLUTION
    tempos: list[TempoEvent] = field(default_factory=lambda: [TempoEvent(0, 120.0)])
    time_signatures: list[TimeSigEvent] = field(
        default_factory=lambda: [TimeSigEvent(0, 4, 4)]
    )
    notes: list[Note] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    audio: AudioRef | None = None

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if self.resolution <= 0:
            raise ValueError("resolution must be positive")
        for t in self.tempos:
            if t.bpm <= 0 or t.tick < 0:
                raise ValueError(f"bad tempo event {t}")
        for ts in self.time_signatures:
            if ts.numerator <= 0 or ts.denominator <= 0 or ts.tick < 0:
                raise ValueError(f"bad time signature {ts}")
        for n in self.notes:
            if n.lane not in LANES:
                raise ValueError(f"unknown lane {n.lane!r} at tick {n.tick}")
            if n.tick < 0:
                raise ValueError(f"negative tick on note {n}")

    @property
    def end_tick(self) -> int:
        return max((n.tick for n in self.notes), default=0)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "title": self.title,
            "artist": self.artist,
            "resolution": self.resolution,
        }
        if self.audio is not None:
            d["audio"] = {"file": self.audio.file, "offset_ms": self.audio.offset_ms}
        d["tempos"] = [{"tick": t.tick, "bpm": t.bpm} for t in self.tempos]
        d["time_signatures"] = [
            {"tick": t.tick, "numerator": t.numerator, "denominator": t.denominator}
            for t in self.time_signatures
        ]
        d["notes"] = [
            {"tick": n.tick, "lane": n.lane, **({"ghost": True} if n.ghost else {})}
            for n in self.notes
        ]
        d["sections"] = [{"tick": s.tick, "name": s.name} for s in self.sections]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Chart":
        audio = d.get("audio")
        return cls(
            title=d.get("title", "Untitled"),
            artist=d.get("artist", ""),
            resolution=int(d.get("resolution", DEFAULT_RESOLUTION)),
            tempos=[TempoEvent(int(t["tick"]), float(t["bpm"])) for t in d.get("tempos", [])]
            or [TempoEvent(0, 120.0)],
            time_signatures=[
                TimeSigEvent(int(t["tick"]), int(t["numerator"]), int(t["denominator"]))
                for t in d.get("time_signatures", [])
            ]
            or [TimeSigEvent(0, 4, 4)],
            notes=[
                Note(int(n["tick"]), n["lane"], bool(n.get("ghost", False)))
                for n in d.get("notes", [])
            ],
            sections=[Section(int(s["tick"]), s["name"]) for s in d.get("sections", [])],
            audio=AudioRef(audio["file"], float(audio.get("offset_ms", 0.0)))
            if audio and audio.get("file")
            else None,
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Chart":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
