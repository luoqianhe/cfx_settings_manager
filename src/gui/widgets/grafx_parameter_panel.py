# src/gui/widgets/grafx_parameter_panel.py
"""Editors for the per-section parameters of a GraFx resource's grafx1.txt, driven by
config/grafx_parameters.json (same entry format as parameters.json, so the inputs come from
widget_factory like the main settings grid).

- AccentsEditor: the accents= string as a strip with one cell per blade pixel (hilt on the
  left), color-coded by attribute, with drag-select + apply and a raw text field.
- GrafxSectionEditor: one section - accents plus every other parameter, each with a "set"
  checkbox. Unchecked means the line is left out (or commented out with ##, as the stock
  files do) so the board uses its own behavior; e.g. delay unset = sync to the sound.
  Used directly by the GraFx Creator wizard (with delay/many/stop excluded, since the wizard
  has its own controls for those).
- GrafxParameterPanel: one tab per state for an existing resource folder, including
  switching a whole section on/off. Reports pending changes as operations for the caller
  to write with grafx_writer's line-level helpers.
"""
import json
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from core import grafx_reader
from gui.widgets.widget_factory import (
    create_parameter_widget, get_widget_value, set_widget_value,
)

_DEFINITIONS_PATH = Path(__file__).parent.parent.parent / 'config' / 'grafx_parameters.json'
_definitions = None

STATE_LABELS = {
    'poweron': 'Power On', 'poweroff': 'Power Off', 'leds': 'Idle (lit)', 'lockup': 'Lockup',
    'preon': 'Pre-On', 'postoff': 'Post-Off', 'idle': 'Idle (off)', 'forever': 'Forever',
}


def definitions() -> dict:
    global _definitions
    if _definitions is None:
        with open(_DEFINITIONS_PATH, encoding='utf-8') as f:
            _definitions = json.load(f)
    return _definitions


def attribute_color(char: str) -> QtGui.QColor:
    defs = definitions()
    attribute = defs['attributes'].get(char)
    if attribute is None:
        return QtGui.QColor(60, 60, 60)
    return QtGui.QColor(defs['attribute_groups'][attribute['group']])


# ---------------------------------------------------------------------------- accents


class AccentsStripWidget(QtWidgets.QWidget):
    """One cell per pixel, hilt on the left. Drag to select a range of pixels."""

    selection_changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._accents = ''
        self._selection = None      # (first, last) inclusive pixel indexes
        self._anchor = None
        self.setMouseTracking(True)
        self.setMinimumHeight(30)
        self.setMaximumHeight(30)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

    def set_accents(self, accents: str):
        self._accents = accents
        if self._selection and self._selection[1] >= len(accents):
            self._selection = None
            self.selection_changed.emit()
        self.update()

    def selection(self):
        return self._selection

    def clear_selection(self):
        self._selection = None
        self.selection_changed.emit()
        self.update()

    def _index_at(self, x: float) -> int:
        count = max(1, len(self._accents))
        return max(0, min(count - 1, int(x / max(1e-6, self.width() / count))))

    def mousePressEvent(self, event):
        if event.button() != QtCore.Qt.LeftButton or not self._accents:
            return
        index = self._index_at(event.position().x())
        if event.modifiers() & QtCore.Qt.ShiftModifier and self._selection:
            self._anchor = self._selection[0]
        else:
            self._anchor = index
        self._selection = tuple(sorted((self._anchor, index)))
        self.selection_changed.emit()
        self.update()

    def mouseMoveEvent(self, event):
        if not self._accents:
            return
        index = self._index_at(event.position().x())
        if event.buttons() & QtCore.Qt.LeftButton and self._anchor is not None:
            self._selection = tuple(sorted((self._anchor, index)))
            self.selection_changed.emit()
            self.update()
        char = self._accents[index]
        attribute = definitions()['attributes'].get(char)
        name = f"{attribute['name']} - {attribute['description']}" if attribute else "unknown attribute"
        QtWidgets.QToolTip.showText(event.globalPosition().toPoint(),
                                    f"Pixel {index + 1}: '{char}' {name}", self)

    def mouseReleaseEvent(self, event):
        self._anchor = None

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(30, 30, 30))
        count = len(self._accents)
        if count:
            cell = self.width() / count
            font = painter.font()
            font.setPixelSize(11)
            painter.setFont(font)
            separator = QtGui.QColor(30, 30, 30)
            for i, char in enumerate(self._accents):
                x0, x1 = int(i * cell), int((i + 1) * cell)
                rect = QtCore.QRect(x0, 0, x1 - x0, self.height())
                painter.fillRect(rect, attribute_color(char))
                if cell >= 5 and i:
                    painter.fillRect(QtCore.QRect(x0, 0, 1, self.height()), separator)
                if cell >= 9:
                    painter.setPen(QtGui.QColor(255, 255, 255))
                    painter.drawText(rect, QtCore.Qt.AlignCenter, char)
            if self._selection:
                first, last = self._selection
                rect = QtCore.QRectF(first * cell, 0, (last - first + 1) * cell, self.height())
                painter.fillRect(rect, QtGui.QColor(255, 255, 255, 70))
                pen = QtGui.QPen(QtGui.QColor(255, 255, 255))
                pen.setWidth(2)
                painter.setPen(pen)
                painter.drawRect(rect.adjusted(1, 1, -1, -1))
        painter.setPen(QtGui.QColor(90, 90, 90))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class AccentsEditor(QtWidgets.QWidget):
    """The accents= attribute string: strip + attribute picker + raw text."""

    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._width_hints = {}     # label -> expected pixel count (BMP width, ledstrip)

        self.strip = AccentsStripWidget()
        self.strip.selection_changed.connect(self._update_selection_label)

        self.attribute_combo = QtWidgets.QComboBox()
        for char, attribute in definitions()['attributes'].items():
            swatch = QtGui.QPixmap(12, 12)
            swatch.fill(attribute_color(char))
            self.attribute_combo.addItem(QtGui.QIcon(swatch), f"{char}  {attribute['name']}", char)
            self.attribute_combo.setItemData(self.attribute_combo.count() - 1,
                                             attribute['description'], QtCore.Qt.ToolTipRole)
        self.attribute_combo.currentIndexChanged.connect(self._update_attribute_hint)
        self.apply_button = QtWidgets.QPushButton("Apply to selected pixels")
        self.apply_button.clicked.connect(self._apply_to_selection)
        all_button = QtWidgets.QPushButton("Apply to all")
        all_button.clicked.connect(self._apply_to_all)

        self.selection_label = QtWidgets.QLabel()
        self.selection_label.setStyleSheet("color: #444444; font-size: 11px;")
        self.attribute_hint = QtWidgets.QLabel()
        self.attribute_hint.setWordWrap(True)
        self.attribute_hint.setStyleSheet("color: #666666; font-style: italic; font-size: 11px;")

        self.text_edit = QtWidgets.QLineEdit()
        self.text_edit.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        allowed = ''.join(definitions()['attributes'])
        self.text_edit.setValidator(QtGui.QRegularExpressionValidator(
            QtCore.QRegularExpression('[' + QtCore.QRegularExpression.escape(allowed) + ']*')))
        self.text_edit.textEdited.connect(self._on_text_edited)

        self.length_label = QtWidgets.QLabel()
        self.length_label.setWordWrap(True)
        self.resize_combo = QtWidgets.QComboBox()
        self.resize_button = QtWidgets.QPushButton("Resize")
        self.resize_button.setToolTip("Trim the string, or pad it with 'a' (sequenced) pixels")
        self.resize_button.clicked.connect(self._resize)

        picker_row = QtWidgets.QHBoxLayout()
        picker_row.addWidget(self.selection_label)
        picker_row.addStretch()
        picker_row.addWidget(self.attribute_combo)
        picker_row.addWidget(self.apply_button)
        picker_row.addWidget(all_button)
        length_row = QtWidgets.QHBoxLayout()
        length_row.addWidget(self.length_label, stretch=1)
        length_row.addWidget(self.resize_combo)
        length_row.addWidget(self.resize_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        hilt_tip = QtWidgets.QHBoxLayout()
        for text, align in (("hilt (pixel 1)", QtCore.Qt.AlignLeft), ("tip", QtCore.Qt.AlignRight)):
            label = QtWidgets.QLabel(text)
            label.setStyleSheet("color: #888888; font-size: 10px;")
            hilt_tip.addWidget(label, alignment=align)
        layout.addLayout(hilt_tip)
        layout.addWidget(self.strip)
        layout.addLayout(picker_row)
        layout.addWidget(self.attribute_hint)
        layout.addWidget(self.text_edit)
        layout.addLayout(length_row)

        self._update_selection_label()
        self._update_attribute_hint()

    def accents(self) -> str:
        return self.text_edit.text()

    def set_accents(self, accents: str, emit: bool = False):
        self.text_edit.setText(accents)
        self.strip.set_accents(accents)
        self._update_length()
        if emit:
            self.changed.emit()

    def set_width_hints(self, hints: dict):
        """{label: pixel count} the string's length should match, e.g. {'BMP width': 146,
        'blade (ledstrip)': 115}."""
        self._width_hints = {k: v for k, v in hints.items() if v}
        self.resize_combo.clear()
        for count in sorted(set(self._width_hints.values())):
            labels = ', '.join(k for k, v in self._width_hints.items() if v == count)
            self.resize_combo.addItem(f"{count} ({labels})", count)
        self._update_length()

    def _on_text_edited(self, text):
        self.strip.set_accents(text)
        self._update_length()
        self.changed.emit()

    def _replace(self, first: int, last: int):
        char = self.attribute_combo.currentData()
        text = self.accents()
        self.set_accents(text[:first] + char * (last - first + 1) + text[last + 1:], emit=True)

    def _apply_to_selection(self):
        if self.strip.selection():
            self._replace(*self.strip.selection())

    def _apply_to_all(self):
        if self.accents():
            self._replace(0, len(self.accents()) - 1)

    def _resize(self):
        count = self.resize_combo.currentData()
        if count:
            text = self.accents()
            self.set_accents(text[:count] + 'a' * max(0, count - len(text)), emit=True)

    def _update_selection_label(self):
        selection = self.strip.selection()
        self.apply_button.setEnabled(selection is not None)
        if selection:
            first, last = selection
            self.selection_label.setText(f"Pixels {first + 1}–{last + 1} selected")
        else:
            self.selection_label.setText("Drag across the strip to select pixels")

    def _update_attribute_hint(self):
        char = self.attribute_combo.currentData()
        self.attribute_hint.setText(definitions()['attributes'][char]['description'] if char else '')

    def _update_length(self):
        length = len(self.accents())
        mismatches = [f"{label} is {count}" for label, count in self._width_hints.items()
                      if count != length]
        text = f"{length} pixels declared."
        if mismatches:
            text += " ⚠ " + "; ".join(mismatches) + "."
            self.length_label.setStyleSheet("color: #8a4b00;")
        else:
            self.length_label.setStyleSheet("color: #444444;")
        self.length_label.setText(text)
        self.resize_combo.setVisible(bool(mismatches))
        self.resize_button.setVisible(bool(mismatches))


# ---------------------------------------------------------------------------- one section


class GrafxSectionEditor(QtWidgets.QWidget):
    """Every parameter of one grafx1.txt section. load() sets the baseline; changes()
    reports what differs from it as {key: value or None (= unset)}."""

    changed = QtCore.Signal()

    def __init__(self, state: str, exclude=(), parent=None):
        super().__init__(parent)
        self.state = state
        self._baseline = {}
        self._rows = {}     # key -> (set_check, input_widget, display_type, note_label, container)
        self._files_present = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        accents_box = QtWidgets.QGroupBox("accents - one attribute per pixel")
        accents_layout = QtWidgets.QVBoxLayout(accents_box)
        self.accents_set_check = QtWidgets.QCheckBox("Set accents= (recommended - every stock file has it)")
        self.accents_set_check.toggled.connect(self._on_accents_set_toggled)
        self.accents_editor = AccentsEditor()
        self.accents_editor.changed.connect(self._on_changed)
        accents_layout.addWidget(self.accents_set_check)
        accents_layout.addWidget(self.accents_editor)
        layout.addWidget(accents_box)

        grid = QtWidgets.QGridLayout()
        grid.setColumnStretch(3, 1)
        row = 0
        for key, param_def in definitions()['parameters'].items():
            if key in exclude:
                continue
            set_check = QtWidgets.QCheckBox(key)
            set_check.setStyleSheet("font-weight: bold;")
            set_check.setToolTip(f"Write {key}= in this section. Unchecked: left out / "
                                 f"commented out with ##.")
            container, widget = create_parameter_widget(key, param_def)
            container.layout().setContentsMargins(0, 0, 0, 0)
            display_type = param_def.get('display_type')
            set_widget_value(widget, display_type, param_def.get('default', 0))
            description = QtWidgets.QLabel(param_def.get('description', ''))
            description.setWordWrap(True)
            description.setStyleSheet("color: #555555; font-size: 11px;")
            note = QtWidgets.QLabel()
            note.setWordWrap(True)
            note.setStyleSheet("color: #8a4b00; font-size: 11px;")
            note.hide()
            text_col = QtWidgets.QVBoxLayout()
            text_col.addWidget(description)
            text_col.addWidget(note)
            extra = None
            if key == 'many':
                extra = QtWidgets.QPushButton("Match files")
                extra.setToolTip("Set many= to the number of BMP files present for this state")
                extra.clicked.connect(self._match_files)
                self._match_button = extra
            grid.addWidget(set_check, row, 0, alignment=QtCore.Qt.AlignTop)
            grid.addWidget(container, row, 1, alignment=QtCore.Qt.AlignTop)
            if extra is not None:
                grid.addWidget(extra, row, 2, alignment=QtCore.Qt.AlignTop)
            grid.addLayout(text_col, row, 3)
            self._rows[key] = (set_check, widget, display_type, note, container)
            set_check.toggled.connect(lambda checked, c=container: c.setEnabled(checked))
            set_check.toggled.connect(self._on_changed)
            self._connect_value_signal(widget)
            container.setEnabled(False)
            row += 1
        layout.addLayout(grid)

        self.other_label = QtWidgets.QLabel()
        self.other_label.setWordWrap(True)
        self.other_label.setStyleSheet("color: #666666; font-size: 11px;")
        self.other_label.hide()
        layout.addWidget(self.other_label)
        layout.addStretch()

    def _connect_value_signal(self, widget):
        for signal_name in ('valueChanged', 'currentIndexChanged', 'toggled', 'textChanged'):
            signal = getattr(widget, signal_name, None)
            if signal is not None:
                signal.connect(self._on_changed)
                return

    # ---- loading / reading

    def load(self, values: dict, width_hints: dict = None, files_present: int = None):
        """values: {key: str} as found in the file (absent key = not set)."""
        values = {k: v for k, v in (values or {}).items() if k != 'accents_count'}
        self._baseline = dict(values)
        self._files_present = files_present
        self.blockSignals(True)
        accents = values.get('accents')
        self.accents_set_check.setChecked(accents is not None)
        self.accents_editor.set_width_hints(width_hints or {})
        # A new accents string defaults to the BMP width (what the file actually drives),
        # else the blade's ledstrip count.
        bmp_widths = [v for k, v in (width_hints or {}).items() if k.startswith('BMP')]
        default_width = max(bmp_widths or list((width_hints or {}).values()) or [0])
        self.accents_editor.set_accents(accents if accents is not None else 'a' * default_width)
        self.accents_editor.setEnabled(accents is not None)
        for key, (set_check, widget, display_type, _note, container) in self._rows.items():
            param_def = definitions()['parameters'][key]
            present = key in values
            set_check.setChecked(present)
            container.setEnabled(present)
            if not (present and set_widget_value(widget, display_type, values[key])):
                set_widget_value(widget, display_type,
                                 files_present if key == 'many' and files_present
                                 else param_def.get('default', 0))
        others = {k: v for k, v in values.items()
                  if k != 'accents' and k not in definitions()['parameters']}
        self.other_label.setText("Other lines kept as they are: " + ", ".join(
            f"{k}={v}" for k, v in others.items()) if others else "")
        self.other_label.setVisible(bool(others))
        if hasattr(self, '_match_button'):
            self._match_button.setVisible(files_present is not None)
            self._match_button.setText(f"Match files ({files_present})" if files_present is not None
                                       else "Match files")
        self.blockSignals(False)
        self._update_notes()

    def values(self) -> dict:
        """{key: str} for every parameter that's set (accents first)."""
        result = {}
        if self.accents_set_check.isChecked() and self.accents_editor.accents():
            result['accents'] = self.accents_editor.accents()
        for key, (set_check, widget, display_type, _note, _container) in self._rows.items():
            if set_check.isChecked():
                result[key] = str(get_widget_value(widget, display_type))
        return result

    def changes(self) -> dict:
        current = self.values()
        managed = {'accents', *self._rows}
        changes = {}
        for key in managed:
            old, new = self._baseline.get(key), current.get(key)
            if old != new:
                changes[key] = new
        return changes

    def prefill_new_section(self):
        """For a section that doesn't exist yet: start with accents= (all 'a') and many=
        switched on, so switching the section on creates a usable one."""
        self.blockSignals(True)
        self.accents_set_check.setChecked(True)
        self.accents_editor.setEnabled(True)
        if 'many' in self._rows:
            set_check, widget, display_type, _note, container = self._rows['many']
            set_check.setChecked(True)
            container.setEnabled(True)
            set_widget_value(widget, display_type, max(1, self._files_present or 1))
        self.blockSignals(False)
        self._update_notes()

    def set_accents_width_hints(self, hints: dict):
        self.accents_editor.set_width_hints(hints)

    # ---- reactions

    def _on_accents_set_toggled(self, checked):
        self.accents_editor.setEnabled(checked)
        self._on_changed()

    def _on_changed(self, *_args):
        self._update_notes()
        if not self.signalsBlocked():
            self.changed.emit()

    def _match_files(self):
        if self._files_present:
            set_check, widget, display_type, _note, _container = self._rows['many']
            set_check.setChecked(True)
            set_widget_value(widget, display_type, self._files_present)

    def _update_notes(self):
        accents = self.accents_editor.accents() if self.accents_set_check.isChecked() else ''
        for key, (set_check, widget, display_type, note, _container) in self._rows.items():
            param_def = definitions()['parameters'][key]
            messages = []
            states = param_def.get('relevant_states')
            if states and self.state not in states:
                messages.append("Has no effect in this section on a GraFx blade.")
            needed = param_def.get('relevant_attributes', '')
            if needed and not any(c in accents for c in needed):
                messages.append(f"No pixel in accents= uses it (needs one of: "
                                f"{' '.join(needed)}).")
            if key == 'many' and self._files_present is not None:
                declared = int(get_widget_value(widget, display_type)) if set_check.isChecked() else 1
                if declared != self._files_present:
                    messages.append(f"{self._files_present} file(s) present for this state, "
                                    f"but only the first {min(declared, self._files_present)} "
                                    f"can play." if declared < self._files_present else
                                    f"Declares {declared} but only {self._files_present} "
                                    f"file(s) exist - missing ones fall back to #1.")
            note.setText(" ".join(messages))
            note.setVisible(bool(messages))


# ---------------------------------------------------------------------------- whole resource


class GrafxParameterPanel(QtWidgets.QWidget):
    """Tabs for every state section of one resource folder's grafx1.txt."""

    dirty_changed = QtCore.Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.folder = None
        self._status = {}           # state -> 'active' | 'disabled' | 'missing' (as loaded)
        self._tabs = {}             # state -> (active_check, editor)
        self._dirty = False

        self.tab_widget = QtWidgets.QTabWidget()
        self.tab_widget.setUsesScrollButtons(True)
        for state, label in STATE_LABELS.items():
            page = QtWidgets.QWidget()
            page_layout = QtWidgets.QVBoxLayout(page)
            active_check = QtWidgets.QCheckBox()
            active_check.toggled.connect(self._on_changed)
            status_label = QtWidgets.QLabel()
            status_label.setWordWrap(True)
            status_label.setStyleSheet("color: #666666; font-size: 11px;")
            editor = GrafxSectionEditor(state)
            editor.changed.connect(self._on_changed)
            active_check.toggled.connect(editor.setEnabled)
            page_layout.addWidget(active_check)
            page_layout.addWidget(status_label)
            page_layout.addWidget(editor)
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
            self.tab_widget.addTab(scroll, label)
            self._tabs[state] = (active_check, editor, status_label)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tab_widget)

    def load(self, folder: Path, blade_pixel_count: int = None, entries=()):
        """entries: grafx_reader.list_grafx_files(folder), for BMP widths and file counts."""
        self.folder = folder
        self._status = {}
        for state, (active_check, editor, status_label) in self._tabs.items():
            status = grafx_reader.section_status(folder, state) if folder else 'missing'
            self._status[state] = status
            if status == 'active':
                values = grafx_reader.section_settings(folder, state)
            elif status == 'disabled':
                values = grafx_reader.disabled_section_values(folder, state)
            else:
                values = {}
            state_files = [e for e in entries if e.state == state]
            widths = {QtGui.QImageReader(str(e.path)).size().width() for e in state_files}
            hints = {}
            if blade_pixel_count:
                hints['blade (ledstrip)'] = blade_pixel_count
            for width in sorted(w for w in widths if w > 0):
                hints[f"BMP width{'' if len(widths) == 1 else ' ' + str(width)}"] = width
            editor.load(values, hints, files_present=len(state_files))
            if status == 'missing':
                editor.prefill_new_section()

            active_check.blockSignals(True)
            active_check.setChecked(status == 'active')
            active_check.blockSignals(False)
            editor.setEnabled(status == 'active')
            active_check.setText({
                'active': "Section active",
                'disabled': "Section active (currently commented out with ##)",
                'missing': "Add this section to grafx1.txt",
            }[status])
            prefix = grafx_reader.GRAFX_STATES[state][1]
            status_label.setText(
                f"[{grafx_reader.GRAFX_STATES[state][0]}] · files: {prefix}1.bmp, "
                f"{prefix}2.bmp, … · {len(state_files)} present" +
                (" - with no BMP files this section has nothing to play." if not state_files else ""))
        self._refresh_tab_titles()
        self._set_dirty(False)

    def select_state(self, state: str):
        if state in STATE_LABELS:
            self.tab_widget.setCurrentIndex(list(STATE_LABELS).index(state))

    def pending_operations(self) -> list:
        """[{'state', 'section', 'enable': True|False|None, 'create': bool,
        'updates': {key: str|None}}] for every section with something to write."""
        operations = []
        for state, (active_check, editor, _status_label) in self._tabs.items():
            status = self._status.get(state, 'missing')
            want_active = active_check.isChecked()
            section = grafx_reader.GRAFX_STATES[state][0]
            if status == 'missing':
                if want_active:
                    operations.append({'state': state, 'section': section, 'enable': None,
                                       'create': True, 'updates': editor.values()})
                continue
            enable = None if want_active == (status == 'active') else want_active
            updates = editor.changes()
            if enable is not None or updates:
                operations.append({'state': state, 'section': section, 'enable': enable,
                                   'create': False, 'updates': updates})
        return operations

    def is_dirty(self) -> bool:
        return self._dirty

    def _on_changed(self, *_args):
        self._refresh_tab_titles()
        self._set_dirty(bool(self.pending_operations()))

    def _set_dirty(self, dirty: bool):
        if dirty != self._dirty:
            self._dirty = dirty
            self.dirty_changed.emit(dirty)

    def _refresh_tab_titles(self):
        for index, (state, (active_check, editor, _status_label)) in enumerate(self._tabs.items()):
            title = STATE_LABELS[state]
            if not active_check.isChecked():
                title += " (off)" if self._status.get(state) == 'disabled' else " (–)"
            self.tab_widget.setTabText(index, title)
