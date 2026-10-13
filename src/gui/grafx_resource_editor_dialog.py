# src/gui/grafx_resource_editor_dialog.py
"""GraFx resource editor: browse the existing resource folders under /extra/GRAFX, preview
any one of their BMP files, open it in the pixel painter at its own size, and edit every
grafx1.txt parameter (GrafxParameterPanel) - the counterpart to the GraFx Creator wizard, which only builds
new resources from presets.

Saving never regenerates grafx1.txt: BMPs are written individually and config changes are
line-level edits (grafx_writer.update_config_section), so accents= strings, comments,
disabled ## params and untouched states all survive.

By default the original resource is left alone: the first change made to a resource in this
dialog copies the whole folder to the next free resource number and writes into the copy;
later changes in the same session go straight to that copy. "Edit originals in place"
switches to overwriting, backing each file up first when the main window has a backup
location configured.
"""
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from core import grafx_reader, grafx_timing, grafx_writer
from core.file_handler import CFXFileHandler
from gui.grafx_creator_dialog import STATE_INFO
from gui.widgets.grafx_parameter_panel import GrafxParameterPanel
from gui.widgets.sound_match_panel import SYNCABLE_STATES, SoundMatchPanel
from gui.widgets.grafx_stage_editor import (
    DEFAULT_PREVIEW_DELAY_MS, MAX_RESOURCE_STAGES, GrafxPixelEditorWindow, PainterDocument,
    GrafxStripPreview, bmp_to_display,
)

MISMATCH_COLOR = QtGui.QColor(255, 236, 200)


class GrafxResourceEditorDialog(QtWidgets.QDialog):
    def __init__(self, cfx_root: Path, main_window=None):
        super().__init__(main_window)
        self.cfx_root = Path(cfx_root)
        self.grafx_root = self.cfx_root / 'extra' / 'grafx'
        self.main_window = main_window
        self.setWindowTitle("Edit GraFx Resources")
        self.resize(1180, 940)

        self.blade_pixel_count = self._blade_pixel_count()
        self.changed_folders = set()   # every folder written to, for the caller to refresh
        self.session_copies = set()    # copies made here - safe to write without copying again
        self._entries = []
        self._preview_image = None

        # ---- left: resource folders
        self.folder_list = QtWidgets.QListWidget()
        self.folder_list.setMinimumWidth(240)
        self.folder_list.currentItemChanged.connect(self._on_folder_item_changed)

        folder_buttons = QtWidgets.QHBoxLayout()
        duplicate_button = QtWidgets.QPushButton("Duplicate…")
        duplicate_button.setToolTip("Copy the selected resource to a new resource number")
        duplicate_button.clicked.connect(self._duplicate_resource)
        reveal_button = QtWidgets.QPushButton("Show in Finder")
        reveal_button.clicked.connect(self._reveal_folder)
        folder_buttons.addWidget(duplicate_button)
        folder_buttons.addWidget(reveal_button)

        left = QtWidgets.QVBoxLayout()
        left.addWidget(self._bold_label("Resources"))
        left.addWidget(self.folder_list, stretch=1)
        left.addLayout(folder_buttons)

        # ---- middle: files in the selected resource
        self.file_table = QtWidgets.QTableWidget(0, 5)
        self.file_table.setHorizontalHeaderLabels(["File", "State", "Size (px × stages)",
                                                   "Delay", "Stop"])
        self.file_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.file_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.file_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.file_table.verticalHeader().setVisible(False)
        self.file_table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.Stretch)
        self.file_table.itemSelectionChanged.connect(self._on_file_changed)
        self.file_table.itemDoubleClicked.connect(lambda _item: self._edit_pixels())

        self.warning_label = QtWidgets.QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet(
            "color: #8a4b00; background-color: #fff3cd; border: 1px solid #e0c060; padding: 4px;")
        self.warning_label.hide()

        self.edit_button = QtWidgets.QPushButton("Edit Pixels…")
        self.edit_button.clicked.connect(self._edit_pixels)

        self.param_panel = GrafxParameterPanel()
        self.param_panel.dirty_changed.connect(self._on_params_dirty_changed)
        self.save_params_button = QtWidgets.QPushButton("Save Parameters")
        self.save_params_button.clicked.connect(self._save_parameters)
        self.revert_params_button = QtWidgets.QPushButton("Revert")
        self.revert_params_button.clicked.connect(self._load_parameters)
        params_buttons = QtWidgets.QHBoxLayout()
        params_buttons.addStretch()
        params_buttons.addWidget(self.revert_params_button)
        params_buttons.addWidget(self.save_params_button)

        files_widget = QtWidgets.QWidget()
        files_layout = QtWidgets.QVBoxLayout(files_widget)
        files_layout.setContentsMargins(0, 0, 0, 0)
        files_layout.addWidget(self._bold_label("Files"))
        files_layout.addWidget(self.file_table, stretch=1)
        files_layout.addWidget(self.warning_label)
        files_layout.addWidget(self.edit_button)
        # "Match to sound" for the selected file's state - rebuilt when the state changes.
        self._sound_panel = None
        self._sound_panel_key = None      # (folder, state) the panel was built for
        self._sound_font = None           # last font picked, kept across states/files
        self._linked_fonts = {}           # resource number -> fonts whose profile links it
        self._sound_panel_holder = QtWidgets.QVBoxLayout()
        files_layout.addLayout(self._sound_panel_holder)

        params_widget = QtWidgets.QWidget()
        params_layout = QtWidgets.QVBoxLayout(params_widget)
        params_layout.setContentsMargins(0, 0, 0, 0)
        params_layout.addWidget(self._bold_label("Parameters (grafx1.txt)"))
        params_layout.addWidget(self.param_panel, stretch=1)
        params_layout.addLayout(params_buttons)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        splitter.addWidget(files_widget)
        splitter.addWidget(params_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([420, 480])
        splitter.setChildrenCollapsible(False)

        middle = QtWidgets.QVBoxLayout()
        middle.addWidget(splitter)

        # ---- right: preview
        self.preview = GrafxStripPreview(lambda: self._preview_image)
        self.preview.setFixedWidth(44)
        self.preview_stage_label = QtWidgets.QLabel("")
        self.preview_stage_label.setStyleSheet("font-size: 10px; color: #666666;")
        self.preview.stage_changed.connect(
            lambda stage, count: self.preview_stage_label.setText(f"{stage + 1}/{count}"))
        self.preview_button = QtWidgets.QPushButton("Pause")
        self.preview_button.clicked.connect(self._toggle_preview)

        right = QtWidgets.QVBoxLayout()
        right.addWidget(self._bold_label("Preview"), alignment=QtCore.Qt.AlignHCenter)
        right.addWidget(self.preview, stretch=1, alignment=QtCore.Qt.AlignHCenter)
        right.addWidget(self.preview_stage_label, alignment=QtCore.Qt.AlignHCenter)
        right.addWidget(self.preview_button)

        content = QtWidgets.QHBoxLayout()
        content.addLayout(left)
        content.addLayout(middle, stretch=1)
        content.addLayout(right)

        # ---- bottom: save mode + close
        self.in_place_check = QtWidgets.QCheckBox(
            "Edit originals in place (backs files up first if a backup location is set)")
        self.in_place_check.toggled.connect(self._on_in_place_toggled)
        mode_hint = QtWidgets.QLabel(
            "By default the original is never changed: the first edit to a resource copies it "
            "to a new resource number and saves there. Later edits in this window go to that "
            "copy.")
        mode_hint.setWordWrap(True)
        mode_hint.setStyleSheet("color: #666666; font-style: italic; font-size: 11px;")
        pixel_hint = QtWidgets.QLabel(
            f"Blade pixel count (ledstrip in config.txt): {self.blade_pixel_count or 'not set'}")
        pixel_hint.setStyleSheet("color: #666666; font-size: 11px;")

        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.accept)
        bottom = QtWidgets.QHBoxLayout()
        bottom_text = QtWidgets.QVBoxLayout()
        bottom_text.addWidget(self.in_place_check)
        bottom_text.addWidget(mode_hint)
        bottom_text.addWidget(pixel_hint)
        bottom.addLayout(bottom_text, stretch=1)
        bottom.addWidget(close_button, alignment=QtCore.Qt.AlignBottom)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(content, stretch=1)
        layout.addLayout(bottom)

        self._on_params_dirty_changed(False)
        self._reload_folders()

    @staticmethod
    def _bold_label(text):
        label = QtWidgets.QLabel(text)
        label.setStyleSheet("font-weight: bold;")
        return label

    def _blade_pixel_count(self):
        try:
            value = int(CFXFileHandler(self.cfx_root).load_master_config().get('ledstrip', 0))
            return value if value > 0 else None
        except (ValueError, TypeError, OSError):
            return None

    # ------------------------------------------------------------------ folders

    def _scan_folders(self):
        folders = []
        if self.grafx_root.is_dir():
            for item in self.grafx_root.iterdir():
                if item.is_dir() and item.name[:1].isdigit():
                    try:
                        folders.append((int(item.name.split('-')[0]), item))
                    except ValueError:
                        continue
        return sorted(folders, key=lambda pair: (pair[0], pair[1].name))

    def _reload_folders(self, select: Path = None):
        current = select or self._current_folder()
        self.folder_list.blockSignals(True)
        self.folder_list.clear()
        for _index, folder in self._scan_folders():
            label = folder.name + ("   (copy)" if folder in self.session_copies else "")
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, str(folder))
            self.folder_list.addItem(item)
            if current is not None and folder == current:
                self.folder_list.setCurrentItem(item)
        self.folder_list.blockSignals(False)
        if self.folder_list.currentItem() is None and self.folder_list.count():
            self.folder_list.setCurrentRow(0)
        else:
            self._on_folder_changed()

    def _on_folder_item_changed(self, current, previous):
        if previous is not None and self.param_panel.is_dirty():
            self._confirm_discard_params(allow_cancel=False)
        self._on_folder_changed()

    def _current_folder(self):
        item = self.folder_list.currentItem()
        return Path(item.data(QtCore.Qt.UserRole)) if item else None

    def _on_folder_changed(self, *_args):
        self._reload_files()
        self._load_parameters()

    def _confirm_discard_params(self, allow_cancel: bool) -> bool:
        """Ask what to do with unsaved parameter edits. True = go ahead (saved or
        discarded), False = cancelled."""
        if not self.param_panel.is_dirty():
            return True
        buttons = QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard
        if allow_cancel:
            buttons |= QtWidgets.QMessageBox.Cancel
        response = QtWidgets.QMessageBox.question(
            self, "Unsaved Parameters",
            f"Save the parameter changes made to {self.param_panel.folder.name}?", buttons)
        if response == QtWidgets.QMessageBox.Save:
            return self._save_parameters(folder=self.param_panel.folder)
        return response == QtWidgets.QMessageBox.Discard

    def _reveal_folder(self):
        folder = self._current_folder()
        if folder is not None:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(folder)))

    def _duplicate_resource(self):
        # Both can switch to a new copy and reload the panel - settle parameter edits first.
        if not self._confirm_discard_params(allow_cancel=True):
            return
        folder = self._current_folder()
        if folder is None:
            return
        copy = self._make_copy(folder, "Duplicate GraFx Resource")
        if copy is not None:
            self._reload_folders(select=copy)

    def _make_copy(self, folder: Path, title: str):
        name = '-'.join(folder.name.split('-')[1:]) or folder.name
        index = grafx_writer.next_available_grafx_index(self.grafx_root)
        new_name, ok = QtWidgets.QInputDialog.getText(
            self, title,
            f"The copy will be resource #{index}. Name for the copy:",
            text=f"{name}-EDIT")
        if not ok:
            return None
        try:
            copy = grafx_writer.duplicate_grafx_resource(folder, self.grafx_root, new_name)
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "Copy Failed", f"Couldn't copy the resource:\n{e}")
            return None
        self.session_copies.add(copy)
        self.changed_folders.add(copy)
        return copy

    def _writable_folder(self, folder: Path):
        """The folder a change to `folder` should actually be written into: the folder
        itself when editing in place or when it's a copy made in this session, otherwise a
        fresh copy (after asking for its name). None if the user cancelled."""
        if self.in_place_check.isChecked() or folder in self.session_copies:
            return folder
        return self._make_copy(folder, "Save to a Copy")

    def _backup(self, path: Path):
        """Back up a file about to be overwritten in an original resource (in-place mode
        only - copies made here have nothing worth preserving)."""
        if (self.main_window is not None and path.parent not in self.session_copies
                and hasattr(self.main_window, '_backup_file')):
            self.main_window._backup_file(path, f"GRAFX/{path.parent.name}")

    def _on_in_place_toggled(self, checked: bool):
        if not checked or self.main_window is None:
            return
        if getattr(self.main_window, 'backup_path', None) is None:
            response = QtWidgets.QMessageBox.question(
                self, "No Backup Location",
                "No backup location is set, so originals will be overwritten without a "
                "backup. Choose a backup location now?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No | QtWidgets.QMessageBox.Cancel)
            if response == QtWidgets.QMessageBox.Yes:
                self.main_window._pick_backup_location()
            elif response == QtWidgets.QMessageBox.Cancel:
                self.in_place_check.setChecked(False)

    # ------------------------------------------------------------------ files

    def _reload_files(self, select_name: str = None):
        folder = self._current_folder()
        previous = select_name or (self._current_entry().path.name if self._current_entry() else None)
        self._entries = grafx_reader.list_grafx_files(folder) if folder else []
        self.file_table.blockSignals(True)
        self.file_table.setRowCount(len(self._entries))
        select_row = 0
        for row, entry in enumerate(self._entries):
            reader = QtGui.QImageReader(str(entry.path))
            size = reader.size()
            settings = grafx_reader.section_settings(folder, entry.state)
            delay = (settings or {}).get('delay')
            if settings is None:
                delay_text, stop_text = "section missing", ""
            else:
                delay_text = f"{delay} ms" if delay and delay != '0' else "sync"
                stop_text = "yes" if settings.get('stop') == '1' else ""
            mismatch = self._mismatch_text(size.width(), settings)
            label = STATE_INFO.get(entry.state, (entry.state,))[0]
            values = [entry.path.name, label,
                      f"{size.width()} × {size.height()}" if size.isValid() else "unreadable",
                      delay_text, stop_text]
            for col, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(("⚠ " if col == 2 and mismatch else "") + value)
                if mismatch:
                    item.setBackground(MISMATCH_COLOR)
                    item.setToolTip(mismatch)
                self.file_table.setItem(row, col, item)
            if entry.path.name == previous:
                select_row = row
        self.file_table.resizeColumnsToContents()
        self.file_table.blockSignals(False)
        if self._entries:
            self.file_table.selectRow(select_row)
        self._on_file_changed()

    def _mismatch_text(self, width: int, settings):
        """Why this file's width (one column per blade pixel) looks wrong, or ''."""
        problems = []
        if self.blade_pixel_count and width != self.blade_pixel_count:
            problems.append(f"it is {width} pixels wide but the blade has "
                            f"{self.blade_pixel_count} pixels (ledstrip in config.txt)")
        accents = (settings or {}).get('accents_count')
        if accents and width != accents:
            problems.append(f"its section's accents= string declares {accents} pixels")
        if not problems:
            return ''
        return "Width mismatch: " + "; ".join(problems) + ". Pixels past the end of the " \
               "shorter one won't play as intended."

    def _current_entry(self):
        rows = self.file_table.selectionModel().selectedRows() if self.file_table.selectionModel() else []
        if not rows or rows[0].row() >= len(self._entries):
            return None
        return self._entries[rows[0].row()]

    def _on_file_changed(self):
        entry = self._current_entry()
        has_entry = entry is not None
        self.edit_button.setEnabled(has_entry)
        self._update_sound_panel(entry)
        if not has_entry:
            self._preview_image = None
            self.preview.stop()
            self.preview.update()
            self.warning_label.hide()
            return

        folder = entry.path.parent
        settings = grafx_reader.section_settings(folder, entry.state)
        image = QtGui.QImage(str(entry.path))
        self._preview_image = None if image.isNull() else bmp_to_display(image)

        mismatch = self._mismatch_text(image.width(), settings)
        notes = [mismatch] if mismatch else []
        if settings is None:
            notes.append(f"grafx1.txt has no active [{grafx_reader.GRAFX_STATES[entry.state][0]}] "
                         "section, so this file won't play. Switch the section on in its "
                         "Parameters tab below.")
        self.warning_label.setText("⚠ " + "\n⚠ ".join(notes))
        self.warning_label.setVisible(bool(notes))

        try:
            delay_ms = int((settings or {}).get('delay') or 0)
        except ValueError:
            delay_ms = 0
        self.param_panel.select_state(entry.state)
        self.preview.set_delay_ms(delay_ms if delay_ms > 0 else DEFAULT_PREVIEW_DELAY_MS)
        self.preview.set_image_source(lambda: self._preview_image)
        if self.preview_button.text() == "Pause":
            self.preview.play()

    # ------------------------------------------------------------------ match to sound

    def _update_sound_panel(self, entry):
        state = entry.state if entry is not None else None
        folder = entry.path.parent if entry is not None else None
        usable = (state in SYNCABLE_STATES and self.main_window is not None
                  and getattr(self.main_window, 'file_handler', None) is not None)
        key = (folder, state) if usable else None
        if key != self._sound_panel_key:
            if self._sound_panel is not None:
                self._sound_font = self._sound_panel.font_path()
                self._sound_panel.setParent(None)
                self._sound_panel.deleteLater()
                self._sound_panel = None
            self._sound_panel_key = key
            if usable:
                preferred = [self._sound_font] if self._sound_font else []
                try:
                    index = int(folder.name.split('-')[0])
                    if index not in self._linked_fonts:     # scans every font - do it once
                        self._linked_fonts[index] = self.main_window.fonts_linked_to_grafx(index)
                    preferred += self._linked_fonts[index]
                except (ValueError, AttributeError):
                    pass
                self._sound_panel = SoundMatchPanel(state, self.main_window, preferred)
                self._sound_panel.apply_requested.connect(self._apply_sound_match)
                # Never squashed by the splitter - the file table gives way instead.
                self._sound_panel.setMinimumHeight(self._sound_panel.sizeHint().height())
                self._sound_panel_holder.addWidget(self._sound_panel)
        if self._sound_panel is not None and entry is not None:
            settings = grafx_reader.section_settings(folder, state) or {}
            try:
                delay = int(settings.get('delay') or 0)
            except ValueError:
                delay = 0
            stages = QtGui.QImageReader(str(entry.path)).size().height()
            self._sound_panel.set_animation(stages, delay or None)

    def _apply_sound_match(self, stage_count: int, delay_ms):
        """Resize every BMP of the selected state to stage_count stages (stretched over
        time) and set/clear that section's delay= - into a copy unless editing in place."""
        entry = self._current_entry()
        if entry is None:
            return
        if not self._confirm_discard_params(allow_cancel=True):
            return
        folder = entry.path.parent
        files = [e.path.name for e in self._entries if e.state == entry.state]
        section = grafx_reader.GRAFX_STATES[entry.state][0]
        delay_text = f"delay={delay_ms}" if delay_ms else "no delay (synced)"
        response = QtWidgets.QMessageBox.question(
            self, "Match to Sound",
            f"Resize {', '.join(files)} to {stage_count} stages (stretched or squashed over "
            f"time) and set [{section}] to {delay_text}?")
        if response != QtWidgets.QMessageBox.Yes:
            return
        target = self._writable_folder(folder)
        if target is None:
            return
        for name in files:
            path = target / name
            image = QtGui.QImage(str(path))
            if image.isNull():
                continue
            self._backup(path)
            if not grafx_writer.save_bmp(grafx_timing.resample_stages(image, stage_count), path):
                self._save_failed(path)
                return
        config = target / 'grafx1.txt'
        self._backup(config)
        grafx_writer.update_config_section(config, section,
                                           {'delay': str(delay_ms) if delay_ms else None})
        self.changed_folders.add(target)
        self._reload_folders(select=target)
        self._reload_files(select_name=entry.path.name)

    def _toggle_preview(self):
        if self.preview.is_playing():
            self.preview.stop()
            self.preview_button.setText("Play")
        else:
            self.preview.play()
            self.preview_button.setText("Pause")

    # ------------------------------------------------------------------ editing

    def _edit_pixels(self):
        """Open the painter on every BMP in the resource (starting at the selected one), so
        they can be switched between and previewed as a sequence. Save writes every file
        that was changed; Save as New Variant writes the one on screen as the next
        <prefix><N>.bmp and any other changed files in place."""
        # Both can switch to a new copy and reload the panel - settle parameter edits first.
        if not self._confirm_discard_params(allow_cancel=True):
            return
        entry = self._current_entry()
        if entry is None:
            return
        folder = entry.path.parent

        documents = []
        for e in self._entries:
            image = QtGui.QImage(str(e.path))
            if image.isNull():
                continue
            settings = grafx_reader.section_settings(folder, e.state)
            try:
                delay_ms = int((settings or {}).get('delay') or 0)
            except ValueError:
                delay_ms = 0
            documents.append(PainterDocument(
                e.path.name, f"{STATE_INFO.get(e.state, (e.state,))[0]} - {e.path.name}",
                image, state=e.state, delay_ms=delay_ms if delay_ms > 0 else None,
                warning=self._mismatch_text(image.width(), settings) or None))
        if not any(doc.key == entry.path.name for doc in documents):
            QtWidgets.QMessageBox.warning(self, "Can't Open", f"Couldn't read {entry.path.name}.")
            return

        self.preview.stop()
        dialog = GrafxPixelEditorWindow(
            parent=self, documents=documents, current_key=entry.path.name,
            max_stages=MAX_RESOURCE_STAGES, title=f"Edit GraFx Resource - {folder.name}",
            accept_buttons=[("Save as New Variant", 'variant'), ("Save", 'save')],
            timing=self._sound_panel.timing() if self._sound_panel is not None
            else self._fallback_timing())
        accepted = dialog.exec() == QtWidgets.QDialog.Accepted
        if self.preview_button.text() == "Pause":
            self.preview.play()
        if not accepted:
            return

        current = dialog.current_document()
        as_variant = dialog.chosen_action == 'variant'
        in_place = [doc for doc in dialog.modified_documents()
                    if not (as_variant and doc is current)]
        if not in_place and not as_variant:
            return      # nothing changed
        target = self._writable_folder(folder)
        if target is None:
            QtWidgets.QMessageBox.information(self, "Not Saved", "Your edits weren't saved.")
            return

        select_name = current.key
        for doc in in_place:
            dest = target / doc.key
            self._backup(dest)
            if not grafx_writer.save_bmp(doc.to_bmp_image(), dest):
                self._save_failed(dest)
                return
        if as_variant:
            section_name, prefix = grafx_reader.GRAFX_STATES[current.state]
            existing = [e.variant for e in grafx_reader.list_grafx_files(target)
                        if e.state == current.state]
            variant = max(existing, default=0) + 1
            dest = target / f"{prefix}{variant}.bmp"
            config = target / 'grafx1.txt'
            self._backup(config)
            if not grafx_writer.save_bmp(current.to_bmp_image(), dest):
                self._save_failed(dest)
                return
            grafx_writer.update_config_section(config, section_name, {'many': str(variant)})
            select_name = dest.name

        self.changed_folders.add(target)
        self._reload_folders(select=target)
        self._reload_files(select_name=select_name)

    def _fallback_timing(self):
        """Font timing for the painter's preview when no Match-to-sound panel is showing:
        the main window's selected font, if any."""
        current = getattr(self.main_window, 'current_font_path', None)
        if current is not None and hasattr(self.main_window, 'font_timing'):
            return self.main_window.font_timing(current)
        return None

    def _save_failed(self, path: Path):
        QtWidgets.QMessageBox.critical(self, "Save Failed", f"Couldn't write {path}.")

    def _load_parameters(self):
        folder = self._current_folder()
        self.param_panel.load(folder, self.blade_pixel_count,
                              grafx_reader.list_grafx_files(folder) if folder else [])
        entry = self._current_entry()
        if entry is not None:
            self.param_panel.select_state(entry.state)

    def _on_params_dirty_changed(self, dirty: bool):
        self.save_params_button.setEnabled(dirty)
        self.revert_params_button.setEnabled(dirty)

    def _save_parameters(self, *_args, folder: Path = None) -> bool:
        """Write the panel's pending changes to grafx1.txt line by line (copying the
        resource first unless editing in place). Returns False if cancelled/failed."""
        folder = folder or self.param_panel.folder
        operations = self.param_panel.pending_operations()
        if folder is None or not operations:
            return True
        target = self._writable_folder(folder)
        if target is None:
            return False
        config = target / 'grafx1.txt'
        self._backup(config)
        try:
            for op in operations:
                section, updates = op['section'], op['updates']
                if op['create']:
                    grafx_writer.update_config_section(config, section, updates)
                elif op['enable'] is True:
                    grafx_writer.set_section_enabled(config, section, True)
                    if updates:
                        grafx_writer.update_config_section(config, section, updates)
                elif op['enable'] is False:
                    # Apply edits while the section is still active, then comment it all out
                    # so they're kept for when it's switched back on.
                    if updates:
                        grafx_writer.update_config_section(config, section, updates)
                    grafx_writer.set_section_enabled(config, section, False)
                else:
                    grafx_writer.update_config_section(config, section, updates)
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "Save Failed", f"Couldn't update grafx1.txt:\n{e}")
            return False
        self.changed_folders.add(target)
        current_tab = self.param_panel.tab_widget.currentIndex()
        self.param_panel.load(target, self.blade_pixel_count, [])   # clears dirty before reselecting
        self._reload_folders(select=target)
        self.param_panel.tab_widget.setCurrentIndex(current_tab)
        return True

    def reject(self):
        if self._confirm_discard_params(allow_cancel=True):
            super().reject()

    def accept(self):
        if self._confirm_discard_params(allow_cancel=True):
            super().accept()

    def done(self, result):
        self.preview.stop()
        super().done(result)
