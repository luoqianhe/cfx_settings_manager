# src/core/grafx_reader.py
"""Reads real GraFx resource folders (/extra/GRAFX/<n>-name/) from a loaded CFX SD card: the
grafx1.txt config file (per-state playback settings) and the BMP sequence files themselves,
so the blade preview can play back a font's *actual* GraFx animation instead of falling back
to a plain color.

Grounded in a manual transcript the user provided ("detailed grafx explanation.txt") and
cross-checked against the real resource folders under test_cfx_folder/extra/GRAFX - notably
that the config file is literally named grafx1.txt (not grafx.txt) in every folder, and that
a couple of states' section header spelling doesn't match their BMP file prefix (idle-lit is
section [LEDS] but files are named normal<N>.bmp; post-off is section [POSTOFF] but files are
pstoff<N>.bmp).

BMP layout: width = number of blade pixels (one column per pixel), height = number of
animation stages. The manual states stages are read "from the bottom left corner... bottom-up",
so stage 0 is the BMP's bottom row (highest y in Qt's top-down QImage coordinates), and later
stages move upward through the image.
"""
import random
import re
from pathlib import Path
from typing import Optional

from PySide6 import QtGui

# state name -> (config section name, BMP filename prefix)
GRAFX_STATES = {
    'poweron': ('POWERON', 'poweron'),
    'poweroff': ('POWEROFF', 'poweroff'),
    'leds': ('LEDS', 'normal'),      # blade-on idle loop
    'lockup': ('LOCKUP', 'lockup'),
    'preon': ('PREON', 'preon'),
    'postoff': ('POSTOFF', 'pstoff'),
    'idle': ('IDLE', 'idle'),        # blade-off idle loop
    'forever': ('FOREVER', 'forever'),
}

_SECTION_RE = re.compile(r'^\[(\w+)\]$')


def parse_grafx_config(txt_path: Path) -> dict:
    """Parse a grafx1.txt into {SECTION_NAME: {key: value}}. Lines starting with '#'
    (including the file format's '##' convention for commenting out both whole sections and
    individual disabled parameters) are ignored."""
    sections = {}
    current = None
    try:
        text = txt_path.read_text(errors='replace')
    except OSError:
        return sections
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        m = _SECTION_RE.match(line)
        if m:
            current = m.group(1).upper()
            sections[current] = {}
            continue
        if current is not None and '=' in line:
            key, _, value = line.partition('=')
            sections[current][key.strip().lower()] = value.strip()
    return sections


def _pick_bmp_path(folder: Path, file_prefix: str, many: int) -> Optional[Path]:
    """many BMP files can exist for a state (poweron1.bmp, poweron2.bmp, ...) - the manual
    says one is "randomly chosen each time you get in a particular state"."""
    many = max(1, many)
    index = random.randint(1, many)
    path = folder / f"{file_prefix}{index}.bmp"
    if path.is_file():
        return path
    # 'many' in grafx1.txt not matching what's actually on disk - fall back to #1.
    fallback = folder / f"{file_prefix}1.bmp"
    return fallback if fallback.is_file() else None


class GrafxState:
    """One playback-ready state: the loaded BMP image plus its declared timing.

    delay_ms is None when the config omits it or sets it to 0, meaning (per the manual)
    "the duration of the sound or the quick-on value is used to calculate the playback
    speed" - callers should spread the image's rows across their own known duration
    (e.g. qon_ms) instead."""
    __slots__ = ('image', 'delay_ms', 'stop')

    def __init__(self, image: QtGui.QImage, delay_ms: Optional[int], stop: bool):
        self.image = image
        self.delay_ms = delay_ms
        self.stop = stop

    @property
    def stage_count(self) -> int:
        return self.image.height()


def load_grafx_state(folder: Path, state: str) -> Optional[GrafxState]:
    """Load one playback state ('poweron', 'poweroff', 'leds', 'lockup', ...) from a GraFx
    resource folder. Returns None if the folder, its grafx1.txt, the section (commented out
    or absent), or the BMP file itself isn't present/usable - callers should fall back to
    their own existing plain-color rendering in that case."""
    if state not in GRAFX_STATES or folder is None:
        return None
    section_name, file_prefix = GRAFX_STATES[state]

    config_path = folder / 'grafx1.txt'
    if not config_path.is_file():
        return None
    sections = parse_grafx_config(config_path)
    section = sections.get(section_name)
    if section is None:
        return None

    try:
        many = int(section.get('many', '1'))
    except ValueError:
        many = 1
    bmp_path = _pick_bmp_path(folder, file_prefix, many)
    if bmp_path is None:
        return None

    image = QtGui.QImage(str(bmp_path))
    if image.isNull() or image.width() == 0 or image.height() == 0:
        return None

    delay_ms = None
    if 'delay' in section:
        try:
            parsed = int(section['delay'])
            delay_ms = parsed if parsed > 0 else None
        except ValueError:
            delay_ms = None

    stop = section.get('stop', '0').strip() == '1'
    return GrafxState(image, delay_ms, stop)


def stage_color(image: QtGui.QImage, stage_index: int, column_frac: float) -> QtGui.QColor:
    """The color of one blade position (column_frac: 0.0 = hilt-end pixel, 1.0 = tip-end
    pixel) at a given animation stage. Stage 0 is the BMP's bottom row per the "bottom-up"
    read order the manual describes; QImage's row 0 is the image's top, so stage_index counts
    upward from image.height()-1."""
    stage_index = max(0, min(image.height() - 1, stage_index))
    row = image.height() - 1 - stage_index
    col = max(0, min(image.width() - 1, int(round(column_frac * (image.width() - 1)))))
    return QtGui.QColor(image.pixel(col, row))
