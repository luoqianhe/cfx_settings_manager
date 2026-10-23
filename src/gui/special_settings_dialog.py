# src/gui/special_settings_dialog.py
"""Edit special.txt - the hand-edited file of overrides and special modes (blademusicstyle,
maxvol, auto-on/off, OLED options, ...) that the main settings grid doesn't cover.

Every setting found in the file is listed, active or ##-disabled, with an on/off checkbox,
an input built from parameters.json when the app knows the setting (a plain text box
otherwise) and the file's own comment as its description. Saving changes only the edited
lines (core.flat_config.update_flat), after backing the file up.
"""
import json
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from core.flat_config import parse_flat, update_flat
from gui.widgets.widget_factory import (
    create_parameter_widget, get_widget_value, set_widget_value,
)

_PARAMETERS_PATH = Path(__file__).parent.parent / 'config' / 'parameters.json'
WARNINGS = {
    'maxvol': "The file itself warns: raising the maximum volume WILL VOID your saber "
              "speaker's warranty.",
    'pudis': "Disables the switches' pull-up resistors - only for repairing dead pads with "
             "external resistors.",
}


def load_parameter_definitions() -> dict:
    try:
        with open(_PARAMETERS_PATH, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


class SpecialSettingsDialog(QtWidgets.QDialog):
    def __init__(self, cfx_root: Path, main_window=None, focus_key: str = None):
        super().__init__(main_window)
        self.setWindowTitle("Special Settings (special.txt)")
        self.resize(820, 720)
        self.main_window = main_window
        self.path = Path(cfx_root) / 'special.txt'
        self.saved = False
        self._definitions = load_parameter_definitions()
        self._rows = {}        # key -> (enable_check, widget, display_type, baseline)

        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(
            "special.txt holds overrides and special modes that aren't in config.txt or the "
            "font settings. Unticked settings are kept in the file commented out with ##. "
            "Only the lines you change are rewritten - the file's comments stay as they are.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #555555;")
        layout.addWidget(intro)

        self.filter_edit = QtWidgets.QLineEdit()
        self.filter_edit.setPlaceholderText("Filter settings…")
        self.filter_edit.textChanged.connect(self._apply_filter)
        layout.addWidget(self.filter_edit)

        container = QtWidgets.QWidget()
        self._list = QtWidgets.QVBoxLayout(container)     # one card per setting
        self._list.addStretch()
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        layout.addWidget(scroll, stretch=1)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        self.revert_button = QtWidgets.QPushButton("Revert")
        self.revert_button.clicked.connect(self._load)
        self.save_button = QtWidgets.QPushButton("Save")
        self.save_button.clicked.connect(self._save)
        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.reject)
        for button in (self.revert_button, self.save_button, close_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self._load()
        if focus_key and focus_key in self._rows:
            self.filter_edit.setText(focus_key)

    # ------------------------------------------------------------------ building

    def _load(self):
        while self._list.count() > 1:                     # keep the trailing stretch
            widget = self._list.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._rows = {}
        if not self.path.is_file():
            self._list.insertWidget(0, QtWidgets.QLabel(f"No special.txt in {self.path.parent}."))
            self._update_buttons()
            return
        for entry in parse_flat(self.path):
            self._add_row(entry)
        self._apply_filter(self.filter_edit.text())
        self._update_buttons()

    def _add_row(self, entry: dict):
        key = entry['key']
        definition = self._definitions.get(key)
        check = QtWidgets.QCheckBox(key)
        check.setStyleSheet("font-weight: bold;")
        check.setToolTip("Ticked: active. Unticked: kept in the file as ##" + key + "=…")
        display_type = definition.get('display_type') if definition else None
        widget = None
        if definition:
            try:
                container, widget = create_parameter_widget(key, definition)
            except (ValueError, KeyError):
                widget = None
        if widget is None or not set_widget_value(widget, display_type, entry['value'], key):
            # Unknown setting, or a value its widget can't show (e.g. a list in a spinner):
            # edit it as text, so nothing is ever silently changed.
            container = widget = QtWidgets.QLineEdit(entry['value'])
            display_type = 'text_input'
        if container.layout() is not None:
            container.layout().setContentsMargins(0, 0, 0, 0)

        container.setMaximumWidth(420)     # long dropdown labels shouldn't crowd the rest
        check.setMinimumWidth(150)

        card = QtWidgets.QFrame()
        card.setFrameShape(QtWidgets.QFrame.StyledPanel)
        card_layout = QtWidgets.QVBoxLayout(card)
        card_layout.setContentsMargins(8, 6, 8, 6)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(check)
        top.addWidget(container, stretch=1)
        top.addStretch()
        card_layout.addLayout(top)
        text = entry['comment'] or (definition or {}).get('description', '')
        if text:
            description = QtWidgets.QLabel(text)
            description.setWordWrap(True)
            description.setStyleSheet("color: #555555; font-size: 11px;")
            card_layout.addWidget(description)
        if key in WARNINGS:
            warning = QtWidgets.QLabel("⚠ " + WARNINGS[key])
            warning.setWordWrap(True)
            warning.setStyleSheet("color: #B00020; font-size: 11px;")
            card_layout.addWidget(warning)

        check.setChecked(entry['enabled'])
        container.setEnabled(entry['enabled'])
        check.toggled.connect(container.setEnabled)
        check.toggled.connect(self._update_buttons)
        self._connect_change(widget)
        self._list.insertWidget(self._list.count() - 1, card)
        baseline = (entry['enabled'], self._value(widget, display_type))
        self._rows[key] = (check, widget, display_type, baseline, (card,))

    def _connect_change(self, widget):
        widgets = widget if isinstance(widget, tuple) else (widget,)
        for w in widgets:
            if isinstance(w, dict):
                continue
            for name in ('valueChanged', 'currentIndexChanged', 'toggled', 'textChanged'):
                signal = getattr(w, name, None)
                if signal is not None:
                    signal.connect(self._update_buttons)
                    break

    @staticmethod
    def _value(widget, display_type):
        if isinstance(widget, QtWidgets.QLineEdit):
            return widget.text().strip()
        return str(get_widget_value(widget, display_type))

    # ------------------------------------------------------------------ state

    def changes(self) -> dict:
        """{key: new value, or None to disable} for every edited setting."""
        changes = {}
        for key, (check, widget, display_type, baseline, _cells) in self._rows.items():
            was_enabled, old_value = baseline
            if not check.isChecked():
                if was_enabled:
                    changes[key] = None            # switched off -> comment it out
                continue
            value = self._value(widget, display_type)
            if not was_enabled or value != old_value:
                changes[key] = value
        return changes

    def _update_buttons(self, *_args):
        dirty = bool(self.changes()) if self._rows else False
        self.save_button.setEnabled(dirty)
        self.revert_button.setEnabled(dirty)

    def _apply_filter(self, text: str):
        text = text.strip().lower()
        for key, (*_rest, cells) in self._rows.items():
            visible = not text or text in key
            for widget in cells:
                widget.setVisible(visible)

    def _save(self) -> bool:
        changes = self.changes()
        if not changes:
            return True
        if 'maxvol' in changes and changes['maxvol'] is not None:
            response = QtWidgets.QMessageBox.warning(
                self, "Maximum Volume",
                "special.txt warns that changing maxvol WILL VOID your saber speaker's "
                "warranty. Save anyway?",
                QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Cancel)
            if response != QtWidgets.QMessageBox.Save:
                return False
        if self.main_window is not None and hasattr(self.main_window, '_backup_file'):
            self.main_window._backup_file(self.path, "(root)")
        try:
            update_flat(self.path, changes)
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "Save Failed", f"Couldn't write special.txt:\n{e}")
            return False
        self.saved = True
        self._load()
        return True

    def reject(self):
        if self._rows and self.changes():
            response = QtWidgets.QMessageBox.question(
                self, "Unsaved Changes", "Save your changes to special.txt?",
                QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard
                | QtWidgets.QMessageBox.Cancel)
            if response == QtWidgets.QMessageBox.Cancel:
                return
            if response == QtWidgets.QMessageBox.Save and not self._save():
                return
        super().reject()
