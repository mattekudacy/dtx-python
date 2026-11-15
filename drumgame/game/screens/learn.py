"""Learn mode: hit each pad so the game records which MIDI notes it sends."""

from __future__ import annotations

import queue

import pygame

from drumgame.config import Config
from drumgame.game import ui
from drumgame.game.screens.base import Screen
from drumgame.input.mapping import LearnSession

MARGIN = 64
LIST_W = 380

MESSAGES = {
    "added": "Note {note} recorded.",
    "repeat": "Note {note} again. Already recorded for this pad.",
    "soft": "Note {note} was too soft and was ignored. Hit a little harder.",
}


class LearnScreen(Screen):
    """`notes` receives (note, velocity) for every note-on the kit sends."""

    def __init__(
        self,
        screen: pygame.Surface,
        config: Config,
        notes: "queue.Queue[tuple[int, int]]",
        device: str,
        session: LearnSession | None = None,
    ) -> None:
        self.notes = notes
        self.device = device
        self.session = session or LearnSession()
        self.message = ""
        self.message_color: ui.Color = ui.TEXT_DIM
        super().__init__(screen, config)

    def _names(self) -> dict[str, str]:
        return {step.lane: step.name for step in self.session.steps}

    def feed(self, note: int, velocity: int) -> None:
        status = self.session.feed(note, velocity)
        if status.startswith("moved:"):
            taken_from = self._names()[status.split(":", 1)[1]]
            self.message = f"Note {note} recorded. It was listed under {taken_from} before."
            self.message_color = ui.WARN
        elif status in MESSAGES:
            self.message = MESSAGES[status].format(note=note)
            self.message_color = ui.WARN if status == "soft" else ui.TEXT_DIM

    def run(self, max_seconds: float | None = None) -> dict[int, str] | None:
        """Returns the learned note map, or None if the player cancelled."""
        frame_clock = pygame.time.Clock()
        elapsed = 0.0
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return None
                if self.system_event(event) or event.type != pygame.KEYDOWN:
                    continue
                if event.key == pygame.K_ESCAPE:
                    return None
                if event.key == pygame.K_RETURN:
                    if self.session.done:
                        return self.session.result()
                    self.session.next()
                    self.message = ""
                elif event.key == pygame.K_BACKSPACE:
                    self.session.back()
                    self.message = ""
                elif event.key == pygame.K_DELETE:
                    self.session.clear()
                    self.message = ""
            while True:
                try:
                    note, velocity = self.notes.get_nowait()
                except queue.Empty:
                    break
                self.feed(note, velocity)
            self.draw()
            pygame.display.flip()
            elapsed += frame_clock.tick(60) / 1000
            if max_seconds is not None and elapsed >= max_seconds:
                return None

    # -- drawing -------------------------------------------------------------

    def draw(self) -> None:
        screen, text, px = self.screen, self.text, self.px
        w, h = screen.get_size()
        screen.fill(ui.BG)
        x = px(MARGIN)
        list_x = w - px(MARGIN) - px(LIST_W)
        main_w = list_x - x - px(MARGIN)
        self._draw_list(list_x, px(MARGIN), px(LIST_W))

        step = self.session.current
        if step is None:
            self._draw_summary(x, main_w)
            hints = "Enter save    Backspace go back    Esc discard"
        else:
            color = ui.LANE_COLORS[step.lane]
            position = f"Pad {self.session.index + 1} of {len(self.session.steps)}"
            text.draw(screen, position, ui.CAPTION, (x, px(MARGIN)), ui.TEXT_DIM)
            y = px(MARGIN + 30)
            text.draw(screen, text.fit(step.name, ui.SCORE, main_w), ui.SCORE, (x, y), color)
            y += px(104)
            y = self.draw_lines(
                [(step.hint, ui.BODY, ui.TEXT),
                 ("Hit every zone at least once, firmly.", ui.BODY, ui.TEXT_DIM)],
                x, y, main_w,
            )  # fmt: skip
            y += px(36)
            heard = self.session.notes[step.lane]
            if heard:
                text.draw(screen, "Notes recorded for this pad", ui.CAPTION, (x, y), ui.TEXT_DIM)
                cx = x
                for note in heard:
                    cx += text.tabular(screen, str(note), ui.VALUE, (cx, y + px(26))) + px(28)
            else:
                text.draw(screen, "Waiting for a hit", ui.VALUE, (x, y + px(14)), ui.TEXT_FAINT)
            if self.message:
                text.draw(
                    screen, text.fit(self.message, ui.CAPTION + 2, main_w), ui.CAPTION + 2,
                    (x, y + px(104)), self.message_color,
                )  # fmt: skip
            hints = "Enter next pad    Backspace previous pad    Delete clear this pad    Esc cancel"

        by = h - px(MARGIN) - px(52)
        pygame.draw.circle(screen, ui.OK, (x + px(6), by + px(12)), px(5))
        text.draw(
            screen, text.fit(self.device, ui.CAPTION + 2, main_w), ui.CAPTION + 2, (x + px(20), by)
        )
        text.draw(
            screen, text.fit(hints, ui.CAPTION, w - 2 * x), ui.CAPTION, (x, by + px(30)),
            ui.TEXT_DIM,
        )  # fmt: skip

    def _draw_list(self, x: int, y: int, width: int) -> None:
        """Every pad with what has been recorded for it; the current one marked."""
        screen, text, px = self.screen, self.text, self.px
        for i, step in enumerate(self.session.steps):
            current = i == self.session.index
            notes = self.session.notes[step.lane]
            if current:
                pygame.draw.rect(
                    screen, ui.PANEL, pygame.Rect(x - px(14), y - px(6), width + px(28), px(40)),
                    border_radius=px(6),
                )  # fmt: skip
            visited = i < self.session.index
            name_color = ui.LANE_COLORS[step.lane] if (current or visited) else ui.TEXT_FAINT
            text.draw(screen, step.name, ui.BODY, (x, y), name_color)
            if notes:
                value, color = "  ".join(str(n) for n in notes), ui.TEXT
            elif visited:
                value, color = "not mapped", ui.WARN
            else:
                value, color = "", ui.TEXT_DIM
            text.tabular(screen, value, ui.BODY, (x + width, y), color, "right")
            y += px(46)

    def _draw_summary(self, x: int, width: int) -> None:
        screen, text, px = self.screen, self.text, self.px
        result = self.session.result()
        missing = [s.name for s in self.session.steps if not self.session.notes[s.lane]]
        y = px(MARGIN + 30)
        heading = "All pads done" if result else "No notes recorded"
        text.draw(screen, heading, ui.SCORE, (x, y))
        y += px(112)
        lines: list[tuple[str, int, ui.Color]] = []
        if result:
            pads = len(self.session.steps) - len(missing)
            lines.append((f"{len(result)} notes recorded across {pads} pads.", ui.BODY, ui.TEXT))
        else:
            lines.append(("Nothing to save. Go back and hit the pads.", ui.BODY, ui.TEXT))
        if missing and result:
            lines.append(("No notes for " + ", ".join(missing) + ".", ui.BODY, ui.WARN))
            lines.append(("Those lanes will not respond to the kit.", ui.BODY, ui.TEXT_DIM))
        lines.append(("Saving replaces the note map the game uses.", ui.BODY, ui.TEXT_DIM))
        self.draw_lines(lines, x, y, width)
