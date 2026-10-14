# src/gui/widgets/grafx_stage_editor.py
"""A freeform pixel-grid painter for GraFx animations. Used two ways:

- by the GraFx Creator wizard's 'Custom' preset (via the compact GrafxStageEditor launcher),
  to hand-paint a new animation;
- by the GraFx resource editor (gui/grafx_resource_editor_dialog.py), to open one existing
  BMP from a resource folder at its own size.
Both allow up to MAX_STAGE_COUNT stages - real resources run to hundreds.

The actual painting happens in a separate, screen-sized GrafxPixelEditorWindow, with zoom
controls and scrolling for animations too long to fit on screen.

The grid is drawn with blade pixels running vertically (top = tip, bottom = hilt, matching
BladePreviewWidget's hilt-at-the-bottom orientation) and stages running horizontally left
(stage 0, played first) to right. Internally the grid is a QImage in that same display
orientation (x = stage index, y = 0 at the tip), so painting, undo snapshots and redraws stay
fast even at 150 pixels x 500 stages. bmp_to_display()/display_to_bmp() convert to and from
the on-disk BMP layout (x = pixel index from the hilt, stage 0 = bottom row - see
core/grafx_reader.py). The colors()/set_colors() list-of-QColor API
([pixel_index][stage_index], pixel_index 0 = hilt-end pixel) is kept for the wizard.
"""
import math
import random

from PySide6 import QtCore, QtGui, QtMultimedia, QtWidgets

from core import grafx_writer
from core.grafx_timing import resample_stages
from core.sound_player import route_to_default_output
from gui.widgets.widget_factory import create_rgb_picker_widget

MAX_STAGE_COUNT = 2000    # painter limit (wizard 'Custom' and resource editor) - stock
                          # files go up to ~500
MAX_RESOURCE_STAGES = MAX_STAGE_COUNT
DEFAULT_CELL_WIDTH = 14   # px per stage column, before GrafxPixelEditorWindow fits it to screen
DEFAULT_CELL_HEIGHT = 5   # px per pixel row, same
MIN_FIT_CELL_WIDTH = 3    # initial auto-fit never goes narrower than this; "Fit" can
MAX_UNDO = 50
DEFAULT_PREVIEW_DELAY_MS = 20  # preview speed for states with no delay= (synced to sound)
ARC_BULGE_RATIO = 0.35    # how far the arc bows away from the straight chord, as a fraction
                          # of the chord's length

# Stages copied with Copy - module-level so they can be pasted into a different file
# opened later in the same session (e.g. copy part of a poweron into a poweroff).
_stage_clipboard = None




def _line_points(x0: int, y0: int, x1: int, y1: int):
    """Bresenham's line algorithm - every integer grid cell between two points, inclusive."""
    points = []
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while True:
        points.append((x, y))
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy
    return points


def _arc_points(x0: int, y0: int, x1: int, y1: int, bulge_ratio: float = ARC_BULGE_RATIO,
                 flip_h: bool = False, flip_v: bool = False):
    """Every integer grid cell along a circular-style arc from (x0,y0) to (x1,y1) - the Arc
    tool's counterpart to _line_points. Since a click-drag-release gesture only supplies two
    points (not the three a circular arc needs), the arc is built as a quadratic Bezier curve
    through a control point offset perpendicular to the chord by bulge_ratio * chord length -
    this always bows to the same side relative to the drag direction, giving a predictable,
    consistent curve rather than requiring a third click to set curvature.

    flip_h/flip_v independently mirror that offset across the vertical/horizontal axis (i.e.
    negate its x/y component), rather than just picking "the other side" of the chord as a
    single toggle would - so a diagonal drag still has two distinct, predictable flips."""
    dx = x1 - x0
    dy = y1 - y0
    chord = math.hypot(dx, dy)
    if chord == 0:
        return [(x0, y0)]

    perp_x, perp_y = -dy / chord, dx / chord
    mid_x, mid_y = (x0 + x1) / 2, (y0 + y1) / 2
    bulge = bulge_ratio * chord
    offset_x, offset_y = perp_x * bulge, perp_y * bulge
    if flip_h:
        offset_x = -offset_x
    if flip_v:
        offset_y = -offset_y
    ctrl_x, ctrl_y = mid_x + offset_x, mid_y + offset_y

    steps = max(2, int((chord + bulge) * 2))
    points = []
    last = None
    for i in range(steps + 1):
        t = i / steps
        inv = 1 - t
        x = inv * inv * x0 + 2 * inv * t * ctrl_x + t * t * x1
        y = inv * inv * y0 + 2 * inv * t * ctrl_y + t * t * y1
        cell = (round(x), round(y))
        if cell != last:
            points.append(cell)
            last = cell
    return points


# Display (x = stage, y = row from the tip) and BMP (x = pixel from the hilt, y = row with
# stage 0 at the bottom) layouts are each other's reflection across the anti-diagonal, so
# the same transform converts in both directions.
_ANTI_DIAGONAL = QtGui.QTransform(0, -1, -1, 0, 0, 0)


def bmp_to_display(image: QtGui.QImage) -> QtGui.QImage:
    return image.convertToFormat(QtGui.QImage.Format_RGB32).transformed(
        _ANTI_DIAGONAL, QtCore.Qt.FastTransformation).convertToFormat(QtGui.QImage.Format_RGB32)


def display_to_bmp(image: QtGui.QImage) -> QtGui.QImage:
    return bmp_to_display(image)


TAN_22_5 = math.tan(math.radians(22.5))

GRADIENT_SHAPES = ('linear', 'radial', 'elliptical')

GRADIENT_SPREADS = {
    'none': QtGui.QGradient.PadSpread,      # Color 1 before the start, Color 2 past the end
    'repeat': QtGui.QGradient.RepeatSpread,  # 1->2, 1->2, ...
    'mirror': QtGui.QGradient.ReflectSpread,  # 1->2->1->2 - loops seamlessly
}


def _snap_45(p0: int, s0: int, p1: int, s1: int, pixel_count: int, stage_count: int):
    """Snap the end of a drag from (p0, s0) to the nearest multiple of 45 degrees, measured
    in grid cells rather than screen pixels - so horizontal is one pixel holding its color
    over time, vertical is the whole blade in one stage, and 45 degrees is exactly one blade
    pixel per stage, whatever the current zoom's cell aspect ratio. A diagonal is shortened
    if needed to stay inside the grid, so it never bends at the edge."""
    ds, dp = s1 - s0, p1 - p0
    if abs(dp) <= abs(ds) * TAN_22_5:
        return p0, s1
    if abs(ds) <= abs(dp) * TAN_22_5:
        return p1, s0
    sign_s = 1 if ds > 0 else -1
    sign_p = 1 if dp > 0 else -1
    room_s = stage_count - 1 - s0 if sign_s > 0 else s0
    room_p = pixel_count - 1 - p0 if sign_p > 0 else p0
    d = min(max(abs(ds), abs(dp)), room_s, room_p)
    return p0 + sign_p * d, s0 + sign_s * d


def _blank_image(stage_count: int, pixel_count: int) -> QtGui.QImage:
    image = QtGui.QImage(max(1, stage_count), max(1, pixel_count), QtGui.QImage.Format_RGB32)
    image.fill(QtGui.QColor(0, 0, 0))
    return image


def _image_to_grid(image: QtGui.QImage, width: int):
    """[pixel_index][stage_index] -> QColor from a BMP-layout image (see module docstring).
    `width` is the caller's own blade pixel count, used (rather than image.width()) so a
    mismatched source image still produces a grid of the right shape."""
    stage_count = max(1, image.height())
    grid = [[QtGui.QColor(0, 0, 0) for _ in range(stage_count)] for _ in range(width)]
    for stage_index in range(stage_count):
        bmp_row = stage_count - 1 - stage_index
        for pixel_index in range(min(width, image.width())):
            grid[pixel_index][stage_index] = QtGui.QColor(image.pixel(pixel_index, bmp_row))
    return grid


def _splice(*parts) -> QtGui.QImage:
    """Concatenate display-layout images (or (image, QRect source) pairs) left to right -
    the building block for every insert/delete stage-range operation."""
    pieces = []
    for part in parts:
        if isinstance(part, tuple):
            image, rect = part
            if rect.width() > 0:
                pieces.append((image, rect))
        elif part.width() > 0:
            pieces.append((part, part.rect()))
    total = sum(rect.width() for _image, rect in pieces)
    height = pieces[0][0].height() if pieces else 1
    result = _blank_image(total, height)
    painter = QtGui.QPainter(result)
    painter.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
    x = 0
    for image, rect in pieces:
        painter.drawImage(QtCore.QPoint(x, 0), image, rect)
        x += rect.width()
    painter.end()
    return result


class GrafxPixelGridWidget(QtWidgets.QWidget):
    """pixel_count rows x stage_count columns of paintable color cells, with
    freehand/line/arc painting, a two-color Gradient tool, a stage-range Select tool
    (copy/paste/duplicate/insert/delete/reverse), adjustable brush size, and multi-level
    undo/redo. Holding Shift snaps Line and Gradient drags to 45-degree steps, and
    Shift-click with Freehand draws a straight line from the last painted cell."""

    cell_painted = QtCore.Signal()
    eyedropped = QtCore.Signal(QtGui.QColor)
    undo_available_changed = QtCore.Signal(bool)
    redo_available_changed = QtCore.Signal(bool)
    stage_count_changed = QtCore.Signal(int)
    selection_changed = QtCore.Signal()
    hovered = QtCore.Signal(int, int)    # pixel_index, stage_index; (-1, -1) on leave

    def __init__(self, pixel_count: int, stage_count: int, parent=None,
                 max_stages: int = MAX_STAGE_COUNT):
        super().__init__(parent)
        self._max_stages = max(1, max_stages)
        self._image = _blank_image(max(1, min(self._max_stages, stage_count)),
                                   max(1, pixel_count))
        self._paint_color = QtGui.QColor(255, 255, 255)
        self._cell_width = DEFAULT_CELL_WIDTH
        self._cell_height = DEFAULT_CELL_HEIGHT
        self._tool = 'freehand'
        self._brush_size = 1
        self._stroke_anchor = None       # (pixel_index, stage_index) while dragging a line/arc
        self._stroke_preview_end = None
        self._last_freehand = None       # previous cell of a freehand drag, to join gaps
        self._last_painted = None        # last freehand cell, kept for Shift-click lines
        self._gradient_start_color = QtGui.QColor(255, 255, 255)   # gradient Color 1
        self._gradient_color = QtGui.QColor(0, 0, 0)                # gradient Color 2
        self._gradient_spread = 'none'
        self._gradient_shape = 'linear'  # 'linear', 'radial' (circle) or 'elliptical'
        self._bucket_tolerance = 0       # max per-channel difference still counted as a match
        self._bucket_replace_all = False  # every matching cell, not just the connected area
        self._bucket_mode = 'solid'      # 'solid' (Paint color) or 'gradient' (Color 1 -> 2)
        self._bucket = None              # (bbox, mask) of a gradient bucket fill being dragged
        self._ellipse_filled = True      # Circle/ellipse tool: filled, or a brush-wide outline
        self._arc_flip_h = False         # mirror the arc tool's bulge left/right
        self._arc_flip_v = False         # mirror the arc tool's bulge up/down
        self._selection = None           # (first_stage, last_stage) inclusive, or None
        self._select_anchor = None
        self._undo_stack = []            # (QImage, selection) snapshots, oldest first
        self._redo_stack = []
        self._modified = False
        self.setMouseTracking(True)
        self._update_size()

    # ------------------------------------------------------------------ geometry / setup

    def _update_size(self):
        self.setFixedSize(self.stage_count() * self._cell_width,
                           self.pixel_count() * self._cell_height)

    def set_cell_size(self, cell_width: int, cell_height: int):
        self._cell_width = max(1, cell_width)
        self._cell_height = max(1, cell_height)
        self._update_size()
        self.update()

    def cell_size(self):
        return self._cell_width, self._cell_height

    def set_paint_color(self, color: QtGui.QColor):
        self._paint_color = QtGui.QColor(color)

    def set_tool(self, tool: str):
        self._tool = tool
        self._stroke_anchor = None
        self._stroke_preview_end = None
        self.update()

    def set_brush_size(self, size: int):
        self._brush_size = max(1, size)

    def set_gradient_colors(self, color1: QtGui.QColor, color2: QtGui.QColor):
        self._gradient_start_color = QtGui.QColor(color1)
        self._gradient_color = QtGui.QColor(color2)
        self.update()

    def set_ellipse_filled(self, filled: bool):
        self._ellipse_filled = bool(filled)
        self.update()

    def set_bucket_options(self, tolerance: int, replace_all: bool, mode: str):
        self._bucket_tolerance = max(0, int(tolerance))
        self._bucket_replace_all = bool(replace_all)
        self._bucket_mode = mode if mode in ('solid', 'gradient') else 'solid'

    def set_gradient_shape(self, shape: str):
        self._gradient_shape = shape if shape in GRADIENT_SHAPES else 'linear'
        self.update()

    def set_gradient_spread(self, spread: str):
        self._gradient_spread = spread if spread in GRADIENT_SPREADS else 'none'
        self.update()

    def set_arc_flip_h(self, flag: bool):
        self._arc_flip_h = bool(flag)
        self.update()

    def set_arc_flip_v(self, flag: bool):
        self._arc_flip_v = bool(flag)
        self.update()

    def max_stages(self) -> int:
        return self._max_stages

    def is_modified(self) -> bool:
        return self._modified

    # ------------------------------------------------------------------ undo / redo

    def push_undo_snapshot(self):
        """Record the current state as one undo step. Called right before any action
        mutates the grid - strokes call this themselves; external mutations (Fill All,
        Apply preset, stage-count changes, range operations) call it too."""
        self._undo_stack.append((QtGui.QImage(self._image), self._selection))
        del self._undo_stack[:-MAX_UNDO]
        self._redo_stack.clear()
        self._modified = True
        self.undo_available_changed.emit(True)
        self.redo_available_changed.emit(False)

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def _restore(self, snapshot):
        old_count = self.stage_count()
        self._image, self._selection = snapshot
        self._modified = True
        self._after_structure_change(old_count)
        self.cell_painted.emit()

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        self._redo_stack.append((QtGui.QImage(self._image), self._selection))
        self._restore(self._undo_stack.pop())
        self.undo_available_changed.emit(bool(self._undo_stack))
        self.redo_available_changed.emit(True)
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._undo_stack.append((QtGui.QImage(self._image), self._selection))
        self._restore(self._redo_stack.pop())
        self.undo_available_changed.emit(True)
        self.redo_available_changed.emit(bool(self._redo_stack))
        return True

    # ------------------------------------------------------------------ data access

    def stage_count(self) -> int:
        return self._image.width()

    def pixel_count(self) -> int:
        return self._image.height()

    def display_image(self) -> QtGui.QImage:
        """The live grid in display layout - read-only use (e.g. the preview strip)."""
        return self._image

    def to_bmp_image(self) -> QtGui.QImage:
        return display_to_bmp(self._image)

    def set_bmp_image(self, image: QtGui.QImage):
        old_count = self.stage_count()
        self._image = bmp_to_display(image)
        self._selection = None
        self._after_structure_change(old_count)

    def colors(self):
        """[pixel_index][stage_index] -> QColor, pixel_index 0 = hilt-end pixel."""
        return _image_to_grid(self.to_bmp_image(), self.pixel_count())

    def set_colors(self, colors):
        """colors: [pixel_index][stage_index] -> QColor, must match pixel_count/stage_count."""
        pixel_count = self.pixel_count()
        image = _blank_image(self.stage_count(), pixel_count)
        for pixel_index, row in enumerate(colors[:pixel_count]):
            y = pixel_count - 1 - pixel_index
            for stage_index, color in enumerate(row[:image.width()]):
                image.setPixel(stage_index, y, QtGui.QColor(color).rgb())
        self._image = image
        self.update()

    def color_at(self, pixel_index: int, stage_index: int) -> QtGui.QColor:
        return QtGui.QColor(self._image.pixel(stage_index, self.pixel_count() - 1 - pixel_index))

    def set_stage_count(self, new_count: int):
        """Resize to new_count stages, keeping existing ones and padding with black."""
        new_count = max(1, min(self._max_stages, new_count))
        if new_count == self.stage_count():
            return
        old_count = self.stage_count()
        if new_count < old_count:
            self._image = self._image.copy(0, 0, new_count, self.pixel_count())
        else:
            self._image = _splice(self._image,
                                  _blank_image(new_count - old_count, self.pixel_count()))
        self._after_structure_change(old_count)

    def fill_all(self, color: QtGui.QColor):
        self._image.fill(QtGui.QColor(color))
        self.update()

    def _after_structure_change(self, old_count: int):
        if self._selection is not None:
            first, last = self._selection
            last = min(last, self.stage_count() - 1)
            self._selection = (first, last) if first <= last else None
        self._update_size()
        self.updateGeometry()
        self.update()
        self.selection_changed.emit()
        if self.stage_count() != old_count:
            self.stage_count_changed.emit(self.stage_count())

    # ------------------------------------------------------------------ stage ranges

    def selection(self):
        return self._selection

    def set_selection(self, first, last=None):
        if first is None:
            self._selection = None
        else:
            last = first if last is None else last
            first, last = sorted((first, last))
            first = max(0, first)
            last = min(self.stage_count() - 1, last)
            self._selection = (first, last) if first <= last else None
        self.update()
        self.selection_changed.emit()

    def _selection_rect(self) -> QtCore.QRect:
        first, last = self._selection
        return QtCore.QRect(first, 0, last - first + 1, self.pixel_count())

    def _insert_stages(self, at: int, block: QtGui.QImage) -> bool:
        """Insert a display-layout block of stages before stage `at`, selecting it."""
        if block.height() != self.pixel_count():
            # Pasting from a file with a different pixel count: keep the hilt ends aligned
            # (the bottom of the display image), padding/cropping at the tip.
            fitted = _blank_image(block.width(), self.pixel_count())
            painter = QtGui.QPainter(fitted)
            painter.drawImage(QtCore.QPoint(0, self.pixel_count() - block.height()), block)
            painter.end()
            block = fitted
        if self.stage_count() + block.width() > self._max_stages:
            return False
        self.push_undo_snapshot()
        old_count = self.stage_count()
        pixels = self.pixel_count()
        self._image = _splice((self._image, QtCore.QRect(0, 0, at, pixels)), block,
                              (self._image, QtCore.QRect(at, 0, old_count - at, pixels)))
        self._selection = (at, at + block.width() - 1)
        self._after_structure_change(old_count)
        self.cell_painted.emit()
        return True

    def copy_selection(self) -> bool:
        global _stage_clipboard
        if self._selection is None:
            return False
        _stage_clipboard = self._image.copy(self._selection_rect())
        return True

    @staticmethod
    def clipboard_stage_count() -> int:
        return _stage_clipboard.width() if _stage_clipboard is not None else 0

    def paste(self) -> bool:
        """Insert the copied stages after the selection (or at the end with none)."""
        if _stage_clipboard is None:
            return False
        at = self._selection[1] + 1 if self._selection else self.stage_count()
        return self._insert_stages(at, QtGui.QImage(_stage_clipboard))

    def duplicate_selection(self) -> bool:
        if self._selection is None:
            return False
        return self._insert_stages(self._selection[1] + 1,
                                   self._image.copy(self._selection_rect()))

    def insert_blank(self, count: int) -> bool:
        """Insert `count` black stages before the selection (or at the end with none)."""
        at = self._selection[0] if self._selection else self.stage_count()
        return self._insert_stages(at, _blank_image(count, self.pixel_count()))

    def delete_selection(self) -> bool:
        if self._selection is None:
            return False
        first, last = self._selection
        if last - first + 1 >= self.stage_count():
            return False    # an animation needs at least one stage
        self.push_undo_snapshot()
        old_count = self.stage_count()
        pixels = self.pixel_count()
        self._image = _splice((self._image, QtCore.QRect(0, 0, first, pixels)),
                              (self._image, QtCore.QRect(last + 1, 0, old_count - last - 1, pixels)))
        self._selection = None
        self._after_structure_change(old_count)
        self.cell_painted.emit()
        return True

    def reverse_selection(self) -> bool:
        """Play the selected stages backwards - e.g. turn a copied power-on into a
        power-off. With nothing selected, reverses the whole animation."""
        first, last = self._selection or (0, self.stage_count() - 1)
        self.push_undo_snapshot()
        block = self._image.copy(QtCore.QRect(first, 0, last - first + 1, self.pixel_count()))
        block = block.flipped(QtCore.Qt.Horizontal) if hasattr(block, 'flipped') \
            else block.mirrored(True, False)
        painter = QtGui.QPainter(self._image)
        painter.drawImage(QtCore.QPoint(first, 0), block)
        painter.end()
        self.update()
        self.cell_painted.emit()
        return True

    # ------------------------------------------------------------------ gradients

    def _gradient_region(self) -> QtCore.QRect:
        """Where a gradient is applied: the selected stages, or the whole grid."""
        if self._selection is not None:
            return self._selection_rect()
        return self._image.rect()

    def _radii(self, p0, s0, p1, s1, shape):
        """(horizontal, vertical) radius in cells of a radial/elliptical gradient dragged
        from its center (p0, s0) to (p1, s1). A circle uses the drag length both ways (so it's
        round in cells - 1 stage = 1 pixel - whatever the zoom); an ellipse takes the drag's
        horizontal and vertical extent separately (a flat axis gets half a cell, so a
        horizontal-only drag still makes a thin band rather than nothing)."""
        if shape == 'radial':
            radius = math.hypot(s1 - s0, p1 - p0)
            return radius, radius
        return max(0.5, abs(s1 - s0)), max(0.5, abs(p1 - p0))

    def _gradient_image(self, region: QtCore.QRect, p0, s0, p1, s1, shape: str = None):
        """The region filled with a Color 1 -> Color 2 gradient from the center of cell
        (p0, s0) to the center of cell (p1, s1), so both get their colors exactly. Linear
        runs along that line; radial/elliptical put Color 1 at (p0, s0) and Color 2 on the
        circle/ellipse through (p1, s1). None for a zero-length drag."""
        if (p0, s0) == (p1, s1):
            return None
        shape = shape or self._gradient_shape
        top = self.pixel_count() - 1
        x0, y0 = s0 + 0.5 - region.x(), top - p0 + 0.5 - region.y()
        x1, y1 = s1 + 0.5 - region.x(), top - p1 + 0.5 - region.y()
        if shape == 'linear':
            gradient = QtGui.QLinearGradient(x0, y0, x1, y1)
        else:
            gradient = QtGui.QRadialGradient(0, 0, 1)
        gradient.setColorAt(0.0, self._gradient_start_color)
        gradient.setColorAt(1.0, self._gradient_color)
        gradient.setSpread(GRADIENT_SPREADS[self._gradient_spread])
        brush = QtGui.QBrush(gradient)
        if shape != 'linear':
            # A unit circle stretched to the radii - Qt has no elliptical gradient as such.
            rx, ry = self._radii(p0, s0, p1, s1, shape)
            brush.setTransform(QtGui.QTransform().translate(x0, y0).scale(rx, ry))
        image = QtGui.QImage(region.size(), QtGui.QImage.Format_RGB32)
        painter = QtGui.QPainter(image)
        painter.fillRect(image.rect(), brush)
        painter.end()
        return image

    def _apply_gradient(self, p0, s0, p1, s1, shape: str = None) -> bool:
        region = self._gradient_region()
        image = self._gradient_image(region, p0, s0, p1, s1, shape)
        if image is None:
            return False
        self.push_undo_snapshot()
        painter = QtGui.QPainter(self._image)
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
        painter.drawImage(region.topLeft(), image)
        painter.end()
        self.update()
        self.cell_painted.emit()
        return True

    def fill_gradient(self, direction: str) -> bool:
        """Gradient across the whole selected stage range (or whole grid) without dragging:
        'time' runs Color 1 at the first stage -> Color 2 at the last (a fade over time);
        'blade' runs Color 1 at the hilt -> Color 2 at the tip (a band along the blade)."""
        region = self._gradient_region()
        first, last = region.left(), region.right()
        if direction == 'time':
            return self._apply_gradient(0, first, 0, last, shape='linear')
        return self._apply_gradient(0, first, self.pixel_count() - 1, first, shape='linear')

    # ------------------------------------------------------------------ paint bucket

    def _bucket_mask(self, pixel_index: int, stage_index: int):
        """The cells a bucket click at (pixel_index, stage_index) fills: everything connected
        to it (up/down/left/right - not diagonally) whose color is within the tolerance of
        the clicked cell's, or every such cell when replacing everywhere; limited to the
        selected stages if any. Returns (bbox, mask) - mask is a bbox-sized ARGB32 image,
        opaque on filled cells - or None if the click is outside the selection."""
        region = self._gradient_region()
        width = self._image.width()
        x0, y0 = stage_index, self.pixel_count() - 1 - pixel_index
        if not region.contains(x0, y0):
            return None
        data = memoryview(self._image.constBits()).cast('I')
        target = data[y0 * width + x0] & 0xFFFFFF
        tol = self._bucket_tolerance
        if tol == 0:
            def match(c):
                return (c & 0xFFFFFF) == target
        else:
            tr, tg, tb = (target >> 16) & 255, (target >> 8) & 255, target & 255

            def match(c):
                return (abs(((c >> 16) & 255) - tr) <= tol and abs(((c >> 8) & 255) - tg) <= tol
                        and abs((c & 255) - tb) <= tol)
        left, right, top, bottom = region.left(), region.right(), region.top(), region.bottom()
        cells = []
        if self._bucket_replace_all:
            for y in range(top, bottom + 1):
                base = y * width
                cells.extend(base + x for x in range(left, right + 1) if match(data[base + x]))
        else:
            seen = bytearray(width * self._image.height())
            stack = [y0 * width + x0]
            while stack:
                i = stack.pop()
                if seen[i]:
                    continue
                seen[i] = 1
                if not match(data[i]):
                    continue
                cells.append(i)
                x, y = i % width, i // width
                if x > left:
                    stack.append(i - 1)
                if x < right:
                    stack.append(i + 1)
                if y > top:
                    stack.append(i - width)
                if y < bottom:
                    stack.append(i + width)
        data.release()

        xs = [i % width for i in cells]
        ys = [i // width for i in cells]
        bbox = QtCore.QRect(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)
        mask = bytearray(bbox.width() * bbox.height() * 4)
        for x, y in zip(xs, ys):
            mask[((y - bbox.y()) * bbox.width() + (x - bbox.x())) * 4 + 3] = 255
        return bbox, QtGui.QImage(bytes(mask), bbox.width(), bbox.height(),
                                  QtGui.QImage.Format_ARGB32).copy()

    def _bucket_gradient_ends(self, bbox: QtCore.QRect, anchor, end):
        """A dragged gradient bucket fill runs along the drag. A plain click: linear runs
        Color 1 -> Color 2 across the filled area over time (left to right), or hilt -> tip
        if it's only one stage wide; radial/elliptical are centered on the filled area and
        reach its outermost cells - so clicking inside a circle shades it center -> rim."""
        if end != anchor:
            return anchor, end
        top = self.pixel_count() - 1
        if self._gradient_shape != 'linear':
            center_s = bbox.left() + (bbox.width() - 1) / 2
            center_p = top - (bbox.top() + (bbox.height() - 1) / 2)
            rx, ry = (bbox.width() - 1) / 2, (bbox.height() - 1) / 2
            if self._gradient_shape == 'radial':
                # The drag length is the radius, so the edge goes straight out sideways.
                return (center_p, center_s), (center_p, center_s + max(rx, ry, 0.5))
            return (center_p, center_s), (center_p + max(ry, 0.5), center_s + max(rx, 0.5))
        if bbox.width() > 1:
            return (anchor[0], bbox.left()), (anchor[0], bbox.right())
        return (top - bbox.bottom(), anchor[1]), (top - bbox.top(), anchor[1])

    def _bucket_layer(self, bbox: QtCore.QRect, mask: QtGui.QImage, ends=None) -> QtGui.QImage:
        """The fill's colors (Paint color, or the gradient) cut out by the mask."""
        layer = None
        if self._bucket_mode == 'gradient' and ends is not None:
            (p0, s0), (p1, s1) = ends
            layer = self._gradient_image(bbox, p0, s0, p1, s1)
        if layer is None:
            layer = QtGui.QImage(bbox.size(), QtGui.QImage.Format_RGB32)
            layer.fill(self._gradient_start_color if self._bucket_mode == 'gradient'
                       else self._paint_color)
        layer = layer.convertToFormat(QtGui.QImage.Format_ARGB32)
        painter = QtGui.QPainter(layer)
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_DestinationIn)
        painter.drawImage(0, 0, mask)
        painter.end()
        return layer

    def _apply_bucket(self, bbox: QtCore.QRect, layer: QtGui.QImage):
        self.push_undo_snapshot()
        painter = QtGui.QPainter(self._image)
        painter.drawImage(bbox.topLeft(), layer)
        painter.end()
        self.update()
        self.cell_painted.emit()

    # ------------------------------------------------------------------ painting

    def _cell_at(self, x: float, y: float):
        stage_index = max(0, min(self.stage_count() - 1, int(x / self._cell_width)))
        row_from_top = max(0, min(self.pixel_count() - 1, int(y / self._cell_height)))
        pixel_index = self.pixel_count() - 1 - row_from_top  # top of widget = tip = highest index
        return pixel_index, stage_index

    def _brush_cells(self, pixel_index: int, stage_index: int):
        """Every cell covered by the brush, centered on (pixel_index, stage_index), clipped
        to the grid bounds."""
        half_lo = (self._brush_size - 1) // 2
        half_hi = self._brush_size // 2
        cells = []
        for dp in range(-half_lo, half_hi + 1):
            p = pixel_index + dp
            if not (0 <= p < self.pixel_count()):
                continue
            for ds in range(-half_lo, half_hi + 1):
                s = stage_index + ds
                if 0 <= s < self.stage_count():
                    cells.append((p, s))
        return cells

    def _line_cells(self, p0: int, s0: int, p1: int, s1: int):
        cells = set()
        for s, p in _line_points(s0, p0, s1, p1):
            cells.update(self._brush_cells(p, s))
        return cells

    def _arc_cells(self, p0: int, s0: int, p1: int, s1: int):
        cells = set()
        for s, p in _arc_points(s0, p0, s1, p1,
                                 flip_h=self._arc_flip_h, flip_v=self._arc_flip_v):
            cells.update(self._brush_cells(p, s))
        return cells

    def _drag_end(self, shift: bool):
        """The current Line/Gradient drag end, snapped to 45 degrees while Shift is held."""
        p1, s1 = self._stroke_preview_end or self._stroke_anchor
        if shift and (self._tool == 'ellipse' or (self._tool in ('gradient', 'bucket')
                                                   and self._gradient_shape == 'elliptical')):
            # Shift makes the ellipse a circle: equal radii, the larger of the two.
            p0, s0 = self._stroke_anchor
            r = max(abs(p1 - p0), abs(s1 - s0))
            return p0 + (r if p1 >= p0 else -r), s0 + (r if s1 >= s0 else -r)
        if shift and self._tool in ('gradient', 'bucket') and self._gradient_shape == 'radial':
            return p1, s1            # a circle's direction doesn't matter - nothing to snap
        if shift and self._tool in ('line', 'gradient', 'bucket'):
            p0, s0 = self._stroke_anchor
            return _snap_45(p0, s0, p1, s1, self.pixel_count(), self.stage_count())
        return p1, s1

    def _ellipse_cells(self, p0: int, s0: int, p1: int, s1: int):
        """Cells of a circle/ellipse centered on (p0, s0) whose radii are the drag's extent:
        horizontal = stages (time), vertical = pixels (along the blade); a flat axis gets
        half a cell. Filled, or an outline as thick as the brush."""
        rx, ry = max(0.5, abs(s1 - s0)), max(0.5, abs(p1 - p0))
        width = self._brush_size
        inner_rx, inner_ry = rx - width, ry - width
        cells = []
        for s in range(max(0, math.floor(s0 - rx)), min(self.stage_count() - 1, math.ceil(s0 + rx)) + 1):
            ds = s - s0
            for p in range(max(0, math.floor(p0 - ry)), min(self.pixel_count() - 1, math.ceil(p0 + ry)) + 1):
                dp = p - p0
                if (ds / rx) ** 2 + (dp / ry) ** 2 > 1:
                    continue
                if (not self._ellipse_filled and inner_rx > 0 and inner_ry > 0
                        and (ds / inner_rx) ** 2 + (dp / inner_ry) ** 2 <= 1):
                    continue
                cells.append((p, s))
        return cells

    def _stroke_cells(self, p0: int, s0: int, p1: int, s1: int):
        if self._tool == 'ellipse':
            return self._ellipse_cells(p0, s0, p1, s1)
        return self._arc_cells(p0, s0, p1, s1) if self._tool == 'arc' \
            else self._line_cells(p0, s0, p1, s1)

    def _set_cells(self, cells):
        rgb = self._paint_color.rgb()
        top = self.pixel_count() - 1
        for p, s in cells:
            self._image.setPixel(s, top - p, rgb)
        self.update()
        self.cell_painted.emit()

    def mousePressEvent(self, event):
        pixel_index, stage_index = self._cell_at(event.position().x(), event.position().y())
        if event.button() == QtCore.Qt.RightButton:
            self.eyedropped.emit(self.color_at(pixel_index, stage_index))
            return
        if event.button() != QtCore.Qt.LeftButton:
            return
        if self._tool == 'select':
            if event.modifiers() & QtCore.Qt.ShiftModifier and self._selection is not None:
                self._select_anchor = self._selection[0]
            else:
                self._select_anchor = stage_index
            self.set_selection(self._select_anchor, stage_index)
        elif self._tool == 'bucket':
            result = self._bucket_mask(pixel_index, stage_index)
            if result is None:
                return
            bbox, mask = result
            if self._bucket_mode == 'solid':
                self._apply_bucket(bbox, self._bucket_layer(bbox, mask))
            else:
                # Gradient: the drag (if any) sets its direction - applied on release.
                self._bucket = (bbox, mask)
                self._stroke_anchor = (pixel_index, stage_index)
                self._stroke_preview_end = (pixel_index, stage_index)
                self.update()
        elif self._tool in ('line', 'arc', 'gradient', 'ellipse'):
            self._stroke_anchor = (pixel_index, stage_index)
            self._stroke_preview_end = (pixel_index, stage_index)
            self.update()
        else:
            self.push_undo_snapshot()
            if event.modifiers() & QtCore.Qt.ShiftModifier and self._last_painted is not None:
                p0, s0 = self._last_painted
                self._set_cells(self._line_cells(p0, s0, pixel_index, stage_index))
            else:
                self._set_cells(self._brush_cells(pixel_index, stage_index))
            self._last_freehand = self._last_painted = (pixel_index, stage_index)

    def mouseMoveEvent(self, event):
        pixel_index, stage_index = self._cell_at(event.position().x(), event.position().y())
        self.hovered.emit(pixel_index, stage_index)
        if not event.buttons() & QtCore.Qt.LeftButton:
            return
        if self._tool == 'select' and self._select_anchor is not None:
            self.set_selection(self._select_anchor, stage_index)
        elif self._tool in ('line', 'arc', 'gradient', 'bucket', 'ellipse') and self._stroke_anchor is not None:
            self._stroke_preview_end = (pixel_index, stage_index)
            self.update()
        elif self._tool == 'freehand' and self._last_freehand is not None:
            # Join to the previous cell so a fast drag doesn't leave gaps.
            p0, s0 = self._last_freehand
            self._set_cells(self._line_cells(p0, s0, pixel_index, stage_index))
            self._last_freehand = self._last_painted = (pixel_index, stage_index)

    def leaveEvent(self, event):
        self.hovered.emit(-1, -1)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() != QtCore.Qt.LeftButton:
            return
        self._last_freehand = None
        self._select_anchor = None
        if self._tool == 'bucket' and self._bucket is not None and self._stroke_anchor is not None:
            bbox, mask = self._bucket
            ends = self._bucket_gradient_ends(
                bbox, self._stroke_anchor,
                self._drag_end(bool(event.modifiers() & QtCore.Qt.ShiftModifier)))
            self._bucket = self._stroke_anchor = self._stroke_preview_end = None
            self._apply_bucket(bbox, self._bucket_layer(bbox, mask, ends))
            return
        if self._tool in ('line', 'arc', 'gradient', 'ellipse') and self._stroke_anchor is not None:
            p0, s0 = self._stroke_anchor
            p1, s1 = self._drag_end(bool(event.modifiers() & QtCore.Qt.ShiftModifier))
            self._stroke_anchor = None
            self._stroke_preview_end = None
            if self._tool == 'gradient':
                if not self._apply_gradient(p0, s0, p1, s1):
                    self.update()
            else:
                self.push_undo_snapshot()
                self._set_cells(self._stroke_cells(p0, s0, p1, s1))

    def _cell_rect(self, pixel_index: int, stage_index: int) -> QtCore.QRectF:
        row_from_top = self.pixel_count() - 1 - pixel_index
        return QtCore.QRectF(stage_index * self._cell_width, row_from_top * self._cell_height,
                              self._cell_width, self._cell_height)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        # Only scale up the part of the image that's actually exposed - a long animation
        # zoomed in can be tens of thousands of pixels wide.
        exposed = event.rect()
        cw, ch = self._cell_width, self._cell_height
        s0 = max(0, exposed.left() // cw)
        s1 = min(self.stage_count() - 1, exposed.right() // cw)
        r0 = max(0, exposed.top() // ch)
        r1 = min(self.pixel_count() - 1, exposed.bottom() // ch)
        if s1 >= s0 and r1 >= r0:
            source = QtCore.QRect(s0, r0, s1 - s0 + 1, r1 - r0 + 1)
            target = QtCore.QRect(s0 * cw, r0 * ch, source.width() * cw, source.height() * ch)
            painter.drawImage(target, self._image, source)

        if self._selection is not None:
            first, last = self._selection
            rect = QtCore.QRectF(first * cw, 0, (last - first + 1) * cw, self.height())
            pen = QtGui.QPen(QtGui.QColor(80, 160, 255))
            if self._tool in ('select', 'gradient', 'bucket'):
                # The tools the selection actually limits - show it in full.
                painter.fillRect(rect, QtGui.QColor(80, 160, 255, 70))
                pen.setWidth(2)
            else:
                # Freehand/Line/Arc paint anywhere - just a faint reminder it's still there
                # for the stage buttons.
                pen.setStyle(QtCore.Qt.DashLine)
            painter.setPen(pen)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))

        if self._stroke_anchor is not None and self._stroke_preview_end is not None:
            shift = bool(QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ShiftModifier)
            p0, s0 = self._stroke_anchor
            p1, s1 = self._drag_end(shift)
            big_ellipse = (self._tool == 'ellipse'
                           and math.pi * max(0.5, abs(s1 - s0)) * max(0.5, abs(p1 - p0)) > 4000)
            if big_ellipse:
                # Thousands of per-cell rects would lag while dragging - show the outline
                # shape instead; the exact cells are painted on release.
                preview_color = QtGui.QColor(self._paint_color)
                preview_color.setAlpha(120)
                center = self._cell_rect(p0, s0).center()
                painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 1, QtCore.Qt.DashLine))
                painter.setBrush(preview_color if self._ellipse_filled else QtCore.Qt.NoBrush)
                painter.drawEllipse(center, max(0.5, abs(s1 - s0)) * cw, max(0.5, abs(p1 - p0)) * ch)
                painter.setBrush(QtCore.Qt.NoBrush)
            elif self._tool in ('line', 'arc', 'ellipse'):
                preview_color = QtGui.QColor(self._paint_color)
                preview_color.setAlpha(160)
                for p, s in self._stroke_cells(p0, s0, p1, s1):
                    painter.fillRect(self._cell_rect(p, s), preview_color)
            elif self._tool == 'bucket' and self._bucket is not None:
                bbox, mask = self._bucket
                layer = self._bucket_layer(bbox, mask,
                                           self._bucket_gradient_ends(bbox, (p0, s0), (p1, s1)))
                painter.drawImage(QtCore.QRect(bbox.x() * cw, bbox.y() * ch,
                                               bbox.width() * cw, bbox.height() * ch), layer)
            if self._tool == 'gradient' or (self._tool == 'bucket' and self._bucket is not None
                                            and (p0, s0) != (p1, s1)):
                if self._tool == 'gradient':
                    region = self._gradient_region()
                    image = self._gradient_image(region, p0, s0, p1, s1)
                    if image is not None:
                        painter.drawImage(QtCore.QRect(region.x() * cw, region.y() * ch,
                                                       region.width() * cw, region.height() * ch),
                                          image)
                pen = QtGui.QPen(QtGui.QColor(255, 255, 255))
                pen.setStyle(QtCore.Qt.DashLine)
                painter.setPen(pen)
                start = self._cell_rect(p0, s0).center()
                end = self._cell_rect(p1, s1).center()
                painter.drawLine(start, end)
                painter.drawEllipse(start, 3, 3)
                painter.drawEllipse(end, 3, 3)
                if self._gradient_shape != 'linear':
                    rx, ry = self._radii(p0, s0, p1, s1, self._gradient_shape)
                    painter.setBrush(QtCore.Qt.NoBrush)
                    painter.drawEllipse(start, rx * cw, ry * ch)

        painter.setPen(QtGui.QColor(60, 60, 60))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class GrafxStripPreview(QtWidgets.QWidget):
    """A looping blade-strip playback of a display-layout image (hilt at the bottom), one
    stage per tick. The image is pulled from a callable on every tick rather than copied in,
    so the painter's preview follows edits as they're made."""

    stage_changed = QtCore.Signal(int, int)   # stage_index, stage_count

    def __init__(self, image_source=None, parent=None):
        super().__init__(parent)
        self._source = image_source or (lambda: None)
        self._stage = 0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.set_delay_ms(DEFAULT_PREVIEW_DELAY_MS)
        self.setMinimumSize(24, 160)
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding)
        self.setFixedWidth(36)

    def set_image_source(self, image_source):
        self._source = image_source
        self._stage = 0
        self.update()

    def set_delay_ms(self, delay_ms: int):
        self._timer.setInterval(max(5, int(delay_ms)))

    def play(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def is_playing(self) -> bool:
        return self._timer.isActive()

    def _tick(self):
        image = self._source()
        count = image.width() if image is not None and not image.isNull() else 1
        self._stage = (self._stage + 1) % max(1, count)
        self.stage_changed.emit(self._stage, count)
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(20, 20, 20))
        image = self._source()
        if image is not None and not image.isNull():
            stage = min(self._stage, image.width() - 1)
            painter.drawImage(self.rect().adjusted(4, 4, -4, -4), image,
                              QtCore.QRect(stage, 0, 1, image.height()))
        painter.setPen(QtGui.QColor(90, 90, 90))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class PainterDocument:
    """One animation the painter can edit - a wizard state, or one BMP of a resource.
    Its grid (with its own undo history, selection and stage count) is created the first
    time it's shown and then kept, so switching away and back preserves everything."""

    def __init__(self, key, label: str, bmp_image: QtGui.QImage, state: str = None,
                 delay_ms: int = None, note: str = None, warning: str = None):
        self.key = key
        self.label = label
        self.state = state            # grafx_reader.GRAFX_STATES key, for the sequence preview
        self.delay_ms = delay_ms      # None = synced to sound (preview uses its sync speed)
        self.note = note
        self.warning = warning
        self._original = bmp_to_display(bmp_image)
        self.grid = None

    def display_image(self) -> QtGui.QImage:
        return self.grid.display_image() if self.grid is not None else self._original

    def is_modified(self) -> bool:
        """Edited and actually different from what it started as (undoing back to the
        original doesn't count)."""
        return (self.grid is not None and self.grid.is_modified()
                and self.grid.display_image() != self._original)

    def to_bmp_image(self) -> QtGui.QImage:
        return display_to_bmp(self.display_image())


# The order the board plays states through one blade cycle: (state, mode). 'once' plays the
# BMP through a single time; 'loop' repeats it for SEQUENCE_LOOP_MS (at least one pass).
SEQUENCE_ORDER = [('forever', 'loop'), ('preon', 'once'), ('poweron', 'once'),
                  ('leds', 'loop'), ('lockup', 'loop'), ('poweroff', 'once'),
                  ('postoff', 'once'), ('idle', 'loop')]
SEQUENCE_LABELS = {'preon': "Pre-On", 'poweron': "Power On", 'leds': "Idle (lit)",
                   'lockup': "Lockup", 'poweroff': "Power Off", 'postoff': "Post-Off",
                   'idle': "Idle (blade off)", 'forever': "Forever (plays alone)"}
SEQUENCE_DEFAULT = ('preon', 'poweron', 'leds', 'poweroff', 'postoff')
_PREVIEW_STATES_KEY = "grafx_preview_states"   # QSettings: the last states picked


class _StickyMenu(QtWidgets.QMenu):
    """A menu whose checkable items toggle without closing it, so several can be
    ticked in one go."""

    def mouseReleaseEvent(self, event):
        action = self.activeAction()
        if action is not None and action.isCheckable() and action.isEnabled():
            action.trigger()
            event.accept()
            return
        super().mouseReleaseEvent(event)
SEQUENCE_LOOP_MS = 2500
PREVIEW_PANEL_WIDTH = 180   # px - the painter's full-height preview column
PREVIEW_STRIP_WIDTH = 72    # px - the blade strip inside it
SEQUENCE_OFF_MS = 700


class GrafxSequencePreview(QtWidgets.QWidget):
    """Plays a list of segments back to back on a blade strip (hilt at the bottom), the way
    the board steps through states: each segment is {'label', 'source' (callable returning
    a display-layout image, read on every tick so unsaved edits show), 'delay_ms' (None =
    the sync speed), 'mode' ('once' | 'loop' | 'off')}, optionally with 'sounds'
    ([(path, ms)] - one is played when the segment starts) and 'delay_fn' (callable(sound_ms)
    -> ms per stage, for states synced to their sound)."""

    status_changed = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._segments = []
        self._index = 0
        self._stage = 0
        self._elapsed = 0
        self._sync_delay = DEFAULT_PREVIEW_DELAY_MS
        self._segment_delay = None    # ms per stage for the current segment, set at its start
        self._sound_enabled = True
        self._sound = QtMultimedia.QSoundEffect(self)
        self._loop_sound = QtMultimedia.QSoundEffect(self)   # hum / lockup, for 'loop_sounds'
        self._loop_sound.setLoopCount(QtMultimedia.QSoundEffect.Loop.Infinite.value)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.setMinimumSize(24, 160)
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding)
        self.setFixedWidth(36)

    def set_segments(self, segments):
        self._segments = list(segments)
        self._index = self._stage = self._elapsed = 0
        self._start_segment(play_sound=self.is_playing())
        self._emit_status()
        self.update()

    def set_sync_delay(self, delay_ms: int):
        self._sync_delay = max(5, int(delay_ms))
        self._start_segment(play_sound=False)

    def set_sound_enabled(self, enabled: bool):
        self._sound_enabled = enabled
        if not enabled:
            self._sound.stop()
            self._loop_sound.stop()
        elif self.is_playing():
            self._start_loop_sound()

    def play(self):
        if self._segments:
            self._timer.start()
            self._start_segment(play_sound=True, restart=False)

    def stop(self):
        self._timer.stop()
        self._sound.stop()
        self._loop_sound.stop()

    def _start_loop_sound(self):
        """Loop the current segment's hum/lockup sound (if it has one) for as long as the
        segment plays; stop it otherwise."""
        segment = self._segment()
        sounds = segment.get('loop_sounds') if segment is not None else None
        if not (sounds and self._sound_enabled and self.is_playing()):
            self._loop_sound.stop()
            return
        path, _ms = random.choice(sounds)
        route_to_default_output(self._loop_sound)
        self._loop_sound.setSource(QtCore.QUrl.fromLocalFile(str(path)))
        self._loop_sound.play()

    def _start_segment(self, play_sound: bool = True, restart: bool = True):
        """Work out the current segment's speed and, if it has sounds, start one - a synced
        segment's speed depends on which sound (of several lengths) was picked."""
        segment = self._segment()
        sound_ms = None
        if segment is not None and segment.get('sounds') and play_sound and self._sound_enabled \
                and (restart or self._stage == 0):
            path, sound_ms = random.choice(segment['sounds'])
            self._sound.stop()
            route_to_default_output(self._sound)
            self._sound.setSource(QtCore.QUrl.fromLocalFile(str(path)))
            self._sound.play()
        if segment is not None and segment.get('delay_fn') is not None:
            self._segment_delay = segment['delay_fn'](sound_ms)
        else:
            self._segment_delay = None
        if restart or self._stage == 0:
            self._start_loop_sound()
        self._apply_interval()

    def is_playing(self) -> bool:
        return self._timer.isActive()

    def _segment(self):
        return self._segments[self._index] if self._segments else None

    def _delay(self, segment) -> int:
        if segment is None or segment['mode'] == 'off':
            return 50
        if segment is self._segment() and self._segment_delay:
            return max(5, round(self._segment_delay))
        return max(5, segment.get('delay_ms') or self._sync_delay)

    def _apply_interval(self):
        self._timer.setInterval(self._delay(self._segment()))

    def _image(self, segment):
        if segment is None or segment['mode'] == 'off':
            return None
        image = segment['source']()
        return image if image is not None and not image.isNull() else None

    def _tick(self):
        segment = self._segment()
        if segment is None:
            return
        delay = self._delay(segment)
        self._elapsed += delay
        if segment['mode'] == 'off':
            if self._elapsed >= SEQUENCE_OFF_MS:
                self._advance()
        else:
            image = self._image(segment)
            count = image.width() if image is not None else 1
            self._stage += 1
            if segment['mode'] == 'once':
                if self._stage >= count:
                    self._advance()
            else:
                if self._stage >= count:
                    self._stage = 0
                if len(self._segments) > 1 and self._elapsed >= max(SEQUENCE_LOOP_MS, count * delay):
                    self._advance()
        self._emit_status()
        self.update()

    def _advance(self):
        self._index = (self._index + 1) % len(self._segments)
        self._stage = self._elapsed = 0
        self._start_segment()

    def _emit_status(self):
        segment = self._segment()
        if segment is None:
            self.status_changed.emit("")
            return
        image = self._image(segment)
        if image is None:
            self.status_changed.emit(segment['label'])
        else:
            self.status_changed.emit(
                f"{segment['label']}\n{min(self._stage, image.width() - 1) + 1}/{image.width()}")

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(20, 20, 20))
        image = self._image(self._segment())
        if image is not None:
            stage = min(self._stage, image.width() - 1)
            painter.drawImage(self.rect().adjusted(4, 4, -4, -4), image,
                              QtCore.QRect(stage, 0, 1, image.height()))
        painter.setPen(QtGui.QColor(90, 90, 90))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class GrafxPixelEditorWindow(QtWidgets.QDialog):
    """The actual painting surface, opened full-size (sized to the screen). Edits are local
    until one of the accept buttons is clicked; Cancel discards them (asking first if
    anything was changed).

    Normally opened on a list of PainterDocuments (every state of a wizard resource, or
    every BMP of an existing resource), switched with the "Editing:" dropdown - each keeps
    its own edits and undo history - while the preview plays them through as a saber
    sequence. The older single-animation form (width/stage_count plus colors or bmp_image)
    still works and becomes a one-document window. accept_buttons is [(label, action_key)];
    the clicked key ends up in self.chosen_action."""

    def __init__(self, width: int = 0, stage_count: int = 0, colors=None, parent=None, *,
                 bmp_image: QtGui.QImage = None, max_stages: int = MAX_STAGE_COUNT,
                 title: str = "Paint GraFx Stages", accept_buttons=None,
                 warning: str = None, preview_delay_ms: int = None, subject: str = None,
                 documents=None, current_key=None, timing=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.chosen_action = None
        if documents is None:
            if bmp_image is None:
                grid = GrafxPixelGridWidget(width, stage_count, max_stages=max_stages)
                if colors is not None:
                    grid.set_colors(colors)
                bmp_image = grid.to_bmp_image()
                grid.deleteLater()
            documents = [PainterDocument('main', subject or "Animation", bmp_image,
                                         delay_ms=preview_delay_ms, warning=warning)]
        self._documents = list(documents)
        self._building_preview_menu = True     # don't save/rebuild while setting up
        self._timing = timing   # core.grafx_timing.FontTiming: sounds + refreshfx, or None
        self._max_stages = max([max_stages] + [d.display_image().width() for d in self._documents])
        self._doc = None
        self._grid = None

        layout = QtWidgets.QVBoxLayout(self)

        # Which animation is on the grid - the full-size painter covers whatever opened it.
        header_row = QtWidgets.QHBoxLayout()
        editing_label = QtWidgets.QLabel("Editing:")
        editing_label.setStyleSheet("font-weight: bold; font-size: 16px;")
        self._doc_combo = QtWidgets.QComboBox()
        self._doc_combo.setStyleSheet("font-weight: bold; font-size: 16px;")
        self._doc_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        for doc in self._documents:
            self._doc_combo.addItem(doc.label, doc.key)
        self._doc_combo.setToolTip("Switch animation - edits to each are kept until you "
                                   "save or cancel. • marks changed ones.")
        self._doc_combo.currentIndexChanged.connect(self._switch_to)
        header_row.addWidget(editing_label)
        header_row.addWidget(self._doc_combo)
        self._doc_note_label = QtWidgets.QLabel()
        self._doc_note_label.setWordWrap(True)
        self._doc_note_label.setStyleSheet("color: #555555; font-style: italic; font-size: 11px;")
        header_row.addWidget(self._doc_note_label, stretch=1)
        layout.addLayout(header_row)

        self._warning_label = QtWidgets.QLabel()
        self._warning_label.setWordWrap(True)
        self._warning_label.setStyleSheet(
            "color: #8a4b00; background-color: #fff3cd; border: 1px solid #e0c060; "
            "padding: 4px;")
        layout.addWidget(self._warning_label)

        # Body: tools, grid and stage buttons on the left; the preview as a full-height
        # panel on the right. `layout` points at the left column until the nav buttons.
        outer_layout = layout
        body_row = QtWidgets.QHBoxLayout()
        outer_layout.addLayout(body_row, stretch=1)
        layout = QtWidgets.QVBoxLayout()
        body_row.addLayout(layout, stretch=1)

        # Left: tool list · middle: the color(s) the current tool paints with · right: that
        # tool's own options, plus the always-there animation settings. Anything only one
        # tool uses is shown only while that tool is selected (see _update_tool_ui).
        tools_row = QtWidgets.QHBoxLayout()

        # ---- left: tools
        tool_box = QtWidgets.QGroupBox("Tool")
        tool_col = QtWidgets.QVBoxLayout(tool_box)
        self._tool_group = QtWidgets.QButtonGroup(self)
        for key, label in (('freehand', "Freehand"), ('line', "Line"), ('arc', "Arc"),
                           ('ellipse', "Circle / ellipse"),
                           ('gradient', "Gradient"), ('bucket', "Bucket (fill)"),
                           ('select', "Select stages")):
            radio = QtWidgets.QRadioButton(label)
            radio.setProperty('tool', key)
            radio.setChecked(key == 'freehand')
            self._tool_group.addButton(radio)
            tool_col.addWidget(radio)
        tool_col.addStretch()
        # Controls act on whichever grid is current, so they look self._grid up when used
        # (via lambdas) rather than binding to one grid at connect time.
        self._tool_group.buttonToggled.connect(
            lambda button, checked: checked and self._on_tool_changed(button.property('tool')))
        tools_row.addWidget(tool_box)

        # ---- middle: colors
        self._colors_box = QtWidgets.QGroupBox("Paint color")
        colors_layout = QtWidgets.QVBoxLayout(self._colors_box)
        self._paint_container, self._color_widgets = create_rgb_picker_widget("", (255, 255, 255))
        self._paint_container.setToolTip("Used by Freehand, Line, Arc, Circle / ellipse, the "
                                         "Bucket's Paint color fill, Fill All Stages and the "
                                         "presets.")
        for spin in self._color_widgets[:3]:
            spin.valueChanged.connect(self._sync_paint_color)
        colors_layout.addWidget(self._paint_container)

        self._gradient_colors = QtWidgets.QWidget()
        gradient_colors_layout = QtWidgets.QVBoxLayout(self._gradient_colors)
        gradient_colors_layout.setContentsMargins(0, 0, 0, 0)
        gradient_pickers = QtWidgets.QHBoxLayout()
        color1_container, self._color1_widgets = create_rgb_picker_widget("Color 1", (255, 255, 255))
        color2_container, self._color2_widgets = create_rgb_picker_widget("Color 2", (0, 0, 0))
        for spin in self._color1_widgets[:3] + self._color2_widgets[:3]:
            spin.valueChanged.connect(self._sync_gradient_color)
        gradient_pickers.addWidget(color1_container)
        gradient_pickers.addWidget(color2_container)
        gradient_colors_layout.addLayout(gradient_pickers)
        swap_row = QtWidgets.QHBoxLayout()
        swap_button = QtWidgets.QPushButton("⇄ Swap")
        swap_button.setToolTip("Swap Color 1 and Color 2")
        swap_button.clicked.connect(self._swap_colors)
        swap_row.addWidget(swap_button)
        pick_hint = QtWidgets.QLabel("Right-click: pick Color 1 · Shift+right-click: Color 2")
        pick_hint.setStyleSheet("color: #666666; font-size: 11px;")
        swap_row.addWidget(pick_hint)
        swap_row.addStretch()
        gradient_colors_layout.addLayout(swap_row)
        colors_layout.addWidget(self._gradient_colors)
        colors_layout.addStretch()
        tools_row.addWidget(self._colors_box)

        # ---- right: tool options (per tool) + animation settings (always)
        right_col = QtWidgets.QVBoxLayout()
        self._options_box = QtWidgets.QGroupBox("Tool options")
        options_layout = QtWidgets.QVBoxLayout(self._options_box)
        self._tool_tip_label = QtWidgets.QLabel()
        self._tool_tip_label.setWordWrap(True)
        self._tool_tip_label.setStyleSheet("color: #555555; font-style: italic; font-size: 11px;")
        # Every tip fits in two lines at this width - reserving both up front keeps the
        # box's height (and so the grid's position) the same for every tool.
        self._options_box.setMinimumWidth(460)
        tip_font = QtGui.QFont(self._tool_tip_label.font())
        tip_font.setPixelSize(11)
        self._tool_tip_label.setMinimumHeight(2 * QtGui.QFontMetrics(tip_font).lineSpacing() + 4)
        options_layout.addWidget(self._tool_tip_label)
        self._options = {}

        def option(name, label, *widgets):
            row = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            if label:
                row_layout.addWidget(QtWidgets.QLabel(label))
            for widget in widgets:
                row_layout.addWidget(widget)
            row_layout.addStretch()
            options_layout.addWidget(row)
            self._options[name] = row

        self._brush_spin = QtWidgets.QSpinBox()
        self._brush_spin.setRange(1, 10)
        self._brush_spin.valueChanged.connect(lambda value: self._grid.set_brush_size(value))
        self._brush_label = QtWidgets.QLabel()
        option('brush', None, self._brush_label, self._brush_spin)

        self._flip_h_check = QtWidgets.QCheckBox("Flip ↔ (H)")
        self._flip_v_check = QtWidgets.QCheckBox("Flip ↕ (V)")
        self._flip_h_check.toggled.connect(lambda checked: self._grid.set_arc_flip_h(checked))
        self._flip_v_check.toggled.connect(lambda checked: self._grid.set_arc_flip_v(checked))
        option('arc', "Curve:", self._flip_h_check, self._flip_v_check)

        self._ellipse_filled_check = QtWidgets.QCheckBox("Filled (unticked: outline)")
        self._ellipse_filled_check.setChecked(True)
        self._ellipse_filled_check.toggled.connect(self._on_ellipse_filled_toggled)
        option('ellipse', None, self._ellipse_filled_check)

        self._bucket_mode_combo = QtWidgets.QComboBox()
        self._bucket_mode_combo.addItem("Paint color", 'solid')
        self._bucket_mode_combo.addItem("Gradient (Color 1 → 2)", 'gradient')
        self._bucket_mode_combo.setToolTip(
            "Fill with the Paint color, or with the Color 1 → Color 2 gradient. For a "
            "gradient, click to run it across the area over time, or drag from the clicked "
            "cell to set its direction (Shift snaps to 45°).")
        self._bucket_tolerance_spin = QtWidgets.QSpinBox()
        self._bucket_tolerance_spin.setRange(0, 255)
        self._bucket_tolerance_spin.setPrefix("±")
        self._bucket_tolerance_spin.setToolTip(
            "Tolerance: also fill cells whose red, green and blue are each within this much "
            "of the clicked cell's (0 = exact color only). Useful on fades and gradients.")
        self._bucket_all_check = QtWidgets.QCheckBox("Replace everywhere")
        self._bucket_all_check.setToolTip(
            "Fill every cell of that color, not just the connected area - e.g. to swap one "
            "color for another throughout the animation (or the selected stages).")
        for widget, signal in ((self._bucket_mode_combo, 'currentIndexChanged'),
                               (self._bucket_tolerance_spin, 'valueChanged'),
                               (self._bucket_all_check, 'toggled')):
            getattr(widget, signal).connect(self._sync_bucket_options)
        option('bucket_mode', "Fill with:", self._bucket_mode_combo)
        option('bucket_match', "Tolerance:", self._bucket_tolerance_spin, self._bucket_all_check)

        self._shape_combo = QtWidgets.QComboBox()
        for key, label in (('linear', "Linear"), ('radial', "Radial (circle)"),
                           ('elliptical', "Elliptical")):
            self._shape_combo.addItem(label, key)
        self._shape_combo.setToolTip(
            "Linear: Color 1 → Color 2 along the drag. Radial: Color 1 at the center you "
            "press, Color 2 on the circle you drag out to (round in cells: 1 stage = 1 pixel). "
            "Elliptical: separate radii over time (stages) and along the blade (pixels); "
            "Shift makes it a circle. For outside-in, Swap the colors.")
        self._shape_combo.currentIndexChanged.connect(
            lambda: self._grid.set_gradient_shape(self._shape_combo.currentData()))
        self._spread_combo = QtWidgets.QComboBox()
        for key, label in (('none', "No repeat"), ('repeat', "Repeat"),
                           ('mirror', "Mirror (loops seamlessly)")):
            self._spread_combo.addItem(label, key)
        self._spread_combo.setToolTip(
            "What happens past the end of a dragged gradient. Mirror goes 1→2→1→…, so a "
            "pulse ends on the color it started with and loops without a jump. With Radial/"
            "Elliptical, Repeat and Mirror make concentric rings.")
        self._spread_combo.currentIndexChanged.connect(
            lambda: self._grid.set_gradient_spread(self._spread_combo.currentData()))
        option('gradient_shape', "Shape:", self._shape_combo, self._spread_combo)

        fill_time_button = QtWidgets.QPushButton("Fill ↔ over time")
        fill_time_button.setToolTip("Color 1 at the first stage → Color 2 at the last, over "
                                    "the selected stages (or all of them): a fade")
        fill_time_button.clicked.connect(lambda: self._range_op(lambda: self._grid.fill_gradient('time')))
        fill_blade_button = QtWidgets.QPushButton("Fill ↕ hilt→tip")
        fill_blade_button.setToolTip("Color 1 at the hilt → Color 2 at the tip, over the "
                                     "selected stages (or all of them): a band along the blade")
        fill_blade_button.clicked.connect(lambda: self._range_op(lambda: self._grid.fill_gradient('blade')))
        option('gradient_fill', None, fill_time_button, fill_blade_button)
        self._gradient_scope_label = QtWidgets.QLabel()
        self._gradient_scope_label.setStyleSheet("color: #444444; font-size: 11px;")
        option('gradient_scope', None, self._gradient_scope_label)
        options_layout.addStretch()
        right_col.addWidget(self._options_box)

        animation_box = QtWidgets.QGroupBox("Animation")
        animation_form = QtWidgets.QFormLayout(animation_box)
        self._stage_count_spin = QtWidgets.QSpinBox()
        self._stage_count_spin.setRange(1, self._max_stages)
        self._stage_count_spin.setKeyboardTracking(False)
        self._stage_count_spin.valueChanged.connect(self._on_stage_count_changed)
        self._match_sound_check = QtWidgets.QCheckBox("Match sound length")
        self._applying_match = False
        # Starts unticked every time - ticking it resizes (and so changes) animations, which
        # shouldn't happen just from opening the painter.
        self._match_sound_check.toggled.connect(self._on_match_sound_toggled)
        self._match_mode_combo = QtWidgets.QComboBox()
        self._match_mode_combo.addItem("by adding blank stages", 'blank')
        self._match_mode_combo.addItem("by stretching", 'stretch')
        self._match_mode_combo.setToolTip(
            "How Match sound length changes the stage count. Adding blank stages keeps every "
            "painted stage as it is and adds black ones at the end to paint (or removes "
            "stages from the end if there are too many). Stretching keeps the animation's "
            "shape, holding each stage longer (or skipping some) so it plays slower/faster.")
        animation_form.addRow(f"Stages (max {self._max_stages}):", self._stage_count_spin)
        match_row = QtWidgets.QHBoxLayout()
        match_row.addWidget(self._match_sound_check)
        match_row.addWidget(self._match_mode_combo)
        match_row.addStretch()
        animation_form.addRow("", match_row)

        zoom_row = QtWidgets.QHBoxLayout()
        self._zoom_w_spin = QtWidgets.QSpinBox()
        self._zoom_w_spin.setRange(1, 40)
        self._zoom_w_spin.setToolTip("Width of each stage column, in screen pixels")
        self._zoom_h_spin = QtWidgets.QSpinBox()
        self._zoom_h_spin.setRange(1, 30)
        self._zoom_h_spin.setToolTip("Height of each blade-pixel row, in screen pixels")
        for spin in (self._zoom_w_spin, self._zoom_h_spin):
            spin.valueChanged.connect(self._on_zoom_spin_changed)
        fit_button = QtWidgets.QPushButton("Fit")
        fit_button.setToolTip("Zoom so the whole animation fits the window")
        fit_button.clicked.connect(lambda: self._fit_to_window(min_cell_width=1))
        zoom_row.addWidget(self._zoom_w_spin)
        zoom_row.addWidget(QtWidgets.QLabel("×"))
        zoom_row.addWidget(self._zoom_h_spin)
        zoom_row.addWidget(fit_button)
        zoom_row.addStretch()
        animation_form.addRow("Zoom (cell px):", zoom_row)
        right_col.addWidget(animation_box)
        tools_row.addLayout(right_col)
        tools_row.addStretch()

        self._tools_area = QtWidgets.QWidget()
        self._tools_area.setLayout(tools_row)
        tools_row.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tools_area)

        hint = QtWidgets.QLabel(
            "Rows are blade pixels (top = tip, bottom = hilt); columns are stages (left = "
            "stage 1, played first). Right-click picks up a cell's color. Ctrl+Z / Ctrl+Shift+Z "
            "undo and redo.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666666; font-style: italic; font-size: 11px;")
        layout.addWidget(hint)

        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(False)

        preview_panel = QtWidgets.QGroupBox("Preview")
        preview_panel.setFixedWidth(PREVIEW_PANEL_WIDTH)
        preview_col = QtWidgets.QVBoxLayout(preview_panel)
        self._preview = GrafxSequencePreview()
        self._preview.setFixedWidth(PREVIEW_STRIP_WIDTH)
        preview_col.addWidget(self._preview, stretch=1, alignment=QtCore.Qt.AlignHCenter)
        self._preview_status = QtWidgets.QLabel("")
        self._preview_status.setAlignment(QtCore.Qt.AlignHCenter)
        self._preview_status.setWordWrap(True)
        self._preview_status.setFixedWidth(PREVIEW_PANEL_WIDTH - 24)
        self._preview_status.setStyleSheet("font-size: 10px; color: #444444;")
        self._preview.status_changed.connect(self._preview_status.setText)
        preview_col.addWidget(self._preview_status, alignment=QtCore.Qt.AlignHCenter)
        self._preview_button = QtWidgets.QPushButton("Play")
        self._preview_button.clicked.connect(self._toggle_preview)
        preview_col.addWidget(self._preview_button)
        self._sequence_button = QtWidgets.QToolButton()
        self._sequence_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self._sequence_button.setToolTip(
            "Which states the preview plays, in the board's order (Pre-On → Power On → Idle "
            "→ Lockup → Power Off → Post-Off → Idle (off) → blade off). None ticked plays just "
            "the animation being edited. Remembered for next time.")
        sequence_menu = _StickyMenu(self._sequence_button)
        self._sequence_actions = {}
        present = {doc.state for doc in self._documents}
        remembered = self._remembered_preview_states()
        for state, _mode in SEQUENCE_ORDER[1:] + SEQUENCE_ORDER[:1]:   # Forever last
            action = sequence_menu.addAction(SEQUENCE_LABELS[state])
            action.setCheckable(True)
            action.setEnabled(state in present)
            action.setChecked(state in present and state in remembered)
            action.toggled.connect(self._on_preview_states_changed)
            self._sequence_actions[state] = action
        sequence_menu.addSeparator()
        sequence_menu.addAction("Tick all").triggered.connect(lambda: self._set_preview_states(True))
        sequence_menu.addAction("Untick all (just the one being edited)").triggered.connect(
            lambda: self._set_preview_states(False))
        self._sequence_button.setMenu(sequence_menu)
        self._sequence_button.setVisible(any(doc.state for doc in self._documents))
        self._building_preview_menu = False
        ticked = sum(a.isChecked() for a in self._sequence_actions.values())
        self._sequence_button.setText(f"States ({ticked})" if ticked else "States (current)")
        preview_col.addWidget(self._sequence_button)
        self._preview_delay_spin = QtWidgets.QSpinBox()
        self._preview_delay_spin.setRange(5, 2000)
        self._preview_delay_spin.setSuffix(" ms")
        self._preview_delay_spin.setToolTip(
            "Preview speed (ms per stage) for animations with no delay= - on the board "
            "those are synced to the sound's length. Doesn't change any file.")
        self._preview_delay_spin.setValue(DEFAULT_PREVIEW_DELAY_MS)
        self._preview_delay_spin.valueChanged.connect(self._preview.set_sync_delay)
        preview_col.addWidget(self._preview_delay_spin)
        self._sound_check = QtWidgets.QCheckBox("Sound")
        self._sound_check.setChecked(timing is not None)
        self._sound_check.setVisible(timing is not None)
        self._sound_check.setToolTip(
            f"Play {timing.label}'s sounds with Pre-On/Power On/Power Off/Post-Off, timed the "
            f"way the board would play them" if timing is not None else "")
        self._sound_check.toggled.connect(self._preview.set_sound_enabled)
        preview_col.addWidget(self._sound_check)

        layout.addWidget(self._scroll, stretch=1)

        self._status_label = QtWidgets.QLabel("")
        self._status_label.setStyleSheet("color: #444444; font-size: 11px;")
        layout.addWidget(self._status_label)

        range_row = QtWidgets.QHBoxLayout()
        self._selection_label = QtWidgets.QLabel()
        self._selection_label.setMinimumWidth(170)
        range_row.addWidget(self._selection_label)
        self._copy_button = QtWidgets.QPushButton("Copy")
        self._copy_button.setToolTip("Copy the selected stages (Ctrl+C) - they can be pasted "
                                     "into another animation too")
        self._copy_button.clicked.connect(self._copy)
        self._paste_button = QtWidgets.QPushButton("Paste")
        self._paste_button.setToolTip("Insert copied stages after the selection, or at the "
                                      "end if nothing is selected (Ctrl+V)")
        self._paste_button.clicked.connect(lambda: self._range_op(self._grid.paste))
        self._duplicate_button = QtWidgets.QPushButton("Duplicate")
        self._duplicate_button.setToolTip("Insert a copy of the selected stages right after "
                                          "them (Ctrl+D)")
        self._duplicate_button.clicked.connect(lambda: self._range_op(self._grid.duplicate_selection))
        self._insert_button = QtWidgets.QPushButton("Insert Blank")
        self._insert_button.setToolTip("Insert black stages before the selection, or at the "
                                       "end if nothing is selected")
        self._insert_button.clicked.connect(
            lambda: self._range_op(lambda: self._grid.insert_blank(self._insert_count_spin.value())))
        self._insert_count_spin = QtWidgets.QSpinBox()
        self._insert_count_spin.setRange(1, 500)
        self._delete_button = QtWidgets.QPushButton("Delete")
        self._delete_button.setToolTip("Remove the selected stages (Delete)")
        self._delete_button.clicked.connect(lambda: self._range_op(self._grid.delete_selection))
        self._reverse_button = QtWidgets.QPushButton("Reverse")
        self._reverse_button.setToolTip("Play the selected stages (or the whole animation, "
                                        "with nothing selected) backwards")
        self._reverse_button.clicked.connect(lambda: self._range_op(self._grid.reverse_selection))
        self._select_none_button = QtWidgets.QPushButton("Select None")
        self._select_none_button.setToolTip("Clear the stage selection (Esc)")
        self._select_none_button.clicked.connect(lambda: self._grid.set_selection(None))
        for widget in (self._select_none_button, self._copy_button, self._paste_button,
                       self._duplicate_button, self._insert_button, self._insert_count_spin,
                       self._delete_button, self._reverse_button):
            range_row.addWidget(widget)
        range_row.addStretch()
        layout.addLayout(range_row)

        mgmt_row = QtWidgets.QHBoxLayout()
        self._undo_button = QtWidgets.QPushButton("Undo")
        self._undo_button.clicked.connect(lambda: self._grid.undo())
        self._redo_button = QtWidgets.QPushButton("Redo")
        self._redo_button.clicked.connect(lambda: self._grid.redo())
        mgmt_row.addWidget(self._undo_button)
        mgmt_row.addWidget(self._redo_button)

        for sequence, slot in (
                (QtGui.QKeySequence.Undo, lambda: self._grid.undo()),
                (QtGui.QKeySequence.Redo, lambda: self._grid.redo()),
                (QtGui.QKeySequence.Copy, self._copy),
                (QtGui.QKeySequence.Paste, lambda: self._range_op(self._grid.paste)),
                (QtGui.QKeySequence("Ctrl+D"), lambda: self._range_op(self._grid.duplicate_selection)),
                (QtGui.QKeySequence.Delete, lambda: self._range_op(self._grid.delete_selection)),
                (QtGui.QKeySequence("Backspace"), lambda: self._range_op(self._grid.delete_selection)),
                (QtGui.QKeySequence("H"), lambda: self._flip_h_check.toggle()),
                (QtGui.QKeySequence("V"), lambda: self._flip_v_check.toggle()),
        ):
            QtGui.QShortcut(sequence, self).activated.connect(slot)

        self._fill_button = QtWidgets.QPushButton("Fill All Stages")
        self._filled = False
        self._fill_button.clicked.connect(self._on_fill_toggle)
        mgmt_row.addWidget(self._fill_button)

        mgmt_row.addWidget(QtWidgets.QLabel(
            "Start from a preset (uses the Paint color above, keeps current stage count):"))
        self._seed_combo = QtWidgets.QComboBox()
        self._seed_combo.addItems(['Solid Fade', 'Wipe', 'Flicker', 'Fire'])
        seed_button = QtWidgets.QPushButton("Apply")
        seed_button.clicked.connect(self._seed_from_preset)
        mgmt_row.addWidget(self._seed_combo)
        mgmt_row.addWidget(seed_button)
        mgmt_row.addStretch()
        layout.addLayout(mgmt_row)

        body_row.addWidget(preview_panel)
        layout = outer_layout

        nav_row = QtWidgets.QHBoxLayout()
        nav_row.addStretch()
        cancel_button = QtWidgets.QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        nav_row.addWidget(cancel_button)
        for label, action in (accept_buttons or [("Done", 'done')]):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(lambda _checked=False, a=action: self._accept_with(a))
            nav_row.addWidget(button)
        layout.addLayout(nav_row)

        # Size the color and option boxes for their fullest contents (both gradient pickers;
        # the tip plus the most option rows any tool shows - 3, for a gradient Bucket fill),
        # so switching tools never resizes them and the grid below never jumps.
        self._gradient_colors.setVisible(True)
        self._paint_container.setVisible(False)
        self._colors_box.setMinimumHeight(self._colors_box.sizeHint().height())
        self._colors_box.setMinimumWidth(self._colors_box.sizeHint().width())
        bucket = next(b for b in self._tool_group.buttons() if b.property('tool') == 'bucket')
        bucket.setChecked(True)
        self._bucket_mode_combo.setCurrentIndex(self._bucket_mode_combo.findData('gradient'))
        self._update_tool_ui()                      # the most option rows any tool shows
        self._options_box.layout().invalidate()     # drop the size cached for the last tool
        self._options_box.setMinimumHeight(self._options_box.layout().totalSizeHint().height())
        self._bucket_mode_combo.setCurrentIndex(0)
        self._tool_group.buttons()[0].setChecked(True)
        self._update_tool_ui()
        self._auto_fit = True
        start = next((i for i, d in enumerate(self._documents) if d.key == current_key), 0)
        self._doc_combo.blockSignals(True)
        self._doc_combo.setCurrentIndex(start)
        self._doc_combo.blockSignals(False)
        self._switch_to(start)
        self._rebuild_sequence()
        self._resize_to_screen()
        self._fit_to_window()

    # ------------------------------------------------------------------ documents

    def _grid_for(self, doc: PainterDocument) -> GrafxPixelGridWidget:
        if doc.grid is None:
            image = doc.display_image()
            grid = GrafxPixelGridWidget(image.height(), image.width(), max_stages=self._max_stages)
            grid.set_bmp_image(display_to_bmp(image))
            # Signals only matter while this grid is the one on screen.
            current = lambda g=grid: g is self._grid
            grid.eyedropped.connect(lambda c, g=grid: current(g) and self._on_eyedrop(c))
            grid.stage_count_changed.connect(
                lambda n, g=grid: current(g) and self._on_grid_stage_count_changed(n))
            grid.selection_changed.connect(lambda g=grid: current(g) and self._update_range_controls())
            grid.hovered.connect(lambda p, s, g=grid: current(g) and self._on_hover(p, s))
            grid.undo_available_changed.connect(lambda _v, g=grid: current(g) and self._update_undo_buttons())
            grid.redo_available_changed.connect(lambda _v, g=grid: current(g) and self._update_undo_buttons())
            grid.cell_painted.connect(self._refresh_doc_labels)
            grid.stage_count_changed.connect(self._refresh_doc_labels)
            grid.stage_count_changed.connect(lambda _n, g=grid: current(g) and self._update_warning())
            doc.grid = grid
        return doc.grid

    def _switch_to(self, index: int):
        if not 0 <= index < len(self._documents):
            return
        if self._grid is not None:
            self._scroll.takeWidget()
            self._grid.setParent(self)     # keep the grid (and its undo history) alive
            self._grid.hide()
        self._doc = self._documents[index]
        self._grid = self._grid_for(self._doc)
        self._scroll.setWidget(self._grid)
        self._grid.show()

        # Carry the window-level tool settings over to this grid.
        self._grid.set_paint_color(self._current_paint_color())
        self._sync_gradient_color()
        self._grid.set_gradient_spread(self._spread_combo.currentData())
        self._grid.set_gradient_shape(self._shape_combo.currentData())
        self._grid.set_tool(self._tool_group.checkedButton().property('tool'))
        self._sync_bucket_options()
        self._grid.set_brush_size(self._brush_spin.value())
        self._grid.set_ellipse_filled(self._ellipse_filled_check.isChecked())
        self._grid.set_arc_flip_h(self._flip_h_check.isChecked())
        self._grid.set_arc_flip_v(self._flip_v_check.isChecked())

        self._stage_count_spin.blockSignals(True)
        self._stage_count_spin.setValue(self._grid.stage_count())
        self._stage_count_spin.blockSignals(False)
        self._doc_note_label.setText(self._doc.note or "")
        self._update_warning()
        self._filled = False
        self._fill_button.setText("Fill All Stages")
        if self._auto_fit:
            self._fit_to_window()
        else:
            self._grid.set_cell_size(self._zoom_w_spin.value(), self._zoom_h_spin.value())
        self._update_range_controls()
        self._update_undo_buttons()
        self._update_match_sound()
        self._rebuild_sequence()

    def _update_warning(self):
        """The document's own warning (e.g. width mismatch) plus a live refreshfx/sound
        timing check of the animation on screen."""
        messages = [self._doc.warning] if self._doc.warning else []
        if self._timing is not None and self._doc.state:
            messages += self._timing.check(self._doc.state, self._grid.stage_count(),
                                           self._doc.delay_ms)
        self._warning_label.setText("\n".join("⚠ " + m for m in messages))
        self._warning_label.setVisible(bool(messages))

    def _refresh_doc_labels(self, *_args):
        for index, doc in enumerate(self._documents):
            text = ("• " if doc.is_modified() else "") + doc.label
            if self._doc_combo.itemText(index) != text:
                self._doc_combo.setItemText(index, text)
                self._doc_combo.adjustSize()   # room for the added "• "

    def _update_undo_buttons(self):
        self._undo_button.setEnabled(self._grid.can_undo())
        self._redo_button.setEnabled(self._grid.can_redo())

    def _document_for_state(self, state):
        """The animation the preview plays for a state: the one being edited if it's that
        state, else the first one (variant 1 of a resource)."""
        if self._doc is not None and self._doc.state == state:
            return self._doc
        return next((d for d in self._documents if d.state == state), None)

    def _rebuild_sequence(self, *_args):
        segments = []
        if any(doc.state for doc in self._documents):
            if self._sequence_actions['forever'].isChecked() and self._document_for_state('forever'):
                order = [('forever', 'loop')]   # on the board, Forever replaces everything
            else:
                order = [(s, m) for s, m in SEQUENCE_ORDER
                         if s != 'forever' and self._sequence_actions[s].isChecked()]
            for state, mode in order:
                doc = self._document_for_state(state)
                if doc is not None:
                    segment = {'label': doc.label, 'source': doc.display_image,
                               'delay_ms': doc.delay_ms, 'mode': mode}
                    if self._timing is not None and mode == 'loop':
                        segment['loop_sounds'] = self._timing.loop_sounds(state)
                        if segment['loop_sounds']:
                            segment['delay_fn'] = (
                                lambda _ms, d=doc, st=state: self._timing.effective_delay_ms(
                                    st, d.display_image().width(), d.delay_ms))
                    if self._timing is not None and mode == 'once':
                        segment['sounds'] = self._timing.sounds(state)
                        segment['delay_fn'] = (
                            lambda sound_ms, d=doc, st=state: self._timing.effective_delay_ms(
                                st, d.display_image().width(), d.delay_ms, sound_ms))
                    segments.append(segment)
            if segments and order[0][0] != 'forever':
                segments.append({'label': "(blade off)", 'source': None, 'delay_ms': None,
                                 'mode': 'off'})
        if not segments and self._doc is not None:
            # Just the animation being edited, over and over - with its sound: a one-shot
            # state replays its sound each time round, a looping one keeps its hum/lockup.
            doc = self._doc
            segment = {'label': doc.label, 'source': doc.display_image,
                       'delay_ms': doc.delay_ms, 'mode': 'loop'}
            if self._timing is not None and doc.state:
                if self._timing.sounds(doc.state):
                    segment['mode'] = 'once'
                    segment['sounds'] = self._timing.sounds(doc.state)
                    segment['delay_fn'] = (
                        lambda sound_ms, d=doc: self._timing.effective_delay_ms(
                            d.state, d.display_image().width(), d.delay_ms, sound_ms))
                else:
                    segment['loop_sounds'] = self._timing.loop_sounds(doc.state)
                    if segment['loop_sounds']:
                        segment['delay_fn'] = (
                            lambda _ms, d=doc: self._timing.effective_delay_ms(
                                d.state, d.display_image().width(), d.delay_ms))
            segments = [segment]
        playing = self._preview.is_playing()
        self._preview.set_segments(segments)
        if playing:
            self._preview.play()

    def documents(self):
        return list(self._documents)

    def modified_documents(self):
        return [doc for doc in self._documents if doc.is_modified()]

    def current_document(self) -> PainterDocument:
        return self._doc

    # ------------------------------------------------------------------ sizing / zoom

    def _resize_to_screen(self):
        screen = QtWidgets.QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else QtCore.QRect(0, 0, 1200, 800)
        width = max(600, min(1600, int(geo.width() * 0.92)))
        height = max(400, min(1100, int(geo.height() * 0.88)))
        self.resize(width, height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._auto_fit:
            # Deferred until the layout has resized the scroll area to match.
            QtCore.QTimer.singleShot(0, self._refit_if_auto)

    def _refit_if_auto(self):
        if self._auto_fit:
            self._fit_to_window()

    def _fit_to_window(self, min_cell_width: int = MIN_FIT_CELL_WIDTH):
        """Size each cell so the whole grid fits the scroll area's viewport when that's
        possible. The initial/auto fit keeps columns at least MIN_FIT_CELL_WIDTH wide (and
        scrolls) so long animations stay paintable; the Fit button goes all the way down."""
        viewport = self._scroll.viewport()
        available_width = max(100, viewport.width() - 4)
        available_height = max(100, viewport.height() - 4)
        cell_width = max(min_cell_width,
                         min(40, available_width // max(1, self._grid.stage_count())))
        cell_height = max(1, min(30, available_height // max(1, self._grid.pixel_count())))
        self._apply_zoom(cell_width, cell_height)
        self._auto_fit = True

    def _apply_zoom(self, cell_width: int, cell_height: int):
        self._grid.set_cell_size(cell_width, cell_height)
        for spin, value in ((self._zoom_w_spin, cell_width), (self._zoom_h_spin, cell_height)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)

    def _on_zoom_spin_changed(self):
        self._auto_fit = False
        self._grid.set_cell_size(self._zoom_w_spin.value(), self._zoom_h_spin.value())

    # ------------------------------------------------------------------ handlers

    # ------------------------------------------------------------------ preview states

    @staticmethod
    def _remembered_preview_states():
        try:
            saved = QtCore.QSettings().value(_PREVIEW_STATES_KEY)
        except Exception:
            saved = None
        if saved is None:
            return set(SEQUENCE_DEFAULT)
        if isinstance(saved, str):          # QSettings returns a 1-item list as a str
            saved = [saved] if saved else []
        return set(saved)

    def _on_preview_states_changed(self, *_args):
        ticked = [s for s, a in self._sequence_actions.items() if a.isChecked()]
        count = len(ticked)
        self._sequence_button.setText(f"States ({count})" if count else "States (current)")
        if not self._building_preview_menu:
            try:
                # Only states this window offers - others keep their remembered choice.
                remembered = self._remembered_preview_states()
                for state, action in self._sequence_actions.items():
                    if action.isEnabled():
                        (remembered.add if action.isChecked() else remembered.discard)(state)
                QtCore.QSettings().setValue(_PREVIEW_STATES_KEY, sorted(remembered))
            except Exception:
                pass
            self._rebuild_sequence()

    def _set_preview_states(self, checked: bool):
        self._building_preview_menu = True
        for action in self._sequence_actions.values():
            if action.isEnabled():
                action.setChecked(checked)
        self._building_preview_menu = False
        self._on_preview_states_changed()

    # ------------------------------------------------------------------ colors

    def _uses_gradient_colors(self) -> bool:
        """The current tool paints with Color 1 → Color 2, not the Paint color."""
        tool = self._tool_group.checkedButton().property('tool')
        return tool == 'gradient' or (tool == 'bucket'
                                      and self._bucket_mode_combo.currentData() == 'gradient')

    TOOL_TIPS = {
        'freehand': "Click or drag to paint. Shift-click draws a straight line from the last "
                    "painted cell.",
        'line': "Click, drag and release for a straight line. Hold Shift to snap to "
                "horizontal / vertical / 45°.",
        'arc': "Click, drag and release for a curve. H / V (or the boxes below) flip which way "
               "it bows.",
        'ellipse': "Press at the center and drag out: sideways = over time, up/down = along "
                   "the blade. Hold Shift for a circle.",
        'gradient': "Drag to set the direction (Radial / Elliptical: from the center out; "
                    "Shift snaps). Fills the selected stages, or everything.",
        'bucket': "Click to fill the connected area of that color, inside the selected stages "
                  "if any. Gradient fill: drag from the clicked cell to set its direction.",
        'select': "Drag across columns to select stages (Shift-click extends), then use the "
                  "stage buttons below the grid. Esc clears the selection.",
    }

    def _current_tool(self) -> str:
        return self._tool_group.checkedButton().property('tool')

    def _update_tool_ui(self):
        """Show only the colors and options the current tool uses."""
        tool = self._current_tool()
        gradient_colors = self._uses_gradient_colors()
        self._paint_container.setVisible(not gradient_colors)
        self._gradient_colors.setVisible(gradient_colors)
        self._colors_box.setTitle("Gradient colors" if gradient_colors else "Paint color")
        outline = tool == 'ellipse' and not self._ellipse_filled_check.isChecked()
        self._brush_label.setText("Outline thickness:" if outline else "Brush size:")
        visible = {
            'brush': tool in ('freehand', 'line', 'arc') or outline,
            'arc': tool == 'arc',
            'ellipse': tool == 'ellipse',
            'bucket_mode': tool == 'bucket',
            'bucket_match': tool == 'bucket',
            'gradient_shape': gradient_colors,
            'gradient_fill': tool == 'gradient',
            'gradient_scope': tool == 'gradient',
        }
        for name, row in self._options.items():
            row.setVisible(visible.get(name, False))
        self._tool_tip_label.setText(self.TOOL_TIPS.get(tool, ""))

    def _on_tool_changed(self, tool: str):
        if self._grid is not None:      # None while the window is still being built
            self._grid.set_tool(tool)
        self._update_tool_ui()

    def _on_ellipse_filled_toggled(self, checked: bool):
        self._grid.set_ellipse_filled(checked)
        self._update_tool_ui()

    def _sync_bucket_options(self, *_args):
        if self._grid is not None:
            self._grid.set_bucket_options(self._bucket_tolerance_spin.value(),
                                          self._bucket_all_check.isChecked(),
                                          self._bucket_mode_combo.currentData())
        self._update_tool_ui()

    def _sync_paint_color(self):
        if self._grid is not None:
            self._grid.set_paint_color(self._current_paint_color())
            self._grid.update()

    @staticmethod
    def _picker_color(widgets) -> QtGui.QColor:
        r_spin, g_spin, b_spin, _swatch = widgets
        return QtGui.QColor(r_spin.value(), g_spin.value(), b_spin.value())

    @staticmethod
    def _set_picker_color(widgets, color: QtGui.QColor):
        for spin, value in zip(widgets[:3], (color.red(), color.green(), color.blue())):
            spin.setValue(value)

    def _sync_gradient_color(self):
        if self._grid is not None:
            self._grid.set_gradient_colors(self._picker_color(self._color1_widgets),
                                           self._picker_color(self._color2_widgets))

    def _swap_colors(self):
        first = self._picker_color(self._color1_widgets)
        second = self._picker_color(self._color2_widgets)
        self._set_picker_color(self._color1_widgets, second)
        self._set_picker_color(self._color2_widgets, first)

    def keyPressEvent(self, event):
        # Shift changes how a Line/Gradient drag in progress snaps - redraw its preview.
        if event.key() == QtCore.Qt.Key_Shift:
            self._grid.update()
        # Esc clears a stage selection first; only with nothing selected does it fall
        # through to QDialog's close (which asks before discarding changes).
        if event.key() == QtCore.Qt.Key_Escape and self._grid.selection() is not None:
            self._grid.set_selection(None)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == QtCore.Qt.Key_Shift:
            self._grid.update()
        super().keyReleaseEvent(event)

    def _on_eyedrop(self, color: QtGui.QColor):
        """Right-click picks up a color into the Paint color - or, with the Gradient tool,
        into Color 1 (Shift+right-click: Color 2)."""
        if self._uses_gradient_colors():
            shift = QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ShiftModifier
            self._set_picker_color(self._color2_widgets if shift else self._color1_widgets, color)
        else:
            self._set_picker_color(self._color_widgets, color)

    def _on_hover(self, pixel_index: int, stage_index: int):
        if pixel_index < 0:
            self._status_label.setText("")
            return
        color = self._grid.color_at(pixel_index, stage_index)
        self._status_label.setText(
            f"Stage {stage_index + 1} of {self._grid.stage_count()}  ·  "
            f"pixel {pixel_index + 1} of {self._grid.pixel_count()} (from the hilt)  ·  "
            f"RGB {color.red()}, {color.green()}, {color.blue()}")

    def _on_stage_count_changed(self, value: int):
        if value == self._grid.stage_count():
            return
        self._grid.push_undo_snapshot()
        self._grid.set_stage_count(value)

    # ------------------------------------------------------------------ match sound length

    def _sound_matched_stages(self, doc):
        """(stage count, explanation) that makes doc's animation last as long as its sound
        (or qon/qoff): that duration ÷ the time each stage really takes - refreshfx when
        synced, or the doc's delay if that's slower. (None, why not) if it can't be worked
        out for this animation."""
        timing = self._timing
        if timing is None:
            return None, "No font to match - select one in the main window (or in the Match to sound panel) first."
        if not doc.state:
            return None, "This animation isn't tied to a state."
        basis = timing.basis(doc.state)
        if basis is None:
            return None, (f"{timing.label} has no sound to match for this state - Idle (blade "
                          f"off) and Forever have no sound of their own.")
        if not timing.refresh_ms:
            return None, f"{timing.label}'s blade profile has no refreshfx."
        per_stage = max(doc.delay_ms or 0, timing.refresh_ms)
        raw = max(1, basis['duration_ms'] // per_stage)
        stages = min(raw, self._max_stages)
        if basis['source'] != 'sound':
            source = basis['source']
        elif doc.state in ('leds', 'lockup'):
            source = "one loop of the shortest " + ("hum" if doc.state == 'leds' else "lockup sound")
        else:
            source = "the shortest sound"
        divisor = (f"delay {doc.delay_ms} ms" if doc.delay_ms and doc.delay_ms > timing.refresh_ms
                   else f"refreshfx {timing.refresh_ms} ms")
        cap = f", capped at the {self._max_stages}-stage limit" if raw > stages else ""
        return stages, (f"{source} ({basis['duration_ms']} ms) ÷ {divisor} = {raw} stages"
                        f"{cap} ({timing.label})")

    def _update_match_sound(self):
        """Enable the box when this animation has a sound to match; if it's ticked, resize
        the animation to match (stretched over time, as one undo step)."""
        stages, why = self._sound_matched_stages(self._doc)
        self._match_sound_check.setEnabled(stages is not None)
        self._match_mode_combo.setEnabled(stages is not None)
        self._match_sound_check.setToolTip(
            "Resize this animation so it lasts exactly as long as its sound: " + why
            if stages is not None else why)
        if stages is None or not self._match_sound_check.isChecked():
            return
        if self._grid.stage_count() != stages:
            self._applying_match = True
            self._grid.push_undo_snapshot()
            if self._match_mode_combo.currentData() == 'stretch':
                self._grid.set_bmp_image(resample_stages(self._grid.to_bmp_image(), stages))
            else:
                self._grid.set_stage_count(stages)   # black stages added / removed at the end
            self._applying_match = False
            self._refresh_doc_labels()

    def _on_match_sound_toggled(self, checked: bool):
        if checked:
            self._update_match_sound()

    def _on_grid_stage_count_changed(self, count: int):
        # Resizing by hand (spinbox, insert/delete stages, undo) means it no longer matches.
        if not self._applying_match and self._match_sound_check.isChecked():
            target, _why = self._sound_matched_stages(self._doc)
            if target is not None and count != target:
                self._match_sound_check.blockSignals(True)
                self._match_sound_check.setChecked(False)
                self._match_sound_check.blockSignals(False)
        self._stage_count_spin.blockSignals(True)
        self._stage_count_spin.setValue(count)
        self._stage_count_spin.blockSignals(False)
        self._preview._emit_status()      # its "stage N/total" counter, without waiting to play
        self._preview.update()
        if self._auto_fit:
            self._fit_to_window()
        self._update_range_controls()

    def _copy(self):
        if self._grid.copy_selection():
            self._update_range_controls()

    def _range_op(self, operation):
        if not operation():
            QtWidgets.QApplication.beep()
        self._update_range_controls()
        self._refresh_doc_labels()

    def _update_range_controls(self):
        selection = self._grid.selection()
        if selection is None:
            self._selection_label.setText("No stages selected")
            self._gradient_scope_label.setText(
                f"Gradients fill: all {self._grid.stage_count()} stages")
        else:
            first, last = selection
            self._selection_label.setText(
                f"Selected: stages {first + 1}–{last + 1} ({last - first + 1})")
            self._gradient_scope_label.setText(
                f"Gradients fill: selected stages {first + 1}–{last + 1} only")
        has_selection = selection is not None
        self._select_none_button.setEnabled(has_selection)
        room = self._grid.max_stages() - self._grid.stage_count()
        clip = GrafxPixelGridWidget.clipboard_stage_count()
        self._copy_button.setEnabled(has_selection)
        self._paste_button.setEnabled(0 < clip <= room)
        self._paste_button.setText(f"Paste ({clip})" if clip else "Paste")
        self._duplicate_button.setEnabled(
            has_selection and selection[1] - selection[0] + 1 <= room)
        self._insert_button.setEnabled(room > 0)
        self._insert_count_spin.setMaximum(max(1, room))
        self._delete_button.setEnabled(
            has_selection and selection[1] - selection[0] + 1 < self._grid.stage_count())

    def _toggle_preview(self):
        if self._preview.is_playing():
            self._preview.stop()
            self._preview_button.setText("Play")
        else:
            self._preview.play()
            self._preview_button.setText("Pause")

    def _current_paint_color(self) -> QtGui.QColor:
        r_spin, g_spin, b_spin, _swatch = self._color_widgets
        return QtGui.QColor(r_spin.value(), g_spin.value(), b_spin.value())

    def _on_fill_toggle(self):
        """Toggles between filling every stage with the paint color and clearing them back
        to black. Undoable, in addition to the button's own toggle-back behavior."""
        self._grid.push_undo_snapshot()
        if not self._filled:
            self._grid.fill_all(self._current_paint_color())
            self._fill_button.setText("Empty All Stages")
        else:
            self._grid.fill_all(QtGui.QColor(0, 0, 0))
            self._fill_button.setText("Fill All Stages")
        self._filled = not self._filled
        self._refresh_doc_labels()

    def _seed_from_preset(self):
        preset = self._seed_combo.currentText()
        width = self._grid.pixel_count()
        stage_count = self._grid.stage_count()
        color = self._current_paint_color()
        rgb = (color.red(), color.green(), color.blue())
        if preset == 'Solid Fade':
            image = grafx_writer.generate_solid_fade(width, stage_count, (0, 0, 0), rgb)
        elif preset == 'Wipe':
            image = grafx_writer.generate_wipe(width, stage_count, rgb, (0, 0, 0))
        elif preset == 'Flicker':
            image = grafx_writer.generate_flicker(width, stage_count, rgb, 60)
        elif preset == 'Fire':
            image = grafx_writer.generate_fire(width, stage_count, rgb)
        else:
            return
        self._grid.push_undo_snapshot()
        self._grid.set_bmp_image(image)
        self._fill_button.setText("Fill All Stages")
        self._filled = False
        self._refresh_doc_labels()

    def _accept_with(self, action: str):
        self.chosen_action = action
        self._preview.stop()
        self.accept()

    def reject(self):
        changed = self.modified_documents()
        if changed:
            names = "\n".join(f"  • {doc.label}" for doc in changed)
            response = QtWidgets.QMessageBox.question(
                self, "Discard Changes?",
                f"Discard the changes you've made to:\n\n{names}",
                QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Cancel)
            if response != QtWidgets.QMessageBox.Discard:
                return
        self._preview.stop()
        super().reject()

    # ------------------------------------------------------------------ results (current)

    def colors(self):
        return self._grid.colors()

    def stage_count(self) -> int:
        return self._grid.stage_count()

    def to_bmp_image(self) -> QtGui.QImage:
        return self._grid.to_bmp_image()


class GrafxStageEditor(QtWidgets.QWidget):
    """Compact launcher embedded in the wizard page: owns the actual stage data (as a
    BMP-layout image, so long animations stay cheap) and opens GrafxPixelEditorWindow to
    paint it."""

    stage_count_changed = QtCore.Signal(int)

    def __init__(self, width: int, initial_stage_count: int = 10, parent=None,
                 subject: str = None):
        super().__init__(parent)
        self._width = max(1, width)
        self._subject = subject   # shown in the painter, e.g. "Power On (state 1 of 3)"
        self._open_handler = None
        stage_count = max(1, min(MAX_STAGE_COUNT, initial_stage_count))
        self._image = display_to_bmp(_blank_image(stage_count, self._width))

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._summary_label = QtWidgets.QLabel()
        self._summary_label.setWordWrap(True)
        layout.addWidget(self._summary_label)

        edit_button = QtWidgets.QPushButton("Edit Stages...")
        edit_button.clicked.connect(self._open_editor)
        layout.addWidget(edit_button)
        layout.addStretch()

        self._update_summary()

    def _update_summary(self):
        self._summary_label.setText(
            f"{self.stage_count()} stage(s), {self._width} pixels wide. "
            f"Click \"Edit Stages...\" to paint them."
        )

    def set_open_handler(self, handler):
        """Let the owner open the painter instead (the wizard opens it on every state at
        once, then hands results back through set_image)."""
        self._open_handler = handler

    def set_image(self, image: QtGui.QImage):
        old_count = self.stage_count()
        self._image = QtGui.QImage(image)
        self._update_summary()
        if self.stage_count() != old_count:
            self.stage_count_changed.emit(self.stage_count())

    def _open_editor(self):
        if self._open_handler is not None:
            self._open_handler()
            return
        dialog = GrafxPixelEditorWindow(self._width, self.stage_count(), parent=self,
                                        bmp_image=self._image, subject=self._subject)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            old_count = self.stage_count()
            self._image = dialog.to_bmp_image()
            self._update_summary()
            if self.stage_count() != old_count:
                self.stage_count_changed.emit(self.stage_count())

    def stage_count(self) -> int:
        return self._image.height()

    def set_stage_count(self, new_count: int):
        """Resize the painted animation to a new stage count, preserving already-painted
        stages and filling any new ones with black - same convention as
        GrafxPixelGridWidget.set_stage_count. Lets the wizard page's "Number of stages"
        spinbox resize the animation without opening "Edit Stages..." first."""
        new_count = max(1, min(MAX_STAGE_COUNT, new_count))
        old_count = self.stage_count()
        if new_count == old_count:
            return
        display = bmp_to_display(self._image)
        if new_count < old_count:
            display = display.copy(0, 0, new_count, self._width)
        else:
            display = _splice(display, _blank_image(new_count - old_count, self._width))
        self._image = display_to_bmp(display)
        self._update_summary()
        self.stage_count_changed.emit(new_count)

    def to_image(self) -> QtGui.QImage:
        return QtGui.QImage(self._image)
