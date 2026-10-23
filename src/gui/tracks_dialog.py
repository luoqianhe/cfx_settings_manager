# src/gui/tracks_dialog.py
"""Music Tracks (iSaber): manage the card's root /tracks folder - the songs the iSaber
player (vocal menu, after the fonts) plays and the blade "plays along" to - plus the three
settings that control it: blademusicstyle (special.txt), loop and shuffle (config.txt).

Songs can be added from any format the system converter reads (MP3, M4A, AIFF, WAV, ...);
they're converted to the board's format (16-bit WAV, 44,100 or 22,050 Hz, mono), optionally
normalized, and numbered track1.wav, track2.wav, ... with no gaps.
"""
import shutil
from pathlib import Path

from PySide6 import QtCore, QtGui, QtMultimedia, QtWidgets

from core import tracks as track_files
from core.flat_config import parse_flat, update_flat
from core.sound_player import route_to_default_output
from gui.special_settings_dialog import load_parameter_definitions

AUDIO_FILTER = "Audio files (*.mp3 *.m4a *.aac *.wav *.aif *.aiff *.flac *.caf);;All files (*)"


def _duration(ms: int) -> str:
    seconds = round(ms / 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"


class AddTrackDialog(QtWidgets.QDialog):
    """Options for converting a song into a track."""

    def __init__(self, source: Path, track_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Song")
        form = QtWidgets.QFormLayout(self)
        form.addRow("Song:", QtWidgets.QLabel(source.name))
        self.position_combo = QtWidgets.QComboBox()
        self.position_combo.addItem(f"At the end (track{track_count + 1}.wav)", 'end')
        self.position_combo.addItem("First (track1.wav - the others move down one)", 'first')
        form.addRow("Position:", self.position_combo)
        self.rate_combo = QtWidgets.QComboBox()
        self.rate_combo.addItem("44,100 Hz (best quality)", 44100)
        self.rate_combo.addItem("22,050 Hz (half the file size)", 22050)
        form.addRow("Sample rate:", self.rate_combo)
        self.mono_check = QtWidgets.QCheckBox("Mono (recommended - the saber has one speaker)")
        self.mono_check.setChecked(True)
        form.addRow("", self.mono_check)
        self.normalize_check = QtWidgets.QCheckBox(
            "Normalize to ~56% peak (the manual suggests 50-60%, to match the saber sounds)")
        self.normalize_check.setChecked(True)
        form.addRow("", self.normalize_check)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok
                                             | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Convert and Add")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class TracksDialog(QtWidgets.QDialog):
    def __init__(self, cfx_root: Path, main_window=None):
        super().__init__(main_window)
        self.setWindowTitle("Music Tracks (iSaber)")
        self.resize(860, 640)
        self.cfx_root = Path(cfx_root)
        self.folder = self.cfx_root / 'tracks'
        self.special_path = self.cfx_root / 'special.txt'
        self.main_window = main_window
        self._tracks = []

        self._player = QtMultimedia.QMediaPlayer(self)
        self._audio = QtMultimedia.QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._player.playbackStateChanged.connect(self._update_buttons)

        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(
            "These are the songs in the card's /tracks folder, played by the iSaber player "
            "(vocal menu, after the fonts). With a pixel blade, the blade plays along to "
            "them. On the saber: double-click the activator to play/pause; long press with "
            "the blade off for the next track. (A font's own tracks folder plays music too, "
            "but the blade doesn't react to it.)")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #555555;")
        layout.addWidget(intro)

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["File", "Length", "Format", "Status"])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.itemDoubleClicked.connect(lambda _item: self._toggle_play())
        layout.addWidget(self.table, stretch=1)

        self.numbering_label = QtWidgets.QLabel()
        self.numbering_label.setWordWrap(True)
        self.numbering_label.setStyleSheet("color: #8a4b00;")
        layout.addWidget(self.numbering_label)

        row = QtWidgets.QHBoxLayout()
        self.add_button = QtWidgets.QPushButton("Add Song…")
        self.add_button.clicked.connect(self._add_song)
        self.play_button = QtWidgets.QPushButton("Play")
        self.play_button.clicked.connect(self._toggle_play)
        self.up_button = QtWidgets.QPushButton("Move Up")
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button = QtWidgets.QPushButton("Move Down")
        self.down_button.clicked.connect(lambda: self._move(1))
        self.fix_button = QtWidgets.QPushButton("Fix Format")
        self.fix_button.setToolTip("Convert this track to 16-bit mono WAV at 44,100 Hz so the "
                                   "board will play it")
        self.fix_button.clicked.connect(self._fix_format)
        self.renumber_button = QtWidgets.QPushButton("Renumber")
        self.renumber_button.setToolTip("Rename the tracks to track1, track2, … with no gaps")
        self.renumber_button.clicked.connect(self._renumber)
        self.remove_button = QtWidgets.QPushButton("Remove…")
        self.remove_button.clicked.connect(self._remove)
        reveal_button = QtWidgets.QPushButton("Show in Finder")
        reveal_button.clicked.connect(
            lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.folder))))
        for button in (self.add_button, self.play_button, self.up_button, self.down_button,
                       self.fix_button, self.renumber_button, self.remove_button):
            row.addWidget(button)
        row.addStretch()
        row.addWidget(reveal_button)
        layout.addLayout(row)

        layout.addWidget(self._build_settings_box())

        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.accept)
        bottom = QtWidgets.QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(close_button)
        layout.addLayout(bottom)

        self._reload()

    # ------------------------------------------------------------------ settings box

    def _build_settings_box(self):
        box = QtWidgets.QGroupBox("iSaber settings")
        form = QtWidgets.QFormLayout(box)
        definitions = load_parameter_definitions()

        self.style_combo = QtWidgets.QComboBox()
        for value, label in (definitions.get('blademusicstyle', {}).get('values') or {}).items():
            self.style_combo.addItem(f"{value}: {label}", value)
        self.style_save = QtWidgets.QPushButton("Save to special.txt")
        self.style_save.clicked.connect(self._save_style)
        self.style_combo.currentIndexChanged.connect(self._update_style_button)
        style_row = QtWidgets.QHBoxLayout()
        style_row.addWidget(self.style_combo, stretch=1)
        style_row.addWidget(self.style_save)
        form.addRow("Blade style (blademusicstyle):", style_row)

        self.loop_check = QtWidgets.QCheckBox("Repeat the current track (loop=1)")
        self.shuffle_combo = QtWidgets.QComboBox()
        for value, label in (definitions.get('shuffle', {}).get('values') or {}).items():
            self.shuffle_combo.addItem(f"{value}: {label.split(' - ')[0]}", value)
        self.player_apply = QtWidgets.QPushButton("Set in Main Window")
        self.player_apply.setToolTip("loop and shuffle are in config.txt: this puts them in the "
                                     "main window's settings, to save with Save Changes there")
        self.player_apply.clicked.connect(self._apply_player_settings)
        player_row = QtWidgets.QHBoxLayout()
        player_row.addWidget(self.loop_check)
        player_row.addWidget(QtWidgets.QLabel("Order:"))
        player_row.addWidget(self.shuffle_combo, stretch=1)
        player_row.addWidget(self.player_apply)
        form.addRow("Player (config.txt):", player_row)

        self.ledstrip_label = QtWidgets.QLabel()
        self.ledstrip_label.setWordWrap(True)
        form.addRow("Blade:", self.ledstrip_label)

        self._load_settings()
        return box

    def _setting(self, name):
        if self.main_window is not None and hasattr(self.main_window, 'current_setting'):
            return self.main_window.current_setting(name)
        return None

    def _special_value(self, key):
        entry = next((e for e in parse_flat(self.special_path) if e['key'] == key), None)
        return entry['value'] if entry and entry['enabled'] else None

    def _load_settings(self):
        self._style_saved = self._special_value('blademusicstyle') or '0'
        index = self.style_combo.findData(self._style_saved)
        self.style_combo.setCurrentIndex(max(0, index))
        self._update_style_button()
        self.loop_check.setChecked(str(self._setting('loop') or '0').split()[0] == '1')
        index = self.shuffle_combo.findData(str(self._setting('shuffle') or '0').split()[0])
        self.shuffle_combo.setCurrentIndex(max(0, index))
        try:
            pixels = int(str(self._setting('ledstrip') or 0).split()[0])
        except ValueError:
            pixels = 0
        if pixels > 0:
            self.ledstrip_label.setText(f"✓ Pixel blade ({pixels} pixels) - the blade can "
                                        f"display the music.")
            self.ledstrip_label.setStyleSheet("color: #2e7d32;")
        else:
            self.ledstrip_label.setText("⚠ ledstrip is 0 (high-power LED mode) - the blade "
                                        "only displays the music in pixel-blade mode.")
            self.ledstrip_label.setStyleSheet("color: #8a4b00;")

    def _update_style_button(self, *_args):
        self.style_save.setEnabled(self.style_combo.currentData() != self._style_saved
                                   and self.special_path.is_file())

    def _save_style(self):
        if self.main_window is not None and hasattr(self.main_window, '_backup_file'):
            self.main_window._backup_file(self.special_path, "(root)")
        try:
            update_flat(self.special_path, {'blademusicstyle': self.style_combo.currentData()})
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "Save Failed", f"Couldn't write special.txt:\n{e}")
            return
        self._style_saved = self.style_combo.currentData()
        self._update_style_button()

    def _apply_player_settings(self):
        if self.main_window is None or not hasattr(self.main_window, 'apply_grid_params'):
            return
        ok, message = self.main_window.apply_grid_params(
            {'loop': '1' if self.loop_check.isChecked() else '0',
             'shuffle': self.shuffle_combo.currentData()})
        (QtWidgets.QMessageBox.information if ok else QtWidgets.QMessageBox.warning)(
            self, "Player Settings", message)

    # ------------------------------------------------------------------ track list

    def _reload(self, select: int = None):
        self._stop()
        self._tracks = track_files.list_tracks(self.folder)
        self.table.setRowCount(len(self._tracks))
        for row, track in enumerate(self._tracks):
            info = track['info']
            fmt = (f"{info['bits']}-bit, {info['rate']:,} Hz, "
                   f"{'mono' if info['channels'] == 1 else str(info['channels']) + ' ch'}"
                   if info else "not PCM WAV")
            status = "⚠ " + " ".join(track['problems']) if track['problems'] else "✓ Plays on the board"
            values = [track['path'].name, _duration(info['ms']) if info else "?", fmt, status]
            for col, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                if track['problems']:
                    item.setBackground(QtGui.QColor(255, 236, 200))
                    item.setToolTip(" ".join(track['problems']))
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        if not self._tracks:
            self.numbering_label.setText(
                "No tracks yet - use Add Song." if self.folder.is_dir() else
                "There's no /tracks folder on this card yet - Add Song creates it.")
            self.numbering_label.setStyleSheet("color: #555555;")
        else:
            problem = track_files.numbering_problem(self._tracks)
            self.numbering_label.setText(("⚠ " + problem) if problem else "")
            self.numbering_label.setStyleSheet("color: #8a4b00;")
        if self._tracks:
            self.table.selectRow(min(select if select is not None else 0, len(self._tracks) - 1))
        self._update_buttons()

    def _selected_row(self):
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def _update_buttons(self, *_args):
        row = self._selected_row()
        has = row is not None
        self.play_button.setEnabled(has)
        self.play_button.setText("Stop" if self._player.playbackState()
                                 == QtMultimedia.QMediaPlayer.PlayingState else "Play")
        self.up_button.setEnabled(has and row > 0)
        self.down_button.setEnabled(has and row < len(self._tracks) - 1)
        self.remove_button.setEnabled(has)
        self.fix_button.setEnabled(has and bool(self._tracks[row]['problems']))
        self.renumber_button.setEnabled(bool(track_files.numbering_problem(self._tracks)))
        self.add_button.setEnabled(track_files.converter() is not None)
        if track_files.converter() is None:
            self.add_button.setToolTip("Needs macOS (afconvert) or ffmpeg to convert songs")

    # ------------------------------------------------------------------ actions

    def _toggle_play(self):
        if self._player.playbackState() == QtMultimedia.QMediaPlayer.PlayingState:
            self._stop()
            return
        row = self._selected_row()
        if row is None:
            return
        route_to_default_output(self._audio)
        self._player.setSource(QtCore.QUrl.fromLocalFile(str(self._tracks[row]['path'])))
        self._player.play()

    def _stop(self):
        self._player.stop()
        self._player.setSource(QtCore.QUrl())    # release the file so it can be renamed

    def _backup(self, path: Path):
        if self.main_window is not None and hasattr(self.main_window, '_backup_file'):
            self.main_window._backup_file(path, "tracks")

    def _busy(self, work, message):
        """Run work() with a wait cursor; report an error instead of raising."""
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            return work()
        except (RuntimeError, OSError, EOFError) as e:
            QtWidgets.QMessageBox.critical(self, message, str(e))
            return None
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _add_song(self):
        path, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose a Song", str(Path.home() / "Music"), AUDIO_FILTER)
        if not path:
            return
        options = AddTrackDialog(Path(path), len(self._tracks), self)
        if options.exec() != QtWidgets.QDialog.Accepted:
            return
        prepared = self._busy(lambda: track_files.prepare_track(
            Path(path), options.rate_combo.currentData(), options.mono_check.isChecked(),
            track_files.NORMALIZE_PEAK if options.normalize_check.isChecked() else None),
            "Couldn't Convert the Song")
        if prepared is None:
            return
        self._stop()
        self.folder.mkdir(exist_ok=True)
        existing = [t['path'] for t in self._tracks]
        if options.position_combo.currentData() == 'first':
            incoming = self.folder / ".incoming.wav"
            shutil.move(str(prepared), incoming)
            track_files.apply_order(self.folder, [incoming] + existing)
            select = 0
        else:
            if track_files.numbering_problem(self._tracks):
                track_files.apply_order(self.folder, existing)
            shutil.move(str(prepared), self.folder / f"track{len(existing) + 1}.wav")
            select = len(existing)
        shutil.rmtree(prepared.parent, ignore_errors=True)
        self._reload(select)

    def _move(self, step: int):
        row = self._selected_row()
        if row is None or not 0 <= row + step < len(self._tracks):
            return
        self._stop()
        order = [t['path'] for t in self._tracks]
        order[row], order[row + step] = order[row + step], order[row]
        track_files.apply_order(self.folder, order)
        self._reload(row + step)

    def _renumber(self):
        self._stop()
        track_files.apply_order(self.folder, [t['path'] for t in self._tracks])
        self._reload()

    def _fix_format(self):
        row = self._selected_row()
        if row is None:
            return
        path = self._tracks[row]['path']
        prepared = self._busy(lambda: track_files.prepare_track(path, 44100, True, None),
                              "Couldn't Convert the Track")
        if prepared is None:
            return
        self._stop()
        self._backup(path)
        shutil.move(str(prepared), path)
        shutil.rmtree(prepared.parent, ignore_errors=True)
        self._reload(row)

    def _remove(self):
        row = self._selected_row()
        if row is None:
            return
        path = self._tracks[row]['path']
        backed_up = getattr(self.main_window, 'backup_path', None) is not None
        response = QtWidgets.QMessageBox.question(
            self, "Remove Track",
            f"Remove {path.name}? The tracks after it move up one."
            + ("" if backed_up else "\n\nNo backup location is set, so it can't be recovered."))
        if response != QtWidgets.QMessageBox.Yes:
            return
        self._stop()
        self._backup(path)
        path.unlink()
        remaining = [t['path'] for t in self._tracks if t['path'] != path]
        track_files.apply_order(self.folder, remaining)
        self._reload(row)

    def done(self, result):
        self._stop()
        super().done(result)
