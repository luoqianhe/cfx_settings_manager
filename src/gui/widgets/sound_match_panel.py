# src/gui/widgets/sound_match_panel.py
"""'Match to sound' panel: shows how one GraFx state's animation lines up with a font's
sounds (or qon/qoff) and the blade profile's refreshfx, warns when stages can't all play,
and offers one-click fixes - which the host (wizard state page, resource editor) applies
via apply_requested(stage_count, delay_ms or None). See core/grafx_timing.py for the rules.
"""
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from core.grafx_timing import SOUND_ACTIONS

SYNCABLE_STATES = tuple(SOUND_ACTIONS)   # one-shot states with a sound to match


class SoundMatchPanel(QtWidgets.QGroupBox):
    apply_requested = QtCore.Signal(int, object)   # stage count, delay ms (None = synced)
    font_changed = QtCore.Signal()

    def __init__(self, state: str, main_window, preferred_fonts=(), parent=None):
        super().__init__("Match to sound", parent)
        self.state = state
        self.main_window = main_window
        self._timing = None
        self._stages = 0
        self._delay_ms = None

        self.font_combo = QtWidgets.QComboBox()
        self.font_combo.setToolTip("Whose sounds, qon/qoff and blade-profile refreshfx to "
                                   "match against")
        fonts = main_window.file_handler.load_font_folders() if main_window.file_handler else []
        for _num, _name, font_path in fonts:
            self.font_combo.addItem(font_path.name, str(font_path))
        preferred = [str(p) for p in preferred_fonts if p]
        if getattr(main_window, 'current_font_path', None):
            preferred.append(str(main_window.current_font_path))
        for path in preferred:
            index = self.font_combo.findData(path)
            if index >= 0:
                self.font_combo.setCurrentIndex(index)
                break
        self.font_combo.currentIndexChanged.connect(self._on_font_changed)

        self.info_label = QtWidgets.QLabel()
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color: #444444; font-size: 11px;")
        self.status_label = QtWidgets.QLabel()
        self.status_label.setWordWrap(True)

        self.sync_button = QtWidgets.QPushButton()
        self.sync_button.setToolTip(
            "Clear delay= so the board stretches the animation over the sound (or qon/qoff), "
            "and resize the animation to the most stages that can all play at this "
            "refreshfx. The animation is stretched/squashed over time, keeping its shape.")
        self.sync_button.clicked.connect(self._apply_sync)

        self.sound_combo = QtWidgets.QComboBox()
        self.sound_combo.setToolTip("The sound to match exactly")
        self.frame_delay_spin = QtWidgets.QSpinBox()
        self.frame_delay_spin.setRange(1, 2000)
        self.frame_delay_spin.setSuffix(" ms/stage")
        self.frame_delay_spin.setValue(20)
        self.frame_stages_label = QtWidgets.QLabel()
        self.frame_button = QtWidgets.QPushButton("Apply")
        self.frame_button.setToolTip(
            "Set a fixed delay= and resize the animation to that sound's length ÷ delay, so "
            "it lines up stage-for-stage with that one sound (the manual's frame-accurate "
            "method - other sounds of different lengths won't line up).")
        self.frame_button.clicked.connect(self._apply_frame_accurate)
        for widget in (self.sound_combo, self.frame_delay_spin):
            signal = getattr(widget, 'currentIndexChanged', None) or widget.valueChanged
            signal.connect(self._update_frame_row)

        font_row = QtWidgets.QHBoxLayout()
        font_row.addWidget(QtWidgets.QLabel("Font:"))
        font_row.addWidget(self.font_combo, stretch=1)
        frame_row = QtWidgets.QHBoxLayout()
        frame_row.addWidget(QtWidgets.QLabel("Frame-accurate:"))
        frame_row.addWidget(self.sound_combo, stretch=1)
        frame_row.addWidget(self.frame_delay_spin)
        frame_row.addWidget(self.frame_stages_label)
        frame_row.addWidget(self.frame_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(font_row)
        layout.addWidget(self.info_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.sync_button)
        layout.addLayout(frame_row)

        self._on_font_changed()

    # ---- public

    def timing(self):
        return self._timing

    def font_path(self):
        data = self.font_combo.currentData()
        return Path(data) if data else None

    def set_animation(self, stages: int, delay_ms):
        """The host's current stage count and delay (None/0 = synced) - updates the status."""
        self._stages = stages
        self._delay_ms = delay_ms or None
        self._update_status()

    # ---- internals

    def _on_font_changed(self):
        path = self.font_path()
        self._timing = self.main_window.font_timing(path) if path else None
        timing = self._timing
        self.sound_combo.blockSignals(True)
        self.sound_combo.clear()
        if timing is not None:
            for sound_path, ms in timing.sounds(self.state):
                self.sound_combo.addItem(f"{sound_path.name} ({ms} ms)", ms)
            if timing.refresh_ms:
                self.frame_delay_spin.setMinimum(timing.refresh_ms)
        self.sound_combo.blockSignals(False)

        if timing is None:
            self.info_label.setText("No font selected.")
        else:
            basis = timing.basis(self.state)
            parts = [f"Synced timing: {basis['description']}" if basis else
                     f"No {'/'.join(SOUND_ACTIONS.get(self.state, ()))} sounds in this font."]
            parts.append(f"refreshfx = {timing.refresh_ms} ms (blade profile)" if timing.refresh_ms
                         else "refreshfx isn't set for this font's blade profile.")
            fits = timing.max_synced_stages(self.state)
            if fits:
                parts.append(f"At most {fits} stages can all play when synced.")
            self.info_label.setText("  ·  ".join(parts))
        self._update_frame_row()
        self._update_status()
        self.font_changed.emit()

    def _update_frame_row(self):
        ms = self.sound_combo.currentData()
        delay = self.frame_delay_spin.value()
        has_sound = bool(ms)
        self.frame_button.setEnabled(has_sound)
        self.frame_stages_label.setText(f"→ {max(1, round(ms / delay))} stages" if has_sound else "")

    def _update_status(self):
        timing = self._timing
        fits = timing.max_synced_stages(self.state) if timing else None
        self.sync_button.setText(f"Sync to sound: {fits} stages, no delay" if fits
                                 else "Sync to sound")
        self.sync_button.setEnabled(bool(fits))
        if timing is None or not self._stages:
            self.status_label.setText("")
            return
        warnings = timing.check(self.state, self._stages, self._delay_ms)
        if warnings:
            self.status_label.setText("⚠ " + " ".join(warnings))
            self.status_label.setStyleSheet("color: #8a4b00; font-size: 11px;")
        elif timing.refresh_ms:
            per_stage = timing.effective_delay_ms(self.state, self._stages, self._delay_ms)
            total = f" ≈ {round(per_stage * self._stages)} ms in total" if per_stage else ""
            self.status_label.setText(f"✓ {self._stages} stages fit{total}.")
            self.status_label.setStyleSheet("color: #2e7d32; font-size: 11px;")
        else:
            self.status_label.setText("")

    def _apply_sync(self):
        fits = self._timing.max_synced_stages(self.state) if self._timing else None
        if fits:
            self.apply_requested.emit(fits, None)

    def _apply_frame_accurate(self):
        ms = self.sound_combo.currentData()
        if ms:
            delay = self.frame_delay_spin.value()
            self.apply_requested.emit(max(1, round(ms / delay)), delay)
