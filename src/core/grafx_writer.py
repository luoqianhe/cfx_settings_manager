# src/core/grafx_writer.py
"""Generates GraFx resource folders (/extra/GRAFX/<n>-name/) from a handful of presets, for
the GraFx Creator wizard (gui/grafx_creator_dialog.py). This is the inverse of
core/grafx_reader.py - same file layout (grafx1.txt + <prefix><N>.bmp files), same bottom-up
stage/row convention, same section-name/file-prefix table (GRAFX_STATES) - so anything written
here round-trips cleanly back through grafx_reader.load_grafx_state().
"""
import random
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from PySide6 import QtGui

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


def write_grafx_resource(folder: Path, state_specs: dict) -> None:
    """Write a complete GraFx resource folder from {state: spec} entries, where state is one
    of grafx_reader.GRAFX_STATES's keys and spec is:
        {'image_variants': [QImage, ...], 'delay_ms': int|None, 'many': int, 'stop': bool}
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
        if spec.get('delay_ms'):
            lines.append(f"delay={int(spec['delay_ms'])}")
        if len(images) > 1:
            lines.append(f"many={len(images)}")
        if spec.get('stop'):
            lines.append("stop=1")
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
