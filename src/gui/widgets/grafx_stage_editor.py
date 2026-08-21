# src/gui/widgets/grafx_stage_editor.py
"""A freeform pixel-grid painter for the GraFx Creator wizard's 'Custom' preset - lets the
user hand-paint every stage of an animation at once, rather than only picking from the 4
generated presets (Solid Fade/Wipe/Flicker/Fire).

The actual painting happens in a separate, screen-sized GrafxPixelEditorWindow rather than a
small embedded panel, since a real blade pixel count (100+) times up to 50 stages doesn't fit
in the wizard's page without scrolling while painting. GrafxStageEditor - what the wizard page
actually embeds - is just a compact launcher: a stage-count summary and an "Edit Stages..."
button.

The grid is drawn with blade pixels running vertically (top = tip, bottom = hilt, matching
BladePreviewWidget's hilt-at-the-bottom orientation) and stages running horizontally left
(stage 0, played first) to right. Internally colors are stored as
self._colors[pixel_index][stage_index], pixel_index 0 = hilt-end pixel (matches
core/grafx_reader.py's BMP column convention).
"""
from PySide6 import QtCore, QtGui, QtWidgets

from core import grafx_writer
from gui.widgets.widget_factory import create_rgb_picker_widget

MAX_STAGE_COUNT = 50
DEFAULT_CELL_WIDTH = 14   # px per stage column, before GrafxPixelEditorWindow fits it to screen
DEFAULT_CELL_HEIGHT = 5   # px per pixel row, same


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


class GrafxPixelGridWidget(QtWidgets.QWidget):
    """pixel_count rows x stage_count columns of paintable color cells, with a freehand/line
    tool and adjustable brush size."""

    cell_painted = QtCore.Signal()
    eyedropped = QtCore.Signal(QtGui.QColor)

    def __init__(self, pixel_count: int, stage_count: int, parent=None):
        super().__init__(parent)
        self._pixel_count = max(1, pixel_count)
        self._stage_count = max(1, min(MAX_STAGE_COUNT, stage_count))
        self._colors = [[QtGui.QColor(0, 0, 0) for _ in range(self._stage_count)]
                         for _ in range(self._pixel_count)]
        self._paint_color = QtGui.QColor(255, 255, 255)
        self._cell_width = DEFAULT_CELL_WIDTH
        self._cell_height = DEFAULT_CELL_HEIGHT
        self._tool = 'freehand'
        self._brush_size = 1
        self._line_anchor = None       # (pixel_index, stage_index) while dragging a line
        self._line_preview_end = None
        self.setMouseTracking(False)
        self._update_size()

    def _update_size(self):
        self.setFixedSize(self._stage_count * self._cell_width,
                           self._pixel_count * self._cell_height)

    def set_cell_size(self, cell_width: int, cell_height: int):
        self._cell_width = max(1, cell_width)
        self._cell_height = max(1, cell_height)
        self._update_size()
        self.update()

    def set_paint_color(self, color: QtGui.QColor):
        self._paint_color = QtGui.QColor(color)

    def set_tool(self, tool: str):
        self._tool = tool
        self._line_anchor = None
        self._line_preview_end = None
        self.update()

    def set_brush_size(self, size: int):
        self._brush_size = max(1, size)

    def stage_count(self) -> int:
        return self._stage_count

    def pixel_count(self) -> int:
        return self._pixel_count

    def colors(self):
        """[pixel_index][stage_index] -> QColor, pixel_index 0 = hilt-end pixel."""
        return self._colors

    def set_stage_count(self, new_count: int):
        new_count = max(1, min(MAX_STAGE_COUNT, new_count))
        if new_count == self._stage_count:
            return
        for row in self._colors:
            if new_count > len(row):
                row.extend([QtGui.QColor(0, 0, 0)] * (new_count - len(row)))
            else:
                del row[new_count:]
        self._stage_count = new_count
        self._update_size()
        self.updateGeometry()
        self.update()

    def set_colors(self, colors):
        """colors: [pixel_index][stage_index] -> QColor, must match pixel_count/stage_count."""
        self._colors = [[QtGui.QColor(c) for c in row] for row in colors]
        self.update()

    def fill_all(self, color: QtGui.QColor):
        self._colors = [[QtGui.QColor(color) for _ in range(self._stage_count)]
                         for _ in range(self._pixel_count)]
        self.update()

    def _cell_at(self, x: float, y: float):
        stage_index = max(0, min(self._stage_count - 1, int(x / self._cell_width)))
        row_from_top = max(0, min(self._pixel_count - 1, int(y / self._cell_height)))
        pixel_index = self._pixel_count - 1 - row_from_top  # top of widget = tip = highest index
        return pixel_index, stage_index

    def _brush_cells(self, pixel_index: int, stage_index: int):
        """Every cell covered by the brush, centered on (pixel_index, stage_index), clipped
        to the grid bounds."""
        half_lo = (self._brush_size - 1) // 2
        half_hi = self._brush_size // 2
        cells = []
        for dp in range(-half_lo, half_hi + 1):
            p = pixel_index + dp
            if not (0 <= p < self._pixel_count):
                continue
            for ds in range(-half_lo, half_hi + 1):
                s = stage_index + ds
                if 0 <= s < self._stage_count:
                    cells.append((p, s))
        return cells

    def _line_cells(self, p0: int, s0: int, p1: int, s1: int):
        cells = set()
        for s, p in _line_points(s0, p0, s1, p1):
            cells.update(self._brush_cells(p, s))
        return cells

    def _apply_paint(self, pixel_index: int, stage_index: int):
        for p, s in self._brush_cells(pixel_index, stage_index):
            self._colors[p][s] = QtGui.QColor(self._paint_color)
        self.update()
        self.cell_painted.emit()

    def mousePressEvent(self, event):
        pixel_index, stage_index = self._cell_at(event.position().x(), event.position().y())
        if event.button() == QtCore.Qt.RightButton:
            self.eyedropped.emit(QtGui.QColor(self._colors[pixel_index][stage_index]))
            return
        if event.button() != QtCore.Qt.LeftButton:
            return
        if self._tool == 'line':
            self._line_anchor = (pixel_index, stage_index)
            self._line_preview_end = (pixel_index, stage_index)
            self.update()
        else:
            self._apply_paint(pixel_index, stage_index)

    def mouseMoveEvent(self, event):
        pixel_index, stage_index = self._cell_at(event.position().x(), event.position().y())
        if self._tool == 'line' and self._line_anchor is not None:
            self._line_preview_end = (pixel_index, stage_index)
            self.update()
        elif self._tool == 'freehand' and event.buttons() & QtCore.Qt.LeftButton:
            self._apply_paint(pixel_index, stage_index)

    def mouseReleaseEvent(self, event):
        if (self._tool == 'line' and event.button() == QtCore.Qt.LeftButton
                and self._line_anchor is not None):
            p0, s0 = self._line_anchor
            p1, s1 = self._line_preview_end or self._line_anchor
            for p, s in self._line_cells(p0, s0, p1, s1):
                self._colors[p][s] = QtGui.QColor(self._paint_color)
            self._line_anchor = None
            self._line_preview_end = None
            self.update()
            self.cell_painted.emit()

    def _cell_rect(self, pixel_index: int, stage_index: int) -> QtCore.QRectF:
        row_from_top = self._pixel_count - 1 - pixel_index
        return QtCore.QRectF(stage_index * self._cell_width, row_from_top * self._cell_height,
                              self._cell_width, self._cell_height)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        for pixel_index in range(self._pixel_count):
            for stage_index in range(self._stage_count):
                painter.fillRect(self._cell_rect(pixel_index, stage_index),
                                  self._colors[pixel_index][stage_index])

        if self._tool == 'line' and self._line_anchor is not None and self._line_preview_end is not None:
            preview_color = QtGui.QColor(self._paint_color)
            preview_color.setAlpha(160)
            p0, s0 = self._line_anchor
            p1, s1 = self._line_preview_end
            for p, s in self._line_cells(p0, s0, p1, s1):
                painter.fillRect(self._cell_rect(p, s), preview_color)

        painter.setPen(QtGui.QColor(60, 60, 60))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class GrafxPixelEditorWindow(QtWidgets.QDialog):
    """The actual painting surface - opened full-size (sized to the screen) from
    GrafxStageEditor's "Edit Stages..." button, so painting never requires scrolling in the
    common case. Edits are local until "Done" is clicked; "Cancel" discards them."""

    def __init__(self, width: int, stage_count: int, colors, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Paint GraFx Stages")
        self._width = width

        layout = QtWidgets.QVBoxLayout(self)

        tools_row = QtWidgets.QHBoxLayout()

        color_container, self._color_widgets = create_rgb_picker_widget("Paint color", (255, 255, 255))
        r_spin, g_spin, b_spin, _swatch = self._color_widgets
        for spin in (r_spin, g_spin, b_spin):
            spin.valueChanged.connect(self._sync_paint_color)
        tools_row.addWidget(color_container)

        tool_col = QtWidgets.QVBoxLayout()
        tool_col.addWidget(QtWidgets.QLabel("Tool:"))
        self._tool_combo = QtWidgets.QComboBox()
        self._tool_combo.addItems(["Freehand", "Line"])
        self._tool_combo.currentTextChanged.connect(self._on_tool_changed)
        tool_col.addWidget(self._tool_combo)
        tools_row.addLayout(tool_col)

        brush_col = QtWidgets.QVBoxLayout()
        brush_col.addWidget(QtWidgets.QLabel("Brush size:"))
        self._brush_spin = QtWidgets.QSpinBox()
        self._brush_spin.setRange(1, 10)
        self._brush_spin.setValue(1)
        self._brush_spin.valueChanged.connect(self._on_brush_changed)
        brush_col.addWidget(self._brush_spin)
        tools_row.addLayout(brush_col)

        stage_col = QtWidgets.QVBoxLayout()
        stage_col.addWidget(QtWidgets.QLabel(f"Stage count (max {MAX_STAGE_COUNT}):"))
        self._stage_count_spin = QtWidgets.QSpinBox()
        self._stage_count_spin.setRange(1, MAX_STAGE_COUNT)
        self._stage_count_spin.setValue(max(1, min(MAX_STAGE_COUNT, stage_count)))
        self._stage_count_spin.valueChanged.connect(self._on_stage_count_changed)
        stage_col.addWidget(self._stage_count_spin)
        tools_row.addLayout(stage_col)

        tools_row.addStretch()
        layout.addLayout(tools_row)

        hint = QtWidgets.QLabel(
            "Rows are blade pixels (top = tip, bottom = hilt), columns are animation stages "
            "(left = stage 1, played first). Left-click/drag to paint (Freehand) or click-drag-"
            "release to draw a straight line (Line), right-click to pick up a cell's color."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666666; font-style: italic; font-size: 11px;")
        layout.addWidget(hint)

        self._grid = GrafxPixelGridWidget(self._width, self._stage_count_spin.value())
        self._grid.set_colors(colors)
        self._grid.eyedropped.connect(self._on_eyedrop)

        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidget(self._grid)
        self._scroll.setWidgetResizable(False)
        layout.addWidget(self._scroll, stretch=1)

        mgmt_row = QtWidgets.QHBoxLayout()
        self._fill_button = QtWidgets.QPushButton("Fill All Stages")
        self._filled = False
        self._fill_button.clicked.connect(self._on_fill_toggle)
        mgmt_row.addWidget(self._fill_button)

        mgmt_row.addWidget(QtWidgets.QLabel("Start from a preset (keeps current stage count):"))
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
        done_button = QtWidgets.QPushButton("Done")
        done_button.clicked.connect(self.accept)
        nav_row.addWidget(cancel_button)
        nav_row.addWidget(done_button)
        layout.addLayout(nav_row)

        self._sync_paint_color()
        self._resize_to_screen()
        self._recompute_cell_size()

    def _resize_to_screen(self):
        screen = QtWidgets.QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else QtCore.QRect(0, 0, 1200, 800)
        width = max(600, min(1400, int(geo.width() * 0.9)))
        height = max(400, min(1000, int(geo.height() * 0.85)))
        self.resize(width, height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recompute_cell_size()

    def _recompute_cell_size(self):
        """Size each cell so the whole grid fits the scroll area's current viewport without
        scrolling, when that's geometrically possible; falls back to a legible minimum (and
        lets the scroll area take over) for very large pixel/stage counts."""
        viewport = self._scroll.viewport()
        available_width = max(100, viewport.width())
        available_height = max(100, viewport.height())
        stage_count = self._grid.stage_count()
        pixel_count = self._grid.pixel_count()
        cell_width = max(6, min(40, available_width // max(1, stage_count)))
        cell_height = max(3, min(30, available_height // max(1, pixel_count)))
        self._grid.set_cell_size(cell_width, cell_height)

    def _sync_paint_color(self):
        r_spin, g_spin, b_spin, _swatch = self._color_widgets
        self._grid.set_paint_color(QtGui.QColor(r_spin.value(), g_spin.value(), b_spin.value()))

    def _on_eyedrop(self, color: QtGui.QColor):
        r_spin, g_spin, b_spin, _swatch = self._color_widgets
        r_spin.setValue(color.red())
        g_spin.setValue(color.green())
        b_spin.setValue(color.blue())

    def _on_tool_changed(self, text: str):
        self._grid.set_tool('line' if text == 'Line' else 'freehand')

    def _on_brush_changed(self, value: int):
        self._grid.set_brush_size(value)

    def _on_stage_count_changed(self, value: int):
        self._grid.set_stage_count(value)
        self._recompute_cell_size()

    def _current_paint_color(self) -> QtGui.QColor:
        r_spin, g_spin, b_spin, _swatch = self._color_widgets
        return QtGui.QColor(r_spin.value(), g_spin.value(), b_spin.value())

    def _on_fill_toggle(self):
        """Toggles between filling every stage with the paint color and clearing them back
        to black, so undoing a fill doesn't mean re-picking black and filling again."""
        if not self._filled:
            self._grid.fill_all(self._current_paint_color())
            self._fill_button.setText("Empty All Stages")
        else:
            self._grid.fill_all(QtGui.QColor(0, 0, 0))
            self._fill_button.setText("Fill All Stages")
        self._filled = not self._filled

    def _seed_from_preset(self):
        preset = self._seed_combo.currentText()
        stage_count = self._grid.stage_count()
        if preset == 'Solid Fade':
            image = grafx_writer.generate_solid_fade(self._width, stage_count, (0, 0, 0), (255, 255, 255))
        elif preset == 'Wipe':
            image = grafx_writer.generate_wipe(self._width, stage_count, (255, 255, 255), (0, 0, 0))
        elif preset == 'Flicker':
            image = grafx_writer.generate_flicker(self._width, stage_count, (255, 255, 255), 60)
        elif preset == 'Fire':
            image = grafx_writer.generate_fire(self._width, stage_count)
        else:
            return
        self._grid.set_colors(self._image_to_grid(image))
        self._fill_button.setText("Fill All Stages")
        self._filled = False

    def _image_to_grid(self, image: QtGui.QImage):
        """[pixel_index][stage_index] -> QColor, bottom-up per grafx_reader's convention (the
        same one grafx_writer._build_stage_image uses on write)."""
        stage_count, width = image.height(), image.width()
        grid = [[None] * stage_count for _ in range(width)]
        for stage_index in range(stage_count):
            bmp_row = stage_count - 1 - stage_index
            for pixel_index in range(width):
                grid[pixel_index][stage_index] = QtGui.QColor(image.pixel(pixel_index, bmp_row))
        return grid

    def colors(self):
        return self._grid.colors()

    def stage_count(self) -> int:
        return self._grid.stage_count()


class GrafxStageEditor(QtWidgets.QWidget):
    """Compact launcher embedded in the wizard page: owns the actual stage data and opens
    GrafxPixelEditorWindow to paint it."""

    def __init__(self, width: int, initial_stage_count: int = 10, parent=None):
        super().__init__(parent)
        self._width = max(1, width)
        self._stage_count = max(1, min(MAX_STAGE_COUNT, initial_stage_count))
        self._colors = self._blank_grid()

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

    def _blank_grid(self):
        return [[QtGui.QColor(0, 0, 0) for _ in range(self._stage_count)]
                for _ in range(self._width)]

    def _update_summary(self):
        self._summary_label.setText(
            f"{self._stage_count} stage(s), {self._width} pixels wide. "
            f"Click \"Edit Stages...\" to paint them."
        )

    def _open_editor(self):
        dialog = GrafxPixelEditorWindow(self._width, self._stage_count, self._colors, parent=self)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self._colors = [[QtGui.QColor(c) for c in row] for row in dialog.colors()]
            self._stage_count = dialog.stage_count()
            self._update_summary()

    def stage_count(self) -> int:
        return self._stage_count

    def to_image(self) -> QtGui.QImage:
        image = QtGui.QImage(self._width, self._stage_count, QtGui.QImage.Format_RGB32)
        for pixel_index in range(self._width):
            for stage_index in range(self._stage_count):
                bmp_row = self._stage_count - 1 - stage_index
                image.setPixel(pixel_index, bmp_row, self._colors[pixel_index][stage_index].rgb())
        return image
