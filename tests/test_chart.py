import mido
import pytest

from drumgame.chart.demo import rock_beat
from drumgame.chart.importers.midi import import_midi
from drumgame.chart.model import AudioRef, Chart, Note, Section, TempoEvent, TimeSigEvent
from drumgame.chart.simplify import collapse_lanes, drop_ghosts
from drumgame.chart.timing import chart_tempo_map, resolve_notes
from drumgame.lanes import COMPACT, FULL, LANES


def test_json_round_trip(tmp_path):
    chart = Chart(
        title="T",
        artist="A",
        tempos=[TempoEvent(0, 104), TempoEvent(960, 97.5)],
        time_signatures=[TimeSigEvent(0, 7, 8), TimeSigEvent(1680, 1, 8)],
        notes=[Note(0, "kick"), Note(0, "hihat"), Note(160, "snare", ghost=True)],
        sections=[Section(0, "Intro")],
        audio=AudioRef("backing.ogg", -35.0),
    )
    path = tmp_path / "c.json"
    chart.save(path)
    assert Chart.load(path) == chart


def test_handoff_example_loads():
    chart = Chart.from_dict(
        {
            "title": "Example",
            "artist": "Example",
            "resolution": 480,
            "audio": {"file": "backing.ogg", "offset_ms": 0},
            "tempos": [{"tick": 0, "bpm": 120.0}],
            "time_signatures": [{"tick": 0, "numerator": 4, "denominator": 4}],
            "notes": [{"tick": 0, "lane": "kick"}, {"tick": 0, "lane": "hihat"}],
            "sections": [{"tick": 0, "name": "Intro"}],
        }
    )
    assert len(chart.notes) == 2 and chart.audio.file == "backing.ogg"


def test_unknown_lane_rejected():
    with pytest.raises(ValueError):
        Chart(notes=[Note(0, "cowbell")])


def test_demo_chart():
    chart = rock_beat(bars=4, bpm=120)
    assert {n.lane for n in chart.notes} <= set(LANES)
    notes = resolve_notes(chart.notes, chart_tempo_map(chart))
    assert notes[0].time == 0.0
    assert notes[-1].time == pytest.approx(8.0)  # 4 bars of 4/4 at 120


def test_collapse_to_compact_merges_and_dedupes():
    notes = [
        Note(0, "crash_l"),
        Note(0, "ride"),
        Note(0, "kick"),
        Note(480, "hh_pedal", ghost=True),
        Note(480, "hihat"),
        Note(960, "tom_mid"),
    ]
    out = collapse_lanes(notes, COMPACT)
    assert out == [Note(0, "crash_r"), Note(0, "kick"), Note(480, "hihat"), Note(960, "tom_hi")]
    assert collapse_lanes(notes, FULL) == notes


def test_layout_order_and_validation():
    order = tuple(reversed(COMPACT.lanes))
    assert COMPACT.with_order(order).lanes == order
    with pytest.raises(ValueError):
        COMPACT.with_order(("kick", "snare"))


def test_drop_ghosts():
    assert drop_ghosts([Note(0, "snare", True), Note(1, "snare")]) == [Note(1, "snare")]


def write_midi(path, tracks, tpb=480, type_=1):
    mid = mido.MidiFile(type=type_, ticks_per_beat=tpb)
    for events in tracks:
        track = mido.MidiTrack()
        last = 0
        for tick, msg in sorted(events, key=lambda e: e[0]):
            track.append(msg.copy(time=tick - last))
            last = tick
        mid.tracks.append(track)
    mid.save(path)


def on(note, vel=100, ch=9):
    return mido.Message("note_on", channel=ch, note=note, velocity=vel)


def test_midi_import_with_tempo_and_time_signature_changes(tmp_path):
    path = tmp_path / "song.mid"
    conductor = [
        (0, mido.MetaMessage("track_name", name="My Song")),
        (0, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120))),
        (0, mido.MetaMessage("time_signature", numerator=4, denominator=4)),
        (0, mido.MetaMessage("marker", text="Intro")),
        (1920, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(60))),
        (1920, mido.MetaMessage("time_signature", numerator=7, denominator=8)),
    ]
    drums = [
        (0, on(36)),
        (0, on(42)),
        (0, on(49)),
        (480, on(38)),
        (480, mido.Message("note_off", channel=9, note=38)),
        (960, on(46)),  # open hi-hat -> same lane as closed
        (960, on(42)),  # duplicate in the hihat lane at this tick
        (1920, on(36)),
        (1920, on(38, vel=0)),  # note-off in disguise
        (2400, on(38, vel=20)),
    ]
    bass = [(0, on(40, ch=1)), (480, on(43, ch=1))]
    write_midi(path, [conductor, drums, bass])

    result = import_midi(path, ghost_velocity=30)
    chart = result.chart
    assert result.warnings == []
    assert chart.title == "My Song" and chart.resolution == 480
    assert [(t.tick, round(t.bpm, 3)) for t in chart.tempos] == [(0, 120.0), (1920, 60.0)]
    assert chart.time_signatures == [TimeSigEvent(0, 4, 4), TimeSigEvent(1920, 7, 8)]
    assert chart.sections == [Section(0, "Intro")]
    assert [(n.tick, n.lane, n.ghost) for n in chart.notes] == [
        (0, "crash_l", False),
        (0, "hihat", False),
        (0, "kick", False),
        (480, "snare", False),
        (960, "hihat", False),
        (1920, "kick", False),
        (2400, "snare", True),
    ]
    times = [n.time for n in resolve_notes(chart.notes, chart_tempo_map(chart))]
    assert times[-2:] == pytest.approx([2.0, 3.0])  # a beat at 60 BPM lasts 1 s


def test_midi_import_keeps_file_resolution(tmp_path):
    path = tmp_path / "r.mid"
    write_midi(path, [[(0, on(36)), (96, on(38))]], tpb=96, type_=0)
    chart = import_midi(path).chart
    assert chart.resolution == 96 and chart.title == "r"
    assert chart.tempos == [TempoEvent(0, 120.0)]  # MIDI default when none is set
    times = [n.time for n in resolve_notes(chart.notes, chart_tempo_map(chart))]
    assert times == pytest.approx([0.0, 0.5])


def test_midi_import_warns_on_wrong_channel_and_unmapped(tmp_path):
    path = tmp_path / "w.mid"
    write_midi(path, [[(0, on(36, ch=0)), (10, on(81, ch=0)), (20, on(81, ch=0))]])
    result = import_midi(path)
    assert [n.lane for n in result.chart.notes] == ["kick"]
    assert len(result.warnings) == 2
    assert "channel 10" in result.warnings[0]
    assert "81 (x2)" in result.warnings[1]
