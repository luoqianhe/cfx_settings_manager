# src/gui/import_font_dialog.py
"""Add a soundfont from another CFX card: copy its folder in as the next font number,
bring its blade and color profiles along (reusing identical ones already on this card) and
copy any GraFx / Accents / Pixies resources they link to. core.profile_library does the
work; this dialog shows the plan first and only writes when the user clicks Import."""
from html import escape
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from core.profile_library import (
    BLADE, COLOR, KINDS, MAX_PROFILES, LineFile, parse_sections, plan_import, run_import,
)


class ImportFontDialog(QtWidgets.QDialog):
    def __init__(self, cfx_root: Path, main_window=None):
        super().__init__(main_window)
        self.setWindowTitle("Add Soundfont")
        self.resize(640, 560)
        self.main_window = main_window
        self.root = Path(cfx_root)
        self.source = None
        self.plan = None
        self.imported = None

        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(
            "Choose a font folder on another CFX card (the card's folder must have its "
            "config.txt and colors.txt). The font is copied here as the next font number, "
            "and its blade and color profiles are added to this card's config.txt and "
            "colors.txt - unless an identical profile is already here, which is reused.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #555555;")
        layout.addWidget(intro)

        row = QtWidgets.QHBoxLayout()
        self.source_label = QtWidgets.QLabel("No font chosen")
        self.source_label.setWordWrap(True)
        choose = QtWidgets.QPushButton("Choose Font Folder…")
        choose.clicked.connect(self._choose)
        row.addWidget(self.source_label, stretch=1)
        row.addWidget(choose)
        layout.addLayout(row)

        self.browsable_check = QtWidgets.QCheckBox(
            "Also import the other profiles this font can switch to with Spectrum")
        self.browsable_check.setToolTip(
            "Off: only the color and blade profile the font starts with are imported, and the "
            "font can browse every profile on this card.\nOn: every profile its "
            "used_profiles masks allow is imported too, so Spectrum offers the same choices "
            "as on the other card.")
        self.browsable_check.toggled.connect(self._replan)
        layout.addWidget(self.browsable_check)

        self.summary = QtWidgets.QTextBrowser()
        layout.addWidget(self.summary, stretch=1)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        self.import_button = QtWidgets.QPushButton("Import")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self._import)
        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.reject)
        buttons.addWidget(self.import_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        self._show_capacity()

    def _show_capacity(self):
        lines = []
        for kind in KINDS:
            path = self.root / kind.filename
            count = len(parse_sections(LineFile(path), kind)) if path.is_file() else 0
            lines.append(f"{kind.filename}: {count} of {MAX_PROFILES} {kind.label}s used")
        self.summary.setHtml("<p style='color:#555555'>" + "<br>".join(lines) + "</p>")

    def _choose(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Choose the Font Folder to Add", str(self.source.parent) if self.source else "")
        if folder:
            self.source = Path(folder)
            self.source_label.setText(f"{self.source.name}  <span style='color:#777777'>"
                                      f"(from {escape(str(self.source.parent))})</span>")
            self._replan()

    def _replan(self, *_args):
        if self.source is None:
            return
        self.plan = plan_import(self.source, self.root, self.browsable_check.isChecked())
        self.summary.setHtml(self._describe(self.plan))
        self.import_button.setEnabled(not self.plan.errors)

    @staticmethod
    def _describe(plan) -> str:
        parts = []
        if plan.errors:
            parts.append("<p style='color:#B00020'><b>Can't import:</b><br>"
                         + "<br>".join(escape(e) for e in plan.errors) + "</p>")
        parts.append(f"<p><b>New font folder:</b> {escape(plan.dest_font.name)}</p>")
        for kind in (BLADE, COLOR):
            rows = [p for p in plan.profiles if p.kind == kind]
            if not rows:
                continue
            items = []
            for p in rows:
                name = f" ({escape(p.name)})" if p.name else ""
                if p.reused:
                    items.append(f"{p.source_number}{name} → reuses identical "
                                 f"{kind.section} {p.target_number}")
                else:
                    items.append(f"{p.source_number}{name} → <b>added as {kind.section} "
                                 f"{p.target_number}</b>")
            parts.append(f"<p><b>{escape(kind.filename)}</b> ({kind.label}s):<br>"
                         + "<br>".join(items) + "</p>")
        if plan.resources:
            items = []
            for r in plan.resources:
                if r.source is None:
                    continue
                if r.reused:
                    items.append(f"{r.kind} {r.source_number} ({escape(r.source.name)}) → "
                                 f"identical {escape(r.dest.name)} already here")
                else:
                    items.append(f"{r.kind} {r.source_number} ({escape(r.source.name)}) → "
                                 f"<b>copied as {escape(r.dest.name)}</b>")
            if items:
                parts.append("<p><b>Linked resources:</b><br>" + "<br>".join(items) + "</p>")
        if plan.font_config:
            starts = ", ".join(f"{k}={v}" for k, v in plan.font_config.items()
                               if k.startswith('start_'))
            parts.append(f"<p><b>font_config.txt:</b> {escape(starts)}. A [font="
                         f"{plan.font_number - 1}] entry is added to prefs.txt, and the "
                         f"font-name comments in config.txt and colors.txt are updated.</p>")
        if plan.warnings:
            parts.append("<p style='color:#8A5A00'>⚠ " + "<br>⚠ ".join(
                escape(w) for w in plan.warnings) + "</p>")
        return "".join(parts)

    def _import(self):
        if self.plan is None or self.plan.errors:
            return
        response = QtWidgets.QMessageBox.question(
            self, "Add Soundfont",
            f"Copy {self.plan.source_font.name} to this card as {self.plan.dest_font.name} "
            f"and update config.txt, colors.txt and prefs.txt?\n\nThe main window reloads "
            f"the card afterwards, so save any changes you're making there first.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel)
        if response != QtWidgets.QMessageBox.Yes:
            return
        if self.main_window is not None and hasattr(self.main_window, '_backup_file'):
            for name in ('config.txt', 'colors.txt', 'prefs.txt'):
                self.main_window._backup_file(self.root / name, "(root)")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            self.imported = run_import(self.plan)
        except (OSError, ValueError) as e:
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.critical(self, "Import Failed", f"The import stopped:\n{e}")
            return
        QtWidgets.QApplication.restoreOverrideCursor()
        self.accept()
