"""Canonical lane IDs and display layouts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

# Default display order, DTXMania XG-style.
LANES: tuple[str, ...] = (
    "crash_l",
    "hihat",
    "hh_pedal",
    "snare",
    "tom_hi",
    "kick",
    "tom_mid",
    "tom_floor",
    "crash_r",
    "ride",
)

# Lanes played with the feet, drawn as wide bars.
PEDAL_LANES = frozenset({"kick", "hh_pedal"})


@dataclass(frozen=True)
class Layout:
    """Which lanes are shown, in what order, and how the rest fold into them."""

    name: str
    lanes: tuple[str, ...]
    collapse: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for lane in self.lanes:
            if lane not in LANES:
                raise ValueError(f"unknown lane {lane!r}")
        for src, dst in self.collapse.items():
            if src not in LANES or dst not in self.lanes:
                raise ValueError(f"bad collapse {src!r} -> {dst!r}")

    def resolve(self, lane: str) -> str | None:
        """Map a canonical lane to the lane it is shown in, or None if dropped."""
        lane = self.collapse.get(lane, lane)
        return lane if lane in self.lanes else None

    def with_order(self, order: tuple[str, ...]) -> "Layout":
        if sorted(order) != sorted(self.lanes):
            raise ValueError(
                f"lane_order must be a reordering of {list(self.lanes)}, got {list(order)}"
            )
        return Layout(self.name, tuple(order), self.collapse)


FULL = Layout("full", LANES)

COMPACT = Layout(
    "compact",
    ("hihat", "snare", "tom_hi", "kick", "tom_floor", "crash_r"),
    {
        "hh_pedal": "hihat",
        "tom_mid": "tom_hi",
        "crash_l": "crash_r",
        "ride": "crash_r",
    },
)

LAYOUTS: dict[str, Layout] = {FULL.name: FULL, COMPACT.name: COMPACT}
