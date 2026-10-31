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


_PREFIX_TO_STATE = {prefix: state for state, (_section, prefix) in GRAFX_STATES.items()}
_BMP_NAME_RE = re.compile(r'^([a-z]+)(\d+)\.bmp$', re.IGNORECASE)


class GrafxFileEntry:
    """One BMP file found in a GraFx resource folder, for the resource editor's file list -
    unlike load_grafx_state (which picks a random variant, as playback does), this names one
    exact file so it can be opened and saved back individually."""
    __slots__ = ('state', 'variant', 'path')

    def __init__(self, state: str, variant: int, path: Path):
        self.state = state
        self.variant = variant
        self.path = path


def list_grafx_files(folder: Path) -> list:
    """Every recognised <prefix><N>.bmp in a resource folder, sorted by GRAFX_STATES order
    then variant number. Files whose prefix isn't a known state (stray BMPs) are skipped."""
    entries = []
    if folder is None or not folder.is_dir():
        return entries
    for path in folder.iterdir():
        m = _BMP_NAME_RE.match(path.name)
        if not m or not path.is_file():
            continue
        state = _PREFIX_TO_STATE.get(m.group(1).lower())
        if state is None:
            continue
        entries.append(GrafxFileEntry(state, int(m.group(2)), path))
    order = list(GRAFX_STATES)
    entries.sort(key=lambda e: (order.index(e.state), e.variant))
    return entries


def section_settings(folder: Path, state: str) -> Optional[dict]:
    """The active (not ##-commented) grafx1.txt section for a state as {key: value}, or None
    if the section is absent/commented out. Also returns a parsed 'accents_count' - the
    length of the accents=aaa... string, i.e. how many pixels the section declares, which the
    BMPs' width is supposed to match."""
    if state not in GRAFX_STATES or folder is None:
        return None
    section = parse_grafx_config(folder / 'grafx1.txt').get(GRAFX_STATES[state][0])
    if section is None:
        return None
    result = dict(section)
    accents = section.get('accents')
    result['accents_count'] = len(accents) if accents else None
    return result


_DISABLED_HEADER_RE = re.compile(r'^##\s*\[(\w+)\]\s*$')
_DISABLED_PARAM_RE = re.compile(r'^##\s*([A-Za-z_]\w*)\s*=(.*)$')


def many_problems(folder: Path) -> list:
    """Active sections whose many= doesn't match their BMP files - the board loads only
    <prefix>1..many.bmp, so a missing many= (or one that's too low) leaves files unplayed and
    one that's too high points at files that don't exist. Sections with no files at all are
    skipped: stock resources ship placeholder sections like that.
    [{'state', 'section', 'many' (int or None), 'available' (N files numbered 1..N),
      'files' (every variant number found)}]"""
    problems = []
    variants = {}
    for entry in list_grafx_files(folder):
        variants.setdefault(entry.state, []).append(entry.variant)
    config = parse_grafx_config(folder / 'grafx1.txt')
    for state, (section_name, _prefix) in GRAFX_STATES.items():
        section = config.get(section_name)
        found = sorted(variants.get(state, []))
        if section is None or not found:
            continue
        available = 0
        while available + 1 in found:
            available += 1
        try:
            many = int(section['many']) if 'many' in section else None
        except ValueError:
            many = None
        if many != available or available != len(found):
            problems.append({'state': state, 'section': section_name, 'many': many,
                             'available': available, 'files': found})
    return problems


def many_message(problem: dict) -> str:
    """A sentence explaining a many_problems() entry."""
    section, prefix = problem['section'], GRAFX_STATES[problem['state']][1]
    many, available, files = problem['many'], problem['available'], problem['files']
    names = ", ".join(f"{prefix}{n}.bmp" for n in files)
    if available != len(files):
        return (f"[{section}] files are {names} - they must be numbered from 1 with no gaps; "
                f"the board can only reach {prefix}1-{available}.bmp."
                if available else f"[{section}] has {names} but no {prefix}1.bmp, so the board "
                                  f"finds none of them.")
    if many is None:
        return (f"[{section}] has no many= line, so the board doesn't load {names} - this "
                f"animation never plays.")
    if many > available:
        return (f"[{section}] says many={many} but only {available} file(s) exist ({names}) - "
                f"the board will look for files that aren't there.")
    return (f"[{section}] says many={many} but there are {available} files ({names}) - the "
            f"extra ones never play.")


def section_status(folder: Path, state: str) -> str:
    """'active', 'disabled' (only present as a ##[SECTION] commented-out block, like the
    stock [FOREVER]) or 'missing'."""
    if state not in GRAFX_STATES or folder is None:
        return 'missing'
    section_name = GRAFX_STATES[state][0]
    if section_name in parse_grafx_config(folder / 'grafx1.txt'):
        return 'active'
    return 'disabled' if disabled_section_values(folder, state) is not None else 'missing'


def disabled_section_values(folder: Path, state: str) -> Optional[dict]:
    """The key=value lines of a ##-commented-out section (with one level of ## removed), so
    a disabled section's settings can still be shown - or None if there's no such block."""
    section_name = GRAFX_STATES[state][0]
    try:
        lines = (folder / 'grafx1.txt').read_text(errors='replace').splitlines()
    except OSError:
        return None
    values = None
    for raw_line in lines:
        line = raw_line.strip()
        header = _DISABLED_HEADER_RE.match(line) or _SECTION_RE.match(line)
        if header:
            if values is not None:
                break
            if line.startswith('#') and header.group(1).upper() == section_name:
                values = {}
            continue
        if values is not None:
            m = _DISABLED_PARAM_RE.match(line)
            if m and not line.startswith('####'):
                values[m.group(1).lower()] = m.group(2).strip()
    return values
