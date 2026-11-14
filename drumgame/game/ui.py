"""Shared look: palette, cached text rendering and small drawing helpers."""

from __future__ import annotations

import pygame

from drumgame.game.judge import Judgement

Color = tuple[int, int, int]

BG: Color = (10, 11, 16)
PANEL: Color = (20, 22, 31)
PANEL_EDGE: Color = (44, 47, 64)
TRACK: Color = (30, 33, 46)  # empty bar / gauge background
TEXT: Color = (232, 234, 242)
TEXT_DIM: Color = (160, 164, 184)  # secondary text; keeps about 7:1 on BG
TEXT_FAINT: Color = (112, 116, 138)  # placeholders such as leading zeros
ACCENT: Color = (120, 200, 255)
OK: Color = (110, 220, 140)
WARN: Color = (240, 180, 80)

LANE_COLORS: dict[str, Color] = {
    "crash_l": (235, 90, 165),
    "hihat": (70, 170, 240),
    "hh_pedal": (225, 130, 215),
    "snare": (240, 210, 60),
    "tom_hi": (85, 210, 115),
    "kick": (160, 115, 245),
    "tom_mid": (240, 85, 75),
    "tom_floor": (240, 155, 55),
    "crash_r": (90, 205, 230),
    "ride": (125, 145, 245),
}
LANE_LABELS: dict[str, str] = {
    "crash_l": "LC", "hihat": "HH", "hh_pedal": "HP", "snare": "SD", "tom_hi": "HT",
    "kick": "BD", "tom_mid": "LT", "tom_floor": "FT", "crash_r": "CY", "ride": "RD",
}  # fmt: skip

JUDGE_COLORS: dict[Judgement, Color] = {
    Judgement.PERFECT: (255, 222, 90),
    Judgement.GOOD: (110, 220, 140),
    Judgement.MISS: (240, 90, 90),
    Judgement.STRAY: (150, 154, 176),
}


def mix(a: Color, b: Color, t: float) -> Color:
    """Blend from `a` (t=0) to `b` (t=1)."""
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))  # type: ignore[return-value]


class Text:
    """Renders text once and reuses the surface: the HUD redraws every frame."""

    def __init__(self) -> None:
        self._fonts: dict[int, pygame.font.Font] = {}
        self._cache: dict[tuple, pygame.Surface] = {}

    def font(self, size: int) -> pygame.font.Font:
        if size not in self._fonts:
            self._fonts[size] = pygame.font.Font(None, size)
        return self._fonts[size]

    def render(self, text: str, size: int, color: Color = TEXT, alpha: int = 255) -> pygame.Surface:
        alpha = min(255, alpha | 15)  # 16 steps are plenty and keep the cache small
        key = (text, size, color, alpha)
        surf = self._cache.get(key)
        if surf is None:
            if len(self._cache) > 1500:
                self._cache.clear()
            surf = self.font(size).render(text, True, color)
            if alpha < 255:
                surf.set_alpha(alpha)
            self._cache[key] = surf
        return surf

    def draw(
        self,
        target: pygame.Surface,
        text: str,
        size: int,
        pos: tuple[float, float],
        color: Color = TEXT,
        anchor: str = "topleft",
        alpha: int = 255,
    ) -> pygame.Rect:
        surf = self.render(text, size, color, alpha)
        rect = surf.get_rect(**{anchor: (round(pos[0]), round(pos[1]))})
        target.blit(surf, rect)
        return rect

    def fit(self, text: str, size: int, width: int) -> str:
        """Shorten with an ellipsis until the text fits in `width` pixels."""
        font = self.font(size)
        if font.size(text)[0] <= width:
            return text
        while len(text) > 1 and font.size(text + "...")[0] > width:
            text = text[:-1]
        return text.rstrip() + "..."

    def digits(
        self,
        target: pygame.Surface,
        value: int,
        places: int,
        size: int,
        pos: tuple[int, int],
        color: Color = TEXT,
        zero_color: Color = TEXT_FAINT,
    ) -> int:
        """Draw a zero-padded number in fixed-width cells so it never jitters.

        Leading zeros are drawn faint. Returns the total width.
        """
        font = self.font(size)
        cell = max(font.size(d)[0] for d in "0123456789")
        s = str(max(0, value)).rjust(places, "0")
        lead = len(s) - len(str(max(0, value))) if value > 0 else len(s) - 1
        for i, ch in enumerate(s):
            surf = self.render(ch, size, zero_color if i < lead else color)
            target.blit(surf, surf.get_rect(midtop=(pos[0] + i * cell + cell // 2, pos[1])))
        return cell * len(s)


def bar(
    target: pygame.Surface, rect: pygame.Rect, fraction: float, color: Color, track: Color = TRACK
) -> None:
    radius = rect.height // 2
    pygame.draw.rect(target, track, rect, border_radius=radius)
    w = round(rect.width * max(0.0, min(1.0, fraction)))
    if w > 0:
        fill = pygame.Rect(rect.left, rect.top, max(w, rect.height), rect.height)
        pygame.draw.rect(target, color, fill, border_radius=radius)


def panel(target: pygame.Surface, rect: pygame.Rect) -> None:
    pygame.draw.rect(target, PANEL, rect, border_radius=10)
    pygame.draw.rect(target, PANEL_EDGE, rect, 1, border_radius=10)
