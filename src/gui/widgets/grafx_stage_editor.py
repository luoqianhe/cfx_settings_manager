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
        self._gradient_color = QtGui.QColor(0, 0, 0)   # Color 2; _paint_color is Color 1
        self._gradient_spread = 'none'
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

    def set_gradient_color(self, color: QtGui.QColor):
        self._gradient_color = QtGui.QColor(color)
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

    def _gradient_image(self, region: QtCore.QRect, p0: int, s0: int, p1: int, s1: int):
        """The region filled with a Color 1 -> Color 2 linear gradient running from the
        center of cell (p0, s0) to the center of cell (p1, s1), so both end cells get their
        colors exactly. None for a zero-length drag."""
        if (p0, s0) == (p1, s1):
            return None
        top = self.pixel_count() - 1
        gradient = QtGui.QLinearGradient(
            s0 + 0.5 - region.x(), top - p0 + 0.5 - region.y(),
            s1 + 0.5 - region.x(), top - p1 + 0.5 - region.y())
        gradient.setColorAt(0.0, self._paint_color)
        gradient.setColorAt(1.0, self._gradient_color)
        gradient.setSpread(GRADIENT_SPREADS[self._gradient_spread])
        image = QtGui.QImage(region.size(), QtGui.QImage.Format_RGB32)
        painter = QtGui.QPainter(image)
        painter.fillRect(image.rect(), QtGui.QBrush(gradient))
        painter.end()
        return image

    def _apply_gradient(self, p0: int, s0: int, p1: int, s1: int) -> bool:
        region = self._gradient_region()
        image = self._gradient_image(region, p0, s0, p1, s1)
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
            return self._apply_gradient(0, first, 0, last)
        return self._apply_gradient(0, first, self.pixel_count() - 1, first)

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
        if shift and self._tool in ('line', 'gradient'):
            p0, s0 = self._stroke_anchor
            return _snap_45(p0, s0, p1, s1, self.pixel_count(), self.stage_count())
        return p1, s1

    def _stroke_cells(self, p0: int, s0: int, p1: int, s1: int):
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
        elif self._tool in ('line', 'arc', 'gradient'):
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
        elif self._tool in ('line', 'arc', 'gradient') and self._stroke_anchor is not None:
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
        if self._tool in ('line', 'arc', 'gradient') and self._stroke_anchor is not None:
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
            if self._tool in ('select', 'gradient'):
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
            if self._tool in ('line', 'arc'):
                preview_color = QtGui.QColor(self._paint_color)
                preview_color.setAlpha(160)
                for p, s in self._stroke_cells(p0, s0, p1, s1):
                    painter.fillRect(self._cell_rect(p, s), preview_color)
            elif self._tool == 'gradient':
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
SEQUENCE_OPTIONAL = {'lockup': "Lockup", 'idle': "Idle (blade off)",
                     'forever': "Forever (replaces everything else)"}
SEQUENCE_LOOP_MS = 2500
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

    def play(self):
        if self._segments:
            self._timer.start()
            self._start_segment(play_sound=True, restart=False)

    def stop(self):
        self._timer.stop()
        self._sound.stop()

    def _start_segment(self, play_sound: bool = True, restart: bool = True):
        """Work out the current segment's speed and, if it has sounds, start one - a synced
        segment's speed depends on which sound (of several lengths) was picked."""
        segment = self._segment()
        sound_ms = None
        if segment is not None and segment.get('sounds') and play_sound and self._sound_enabled \
                and (restart or self._stage == 0):
            path, sound_ms = random.choice(segment['sounds'])
            self._sound.stop()
            self._sound.setSource(QtCore.QUrl.fromLocalFile(str(path)))
            self._sound.play()
        if segment is not None and segment.get('delay_fn') is not None:
            self._segment_delay = segment['delay_fn'](sound_ms)
        else:
            self._segment_delay = None
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

        tools_row = QtWidgets.QHBoxLayout()

        color_container, self._color_widgets = create_rgb_picker_widget(
            "Paint color (Color 1)", (255, 255, 255))
        r_spin, g_spin, b_spin, _swatch = self._color_widgets
        for spin in (r_spin, g_spin, b_spin):
            spin.valueChanged.connect(self._sync_paint_color)
        tools_row.addWidget(color_container)

        gradient_col = QtWidgets.QVBoxLayout()
        color2_container, self._color2_widgets = create_rgb_picker_widget(
            "Gradient Color 2", (0, 0, 0))
        for spin in self._color2_widgets[:3]:
            spin.valueChanged.connect(self._sync_gradient_color)
        gradient_col.addWidget(color2_container)
        gradient_options = QtWidgets.QHBoxLayout()
        swap_button = QtWidgets.QPushButton("⇄ Swap")
        swap_button.setToolTip("Swap Color 1 and Color 2")
        swap_button.clicked.connect(self._swap_colors)
        gradient_options.addWidget(swap_button)
        self._spread_combo = QtWidgets.QComboBox()
        for key, label in (('none', "No repeat"), ('repeat', "Repeat"),
                           ('mirror', "Mirror (loops seamlessly)")):
            self._spread_combo.addItem(label, key)
        self._spread_combo.setToolTip(
            "What happens past the end of a dragged gradient. Mirror goes 1→2→1→…, so a "
            "pulse ends on the color it started with and loops without a jump.")
        self._spread_combo.currentIndexChanged.connect(
            lambda: self._grid.set_gradient_spread(self._spread_combo.currentData()))
        gradient_options.addWidget(self._spread_combo)
        gradient_col.addLayout(gradient_options)
        fill_options = QtWidgets.QHBoxLayout()
        fill_time_button = QtWidgets.QPushButton("Fill ↔ over time")
        fill_time_button.setToolTip("Color 1 at the first stage → Color 2 at the last, over "
                                    "the selected stages (or all of them): a fade")
        fill_time_button.clicked.connect(lambda: self._range_op(lambda: self._grid.fill_gradient('time')))
        fill_blade_button = QtWidgets.QPushButton("Fill ↕ hilt→tip")
        fill_blade_button.setToolTip("Color 1 at the hilt → Color 2 at the tip, over the "
                                     "selected stages (or all of them): a band along the blade")
        fill_blade_button.clicked.connect(lambda: self._range_op(lambda: self._grid.fill_gradient('blade')))
        fill_options.addWidget(fill_time_button)
        fill_options.addWidget(fill_blade_button)
        self._gradient_scope_label = QtWidgets.QLabel()
        self._gradient_scope_label.setStyleSheet("color: #444444; font-size: 11px;")
        gradient_col.addWidget(self._gradient_scope_label)
        gradient_col.addLayout(fill_options)
        tools_row.addLayout(gradient_col)

        tool_col = QtWidgets.QVBoxLayout()
        tool_col.addWidget(QtWidgets.QLabel("Tool:"))
        self._tool_group = QtWidgets.QButtonGroup(self)
        for key, label in (('freehand', "Freehand"), ('line', "Line"), ('arc', "Arc"),
                           ('gradient', "Gradient"), ('select', "Select stages")):
            radio = QtWidgets.QRadioButton(label)
            radio.setProperty('tool', key)
            radio.setChecked(key == 'freehand')
            self._tool_group.addButton(radio)
            tool_col.addWidget(radio)
        # Controls act on whichever grid is current, so they look self._grid up when used
        # (via lambdas) rather than binding to one grid at connect time.
        self._tool_group.buttonToggled.connect(
            lambda button, checked: checked and self._grid.set_tool(button.property('tool')))
        self._flip_h_check = QtWidgets.QCheckBox("Flip arc ↔ (H)")
        self._flip_v_check = QtWidgets.QCheckBox("Flip arc ↕ (V)")
        self._flip_h_check.toggled.connect(lambda checked: self._grid.set_arc_flip_h(checked))
        self._flip_v_check.toggled.connect(lambda checked: self._grid.set_arc_flip_v(checked))
        tool_col.addWidget(self._flip_h_check)
        tool_col.addWidget(self._flip_v_check)
        tools_row.addLayout(tool_col)

        settings_col = QtWidgets.QFormLayout()
        self._brush_spin = QtWidgets.QSpinBox()
        self._brush_spin.setRange(1, 10)
        self._brush_spin.valueChanged.connect(lambda value: self._grid.set_brush_size(value))
        settings_col.addRow("Brush size:", self._brush_spin)

        self._stage_count_spin = QtWidgets.QSpinBox()
        self._stage_count_spin.setRange(1, self._max_stages)
        self._stage_count_spin.setKeyboardTracking(False)
        self._stage_count_spin.valueChanged.connect(self._on_stage_count_changed)
        settings_col.addRow(f"Stages (max {self._max_stages}):", self._stage_count_spin)

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
        settings_col.addRow("Zoom (cell px):", zoom_row)
        tools_row.addLayout(settings_col)

        tools_row.addStretch()
        layout.addLayout(tools_row)

        hint = QtWidgets.QLabel(
            "Rows are blade pixels (top = tip, bottom = hilt), columns are animation stages "
            "(left = stage 1, played first). Left-click/drag to paint (Freehand), or click-"
            "drag-release to draw a straight line (Line), a curve (Arc) or a Color 1 → Color 2 "
            "gradient (Gradient - fills the selected stages, or everything). Hold Shift with "
            "Line or Gradient to snap to horizontal/vertical/45°; Shift-click with Freehand "
            "draws a line from the last painted cell. Right-click picks up a cell's color. "
            "With Select stages, drag across columns (Shift-click to extend) and use the stage "
            "buttons below; Esc or Select None clears the selection. Ctrl+Z / Ctrl+Shift+Z "
            "undo and redo. With the Arc tool, press H or V (or the checkboxes) to flip which "
            "way the curve bows."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666666; font-style: italic; font-size: 11px;")
        layout.addWidget(hint)

        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(False)

        preview_col = QtWidgets.QVBoxLayout()
        preview_title = QtWidgets.QLabel("Preview")
        preview_title.setStyleSheet("font-weight: bold;")
        preview_col.addWidget(preview_title, alignment=QtCore.Qt.AlignHCenter)
        self._preview = GrafxSequencePreview()
        preview_col.addWidget(self._preview, stretch=1, alignment=QtCore.Qt.AlignHCenter)
        self._preview_status = QtWidgets.QLabel("")
        self._preview_status.setAlignment(QtCore.Qt.AlignHCenter)
        self._preview_status.setWordWrap(True)
        self._preview_status.setFixedWidth(96)
        self._preview_status.setStyleSheet("font-size: 10px; color: #444444;")
        self._preview.status_changed.connect(self._preview_status.setText)
        preview_col.addWidget(self._preview_status, alignment=QtCore.Qt.AlignHCenter)
        self._preview_button = QtWidgets.QPushButton("Play")
        self._preview_button.clicked.connect(self._toggle_preview)
        preview_col.addWidget(self._preview_button)
        self._sequence_button = QtWidgets.QToolButton()
        self._sequence_button.setText("Sequence")
        self._sequence_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self._sequence_button.setToolTip(
            "The preview plays the states in the board's order: Pre-On → Power On → Idle "
            "(lit) → Power Off → Post-Off → blade off. Add the optional ones here.")
        sequence_menu = QtWidgets.QMenu(self._sequence_button)
        self._sequence_actions = {}
        present = {doc.state for doc in self._documents}
        for state, label in SEQUENCE_OPTIONAL.items():
            action = sequence_menu.addAction(label)
            action.setCheckable(True)
            action.setEnabled(state in present)
            action.toggled.connect(self._rebuild_sequence)
            self._sequence_actions[state] = action
        self._sequence_button.setMenu(sequence_menu)
        self._sequence_button.setVisible(any(doc.state for doc in self._documents))
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

        grid_row = QtWidgets.QHBoxLayout()
        grid_row.addWidget(self._scroll, stretch=1)
        grid_row.addLayout(preview_col)
        layout.addLayout(grid_row, stretch=1)

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
        self._grid.set_tool(self._tool_group.checkedButton().property('tool'))
        self._grid.set_brush_size(self._brush_spin.value())
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
                order = [('forever', 'loop')]
            else:
                order = [(s, m) for s, m in SEQUENCE_ORDER if s != 'forever' and
                         (s not in SEQUENCE_OPTIONAL or self._sequence_actions[s].isChecked())]
            for state, mode in order:
                doc = self._document_for_state(state)
                if doc is not None:
                    segment = {'label': doc.label, 'source': doc.display_image,
                               'delay_ms': doc.delay_ms, 'mode': mode}
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
            segments = [{'label': self._doc.label, 'source': self._doc.display_image,
                         'delay_ms': self._doc.delay_ms, 'mode': 'loop'}]
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

    def _sync_paint_color(self):
        if self._grid is not None:
            self._grid.set_paint_color(self._current_paint_color())
            self._grid.update()

    def _sync_gradient_color(self):
        if self._grid is not None:
            r_spin, g_spin, b_spin, _swatch = self._color2_widgets
            self._grid.set_gradient_color(QtGui.QColor(r_spin.value(), g_spin.value(), b_spin.value()))

    def _swap_colors(self):
        first = [spin.value() for spin in self._color_widgets[:3]]
        second = [spin.value() for spin in self._color2_widgets[:3]]
        for spin, value in zip(self._color_widgets[:3], second):
            spin.setValue(value)
        for spin, value in zip(self._color2_widgets[:3], first):
            spin.setValue(value)

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
        r_spin, g_spin, b_spin, _swatch = self._color_widgets
        r_spin.setValue(color.red())
        g_spin.setValue(color.green())
        b_spin.setValue(color.blue())

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

    def _on_grid_stage_count_changed(self, count: int):
        self._stage_count_spin.blockSignals(True)
        self._stage_count_spin.setValue(count)
        self._stage_count_spin.blockSignals(False)
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
