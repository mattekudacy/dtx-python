"""Shared look: palette, cached text rendering and small drawing helpers."""

from __future__ import annotations

from importlib import resources

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

# Highway surfaces.
LANE_BASE: Color = (16, 17, 25)
LANE_TINT = 0.13  # how much of its colour each lane's background carries
SEPARATOR: Color = (8, 9, 13)
BEAT_LINE: Color = (52, 55, 74)
BAR_LINE: Color = (128, 132, 160)
HIT_LINE: Color = (240, 242, 250)
FOOTER_BG: Color = (14, 15, 22)
KEYCAP: Color = (30, 33, 46)
KEYCAP_EDGE: Color = (62, 66, 88)

# Type scale, in design pixels (see Text for how they reach the screen). The
# player sits behind a kit, further from the screen than a desk user, so
# nothing informative goes below CAPTION.
CAPTION = 20
BODY = 24
TITLE = 32
VALUE = 44
SCORE = 88
DISPLAY = 150
GRADE = 190

# The design is drawn for this size and scaled to fit the window.
DESIGN_W, DESIGN_H = 1280, 720
# The layout still works when the window is this small in design pixels, which
# is how far a ui_scale above 1 may enlarge things.
MIN_DESIGN_W, MIN_DESIGN_H = 1024, 640

FONT_FILES = {False: "BarlowSemiCondensed-SemiBold.ttf", True: "BarlowSemiCondensed-Bold.ttf"}
BOLD_FROM = VALUE  # sizes from here up use the bold cut
# Barlow's digits and capitals are this fraction of the nominal size taller
# than the face the sizes were first tuned on.
FONT_SIZE_FACTOR = 0.78


def fit_scale(width: int, height: int, ui_scale: float = 1.0) -> float:
    """Screen pixels per design pixel for a window of this size."""
    fit = min(width / DESIGN_W, height / DESIGN_H)
    largest = min(width / MIN_DESIGN_W, height / MIN_DESIGN_H)
    return max(0.25, min(fit * ui_scale, largest))


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
    """Text rendering and the design-to-screen scale.

    All sizes and distances in the UI code are design pixels; `px` converts
    them. Rendered text is cached, because the HUD redraws every frame.
    """

    def __init__(self, scale: float = 1.0) -> None:
        self.scale = scale
        self._fonts: dict[int, pygame.font.Font] = {}
        self._cache: dict[tuple, pygame.Surface] = {}
        self._cells: dict[int, int] = {}

    def px(self, n: float) -> int:
        """Design pixels to screen pixels; never rounds a visible size to 0."""
        v = round(n * self.scale)
        return v if v or not n else (1 if n > 0 else -1)

    def font(self, size: int) -> pygame.font.Font:
        if size not in self._fonts:
            real = max(8, round(size * self.scale * FONT_SIZE_FACTOR))
            name = FONT_FILES[size >= BOLD_FROM]
            try:
                path = resources.files("drumgame").joinpath("data/fonts", name)
                with resources.as_file(path) as f:
                    self._fonts[size] = pygame.font.Font(str(f), real)
            except (OSError, pygame.error):  # font file missing: pygame's default
                self._fonts[size] = pygame.font.Font(None, round(size * self.scale))
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

    def _digit_cell(self, size: int) -> int:
        if size not in self._cells:
            self._cells[size] = max(self.font(size).size(d)[0] for d in "0123456789")
        return self._cells[size]

    def tabular(
        self,
        target: pygame.Surface,
        text: str,
        size: int,
        pos: tuple[float, float],
        color: Color = TEXT,
        align: str = "left",
        faint: int = 0,
    ) -> int:
        """Draw text with every digit in a fixed-width cell, so changing
        numbers never shift their neighbours. `pos` is the top-left corner,
        or the top-right with align="right". The first `faint` characters
        are drawn in the placeholder colour. Returns the width drawn.
        """
        font, cell = self.font(size), self._digit_cell(size)
        widths = [cell if ch.isdigit() else font.size(ch)[0] for ch in text]
        x = round(pos[0]) - (sum(widths) if align == "right" else 0)
        y = round(pos[1])
        for i, (ch, w) in enumerate(zip(text, widths)):
            surf = self.render(ch, size, TEXT_FAINT if i < faint else color)
            target.blit(surf, surf.get_rect(midtop=(x + w // 2, y)))
            x += w
        return sum(widths)


def ease_out(k: float) -> float:
    """Cubic ease-out over 0..1: fast at first, settling at the end."""
    k = max(0.0, min(1.0, k))
    return 1 - (1 - k) ** 3


def bar(
    target: pygame.Surface, rect: pygame.Rect, fraction: float, color: Color, track: Color = TRACK
) -> None:
    radius = rect.height // 2
    pygame.draw.rect(target, track, rect, border_radius=radius)
    w = round(rect.width * max(0.0, min(1.0, fraction)))
    if w > 0:
        fill = pygame.Rect(rect.left, rect.top, max(w, rect.height), rect.height)
        pygame.draw.rect(target, color, fill, border_radius=radius)


def panel(target: pygame.Surface, rect: pygame.Rect, radius: int = 10) -> None:
    pygame.draw.rect(target, PANEL, rect, border_radius=radius)
    pygame.draw.rect(target, PANEL_EDGE, rect, 1, border_radius=radius)
