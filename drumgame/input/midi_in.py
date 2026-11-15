"""MIDI input: an rtmidi callback that pushes HitEvents onto a queue."""

from __future__ import annotations

import queue
import time
from typing import Callable, Mapping

from drumgame.input.events import HitEvent
from drumgame.input.mapping import Debouncer

# listener(note, velocity, channel_index, lane_or_None, status)
# status is "hit", "debounced", "unmapped" or "filtered" (wrong channel).
Listener = Callable[[int, int, int, "str | None", str], None]


def list_input_ports() -> list[str]:
    """Names of available MIDI input ports. Raises if the backend is unusable."""
    import mido

    return list(mido.get_input_names())


class MidiInput:
    def __init__(
        self,
        out_queue: "queue.Queue[HitEvent]",
        note_map: Mapping[int, str],
        debouncer: Debouncer | None = None,
        channel: int | None = None,
        listener: Listener | None = None,
        time_fn: Callable[[], float] = time.perf_counter,
    ) -> None:
        """`channel` is a 0-based index (drum channel 10 is 9); None accepts all."""
        self._queue = out_queue
        self._note_map = note_map
        self._debouncer = debouncer or Debouncer()
        self._channel = channel
        self.listener = listener
        self._time_fn = time_fn
        self._port = None
        self.port_name: str | None = None
        self.error: str | None = None

    def open(self, port_hint: str = "", virtual_name: str | None = None) -> bool:
        """Open a port; never raises. On failure returns False and sets `error`.

        `port_hint` is a case-insensitive substring of the port name. With
        `virtual_name`, create a virtual port other programs can send to.
        """
        try:
            import mido

            if virtual_name:
                name = virtual_name
                self._port = mido.open_input(
                    name, virtual=True, callback=self.handle_message
                )
            else:
                names = list(mido.get_input_names())
                name = _choose_port(names, port_hint)
                self._port = mido.open_input(name, callback=self.handle_message)
        except Exception as exc:  # missing backend, no device, busy port...
            self.error = str(exc) or type(exc).__name__
            self._port = None
            return False
        self.port_name = name
        self.error = None
        return True

    def close(self) -> None:
        if self._port is not None:
            self._port.close()
            self._port = None

    def handle_message(self, msg) -> None:
        """Runs on the rtmidi thread. Stamp first, then filter."""
        t = self._time_fn()
        # A note_on with velocity 0 is a note-off.
        if msg.type != "note_on" or msg.velocity == 0:
            return
        if self._channel is not None and msg.channel != self._channel:
            status, lane = "filtered", None
        else:
            lane = self._note_map.get(msg.note)
            if lane is None:
                status = "unmapped"
            elif not self._debouncer.accept(lane, t):
                status = "debounced"
            else:
                status = "hit"
                self._queue.put(HitEvent(t, lane, msg.velocity, "midi"))
        if self.listener is not None:
            self.listener(msg.note, msg.velocity, msg.channel, lane, status)


def _choose_port(names: list[str], hint: str) -> str:
    if not names:
        raise RuntimeError("no MIDI input ports found")
    if hint:
        for name in names:
            if hint.lower() in name.lower():
                return name
        raise RuntimeError(f"no MIDI input port matching {hint!r} (found: {names})")
    # ALSA always exposes a loopback "Midi Through" port; prefer a real device.
    for name in names:
        if "midi through" not in name.lower():
            return name
    return names[0]
