from array import array

import pytest

from drumgame.chart.demo import rock_beat
from drumgame.chart.model import Chart, Note, TempoEvent, TimeSigEvent
from drumgame.chart.timing import chart_tempo_map
from drumgame.config import load_config
from drumgame.game.clock import SongClock
from drumgame.game.metronome import click_schedule, render_click_track
from drumgame.lanes import LANES


class FakeTime:
    def __init__(self):
        self.t = 50.0

    def __call__(self):
        return self.t


def test_clock_lead_in_and_hit_conversion():
    ft = FakeTime()
    clock = SongClock(time_fn=ft)
    clock.start(-2.0)
    assert clock.now() == pytest.approx(-2.0)
    ft.t += 3.0
    assert clock.now() == pytest.approx(1.0)
    assert clock.to_song_time(ft.t - 0.25) == pytest.approx(0.75)


def test_clock_offset():
    ft = FakeTime()
    clock = SongClock(offset_s=0.040, time_fn=ft)
    clock.start()
    ft.t += 1.0
    assert clock.now() == pytest.approx(1.040)


def test_clock_pause_resume():
    ft = FakeTime()
    clock = SongClock(time_fn=ft)
    clock.start()
    ft.t += 1.0
    clock.pause()
    ft.t += 5.0
    assert clock.paused and clock.now() == pytest.approx(1.0)
    clock.resume()
    ft.t += 0.5
    assert clock.running and clock.now() == pytest.approx(1.5)


def test_clock_must_be_started():
    with pytest.raises(RuntimeError):
        SongClock().now()


def test_click_schedule_count_in_and_accents():
    chart = Chart(
        tempos=[TempoEvent(0, 120)],
        time_signatures=[TimeSigEvent(0, 3, 4)],
        notes=[Note(1440, "kick")],
    )
    lead_in, clicks = click_schedule(chart, chart_tempo_map(chart))
    assert lead_in == pytest.approx(2.0)
    assert [t for t, _ in clicks] == pytest.approx([-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5])
    assert [a for _, a in clicks] == [True, False, False, False, True, False, False, True]


def test_render_click_track_places_clicks_sample_accurately():
    rate = 8000
    pcm = array("h", render_click_track([(-1.0, True), (0.0, False), (0.5, False)], 1.0, rate, 2))
    left, right = pcm[0::2], pcm[1::2]
    assert left == right
    assert len(left) == int((0.5 + 1.0 + 0.5) * rate)

    def loud(start_s):
        s = int(start_s * rate)
        return max(abs(v) for v in left[s : s + 40]) > 3000

    def silent(start_s, end_s):
        return not any(left[int(start_s * rate) : int(end_s * rate)])

    assert loud(0.0) and loud(1.0) and loud(1.5)
    assert silent(0.05, 1.0) and silent(1.05, 1.5)
    assert left[rate - 1] == 0 and any(left[rate : rate + 3])  # onset on the exact sample


def test_render_click_track_mono_and_empty():
    assert render_click_track([], 0.0) == b""
    mono = render_click_track([(0.0, True)], 0.0, 8000, 1)
    assert len(mono) == 2 * int(0.5 * 8000)


def test_default_config_loads(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = load_config()
    assert cfg.midi_channel is None and cfg.debounce_s == pytest.approx(0.030)
    assert cfg.windows.perfect_s == pytest.approx(0.050)
    assert cfg.midi_map[36] == "kick" and cfg.midi_map[53] == "ride"
    assert set(cfg.midi_map.values()) == set(LANES)
    assert set(cfg.keyboard.values()) == set(LANES)
    assert cfg.layout.name == "full"


def test_user_config_overrides_only_what_it_sets(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "drumgame").mkdir()
    (tmp_path / "drumgame" / "config.toml").write_text(
        '[input]\nmidi_channel = 10\n[midi_map]\n36 = ""\n60 = "kick"\n'
        '[video]\nlayout = "compact"\n'
    )
    cfg = load_config()
    assert cfg.midi_channel == 9
    assert 36 not in cfg.midi_map and cfg.midi_map[60] == "kick" and cfg.midi_map[38] == "snare"
    assert cfg.layout.name == "compact" and cfg.debounce_s == pytest.approx(0.030)


def test_bad_config_rejected(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text('[input.keyboard]\nx = "cowbell"\n')
    with pytest.raises(ValueError):
        load_config(bad)


def test_play_screen_headless_smoke(monkeypatch, tmp_path):
    """Runs the real play loop for a moment with dummy video/audio drivers."""
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    import queue
    import time

    import pygame

    from drumgame.game.screens.play import PlayScreen
    from drumgame.input.events import HitEvent
    from drumgame.input.keyboard_in import KeyboardInput, keymap_from_names

    cfg = load_config()
    pygame.mixer.pre_init(cfg.sample_rate, -16, 2, cfg.audio_buffer)
    pygame.init()
    try:
        screen = pygame.display.set_mode((cfg.width, cfg.height))
        hits = queue.Queue()
        keymap = keymap_from_names(cfg.keyboard)
        assert keymap[pygame.K_SPACE] == "kick" and keymap[pygame.K_SEMICOLON] == "ride"
        keyboard = KeyboardInput(hits, keymap)
        play = PlayScreen(screen, rock_beat(bars=2, bpm=240), cfg, hits, keyboard, "test")
        play.start()
        # A kick exactly on the first note, as if stamped by the MIDI thread.
        hits.put(HitEvent(time.perf_counter() + play.lead_in, "kick", 100, "midi"))
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_d))
        orig_start = play.start
        play.start = lambda: None  # run() would otherwise restart and drop the queued hits
        stats = play.run(max_seconds=0.3)
        play.start = orig_start
        assert stats.total == len(play.notes) > 0
        assert stats.perfect == 1 and stats.stray == 1
    finally:
        pygame.quit()


def test_window_size_and_scroll_are_validated():
    from drumgame.config import Config, default_dict

    for patch in ({"width": 800}, {"height": 480}, {"scroll_seconds": 0}):
        data = default_dict()
        data["video"].update(patch)
        with pytest.raises(ValueError):
            Config.from_dict(data)
