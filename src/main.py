# src/main.py
import sys
from PySide6 import QtWidgets, QtGui
from gui.main_window import MainWindow


def _build_light_palette() -> QtGui.QPalette:
    """A fixed light palette, applied regardless of the OS theme.

    The app's own styling (section headers, alternating rows, etc.) hardcodes light
    backgrounds throughout, but several labels and list items never set an explicit text
    color - they rely on whatever the palette says. Under an OS dark theme, Qt's default
    palette supplies white text for those, landing on top of the hardcoded near-white
    backgrounds and becoming unreadable. Pinning the palette (rather than patching every
    such spot) keeps the whole app's contrast correct on any OS/theme setting.
    """
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#f0f0f0"))
    palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#000000"))
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor("#ffffff"))
    palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor("#f7f7f7"))
    palette.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor("#ffffe1"))
    palette.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor("#000000"))
    palette.setColor(QtGui.QPalette.Text, QtGui.QColor("#000000"))
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor("#f0f0f0"))
    palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#000000"))
    palette.setColor(QtGui.QPalette.BrightText, QtGui.QColor("#ff0000"))
    palette.setColor(QtGui.QPalette.Link, QtGui.QColor("#4A90E2"))
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#4A90E2"))
    palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#ffffff"))
    palette.setColor(QtGui.QPalette.PlaceholderText, QtGui.QColor("#808080"))
    palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Text, QtGui.QColor("#a0a0a0"))
    palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.WindowText, QtGui.QColor("#a0a0a0"))
    palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.ButtonText, QtGui.QColor("#a0a0a0"))
    return palette


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(_build_light_palette())
    window = MainWindow()
    window.show()
    return app.exec()

if __name__ == "__main__":
    sys.exit(main())
