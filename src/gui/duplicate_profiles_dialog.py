# src/gui/duplicate_profiles_dialog.py
"""Find blade profiles (config.txt) and color profiles (colors.txt) whose settings are
exactly the same - names aside - and merge them: the lowest-numbered copy is kept, every
font using another copy is pointed at it, and the profiles after it are renumbered.
Also refreshes the "//3-LIGHT, 7-ROGUE" font-name comments above each profile."""
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from core.profile_library import (
    KINDS, find_duplicates, font_comment_changes, font_folders, merge_duplicates,
    update_font_comments,
)


class DuplicateProfilesDialog(QtWidgets.QDialog):
    def __init__(self, cfx_root: Path, main_window=None):
        super().__init__(main_window)
        self.setWindowTitle("Check Duplicate Profiles")
        self.resize(720, 520)
        self.main_window = main_window
        self.root = Path(cfx_root)
        self.changed = False
        self._groups = {}          # tree item -> DuplicateGroup

        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(
            "Profiles listed together have exactly the same settings (only their names "
            "differ, if at all). Merging keeps the first one, points every font that used "
            "the others at it, and renumbers the profiles after it so there are no gaps - "
            "font_config.txt files and prefs.txt are updated to match.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #555555;")
        layout.addWidget(intro)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Profile", "Name", "Used by"])
        self.tree.setColumnWidth(0, 200)
        self.tree.setColumnWidth(1, 180)
        self.tree.itemChanged.connect(self._update_buttons)
        layout.addWidget(self.tree, stretch=1)

        self.comment_label = QtWidgets.QLabel()
        self.comment_label.setWordWrap(True)
        layout.addWidget(self.comment_label)

        buttons = QtWidgets.QHBoxLayout()
        self.comments_button = QtWidgets.QPushButton("Update Font-Name Comments")
        self.comments_button.setToolTip(
            "Rewrite the //font, font comment above each profile in config.txt and "
            "colors.txt to list the fonts that use it now")
        self.comments_button.clicked.connect(self._update_comments)
        buttons.addWidget(self.comments_button)
        buttons.addStretch()
        self.merge_button = QtWidgets.QPushButton("Merge Ticked Duplicates")
        self.merge_button.clicked.connect(self._merge)
        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(self.merge_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        self._load()

    def _load(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        self._groups = {}
        for kind in KINDS:
            groups = find_duplicates(self.root, kind)
            top = QtWidgets.QTreeWidgetItem(
                [f"{kind.filename} - " + (f"{len(groups)} group(s) of duplicates" if groups
                                          else "no duplicates")])
            top.setFirstColumnSpanned(True)
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            self.tree.addTopLevelItem(top)
            for group in groups:
                item = QtWidgets.QTreeWidgetItem(
                    [f"Merge into {kind.section} {group.keep}",
                     f"{len(group.numbers)} identical {kind.label}s"])
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(0, QtCore.Qt.Checked)
                top.addChild(item)
                self._groups[id(item)] = (item, group)
                for n in group.numbers:
                    role = "keep" if n == group.keep else "remove"
                    child = QtWidgets.QTreeWidgetItem(
                        [f"{kind.section} {n}  ({role})", group.names.get(n, ''),
                         ", ".join(group.usage.get(n, [])) or "no font"])
                    item.addChild(child)
                item.setExpanded(True)
            top.setExpanded(True)
        self.tree.blockSignals(False)
        stale = [k.filename for k in KINDS if font_comment_changes(self.root, k)]
        self.comment_label.setText(
            ("The font-name comments in " + " and ".join(stale) + " are out of date.")
            if stale else "The font-name comments above each profile are up to date.")
        self.comments_button.setEnabled(bool(stale))
        self._update_buttons()

    def _ticked(self):
        return [group for item, group in self._groups.values()
                if item.checkState(0) == QtCore.Qt.Checked]

    def _update_buttons(self, *_args):
        self.merge_button.setEnabled(bool(self._ticked()))

    def _backup_all(self):
        if self.main_window is None or not hasattr(self.main_window, '_backup_file'):
            return
        for name in ('config.txt', 'colors.txt', 'prefs.txt'):
            self.main_window._backup_file(self.root / name, "(root)")
        for number, name, path in font_folders(self.root):
            self.main_window._backup_file(path / 'font_config.txt', f"{number}-{name}")

    def _merge(self):
        groups = self._ticked()
        removed = sum(len(g.remove) for g in groups)
        response = QtWidgets.QMessageBox.question(
            self, "Merge Duplicates",
            f"Remove {removed} duplicate profile(s) and renumber the rest? Fonts that used "
            f"them will use the kept copy instead.\n\nThe main window reloads the card "
            f"afterwards, so save any changes you're making there first.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel)
        if response != QtWidgets.QMessageBox.Yes:
            return
        self._backup_all()
        try:
            merge_duplicates(self.root, groups)
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "Merge Failed", f"Couldn't update the files:\n{e}")
        self.changed = True
        self._load()

    def _update_comments(self):
        if self.main_window is not None and hasattr(self.main_window, '_backup_file'):
            for name in ('config.txt', 'colors.txt'):
                self.main_window._backup_file(self.root / name, "(root)")
        try:
            update_font_comments(self.root)
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "Update Failed", f"Couldn't update the files:\n{e}")
        self.changed = True
        self._load()
