# src/gui/sound_check_dialog.py
"""Check Sounds: scan every font folder (and /extra) for WAV files the board would skip
or might stall on, and fix the ticked ones - stripping editor metadata, mixing stereo down
to mono, converting odd formats - after backing each file up. Also offers to delete the
hidden files macOS writes onto FAT cards. See core.sound_check."""
import shutil
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from core.profile_library import font_folders
from core.sound_check import (
    ERROR, check_folder, describe_actions, fix_actions, fix_file, macos_junk,
)

_FILE_ROLE = QtCore.Qt.UserRole
SHORT = {'not_wav': "not a WAV", 'format': "wrong format", 'rate': "wrong sample rate",
         'truncated': "truncated", 'stereo': "stereo", 'mixed_rate': "different sample rate",
         'metadata': "editor metadata"}
# Common and usually harmless (most editors add it), so fixing these is opt-in.
OPT_IN = {'mixed_rate', 'metadata'}


class SoundCheckDialog(QtWidgets.QDialog):
    def __init__(self, cfx_root: Path, main_window=None):
        super().__init__(main_window)
        self.setWindowTitle("Check Sounds")
        self.resize(900, 640)
        self.main_window = main_window
        self.root = Path(cfx_root)
        self._reports = []           # FolderReport per scanned folder
        self._junk = []

        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(
            "Red: the board skips the file (wrong format). Orange: it plays, but may be slow "
            "to start - stereo, a sample rate that differs from the rest of the font, or "
            "editor metadata in front of the audio. A sound that beeps and pauses the blade "
            "only on its first play after boot is often the SD card being slow to find it: "
            "if fixing files doesn't help, back the card up, format it and copy everything "
            "back in one go.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #555555;")
        layout.addWidget(intro)

        options = QtWidgets.QHBoxLayout()
        self.problems_only = QtWidgets.QCheckBox("Show only files with problems")
        self.problems_only.setChecked(True)
        self.problems_only.toggled.connect(self._populate)
        self.summary_label = QtWidgets.QLabel()
        options.addWidget(self.problems_only)
        options.addStretch()
        options.addWidget(self.summary_label)
        layout.addLayout(options)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["File", "Format", "Problems", "Fix"])
        self.tree.setColumnWidth(0, 230)
        self.tree.setColumnWidth(1, 150)
        self.tree.setColumnWidth(2, 330)
        self.tree.itemChanged.connect(self._update_buttons)
        self.tree.currentItemChanged.connect(self._show_details)
        layout.addWidget(self.tree, stretch=1)

        self.details = QtWidgets.QLabel()
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.details.setMinimumHeight(48)
        self.details.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        layout.addWidget(self.details)

        junk_row = QtWidgets.QHBoxLayout()
        self.junk_label = QtWidgets.QLabel()
        self.junk_label.setWordWrap(True)
        self.junk_button = QtWidgets.QPushButton("Delete macOS Files…")
        self.junk_button.setToolTip(
            "Delete the ._ files and .Spotlight-V100 / .fseventsd / .Trashes folders macOS "
            "writes onto the card. They aren't sounds; the board just has to step over them.")
        self.junk_button.clicked.connect(self._delete_junk)
        junk_row.addWidget(self.junk_label, stretch=1)
        junk_row.addWidget(self.junk_button)
        layout.addLayout(junk_row)

        buttons = QtWidgets.QHBoxLayout()
        rescan = QtWidgets.QPushButton("Rescan")
        rescan.clicked.connect(self._scan)
        reveal = QtWidgets.QPushButton("Show in Finder")
        reveal.clicked.connect(self._reveal)
        tick_all = QtWidgets.QPushButton("Tick All Fixable")
        tick_all.clicked.connect(lambda: self._tick_all(True))
        untick_all = QtWidgets.QPushButton("Untick All")
        untick_all.clicked.connect(lambda: self._tick_all(False))
        self.fix_button = QtWidgets.QPushButton("Fix Ticked Files")
        self.fix_button.clicked.connect(self._fix)
        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.accept)
        for button in (rescan, reveal, tick_all, untick_all):
            buttons.addWidget(button)
        buttons.addStretch()
        buttons.addWidget(self.fix_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        QtCore.QTimer.singleShot(0, self._scan)

    # ------------------------------------------------------------------ scanning

    def _scan(self):
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            folders = [(path, False) for _n, _name, path in font_folders(self.root)]
            if (self.root / 'extra').is_dir():
                folders.append((self.root / 'extra', True))
            self._reports = [check_folder(path, recursive) for path, recursive in folders]
            self._junk = macos_junk(self.root)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._populate()

    @staticmethod
    def _format(info) -> str:
        if info is None:
            return ""
        channels = "mono" if info.channels == 1 else f"{info.channels} ch"
        return f"{info.bits}-bit {info.rate / 1000:g} kHz {channels}"

    def _populate(self, *_args):
        self.tree.blockSignals(True)
        self.tree.clear()
        problems_only = self.problems_only.isChecked()
        total_files = total_problems = 0
        for report in self._reports:
            total_files += report.wav_count
            problem_files = report.problem_files
            total_problems += len(problem_files)
            shown = problem_files if problems_only else report.files
            if problems_only and not shown:
                continue
            name = report.folder.relative_to(self.root).as_posix()
            errors = sum(1 for f in problem_files
                         if any(p.severity == ERROR for p in f.problems))
            summary = (f"{len(problem_files)} of {report.wav_count} files with problems"
                       + (f" ({errors} skipped by the board)" if errors else "")
                       if problem_files else f"{report.wav_count} files, no problems")
            top = QtWidgets.QTreeWidgetItem([name, f"mostly {report.main_rate / 1000:g} kHz"
                                             if report.main_rate else "", summary])
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            self.tree.addTopLevelItem(top)
            for file_report in shown:
                actions = fix_actions(file_report)
                relative = file_report.path.relative_to(report.folder).as_posix()
                item = QtWidgets.QTreeWidgetItem([
                    relative, self._format(file_report.info),
                    ", ".join(SHORT[p.code] for p in file_report.problems),
                    describe_actions(actions, report.main_rate) if actions else
                    ("can't fix automatically" if file_report.problems else "")])
                item.setData(0, _FILE_ROLE, (report, file_report))
                if file_report.problems:
                    severe = any(p.severity == ERROR for p in file_report.problems)
                    item.setForeground(2, QtGui.QBrush(QtGui.QColor(
                        "#B00020" if severe else "#B35C00")))
                if actions:
                    item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                    # Opt-in problems alone (a deliberate rate, metadata) start unticked.
                    opt_in = {p.code for p in file_report.problems} <= OPT_IN
                    item.setCheckState(0, QtCore.Qt.Unchecked if opt_in else QtCore.Qt.Checked)
                top.addChild(item)
            top.setExpanded(bool(problem_files) and len(problem_files) <= 40)
        self.tree.blockSignals(False)
        self.summary_label.setText(f"{total_problems} of {total_files} files with problems")
        junk_files = [p for p in self._junk if p.name.startswith('._')]
        junk_folders = [p for p in self._junk if not p.name.startswith('._')]
        if self._junk:
            parts = []
            if junk_files:
                parts.append(f"{len(junk_files)} \"._\" file(s)")
            if junk_folders:
                parts.append(", ".join(p.name for p in junk_folders))
            self.junk_label.setText("macOS has left hidden files on the card: "
                                    + " and ".join(parts) + ".")
        else:
            self.junk_label.setText("No hidden macOS files on the card.")
        self.junk_button.setEnabled(bool(self._junk))
        self._update_buttons()

    def _ticked(self):
        ticked = []
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                item = top.child(j)
                if item.flags() & QtCore.Qt.ItemIsUserCheckable \
                        and item.checkState(0) == QtCore.Qt.Checked:
                    ticked.append(item.data(0, _FILE_ROLE))
        return ticked

    def _tick_all(self, ticked: bool):
        state = QtCore.Qt.Checked if ticked else QtCore.Qt.Unchecked
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                if top.child(j).flags() & QtCore.Qt.ItemIsUserCheckable:
                    top.child(j).setCheckState(0, state)

    def _update_buttons(self, *_args):
        count = len(self._ticked())
        self.fix_button.setEnabled(bool(count))
        self.fix_button.setText(f"Fix {count} Ticked File(s)" if count else "Fix Ticked Files")

    def _show_details(self, item, _previous=None):
        data = item.data(0, _FILE_ROLE) if item is not None else None
        if not data:
            self.details.setText("")
            return
        _report, file_report = data
        lines = [f"<b>{file_report.path.name}</b>"]
        lines += [("⛔ " if p.severity == ERROR else "⚠ ") + p.message for p in file_report.problems]
        if file_report.info and file_report.info.rate:
            lines.append(f"<span style='color:#777777'>{file_report.info.ms / 1000:.2f} s, "
                         f"chunks: {', '.join(file_report.info.chunks)}</span>")
        self.details.setText("<br>".join(lines))

    # ------------------------------------------------------------------ actions

    def _reveal(self):
        item = self.tree.currentItem()
        data = item.data(0, _FILE_ROLE) if item is not None else None
        target = data[1].path.parent if data else self.root
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(target)))

    def _backup(self, path: Path):
        if self.main_window is not None and hasattr(self.main_window, '_backup_file'):
            folder = path.parent.relative_to(self.root).as_posix()
            self.main_window._backup_file(path, folder)

    def _fix(self):
        ticked = self._ticked()
        if not ticked:
            return
        no_backup = self.main_window is not None and getattr(self.main_window, 'backup_path', 1) is None
        message = (f"Fix {len(ticked)} file(s) in place?"
                   + ("\n\nNo backup location is set, so the originals won't be kept."
                      if no_backup else "\n\nEach file is backed up first."))
        if QtWidgets.QMessageBox.question(
                self, "Fix Sounds", message,
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel) != QtWidgets.QMessageBox.Yes:
            return
        progress = QtWidgets.QProgressDialog("Fixing sounds…", "Stop", 0, len(ticked), self)
        progress.setWindowModality(QtCore.Qt.WindowModal)
        progress.setMinimumDuration(300)
        failures = []
        for i, (report, file_report) in enumerate(ticked):
            progress.setValue(i)
            QtWidgets.QApplication.processEvents()
            if progress.wasCanceled():
                break
            try:
                self._backup(file_report.path)
                fix_file(file_report, report.main_rate)
            except (OSError, RuntimeError, ValueError) as e:
                failures.append(f"{file_report.path.relative_to(self.root)}: {e}")
        progress.setValue(len(ticked))
        if failures:
            QtWidgets.QMessageBox.warning(
                self, "Some Files Weren't Fixed", "\n".join(failures[:20])
                + (f"\n…and {len(failures) - 20} more" if len(failures) > 20 else ""))
        self._scan()

    def _delete_junk(self):
        if QtWidgets.QMessageBox.question(
                self, "Delete macOS Files",
                f"Delete {len(self._junk)} hidden macOS file(s)/folder(s) from the card? They "
                f"hold Finder metadata, not sounds or settings.",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel) != QtWidgets.QMessageBox.Yes:
            return
        failures = []
        for path in self._junk:
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.exists():
                    path.unlink()
            except OSError as e:
                failures.append(f"{path.name}: {e}")
        if failures:
            QtWidgets.QMessageBox.warning(self, "Some Files Weren't Deleted", "\n".join(failures[:20]))
        self._scan()
