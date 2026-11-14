import pytest

from drumgame.chart.model import Note, TempoEvent, TimeSigEvent
from drumgame.chart.timing import TempoMap, beat_grid, resolve_notes


def test_constant_tempo():
    tm = TempoMap(480, [TempoEvent(0, 120.0)])
    assert tm.tick_to_seconds(0) == 0.0
    assert tm.tick_to_seconds(480) == pytest.approx(0.5)
    assert tm.tick_to_seconds(1920) == pytest.approx(2.0)


def test_tempo_changes_accumulate():
    # 4 beats at 120 (2.0 s), 4 beats at 60 (4.0 s), then 240.
    tm = TempoMap(480, [TempoEvent(0, 120), TempoEvent(1920, 60), TempoEvent(3840, 240)])
    assert tm.tick_to_seconds(1920) == pytest.approx(2.0)
    assert tm.tick_to_seconds(1920 + 480) == pytest.approx(3.0)
    assert tm.tick_to_seconds(3840) == pytest.approx(6.0)
    assert tm.tick_to_seconds(3840 + 480) == pytest.approx(6.25)


def test_many_tempo_changes_round_trip():
    bpms = [104, 97, 147, 108, 168, 110, 109, 106]
    tm = TempoMap(480, [TempoEvent(i * 1000, b) for i, b in enumerate(bpms)])
    for tick in (0, 1, 999, 1000, 2500, 6999, 7000, 12345):
        assert tm.seconds_to_tick(tm.tick_to_seconds(tick)) == pytest.approx(tick)
    secs = [tm.tick_to_seconds(t) for t in range(0, 9000, 37)]
    assert secs == sorted(secs)


def test_unsorted_input_and_duplicate_ticks():
    tm = TempoMap(480, [TempoEvent(480, 60), TempoEvent(0, 100), TempoEvent(0, 120)])
    assert tm.tick_to_seconds(480) == pytest.approx(0.5)  # the last tempo at tick 0 wins
    assert tm.tick_to_seconds(960) == pytest.approx(1.5)


def test_missing_initial_tempo_defaults_to_120():
    tm = TempoMap(480, [TempoEvent(960, 60)])
    assert tm.tick_to_seconds(960) == pytest.approx(1.0)
    assert tm.tick_to_seconds(1440) == pytest.approx(2.0)


def test_negative_ticks_extrapolate_at_first_tempo():
    tm = TempoMap(480, [TempoEvent(0, 120)])
    assert tm.tick_to_seconds(-480) == pytest.approx(-0.5)


def test_triplets_and_32nds_are_exact_at_480():
    tm = TempoMap(480, [TempoEvent(0, 120)])
    assert tm.tick_to_seconds(160) == pytest.approx(0.5 / 3)
    assert tm.tick_to_seconds(60) == pytest.approx(0.5 / 8)


def test_bad_values_rejected():
    with pytest.raises(ValueError):
        TempoMap(0, [])
    with pytest.raises(ValueError):
        TempoMap(480, [TempoEvent(0, 0)])


def test_resolve_notes_sorted_by_time():
    tm = TempoMap(480, [TempoEvent(0, 120)])
    notes = resolve_notes([Note(960, "snare"), Note(0, "kick", ghost=True)], tm)
    assert [(n.time, n.lane, n.ghost) for n in notes] == [(0.0, "kick", True), (1.0, "snare", False)]


def test_beat_grid_4_4():
    beats = beat_grid(480, [TimeSigEvent(0, 4, 4)], 1920)
    assert [(b.tick, b.bar, b.beat) for b in beats] == [
        (0, 0, 0), (480, 0, 1), (960, 0, 2), (1440, 0, 3), (1920, 1, 0),
    ]  # fmt: skip


def test_beat_grid_odd_and_short_bars():
    # One bar of 7/8, one of 1/8, one of 1/4, then 6/8.
    sigs = [
        TimeSigEvent(0, 7, 8),
        TimeSigEvent(1680, 1, 8),
        TimeSigEvent(1920, 1, 4),
        TimeSigEvent(2400, 6, 8),
    ]
    beats = beat_grid(480, sigs, 2400 + 1440)
    downbeats = [b.tick for b in beats if b.beat == 0]
    assert downbeats == [0, 1680, 1920, 2400, 3840]
    assert [b.bar for b in beats if b.beat == 0] == [0, 1, 2, 3, 4]
    assert len([b for b in beats if b.bar == 0]) == 7
    assert len([b for b in beats if b.bar == 3]) == 6


def test_beat_grid_change_mid_bar_starts_new_bar():
    beats = beat_grid(480, [TimeSigEvent(0, 4, 4), TimeSigEvent(960, 3, 4)], 960 + 1440)
    assert [(b.tick, b.bar, b.beat) for b in beats] == [
        (0, 0, 0), (480, 0, 1), (960, 1, 0), (1440, 1, 1), (1920, 1, 2), (2400, 2, 0),
    ]  # fmt: skip
