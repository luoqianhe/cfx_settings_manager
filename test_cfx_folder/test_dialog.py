from PySide6 import QtWidgets
import sys

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CFX Settings Manager")
        self.setMinimumSize(1024, 768)
        
        # Show file dialog immediately
        self.prompt_for_folder()

    def prompt_for_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select CFX Root Folder",
            "",
            QtWidgets.QFileDialog.ShowDirsOnly
        )
        if folder:
            print(f"Selected folder: {folder}")
        else:
            print("No folder selected")

app = QtWidgets.QApplication(sys.argv)
window = MainWindow()
window.show()
app.exec()