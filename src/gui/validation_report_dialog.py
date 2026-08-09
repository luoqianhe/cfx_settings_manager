# src/gui/validation_report_dialog.py
from PySide6 import QtWidgets, QtCore


class ValidationReportDialog(QtWidgets.QDialog):
    """Shows the results of a full-folder validation pass: per-font parameter errors (the
    same checks the settings grid highlights red for the currently-selected font, run across
    every font), config.txt/colors.txt structural errors (duplicate profile/color numbers),
    and blade/color profiles that are defined but never actually used by any font."""

    jump_to_font = QtCore.Signal(str)  # font_path, as a string

    def __init__(self, report: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Validate All Soundfonts")
        self.resize(700, 500)

        layout = QtWidgets.QVBoxLayout(self)

        issue_count = (
            len(report['structural_errors'])
            + len(report.get('global_errors', {}))
            + sum(len(f['errors']) for f in report['font_reports'])
            + len(report['orphaned_profiles'])
            + len(report['orphaned_colors'])
        )
        font_count = report.get('font_count', 0)

        summary = QtWidgets.QLabel()
        if issue_count == 0:
            summary.setText(f"No issues found across {font_count} soundfont(s).")
            summary.setStyleSheet("color: #2e7d32; font-weight: bold; padding: 8px;")
        else:
            summary.setText(f"Found {issue_count} issue(s) across {font_count} soundfont(s) checked.")
            summary.setStyleSheet("color: #B00020; font-weight: bold; padding: 8px;")
        layout.addWidget(summary)

        tree = QtWidgets.QTreeWidget()
        tree.setHeaderLabels(["Issue"])
        tree.itemDoubleClicked.connect(self._on_item_double_clicked)

        if report['structural_errors']:
            group = QtWidgets.QTreeWidgetItem(tree, ["File Structure"])
            group.setExpanded(True)
            for msg in report['structural_errors']:
                QtWidgets.QTreeWidgetItem(group, [msg])

        global_errors = report.get('global_errors', {})
        if global_errors:
            group = QtWidgets.QTreeWidgetItem(
                tree, [f"Global Settings ({len(global_errors)}) - applies to every soundfont, reported once"])
            group.setExpanded(True)
            for param_name, msg in global_errors.items():
                QtWidgets.QTreeWidgetItem(group, [f"{param_name}: {msg}"])

        for font_report in report['font_reports']:
            label = (f"{font_report['font_num']}-{font_report['font_name']} "
                      f"({len(font_report['errors'])} issue(s))")
            group = QtWidgets.QTreeWidgetItem(tree, [label])
            group.setData(0, QtCore.Qt.UserRole, str(font_report['font_path']))
            group.setExpanded(True)
            for param_name, msg in font_report['errors'].items():
                QtWidgets.QTreeWidgetItem(group, [f"{param_name}: {msg}"])

        if report['orphaned_profiles']:
            group = QtWidgets.QTreeWidgetItem(
                tree, [f"Unused blade profiles ({len(report['orphaned_profiles'])})"])
            group.setExpanded(True)
            for num in report['orphaned_profiles']:
                QtWidgets.QTreeWidgetItem(
                    group, [f"Profile {num} is defined in config.txt but no font references it"])

        if report['orphaned_colors']:
            group = QtWidgets.QTreeWidgetItem(
                tree, [f"Unused color profiles ({len(report['orphaned_colors'])})"])
            group.setExpanded(True)
            for num in report['orphaned_colors']:
                QtWidgets.QTreeWidgetItem(
                    group, [f"Color {num} is defined in colors.txt but no font references it"])

        if issue_count == 0:
            placeholder = QtWidgets.QTreeWidgetItem(tree, ["Nothing to report"])
            placeholder.setDisabled(True)

        layout.addWidget(tree)

        hint = QtWidgets.QLabel("Double-click a font's row to jump to it.")
        hint.setStyleSheet("color: #666; font-style: italic; padding: 4px;")
        layout.addWidget(hint)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)

    def _on_item_double_clicked(self, item, _column):
        font_path = item.data(0, QtCore.Qt.UserRole)
        if font_path:
            self.jump_to_font.emit(font_path)
            self.accept()
