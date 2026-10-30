# src/core/grafx_timing.py
"""Timing checks between GraFx animations, a font's sounds and the blade profile's
refreshfx - so an animation can be sized to its sound, and mismatches can be flagged.

What the manual (rev 1.19, "GraFx BMP size and sequence duration considerations") says:
- With delay unset or 0, the board spreads the BMP's stages over "the duration of the sound
  or the quick-on value" - power-on uses qon when it's set (its example is a 400 ms quick
  on), so likewise power-off uses qoff.
- Stages can't advance faster than the blade's refreshfx period: its example of 300 stages
  in a 400 ms quick-on with refreshfx=10 needs 1.33 ms per stage, "but in practice it's
  capped to 10, and the sequence will not be played entirely". Rule of thumb: stages =
  duration / refreshfx.
- For frame-accurate effects, set delay (20-40 ms) and make stages = sound duration / delay.

Sound file names per state (manual's sound list): poweron<N>.wav; poweroff<N>.wav plus the
alternate pwroff2.wav (played on a power-off while moving); preon<N>.wav; pstoff<N>.wav.
Looping states with a looping sound - Idle lit (humM<N>.wav) and Lockup (lockup<N>.wav) -
are matched to one loop of that sound; the blade-off Idle and Forever have no sound, so only
their delay is checked.
"""
import re
import wave
from pathlib import Path
from typing import Dict, List, Optional

from PySide6 import QtCore, QtGui

from core import grafx_reader

SOUND_ACTIONS = {
    'poweron': ('poweron',),
    'poweroff': ('poweroff', 'pwroff'),
    'preon': ('preon',),
    'postoff': ('pstoff',),
}
QUICK_PARAMS = {'poweron': 'qon', 'poweroff': 'qoff'}
# Looping states' sounds - same names the main window's blade preview plays. The sound loops
# for as long as the state lasts; a synced animation of one loop's length stays in step with
# it on every repeat, so it's what "match the sound" sizes these states to.
LOOP_SOUND_ACTIONS = {
    'leds': ('humM',),
    'lockup': ('lockup',),
}

_duration_cache: Dict[str, Optional[int]] = {}


def wav_duration_ms(path: Path) -> Optional[int]:
    key = str(path)
    if key not in _duration_cache:
        try:
            with wave.open(key, 'rb') as w:
                _duration_cache[key] = round(w.getnframes() * 1000 / w.getframerate())
        except (wave.Error, OSError, EOFError, ZeroDivisionError):
            _duration_cache[key] = None
    return _duration_cache[key]


def state_sounds(font_path: Optional[Path], state: str, actions=None) -> List[tuple]:
    """[(path, duration_ms)] of every sound that can play with this state."""
    actions = actions or SOUND_ACTIONS.get(state)
    if not actions or font_path is None or not Path(font_path).is_dir():
        return []
    pattern = re.compile(r'^(%s)(\d*)\.wav$' % '|'.join(map(re.escape, actions)), re.IGNORECASE)
    sounds = []
    for path in sorted(Path(font_path).iterdir()):
        if path.is_file() and pattern.match(path.name):
            duration = wav_duration_ms(path)
            if duration:
                sounds.append((path, duration))
    return sounds


def _int(settings: dict, key: str) -> Optional[int]:
    try:
        return int(str(settings.get(key, '')).split()[0])
    except (ValueError, IndexError):
        return None


class FontTiming:
    """The timing context of one font: its sounds plus the effective (global -> blade
    profile -> color -> font_config.txt) settings that matter here - refreshfx, qon, qoff."""

    def __init__(self, font_path: Optional[Path], settings: dict, label: str = None):
        self.font_path = Path(font_path) if font_path else None
        self.settings = settings or {}
        self.label = label or (self.font_path.name if self.font_path else "(no font)")
        refresh = _int(self.settings, 'refreshfx')
        self.refresh_ms = refresh if refresh and refresh > 0 else None

    def sounds(self, state: str) -> List[tuple]:
        return state_sounds(self.font_path, state)

    def loop_sounds(self, state: str) -> List[tuple]:
        """The hum (Idle lit) / lockup sounds that loop while a looping state plays."""
        actions = LOOP_SOUND_ACTIONS.get(state)
        return state_sounds(self.font_path, state, actions) if actions else []

    def basis(self, state: str) -> Optional[dict]:
        """What a synced (no delay) state is timed to: {'duration_ms' (shortest - the worst
        case), 'longest_ms', 'source' ('qon'/'qoff'/'sound'), 'description'}; None for
        states with nothing to sync to."""
        quick_param = QUICK_PARAMS.get(state)
        quick = _int(self.settings, quick_param) if quick_param else None
        sounds = self.sounds(state) or self.loop_sounds(state)
        looping = state in LOOP_SOUND_ACTIONS
        if quick and quick > 0:
            return {'duration_ms': quick, 'longest_ms': quick, 'source': quick_param,
                    'description': f"{quick_param}={quick} ms (quick-on/off is set, so the "
                                   f"board times this state to it rather than the sound)"}
        if not sounds:
            return None
        durations = [d for _p, d in sounds]
        low, high = min(durations), max(durations)
        span = f"{low} ms" if low == high else f"{low}–{high} ms"
        kind = f"{LOOP_SOUND_ACTIONS[state][0]} loop" if looping else "sound"
        return {'duration_ms': low, 'longest_ms': high, 'source': 'sound',
                'description': f"{len(sounds)} {kind} file(s), {span}"}

    def max_synced_stages(self, state: str) -> Optional[int]:
        """Most stages a synced animation can have and still play to the end every time."""
        basis = self.basis(state)
        if basis is None or not self.refresh_ms:
            return None
        return max(1, basis['duration_ms'] // self.refresh_ms)

    def effective_delay_ms(self, state: str, stages: int, delay_ms: Optional[int],
                           sound_ms: Optional[int] = None) -> Optional[float]:
        """How long each stage really lasts on the board. sound_ms picks one specific sound
        (e.g. the one the preview is playing) instead of the worst-case basis."""
        floor = self.refresh_ms or 0
        if delay_ms:
            return max(delay_ms, floor)
        basis = self.basis(state)
        if basis is None:
            return None
        duration = basis['duration_ms'] if basis['source'] != 'sound' or sound_ms is None else sound_ms
        return max(duration / max(1, stages), floor)

    def issues(self, state: str, stages: int, delay_ms: Optional[int]) -> List[dict]:
        """Timing problems for an animation of `stages` stages with this delay (None/0 =
        synced), as dicts with a 'message' plus what a fix needs:
        'too_many_stages' - synced, more stages than the basis allows: 'fits' stages,
            'needed_ms' per stage;
        'delay_too_fast' - delay below refreshfx: 'retimed_stages' at delay=refreshfx
            keeps the intended length."""
        refresh = self.refresh_ms
        if not refresh or stages <= 0:
            return []
        if delay_ms:
            if delay_ms >= refresh:
                return []
            return [{
                'kind': 'delay_too_fast', 'refresh': refresh, 'stages': stages, 'delay': delay_ms,
                'retimed_stages': max(1, round(stages * delay_ms / refresh)),
                'message':
                    f"delay={delay_ms} ms is faster than refreshfx={refresh} ms - the board can't "
                    f"advance a stage more often than every {refresh} ms, so the {stages} stages "
                    f"take about {stages * refresh} ms instead of {stages * delay_ms} ms."}]
        basis = self.basis(state)
        if basis is None:
            return []
        needed = basis['duration_ms'] / stages
        if needed >= refresh:
            return []
        fits = max(1, basis['duration_ms'] // refresh)
        what = (basis['source'] if basis['source'] != 'sound'
                else f"the shortest sound ({basis['duration_ms']} ms)")
        return [{
            'kind': 'too_many_stages', 'refresh': refresh, 'stages': stages, 'delay': None,
            'fits': fits, 'needed_ms': needed, 'basis_ms': basis['duration_ms'],
            'message':
                f"Synced to {what}: {stages} stages would need {needed:.1f} ms each, but "
                f"refreshfx is {refresh} ms - only about {fits} of the {stages} stages will "
                f"play. Keep it to {fits} stages or fewer, or set a delay."}]

    def check(self, state: str, stages: int, delay_ms: Optional[int]) -> List[str]:
        """Warning messages for an animation of `stages` stages with this delay."""
        return [issue['message'] for issue in self.issues(state, stages, delay_ms)]


def resample_stages(image: QtGui.QImage, stage_count: int) -> QtGui.QImage:
    """Stretch or squash an animation (BMP layout: one row per stage) to stage_count
    stages, keeping its shape over time. Nearest-neighbor, so colors stay exact."""
    stage_count = max(1, int(stage_count))
    if image.height() == stage_count:
        return QtGui.QImage(image)
    return image.convertToFormat(QtGui.QImage.Format_RGB32).scaled(
        image.width(), stage_count, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.FastTransformation)


def check_resource(folder: Path, timing: FontTiming) -> List[dict]:
    """Every timing warning for one GraFx resource folder against one font's timing:
    [{'state', 'file', 'path', 'folder', 'message', 'kind', ...}] (see FontTiming.issues) -
    each BMP variant of each active section."""
    results = []
    if folder is None or not folder.is_dir():
        return results
    for entry in grafx_reader.list_grafx_files(folder):
        settings = grafx_reader.section_settings(folder, entry.state)
        if settings is None:
            continue
        try:
            delay = int(settings.get('delay') or 0)
        except ValueError:
            delay = 0
        stages = QtGui.QImageReader(str(entry.path)).size().height()
        for issue in timing.issues(entry.state, stages, delay or None):
            results.append({'state': entry.state, 'file': entry.path.name, 'path': entry.path,
                            'folder': folder, **issue})
    return results
