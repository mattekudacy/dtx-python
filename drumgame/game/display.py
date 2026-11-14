"""Opening the game window, windowed or fullscreen."""

from __future__ import annotations

import pygame

from drumgame.config import MIN_HEIGHT, MIN_WIDTH


def open_display(width: int, height: int, fullscreen: bool) -> pygame.Surface:
    """(Re)create the display surface. Fullscreen uses the desktop resolution;
    the UI scales itself to whatever size comes back."""
    if fullscreen:
        return pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
    try:  # stop the window being dragged too small to read
        pygame.Window.from_display_module().minimum_size = (MIN_WIDTH, MIN_HEIGHT)
    except (AttributeError, pygame.error):
        pass
    return screen
