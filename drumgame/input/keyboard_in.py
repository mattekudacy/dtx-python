"""Keyboard input: pygame key events -> HitEvents on the shared queue."""

from __future__ import annotations

import queue
import time
from typing import Callable, Mapping

import pygame

from drumgame.input.events import HitEvent

KEYBOARD_VELOCITY = 100


def keymap_from_names(names: Mapping[str, str]) -> dict[int, str]:
    """Turn {"space": "kick"} into {pygame.K_SPACE: "kick"}."""
    out: dict[int, str] = {}
    for key_name, lane in names.items():
        try:
            out[pygame.key.key_code(key_name)] = lane
        except ValueError as exc:
            raise ValueError(f"unknown key name {key_name!r} in keyboard map") from exc
    return out


class KeyboardInput:
    def __init__(
        self,
        out_queue: "queue.Queue[HitEvent]",
        keymap: Mapping[int, str],
        time_fn: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._queue = out_queue
        self.keymap = dict(keymap)
        self._time_fn = time_fn

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Feed every pygame event here; returns True if it became a hit.

        pygame gives key events no usable timestamp, so the stamp is taken
        when the frame loop sees the event: keyboard timing is only as fine
        as the frame interval.
        """
        if event.type != pygame.KEYDOWN:
            return False
        lane = self.keymap.get(event.key)
        if lane is None:
            return False
        self._queue.put(HitEvent(self._time_fn(), lane, KEYBOARD_VELOCITY, "keyboard"))
        return True
