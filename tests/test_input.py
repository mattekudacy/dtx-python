import queue

import mido
import pytest

from drumgame.input.mapping import Debouncer, parse_note_map
from drumgame.input.midi_in import MidiInput, _choose_port


class FakeTime:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def make_input(**kw):
    q = queue.Queue()
    clock = FakeTime()
    seen = []
    midi = MidiInput(
        q,
        {36: "kick", 38: "snare", 40: "snare"},
        Debouncer(0.030),
        listener=lambda *a: seen.append(a),
        time_fn=clock,
        **kw,
    )
    return midi, q, clock, seen


def drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_note_on_becomes_stamped_hit():
    midi, q, clock, _ = make_input()
    clock.t = 123.456
    midi.handle_message(mido.Message("note_on", channel=9, note=36, velocity=90))
    (hit,) = drain(q)
    assert (hit.time, hit.lane, hit.velocity, hit.source) == (123.456, "kick", 90, "midi")


def test_velocity_zero_and_other_messages_ignored():
    midi, q, _, seen = make_input()
    midi.handle_message(mido.Message("note_on", channel=9, note=36, velocity=0))
    midi.handle_message(mido.Message("note_off", channel=9, note=36, velocity=64))
    midi.handle_message(mido.Message("control_change", channel=9, control=4, value=90))
    midi.handle_message(mido.Message("clock"))
    assert drain(q) == [] and seen == []


def test_unmapped_note_reported_but_not_queued():
    midi, q, _, seen = make_input()
    midi.handle_message(mido.Message("note_on", channel=9, note=99, velocity=80))
    assert drain(q) == []
    assert seen == [(99, 80, 9, None, "unmapped")]


def test_channel_filter():
    midi, q, _, seen = make_input(channel=9)
    midi.handle_message(mido.Message("note_on", channel=0, note=36, velocity=80))
    midi.handle_message(mido.Message("note_on", channel=9, note=36, velocity=80))
    assert len(drain(q)) == 1
    assert [s[-1] for s in seen] == ["filtered", "hit"]


def test_any_channel_by_default():
    midi, q, _, _ = make_input()
    midi.handle_message(mido.Message("note_on", channel=0, note=36, velocity=80))
    assert len(drain(q)) == 1


def test_debounce_is_per_lane():
    midi, q, clock, seen = make_input()
    midi.handle_message(mido.Message("note_on", note=38, velocity=80))
    clock.t += 0.010
    midi.handle_message(mido.Message("note_on", note=40, velocity=80))  # same lane: dropped
    midi.handle_message(mido.Message("note_on", note=36, velocity=80))  # other lane: kept
    clock.t += 0.025
    midi.handle_message(mido.Message("note_on", note=38, velocity=80))  # 35 ms on: kept
    assert [h.lane for h in drain(q)] == ["snare", "kick", "snare"]
    assert [s[-1] for s in seen] == ["hit", "debounced", "hit", "hit"]


def test_debouncer_measures_from_last_accepted_hit():
    d = Debouncer(0.030)
    assert d.accept("snare", 0.000)
    assert not d.accept("snare", 0.020)
    assert d.accept("snare", 0.040)  # 40 ms after the accepted hit, not 20 after the dropped one


def test_open_fails_gracefully(monkeypatch):
    def boom(*a, **k):
        raise OSError("no backend")

    monkeypatch.setattr(mido, "get_input_names", boom)
    midi, _, _, _ = make_input()
    assert midi.open() is False
    assert midi.port_name is None and "no backend" in midi.error
    midi.close()  # safe when nothing is open


def test_open_with_no_ports(monkeypatch):
    monkeypatch.setattr(mido, "get_input_names", lambda: [])
    midi, _, _, _ = make_input()
    assert midi.open() is False
    assert "no MIDI input ports" in midi.error


def test_choose_port():
    names = ["Midi Through:Midi Through Port-0 14:0", "TD-17:TD-17 MIDI 1 24:0"]
    assert _choose_port(names, "") == names[1]
    assert _choose_port(names, "td-17") == names[1]
    assert _choose_port(names[:1], "") == names[0]
    with pytest.raises(RuntimeError):
        _choose_port(names, "nope")


def test_parse_note_map():
    assert parse_note_map({"36": "kick", "38": "snare", "40": ""}) == {36: "kick", 38: "snare"}
    with pytest.raises(ValueError):
        parse_note_map({"36": "cowbell"})
    with pytest.raises(ValueError):
        parse_note_map({"200": "kick"})
