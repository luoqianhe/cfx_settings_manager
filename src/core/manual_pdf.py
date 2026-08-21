# src/core/manual_pdf.py
"""Helpers for the "open this parameter in the CFX manual" feature: where the user's local
copy of the manual PDF lives (persisted across runs via QSettings) and how to jump to a
parameter in it.

There's no standard, viewer-agnostic way to hand a search term to whatever PDF application
happens to be the OS default - so instead of trying to drive a specific viewer, this copies
the parameter name to the clipboard and opens the PDF in the OS's default viewer, letting the
user paste it straight into that viewer's own search (Cmd+F / Ctrl+F).
"""
from pathlib import Path
from PySide6 import QtCore, QtGui, QtWidgets

MANUAL_DOWNLOAD_URL = "https://www.plecterlabs.com/shop/article_info.php?articles_id=125"
_SETTINGS_KEY = "manual_pdf_path"


def get_manual_pdf_path() -> str:
    """Path to the user's locally selected CFX manual PDF, or '' if none has been picked."""
    return QtCore.QSettings().value(_SETTINGS_KEY, "", type=str)


def set_manual_pdf_path(path: str):
    QtCore.QSettings().setValue(_SETTINGS_KEY, path)


def open_manual_for_parameter(param_name: str, parent: QtWidgets.QWidget = None) -> bool:
    """Copy param_name to the clipboard and open the manual PDF in the OS default viewer.
    Returns False (and shows a message box) if no manual PDF has been selected yet, or the
    previously selected one no longer exists on disk."""
    path = get_manual_pdf_path()
    if not path or not Path(path).is_file():
        QtWidgets.QMessageBox.information(
            parent, "No Manual Selected",
            "No CFX manual PDF has been selected yet.\n\n"
            "Download the manual from the link in the Validation Issues section, then use "
            "\"Select Manual PDF...\" there to point the app at it."
        )
        return False

    QtWidgets.QApplication.clipboard().setText(param_name)
    QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))
    return True
