import pytest

from drumgame.chart.model import TimedNote
from drumgame.game.judge import HitWindows, Judge, Judgement


def make(*notes):
    return Judge([TimedNote(t, lane) for t, lane in notes], HitWindows(0.050, 0.100))


def test_perfect_good_and_delta_sign():
    j = make((1.0, "snare"), (2.0, "snare"))
    r = j.hit("snare", 1.02)
    assert r.judgement is Judgement.PERFECT and r.delta_s == pytest.approx(0.02)
    r = j.hit("snare", 1.92)
    assert r.judgement is Judgement.GOOD and r.delta_s == pytest.approx(-0.08)
    assert (j.stats.perfect, j.stats.good, j.stats.score, j.stats.combo) == (1, 1, 150, 2)


def test_outside_window_is_stray_and_leaves_note():
    j = make((1.0, "snare"))
    assert j.hit("snare", 0.85).judgement is Judgement.STRAY
    assert j.hit("snare", 1.15).judgement is Judgement.STRAY
    assert j.results == [None]
    assert j.stats.stray == 2


def test_wrong_lane_is_stray():
    j = make((1.0, "snare"))
    assert j.hit("kick", 1.0).judgement is Judgement.STRAY
    assert j.hit("ride", 1.0).judgement is Judgement.STRAY  # lane with no notes at all
    assert j.hit("snare", 1.0).judgement is Judgement.PERFECT


def test_simultaneous_notes_in_different_lanes():
    j = make((1.0, "kick"), (1.0, "hihat"), (1.0, "crash_l"))
    for lane in ("hihat", "kick", "crash_l"):
        assert j.hit(lane, 1.01).judgement is Judgement.PERFECT
    assert j.finished


def test_a_note_is_only_judged_once():
    j = make((1.0, "snare"))
    assert j.hit("snare", 1.0).judgement is Judgement.PERFECT
    assert j.hit("snare", 1.01).judgement is Judgement.STRAY


def test_nearest_note_wins_over_earlier_one():
    j = make((1.00, "snare"), (1.12, "snare"))
    r = j.hit("snare", 1.09)  # 90 ms late for the first, 30 ms early for the second
    assert r.note_index == 1 and r.judgement is Judgement.PERFECT
    r = j.hit("snare", 1.095)  # the first is still open
    assert r.note_index == 0 and r.judgement is Judgement.GOOD


def test_fast_roll_each_hit_takes_its_own_note():
    times = [1.0 + i * 0.06 for i in range(8)]
    j = make(*[(t, "snare") for t in times])
    for i, t in enumerate(times):
        r = j.hit("snare", t + 0.005)
        assert r.note_index == i and r.judgement is Judgement.PERFECT
    assert j.stats.max_combo == 8


def test_miss_after_window_passes_and_resets_combo():
    j = make((1.0, "snare"), (2.0, "snare"), (3.0, "kick"))
    j.hit("snare", 1.0)
    assert j.update(2.05) == []  # still inside the good window
    missed = j.update(2.11)
    assert [(m.judgement, m.note_index, m.lane) for m in missed] == [(Judgement.MISS, 1, "snare")]
    assert j.stats.combo == 0 and j.stats.max_combo == 1 and j.stats.miss == 1
    assert j.hit("snare", 2.12).judgement is Judgement.STRAY  # too late now
    assert j.update(2.5) == []  # not reported twice
    assert not j.finished
    j.hit("kick", 3.0)
    assert j.finished


def test_update_skips_hit_notes():
    j = make((1.0, "snare"), (1.5, "snare"))
    j.hit("snare", 1.0)
    j.hit("snare", 1.5)
    assert j.update(10.0) == []
    assert j.stats.miss == 0


def test_stray_does_not_break_combo():
    j = make((1.0, "snare"), (2.0, "snare"))
    j.hit("snare", 1.0)
    j.hit("snare", 1.5)
    j.hit("snare", 2.0)
    assert j.stats.combo == 2 and j.stats.stray == 1


def test_accuracy():
    j = make((1.0, "snare"), (2.0, "snare"), (3.0, "snare"), (4.0, "snare"))
    assert j.stats.accuracy == 1.0
    j.hit("snare", 1.0)
    j.hit("snare", 2.08)
    j.update(3.5)
    assert j.stats.accuracy == pytest.approx(150 / 300)


def test_configurable_windows():
    j = Judge([TimedNote(1.0, "snare")], HitWindows(0.010, 0.020))
    assert j.hit("snare", 1.03).judgement is Judgement.STRAY
    assert j.hit("snare", 1.015).judgement is Judgement.GOOD
    with pytest.raises(ValueError):
        HitWindows(0.2, 0.1)


def test_unsorted_notes_are_sorted():
    j = make((2.0, "snare"), (1.0, "kick"))
    assert [n.time for n in j.notes] == [1.0, 2.0]
