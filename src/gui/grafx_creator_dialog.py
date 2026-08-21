# src/gui/grafx_creator_dialog.py
"""GraFx Creator wizard: walks the user through generating a GraFx resource folder (BMP
animation files + grafx1.txt) from a handful of presets, with a live preview against the
same BladePreviewWidget/grafx_reader pipeline used elsewhere in the app - no external tools
needed to build a custom power-on/off, idle, lockup, pre-on, post-off, blade-off-idle, or
forever animation.
"""
import random
import shutil
import tempfile
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from core import grafx_writer
from core.file_handler import CFXFileHandler
from gui.widgets.blade_preview import BladePreviewWidget
from gui.widgets.widget_factory import create_rgb_picker_widget
from gui.widgets.grafx_stage_editor import GrafxStageEditor

DEFAULT_PIXEL_COUNT = 125  # fallback used when config.txt has no usable 'ledstrip' value

# state key -> (human label, style id to set on the preview so it plays this state via GraFx,
# or None for the two states with no style_* selector - see _off_idle_animation_active/
# _grafx_forever_state in blade_preview.py)
STATE_INFO = {
    'poweron': ('Power On', 'pon_style_id', '10'),
    'poweroff': ('Power Off', 'poff_style_id', '11'),
    'leds': ('Idle (blade lit)', 'unstable_id', '17'),
    'lockup': ('Lockup', 'lockup_style_id', '7'),
    'preon': ('Pre-On', 'preon_style_id', '4'),
    'postoff': ('Post-Off', 'postoff_style_id', '4'),
    'idle': ('Idle (blade off)', None, None),
    'forever': ('Forever (overrides everything else)', None, None),
}
STATE_ORDER = ['poweron', 'poweroff', 'leds', 'lockup', 'preon', 'postoff', 'idle', 'forever']
DEFAULT_CHECKED_STATES = ('poweron', 'poweroff')
ONE_SHOT_STATES = ('poweron', 'poweroff', 'preon', 'postoff')  # can meaningfully use stop=1/sync
PRESETS = ['Solid Fade', 'Wipe', 'Flicker', 'Fire', 'Custom']

# state key -> the blade-profile parameter that has to be set to "GraFx" for that state to
# actually play back from the linked resource (STATE_INFO's third element is exactly the
# right value for that param - the two dicts were grounded in the same parameters.json
# entries). 'idle' and 'forever' have no style selector - see STATE_INFO above - so they're
# not listed here; linking style_grafx alone is enough for those two.
FONT_PARAM_FOR_STATE = {
    'poweron': 'style_pon',
    'poweroff': 'style_poff',
    'leds': 'unstable',
    'lockup': 'style_lockup',
    'preon': 'style_preon',
    'postoff': 'style_postoff',
}


class GrafxCreatorDialog(QtWidgets.QDialog):
    def __init__(self, cfx_root: Path, main_window=None):
        super().__init__(main_window)
        self.cfx_root = Path(cfx_root)
        self.grafx_root = self.cfx_root / 'extra' / 'grafx'
        self.main_window = main_window
        self.setWindowTitle("GraFx Creator")
        self.resize(760, 560)

        self._staging_dir = Path(tempfile.mkdtemp(prefix="grafx_preview_"))
        self.state_widgets = {}  # state -> dict of control widgets, built after Setup->Next
        self.created_index = None
        self.created_folder = None

        self.stack = QtWidgets.QStackedWidget()
        self.setup_page = self._build_setup_page()
        self.stack.addWidget(self.setup_page)

        self.preview = BladePreviewWidget()
        self.preview.setFixedSize(140, 260)
        self.preview_label = QtWidgets.QLabel("Preview")
        self.preview_label.setStyleSheet("font-weight: bold;")
        self.preview_button = QtWidgets.QPushButton("Update Preview")
        self.preview_button.clicked.connect(self._on_preview_clicked)

        preview_panel = QtWidgets.QWidget()
        preview_layout = QtWidgets.QVBoxLayout(preview_panel)
        preview_layout.addWidget(self.preview_label)
        preview_layout.addWidget(self.preview, alignment=QtCore.Qt.AlignHCenter)
        preview_layout.addWidget(self.preview_button)
        preview_layout.addStretch()

        content_layout = QtWidgets.QHBoxLayout()
        content_layout.addWidget(self.stack, stretch=1)
        content_layout.addWidget(preview_panel)

        nav_layout = QtWidgets.QHBoxLayout()
        self.back_button = QtWidgets.QPushButton("< Back")
        self.back_button.clicked.connect(self._go_back)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.next_button = QtWidgets.QPushButton("Next >")
        self.next_button.clicked.connect(self._go_next)
        nav_layout.addWidget(self.back_button)
        nav_layout.addStretch()
        nav_layout.addWidget(self.cancel_button)
        nav_layout.addWidget(self.next_button)

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.addLayout(content_layout)
        main_layout.addLayout(nav_layout)

        self.stack.currentChanged.connect(self._update_nav_and_preview_visibility)
        self._update_nav_and_preview_visibility()

    def _default_pixel_count(self) -> int:
        """The 'ledstrip' parameter in the root config.txt's global header defines the main
        blade's actual pixel count (0 means the board is in high-power LED mode, not a pixel
        blade at all) - use it as the starting Blade pixel count whenever it's set, since it's
        the real value for this card rather than a guess."""
        try:
            global_settings = CFXFileHandler(self.cfx_root).load_master_config()
            ledstrip = int(global_settings.get('ledstrip', 0))
            if ledstrip > 0:
                return ledstrip
        except (ValueError, TypeError, OSError):
            pass
        return DEFAULT_PIXEL_COUNT

    # ------------------------------------------------------------------ setup page

    def _build_setup_page(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)

        title = QtWidgets.QLabel("Create a new GraFx resource")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        form = QtWidgets.QFormLayout()
        self.pixel_count_spin = QtWidgets.QSpinBox()
        self.pixel_count_spin.setRange(1, 1000)
        self.pixel_count_spin.setValue(self._default_pixel_count())
        form.addRow("Blade pixel count:", self.pixel_count_spin)

        self.name_edit = QtWidgets.QLineEdit("MyGrafx")
        form.addRow("Resource name:", self.name_edit)

        self.index_spin = QtWidgets.QSpinBox()
        self.index_spin.setRange(0, 999)
        self.index_spin.setValue(grafx_writer.next_available_grafx_index(self.grafx_root))
        form.addRow("Resource number:", self.index_spin)
        layout.addLayout(form)

        hint = QtWidgets.QLabel(
            "The pixel count should match your blade's actual LED count for the animation "
            "to look right on real hardware."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666666; font-style: italic; font-size: 11px;")
        layout.addWidget(hint)

        layout.addWidget(QtWidgets.QLabel("Which animations do you want to create?"))
        self.state_checks = {}
        for state in STATE_ORDER:
            label, _, _ = STATE_INFO[state]
            check = QtWidgets.QCheckBox(label)
            check.setChecked(state in DEFAULT_CHECKED_STATES)
            self.state_checks[state] = check
            layout.addWidget(check)

        layout.addWidget(self._build_link_section())

        layout.addStretch()
        return page

    def _selected_font_name(self):
        """Display name of whichever font is currently selected in the main window, or None
        if the wizard was opened with no font selected (or no main_window at all - e.g. under
        a headless test)."""
        if self.main_window is None:
            return None
        current_item = self.main_window.font_list.currentItem()
        if current_item is None:
            return None
        font_path = Path(current_item.data(QtCore.Qt.UserRole))
        return '-'.join(font_path.name.split('-')[1:]) or font_path.name

    def _build_link_section(self):
        """Optionally set style_grafx{1,2,3} plus the per-state style_* params directly on the
        currently selected font's live settings grid, so the user doesn't have to go find and
        set each dropdown by hand after the wizard closes. Nothing is written to disk here -
        it just stages the same widgets the settings grid already saves from, so the normal
        Save Changes flow (and its backup/confirmation prompts) still applies."""
        box = QtWidgets.QGroupBox("Link to current font")
        layout = QtWidgets.QVBoxLayout(box)

        font_name = self._selected_font_name()
        self.link_check = QtWidgets.QCheckBox()
        if font_name is not None:
            self.link_check.setText(f"Automatically set up '{font_name}' to use this resource")
            self.link_check.setChecked(True)
        else:
            self.link_check.setText("Automatically set up the selected font to use this resource")
            self.link_check.setChecked(False)
            self.link_check.setEnabled(False)
        layout.addWidget(self.link_check)

        slot_row = QtWidgets.QHBoxLayout()
        slot_row.addWidget(QtWidgets.QLabel("Blade:"))
        self.link_slot_combo = QtWidgets.QComboBox()
        self.link_slot_combo.addItem("Main blade (style_grafx1)", "1")
        self.link_slot_combo.addItem("Aux 1 (style_grafx2)", "2")
        self.link_slot_combo.addItem("Aux 2 (style_grafx3)", "3")
        self.link_slot_combo.setEnabled(font_name is not None)
        slot_row.addWidget(self.link_slot_combo)
        slot_row.addStretch()
        layout.addLayout(slot_row)

        hint = QtWidgets.QLabel(
            "Sets the GraFx link plus the matching style_* parameter for each animation you "
            "create below (e.g. style_pon = GrafX sequence for Power On). Only the main blade "
            "is shown live in this wizard's preview and in the app's blade preview panel. "
            "Changes still need Save to be written to disk."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666666; font-style: italic; font-size: 11px;")
        layout.addWidget(hint)

        return box

    def link_apply_specs(self) -> dict:
        """Parameter name -> value to push into the settings grid for the currently selected
        font, so it actually plays back the resource just created - empty if the user didn't
        opt into linking (or there was no font selected to link to)."""
        if not (hasattr(self, 'link_check') and self.link_check.isChecked()
                and self.link_check.isEnabled() and self.created_index is not None):
            return {}
        slot = self.link_slot_combo.currentData()
        specs = {f'style_grafx{slot}': str(self.created_index)}
        for state in self._selected_states():
            param = FONT_PARAM_FOR_STATE.get(state)
            if param:
                _, _, style_id = STATE_INFO[state]
                specs[param] = style_id
        return specs

    # ------------------------------------------------------------------ per-state pages

    def _build_state_page(self, state):
        label, _, _ = STATE_INFO[state]
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)

        title = QtWidgets.QLabel(label)
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        preset_combo = QtWidgets.QComboBox()
        preset_combo.addItems(PRESETS)
        layout.addWidget(preset_combo)

        preset_stack = QtWidgets.QStackedWidget()
        widgets = {'preset_combo': preset_combo, 'preset_stack': preset_stack}

        # Solid Fade: start -> end color
        fade_panel = QtWidgets.QWidget()
        fade_layout = QtWidgets.QHBoxLayout(fade_panel)
        start_container, widgets['start_color'] = create_rgb_picker_widget("Start", (0, 0, 0))
        end_container, widgets['end_color'] = create_rgb_picker_widget("End", (0, 200, 255))
        fade_layout.addWidget(start_container)
        fade_layout.addWidget(end_container)
        preset_stack.addWidget(fade_panel)

        # Wipe: fill -> background color
        wipe_panel = QtWidgets.QWidget()
        wipe_layout = QtWidgets.QHBoxLayout(wipe_panel)
        fill_container, widgets['fill_color'] = create_rgb_picker_widget("Fill", (0, 200, 255))
        bg_container, widgets['bg_color'] = create_rgb_picker_widget("Background", (0, 0, 0))
        wipe_layout.addWidget(fill_container)
        wipe_layout.addWidget(bg_container)
        preset_stack.addWidget(wipe_panel)

        # Flicker: base color + jitter amount
        flicker_panel = QtWidgets.QWidget()
        flicker_layout = QtWidgets.QVBoxLayout(flicker_panel)
        flicker_color_container, widgets['flicker_color'] = create_rgb_picker_widget(
            "Base color", (0, 200, 255))
        flicker_layout.addWidget(flicker_color_container)
        jitter_row = QtWidgets.QHBoxLayout()
        jitter_row.addWidget(QtWidgets.QLabel("Jitter amount:"))
        widgets['jitter_spin'] = QtWidgets.QSpinBox()
        widgets['jitter_spin'].setRange(0, 255)
        widgets['jitter_spin'].setValue(60)
        jitter_row.addWidget(widgets['jitter_spin'])
        flicker_layout.addLayout(jitter_row)
        preset_stack.addWidget(flicker_panel)

        # Fire: base color only
        fire_panel = QtWidgets.QWidget()
        fire_layout = QtWidgets.QVBoxLayout(fire_panel)
        fire_color_container, widgets['fire_color'] = create_rgb_picker_widget(
            "Base color", (255, 90, 0))
        fire_layout.addWidget(fire_color_container)
        preset_stack.addWidget(fire_panel)

        # Custom: hand-paint each stage directly, rather than generating from parameters.
        # Owns its own stage count (via Add/Delete Stage) - the "Number of stages" and
        # "Random variants" controls below are disabled while this preset is selected.
        widgets['stage_editor'] = GrafxStageEditor(self.pixel_count_spin.value(), initial_stage_count=10)
        preset_stack.addWidget(widgets['stage_editor'])

        preset_combo.currentIndexChanged.connect(preset_stack.setCurrentIndex)
        layout.addWidget(preset_stack)

        # Timing / variant controls common to every preset
        timing_form = QtWidgets.QFormLayout()
        widgets['stage_count_spin'] = QtWidgets.QSpinBox()
        widgets['stage_count_spin'].setRange(2, 400)
        widgets['stage_count_spin'].setValue(30)
        timing_form.addRow("Number of stages:", widgets['stage_count_spin'])

        widgets['sync_check'] = QtWidgets.QCheckBox("Sync timing to sound/quick-on duration")
        widgets['sync_check'].setChecked(state in ONE_SHOT_STATES)
        timing_form.addRow("", widgets['sync_check'])

        widgets['delay_spin'] = QtWidgets.QSpinBox()
        widgets['delay_spin'].setRange(1, 2000)
        widgets['delay_spin'].setValue(50)
        widgets['delay_spin'].setSuffix(" ms/stage")
        widgets['delay_spin'].setEnabled(not widgets['sync_check'].isChecked())
        widgets['sync_check'].toggled.connect(lambda checked: widgets['delay_spin'].setEnabled(not checked))
        timing_form.addRow("Stage delay:", widgets['delay_spin'])

        widgets['many_spin'] = QtWidgets.QSpinBox()
        widgets['many_spin'].setRange(1, 5)
        widgets['many_spin'].setValue(1)
        timing_form.addRow("Random variants:", widgets['many_spin'])

        widgets['stop_check'] = QtWidgets.QCheckBox("Freeze on last stage instead of looping")
        widgets['stop_check'].setChecked(state in ONE_SHOT_STATES)
        timing_form.addRow("", widgets['stop_check'])

        layout.addLayout(timing_form)

        # The Custom preset manages its own stage count and only ever produces one variant
        # (hand-painting several full alternate animations isn't worth the UI complexity),
        # so these two controls are irrelevant - and re-enabled again for any other preset.
        def on_preset_changed(index):
            is_custom = PRESETS[index] == 'Custom'
            widgets['stage_count_spin'].setEnabled(not is_custom)
            widgets['many_spin'].setEnabled(not is_custom)
            if is_custom:
                widgets['many_spin'].setValue(1)
        preset_combo.currentIndexChanged.connect(on_preset_changed)

        if state == 'forever':
            warning = QtWidgets.QLabel(
                "Forever completely overrides every other GraFx sequence in this resource - "
                "power on/off, lockup, and both idle loops all get replaced by this one "
                "continuous animation for as long as the saber is running."
            )
            warning.setWordWrap(True)
            warning.setStyleSheet("color: #B00020; font-style: italic; font-size: 11px;")
            layout.addWidget(warning)

        layout.addStretch()

        self.state_widgets[state] = widgets
        return page

    def _selected_states(self):
        return [s for s in STATE_ORDER if self.state_checks[s].isChecked()]

    def _rebuild_state_and_review_pages(self):
        """Drop and rebuild every page after Setup, based on the currently checked states -
        called each time Next is pressed from Setup, so going back and re-checking boxes
        never leaves a stale page around."""
        while self.stack.count() > 1:
            widget = self.stack.widget(1)
            self.stack.removeWidget(widget)
            widget.deleteLater()
        self.state_widgets = {}

        for state in self._selected_states():
            self.stack.addWidget(self._build_state_page(state))

        self.review_page = self._build_review_page()
        self.stack.addWidget(self.review_page)

    # ------------------------------------------------------------------ review page

    def _build_review_page(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.addWidget(QtWidgets.QLabel("Review"))
        self.review_summary = QtWidgets.QLabel()
        self.review_summary.setWordWrap(True)
        layout.addWidget(self.review_summary)
        layout.addStretch()
        return page

    def _refresh_review_summary(self):
        name = grafx_writer.sanitize_folder_name(self.name_edit.text())
        folder_name = f"{self.index_spin.value()}-{name}"
        states = self._selected_states()
        state_labels = ", ".join(STATE_INFO[s][0] for s in states)
        text = (
            f"This will create:\n\n"
            f"{self.grafx_root / folder_name}\n\n"
            f"Animations: {state_labels}\n"
            f"Blade pixel count: {self.pixel_count_spin.value()}\n\n"
        )
        if self.link_check.isChecked() and self.link_check.isEnabled():
            slot_label = self.link_slot_combo.currentText()
            font_params = ", ".join(
                FONT_PARAM_FOR_STATE[s] for s in states if s in FONT_PARAM_FOR_STATE)
            text += (
                f"Will also link to '{self._selected_font_name()}' ({slot_label})"
                + (f", setting: {font_params}" if font_params else "") + ".\n\n"
            )
        text += "Click Finish to write these files."
        self.review_summary.setText(text)

    # ------------------------------------------------------------------ navigation

    def _current_state(self):
        """The state key for whichever per-state page is currently shown, or None."""
        index = self.stack.currentIndex()
        states = self._selected_states()
        if 1 <= index <= len(states):
            return states[index - 1]
        return None

    def _update_nav_and_preview_visibility(self):
        index = self.stack.currentIndex()
        self.back_button.setEnabled(index > 0)
        is_review = hasattr(self, 'review_page') and self.stack.currentWidget() is self.review_page
        self.next_button.setText("Finish" if is_review else "Next >")

        state = self._current_state()
        self.preview_label.setVisible(state is not None)
        self.preview.setVisible(state is not None)
        self.preview_button.setVisible(state is not None)
        if state is not None:
            self.preview_label.setText(f"Preview: {STATE_INFO[state][0]}")

    def _go_back(self):
        if self.stack.currentIndex() > 0:
            self.stack.setCurrentIndex(self.stack.currentIndex() - 1)

    def _go_next(self):
        if self.stack.currentWidget() is self.setup_page:
            if not self._selected_states():
                QtWidgets.QMessageBox.warning(self, "Nothing to Create",
                                               "Check at least one animation to create.")
                return
            self._rebuild_state_and_review_pages()
            self.stack.setCurrentIndex(1)
            return

        if hasattr(self, 'review_page') and self.stack.currentWidget() is self.review_page:
            self._finish()
            return

        next_index = self.stack.currentIndex() + 1
        if next_index == self.stack.count() - 1:  # about to land on the review page
            self._refresh_review_summary()
        self.stack.setCurrentIndex(next_index)

    # ------------------------------------------------------------------ generation

    @staticmethod
    def _rgb_from(picker_widgets):
        r_spin, g_spin, b_spin, _swatch = picker_widgets
        return (r_spin.value(), g_spin.value(), b_spin.value())

    def _generate_image(self, state, seed):
        widgets = self.state_widgets[state]
        width = self.pixel_count_spin.value()
        stage_count = widgets['stage_count_spin'].value()
        preset = widgets['preset_combo'].currentText()

        if preset == 'Solid Fade':
            return grafx_writer.generate_solid_fade(
                width, stage_count, self._rgb_from(widgets['start_color']),
                self._rgb_from(widgets['end_color']))
        if preset == 'Wipe':
            return grafx_writer.generate_wipe(
                width, stage_count, self._rgb_from(widgets['fill_color']),
                self._rgb_from(widgets['bg_color']))
        if preset == 'Flicker':
            return grafx_writer.generate_flicker(
                width, stage_count, self._rgb_from(widgets['flicker_color']),
                widgets['jitter_spin'].value(), seed=seed)
        if preset == 'Fire':
            return grafx_writer.generate_fire(
                width, stage_count, self._rgb_from(widgets['fire_color']), seed=seed)
        if preset == 'Custom':
            return widgets['stage_editor'].to_image()
        raise ValueError(f"Unknown preset: {preset}")

    def _build_state_spec(self, state):
        widgets = self.state_widgets[state]
        many = widgets['many_spin'].value()
        variants = [self._generate_image(state, seed=random.randint(0, 1_000_000))
                    for _ in range(many)]
        delay_ms = None if widgets['sync_check'].isChecked() else widgets['delay_spin'].value()
        return {
            'image_variants': variants,
            'delay_ms': delay_ms,
            'many': many,
            'stop': widgets['stop_check'].isChecked(),
        }

    def _on_preview_clicked(self):
        state = self._current_state()
        if state is None:
            return
        spec = self._build_state_spec(state)
        grafx_writer.write_grafx_resource(self._staging_dir, {state: spec})

        _, style_kwarg, style_id = STATE_INFO[state]
        kwargs = {style_kwarg: style_id} if style_kwarg else {}
        self.preview.set_profile(
            (0, 200, 255), 1200, 1200, False, False,
            grafx_folder=self._staging_dir, **kwargs
        )
        self._play_preview_for_state(state)

    def _play_preview_for_state(self, state):
        p = self.preview
        p.reset()
        if state in ('poweron', 'preon'):
            p.ignite()
        elif state in ('poweroff', 'postoff'):
            p._fill = 1.0
            p._direction = 0
            p.retract()
        elif state == 'leds':
            p._fill = 1.0
            p._direction = 0
            p._sync_timer()
            p.update()
        elif state in ('idle', 'forever'):
            p._sync_timer()
            p.update()
        elif state == 'lockup':
            p._fill = 1.0
            p._direction = 0
            p.toggle_lockup()

    # ------------------------------------------------------------------ finish

    def _finish(self):
        name = grafx_writer.sanitize_folder_name(self.name_edit.text())
        index = self.index_spin.value()
        folder_name = f"{index}-{name}"
        dest = self.grafx_root / folder_name

        if dest.exists():
            QtWidgets.QMessageBox.warning(
                self, "Already Exists",
                f"'{folder_name}' already exists under {self.grafx_root}. "
                f"Choose a different resource number or name."
            )
            self.stack.setCurrentIndex(0)
            return

        state_specs = {state: self._build_state_spec(state) for state in self._selected_states()}
        grafx_writer.write_grafx_resource(dest, state_specs)

        self.created_index = index
        self.created_folder = dest
        self.accept()

    def done(self, result):
        shutil.rmtree(self._staging_dir, ignore_errors=True)
        super().done(result)
