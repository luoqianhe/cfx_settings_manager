# src/core/grafx_sim.py
"""An approximate simulation of how the board renders a GraFx frame, for the painter's
preview: per-pixel accents= attributes plus SwingBright, driven by a simulated swing speed
(the preview can't feel motion) and a volume derived from it.

Grounded in the manual's descriptions (rev 1.19 - "GraFx pixel attributes", "GraFx
Timings & Morphing", "SwingBright Fx variants"); the firmware's exact curves aren't
documented, so this shows the right kind of behavior, not a frame-exact match:
- a: BMP color.  m: fades from this stage's color to the next over the stage.
- r: random RGB each stage.  R: random color-wheel hue (full brightness) each stage.
- ~ / ^: BMP color pulsing (inverted for ^) by accpulsed % over accpulsel ms.
  B / I: the same with the blade color; X / L: with the crystal color (xcolor).
- @: BMP color scaled by the volume; #: inverted. * / $: blade / crystal color by volume.
- s: mirrors pixel #1.  Magnetic (M C S T A), PLI (p P) and color shift (H) aren't
  simulated - they show their BMP color.
- SwingBright (Idle lit only - it acts on the blade fx): style 0 cross-fades the
  animation toward the blade color as the swing gets faster; style 1 the other way
  round. mapping_move's two numbers are the swing-speed range; delay_sbright slows the
  fade back after a swing.
"""
import colorsys
import math
import random
from typing import Dict, List, Optional, Tuple

from core.color_utils import rgbw_to_rgb

RGB = Tuple[int, int, int]

SWINGBRIGHT_MAPPINGS = {0: "static", 1: "audio", 2: "angle", 3: "motion", 4: "angle, reversed"}
HUM_VOLUME = 0.35          # simulated volume at rest; swinging adds up to the rest
DEFAULT_BLADE = (0, 140, 255)


def _int(settings: dict, key: str, default: int = 0) -> int:
    try:
        return int(str(settings.get(key, default)).split(',')[0].split()[0])
    except (ValueError, IndexError):
        return default


def _rgbw(value, default: RGB) -> RGB:
    try:
        r, g, b, w = map(int, str(value).split(','))
        return rgbw_to_rgb(r, g, b, w)
    except (ValueError, TypeError):
        return default


def _scale(color: RGB, factor: float) -> RGB:
    factor = max(0.0, min(1.0, factor))
    return tuple(int(round(c * factor)) for c in color)


def _mix(a: RGB, b: RGB, t: float) -> RGB:
    t = max(0.0, min(1.0, t))
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


class SwingBright:
    """The blade profile's SwingBright settings, optionally overridden to try it out."""

    def __init__(self, settings: dict, override: Optional[dict] = None):
        settings = dict(settings or {})
        settings.update(override or {})
        self.style = _int(settings, 'style_sbright')
        self.mapping = _int(settings, 'mapping_sbright')
        self.delay = _int(settings, 'delay_sbright')
        try:
            low, high = (int(v) for v in str(settings.get('mapping_move', '80,310')).split(','))
        except ValueError:
            low, high = 80, 310
        self.move_low, self.move_high = min(low, high), max(low, high, min(low, high) + 1)

    @property
    def active(self) -> bool:
        return self.mapping in (1, 2, 3, 4)

    def describe(self) -> str:
        if not self.active:
            return "SwingBright: static (mapping_sbright=0) - doesn't react to swings"
        direction = ("fades to blade color on swings" if self.style == 0
                     else "animation fades in on swings")
        return (f"SwingBright: {SWINGBRIGHT_MAPPINGS[self.mapping]}, style {self.style} "
                f"({direction}), range {self.move_low}-{self.move_high}")

    def target(self, swing_speed: float, volume: float) -> float:
        """0..1 - how far toward the "wet" side the cross-fade wants to be."""
        if self.mapping == 1:
            return volume
        span = (swing_speed - self.move_low) / (self.move_high - self.move_low)
        span = max(0.0, min(1.0, span))
        return 1.0 - span if self.mapping == 4 else span


class FrameSimulator:
    """Holds the simulated swing and SwingBright's smoothed amount between frames."""

    def __init__(self, settings: Optional[dict] = None):
        self.set_settings(settings)
        self.swing_speed = 0.0       # board units, like mapping_move
        self.sbright_override = None
        self._sbright_amount = 0.0
        self._random_cache = {}      # (segment id, stage) -> per-pixel random colors

    def set_settings(self, settings: Optional[dict]):
        self.settings = dict(settings or {})
        self.blade = _rgbw(self.settings.get('color'), DEFAULT_BLADE)
        self.crystal = _rgbw(self.settings.get('xcolor'), self.blade)

    def swingbright(self) -> SwingBright:
        return SwingBright(self.settings, self.sbright_override)

    @property
    def volume(self) -> float:
        """Simulated sound volume: the hum, louder the faster the swing (as with a
        smoothswing font)."""
        return min(1.0, HUM_VOLUME + (1 - HUM_VOLUME) * min(1.0, self.swing_speed / 600.0))

    def step(self, elapsed_ms: float):
        """Advance SwingBright's smoothing by elapsed_ms: it follows a rising swing
        straight away and fades back over a time set by delay_sbright."""
        sbright = self.swingbright()
        target = sbright.target(self.swing_speed, self.volume) if sbright.active else 0.0
        if target >= self._sbright_amount:
            self._sbright_amount = target
        else:
            fall_ms = 120 + sbright.delay * 12
            self._sbright_amount = max(target, self._sbright_amount - elapsed_ms / fall_ms)

    def _random(self, key, count: int, wheel: bool) -> List[RGB]:
        cache_key = (key, wheel)
        if cache_key not in self._random_cache:
            rng = random.Random(hash(cache_key))
            if wheel:
                colors = [tuple(int(c * 255) for c in colorsys.hsv_to_rgb(rng.random(), 1, 1))
                          for _ in range(count)]
            else:
                colors = [(rng.randrange(256), rng.randrange(256), rng.randrange(256))
                          for _ in range(count)]
            self._random_cache[cache_key] = colors
            if len(self._random_cache) > 64:
                self._random_cache.pop(next(iter(self._random_cache)))
        return self._random_cache[cache_key]

    def render(self, current: List[RGB], following: List[RGB], progress: float,
               accents: Optional[str], params: Optional[dict], time_ms: float,
               stage_key=None, swingbright: bool = False) -> List[RGB]:
        """One frame's pixel colors (index 0 = hilt). current/following: this stage's and
        the next stage's BMP colors; progress: 0..1 through the current stage."""
        params = params or {}
        depth = _int(params, 'accpulsed', 90) / 100.0
        period = max(1, _int(params, 'accpulsel', 1000))
        phase = 0.5 - 0.5 * math.cos(2 * math.pi * time_ms / period)   # 0 -> 1 -> 0
        pulse = 1.0 - depth * phase
        pulse_inverted = 1.0 - depth * (1.0 - phase)
        volume = self.volume
        count = len(current)
        accents = accents or ''
        out = []
        for i, color in enumerate(current):
            attr = accents[i] if i < len(accents) else 'a'
            if attr == 'm':
                color = _mix(color, following[i], progress)
            elif attr in 'rR':
                color = self._random(stage_key, count, attr == 'R')[i]
            elif attr == '~':
                color = _scale(color, pulse)
            elif attr == '^':
                color = _scale(color, pulse_inverted)
            elif attr == 'B':
                color = _scale(self.blade, pulse)
            elif attr == 'I':
                color = _scale(self.blade, pulse_inverted)
            elif attr == 'X':
                color = _scale(self.crystal, pulse)
            elif attr == 'L':
                color = _scale(self.crystal, pulse_inverted)
            elif attr == '@':
                color = _scale(color, volume)
            elif attr == '#':
                color = _scale(color, 1.0 - volume)
            elif attr == '*':
                color = _scale(self.blade, volume)
            elif attr == '$':
                color = _scale(self.crystal, volume)
            out.append(color)
        if accents:
            for i, attr in enumerate(accents[:count]):
                if attr == 's':
                    out[i] = out[0]
        if swingbright:
            sbright = self.swingbright()
            amount = self._sbright_amount
            if sbright.active and amount > 0:
                if sbright.style == 0:
                    out = [_mix(c, self.blade, amount) for c in out]
                else:
                    out = [_mix(self.blade, c, amount) for c in out]
            elif sbright.active and sbright.style == 1:
                out = [self.blade] * len(out)     # style 1 at rest: plain blade color
        return out

    def sbright_amount(self) -> float:
        return self._sbright_amount
