# src/core/sound_player.py
"""Plays a soundfont's actual audio files for the blade preview panel's Ignite/Retract/
Clash/Lockup/Blaster Block buttons, so the preview matches this font's real sound as well as
its (approximate) visual behavior.

File naming follows the CFX convention: an action's sound is either a single '<action>.wav'
or a numbered set '<action><N>.wav' (confirmed against every font in test_cfx_folder - e.g.
poweron.wav+poweron2..7.wav, clash1..16.wav with no bare clash.wav, lockup.wav+lockup2..4.wav)
- one variant is chosen at random each time the action fires, the same idea the app already
uses for GraFx bitmap variants (see core/grafx_reader.py's 'many' handling). The match is
deliberately exact-prefix-plus-digits-only so it doesn't also catch unrelated files that
happen to share a prefix (e.g. poweronf.wav is a distinct effect, not a poweron variant, and
pwroff2.wav doesn't match 'poweroff' either).
"""
import random
import re
from pathlib import Path
from typing import List, Optional

from PySide6 import QtCore, QtMultimedia

# Loop channels can legitimately overlap (a lockup sustain layered on top of the idle hum),
# so each gets its own player rather than sharing one.
LOOP_CHANNELS = ('hum', 'lockup')


def find_sound_variants(font_path: Optional[Path], action: str) -> List[Path]:
    """Every '<action>.wav' / '<action><N>.wav' file for this action in a font folder."""
    if font_path is None or not Path(font_path).is_dir():
        return []
    pattern = re.compile(rf'^{re.escape(action)}(\d*)\.wav$', re.IGNORECASE)
    return sorted(p for p in Path(font_path).iterdir() if p.is_file() and pattern.match(p.name))


def pick_sound(font_path: Optional[Path], action: str) -> Optional[Path]:
    """One randomly-chosen variant for this action, or None if the font has none."""
    variants = find_sound_variants(font_path, action)
    return random.choice(variants) if variants else None


class SoundPlayer(QtCore.QObject):
    """One QSoundEffect for one-shot sounds (poweron/poweroff/clash/blaster/preon/postoff)
    plus one looping QMediaPlayer per entry in LOOP_CHANNELS (hum, lockup)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._effect = QtMultimedia.QSoundEffect(self)

        self._loop_players = {}
        self._loop_outputs = {}  # kept alive alongside their player - QAudioOutput has no parent
        for channel in LOOP_CHANNELS:
            player = QtMultimedia.QMediaPlayer(self)
            output = QtMultimedia.QAudioOutput(self)
            player.setAudioOutput(output)
            player.setLoops(QtMultimedia.QMediaPlayer.Infinite)
            self._loop_players[channel] = player
            self._loop_outputs[channel] = output

    def play_one_shot(self, font_path: Optional[Path], action: str) -> bool:
        """Play a random variant of this action's sound once. Returns False (no-op) if the
        font has no matching file."""
        sound_path = pick_sound(font_path, action)
        if sound_path is None:
            return False
        self._effect.setSource(QtCore.QUrl.fromLocalFile(str(sound_path)))
        self._effect.play()
        return True

    def start_loop(self, channel: str, font_path: Optional[Path], action: str) -> bool:
        """Start (or restart, with a freshly re-rolled variant) a looping channel. Returns
        False and stops the channel if the font has no matching file."""
        player = self._loop_players[channel]
        sound_path = pick_sound(font_path, action)
        if sound_path is None:
            player.stop()
            return False
        player.setSource(QtCore.QUrl.fromLocalFile(str(sound_path)))
        player.play()
        return True

    def stop_loop(self, channel: str):
        self._loop_players[channel].stop()

    def stop_all(self):
        self._effect.stop()
        for channel in self._loop_players:
            self.stop_loop(channel)
