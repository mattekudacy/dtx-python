"""What every screen shares: the surface, the UI scale, and fullscreen."""

from __future__ import annotations

import pygame

from drumgame.config import Config
from drumgame.game import ui
from drumgame.game.display import open_display


class Screen:
    """Subclasses put everything size-dependent in `arrange`, which runs at
    construction and again whenever the window changes size."""

    def __init__(self, screen: pygame.Surface, config: Config) -> None:
        self.config = config
        self.fullscreen = bool(screen.get_flags() & pygame.FULLSCREEN)
        self.set_screen(screen)

    def set_screen(self, screen: pygame.Surface) -> None:
        self.screen = screen
        w, h = screen.get_size()
        self.text = ui.Text(ui.fit_scale(w, h, self.config.ui_scale))
        self.px = self.text.px
        self.arrange()

    def arrange(self) -> None:
        pass

    def toggle_fullscreen(self) -> None:
        self.fullscreen = not self.fullscreen
        self.set_screen(open_display(self.config.width, self.config.height, self.fullscreen))

    def system_event(self, event: pygame.event.Event) -> bool:
        """Handle window resizes and F11. Returns True if the event was used."""
        if event.type == pygame.VIDEORESIZE:
            self.set_screen(pygame.display.get_surface())
            return True
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
            self.toggle_fullscreen()
            return True
        return False

    def draw_lines(
        self, lines: "list[tuple[str, int, ui.Color]]", x: int, y: int, width: int, gap: int = 8
    ) -> int:
        """Draw left-aligned lines of (text, size, colour) downwards from y,
        each shortened to fit `width`. Returns the y below the last line."""
        for line, size, color in lines:
            self.text.draw(self.screen, self.text.fit(line, size, width), size, (x, y), color)
            y += self.text.font(size).get_linesize() + self.px(gap)
        return y
