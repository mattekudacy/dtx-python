"""Lane and note rendering."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from typing import Sequence

import pygame

from drumgame.chart.model import TimedNote
from drumgame.game.judge import Judgement
from drumgame.game import ui
from drumgame.game.ui import JUDGE_COLORS, LANE_COLORS, LANE_LABELS, TEXT, TEXT_DIM, mix
from drumgame.lanes import PEDAL_LANES, Layout

FLASH_S = 0.14  # pad target and beam after a hit
POPUP_S = 0.45  # in-lane judgement text
FOOTER_H = 118
BEAM_H = 190
FADE_H = 70


class Highway:
    def __init__(
        self,
        rect: pygame.Rect,
        layout: Layout,
        notes: Sequence[TimedNote],
        scroll_seconds: float,
        text: Text,
        key_labels: dict[str, str] | None = None,
        reduce_motion: bool = False,
    ) -> None:
        self.rect = rect
        self.layout = layout
        self.notes = notes  # sorted by time, same order as Judge.notes
        self.text = text
        self.reduce_motion = reduce_motion
        self._times = [n.time for n in notes]
        self.hit_y = rect.bottom - FOOTER_H
        self.pps = (self.hit_y - rect.top) / scroll_seconds  # pixels per second
        self.lane_w = rect.width // len(layout.lanes)
        self._lane_x = {
            lane: rect.left + i * self.lane_w for i, lane in enumerate(layout.lanes)
        }
        self._hits: dict[str, tuple[Judgement, float, float | None]] = {}
        self._key_labels = key_labels or {}
        # Largest judgement text that still sits inside one lane (plus a little).
        self._popup_size = next(
            (s for s in range(26, 15, -1) if text.font(s).size("PERFECT")[0] <= self.lane_w + 10),
            16,
        )
        self._chips = {
            (lane, ghost, missed): self._make_chip(lane, ghost, missed)
            for lane in layout.lanes
            for ghost in (False, True)
            for missed in (False, True)
        }
        self._beams = {lane: self._make_beam(lane) for lane in layout.lanes}
        self._background = self._make_background()
        self._footer = self._make_footer()
        self._fade = self._make_fade()

    # -- pre-rendered pieces -------------------------------------------------

    def _make_chip(self, lane: str, ghost: bool, missed: bool) -> pygame.Surface:
        """Pedals are wide, thin bars; hands are narrower, taller chips."""
        if lane in PEDAL_LANES:
            w, h = self.lane_w - 6, 10
        else:
            w, h = int(self.lane_w * 0.74), 16
        if ghost:
            w, h = int(w * 0.6), int(h * 0.75)
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        color = LANE_COLORS[lane]
        pygame.draw.rect(surf, mix(color, (0, 0, 0), 0.45), surf.get_rect(), border_radius=5)
        pygame.draw.rect(surf, color, pygame.Rect(0, 0, w, h - 2), border_radius=5)
        pygame.draw.rect(
            surf, mix(color, (255, 255, 255), 0.55), pygame.Rect(3, 2, w - 6, max(2, h // 4)),
            border_radius=2,
        )  # fmt: skip
        surf = surf.convert_alpha()
        if missed:
            surf.set_alpha(55)
        elif ghost:
            surf.set_alpha(150)
        return surf

    def _make_beam(self, lane: str) -> pygame.Surface:
        """A column of light rising from the hit line, brightest at the bottom."""
        surf = pygame.Surface((self.lane_w, BEAM_H), pygame.SRCALPHA)
        color = LANE_COLORS[lane]
        for y in range(BEAM_H):
            a = round(150 * (y / BEAM_H) ** 2)
            pygame.draw.line(surf, (*color, a), (0, y), (self.lane_w, y))
        return surf.convert_alpha()

    def _make_background(self) -> pygame.Surface:
        surf = pygame.Surface(self.rect.size)
        surf.fill(ui.LANE_BASE)
        for i, lane in enumerate(self.layout.lanes):
            x = i * self.lane_w
            pygame.draw.rect(
                surf,
                mix(ui.LANE_BASE, LANE_COLORS[lane], ui.LANE_TINT),
                pygame.Rect(x, 0, self.lane_w, self.rect.height),
            )
            pygame.draw.line(surf, ui.SEPARATOR, (x, 0), (x, self.rect.height), 2)
        return surf.convert()

    def _make_footer(self) -> pygame.Surface:
        """Everything below the pad targets: lane names and their keys."""
        h = FOOTER_H - 20
        surf = pygame.Surface((self.rect.width, h))
        surf.fill(ui.FOOTER_BG)
        for i, lane in enumerate(self.layout.lanes):
            x = i * self.lane_w
            cx = x + self.lane_w // 2
            pygame.draw.rect(surf, LANE_COLORS[lane], pygame.Rect(x + 6, h - 5, self.lane_w - 12, 3))
            self.text.draw(surf, LANE_LABELS[lane], 26, (cx, 26), LANE_COLORS[lane], "center")
            key = self._key_labels.get(lane)
            if key:
                # A key cap, so the binding reads as "press this" and not as a second name.
                kw = max(26, self.text.font(18).size(key)[0] + 12)
                cap = pygame.Rect(0, 0, min(kw, self.lane_w - 6), 22)
                cap.center = (cx, 60)
                pygame.draw.rect(surf, ui.KEYCAP, cap, border_radius=5)
                pygame.draw.rect(surf, ui.KEYCAP_EDGE, cap, 1, border_radius=5)
                self.text.draw(surf, key, 18, cap.center, TEXT_DIM, "center")
        return surf.convert()

    def _make_fade(self) -> pygame.Surface:
        """Notes ease in at the top instead of popping into view."""
        surf = pygame.Surface((self.rect.width, FADE_H), pygame.SRCALPHA)
        for y in range(FADE_H):
            a = round(235 * (1 - y / FADE_H) ** 1.6)
            pygame.draw.line(surf, (*ui.BG, a), (0, y), (self.rect.width, y))
        return surf.convert_alpha()

    # -- state ---------------------------------------------------------------

    def y_at(self, note_time: float, now: float) -> float:
        return self.hit_y - (note_time - now) * self.pps

    def register(
        self, lane: str, judgement: Judgement, wall_time: float, delta_s: float | None = None
    ) -> None:
        """Record a hit or miss so the lane can react to it."""
        self._hits[lane] = (judgement, wall_time, delta_s)

    # -- drawing -------------------------------------------------------------

    def draw(
        self,
        surface: pygame.Surface,
        now: float,
        wall_time: float,
        results: Sequence[Judgement | None],
        grid: Sequence[tuple[float, bool]],
        combo: int = 0,
    ) -> None:
        """`grid` is (time, is_bar_line) per beat, sorted by time."""
        r = self.rect
        prev_clip = surface.get_clip()
        surface.set_clip(r)
        surface.blit(self._background, r.topleft)

        # Only what is inside the visible time window gets drawn.
        t_top = now + (self.hit_y - r.top) / self.pps
        t_bottom = now - 30 / self.pps

        for t, is_bar in grid:
            if t < t_bottom:
                continue
            if t > t_top:
                break
            y = round(self.y_at(t, now))
            pygame.draw.line(
                surface, ui.BAR_LINE if is_bar else ui.BEAT_LINE, (r.left, y), (r.right, y),
                2 if is_bar else 1,
            )  # fmt: skip

        if combo >= 4:  # behind the notes, where the eyes already are
            cy = r.top + (self.hit_y - r.top) * 0.36
            # Alpha 95 keeps the number at about 3:1 on the lanes: readable at a
            # glance, still clearly behind the chips.
            self.text.draw(surface, str(combo), ui.DISPLAY, (r.centerx, cy), TEXT, "center", 95)
            self.text.draw(surface, "COMBO", ui.TITLE, (r.centerx, cy + 62), TEXT, "center", 95)

        for lane, (judgement, t_hit, _) in self._hits.items():
            age = wall_time - t_hit
            if self.reduce_motion:
                break
            if judgement is not Judgement.MISS and 0 <= age < FLASH_S:
                beam = self._beams[lane]
                beam.set_alpha(round(255 * (1 - ui.ease_out(age / FLASH_S))))
                surface.blit(beam, (self._lane_x[lane], self.hit_y - BEAM_H))

        lo = bisect_left(self._times, t_bottom)
        hi = bisect_right(self._times, t_top)
        for i in range(hi - 1, lo - 1, -1):  # later notes first, so nearer ones sit on top
            res = results[i]
            if res is Judgement.PERFECT or res is Judgement.GOOD:
                continue
            note = self.notes[i]
            chip = self._chips[(note.lane, note.ghost, res is Judgement.MISS)]
            cx = self._lane_x[note.lane] + self.lane_w // 2
            surface.blit(chip, chip.get_rect(center=(cx, round(self.y_at(note.time, now)))))

        surface.blit(self._fade, r.topleft)
        surface.blit(self._footer, (r.left, self.hit_y + 20))
        pygame.draw.rect(surface, ui.FOOTER_BG, pygame.Rect(r.left, self.hit_y, r.width, 20))
        pygame.draw.line(surface, ui.HIT_LINE, (r.left, self.hit_y), (r.right - 1, self.hit_y), 3)
        self._draw_targets(surface, wall_time)
        self._draw_popups(surface, wall_time)
        surface.set_clip(prev_clip)

    def _draw_targets(self, surface: pygame.Surface, wall_time: float) -> None:
        """Pad-shaped targets on the hit line that light up when struck."""
        for lane, x in self._lane_x.items():
            color = LANE_COLORS[lane]
            glow = 0.0
            hit = self._hits.get(lane)
            if hit is not None and hit[0] is not Judgement.MISS:
                age = wall_time - hit[1]
                if 0 <= age < FLASH_S:
                    glow = 1 - ui.ease_out(age / FLASH_S)
            if lane in PEDAL_LANES:
                shape = pygame.Rect(
                    0, 0, self.lane_w - 10, 16 + (0 if self.reduce_motion else round(4 * glow))
                )
            else:
                grow = 0 if self.reduce_motion else round(6 * glow)
                shape = pygame.Rect(0, 0, int(self.lane_w * 0.76) + grow, 24 + grow)
            shape.center = (x + self.lane_w // 2, self.hit_y)
            fill = mix(mix(ui.LANE_BASE, color, 0.22), (255, 255, 255), 0.85 * glow)
            edge = mix(color, (255, 255, 255), 0.6 * glow)
            if lane in PEDAL_LANES:
                pygame.draw.rect(surface, fill, shape, border_radius=6)
                pygame.draw.rect(surface, edge, shape, 3, border_radius=6)
            else:
                pygame.draw.ellipse(surface, fill, shape)
                pygame.draw.ellipse(surface, edge, shape, 3)

    def _draw_popups(self, surface: pygame.Surface, wall_time: float) -> None:
        """Judgement text in the lane it belongs to, rising and fading."""
        for lane, (judgement, t_hit, delta) in self._hits.items():
            age = wall_time - t_hit
            if judgement is Judgement.STRAY or not 0 <= age < POPUP_S:
                continue
            k = age / POPUP_S
            alpha = round(255 * (1 - k * k))
            cx = self._lane_x[lane] + self.lane_w // 2
            y = self.hit_y - 44 - (0 if self.reduce_motion else 16 * ui.ease_out(k))
            color = JUDGE_COLORS[judgement]
            self.text.draw(
                surface, judgement.value.upper(), self._popup_size, (cx, y), color, "center", alpha
            )
            if judgement is Judgement.GOOD and delta is not None:
                hint = "EARLY" if delta < 0 else "LATE"
                self.text.draw(surface, hint, 16, (cx, y + 16), TEXT_DIM, "center", alpha)
