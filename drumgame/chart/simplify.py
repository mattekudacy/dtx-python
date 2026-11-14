"""Chart reductions: lane collapse for smaller layouts, ghost-note removal."""

from __future__ import annotations

from typing import Iterable

from drumgame.chart.model import Note
from drumgame.lanes import Layout


def collapse_lanes(notes: Iterable[Note], layout: Layout) -> list[Note]:
    """Fold notes into the layout's lanes, merging any that now coincide.

    When a ghost and a full note merge, the full note wins.
    """
    merged: dict[tuple[int, str], Note] = {}
    for n in notes:
        lane = layout.resolve(n.lane)
        if lane is None:
            continue
        key = (n.tick, lane)
        prev = merged.get(key)
        if prev is None or (prev.ghost and not n.ghost):
            merged[key] = Note(n.tick, lane, n.ghost)
    return sorted(merged.values(), key=lambda n: n.tick)


def drop_ghosts(notes: Iterable[Note]) -> list[Note]:
    return [n for n in notes if not n.ghost]
