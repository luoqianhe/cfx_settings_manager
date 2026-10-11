# src/core/grafx_writer.py
"""Generates GraFx resource folders (/extra/GRAFX/<n>-name/) from a handful of presets, for
the GraFx Creator wizard (gui/grafx_creator_dialog.py). This is the inverse of
core/grafx_reader.py - same file layout (grafx1.txt + <prefix><N>.bmp files), same bottom-up
stage/row convention, same section-name/file-prefix table (GRAFX_STATES) - so anything written
here round-trips cleanly back through grafx_reader.load_grafx_state().
"""
import random
import re
import shutil
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from PySide6 import QtCore, QtGui

from core.grafx_reader import GRAFX_STATES

RGB = Tuple[int, int, int]


def _build_stage_image(width: int, stage_count: int,
                        stage_pixel_fn: Callable[[int, int], RGB]) -> QtGui.QImage:
    """Build a QImage where stage_pixel_fn(stage_index, pixel_index) -> (r, g, b) supplies
    each pixel's color. Stage 0 is written to the bottom row, matching grafx_reader.
    stage_color()'s read-side convention (row = stage_count - 1 - stage_index), so a preset
    generated here and one already on disk look identical once loaded back."""
    width = max(1, width)
    stage_count = max(1, stage_count)
    image = QtGui.QImage(width, stage_count, QtGui.QImage.Format_RGB32)
    for stage in range(stage_count):
        row = stage_count - 1 - stage
        for pixel in range(width):
            r, g, b = stage_pixel_fn(stage, pixel)
            image.setPixel(pixel, row, QtGui.qRgb(
                max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
            ))
    return image


def generate_solid_fade(width: int, stage_count: int, start_rgb: RGB, end_rgb: RGB) -> QtGui.QImage:
    """Every pixel the same color each stage, interpolating start_rgb -> end_rgb across
    stages. Good for a simple power-on (black -> color) or power-off (color -> black)."""
    denom = max(1, stage_count - 1)

    def pixel_fn(stage, _pixel):
        t = stage / denom
        return tuple(round(s + (e - s) * t) for s, e in zip(start_rgb, end_rgb))

    return _build_stage_image(width, stage_count, pixel_fn)


def generate_wipe(width: int, stage_count: int, fill_rgb: RGB, bg_rgb: RGB,
                   bottom_up: bool = True) -> QtGui.QImage:
    """A color front progressively fills the blade (or empties it) over stages - the classic
    "blade extending" look, useful for power-on/off and pre-on/post-off."""
    denom = max(1, stage_count - 1)
    last_pixel = max(0, width - 1)

    def pixel_fn(stage, pixel):
        t = stage / denom
        threshold = t * width
        pos = pixel if bottom_up else (last_pixel - pixel)
        return fill_rgb if pos < threshold else bg_rgb

    return _build_stage_image(width, stage_count, pixel_fn)


def generate_flicker(width: int, stage_count: int, base_rgb: RGB, jitter: int = 60,
                      seed: Optional[int] = None) -> QtGui.QImage:
    """Base color with random per-pixel, per-stage brightness jitter - a loopable idle/lockup
    shimmer rather than a one-shot transition."""
    rng = random.Random(seed)

    def pixel_fn(_stage, _pixel):
        delta = rng.randint(-jitter, jitter)
        return tuple(c + delta for c in base_rgb)

    return _build_stage_image(width, stage_count, pixel_fn)


def generate_fire(width: int, stage_count: int, base_rgb: Optional[RGB] = None,
                   seed: Optional[int] = None) -> QtGui.QImage:
    """Warm per-pixel noise animation - the same "flame" idea as the app's built-in
    approximate 'fire' unstable mode, rendered here as a real bitmap loop."""
    base_rgb = base_rgb or (255, 90, 0)
    rng = random.Random(seed)

    def pixel_fn(_stage, _pixel):
        heat = rng.uniform(0.4, 1.0)
        r, g, b = base_rgb
        return (r * heat, g * heat * rng.uniform(0.6, 1.0), b * heat * rng.uniform(0.0, 0.5))

    return _build_stage_image(width, stage_count, pixel_fn)


def _marquee_font(pixel_height: int) -> QtGui.QFont:
    font = QtGui.QFont("Sans Serif")
    font.setPixelSize(max(1, pixel_height))
    font.setBold(True)
    return font


def marquee_message_width(width: int, text: str, gap_px: Optional[int] = None) -> int:
    """Total pixel width of one full marquee cycle (rendered message + trailing blank gap)
    at a given blade pixel count, without actually rendering the bitmap - lets the wizard's
    "Fit Stages" control pick a stage count that covers exactly one loop."""
    metrics = QtGui.QFontMetrics(_marquee_font(width))
    text_width = max(1, metrics.horizontalAdvance(text or " "))
    gap = width if gap_px is None else gap_px
    return text_width + gap


def _render_text_strip(width: int, text: str, fg_rgb: RGB, bg_rgb: RGB,
                        gap_px: Optional[int] = None) -> QtGui.QImage:
    """Renders `text` at a pixel height equal to the full blade pixel count (using all of the
    blade's resolution to keep characters legible), as wide as the message needs plus a
    trailing blank gap (default: one blade-width), so a looping playback doesn't jump
    straight from the end of the message back into its own start."""
    font = _marquee_font(width)
    metrics = QtGui.QFontMetrics(font)
    text_width = max(1, metrics.horizontalAdvance(text or " "))
    gap = width if gap_px is None else gap_px
    total_width = text_width + gap

    image = QtGui.QImage(total_width, width, QtGui.QImage.Format_RGB32)
    image.fill(QtGui.QColor(*bg_rgb))
    painter = QtGui.QPainter(image)
    painter.setFont(font)
    painter.setPen(QtGui.QColor(*fg_rgb))
    painter.drawText(QtCore.QRect(0, 0, text_width, width),
                      QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, text or "")
    painter.end()
    return image


def generate_marquee_text(width: int, stage_count: int, text: str, fg_rgb: RGB, bg_rgb: RGB,
                           scroll_px_per_stage: int = 3) -> QtGui.QImage:
    """A scrolling marquee/LED-sign effect. A blade only has one spatial dimension (its
    length), so there's no room for both real glyph height *and* horizontal scroll travel
    along that same axis - instead, the message is rendered as a strip as tall as the full
    blade pixel count (so characters use the blade's whole resolution) but much WIDER than
    the blade, and each stage samples one single-pixel-wide vertical slice of that strip -
    stage 0 at its left edge, later stages sweeping rightward through the message at
    scroll_px_per_stage pixels/stage and wrapping back to the start once past the end. Since
    every pixel of a given stage is drawn from the same x position (differing only by height,
    i.e. by glyph shape), the blade shows the message's current "reading position" as a
    whole, and stepping through stages in playback reads as the text scrolling past - the
    same effect a persistence-of-vision/scan display gets from a 1D strip.

    Pixel index 0 is the hilt end (matches every other convention in this module); row 0 of
    the rendered strip is its top edge (where QPainter starts drawing glyphs). To keep text
    right-side-up when the blade is held tip-up, the top of a glyph needs to land at the tip
    (the *highest* pixel index), so pixel index is flipped when sampling the strip."""
    strip = _render_text_strip(width, text, fg_rgb, bg_rgb)
    total_width = strip.width()

    def pixel_fn(stage, pixel):
        x = (stage * scroll_px_per_stage) % total_width
        color = strip.pixelColor(x, width - 1 - pixel)
        return (color.red(), color.green(), color.blue())

    return _build_stage_image(width, stage_count, pixel_fn)


def write_grafx_resource(folder: Path, state_specs: dict) -> None:
    """Write a complete GraFx resource folder from {state: spec} entries, where state is one
    of grafx_reader.GRAFX_STATES's keys and spec is:
        {'image_variants': [QImage, ...], 'delay_ms': int|None, 'many': int, 'stop': bool,
         'accents': str (optional), 'extra_params': {key: value} (optional - accpulsed etc.)}
    len(image_variants) should equal 'many' - one randomly-chosen variant is played back each
    time the state is entered (see grafx_reader._pick_bmp_path). delay_ms of None omits the
    'delay' key entirely, matching the format's "sync playback to the sound/quick-on
    duration" fallback that grafx_reader.load_grafx_state already implements on read."""
    folder.mkdir(parents=True, exist_ok=True)

    lines: List[str] = []
    for state, spec in state_specs.items():
        if state not in GRAFX_STATES:
            continue
        section_name, file_prefix = GRAFX_STATES[state]
        images = spec['image_variants']

        for i, image in enumerate(images, start=1):
            image.save(str(folder / f"{file_prefix}{i}.bmp"), "BMP")

        lines.append(f"[{section_name}]")
        if spec.get('accents'):
            lines.append(f"accents={spec['accents']}")
        if spec.get('delay_ms'):
            lines.append(f"delay={int(spec['delay_ms'])}")
        if len(images) > 1:
            lines.append(f"many={len(images)}")
        if spec.get('stop'):
            lines.append("stop=1")
        for key, value in spec.get('extra_params', {}).items():
            lines.append(f"{key}={value}")
        lines.append("")

    (folder / 'grafx1.txt').write_text("\n".join(lines) + "\n")


def next_available_grafx_index(grafx_root: Path) -> int:
    """Smallest non-negative integer not already used as a '<n>-name' folder prefix under
    the GraFx root - matches the int(item.name.split('-')[0]) convention main_window.py
    already uses to parse these folders."""
    used = set()
    if grafx_root.exists():
        for item in grafx_root.iterdir():
            if item.is_dir() and item.name[:1].isdigit():
                try:
                    used.add(int(item.name.split('-')[0]))
                except ValueError:
                    continue
    n = 0
    while n in used:
        n += 1
    return n


def sanitize_folder_name(name: str) -> str:
    """Make a user-typed resource name safe to use as (part of) a folder name."""
    cleaned = "".join(c if (c.isalnum() or c in "-_") else "_" for c in name.strip())
    return cleaned or "GRAFX"


def save_bmp(image: QtGui.QImage, path: Path) -> bool:
    """Save a GraFx BMP as 24-bit color (the format the board expects). Qt writes 24 bpp for
    RGB32 images, so normalise to that first in case the source carried an alpha channel."""
    return image.convertToFormat(QtGui.QImage.Format_RGB32).save(str(path), "BMP")


_SECTION_HEADER_RE = re.compile(r'^\[(\w+)\]$')


def update_config_section(txt_path: Path, section_name: str, updates: dict) -> None:
    """Edit individual key=value lines of one grafx1.txt section in place, leaving every
    other line (comments, accents=..., other sections, ##-disabled params) and the file's
    line endings untouched - unlike write_grafx_resource, which regenerates the whole file.

    updates: {key: value_str or None}. A string sets the key (replacing the active line, or
    re-enabling a '##key=' line in that section, or inserting a new line after the section's
    last line). None disables the key by commenting its active line out with '##', the same
    convention the stock files use. A section that doesn't exist (or is only commented out)
    is appended as a new active section at the end of the file."""
    try:
        raw = txt_path.read_bytes().decode('utf-8', errors='replace')
    except OSError:
        raw = ''
    newline = '\r\n' if '\r\n' in raw else '\n'
    lines = raw.splitlines()
    target = section_name.upper()

    # [start, end) line range of the active section (end = next header or EOF)
    start = end = None
    for i, line in enumerate(lines):
        m = _SECTION_HEADER_RE.match(line.strip())
        if m:
            if start is not None:
                end = i
                break
            if m.group(1).upper() == target:
                start = i
    if start is not None and end is None:
        end = len(lines)

    if start is None:
        new_lines = [f"{key}={value}" for key, value in updates.items() if value is not None]
        if lines and lines[-1].strip():
            lines.append('')
        lines.append(f"[{target}]")
        lines.extend(new_lines)
        lines.append('')
        txt_path.write_bytes((newline.join(lines) + newline).encode('utf-8'))
        return

    # Last key=value line (active or ##-disabled) in the section, so inserted keys go right
    # after its settings - not after blank separators or free-text comments like
    # "## TO COME PRE-ON & POST-OFF here" that sit before the next header.
    last_content = start
    for i in range(start + 1, end):
        stripped = lines[i].strip()
        if re.match(r'^(##\s*)?[A-Za-z_]\w*\s*=', stripped):
            last_content = i

    for key, value in updates.items():
        key = key.lower()
        active_i = commented_i = None
        for i in range(start + 1, end):
            stripped = lines[i].strip()
            if stripped.startswith('#'):
                body = stripped.lstrip('#').strip()
                if body.partition('=')[0].strip().lower() == key and '=' in body:
                    commented_i = i if commented_i is None else commented_i
            elif '=' in stripped and stripped.partition('=')[0].strip().lower() == key:
                active_i = i
        if value is None:
            if active_i is not None:
                lines[active_i] = '##' + lines[active_i].strip()
        elif active_i is not None:
            lines[active_i] = f"{key}={value}"
        elif commented_i is not None:
            lines[commented_i] = f"{key}={value}"
        else:
            last_content += 1
            lines.insert(last_content, f"{key}={value}")
            end += 1

    txt_path.write_bytes((newline.join(lines) + newline).encode('utf-8'))


def duplicate_grafx_resource(source: Path, grafx_root: Path, name: str) -> Path:
    """Copy a whole resource folder to the next free '<n>-name' slot under grafx_root and
    return the new folder. The original is never touched."""
    index = next_available_grafx_index(grafx_root)
    dest = grafx_root / f"{index}-{sanitize_folder_name(name)}"
    shutil.copytree(source, dest)
    return dest


_PARAM_LINE_RE = re.compile(r'^[A-Za-z_]\w*\s*=')
_DISABLED_LINE_RE = re.compile(r'^##(\s*\[\w+\]|\s*[A-Za-z_]\w*\s*=|##)')


def set_section_enabled(txt_path: Path, section_name: str, enabled: bool) -> bool:
    """Comment a whole section out with '##' (like the stock disabled [FOREVER] block), or
    bring a commented-out one back. Only the header and key=value lines are touched - free
    text comments stay as they are. A param line that was already disabled gets a second
    '##' when its section is disabled, so re-enabling the section restores it as still
    disabled rather than switching it on. Returns False if there was nothing to change."""
    try:
        raw = txt_path.read_bytes().decode('utf-8', errors='replace')
    except OSError:
        return False
    newline = '\r\n' if '\r\n' in raw else '\n'
    lines = raw.splitlines()
    target = section_name.upper()
    header_re = re.compile(r'^(##\s*)?\[(\w+)\]\s*$')

    start = None
    for i, line in enumerate(lines):
        m = header_re.match(line.strip())
        if m and m.group(2).upper() == target and bool(m.group(1)) == enabled:  # commented iff enabling
            start = i
            break
    if start is None:
        return False

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if header_re.match(lines[i].strip()):
            end = i
            break

    for i in range(start, end):
        stripped = lines[i].strip()
        if enabled:
            if _DISABLED_LINE_RE.match(stripped):
                lines[i] = stripped[2:].lstrip() if stripped[2:3] != '#' else stripped[2:]
        elif i == start or _PARAM_LINE_RE.match(stripped) or \
                re.match(r'^##\s*[A-Za-z_]\w*\s*=', stripped):
            lines[i] = '##' + stripped

    txt_path.write_bytes((newline.join(lines) + newline).encode('utf-8'))
    return True
