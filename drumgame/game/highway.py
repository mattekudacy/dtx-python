"""Lane and note rendering."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from typing import Sequence

import pygame

from drumgame.chart.model import TimedNote
from drumgame.game.judge import Judgement
from drumgame.lanes import PEDAL_LANES, Layout

LANE_COLORS: dict[str, tuple[int, int, int]] = {
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

BG = (12, 12, 18)
LANE_BG = (22, 22, 32)
LANE_EDGE = (48, 48, 64)
FOOTER_BG = (16, 16, 24)
BEAT_LINE = (44, 44, 60)
BAR_LINE = (110, 110, 135)
HIT_LINE = (235, 235, 245)
FLASH_S = 0.12


class Highway:
    def __init__(
        self,
        rect: pygame.Rect,
        layout: Layout,
        notes: Sequence[TimedNote],
        scroll_seconds: float,
        key_labels: dict[str, str] | None = None,
    ) -> None:
        self.rect = rect
        self.layout = layout
        self.notes = notes  # sorted by time, same order as Judge.notes
        self._times = [n.time for n in notes]
        self.hit_y = rect.bottom - 110
        self.pps = (self.hit_y - rect.top) / scroll_seconds  # pixels per second
        self.lane_w = rect.width // len(layout.lanes)
        self._lane_x = {
            lane: rect.left + i * self.lane_w for i, lane in enumerate(layout.lanes)
        }
        self._flash: dict[str, float] = {}
        self._font = pygame.font.Font(None, 22)
        self._key_labels = key_labels or {}
        self._chips = {
            (lane, ghost, missed): self._make_chip(lane, ghost, missed)
            for lane in layout.lanes
            for ghost in (False, True)
            for missed in (False, True)
        }
        self._flash_surf = pygame.Surface((self.lane_w, self.hit_y - rect.top), pygame.SRCALPHA)

    def _make_chip(self, lane: str, ghost: bool, missed: bool) -> pygame.Surface:
        """Pedals are wide, thin bars; hands are narrower, taller chips."""
        if lane in PEDAL_LANES:
            w, h = self.lane_w - 4, 10
        else:
            w, h = int(self.lane_w * 0.72), 16
        if ghost:
            w, h = int(w * 0.6), int(h * 0.75)
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        color = LANE_COLORS[lane]
        pygame.draw.rect(surf, color, surf.get_rect(), border_radius=4)
        light = tuple(min(255, c + 70) for c in color)
        pygame.draw.rect(surf, light, pygame.Rect(2, 1, w - 4, max(2, h // 4)), border_radius=2)
        if missed:
            surf.set_alpha(60)
        elif ghost:
            surf.set_alpha(150)
        return surf

    def y_at(self, note_time: float, now: float) -> float:
        return self.hit_y - (note_time - now) * self.pps

    def flash(self, lane: str, wall_time: float) -> None:
        self._flash[lane] = wall_time

    def draw(
        self,
        surface: pygame.Surface,
        now: float,
        wall_time: float,
        results: Sequence[Judgement | None],
        grid: Sequence[tuple[float, bool]],
    ) -> None:
        """`grid` is (time, is_bar_line) per beat, sorted by time."""
        r = self.rect
        pygame.draw.rect(surface, LANE_BG, r)
        prev_clip = surface.get_clip()
        surface.set_clip(r)

        # Only what is inside the visible time window gets drawn.
        t_top = now + (self.hit_y - r.top) / self.pps
        t_bottom = now - (r.bottom - self.hit_y) / self.pps

        for t, is_bar in grid:
            if t < t_bottom:
                continue
            if t > t_top:
                break
            y = round(self.y_at(t, now))
            pygame.draw.line(
                surface, BAR_LINE if is_bar else BEAT_LINE, (r.left, y), (r.right, y),
                2 if is_bar else 1,
            )  # fmt: skip

        for lane, x in self._lane_x.items():
            pygame.draw.line(surface, LANE_EDGE, (x, r.top), (x, r.bottom))
            age = wall_time - self._flash.get(lane, -1e9)
            if 0 <= age < FLASH_S:
                self._flash_surf.fill((*LANE_COLORS[lane], int(90 * (1 - age / FLASH_S))))
                surface.blit(self._flash_surf, (x, r.top))
        pygame.draw.line(surface, LANE_EDGE, (r.right - 1, r.top), (r.right - 1, r.bottom))

        pygame.draw.line(surface, HIT_LINE, (r.left, self.hit_y), (r.right, self.hit_y), 3)

        lo = bisect_left(self._times, t_bottom)
        hi = bisect_right(self._times, t_top)
        for i in range(hi - 1, lo - 1, -1):  # later notes first, so nearer ones sit on top
            res = results[i]
            if res is Judgement.PERFECT or res is Judgement.GOOD:
                continue
            note = self.notes[i]
            chip = self._chips[(note.lane, note.ghost, res is Judgement.MISS)]
            cx = self._lane_x[note.lane] + self.lane_w // 2
            y = self.y_at(note.time, now)
            surface.blit(chip, chip.get_rect(center=(cx, round(y))))

        # Opaque footer so passing notes and grid lines do not run through the labels.
        footer = pygame.Rect(r.left, self.hit_y + 14, r.width, r.bottom - self.hit_y - 14)
        pygame.draw.rect(surface, FOOTER_BG, footer)
        for lane, x in self._lane_x.items():
            cx = x + self.lane_w // 2
            label = self._font.render(LANE_LABELS[lane], True, LANE_COLORS[lane])
            surface.blit(label, label.get_rect(center=(cx, self.hit_y + 40)))
            key = self._key_labels.get(lane)
            if key:
                ksurf = self._font.render(key, True, (130, 130, 150))
                surface.blit(ksurf, ksurf.get_rect(center=(cx, self.hit_y + 66)))

        surface.set_clip(prev_clip)
