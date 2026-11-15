"""Calibration: play along to a click so the game can measure your lag."""

from __future__ import annotations

import queue

import pygame

from drumgame.config import Config
from drumgame.game import ui
from drumgame.game.calibration import MIN_HITS, Calibration, CalibrationResult
from drumgame.game.clock import SongClock
from drumgame.game.metronome import render_click_track
from drumgame.game.screens.base import Screen
from drumgame.input.events import HitEvent
from drumgame.input.keyboard_in import KeyboardInput

BPM = 100.0
COUNT_IN = 4
MEASURED = 16
TAIL_S = 0.6
COLUMN_W = 640
METER_RANGE_S = 0.15  # the meter spans this far early and late
STEADY_S = 0.040  # a spread above this means the reading is not trustworthy


class CalibrateScreen(Screen):
    def __init__(
        self,
        screen: pygame.Surface,
        config: Config,
        hits: "queue.Queue[HitEvent]",
        keyboard: KeyboardInput,
    ) -> None:
        self.hits = hits
        self.keyboard = keyboard
        beat = 60.0 / BPM
        self.lead_in = COUNT_IN * beat
        self.click_times = [i * beat for i in range(MEASURED)]
        self.end_time = self.click_times[-1] + TAIL_S
        clicks = [(-(COUNT_IN - i) * beat, i == 0) for i in range(COUNT_IN)]
        clicks += [(t, False) for t in self.click_times]
        self.count_in = [t for t, _ in clicks if t < 0]
        self.sound: pygame.mixer.Sound | None = None
        init = pygame.mixer.get_init()
        if init and init[1] == -16:
            self.sound = pygame.mixer.Sound(
                buffer=render_click_track(clicks, self.lead_in, init[0], init[2])
            )
        self.channel: pygame.mixer.Channel | None = None
        self.clock = SongClock()  # no offset: this measures the raw lag
        self.calibration = Calibration(self.click_times)
        self.finished = False
        super().__init__(screen, config)

    def start(self) -> None:
        while True:
            try:
                self.hits.get_nowait()
            except queue.Empty:
                break
        self.calibration = Calibration(self.click_times)
        self.finished = False
        if self.channel is not None:
            self.channel.stop()
        if self.sound is not None:
            self.channel = self.sound.play()
        self.clock.start(-self.lead_in)

    def run(self, max_seconds: float | None = None) -> CalibrationResult | None:
        """Returns the measurement the player chose to save, or None."""
        frame_clock = pygame.time.Clock()
        elapsed = 0.0
        self.start()
        try:
            while True:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        return None
                    if self.system_event(event):
                        continue
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        return None
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_BACKSPACE:
                        self.start()
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                        if self.finished and self.calibration.result() is not None:
                            return self.calibration.result()
                    else:
                        self.keyboard.handle_event(event)
                while True:
                    try:
                        hit = self.hits.get_nowait()
                    except queue.Empty:
                        break
                    if not self.finished:
                        self.calibration.add_hit(self.clock.to_song_time(hit.time))
                now = self.clock.now()
                if now >= self.end_time:
                    self.finished = True
                self.draw(now)
                pygame.display.flip()
                elapsed += frame_clock.tick(self.config.fps) / 1000
                if max_seconds is not None and elapsed >= max_seconds:
                    return None
        finally:
            if self.channel is not None:
                self.channel.stop()

    # -- drawing -------------------------------------------------------------

    def draw(self, now: float) -> None:
        screen, text, px = self.screen, self.text, self.px
        w, h = screen.get_size()
        screen.fill(ui.BG)
        col_w = min(px(COLUMN_W), w - px(64))
        x = (w - col_w) // 2
        y = px(96)

        if self.sound is None:
            y = self.draw_lines(
                [("No audio device found", ui.VALUE, ui.WARN),
                 ("Calibration needs the click to be audible.", ui.BODY, ui.TEXT),
                 ("Check your sound output, then run it again.", ui.BODY, ui.TEXT_DIM)],
                x, y, col_w,
            )  # fmt: skip
            hints = "Esc close"
        elif self.finished:
            hints = self._draw_result(x, y, col_w)
        else:
            counted = sum(1 for t in self.count_in if t <= now + 0.02)
            heading = "Hit any pad on every click"
            if now < 0:
                heading = f"Listen: {counted}" if counted else "Listen"
            y = self.draw_lines(
                [(heading, ui.VALUE, ui.TEXT),
                 ("Play by ear, with the pad or key you normally use.", ui.BODY, ui.TEXT_DIM)],
                x, y, col_w,
            )  # fmt: skip
            self._draw_progress(x, y + px(40), col_w)
            self._draw_meter(x, y + px(110), col_w)
            hints = "Backspace start again    Esc cancel"
        text.draw(screen, text.fit(hints, ui.CAPTION, col_w), ui.CAPTION, (x, h - px(84)),
                  ui.TEXT_DIM)  # fmt: skip

    def _draw_progress(self, x: int, y: int, width: int) -> None:
        """One mark per measured click, filled once a hit has landed on it."""
        step = width / MEASURED
        hit = self.calibration.hit_clicks
        for i in range(MEASURED):
            mark = pygame.Rect(round(x + i * step), y, max(4, round(step) - self.px(8)), self.px(10))
            color = ui.ACCENT if i in hit else ui.TRACK
            pygame.draw.rect(self.screen, color, mark, border_radius=self.px(3))
        caption = f"{self.calibration.count} of {MEASURED} clicks hit"
        self.text.tabular(self.screen, caption, ui.CAPTION, (x, y + self.px(22)), ui.TEXT_DIM)

    def _draw_meter(self, x: int, y: int, width: int, show_average: bool = True) -> None:
        ui.timing_meter(
            self.screen, self.text, pygame.Rect(x, y, width, self.px(70)),
            tuple(self.calibration.deltas), self.config.windows.perfect_s, METER_RANGE_S,
            MEASURED, "Your hits will appear here", show_average,
        )  # fmt: skip

    def _draw_result(self, x: int, y: int, width: int) -> str:
        result = self.calibration.result()
        if result is None:
            self.draw_lines(
                [("Not enough hits to measure", ui.VALUE, ui.WARN),
                 (f"{self.calibration.count} of {MEASURED} clicks had a hit near them; "
                  f"{MIN_HITS} are needed.", ui.BODY, ui.TEXT),
                 ("If the kit made no marks at all, run learn mode first.", ui.BODY, ui.TEXT_DIM)],
                x, y, width,
            )  # fmt: skip
            return "Backspace try again    Esc cancel"
        ms = result.median_s * 1000
        if abs(ms) < 3:
            heading = "Right on the click"
        else:
            heading = f"{abs(ms):.0f} ms {'after' if ms > 0 else 'before'} the click"
        steady = result.spread_s <= STEADY_S
        lines: list[tuple[str, int, ui.Color]] = [
            (heading, ui.SCORE, ui.TEXT),
            (f"Measured over {result.count} hits, typically within "
             f"{result.spread_s * 1000:.0f} ms of each other.", ui.BODY, ui.TEXT),
        ]  # fmt: skip
        if not steady:
            lines.append(
                ("Your hits varied a lot. Try again for a steadier reading.", ui.BODY, ui.WARN)
            )
        lines.append(
            (f"Saving sets the audio offset to {result.offset_ms:+.0f} ms, so that playing "
             "this way counts as on time.", ui.BODY, ui.TEXT_DIM)
        )  # fmt: skip
        y = self.draw_lines(lines, x, y, width)
        # The heading already states the result; a second average here would
        # only disagree with it by a rounding step.
        self._draw_meter(x, y + self.px(8), width, show_average=False)
        return "Enter save    Backspace measure again    Esc discard"
