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
MAP_H = 44  # song map height
MAP_BIN = 6  # width of one song-map column, including its 2 px gap
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
            hw_rect, self.layout, self.notes, config.scroll_seconds, self.text, key_labels,
            config.reduce_motion,
        )  # fmt: skip
        self.gauge_rect = pygame.Rect(MARGIN, MARGIN, GAUGE_W, self.highway.hit_y - MARGIN)
        px = hw_rect.right + MARGIN
        self.panel = pygame.Rect(px, MARGIN, min(PANEL_MAX_W, w - MARGIN - px), h - 2 * MARGIN)
        self._map_ahead, self._map_played = self._make_song_map(self.panel.width)
        self._shade = pygame.Surface(hw_rect.size, pygame.SRCALPHA)
        self._shade.fill((*ui.BG, 185))
        # Backdrop for the count-in number, so notes scrolling past stay out of it.
        self._count_disc = pygame.Surface((190, 190), pygame.SRCALPHA)
        pygame.draw.circle(self._count_disc, (*ui.BG, 215), (95, 95), 95)

        self.clock = SongClock(config.audio_offset_s)
        self.judge = Judge(self.notes, config.windows)
        self.deltas: deque[float] = deque(maxlen=TIMING_HISTORY)
        self.finished = False

    def _make_song_map(self, width: int) -> tuple[pygame.Surface, pygame.Surface]:
        """The song as a strip of note density, with section starts marked.

        Returns the "still ahead" and "already played" renderings; drawing
        blends them at the playhead.
        """
        bins = max(1, width // MAP_BIN)
        counts = [0] * bins
        span = self.last_note_time or 1.0
        for n in self.notes:
            counts[min(bins - 1, int(n.time / span * bins))] += 1
        peak = max(counts) or 1
        out = []
        for color in (ui.mix(ui.TRACK, ui.TEXT_DIM, 0.45), ui.ACCENT):
            surf = pygame.Surface((width, MAP_H))
            surf.fill(ui.BG)
            for i, c in enumerate(counts):
                h = max(2, round((MAP_H - 8) * c / peak)) if c else 2
                pygame.draw.rect(
                    surf, color if c else ui.TRACK,
                    pygame.Rect(i * MAP_BIN, MAP_H - h, MAP_BIN - 2, h), border_radius=1,
                )  # fmt: skip
            for t in self.section_times:
                x = round(min(max(t / span, 0.0), 1.0) * (width - 2))
                pygame.draw.rect(surf, ui.TEXT_DIM, pygame.Rect(x, 0, 2, 5))
            out.append(surf.convert())
        return out[0], out[1]

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
                    # Esc never throws a run away in one press: it pauses first.
                    if self.finished or self.clock.paused:
                        running = False
                    else:
                        self.toggle_pause()
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
        # The combo number would sit right under the pause and results overlays.
        combo = 0 if self.finished or self.clock.paused else self.judge.stats.combo
        hw.draw(screen, now, wall, self.judge.results, self.grid, combo)
        self._draw_gauge()
        self._draw_panel(now)
        if self.finished:
            self._draw_results()
        elif self.clock.paused:
            self._draw_paused()
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
        x, y = p.left, p.top

        # Score, then accuracy and best combo as one quiet line beneath it.
        score = str(stats.score).rjust(7, "0")
        lead = len(score) - len(str(stats.score)) if stats.score else len(score) - 1
        text.tabular(screen, score, ui.SCORE, (x - 2, y - 6), faint=lead)
        y += 68
        judged = stats.perfect + stats.good + stats.miss
        accuracy = f"{stats.accuracy * 100:.1f}%" if judged else "--"
        w = text.tabular(screen, accuracy, ui.BODY, (x, y))
        w += text.draw(screen, " accuracy", ui.BODY, (x + w, y), ui.TEXT_DIM).width
        text.draw(screen, "max combo", ui.BODY, (p.right, y), ui.TEXT_DIM, "topright")
        label_w = text.font(ui.BODY).size("max combo ")[0]
        text.tabular(screen, str(stats.max_combo), ui.BODY, (p.right - label_w, y), align="right")

        # The song: what it is, where its busy parts are, where we are in it.
        y += 60
        text.draw(screen, text.fit(self.chart.title, ui.TITLE, p.width), ui.TITLE, (x, y))
        y += 30
        if self.chart.artist:
            text.draw(
                screen, text.fit(self.chart.artist, ui.CAPTION, p.width), ui.CAPTION, (x, y),
                ui.TEXT_DIM,
            )  # fmt: skip
        y += 30
        t = max(now, 0.0)
        progress = min(t / self.last_note_time, 1.0) if self.last_note_time > 0 else 1.0
        head = round(progress * (p.width - 2))
        screen.blit(self._map_ahead, (x, y))
        screen.blit(self._map_played, (x, y), pygame.Rect(0, 0, head, MAP_H))
        pygame.draw.rect(screen, ui.TEXT, pygame.Rect(x + head, y, 2, MAP_H))
        y += MAP_H + 8
        bar_no = min(max(bisect_right(self.bar_times, t), 1), max(len(self.bar_times), 1))
        bpm = self.tempo_bpms[max(bisect_right(self.tempo_times, t) - 1, 0)]
        w = text.tabular(screen, f"Bar {bar_no}", ui.CAPTION, (x, y))
        text.tabular(screen, f"{bpm:.0f} BPM", ui.CAPTION, (p.right, y), ui.TEXT_DIM, "right")
        si = bisect_right(self.section_times, t) - 1
        if si >= 0:
            name = text.fit(self.chart.sections[si].name, ui.CAPTION, p.width - w - 130)
            text.draw(screen, name, ui.CAPTION, (x + w + 16, y), ui.ACCENT)

        # Judgement tallies: the count sits right beside its name.
        y += 52
        rows = [
            ("Perfect", stats.perfect, Judgement.PERFECT),
            ("Good", stats.good, Judgement.GOOD),
            ("Miss", stats.miss, Judgement.MISS),
            ("Stray", stats.stray, Judgement.STRAY),
        ]
        for name, count, judgement in rows:
            text.draw(screen, name, ui.BODY, (x, y), ui.JUDGE_COLORS[judgement])
            text.tabular(screen, str(count), ui.BODY, (x + 150, y), align="right")
            y += 28

        self._draw_timing(pygame.Rect(x, y + 24, p.width, 70))

        # Input status and the controls that apply right now, bottom-aligned.
        by = p.bottom - 50
        if self.config.metronome and self.click_sound is None:
            text.draw(
                screen, "No audio device found, so the metronome is silent", ui.CAPTION,
                (x, by - 28), ui.WARN,
            )  # fmt: skip
        dot = ui.OK if self.midi_connected else ui.WARN
        pygame.draw.circle(screen, dot, (x + 6, by + 9), 5)
        text.draw(
            screen, text.fit(self.midi_status, ui.CAPTION + 2, p.width - 22), ui.CAPTION + 2,
            (x + 20, by),
        )  # fmt: skip
        if self.finished:
            hints = "Backspace retry    Esc quit"
        elif self.clock.paused:
            hints = "Enter resume    Backspace restart    Esc quit"
        else:
            hints = "Esc pause    Backspace restart"
        text.draw(screen, hints, ui.CAPTION, (x, by + 30), ui.TEXT_DIM)

    def _draw_timing(self, r: pygame.Rect) -> None:
        """Recent hits on an early-to-late scale, with their average in words."""
        screen, text, win = self.screen, self.text, self.config.windows
        if self.deltas:
            avg = sum(self.deltas) / len(self.deltas) * 1000
            side = "late" if avg > 0 else "early"
            label = "On the beat" if abs(avg) < 5 else f"{abs(avg):.0f} ms {side} on average"
            text.tabular(screen, label, ui.CAPTION, r.topleft)
        else:
            text.draw(screen, "Timing appears here once you hit a note", ui.CAPTION, r.topleft,
                      ui.TEXT_DIM)  # fmt: skip
        track = pygame.Rect(r.left, r.top + 26, r.width, 18)
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
        text.draw(screen, "early", ui.CAPTION, (track.left, track.bottom + 4), ui.TEXT_DIM)
        text.draw(
            screen, "late", ui.CAPTION, (track.right, track.bottom + 4), ui.TEXT_DIM, "topright"
        )

    def _draw_count_in(self, now: float) -> None:
        """Count the clicks as they sound: 1, 2, 3, 4."""
        counted = sum(1 for t in self.count_in if t <= now + 0.02)
        hw = self.highway
        center = (hw.rect.centerx, round(hw.rect.top + (hw.hit_y - hw.rect.top) * 0.36))
        if counted:
            self.screen.blit(self._count_disc, self._count_disc.get_rect(center=center))
            self.text.draw(self.screen, str(counted), ui.DISPLAY, center, anchor="center")
        else:
            self.text.draw(self.screen, "Get ready", ui.VALUE, center, anchor="center")

    def _draw_paused(self) -> None:
        hw = self.highway
        self.screen.blit(self._shade, hw.rect.topleft)
        cx, cy = hw.rect.centerx, hw.rect.top + (hw.hit_y - hw.rect.top) * 0.4
        self.text.draw(self.screen, "Paused", ui.SCORE, (cx, cy), anchor="center")
        self.text.draw(
            self.screen, "Enter resume    Backspace restart    Esc quit", ui.CAPTION,
            (cx, cy + 56), ui.TEXT_DIM, "center",
        )  # fmt: skip

    def _draw_results(self) -> None:
        screen, text, stats, hw = self.screen, self.text, self.judge.stats, self.highway
        screen.blit(self._shade, hw.rect.topleft)
        card = pygame.Rect(0, 0, min(460, hw.rect.width - 40), 300)
        card.center = (hw.rect.centerx, hw.rect.top + (hw.hit_y - hw.rect.top) // 2)
        ui.panel(screen, card)
        cx = card.centerx
        if stats.total == 0:
            # Nothing was playable, so a grade would be a lie.
            text.draw(screen, "No notes to play", ui.VALUE, (cx, card.top + 110), anchor="center")
            for i, line in enumerate(
                ("This chart has no notes in the lanes shown.", "Check the import warnings.")
            ):
                text.draw(
                    screen, line, ui.CAPTION, (cx, card.top + 160 + i * 26), ui.TEXT_DIM, "center"
                )
        else:
            letter = grade(stats.accuracy)
            text.draw(screen, letter, 190, (cx, card.top + 92), GRADE_COLORS[letter], "center")
            text.draw(
                screen, f"{stats.accuracy * 100:.1f}% accuracy", ui.TITLE, (cx, card.top + 178),
                anchor="center",
            )  # fmt: skip
            summary = f"{stats.score} points    max combo {stats.max_combo}    {stats.miss} missed"
            text.draw(
                screen, text.fit(summary, ui.CAPTION + 2, card.width - 32), ui.CAPTION + 2,
                (cx, card.top + 218), ui.TEXT_DIM, "center",
            )  # fmt: skip
        text.draw(
            screen, "Backspace retry    Esc quit", ui.CAPTION, (cx, card.bottom - 28), ui.TEXT_DIM,
            "center",
        )  # fmt: skip
