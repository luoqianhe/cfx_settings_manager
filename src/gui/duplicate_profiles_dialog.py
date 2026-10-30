# src/gui/duplicate_profiles_dialog.py
"""Clean Up Profiles: tidy the shared blade profiles (config.txt) and color profiles
(colors.txt).

  * Duplicates - profiles whose settings are exactly the same (names aside) are merged:
    the lowest-numbered copy is kept and every font using another copy is pointed at it.
  * Unused - profiles no font boots with are removed.

Either way the remaining profiles are renumbered without gaps and every font's references
(font_config.txt, prefs.txt) follow. Also refreshes the "//3-LIGHT, 7-ROGUE" font-name
comments above each profile."""
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from core.profile_library import (
    KINDS, find_duplicates, find_unused, font_comment_changes, font_folders, merge_duplicates,
    remove_unused, update_font_comments,
)


def _bold(item: QtWidgets.QTreeWidgetItem):
    font = item.font(0)
    font.setBold(True)
    item.setFont(0, font)


class DuplicateProfilesDialog(QtWidgets.QDialog):
    def __init__(self, cfx_root: Path, main_window=None, tab: str = None):
        super().__init__(main_window)
        self.setWindowTitle("Clean Up Profiles")
        self.resize(760, 560)
        self.main_window = main_window
        self.root = Path(cfx_root)
        self.changed = False
        self._groups = []          # (tree item, DuplicateGroup)
        self._unused = []          # (tree item, UnusedProfile)

        layout = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs, stretch=1)

        # --- Duplicates tab
        dup_page = QtWidgets.QWidget()
        dup_layout = QtWidgets.QVBoxLayout(dup_page)
        intro = QtWidgets.QLabel(
            "Profiles listed together have exactly the same settings (only their names "
            "differ, if at all). Merging keeps the first one, points every font that used "
            "the others at it, and renumbers the profiles after it so there are no gaps - "
            "font_config.txt files and prefs.txt are updated to match.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #555555;")
        dup_layout.addWidget(intro)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Profile", "Name", "Used by"])
        self.tree.setColumnWidth(0, 200)
        self.tree.setColumnWidth(1, 180)
        self.tree.itemChanged.connect(self._update_buttons)
        dup_layout.addWidget(self.tree, stretch=1)
        dup_buttons = QtWidgets.QHBoxLayout()
        dup_buttons.addStretch()
        self.merge_button = QtWidgets.QPushButton("Merge Ticked Duplicates")
        self.merge_button.clicked.connect(self._merge)
        dup_buttons.addWidget(self.merge_button)
        dup_layout.addLayout(dup_buttons)
        self.tabs.addTab(dup_page, "Duplicates")

        # --- Unused tab
        unused_page = QtWidgets.QWidget()
        unused_layout = QtWidgets.QVBoxLayout(unused_page)
        intro = QtWidgets.QLabel(
            "No font starts with these profiles (by start_blade / start_color, or the "
            "last-used profile saved in prefs.txt). But a font can still switch to them "
            "with Spectrum if its used_profiles mask allows it - removing one removes that "
            "choice. Profile 0 is never listed: it's the board's fallback.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #555555;")
        unused_layout.addWidget(intro)
        self.unused_tree = QtWidgets.QTreeWidget()
        self.unused_tree.setHeaderLabels(["Profile", "Name", "Spectrum can switch to it in"])
        self.unused_tree.setColumnWidth(0, 200)
        self.unused_tree.setColumnWidth(1, 180)
        self.unused_tree.itemChanged.connect(self._update_buttons)
        unused_layout.addWidget(self.unused_tree, stretch=1)
        unused_buttons = QtWidgets.QHBoxLayout()
        tick_all = QtWidgets.QPushButton("Tick All")
        tick_all.clicked.connect(lambda: self._tick_unused(True))
        untick_all = QtWidgets.QPushButton("Untick All")
        untick_all.clicked.connect(lambda: self._tick_unused(False))
        unused_buttons.addWidget(tick_all)
        unused_buttons.addWidget(untick_all)
        unused_buttons.addStretch()
        self.remove_button = QtWidgets.QPushButton("Remove Ticked Profiles")
        self.remove_button.clicked.connect(self._remove_unused)
        unused_buttons.addWidget(self.remove_button)
        unused_layout.addLayout(unused_buttons)
        self.tabs.addTab(unused_page, "Unused")

        # --- shared footer
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
        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self._load()
        if tab == 'unused':
            self.tabs.setCurrentWidget(unused_page)

    # ------------------------------------------------------------------ loading

    def _load(self):
        self._load_duplicates()
        self._load_unused()
        stale = [k.filename for k in KINDS if font_comment_changes(self.root, k)]
        self.comment_label.setText(
            ("The font-name comments in " + " and ".join(stale) + " are out of date.")
            if stale else "The font-name comments above each profile are up to date.")
        self.comments_button.setEnabled(bool(stale))
        self._update_buttons()

    def _load_duplicates(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        self._groups = []
        total = 0
        for kind in KINDS:
            groups = find_duplicates(self.root, kind)
            total += len(groups)
            top = QtWidgets.QTreeWidgetItem(
                [f"{kind.filename} - " + (f"{len(groups)} group(s) of duplicates" if groups
                                          else "no duplicates")])
            top.setFirstColumnSpanned(True)
            _bold(top)
            self.tree.addTopLevelItem(top)
            for group in groups:
                item = QtWidgets.QTreeWidgetItem(
                    [f"Merge into {kind.section} {group.keep}",
                     f"{len(group.numbers)} identical {kind.label}s"])
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(0, QtCore.Qt.Checked)
                top.addChild(item)
                self._groups.append((item, group))
                for n in group.numbers:
                    role = "keep" if n == group.keep else "remove"
                    item.addChild(QtWidgets.QTreeWidgetItem(
                        [f"{kind.section} {n}  ({role})", group.names.get(n, ''),
                         ", ".join(group.usage.get(n, [])) or "no font"]))
                item.setExpanded(True)
            top.setExpanded(True)
        self.tree.blockSignals(False)
        self.tabs.setTabText(0, f"Duplicates ({total})")

    def _load_unused(self):
        self.unused_tree.blockSignals(True)
        self.unused_tree.clear()
        self._unused = []
        font_count = len(font_folders(self.root))
        total = 0
        for kind in KINDS:
            unused = find_unused(self.root, kind)
            total += len(unused)
            top = QtWidgets.QTreeWidgetItem(
                [f"{kind.filename} - " + (f"{len(unused)} unused {kind.label}(s)" if unused
                                          else f"every {kind.label} is used")])
            top.setFirstColumnSpanned(True)
            _bold(top)
            self.unused_tree.addTopLevelItem(top)
            for profile in unused:
                fonts = profile.browsable_from
                where = ("no font" if not fonts else
                         f"all {font_count} fonts" if len(fonts) == font_count else
                         ", ".join(fonts))
                item = QtWidgets.QTreeWidgetItem(
                    [f"{kind.section} {profile.number}", profile.name, where])
                item.setToolTip(2, ", ".join(fonts) or "No font's used_profiles mask allows it")
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(0, QtCore.Qt.Unchecked)
                top.addChild(item)
                self._unused.append((item, profile))
            top.setExpanded(True)
        self.unused_tree.blockSignals(False)
        self.tabs.setTabText(1, f"Unused ({total})")

    # ------------------------------------------------------------------ state

    def _ticked_groups(self):
        return [g for item, g in self._groups if item.checkState(0) == QtCore.Qt.Checked]

    def _ticked_unused(self):
        return [p for item, p in self._unused if item.checkState(0) == QtCore.Qt.Checked]

    def _tick_unused(self, ticked: bool):
        for item, _p in self._unused:
            item.setCheckState(0, QtCore.Qt.Checked if ticked else QtCore.Qt.Unchecked)

    def _update_buttons(self, *_args):
        self.merge_button.setEnabled(bool(self._ticked_groups()))
        count = len(self._ticked_unused())
        self.remove_button.setEnabled(bool(count))
        self.remove_button.setText(f"Remove {count} Ticked Profile(s)" if count
                                   else "Remove Ticked Profiles")

    # ------------------------------------------------------------------ actions

    def _backup_all(self):
        if self.main_window is None or not hasattr(self.main_window, '_backup_file'):
            return
        for name in ('config.txt', 'colors.txt', 'prefs.txt'):
            self.main_window._backup_file(self.root / name, "(root)")
        for number, name, path in font_folders(self.root):
            self.main_window._backup_file(path / 'font_config.txt', f"{number}-{name}")

    def _confirm(self, title: str, text: str) -> bool:
        return QtWidgets.QMessageBox.question(
            self, title, text + "\n\nThe main window reloads the card afterwards, so save "
                                "any changes you're making there first.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel) == QtWidgets.QMessageBox.Yes

    def _merge(self):
        groups = self._ticked_groups()
        removed = sum(len(g.remove) for g in groups)
        if not self._confirm("Merge Duplicates",
                             f"Remove {removed} duplicate profile(s) and renumber the rest? "
                             f"Fonts that used them will use the kept copy instead."):
            return
        self._backup_all()
        try:
            merge_duplicates(self.root, groups)
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "Merge Failed", f"Couldn't update the files:\n{e}")
        self.changed = True
        self._load()

    def _remove_unused(self):
        profiles = self._ticked_unused()
        browsable = sum(1 for p in profiles if p.browsable_from)
        text = f"Remove {len(profiles)} unused profile(s) and renumber the rest?"
        if browsable:
            text += (f"\n\n{browsable} of them can still be picked with Spectrum in some fonts; "
                     f"that choice goes away.")
        if not self._confirm("Remove Unused Profiles", text):
            return
        self._backup_all()
        try:
            remove_unused(self.root, profiles)
        except (OSError, ValueError) as e:
            QtWidgets.QMessageBox.critical(self, "Remove Failed", f"Couldn't remove them:\n{e}")
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
