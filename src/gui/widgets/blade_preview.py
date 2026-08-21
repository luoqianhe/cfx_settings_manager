# src/gui/widgets/blade_preview.py
import math
import random
from PySide6 import QtWidgets, QtCore, QtGui

from core.grafx_reader import load_grafx_state, stage_color

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
# styles have. 'grafx' (GraFx sequence) plays back this font's actual GraFx BMP resource, if
# one's linked (style_grafx1) and its grafx1.txt has a [POWERON]/[POWEROFF] section for it -
# see core/grafx_reader.py - falling back to a plain fill otherwise.
PON_STYLE_MAP = {
    '0': 'normal', '1': 'lightstick',
    '2': 'flare', '3': 'base_flare', '4': 'comet', '5': 'full_flare',
    '6': 'crumble', '7': 'comet', '8': 'comet', '9': 'comet', '10': 'grafx',
    '11': 'inverted', '12': 'split_in', '13': 'split_out', '14': 'chopped',
}
POFF_STYLE_MAP = {
    '0': 'normal', '1': 'lightstick',
    '2': 'crumble', '3': 'sparkle_dust', '4': 'comet', '5': 'crumble',
    '6': 'fade_trail', '7': 'sparkle_flake', '8': 'comet', '9': 'comet', '10': 'split_in',
    '11': 'grafx',
    '12': 'flare', '13': 'base_flare', '14': 'comet', '15': 'full_flare',
    '16': 'inverted', '17': 'chopped',
}

# unstable values this preview approximates, likewise grounded in the RICE Option names
# (BladeProfileConfig.json) rather than guessed. 'fire' is a rougher/warmer-tinted flicker for
# the named particle-sim styles that don't otherwise map to anything more specific here, and
# 'glitch' is an occasional hard dropout rather than a smooth brightness jitter - neither is a
# real recreation of what those styles actually look like, just a distinguishable stand-in.
# 'grafx' (GraFx playback, 17) and 'vision' (Visions/PoV fx, 18) both play back this font's
# actual GraFx BMP idle ([LEDS] section) if one's linked - see core/grafx_reader.py. Vision Fx
# is persistence-of-vision (spinning-dependent), which a static 2D preview can't really show,
# so it reuses the same idle bitmap as plain GraFx playback as the closest available stand-in.
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
    '11': 'fire',      # Sauron
    '12': 'fire',      # Sauron II
    '13': 'glitch',    # Jedi Fallen Order
    '14': 'knightrider',  # Knight Rider / Energy Beam
    '15': 'fire',      # Generative Unstable Fire
    '16': 'pulse',    # Bicolor Pulse Fx
    '17': 'grafx',    # GraFx powered blade
    '18': 'vision',   # Vision Fx (GraFx powered)
}

# style_blaster (Blaster Bolt Deflect) options, grounded in BladeProfileConfig.json. No
# documented fx duration parameter exists for this (unlike clash's focd), so
# BladePreviewWidget.BLASTER_DURATION_MS is a plausible fixed guess, not a read value.
BLASTER_STYLE_MAP = {
    '0': 'none',                              # Disable rendering
    '1': 'flash', '2': 'flash_soft',          # Legacy impact / Fading bolt (softer edges)
    '3': 'waves', '4': 'waves_tail',          # Splitting waves, with/without tailing
    '5': 'waves_flare', '6': 'waves_tail_flare',  # Splitting waves + impact flare, with/without tailing
    '7': 'energy', '8': 'energy_flare',       # Energy gradient, with/without a flaring center
}

# style_clash options, grounded in BladeProfileConfig.json's Options list for style_clash.
# "Local fade II" explicitly says it shares its position/length with localized lockup
# (style_lockup's pos_lockup/size_lockup), so that's the source used for it below. "Local
# fade" is described as changing randomly on the blade, so that one picks a fresh random
# band each clash instead. "Absorb" reads as the blade dimming from the hit rather than
# flaring - approximated as a brief darken-then-recover instead of a bright flash.
CLASH_STYLE_MAP = {
    '0': 'none',
    '1': 'flash_full', '2': 'flash_full',    # Legacy / Fade: whole blade flashes to FoC, decays back
    '3': 'flash_random',                     # Local fade: random band each clash
    '4': 'flash_localized',                  # Local fade II: shares pos_lockup/size_lockup
    '5': 'flash_base',                       # Base flare impact: hilt-end band
    '6': 'flash_rainbow',                    # Unicorn clash: rainbow, localized
    '7': 'flash_absorb',                     # Absorb: darkens instead of flaring
}

# style_lockup options, likewise grounded in BladeProfileConfig.json. 'grafx' (GraFx sequence)
# plays back this font's [LOCKUP] GraFx BMP if one's linked - see core/grafx_reader.py -
# falling back to Legacy (whole-blade tint) otherwise.
LOCKUP_STYLE_MAP = {
    '0': 'none', '1': 'legacy',
    '2': 'localized', '3': 'noise', '4': 'noise2',
    '5': 'flare', '6': 'rainbow', '7': 'grafx',
}

# style_preon/style_postoff options, grounded in parameters.json's Option descriptions. Only
# id 4 ('GraFx preon'/'GraFx post off') is rendered here - the other ids (Rey burst, base
# noise/candle, broken) are non-GraFx custom fx this preview doesn't approximate yet, so they
# fall back to 'none' (straight through to poweron/poweroff with no distinct pre/post phase).
PREON_STYLE_MAP = {
    '0': 'none', '1': 'none', '2': 'none', '3': 'none', '4': 'grafx', '5': 'none',
}
POSTOFF_STYLE_MAP = {
    '0': 'none', '1': 'none', '2': 'none', '3': 'none', '4': 'grafx', '5': 'none',
}


class BladePreviewWidget(QtWidgets.QWidget):
    """A rough visual preview of blade behavior - ignition/retraction, idle look, Clash/Lockup
    reactions, and Blaster Bolt Deflect.

    This is NOT a faithful simulation of what a real CFX-driven blade looks like - it's a set
    of rough, thematic guesses at what most style_pon/style_poff/style_clash/style_lockup/
    style_blaster/unstable values might look like (see the maps above), not recreations of
    their actual algorithms. GraFx (bitmap-driven) fx are the one exception: whenever a
    style_pon/poff/preon/postoff/lockup/unstable value selects "GraFx" and the font has a
    resource linked via style_grafx1, this plays back the font's real BMP animation instead of
    an approximation - see core/grafx_reader.py. Motion-driven fx (SmoothSwing) remain
    unmodeled, since there's genuinely nothing to approximate them from here. Treat everything
    else as a sanity-check for color, timing, and rough shape/mood - not a preview of the real
    hardware's appearance.
    """

    # Fires exactly when the blade finishes igniting (fill reaches 1.0) - the reliable way
    # to know that moment, since the actual duration can be longer than qon_ms alone (a
    # Pre-On phase runs first, or a GraFx-driven poweron paces itself by its own delay).
    ignited = QtCore.Signal()

    # Fire at the moment each of these phases actually starts playing, same reasoning as
    # `ignited` above - a caller (e.g. main_window's sound playback) can't just fire preon's
    # sound on the Ignite click and poweron's sound qon_ms later, since a Pre-On phase (when
    # one is configured and rendered - see PREON_STYLE_MAP) delays poweron by its own,
    # separately-timed duration. Post-Off is the mirror case, firing once retraction finishes
    # and a Post-Off phase begins.
    preon_started = QtCore.Signal()
    poweron_started = QtCore.Signal()
    postoff_started = QtCore.Signal()

    FRAME_MS = 33  # ~30fps
    CLASH_DECAY_MS = 350  # fallback used when this font doesn't set focd
    BLASTER_DURATION_MS = 450  # no documented fx duration param for this - a plausible guess
    PREON_FALLBACK_MS = 600  # no documented preon-sound duration param - a plausible guess
    POSTOFF_FALLBACK_MS = 600  # same, for the postoff/pstoff sound
    RAINBOW_PERIOD_S = 6.0
    PULSE_PERIOD_S = 1.6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(110, 260)

        self._color = QtGui.QColor(200, 200, 200)
        self._foc_color = QtGui.QColor(255, 255, 255)
        self._lockup_color = QtGui.QColor(255, 140, 0)
        self._bolt_color = QtGui.QColor(255, 60, 0)

        self._fill = 0.0  # 0.0 = fully retracted, 1.0 = fully ignited
        self._flicker_brightness = 1.0

        self._qon_ms = 300
        self._qoff_ms = 300
        self._flicker_on = False
        self._flicker_off = False
        self._pon_style = 'normal'
        self._poff_style = 'normal'
        self._unstable_mode = None  # None, 'rainbow', or 'pulse'
        self._clash_style = 'flash_full'
        self._lockup_style = 'legacy'
        self._blaster_style = 'flash'
        self._lockup_frac_pos = 0.35   # fraction of blade length from the hilt (pos_lockup/280)
        self._lockup_frac_size = 0.25  # fraction of blade length (size_lockup/280)
        self._clash_decay_ms = self.CLASH_DECAY_MS

        self._duration_ms = 300
        self._flicker_enabled = False
        self._direction = 0  # 1 = igniting, -1 = retracting, 0 = idle
        self._elapsed_ms = 0
        self._idle_phase_s = 0.0

        self._clash_intensity = 0.0  # 0..1, decays after clash()
        self._clash_band_pos = 0.4   # fraction from hilt, re-rolled per clash() for random styles
        self._clash_band_size = 0.22
        self._lockup_engaged = False

        self._blaster_active = False
        self._blaster_elapsed_ms = 0
        self._blaster_pos_frac = 0.5  # fraction from hilt, re-rolled per blaster_deflect()

        self._grafx_folder = None  # Path to this font's linked /extra/GRAFX/<n> folder, or None
        self._grafx_poweron_state = None   # GrafxState loaded fresh by ignite(), or None
        self._grafx_poweroff_state = None  # same, loaded fresh by retract()
        self._grafx_leds_state = None      # cached once idle-lit playback starts
        self._grafx_leds_attempted = False  # avoids re-reading disk every idle frame on a miss
        self._grafx_lockup_state = None    # cached once lockup engages

        # style_preon/style_postoff's GraFx option (id 4) - transient sequences that run
        # before poweron/after poweroff respectively, see ignite()/retract()/_begin_poweron()/
        # _begin_postoff(). Unlike poweron/poweroff there's no real sound-duration parameter
        # this app knows about to fall back to when delay is omitted from grafx1.txt, so
        # PREON/POSTOFF_FALLBACK_MS below are plausible guesses, same spirit as
        # BLASTER_DURATION_MS.
        self._preon_style = 'none'
        self._postoff_style = 'none'
        self._grafx_preon_state = None
        self._preon_active = False
        self._preon_elapsed_ms = 0
        self._preon_duration_ms = 0
        self._grafx_postoff_state = None
        self._postoff_active = False
        self._postoff_elapsed_ms = 0
        self._postoff_duration_ms = 0

        # [IDLE] - the blade-OFF idle loop (distinct from [LEDS], the blade-ON idle loop).
        # Per the manual, this plays whenever the saber reaches the OFF state and the linked
        # GraFx resource defines it, with no separate style_* selector gating it.
        self._grafx_idle_off_state = None
        self._grafx_idle_off_attempted = False

        # [FOREVER] - overrides every other sequence (poweron/poweroff/lockup/idle, on or
        # off) with one continuous loop, per the manual. Loaded eagerly in set_profile()
        # rather than lazily like the others, since it can be relevant in every state.
        self._grafx_forever_state = None

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._tick)

    def set_profile(self, rgb, qon_ms, qoff_ms, flicker_on, flicker_off,
                     foc_rgb=None, lockup_rgb=None, pon_style_id=None, poff_style_id=None,
                     unstable_id=None, clash_style_id=None, lockup_style_id=None,
                     pos_lockup=None, size_lockup=None, focd_ms=None,
                     bolt_rgb=None, blaster_style_id=None, grafx_folder=None,
                     preon_style_id=None, postoff_style_id=None):
        """Update the color/timing/style this preview animates with. Does not change
        whatever ignition state is currently being displayed. grafx_folder is this font's
        linked /extra/GRAFX/<n> folder (a Path, resolved from style_grafx1 by the caller), or
        None if it doesn't point anywhere real - see core/grafx_reader.py."""
        self._color = QtGui.QColor(*rgb)
        self._foc_color = QtGui.QColor(*foc_rgb) if foc_rgb else QtGui.QColor(255, 255, 255)
        self._lockup_color = QtGui.QColor(*lockup_rgb) if lockup_rgb else QtGui.QColor(255, 140, 0)
        self._bolt_color = QtGui.QColor(*bolt_rgb) if bolt_rgb else QtGui.QColor(255, 60, 0)
        self._qon_ms = max(1, qon_ms)
        self._qoff_ms = max(1, qoff_ms)
        self._flicker_on = flicker_on
        self._flicker_off = flicker_off
        self._pon_style = PON_STYLE_MAP.get(str(pon_style_id), 'normal')
        self._poff_style = POFF_STYLE_MAP.get(str(poff_style_id), 'normal')
        self._unstable_mode = UNSTABLE_MAP.get(str(unstable_id))
        self._clash_style = CLASH_STYLE_MAP.get(str(clash_style_id), 'flash_full')
        self._lockup_style = LOCKUP_STYLE_MAP.get(str(lockup_style_id), 'legacy')
        self._blaster_style = BLASTER_STYLE_MAP.get(str(blaster_style_id), 'flash')
        self._preon_style = PREON_STYLE_MAP.get(str(preon_style_id), 'none')
        self._postoff_style = POSTOFF_STYLE_MAP.get(str(postoff_style_id), 'none')

        # A new font may point at a different (or no) GraFx folder - drop anything cached
        # from the previous one so a stale bitmap can't linger.
        self._grafx_folder = grafx_folder
        self._grafx_poweron_state = None
        self._grafx_poweroff_state = None
        self._grafx_leds_state = None
        self._grafx_leds_attempted = False
        self._grafx_lockup_state = None
        self._grafx_preon_state = None
        self._preon_active = False
        self._grafx_postoff_state = None
        self._postoff_active = False
        self._grafx_idle_off_state = None
        self._grafx_idle_off_attempted = False
        # [FOREVER] applies in every state (on, off, transitioning), so - unlike the others -
        # it's loaded right away rather than lazily on first use.
        self._grafx_forever_state = (
            load_grafx_state(self._grafx_folder, 'forever') if self._grafx_folder is not None else None
        )
        self._lockup_frac_pos, self._lockup_frac_size = self._parse_localized(pos_lockup, size_lockup)
        try:
            self._clash_decay_ms = max(1, int(focd_ms))
        except (TypeError, ValueError):
            self._clash_decay_ms = self.CLASH_DECAY_MS
        self.update()
        self._sync_timer()

    @staticmethod
    def _parse_localized(pos, size):
        """pos_lockup/size_lockup are 0..280 addressable-pixel-index values (parameters.json) -
        normalize to 0..1 fractions of blade length, hilt-anchored (pixel 0 = hilt) same as
        this widget's own bottom-up fill direction. Falls back to a generic mid-blade band if
        unset or unparsable."""
        try:
            pos_f = max(0.0, min(1.0, int(pos) / 280.0))
        except (TypeError, ValueError):
            pos_f = 0.35
        try:
            size_f = max(0.02, min(1.0, int(size) / 280.0))
        except (TypeError, ValueError):
            size_f = 0.25
        return pos_f, size_f

    def ignite(self):
        if self._direction == 1 or self._preon_active:
            return
        self._grafx_idle_off_attempted = False  # leaving off-idle - re-check next time we're off
        if self._preon_style == 'grafx' and self._grafx_folder is not None:
            self._grafx_preon_state = load_grafx_state(self._grafx_folder, 'preon')
        else:
            self._grafx_preon_state = None
        if self._grafx_preon_state is not None:
            self._preon_active = True
            self._preon_elapsed_ms = 0
            self._preon_duration_ms = self._grafx_duration_ms(
                self._grafx_preon_state, self.PREON_FALLBACK_MS)
            self._sync_timer()
            self.update()
            self.preon_started.emit()
            return
        self._begin_poweron()

    def _begin_poweron(self):
        self._grafx_leds_attempted = False  # leaving idle - re-check for a GraFx idle loop next time
        self._grafx_poweron_state = None
        duration_ms = self._qon_ms
        if self._pon_style == 'grafx' and self._grafx_folder is not None:
            self._grafx_poweron_state = load_grafx_state(self._grafx_folder, 'poweron')
            duration_ms = self._grafx_duration_ms(self._grafx_poweron_state, self._qon_ms)
        self._start(direction=1, duration_ms=duration_ms, flicker=self._flicker_on)
        self.poweron_started.emit()

    def retract(self):
        if self._direction == -1 or self._postoff_active:
            return
        self._lockup_engaged = False
        self._grafx_lockup_state = None
        self._grafx_poweroff_state = None
        duration_ms = self._qoff_ms
        if self._poff_style == 'grafx' and self._grafx_folder is not None:
            self._grafx_poweroff_state = load_grafx_state(self._grafx_folder, 'poweroff')
            duration_ms = self._grafx_duration_ms(self._grafx_poweroff_state, self._qoff_ms)
        self._start(direction=-1, duration_ms=duration_ms, flicker=self._flicker_off)

    def _begin_postoff(self):
        self._grafx_idle_off_attempted = False
        if self._postoff_style == 'grafx' and self._grafx_folder is not None:
            self._grafx_postoff_state = load_grafx_state(self._grafx_folder, 'postoff')
        else:
            self._grafx_postoff_state = None
        if self._grafx_postoff_state is not None:
            self._postoff_active = True
            self._postoff_elapsed_ms = 0
            self._postoff_duration_ms = self._grafx_duration_ms(
                self._grafx_postoff_state, self.POSTOFF_FALLBACK_MS)
            self._sync_timer()
            self.postoff_started.emit()

    @staticmethod
    def _grafx_duration_ms(state, fallback_ms):
        """A one-shot GraFx sequence's real playback duration: stage_count * delay when the
        resource declares an explicit delay, otherwise (delay omitted/0) the manual says the
        firmware stretches it to match the sound/quick-on duration - so fall back to the
        already-known qon_ms/qoff_ms in that case."""
        if state is None:
            return fallback_ms
        if state.delay_ms is not None:
            return max(1, state.stage_count * state.delay_ms)
        return fallback_ms

    def clash(self):
        """Momentary Flash-on-Clash: a brief flash (or localized band, or darken - see
        CLASH_STYLE_MAP) that decays back over this font's configured focd duration."""
        if self._clash_style == 'none':
            return
        self._clash_intensity = 1.0
        if self._clash_style in ('flash_random', 'flash_rainbow'):
            self._clash_band_pos = random.uniform(0.05, 0.7)
            self._clash_band_size = random.uniform(0.15, 0.3)
        self._sync_timer()

    def blaster_deflect(self):
        """Momentary Blaster Bolt Deflect fx (style_blaster) at a random point along the
        blade - see BLASTER_STYLE_MAP for the render styles this approximates. Only
        meaningful while the blade is lit."""
        if self._blaster_style == 'none' or self._fill <= 0.0:
            return
        self._blaster_active = True
        self._blaster_elapsed_ms = 0
        self._blaster_pos_frac = random.uniform(0.15, 0.85)
        self._sync_timer()

    def toggle_lockup(self) -> bool:
        """Engage/disengage the lockup color mix (see LOCKUP_STYLE_MAP for the render styles
        this approximates). Returns the new engaged state."""
        if self._fill <= 0.0:
            return False  # nothing to lock up if the blade isn't lit
        self._lockup_engaged = not self._lockup_engaged
        if self._lockup_engaged and self._lockup_style == 'grafx' and self._grafx_folder is not None:
            self._grafx_lockup_state = load_grafx_state(self._grafx_folder, 'lockup')
        elif not self._lockup_engaged:
            self._grafx_lockup_state = None
        self._sync_timer()
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
        self._blaster_active = False
        self._grafx_poweron_state = None
        self._grafx_poweroff_state = None
        self._grafx_lockup_state = None
        self._grafx_leds_attempted = False
        self._preon_active = False
        self._grafx_preon_state = None
        self._postoff_active = False
        self._grafx_postoff_state = None
        self._grafx_idle_off_attempted = False
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
        """The blade-ON idle loop (unstable_id, [LEDS]) - active whenever the blade is fully
        lit, not mid-lockup, and a style is actually selected for it."""
        return (self._direction == 0 and self._fill >= 1.0
                and self._unstable_mode is not None and not self._lockup_engaged)

    def _off_idle_animation_active(self) -> bool:
        """The blade-OFF idle loop ([IDLE], distinct from [LEDS]) - per the manual this plays
        whenever the saber reaches the OFF state and the linked GraFx resource defines it, with
        no separate style_* selector gating it (unlike every other GraFx-driven state here)."""
        return (self._direction == 0 and self._fill <= 0.0
                and not self._preon_active and not self._postoff_active
                and self._grafx_folder is not None)

    def _sync_timer(self):
        should_run = (self._direction != 0 or self._clash_intensity > 0
                      or self._idle_animation_active() or self._lockup_engaged
                      or self._blaster_active or self._preon_active or self._postoff_active
                      or self._grafx_forever_state is not None
                      or self._off_idle_animation_active())
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
                if was_igniting:
                    self.ignited.emit()
                if not was_igniting:
                    self._begin_postoff()

        if self._preon_active:
            self._preon_elapsed_ms += self.FRAME_MS
            if self._preon_elapsed_ms >= self._preon_duration_ms:
                self._preon_active = False
                self._begin_poweron()

        if self._postoff_active:
            self._postoff_elapsed_ms += self.FRAME_MS
            if self._postoff_elapsed_ms >= self._postoff_duration_ms:
                self._postoff_active = False
                self._grafx_postoff_state = None

        if self._clash_intensity > 0:
            self._clash_intensity = max(
                0.0, self._clash_intensity - self.FRAME_MS / self._clash_decay_ms
            )

        if self._blaster_active:
            self._blaster_elapsed_ms += self.FRAME_MS
            if self._blaster_elapsed_ms >= self.BLASTER_DURATION_MS:
                self._blaster_active = False

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
        if self._idle_animation_active():
            if self._unstable_mode == 'rainbow':
                hue = (self._idle_phase_s / self.RAINBOW_PERIOD_S) % 1.0
                return QtGui.QColor.fromHsvF(hue, 1.0, 1.0)
            if self._unstable_mode == 'pulse':
                t = (math.sin(self._idle_phase_s * (2 * math.pi / self.PULSE_PERIOD_S)) + 1) / 2
                return self._blend(self._color, self._foc_color, t)
            if self._unstable_mode == 'flicker':
                return self._scale_brightness(self._color, random.uniform(0.5, 1.0))
            if self._unstable_mode == 'fire':
                # Rougher and warmer than plain flicker: brightness jitter plus an occasional
                # shift toward an orange/ember tone, distinguishing the named particle-sim
                # styles (Sauron/Sauron II/Generative Unstable Fire) from simple flicker.
                warm = self._blend(self._color, QtGui.QColor(255, 120, 0), random.uniform(0.0, 0.4))
                return self._scale_brightness(warm, random.uniform(0.55, 1.0))
            if self._unstable_mode == 'glitch':
                # Occasional hard dropout rather than a smooth jitter - reads as corrupted/
                # glitchy rather than a natural flicker.
                if random.random() < 0.12:
                    return self._scale_brightness(self._color, random.uniform(0.05, 0.25))
                return self._color

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

    def _localized_band(self, top, bottom, pos_frac, size_frac):
        """A QRect band within [top, bottom], anchored the same hilt-relative way pos_lockup/
        size_lockup are (pos_frac=0 sits right at the hilt end, i.e. rect.bottom())."""
        full_h = bottom - top
        band_h = max(4, int(full_h * size_frac))
        band_bottom = bottom - int(full_h * pos_frac)
        band_top = max(top, band_bottom - band_h)
        band_bottom = min(bottom, max(band_top + 1, band_bottom))
        return band_top, band_bottom

    def _draw_lockup(self, painter, rect, color, left, width):
        """Blade Lockup: the lockup parameter's own description mentions 'shimmering applied
        to the high-power LED', so every style below gets a persistent, gentle brightness
        flicker layered on top of whatever it draws. style_lockup maps to LOCKUP_STYLE_MAP -
        'legacy' tints the whole blade toward the lockup color (this widget's original lockup
        look, kept as the fallback); the rest localize the effect to a pos_lockup/size_lockup
        band instead of recoloring the whole blade, per the RICE schema's option descriptions."""
        shimmer = random.uniform(0.85, 1.0)

        if self._lockup_style == 'none':
            painter.fillRect(rect, self._scale_brightness(color, shimmer))
            return

        if self._lockup_style == 'legacy':
            tinted = self._blend(color, self._lockup_color, 0.5)
            painter.fillRect(rect, self._scale_brightness(tinted, shimmer))
            return

        painter.fillRect(rect, self._scale_brightness(color, shimmer))

        band_top, band_bottom = self._localized_band(
            rect.top(), rect.bottom(), self._lockup_frac_pos, self._lockup_frac_size
        )
        band = QtCore.QRect(left, band_top, width, band_bottom - band_top)

        if self._lockup_style == 'noise':
            self._draw_crumble(painter, band, self._lockup_color)
        elif self._lockup_style == 'noise2':
            self._draw_chopped(painter, band, self._lockup_color)
        elif self._lockup_style == 'flare':
            gradient = QtGui.QLinearGradient(band.left(), band.top(), band.left(), band.bottom())
            mid = self._blend(self._lockup_color, self._foc_color, 0.6)
            gradient.setColorAt(0.0, self._lockup_color)
            gradient.setColorAt(0.5, mid)
            gradient.setColorAt(1.0, self._lockup_color)
            painter.fillRect(band, QtGui.QBrush(gradient))
        elif self._lockup_style == 'rainbow':
            hue = (self._idle_phase_s / 2.0) % 1.0
            painter.fillRect(band, QtGui.QColor.fromHsvF(hue, 1.0, 1.0))
        else:
            painter.fillRect(band, self._lockup_color)

    def _draw_localized_clash(self, painter, left, top, width, bottom):
        """Overlay for the style_clash styles that flash a specific band rather than the
        whole blade (see CLASH_STYLE_MAP) - drawn last so it visibly sits on top of the
        ignition/lockup/idle rendering underneath, and fades out as _clash_intensity decays."""
        if self._clash_intensity <= 0 or self._clash_style not in (
            'flash_random', 'flash_localized', 'flash_base', 'flash_rainbow'
        ):
            return

        if self._clash_style == 'flash_base':
            pos_f, size_f = 0.0, 0.3
        elif self._clash_style == 'flash_localized':
            pos_f, size_f = self._lockup_frac_pos, self._lockup_frac_size
        else:  # flash_random, flash_rainbow
            pos_f, size_f = self._clash_band_pos, self._clash_band_size

        band_top, band_bottom = self._localized_band(top, bottom, pos_f, size_f)
        rect = QtCore.QRect(left, band_top, width, band_bottom - band_top)

        if self._clash_style == 'flash_rainbow':
            hue = (self._idle_phase_s / 1.5) % 1.0  # fast cycle - "Unicorn" reads flashy
            tint = QtGui.QColor.fromHsvF(hue, 1.0, 1.0)
        else:
            tint = self._foc_color

        overlay = QtGui.QColor(tint)
        overlay.setAlpha(int(220 * self._clash_intensity))
        painter.fillRect(rect, overlay)

    @staticmethod
    def _alpha_color(color: QtGui.QColor, alpha_frac: float) -> QtGui.QColor:
        c = QtGui.QColor(color)
        c.setAlpha(max(0, min(255, int(255 * alpha_frac))))
        return c

    def _draw_blaster(self, painter, left, top, width, bottom):
        """Overlay for Blaster Bolt Deflect (style_blaster, see BLASTER_STYLE_MAP), drawn last
        so it sits on top of everything else, at the random point blaster_deflect() picked.
        progress runs 0->1 over BLASTER_DURATION_MS (a guessed duration - see its definition);
        fade is progress's complement, used to decay alpha as the effect plays out."""
        if not self._blaster_active or self._blaster_style == 'none':
            return

        full_h = bottom - top
        if full_h <= 0:
            return

        progress = min(1.0, self._blaster_elapsed_ms / self.BLASTER_DURATION_MS)
        fade = 1.0 - progress
        impact_y = bottom - int(full_h * self._blaster_pos_frac)
        style = self._blaster_style

        if style in ('flash', 'flash_soft'):
            band_h = max(6, int(full_h * 0.12))
            if style == 'flash_soft':
                halo = QtCore.QRect(left, impact_y - band_h, width, band_h * 2)
                painter.fillRect(halo, self._alpha_color(self._bolt_color, 0.35 * fade))
            rect = QtCore.QRect(left, impact_y - band_h // 2, width, band_h)
            painter.fillRect(rect, self._alpha_color(self._bolt_color, fade))
            return

        if style in ('energy', 'energy_flare'):
            radius = int(full_h * 0.4 * progress)
            rect = QtCore.QRect(left, max(top, impact_y - radius), width, min(full_h, radius * 2))
            painter.fillRect(rect, self._alpha_color(self._bolt_color, 0.5 * fade))
            if style == 'energy_flare':
                core = QtCore.QRect(left, impact_y - 4, width, 8)
                painter.fillRect(core, self._alpha_color(self._bolt_color, fade))
            return

        # waves / waves_tail / waves_flare / waves_tail_flare: two thin bands travel apart
        # from the impact point (one toward the tip, one toward the hilt) as progress advances;
        # the "tail" variants also shade in the region each wave has already crossed.
        travel = int(full_h * 0.5 * progress)
        band_h = max(4, int(full_h * 0.05))
        for direction in (-1, 1):
            wave_y = max(top, min(bottom - band_h, impact_y + direction * travel))
            painter.fillRect(QtCore.QRect(left, wave_y, width, band_h),
                              self._alpha_color(self._bolt_color, fade))
            if style in ('waves_tail', 'waves_tail_flare'):
                tail_top = wave_y if direction == -1 else impact_y
                tail_bottom = impact_y if direction == -1 else wave_y + band_h
                tail_top, tail_bottom = max(top, tail_top), min(bottom, tail_bottom)
                if tail_bottom > tail_top:
                    painter.fillRect(QtCore.QRect(left, tail_top, width, tail_bottom - tail_top),
                                      self._alpha_color(self._bolt_color, 0.25 * fade))

        if style in ('waves_flare', 'waves_tail_flare'):
            flare_rect = QtCore.QRect(left, impact_y - band_h, width, band_h * 2)
            painter.fillRect(flare_rect, self._alpha_color(self._bolt_color, fade))

    def _grafx_stage_index(self, state, elapsed_ms=None, duration_ms=None) -> int:
        """Stage index for a one-shot GraFx sequence. Defaults to this widget's own
        elapsed_ms/duration_ms ignition progress (poweron/poweroff, sized by ignite()/
        retract() via _grafx_duration_ms()); preon/postoff pass their own elapsed/duration
        pair instead, since those run outside the direction/fill state machine."""
        if elapsed_ms is None:
            elapsed_ms = self._elapsed_ms
        if duration_ms is None:
            duration_ms = self._duration_ms
        stages = state.stage_count
        if stages <= 1 or duration_ms <= 0:
            return 0
        progress = min(1.0, elapsed_ms / duration_ms)
        return min(stages - 1, int(progress * stages))

    def _grafx_loop_stage_index(self, state) -> int:
        """Stage index for a looping GraFx sequence ([LEDS]/[LOCKUP]), paced by its own
        declared delay - falling back to a generic 100ms/stage if the section omits one,
        since (unlike poweron/poweroff) there's no sound/quick-on duration to sync a loop to."""
        stages = state.stage_count
        if stages <= 1:
            return 0
        delay_ms = state.delay_ms or 100
        elapsed_ms = self._idle_phase_s * 1000.0
        return int(elapsed_ms / delay_ms) % stages

    def _draw_grafx_bitmap(self, painter, left, top, width, bottom, image, stage_index):
        """Render one animation stage of a real GraFx BMP across the full blade extent - each
        BMP column drives its own blade-pixel position (column 0 = hilt-end pixel), independent
        of this widget's own fill/style logic, since the bitmap itself already encodes whatever
        growth/motion look its author designed (see core/grafx_reader.py)."""
        full_h = bottom - top
        cols = image.width()
        if full_h <= 0 or cols <= 0:
            return
        for c in range(cols):
            y0 = bottom - int(full_h * (c + 1) / cols)
            y1 = bottom - int(full_h * c / cols)
            if y1 <= y0:
                continue
            color = stage_color(image, stage_index, c / max(1, cols - 1))
            painter.fillRect(QtCore.QRect(left, y0, width, y1 - y0), color)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        rect = self.rect()
        painter.fillRect(rect, QtGui.QColor(25, 25, 25))

        hilt_h = 24
        hilt_width = 34
        hilt_rect = QtCore.QRect(rect.width() // 2 - hilt_width // 2, rect.height() - hilt_h,
                                  hilt_width, hilt_h)
        painter.fillRect(hilt_rect, QtGui.QColor(90, 90, 90))

        blade_width = 26  # wide enough that fine-grained styles (crumble/chopped/noise) read clearly
        blade_left = rect.width() // 2 - blade_width // 2
        blade_top = 10
        blade_bottom = rect.height() - hilt_h

        segments, style_brightness = self._lit_segments(blade_left, blade_top, blade_width, blade_bottom)

        base_color = self._base_color()
        if self._flicker_brightness != 1.0:
            base_color = self._scale_brightness(base_color, self._flicker_brightness)
        if style_brightness != 1.0:
            base_color = self._scale_brightness(base_color, style_brightness)

        # Only the whole-blade clash styles (flash_full/flash_absorb) bake into the base
        # color here; the localized ones (random/localized/base/rainbow) are layered on top
        # afterward by _draw_localized_clash so they don't tint the rest of the blade.
        if self._clash_intensity > 0:
            if self._clash_style == 'flash_full':
                base_color = self._blend(base_color, self._foc_color, self._clash_intensity)
            elif self._clash_style == 'flash_absorb':
                base_color = self._blend(base_color, QtGui.QColor(0, 0, 0), self._clash_intensity)

        color = base_color
        style = self._current_style()
        position_dependent_idle = (
            self._idle_animation_active()
            and self._unstable_mode in ('wave', 'chase', 'knightrider', 'gradient')
        )

        # GraFx-driven states bypass the normal fill/style rendering entirely: the bitmap
        # already encodes its own growth/motion across the whole blade extent, so there's no
        # separate "segment" to compute the way the synthetic styles above need. Falls
        # through to the normal rendering below if no GraFx resource is actually available
        # for the relevant state (folder unlinked, section missing, BMP not found, etc).
        # [FOREVER] takes priority over everything else, per the manual - one continuous loop
        # regardless of what state (on/off/transitioning) the saber is actually in.
        grafx_handled = False
        if self._grafx_forever_state is not None:
            stage = self._grafx_loop_stage_index(self._grafx_forever_state)
            self._draw_grafx_bitmap(painter, blade_left, blade_top, blade_width, blade_bottom,
                                     self._grafx_forever_state.image, stage)
            grafx_handled = True
        elif self._preon_active and self._grafx_preon_state is not None:
            stage = self._grafx_stage_index(
                self._grafx_preon_state, self._preon_elapsed_ms, self._preon_duration_ms)
            self._draw_grafx_bitmap(painter, blade_left, blade_top, blade_width, blade_bottom,
                                     self._grafx_preon_state.image, stage)
            grafx_handled = True
        elif self._direction == 1 and self._pon_style == 'grafx' and self._grafx_poweron_state is not None:
            stage = self._grafx_stage_index(self._grafx_poweron_state)
            self._draw_grafx_bitmap(painter, blade_left, blade_top, blade_width, blade_bottom,
                                     self._grafx_poweron_state.image, stage)
            grafx_handled = True
        elif self._direction == -1 and self._poff_style == 'grafx' and self._grafx_poweroff_state is not None:
            stage = self._grafx_stage_index(self._grafx_poweroff_state)
            self._draw_grafx_bitmap(painter, blade_left, blade_top, blade_width, blade_bottom,
                                     self._grafx_poweroff_state.image, stage)
            grafx_handled = True
        elif self._postoff_active and self._grafx_postoff_state is not None:
            stage = self._grafx_stage_index(
                self._grafx_postoff_state, self._postoff_elapsed_ms, self._postoff_duration_ms)
            self._draw_grafx_bitmap(painter, blade_left, blade_top, blade_width, blade_bottom,
                                     self._grafx_postoff_state.image, stage)
            grafx_handled = True
        elif self._lockup_engaged and self._lockup_style == 'grafx' and self._grafx_lockup_state is not None:
            stage = self._grafx_loop_stage_index(self._grafx_lockup_state)
            self._draw_grafx_bitmap(painter, blade_left, blade_top, blade_width, blade_bottom,
                                     self._grafx_lockup_state.image, stage)
            grafx_handled = True
        elif self._idle_animation_active() and self._unstable_mode in ('grafx', 'vision'):
            if self._grafx_leds_state is None and not self._grafx_leds_attempted:
                self._grafx_leds_attempted = True
                if self._grafx_folder is not None:
                    self._grafx_leds_state = load_grafx_state(self._grafx_folder, 'leds')
            if self._grafx_leds_state is not None:
                stage = self._grafx_loop_stage_index(self._grafx_leds_state)
                self._draw_grafx_bitmap(painter, blade_left, blade_top, blade_width, blade_bottom,
                                         self._grafx_leds_state.image, stage)
                grafx_handled = True
        elif self._off_idle_animation_active():
            if self._grafx_idle_off_state is None and not self._grafx_idle_off_attempted:
                self._grafx_idle_off_attempted = True
                self._grafx_idle_off_state = load_grafx_state(self._grafx_folder, 'idle')
            if self._grafx_idle_off_state is not None:
                stage = self._grafx_loop_stage_index(self._grafx_idle_off_state)
                self._draw_grafx_bitmap(painter, blade_left, blade_top, blade_width, blade_bottom,
                                         self._grafx_idle_off_state.image, stage)
                grafx_handled = True

        if not grafx_handled:
            for blade_rect in segments:
                if blade_rect.height() <= 0:
                    continue

                glow = QtGui.QColor(color)
                glow.setAlpha(70)
                painter.fillRect(blade_rect.adjusted(-10, -4, 10, 0), glow)

                if self._lockup_engaged:
                    self._draw_lockup(painter, blade_rect, color, blade_left, blade_width)
                elif position_dependent_idle:
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

        if not grafx_handled and self._direction == -1 and style in ('sparkle_dust', 'sparkle_flake'):
            self._draw_retraction_sparkles(painter, blade_left, blade_top, blade_width, segments)

        if not self._lockup_engaged:
            self._draw_localized_clash(painter, blade_left, blade_top, blade_width, blade_bottom)

        self._draw_blaster(painter, blade_left, blade_top, blade_width, blade_bottom)
