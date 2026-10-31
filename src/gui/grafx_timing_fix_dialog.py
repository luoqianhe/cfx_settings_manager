# src/gui/grafx_timing_fix_dialog.py
"""Fix the GraFx warnings from the validation report: one row per animation (or per
grafx1.txt section, for delay and many= fixes), each with a choice of fix. See
core.grafx_timing_fix."""
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from core.grafx_timing_fix import SKIP, apply_fixes, plan_fixes


class GrafxTimingFixDialog(QtWidgets.QDialog):
    def __init__(self, warnings: list, cfx_root: Path, main_window=None):
        super().__init__(main_window)
        self.setWindowTitle("Fix GraFx Warnings")
        self.resize(980, 460)
        self.main_window = main_window
        self.root = Path(cfx_root)
        self.changes = []
        self._fixes = plan_fixes(warnings)
        self._combos = []

        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(
            "The board only loads the BMP files a section's many= declares, so a missing or "
            "wrong many= stops an animation from playing. For timing: the board can't move "
            "to the next stage of an animation faster than the blade "
            "profile's refreshfx. Squashing an animation keeps its look but drops stages "
            "evenly, so it fits the time it has. Lowering refreshfx keeps every stage, but "
            "changes the timing of everything else that profile shows (6 ms is the minimum; "
            "the manual suggests around 10). Files are changed in place, after a backup.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #555555;")
        layout.addWidget(intro)

        self.table = QtWidgets.QTableWidget(len(self._fixes), 4)
        self.table.setHorizontalHeaderLabels(["Animation", "Fonts", "Problem", "Fix"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        for row, fix in enumerate(self._fixes):
            files = ", ".join(path.name for path, _s, _t in fix.files)
            animation = QtWidgets.QTableWidgetItem(f"{fix.folder.name}\n{files}")
            fonts = QtWidgets.QTableWidgetItem("\n".join(fix.fonts))
            messages = sorted({w['message'] for w in fix.warnings})
            problem = QtWidgets.QTableWidgetItem(messages[0] + (
                f"\n(+{len(messages) - 1} similar for other fonts)" if len(messages) > 1 else ""))
            problem.setToolTip("\n\n".join(messages))
            for column, item in enumerate((animation, fonts, problem)):
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                self.table.setItem(row, column, item)
            combo = QtWidgets.QComboBox()
            for action, label in fix.options():
                combo.addItem(label, action)
            combo.currentIndexChanged.connect(self._update_buttons)
            self.table.setCellWidget(row, 3, combo)
            self._combos.append(combo)
        self.table.resizeRowsToContents()
        layout.addWidget(self.table, stretch=1)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        self.apply_button = QtWidgets.QPushButton("Apply Fixes")
        self.apply_button.clicked.connect(self._apply)
        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.reject)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        self._update_buttons()

    def _choices(self):
        return [(fix, combo.currentData()) for fix, combo in zip(self._fixes, self._combos)
                if combo.currentData() != SKIP]

    def _update_buttons(self, *_args):
        self.apply_button.setEnabled(bool(self._choices()))

    def _apply(self):
        choices = self._choices()
        if QtWidgets.QMessageBox.question(
                self, "Fix GraFx Warnings",
                f"Apply {len(choices)} fix(es)? The changed files are backed up first.",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel) != QtWidgets.QMessageBox.Yes:
            return
        backup = getattr(self.main_window, '_backup_file', None)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            self.changes = apply_fixes(self.root, choices, backup)
        except (OSError, ValueError) as e:
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.critical(self, "Fix Failed", f"Stopped part-way:\n{e}")
            self.accept()
            return
        QtWidgets.QApplication.restoreOverrideCursor()
        QtWidgets.QMessageBox.information(
            self, "GraFx Warnings Fixed", "Changed:\n\n" + "\n".join(self.changes or ["(nothing)"]))
        self.accept()
