"""The play screen: runs one chart from count-in to results."""

from __future__ import annotations

import queue
import time
from bisect import bisect_right
from collections import deque

import pygame

from drumgame.chart.model import Chart
from drumgame.chart.simplify import collapse_lanes
from drumgame.chart.timing import beat_grid, chart_tempo_map, resolve_notes
from drumgame.config import Config
from drumgame.game import ui
from drumgame.game.clock import SongClock
from drumgame.game.highway import Highway
from drumgame.game.judge import Judge, Judgement, Stats, grade
from drumgame.game.metronome import click_schedule, render_click_track
from drumgame.input.events import HitEvent
from drumgame.input.keyboard_in import KeyboardInput

END_PAD_S = 2.0
MARGIN = 32
GAUGE_W = 16
GAUGE_CELLS = 24
PANEL_MIN_W = 400
PANEL_MAX_W = 470
MAX_LANE_W = 96
TIMING_HISTORY = 24
GRADE_COLORS = {"S": ui.JUDGE_COLORS[Judgement.PERFECT], "A": ui.OK, "B": ui.ACCENT,
                "C": ui.WARN, "D": ui.JUDGE_COLORS[Judgement.MISS]}  # fmt: skip


class PlayScreen:
    def __init__(
        self,
        screen: pygame.Surface,
        chart: Chart,
        config: Config,
        hits: "queue.Queue[HitEvent]",
        keyboard: KeyboardInput,
        midi_status: str,
        midi_connected: bool = False,
    ) -> None:
        self.screen = screen
        self.chart = chart
        self.config = config
        self.hits = hits
        self.keyboard = keyboard
        self.midi_status = midi_status
        self.midi_connected = midi_connected
        self.layout = config.layout
        self.text = ui.Text()

        tempo_map = chart_tempo_map(chart)
        self.notes = resolve_notes(collapse_lanes(chart.notes, self.layout), tempo_map)
        self.last_note_time = self.notes[-1].time if self.notes else 0.0
        self.end_time = self.last_note_time + END_PAD_S
        beats = beat_grid(chart.resolution, chart.time_signatures, chart.end_tick)
        self.grid = [(tempo_map.tick_to_seconds(b.tick), b.beat == 0) for b in beats]
        self.bar_times = [t for t, is_bar in self.grid if is_bar]
        self.tempo_times = [tempo_map.tick_to_seconds(t.tick) for t in chart.tempos]
        self.tempo_bpms = [t.bpm for t in chart.tempos]
        self.section_times = [tempo_map.tick_to_seconds(s.tick) for s in chart.sections]
        self.lead_in, clicks = click_schedule(chart, tempo_map)
        self.count_in = [t for t, _ in clicks if t < 0]
        self.click_sound = self._make_click_sound(clicks)
        self.click_channel: pygame.mixer.Channel | None = None

        key_labels: dict[str, str] = {}
        for key_name, lane in config.keyboard.items():
            shown = self.layout.resolve(lane)
            if shown is not None:
                key_labels.setdefault(shown, key_name.upper())

        # Left to right: gauge, highway, info panel.
        w, h = screen.get_size()
        n = len(self.layout.lanes)
        hw_left = MARGIN + GAUGE_W + 12
        lane_w = min(MAX_LANE_W, (w - hw_left - MARGIN - PANEL_MIN_W - MARGIN) // n)
        hw_rect = pygame.Rect(hw_left, 0, lane_w * n, h)
        self.highway = Highway(
            hw_rect, self.layout, self.notes, config.scroll_seconds, self.text, key_labels
        )
        self.gauge_rect = pygame.Rect(MARGIN, MARGIN, GAUGE_W, self.highway.hit_y - MARGIN)
        px = hw_rect.right + MARGIN
        self.panel = pygame.Rect(px, MARGIN, min(PANEL_MAX_W, w - MARGIN - px), h - 2 * MARGIN)
        self._shade = pygame.Surface(hw_rect.size, pygame.SRCALPHA)
        self._shade.fill((*ui.BG, 185))
        # Backdrop for the count-in number, so notes scrolling past stay out of it.
        self._count_disc = pygame.Surface((190, 190), pygame.SRCALPHA)
        pygame.draw.circle(self._count_disc, (*ui.BG, 215), (95, 95), 95)

        self.clock = SongClock(config.audio_offset_s)
        self.judge = Judge(self.notes, config.windows)
        self.deltas: deque[float] = deque(maxlen=TIMING_HISTORY)
        self.finished = False

    def _make_click_sound(self, clicks) -> "pygame.mixer.Sound | None":
        if not self.config.metronome:
            return None
        init = pygame.mixer.get_init()
        if not init or init[1] != -16:
            return None  # no audio device, or an unexpected sample format
        rate, _, channels = init
        return pygame.mixer.Sound(
            buffer=render_click_track(clicks, self.lead_in, rate, channels)
        )

    def start(self) -> None:
        while True:  # drop hits made before the song started
            try:
                self.hits.get_nowait()
            except queue.Empty:
                break
        self.judge = Judge(self.notes, self.config.windows)
        self.deltas.clear()
        self.finished = False
        if self.click_channel is not None:
            self.click_channel.stop()
        if self.click_sound is not None:
            self.click_channel = self.click_sound.play()
        # Anchor immediately after starting audio so the two stay aligned.
        self.clock.start(-self.lead_in)

    def toggle_pause(self) -> None:
        if self.finished:
            return
        if self.clock.paused:
            self.clock.resume()
            if self.click_channel is not None:
                self.click_channel.unpause()
        else:
            self.clock.pause()
            if self.click_channel is not None:
                self.click_channel.pause()

    def run(self, max_seconds: float | None = None) -> Stats:
        """Run until the player quits. `max_seconds` caps wall time (for tests)."""
        frame_clock = pygame.time.Clock()
        started = time.perf_counter()
        self.start()
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                    self.toggle_pause()
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_BACKSPACE:
                    self.start()
                else:
                    self.keyboard.handle_event(event)

            wall = time.perf_counter()
            self._drain_hits(wall)
            now = self.clock.now()
            for res in self.judge.update(now):
                self.highway.register(res.lane, res.judgement, wall)
            if not self.finished and now >= self.end_time:
                self.finished = True

            self.draw(now, wall)
            pygame.display.flip()
            frame_clock.tick(self.config.fps)
            if max_seconds is not None and wall - started >= max_seconds:
                running = False
        if self.click_channel is not None:
            self.click_channel.stop()
        return self.judge.stats

    def _drain_hits(self, wall: float) -> None:
        while True:
            try:
                hit = self.hits.get_nowait()
            except queue.Empty:
                return
            lane = self.layout.resolve(hit.lane)
            if lane is None:
                continue
            if self.clock.paused or self.finished:
                self.highway.register(lane, Judgement.STRAY, wall)  # pads still light up
                continue
            res = self.judge.hit(lane, self.clock.to_song_time(hit.time))
            self.highway.register(lane, res.judgement, wall, res.delta_s)
            if res.delta_s is not None:
                self.deltas.append(res.delta_s)

    # -- drawing -------------------------------------------------------------

    def draw(self, now: float, wall: float) -> None:
        screen, hw = self.screen, self.highway
        screen.fill(ui.BG)
        combo = 0 if self.finished else self.judge.stats.combo
        hw.draw(screen, now, wall, self.judge.results, self.grid, combo)
        self._draw_gauge()
        self._draw_panel(now)
        if self.finished:
            self._draw_results()
        elif self.clock.paused:
            self._draw_overlay("PAUSED", "Enter to resume")
        elif now < 0:
            self._draw_count_in(now)

    def _draw_gauge(self) -> None:
        """Segmented meter of recent form, lit from the bottom."""
        r = self.gauge_rect
        cell_h = r.height / GAUGE_CELLS
        lit = round(self.judge.gauge.value * GAUGE_CELLS)
        for i in range(GAUGE_CELLS):
            cell = pygame.Rect(
                r.left, round(r.bottom - (i + 1) * cell_h) + 1, r.width, round(cell_h) - 2
            )
            if i >= lit:
                color = ui.TRACK
            elif i >= GAUGE_CELLS * 0.8:
                color = ui.JUDGE_COLORS[Judgement.PERFECT]
            else:
                color = ui.OK
            pygame.draw.rect(self.screen, color, cell, border_radius=2)

    def _draw_panel(self, now: float) -> None:
        screen, text, stats, p = self.screen, self.text, self.judge.stats, self.panel
        x, right, y = p.left, p.right, p.top

        text.draw(screen, "SCORE", 20, (x, y), ui.TEXT_DIM)
        text.digits(screen, stats.score, 7, 84, (x - 2, y + 20))

        y += 96
        col = p.width // 2
        text.draw(screen, "ACCURACY", 20, (x, y), ui.TEXT_DIM)
        judged = stats.perfect + stats.good + stats.miss
        accuracy = f"{stats.accuracy * 100:.1f}%" if judged else "--"
        text.draw(screen, accuracy, 40, (x, y + 20))
        text.draw(screen, "MAX COMBO", 20, (x + col, y), ui.TEXT_DIM)
        text.draw(screen, str(stats.max_combo), 40, (x + col, y + 20))

        # Song card: what is playing and how far along it is.
        y += 74
        card = pygame.Rect(x, y, p.width, 138)
        ui.panel(screen, card)
        inner = card.inflate(-36, 0)
        text.draw(screen, text.fit(self.chart.title, 34, inner.width), 34, (inner.left, y + 16))
        if self.chart.artist:
            text.draw(
                screen, text.fit(self.chart.artist, 22, inner.width), 22, (inner.left, y + 46),
                ui.TEXT_DIM,
            )  # fmt: skip
        t = max(now, 0.0)
        bar_no = min(max(bisect_right(self.bar_times, t), 1), max(len(self.bar_times), 1))
        bpm = self.tempo_bpms[max(bisect_right(self.tempo_times, t) - 1, 0)]
        text.draw(screen, f"BAR {bar_no}", 22, (inner.left, y + 82), ui.TEXT)
        text.draw(screen, f"{bpm:.0f} BPM", 22, (inner.right, y + 82), ui.TEXT_DIM, "topright")
        si = bisect_right(self.section_times, t) - 1
        if si >= 0:
            name = text.fit(self.chart.sections[si].name.upper(), 22, inner.width - 200)
            text.draw(screen, name, 22, (inner.centerx, y + 82), ui.ACCENT, "midtop")
        progress = t / self.last_note_time if self.last_note_time > 0 else 1.0
        ui.bar(screen, pygame.Rect(inner.left, y + 112, inner.width, 6), progress, ui.ACCENT)

        # Judgement counts, each with its share of the chart as a bar.
        y += 138 + 26
        rows = [
            ("PERFECT", stats.perfect, Judgement.PERFECT),
            ("GOOD", stats.good, Judgement.GOOD),
            ("MISS", stats.miss, Judgement.MISS),
            ("STRAY", stats.stray, Judgement.STRAY),
        ]
        total = max(stats.total, 1)
        for name, count, judgement in rows:
            color = ui.JUDGE_COLORS[judgement]
            text.draw(screen, name, 22, (x, y), color)
            ui.bar(screen, pygame.Rect(x + 96, y + 4, p.width - 96 - 64, 8), count / total, color)
            text.draw(screen, str(count), 24, (right, y - 2), ui.TEXT, "topright")
            y += 30

        self._draw_timing(pygame.Rect(x, y + 18, p.width, 64))

        # Input status and controls, bottom-aligned.
        by = p.bottom - 44
        if self.config.metronome and self.click_sound is None:
            text.draw(screen, "No audio device: metronome is off", 20, (x, by - 26), ui.WARN)
        dot = ui.OK if self.midi_connected else ui.WARN
        pygame.draw.circle(screen, dot, (x + 6, by + 8), 5)
        text.draw(screen, text.fit(self.midi_status, 22, p.width - 22), 22, (x + 20, by))
        text.draw(
            screen, "Esc quit    Enter pause    Backspace restart", 20, (x, by + 26), ui.TEXT_DIM
        )

    def _draw_timing(self, r: pygame.Rect) -> None:
        """Recent hits on an early-to-late scale, with their average."""
        screen, text, win = self.screen, self.text, self.config.windows
        text.draw(screen, "TIMING", 20, r.topleft, ui.TEXT_DIM)
        if self.deltas:
            avg = sum(self.deltas) / len(self.deltas) * 1000
            side = "late" if avg > 0 else "early"
            label = "on the beat" if abs(avg) < 5 else f"{abs(avg):.0f} ms {side} on average"
            text.draw(screen, label, 20, r.topright, ui.TEXT, "topright")
        track = pygame.Rect(r.left, r.top + 24, r.width, 18)
        pygame.draw.rect(screen, ui.TRACK, track, border_radius=4)
        half = track.width / 2
        perfect_w = round(half * win.perfect_s / win.good_s)
        zone = pygame.Rect(track.centerx - perfect_w, track.top, perfect_w * 2, track.height)
        pygame.draw.rect(screen, ui.mix(ui.TRACK, ui.JUDGE_COLORS[Judgement.PERFECT], 0.16), zone)
        pygame.draw.line(
            screen, ui.TEXT_DIM, (track.centerx, track.top - 3), (track.centerx, track.bottom + 2)
        )
        count = len(self.deltas)
        for i, delta in enumerate(self.deltas):  # oldest first, so the newest sits on top
            k = max(-1.0, min(1.0, delta / win.good_s))
            tx = round(track.centerx + k * (half - 2))
            judgement = Judgement.PERFECT if abs(delta) <= win.perfect_s else Judgement.GOOD
            age = (count - 1 - i) / TIMING_HISTORY
            color = ui.mix(ui.JUDGE_COLORS[judgement], ui.TRACK, 0.75 * age)
            pygame.draw.line(screen, color, (tx, track.top + 2), (tx, track.bottom - 3), 3)
        text.draw(screen, "EARLY", 18, (track.left, track.bottom + 5), ui.TEXT_DIM)
        text.draw(screen, "LATE", 18, (track.right, track.bottom + 5), ui.TEXT_DIM, "topright")

    def _draw_count_in(self, now: float) -> None:
        """Count the clicks as they sound: 1, 2, 3, 4."""
        counted = sum(1 for t in self.count_in if t <= now + 0.02)
        hw = self.highway
        center = (hw.rect.centerx, round(hw.rect.top + (hw.hit_y - hw.rect.top) * 0.36))
        if counted:
            self.screen.blit(self._count_disc, self._count_disc.get_rect(center=center))
            self.text.draw(self.screen, str(counted), 150, center, anchor="center")
        else:
            self.text.draw(self.screen, "GET READY", 64, center, anchor="center")

    def _draw_overlay(self, title: str, hint: str) -> None:
        hw = self.highway
        self.screen.blit(self._shade, hw.rect.topleft)
        cy = hw.rect.top + (hw.hit_y - hw.rect.top) * 0.4
        self.text.draw(self.screen, title, 84, (hw.rect.centerx, cy), anchor="center")
        self.text.draw(
            self.screen, hint, 24, (hw.rect.centerx, cy + 52), ui.TEXT_DIM, anchor="center"
        )

    def _draw_results(self) -> None:
        screen, text, stats, hw = self.screen, self.text, self.judge.stats, self.highway
        screen.blit(self._shade, hw.rect.topleft)
        card = pygame.Rect(0, 0, min(440, hw.rect.width - 40), 330)
        card.center = (hw.rect.centerx, hw.rect.top + (hw.hit_y - hw.rect.top) // 2)
        ui.panel(screen, card)
        cx = card.centerx
        letter = grade(stats.accuracy)
        text.draw(screen, "FINISHED", 22, (cx, card.top + 28), ui.TEXT_DIM, "center")
        text.draw(screen, letter, 190, (cx, card.top + 112), GRADE_COLORS[letter], "center")
        text.draw(screen, f"{stats.accuracy * 100:.1f}%", 48, (cx, card.top + 196), anchor="center")
        cols = [("SCORE", str(stats.score)), ("MAX COMBO", str(stats.max_combo)),
                ("MISSED", str(stats.miss))]  # fmt: skip
        step = card.width / len(cols)
        for i, (label, value) in enumerate(cols):
            colx = card.left + step * (i + 0.5)
            text.draw(screen, label, 18, (colx, card.top + 242), ui.TEXT_DIM, "center")
            text.draw(screen, value, 32, (colx, card.top + 266), anchor="center")
        text.draw(
            screen, "Backspace to retry    Esc to quit", 20, (cx, card.bottom - 22), ui.TEXT_DIM,
            "center",
        )  # fmt: skip
