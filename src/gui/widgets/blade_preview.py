# src/gui/widgets/blade_preview.py
import math
import random
from PySide6 import QtWidgets, QtCore, QtGui

# Map the CFX manual's style_pon/style_poff values onto the handful of render shapes this
# preview approximates, grounded in the RICE schema's Option descriptions (see
# settings explanation json files/BladeProfileConfig.json) rather than guessed from the
# option names alone. Styles that share a description's wording share a render:
# 'crumble' = "pixelated" grain, 'chopped' = "flashing chunks" (a distinct, coarser look -
# same idea, bigger and binary rather than fine and jittered), 'comet' = a bright FoC-tinted
# leading edge fading back to blade color ("tip flare"/quicksilver/mercury/catchup/super nova
# all describe basically this), 'base_flare'/'full_flare' = flares explicitly localized to the
# hilt end (and hilt+tip together), and 'fade_trail' = a tailing fade that stays blade-colored
# throughout, since Dissolve's description explicitly rules out any FoC tint the other tailing
# styles have. GraFx/Vision Fx (bitmap-sequence based) are the one family left as a plain
# fallback, since there's no image data here to approximate from at all.
PON_STYLE_MAP = {
    '0': 'normal', '1': 'lightstick',
    '2': 'flare', '3': 'base_flare', '4': 'comet', '5': 'full_flare',
    '6': 'crumble', '7': 'comet', '8': 'comet', '9': 'comet',
    '11': 'inverted', '12': 'split_in', '13': 'split_out', '14': 'chopped',
}
POFF_STYLE_MAP = {
    '0': 'normal', '1': 'lightstick',
    '2': 'crumble', '3': 'sparkle_dust', '4': 'comet', '5': 'crumble',
    '6': 'fade_trail', '7': 'sparkle_flake', '8': 'comet', '9': 'comet', '10': 'split_in',
    '12': 'flare', '13': 'base_flare', '14': 'comet', '15': 'full_flare',
    '16': 'inverted', '17': 'chopped',
}

# unstable values this preview approximates, likewise grounded in the RICE Option names
# (BladeProfileConfig.json) rather than guessed. GraFx/Vision Fx (bitmap-based) and the more
# elaborate particle sims (Sauron/Sauron II, Jedi Fallen Order, Generative Unstable Fire) are
# left as a plain blade color - genuinely nothing here to approximate them from.
UNSTABLE_MAP = {
    '1': 'flicker',   # Unstable blade
    '2': 'flicker',   # Flame (legacy fire)
    '3': 'flicker',   # Rain sizzle
    '4': 'flicker',   # Chainsaw
    '5': 'flicker',   # Starkiller
    '6': 'flicker',   # Unstable TFU
    '7': 'gradient',  # Gradient
    '8': 'wave',       # Wave
    '9': 'rainbow',   # Rainbow
    '10': 'chase',    # Theater chase
    '14': 'knightrider',  # Knight Rider / Energy Beam
    '16': 'pulse',    # Bicolor Pulse Fx
}


class BladePreviewWidget(QtWidgets.QWidget):
    """A rough visual preview of blade behavior - ignition/retraction, idle look, and
    Clash/Lockup reactions.

    This is NOT a faithful simulation of what a real CFX-driven blade looks like - it's a set
    of rough, thematic guesses at what most style_pon/style_poff/unstable values might look
    like (see the maps above), not recreations of their actual algorithms. Bitmap (GraFx) fx
    and motion-driven fx (SmoothSwing) are the only things left unmodeled entirely, since
    there's genuinely nothing to approximate them from here. Treat this as a sanity-check for
    color, timing, and rough shape/mood - not a preview of the real hardware's appearance.
    """

    FRAME_MS = 33  # ~30fps
    CLASH_DECAY_MS = 350
    RAINBOW_PERIOD_S = 6.0
    PULSE_PERIOD_S = 1.6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(60, 260)

        self._color = QtGui.QColor(200, 200, 200)
        self._foc_color = QtGui.QColor(255, 255, 255)
        self._lockup_color = QtGui.QColor(255, 140, 0)

        self._fill = 0.0  # 0.0 = fully retracted, 1.0 = fully ignited
        self._flicker_brightness = 1.0

        self._qon_ms = 300
        self._qoff_ms = 300
        self._flicker_on = False
        self._flicker_off = False
        self._pon_style = 'normal'
        self._poff_style = 'normal'
        self._unstable_mode = None  # None, 'rainbow', or 'pulse'

        self._duration_ms = 300
        self._flicker_enabled = False
        self._direction = 0  # 1 = igniting, -1 = retracting, 0 = idle
        self._elapsed_ms = 0
        self._idle_phase_s = 0.0

        self._clash_intensity = 0.0  # 0..1, decays after clash()
        self._lockup_engaged = False

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._tick)

    def set_profile(self, rgb, qon_ms, qoff_ms, flicker_on, flicker_off,
                     foc_rgb=None, lockup_rgb=None, pon_style_id=None, poff_style_id=None,
                     unstable_id=None):
        """Update the color/timing/style this preview animates with. Does not change
        whatever ignition state is currently being displayed."""
        self._color = QtGui.QColor(*rgb)
        self._foc_color = QtGui.QColor(*foc_rgb) if foc_rgb else QtGui.QColor(255, 255, 255)
        self._lockup_color = QtGui.QColor(*lockup_rgb) if lockup_rgb else QtGui.QColor(255, 140, 0)
        self._qon_ms = max(1, qon_ms)
        self._qoff_ms = max(1, qoff_ms)
        self._flicker_on = flicker_on
        self._flicker_off = flicker_off
        self._pon_style = PON_STYLE_MAP.get(str(pon_style_id), 'normal')
        self._poff_style = POFF_STYLE_MAP.get(str(poff_style_id), 'normal')
        self._unstable_mode = UNSTABLE_MAP.get(str(unstable_id))
        self.update()
        self._sync_timer()

    def ignite(self):
        if self._direction == 1:
            return
        self._start(direction=1, duration_ms=self._qon_ms, flicker=self._flicker_on)

    def retract(self):
        if self._direction == -1:
            return
        self._lockup_engaged = False
        self._start(direction=-1, duration_ms=self._qoff_ms, flicker=self._flicker_off)

    def clash(self):
        """Momentary Flash-on-Clash: a brief flash toward the FoC color that decays back."""
        self._clash_intensity = 1.0
        self._sync_timer()

    def toggle_lockup(self) -> bool:
        """Engage/disengage the (simplified, non-localized) lockup color mix. Returns the
        new engaged state."""
        if self._fill <= 0.0:
            return False  # nothing to lock up if the blade isn't lit
        self._lockup_engaged = not self._lockup_engaged
        self.update()
        return self._lockup_engaged

    def reset(self):
        """Snap immediately to the unlit state - used when switching fonts."""
        self._timer.stop()
        self._direction = 0
        self._fill = 0.0
        self._flicker_brightness = 1.0
        self._clash_intensity = 0.0
        self._lockup_engaged = False
        self.update()

    def is_ignited(self) -> bool:
        return self._direction == 0 and self._fill >= 1.0

    def _start(self, direction, duration_ms, flicker):
        self._direction = direction
        self._duration_ms = duration_ms
        self._flicker_enabled = flicker
        self._elapsed_ms = 0
        self._sync_timer()

    def _idle_animation_active(self) -> bool:
        return (self._direction == 0 and self._fill >= 1.0
                and self._unstable_mode is not None and not self._lockup_engaged)

    def _sync_timer(self):
        should_run = (self._direction != 0 or self._clash_intensity > 0
                      or self._idle_animation_active())
        if should_run and not self._timer.isActive():
            self._timer.start()
        elif not should_run and self._timer.isActive():
            self._timer.stop()

    def _tick(self):
        self._elapsed_ms += self.FRAME_MS
        self._idle_phase_s += self.FRAME_MS / 1000.0

        if self._direction != 0:
            progress = min(1.0, self._elapsed_ms / self._duration_ms)
            self._fill = progress if self._direction == 1 else 1.0 - progress
            self._flicker_brightness = (
                random.uniform(0.65, 1.0) if self._flicker_enabled else 1.0
            )
            if progress >= 1.0:
                was_igniting = self._direction == 1
                self._direction = 0
                self._fill = 1.0 if was_igniting else 0.0
                self._flicker_brightness = 1.0

        if self._clash_intensity > 0:
            self._clash_intensity = max(
                0.0, self._clash_intensity - self.FRAME_MS / self.CLASH_DECAY_MS
            )

        self._sync_timer()
        self.update()

    @staticmethod
    def _blend(c1: QtGui.QColor, c2: QtGui.QColor, t: float) -> QtGui.QColor:
        t = max(0.0, min(1.0, t))
        return QtGui.QColor(
            int(c1.red() + (c2.red() - c1.red()) * t),
            int(c1.green() + (c2.green() - c1.green()) * t),
            int(c1.blue() + (c2.blue() - c1.blue()) * t),
        )

    @staticmethod
    def _scale_brightness(color: QtGui.QColor, factor: float) -> QtGui.QColor:
        factor = max(0.0, min(1.0, factor))
        return QtGui.QColor(
            int(color.red() * factor), int(color.green() * factor), int(color.blue() * factor)
        )

    def _current_style(self):
        return self._pon_style if self._direction != -1 else self._poff_style

    def _lit_segments(self, left, top, width, bottom):
        """Return (list of QRects to paint, brightness multiplier) for the current fill/style."""
        full_h = max(0, bottom - top)
        style = self._current_style()
        fill = self._fill

        if style in ('lightstick', 'flare'):
            return [QtCore.QRect(left, top, width, full_h)], fill

        if style == 'inverted':
            h = int(full_h * fill)
            return [QtCore.QRect(left, top, width, h)], 1.0

        if style == 'split_in':
            half = full_h // 2
            h = int(half * fill)
            return [
                QtCore.QRect(left, top, width, h),
                QtCore.QRect(left, bottom - h, width, h),
            ], 1.0

        if style == 'split_out':
            half = full_h // 2
            h = int(half * fill)
            center = top + half
            return [
                QtCore.QRect(left, center - h, width, h),
                QtCore.QRect(left, center, width, h),
            ], 1.0

        # 'normal' and anything unrecognized: scroll up from the hilt
        h = int(full_h * fill)
        return [QtCore.QRect(left, bottom - h, width, h)], 1.0

    def _base_color(self):
        if self._lockup_engaged:
            return self._blend(self._color, self._lockup_color, 0.5)

        if self._idle_animation_active():
            if self._unstable_mode == 'rainbow':
                hue = (self._idle_phase_s / self.RAINBOW_PERIOD_S) % 1.0
                return QtGui.QColor.fromHsvF(hue, 1.0, 1.0)
            if self._unstable_mode == 'pulse':
                t = (math.sin(self._idle_phase_s * (2 * math.pi / self.PULSE_PERIOD_S)) + 1) / 2
                return self._blend(self._color, self._foc_color, t)
            if self._unstable_mode == 'flicker':
                return self._scale_brightness(self._color, random.uniform(0.5, 1.0))

        style = self._current_style()
        if style == 'flare':
            return self._blend(self._foc_color, self._color, self._fill)

        return self._color

    def _draw_crumble(self, painter, rect, color):
        """Chunky/pixelated look: independently-jittered brightness blocks, refreshed every
        frame so it reads as grainy rather than a smooth fill."""
        block_h = 6
        y = rect.top()
        while y < rect.bottom():
            h = min(block_h, rect.bottom() - y)
            block_color = self._scale_brightness(color, random.uniform(0.35, 1.0))
            painter.fillRect(QtCore.QRect(rect.left(), y, rect.width(), h), block_color)
            y += block_h

    def _draw_comet(self, painter, rect, color):
        """Bright FoC-tinted 'head' at the moving edge (rect.top(), since every style that maps
        here uses the hilt-anchored growth/shrink shape) fading into blade color behind it."""
        glow = QtGui.QColor(color)
        glow.setAlpha(70)
        painter.fillRect(rect.adjusted(-8, -4, 8, 0), glow)
        painter.fillRect(rect, color)
        self._draw_comet_head(painter, rect, color)

    def _draw_comet_head(self, painter, rect, color):
        """Just the bright FoC-tinted head bands from _draw_comet, without the base fill -
        so full_flare can layer this on top of its own hilt-end gradient instead of one
        overwriting the other."""
        head_h = min(24, rect.height())
        band_h = max(1, head_h // 3)
        y = rect.top()
        for frac in (1.0, 0.6, 0.3):
            painter.fillRect(QtCore.QRect(rect.left(), y, rect.width(), band_h),
                              self._blend(color, self._foc_color, frac))
            y += band_h

    def _draw_fade_trail(self, painter, rect, color):
        """Dissolve: tailing like the comet styles, but explicitly 'blade colored only' per
        the RICE description - a brightness fade at the edge rather than an FoC-tinted head."""
        glow = QtGui.QColor(color)
        glow.setAlpha(70)
        painter.fillRect(rect.adjusted(-8, -4, 8, 0), glow)
        painter.fillRect(rect, color)

        head_h = min(24, rect.height())
        band_h = max(1, head_h // 3)
        y = rect.top()
        for frac in (0.3, 0.55, 0.8):
            painter.fillRect(QtCore.QRect(rect.left(), y, rect.width(), band_h),
                              self._scale_brightness(color, frac))
            y += band_h

    def _draw_chopped(self, painter, rect, color):
        """Chopped-on/off: 'poweron/poweroff in flashing chunks' - large blocks that are
        either fully lit or nearly dark, refreshed every frame. Distinct from crumble's fine,
        continuously-jittered grain: fewer, bigger blocks and binary rather than graded
        brightness, so it reads as chunky flashing rather than pixelated noise."""
        block_h = 20
        y = rect.top()
        while y < rect.bottom():
            h = min(block_h, rect.bottom() - y)
            lit = random.random() < 0.6
            block_color = color if lit else self._scale_brightness(color, 0.12)
            painter.fillRect(QtCore.QRect(rect.left(), y, rect.width(), h), block_color)
            y += block_h

    def _draw_base_flare(self, painter, rect, color):
        """Base flare: 'applies FoC to the base of the blade only'. A gradient anchored at
        the hilt end (rect.bottom()) blending toward FoC, strongest right as the transition
        starts and fading out by the time it's half done - outside a transition (idle) it's
        just the plain color, since the effect is explicitly tied to ignition/retraction."""
        if self._direction == 0:
            painter.fillRect(rect, color)
            return
        progress = self._fill if self._direction == 1 else (1.0 - self._fill)
        intensity = max(0.0, 1.0 - 2.0 * progress)
        if intensity <= 0.0:
            painter.fillRect(rect, color)
            return
        gradient = QtGui.QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        gradient.setColorAt(0.0, color)
        gradient.setColorAt(1.0, self._blend(color, self._foc_color, intensity))
        painter.fillRect(rect, QtGui.QBrush(gradient))

    def _draw_full_flare(self, painter, rect, color):
        """Full flare: 'Combines Base and Tip flare' - the base_flare hilt-end gradient plus
        a comet-style head at the moving edge, layered rather than drawn separately so
        neither overwrites the other."""
        self._draw_base_flare(painter, rect, color)
        glow = QtGui.QColor(color)
        glow.setAlpha(70)
        painter.fillRect(rect.adjusted(-8, -4, 8, 0), glow)
        self._draw_comet_head(painter, rect, color)

    def _draw_retraction_sparkles(self, painter, left, top, width, segments):
        """Star dust / Star flakes (poff 3/7): both explicitly describe residue trailing the
        retraction ('leaves light dust behind' / sparkle tailing), not a moving comet head -
        so unlike the comet styles, this paints faint specks in the region the retracting
        blade has already vacated (between the blade tip and the current lit edge), denser
        and brighter near that edge and fading out toward the tip."""
        if not segments:
            return
        vacated_bottom = segments[0].top()
        vacated_top = top
        span = vacated_bottom - vacated_top
        if span <= 0:
            return
        tint = self._foc_color if self._poff_style == 'sparkle_flake' else self._color
        for _ in range(14):
            y = random.randint(vacated_top, vacated_bottom)
            dist = (vacated_bottom - y) / span
            brightness = max(0.0, 1.0 - dist) * random.uniform(0.4, 1.0)
            if self._poff_style == 'sparkle_flake':
                brightness *= random.uniform(0.5, 1.0)  # flicker
            if brightness <= 0.05:
                continue
            speck = self._scale_brightness(tint, brightness)
            x = left + random.randint(0, max(0, width - 2))
            painter.fillRect(QtCore.QRect(x, y, 2, 2), speck)

    def _draw_idle_pattern(self, painter, rect, base_color):
        """Position-dependent idle looks (wave/chase/Knight Rider/gradient) - these vary
        along the blade's length, unlike the other modes which are a single flat color."""
        mode = self._unstable_mode

        if mode == 'gradient':
            # Static (non-animated) gradient along the blade's length - unlike wave/chase/
            # knightrider this isn't a moving effect, just a fixed FoC-tinted tip fading to
            # plain blade color toward the hilt.
            gradient = QtGui.QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
            gradient.setColorAt(0.0, self._foc_color)
            gradient.setColorAt(1.0, base_color)
            painter.fillRect(rect, QtGui.QBrush(gradient))
            return

        if mode == 'wave':
            gradient = QtGui.QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
            steps = 8
            phase = self._idle_phase_s * 2.0
            for i in range(steps + 1):
                frac = i / steps
                wave = (math.sin(phase + frac * 4 * math.pi) + 1) / 2  # 2 full waves along the blade
                gradient.setColorAt(frac, self._blend(base_color, self._foc_color, wave * 0.6))
            painter.fillRect(rect, QtGui.QBrush(gradient))
            return

        if mode == 'chase':
            bands = 6
            band_h = max(1, rect.height() // bands)
            phase_index = int(self._idle_phase_s * 4) % bands  # ~4 bands/sec
            y = rect.top()
            for i in range(bands):
                h = band_h if i < bands - 1 else rect.bottom() - y
                lit = (i - phase_index) % bands < bands // 2
                band_color = base_color if lit else self._scale_brightness(base_color, 0.15)
                painter.fillRect(QtCore.QRect(rect.left(), y, rect.width(), h), band_color)
                y += h
            return

        if mode == 'knightrider':
            band_h = max(6, rect.height() // 6)
            travel = max(0, rect.height() - band_h)
            t = (math.sin(self._idle_phase_s * 2.5) + 1) / 2  # bounces 0..1..0
            y = rect.top() + int(travel * t)
            painter.fillRect(rect, self._scale_brightness(base_color, 0.15))
            painter.fillRect(QtCore.QRect(rect.left(), y, rect.width(), band_h),
                              self._blend(base_color, self._foc_color, 0.7))
            return

        painter.fillRect(rect, base_color)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        rect = self.rect()
        painter.fillRect(rect, QtGui.QColor(25, 25, 25))

        hilt_h = 24
        hilt_rect = QtCore.QRect(rect.width() // 2 - 10, rect.height() - hilt_h,
                                  20, hilt_h)
        painter.fillRect(hilt_rect, QtGui.QColor(90, 90, 90))

        blade_left = rect.width() // 2 - 4
        blade_top = 10
        blade_bottom = rect.height() - hilt_h
        blade_width = 8

        segments, style_brightness = self._lit_segments(blade_left, blade_top, blade_width, blade_bottom)

        color = self._base_color()
        if self._flicker_brightness != 1.0:
            color = self._scale_brightness(color, self._flicker_brightness)
        if style_brightness != 1.0:
            color = self._scale_brightness(color, style_brightness)
        if self._clash_intensity > 0:
            color = self._blend(color, self._foc_color, self._clash_intensity)

        style = self._current_style()
        position_dependent_idle = (
            self._idle_animation_active()
            and self._unstable_mode in ('wave', 'chase', 'knightrider', 'gradient')
        )

        for blade_rect in segments:
            if blade_rect.height() <= 0:
                continue

            glow = QtGui.QColor(color)
            glow.setAlpha(70)
            painter.fillRect(blade_rect.adjusted(-8, -4, 8, 0), glow)

            if position_dependent_idle:
                self._draw_idle_pattern(painter, blade_rect, color)
            elif style == 'crumble':
                self._draw_crumble(painter, blade_rect, color)
            elif style == 'chopped':
                self._draw_chopped(painter, blade_rect, color)
            elif style == 'comet':
                self._draw_comet(painter, blade_rect, color)
            elif style == 'fade_trail':
                self._draw_fade_trail(painter, blade_rect, color)
            elif style == 'base_flare':
                self._draw_base_flare(painter, blade_rect, color)
            elif style == 'full_flare':
                self._draw_full_flare(painter, blade_rect, color)
            else:
                painter.fillRect(blade_rect, color)

        if self._direction == -1 and style in ('sparkle_dust', 'sparkle_flake'):
            self._draw_retraction_sparkles(painter, blade_left, blade_top, blade_width, segments)
