"""The play screen: runs one chart from count-in to results."""

from __future__ import annotations

import queue
import time

import pygame

from drumgame.chart.model import Chart
from drumgame.chart.simplify import collapse_lanes
from drumgame.chart.timing import beat_grid, chart_tempo_map, resolve_notes
from drumgame.config import Config
from drumgame.game.clock import SongClock
from drumgame.game.highway import BG, Highway
from drumgame.game.judge import Judge, JudgeResult, Judgement, Stats
from drumgame.game.metronome import click_schedule, render_click_track
from drumgame.input.events import HitEvent
from drumgame.input.keyboard_in import KeyboardInput

JUDGE_COLORS = {
    Judgement.PERFECT: (255, 225, 90),
    Judgement.GOOD: (110, 220, 130),
    Judgement.MISS: (235, 80, 80),
    Judgement.STRAY: (130, 130, 150),
}
END_PAD_S = 2.0
FEEDBACK_S = 0.5
DIM = (140, 140, 160)
DIMMER = (100, 100, 120)


class PlayScreen:
    def __init__(
        self,
        screen: pygame.Surface,
        chart: Chart,
        config: Config,
        hits: "queue.Queue[HitEvent]",
        keyboard: KeyboardInput,
        midi_status: str,
    ) -> None:
        self.screen = screen
        self.chart = chart
        self.config = config
        self.hits = hits
        self.keyboard = keyboard
        self.midi_status = midi_status
        self.layout = config.layout

        tempo_map = chart_tempo_map(chart)
        self.notes = resolve_notes(collapse_lanes(chart.notes, self.layout), tempo_map)
        self.end_time = (self.notes[-1].time if self.notes else 0.0) + END_PAD_S
        self.grid = [
            (tempo_map.tick_to_seconds(b.tick), b.beat == 0)
            for b in beat_grid(chart.resolution, chart.time_signatures, chart.end_tick)
        ]
        self.lead_in, clicks = click_schedule(chart, tempo_map)
        self.click_sound = self._make_click_sound(clicks)
        self.click_channel: pygame.mixer.Channel | None = None

        key_labels: dict[str, str] = {}
        for key_name, lane in config.keyboard.items():
            shown = self.layout.resolve(lane)
            if shown is not None:
                key_labels.setdefault(shown, key_name.upper())
        lane_w = min(84, (screen.get_width() - 420) // len(self.layout.lanes))
        width = lane_w * len(self.layout.lanes)
        rect = pygame.Rect((screen.get_width() - width) // 2, 0, width, screen.get_height())
        self.highway = Highway(rect, self.layout, self.notes, config.scroll_seconds, key_labels)

        self.font = pygame.font.Font(None, 28)
        self.big = pygame.font.Font(None, 54)
        self.small = pygame.font.Font(None, 22)
        self.clock = SongClock(config.audio_offset_s)
        self.judge = Judge(self.notes, config.windows)
        self.feedback: tuple[JudgeResult, float] | None = None
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
        self.feedback = None
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
                self.feedback = (res, wall)
            if not self.finished and now >= self.end_time:
                self.finished = True

            self._draw(now, wall)
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
            self.highway.flash(lane, wall)
            if self.clock.paused or self.finished:
                continue
            res = self.judge.hit(lane, self.clock.to_song_time(hit.time))
            self.feedback = (res, wall)

    def _text(self, text: str, pos, color=(215, 215, 228), font=None, center=False) -> None:
        surf = (font or self.font).render(text, True, color)
        rect = surf.get_rect(center=pos) if center else surf.get_rect(topleft=pos)
        self.screen.blit(surf, rect)

    @staticmethod
    def _fit(text: str, font: pygame.font.Font, width: int) -> str:
        """Shorten text with an ellipsis until it fits in `width` pixels."""
        if font.size(text)[0] <= width:
            return text
        while len(text) > 1 and font.size(text + "...")[0] > width:
            text = text[:-1]
        return text + "..."

    def _draw(self, now: float, wall: float) -> None:
        screen, stats, hw = self.screen, self.judge.stats, self.highway
        screen.fill(BG)
        hw.draw(screen, now, wall, self.judge.results, self.grid)
        cx = hw.rect.centerx

        left, side_w = 24, hw.rect.left - 48
        bottom = screen.get_height()
        self._text(self._fit(self.chart.title, self.font, side_w), (left, 24))
        if self.chart.artist:
            self._text(
                self._fit(self.chart.artist, self.small, side_w), (left, 54), DIM, self.small
            )
        lines = [(self.midi_status, DIM), ("Esc quit", DIMMER), ("Enter pause", DIMMER),
                 ("Backspace restart", DIMMER)]  # fmt: skip
        if self.config.metronome and self.click_sound is None:
            lines.insert(0, ("no audio: metronome off", (200, 120, 90)))
        for i, (line, color) in enumerate(reversed(lines)):
            self._text(
                self._fit(line, self.small, side_w), (left, bottom - 40 - i * 24), color, self.small
            )

        right = hw.rect.right + 28
        self._text(f"{stats.score}", (right, 24), font=self.big)
        self._text(f"combo {stats.combo}   max {stats.max_combo}", (right, 76))
        rows = [
            ("perfect", stats.perfect, Judgement.PERFECT),
            ("good", stats.good, Judgement.GOOD),
            ("miss", stats.miss, Judgement.MISS),
            ("stray", stats.stray, Judgement.STRAY),
        ]
        for i, (name, count, j) in enumerate(rows):
            self._text(f"{name:8}{count}", (right, 124 + i * 28), JUDGE_COLORS[j])
        self._text(f"accuracy {stats.accuracy * 100:.1f}%", (right, 124 + len(rows) * 28 + 8))

        if self.feedback is not None and wall - self.feedback[1] < FEEDBACK_S:
            res = self.feedback[0]
            label = res.judgement.value.upper()
            if res.delta_s is not None:
                label += f"  {res.delta_s * 1000:+.0f} ms"
            self._text(label, (cx, hw.hit_y - 70), JUDGE_COLORS[res.judgement], self.big, True)

        if now < 0 and not self.clock.paused:
            self._text("get ready", (cx, screen.get_height() // 3), font=self.big, center=True)
        if self.clock.paused:
            self._text("PAUSED", (cx, screen.get_height() // 3), font=self.big, center=True)
        if self.finished:
            box = pygame.Rect(0, 0, 420, 150)
            box.center = (cx, screen.get_height() // 3)
            pygame.draw.rect(screen, (30, 30, 44), box, border_radius=10)
            pygame.draw.rect(screen, (90, 90, 120), box, 2, border_radius=10)
            self._text("FINISHED", (cx, box.top + 36), font=self.big, center=True)
            self._text(
                f"score {stats.score}   accuracy {stats.accuracy * 100:.1f}%",
                (cx, box.top + 84),
                center=True,
            )
            self._text(
                "Backspace to retry, Esc to quit", (cx, box.top + 118), (140, 140, 160), center=True
            )
