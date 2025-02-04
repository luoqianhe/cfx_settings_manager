# src/main.py
import sys
from PySide6 import QtWidgets
from gui.main_window import MainWindow

def main():
    app = QtWidgets.QApplication(sys.argv)

     # Set light mode style
    app.setStyle('Fusion')
    palette = app.palette()
    app.setPalette(palette)
    
    window = MainWindow()
    window.show()
    return app.exec()

if __name__ == "__main__":
    sys.exit(main())