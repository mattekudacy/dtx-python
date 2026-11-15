"""Learn mode, calibration and saved settings."""

import json
import queue

import pytest

from drumgame import saved
from drumgame.config import load_config
from drumgame.game.calibration import MIN_HITS, Calibration
from drumgame.input.mapping import LEARN_STEPS, LearnSession
from drumgame.lanes import LANES


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


# -- learn session ---------------------------------------------------------


def test_learn_steps_cover_every_lane_once():
    assert sorted(step.lane for step in LEARN_STEPS) == sorted(LANES)


def test_learn_records_notes_per_pad():
    s = LearnSession()
    assert s.current.lane == "kick"
    assert s.feed(36, 100) == "added"
    assert s.feed(36, 90) == "repeat"
    s.next()
    assert s.current.lane == "snare"
    for note in (38, 40, 37):
        assert s.feed(note, 80) == "added"
    assert s.result() == {36: "kick", 38: "snare", 40: "snare", 37: "snare"}


def test_learn_ignores_soft_notes_as_crosstalk():
    s = LearnSession()
    assert s.feed(48, 10) == "soft"
    assert s.result() == {}


def test_learn_note_moves_to_the_latest_pad():
    s = LearnSession()
    s.feed(36, 100)
    s.next()
    assert s.feed(36, 100) == "moved:kick"
    assert s.result() == {36: "snare"}


def test_learn_back_clear_and_skipping():
    s = LearnSession()
    s.feed(36, 100)
    s.next()
    s.feed(99, 100)
    s.clear()
    assert s.notes["snare"] == []
    s.back()
    assert s.current.lane == "kick" and s.notes["kick"] == [36]
    s.back()  # already at the first pad
    assert s.index == 0
    while not s.done:
        s.next()  # every remaining pad skipped
    assert s.current is None and s.feed(1, 100) == "done"
    assert s.result() == {36: "kick"}


# -- calibration -----------------------------------------------------------


def test_calibration_measures_a_constant_lag():
    clicks = [i * 0.6 for i in range(16)]
    cal = Calibration(clicks)
    for i, t in enumerate(clicks):
        cal.add_hit(t + 0.030 + (0.004 if i % 2 else -0.004))
    result = cal.result()
    assert result.count == 16
    assert result.median_s == pytest.approx(0.030, abs=0.005)
    assert result.spread_s < 0.010
    assert result.offset_ms == pytest.approx(-30, abs=5)


def test_calibration_early_hits_give_a_positive_offset():
    clicks = [i * 0.6 for i in range(16)]
    cal = Calibration(clicks)
    for t in clicks:
        cal.add_hit(t - 0.020)
    assert cal.result().offset_ms == pytest.approx(20.0)


def test_calibration_needs_enough_hits_and_ignores_far_ones():
    clicks = [i * 0.6 for i in range(16)]
    cal = Calibration(clicks)
    assert cal.add_hit(0.29) is None  # halfway between clicks: not counted
    for t in clicks[: MIN_HITS - 1]:
        cal.add_hit(t + 0.01)
    assert cal.result() is None
    cal.add_hit(clicks[MIN_HITS - 1] + 0.01)
    assert cal.result() is not None


def test_calibration_double_trigger_counts_once_and_outliers_do_not_skew():
    clicks = [i * 0.6 for i in range(16)]
    cal = Calibration(clicks)
    for t in clicks:
        cal.add_hit(t + 0.020)
        cal.add_hit(t + 0.060)  # a bounce on the same click
    cal.add_hit(clicks[3] + 0.2)  # a wild one; the closer hit is kept
    assert cal.count == 16
    assert cal.result().median_s == pytest.approx(0.020)
    assert cal.hit_clicks == set(range(16))


# -- saved settings --------------------------------------------------------


def test_saved_round_trip_and_reset(home):
    assert saved.load_saved() == {}
    path = saved.save({"audio": {"offset_ms": -23.0}})
    assert path == home / "drumgame" / "saved.json"
    saved.save({"midi_map": {"36": "kick"}})
    assert saved.load_saved() == {"audio": {"offset_ms": -23.0}, "midi_map": {"36": "kick"}}
    assert saved.reset() is True and saved.reset() is False
    assert saved.load_saved() == {}


def test_corrupt_saved_file_is_ignored(home):
    (home / "drumgame").mkdir()
    (home / "drumgame" / "saved.json").write_text("{not json")
    assert saved.load_saved() == {}
    assert load_config().midi_map[36] == "kick"  # still starts, on defaults


def test_learned_map_replaces_the_default_map(home):
    saved.save({"midi_map": {"60": "kick", "61": "snare"}})
    cfg = load_config()
    assert cfg.midi_map == {60: "kick", 61: "snare"}  # none of the draft defaults remain


def test_saved_offset_beats_config_file_and_cli_beats_both(home):
    (home / "drumgame").mkdir()
    (home / "drumgame" / "config.toml").write_text("[audio]\noffset_ms = 5\nbuffer = 512\n")
    assert load_config().audio_offset_s == pytest.approx(0.005)
    saved.save({"audio": {"offset_ms": -23.0}})
    cfg = load_config()
    assert cfg.audio_offset_s == pytest.approx(-0.023)
    assert cfg.audio_buffer == 512  # other config.toml values are untouched
    cfg = load_config(overrides={"audio": {"offset_ms": 0}})
    assert cfg.audio_offset_s == 0.0


def test_bad_learned_map_is_reported(home):
    saved.save({"midi_map": {"36": "cowbell"}})
    with pytest.raises(ValueError):
        load_config()


# -- screens, headless -----------------------------------------------------


@pytest.fixture
def pg(home, monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    import pygame

    pygame.mixer.pre_init(44100, -16, 2, 256)
    pygame.init()
    yield pygame
    pygame.quit()


@pytest.mark.parametrize("size", [(1280, 720), (640, 360), (1920, 1080)])
def test_learn_screen_runs_and_returns_the_map(pg, size):
    from drumgame.game.screens.learn import LearnScreen

    cfg = load_config()
    notes = queue.Queue()
    screen = LearnScreen(pg.display.set_mode(size), cfg, notes, "MIDI: test")
    for note in (36, 5):
        notes.put((note, 100 if note == 36 else 3))
    assert screen.run(max_seconds=0.05) is None  # timed out, nothing confirmed
    assert screen.session.notes["kick"] == [36] and "too soft" in screen.message
    screen.draw()
    # Enter on every pad, then Enter on the summary saves.
    for _ in range(len(LEARN_STEPS) + 1):
        pg.event.post(pg.event.Event(pg.KEYDOWN, key=pg.K_RETURN))
    assert screen.run(max_seconds=1.0) == {36: "kick"}


def test_learn_screen_escape_cancels(pg):
    from drumgame.game.screens.learn import LearnScreen

    screen = LearnScreen(pg.display.set_mode((1280, 720)), load_config(), queue.Queue(), "x")
    pg.event.post(pg.event.Event(pg.KEYDOWN, key=pg.K_ESCAPE))
    assert screen.run(max_seconds=1.0) is None


def test_calibrate_screen_measures_hits_against_its_clicks(pg):
    import time

    from drumgame.game.screens.calibrate import CalibrateScreen
    from drumgame.input.events import HitEvent
    from drumgame.input.keyboard_in import KeyboardInput

    cfg = load_config()
    hits = queue.Queue()
    screen = CalibrateScreen(pg.display.set_mode((1280, 720)), cfg, hits, KeyboardInput(hits, {}))
    screen.start()
    zero = time.perf_counter() + screen.lead_in  # perf time of the first measured click
    for t in screen.click_times:
        screen.calibration.add_hit(screen.clock.to_song_time(zero + t + 0.025))
    result = screen.calibration.result()
    assert result.count == 16 and result.offset_ms == pytest.approx(-25, abs=2)
    for now, finished in ((-1.0, False), (3.0, False), (99.0, True)):
        screen.finished = finished
        screen.draw(now)
    # run(): a real hit through the queue, stamped on the first measured click
    screen.start = lambda: None
    hits.put(HitEvent(zero, "snare", 100, "midi"))
    assert screen.run(max_seconds=0.05) is None
    assert screen.calibration.count == 16


def test_cli_reset_saved(home, capsys):
    from drumgame.main import main

    saved.save({"audio": {"offset_ms": 1.0}})
    assert main(["--reset-saved"]) == 0
    assert "removed" in capsys.readouterr().out
    assert not (home / "drumgame" / "saved.json").exists()
    assert json.dumps(saved.load_saved()) == "{}"
