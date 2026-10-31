# src/gui/validation_report_dialog.py
from pathlib import Path
from PySide6 import QtWidgets, QtCore


class ValidationReportDialog(QtWidgets.QDialog):
    """Shows the results of a full-folder validation pass: per-font parameter errors (the
    same checks the settings grid highlights red for the currently-selected font, run across
    every font), config.txt/colors.txt structural errors (duplicate profile/color numbers),
    and blade/color profiles that are defined but never actually used by any font."""

    jump_to_font = QtCore.Signal(str)  # font_path, as a string
    font_config_changed = QtCore.Signal(str)  # font_path, as a string - written to disk from here
    fix_grafx_requested = QtCore.Signal(list)   # the report's grafx_warnings
    cleanup_profiles_requested = QtCore.Signal()

    def __init__(self, report: dict, file_handler, parent=None, backup_fn=None):
        super().__init__(parent)
        self.file_handler = file_handler
        # Optional callable(file_path: Path, font_name: str) -> None, supplied by
        # MainWindow, that backs up a file before it's overwritten. None if the user
        # hasn't configured a backup location.
        self.backup_fn = backup_fn
        self.setWindowTitle("Validate All Soundfonts")
        self.resize(700, 500)

        # font_path (str) -> {'group', 'missing_group', 'missing_keys', 'error_count'}, so a
        # right-click "insert missing keys" action can find and update the right row without
        # re-running the whole validation pass.
        self._font_rows = {}
        self.issue_count = (
            len(report['structural_errors'])
            + len(report.get('global_errors', {}))
            + sum(len(f['errors']) for f in report['font_reports'])
            + sum(len(f.get('missing_keys', {})) for f in report['font_reports'])
            + len(report['orphaned_profiles'])
            + len(report['orphaned_colors'])
            + len(report.get('grafx_warnings', []))
        )
        self.font_count = report.get('font_count', 0)

        layout = QtWidgets.QVBoxLayout(self)

        self.summary = QtWidgets.QLabel()
        layout.addWidget(self.summary)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Issue"])
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu_requested)

        if report['structural_errors']:
            group = QtWidgets.QTreeWidgetItem(self.tree, ["File Structure"])
            group.setExpanded(True)
            for msg in report['structural_errors']:
                QtWidgets.QTreeWidgetItem(group, [msg])

        global_errors = report.get('global_errors', {})
        if global_errors:
            group = QtWidgets.QTreeWidgetItem(
                self.tree, [f"Global Settings ({len(global_errors)}) - applies to every soundfont, reported once"])
            group.setExpanded(True)
            for param_name, msg in global_errors.items():
                QtWidgets.QTreeWidgetItem(group, [f"{param_name}: {msg}"])

        for font_report in report['font_reports']:
            self._add_font_row(font_report)

        grafx_warnings = report.get('grafx_warnings', [])
        if grafx_warnings:
            group = QtWidgets.QTreeWidgetItem(
                self.tree, [f"GraFx warnings ({len(grafx_warnings)}) - animation files, and "
                            f"timing vs. refreshfx and sound length"])
            group.setExpanded(True)
            by_font = {}
            for warning in grafx_warnings:
                by_font.setdefault(str(warning['font_path']), []).append(warning)
            for font_path, warnings in by_font.items():
                first = warnings[0]
                font_item = QtWidgets.QTreeWidgetItem(
                    group, [f"{first['font_num']}-{first['font_name']} ({len(warnings)})"])
                font_item.setData(0, QtCore.Qt.UserRole, font_path)
                for warning in warnings:
                    item = QtWidgets.QTreeWidgetItem(
                        font_item, [f"{warning['resource']}/{warning['file']}: {warning['message']}"])
                    item.setToolTip(0, warning['message'])

        if report['orphaned_profiles']:
            group = QtWidgets.QTreeWidgetItem(
                self.tree, [f"Unused blade profiles ({len(report['orphaned_profiles'])})"])
            group.setExpanded(True)
            for num in report['orphaned_profiles']:
                QtWidgets.QTreeWidgetItem(
                    group, [f"Profile {num} is defined in config.txt but no font references it"])

        if report['orphaned_colors']:
            group = QtWidgets.QTreeWidgetItem(
                self.tree, [f"Unused color profiles ({len(report['orphaned_colors'])})"])
            group.setExpanded(True)
            for num in report['orphaned_colors']:
                QtWidgets.QTreeWidgetItem(
                    group, [f"Color {num} is defined in colors.txt but no font references it"])

        self._placeholder = None
        if self.issue_count == 0:
            self._placeholder = QtWidgets.QTreeWidgetItem(self.tree, ["Nothing to report"])
            self._placeholder.setDisabled(True)

        self._update_summary()
        layout.addWidget(self.tree)

        hint = QtWidgets.QLabel(
            "Double-click a font's row to jump to it. Right-click a font with missing "
            "parameters to insert them all with their reference defaults.")
        hint.setStyleSheet("color: #666; font-style: italic; padding: 4px;")
        layout.addWidget(hint)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.accept)
        if grafx_warnings:
            fix_button = buttons.addButton("Fix GraFx Warnings…", QtWidgets.QDialogButtonBox.ActionRole)
            fix_button.clicked.connect(lambda: self.fix_grafx_requested.emit(grafx_warnings))
        if report['orphaned_profiles'] or report['orphaned_colors']:
            cleanup_button = buttons.addButton("Remove Unused Profiles…",
                                               QtWidgets.QDialogButtonBox.ActionRole)
            cleanup_button.clicked.connect(self.cleanup_profiles_requested.emit)
        layout.addWidget(buttons)

    def _add_font_row(self, font_report):
        missing_keys = dict(font_report.get('missing_keys', {}))
        error_count = len(font_report['errors'])
        font_path = str(font_report['font_path'])

        group = QtWidgets.QTreeWidgetItem(self.tree, [""])
        group.setData(0, QtCore.Qt.UserRole, font_path)
        group.setExpanded(True)
        for param_name, msg in font_report['errors'].items():
            QtWidgets.QTreeWidgetItem(group, [f"{param_name}: {msg}"])

        row = {
            'group': group,
            'missing_group': None,
            'missing_keys': missing_keys,
            'error_count': error_count,
            'font_num': font_report['font_num'],
            'font_name': font_report['font_name'],
        }
        self._font_rows[font_path] = row

        if missing_keys:
            self._build_missing_group(row)

        self._update_font_row_label(row)
        return row

    def _build_missing_group(self, row):
        missing_keys = row['missing_keys']
        missing_group = QtWidgets.QTreeWidgetItem(
            row['group'], [f"Missing font_config.txt keys ({len(missing_keys)}) - "
                            f"right-click the font above to add them all"])
        for param_name, default_value in sorted(missing_keys.items()):
            QtWidgets.QTreeWidgetItem(
                missing_group, [f"{param_name} (reference default: {default_value})"])
        row['missing_group'] = missing_group

    def _update_font_row_label(self, row):
        total = row['error_count'] + len(row['missing_keys'])
        row['group'].setText(0, f"{row['font_num']}-{row['font_name']} ({total} issue(s))")

    def _update_summary(self):
        if self.issue_count == 0:
            self.summary.setText(f"No issues found across {self.font_count} soundfont(s).")
            self.summary.setStyleSheet("color: #2e7d32; font-weight: bold; padding: 8px;")
        else:
            self.summary.setText(
                f"Found {self.issue_count} issue(s) across {self.font_count} soundfont(s) checked.")
            self.summary.setStyleSheet("color: #B00020; font-weight: bold; padding: 8px;")

    def _on_item_double_clicked(self, item, _column):
        font_path = item.data(0, QtCore.Qt.UserRole)
        if font_path:
            self.jump_to_font.emit(font_path)
            self.accept()

    def _on_context_menu_requested(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        font_path = item.data(0, QtCore.Qt.UserRole)
        row = self._font_rows.get(font_path)
        if row is None or not row['missing_keys']:
            return

        menu = QtWidgets.QMenu(self)
        count = len(row['missing_keys'])
        action = menu.addAction(f"Insert {count} missing parameter(s) with default values")
        action.triggered.connect(lambda: self._insert_missing_keys(font_path))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _insert_missing_keys(self, font_path):
        row = self._font_rows.get(font_path)
        if row is None or not row['missing_keys']:
            return

        font_dir = Path(font_path)
        if self.backup_fn:
            self.backup_fn(font_dir / "font_config.txt", font_dir.name)

        if not self.file_handler.save_font_config(font_dir, row['missing_keys']):
            QtWidgets.QMessageBox.warning(
                self, "Insert Failed",
                f"Couldn't write to font_config.txt for {row['font_num']}-{row['font_name']}."
            )
            return

        inserted = len(row['missing_keys'])
        self.issue_count -= inserted
        row['missing_keys'] = {}
        if row['missing_group'] is not None:
            row['group'].removeChild(row['missing_group'])
            row['missing_group'] = None
        self._update_font_row_label(row)
        self._update_summary()

        if self.issue_count == 0 and self._placeholder is None:
            self._placeholder = QtWidgets.QTreeWidgetItem(self.tree, ["Nothing to report"])
            self._placeholder.setDisabled(True)

        self.font_config_changed.emit(font_path)
