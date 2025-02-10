from PySide6 import QtWidgets, QtGui
from pathlib import Path
import json
import os
from src.gui.widgets.widget_factory import (
    create_spinner_widget, 
    create_dropdown_widget, 
    create_toggle_widget, 
    create_range_pair_widget,
    create_color_picker_widget,
    create_triple_range_widget,
    create_text_input_widget,
    create_parameter_widget
)
class TestWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Parameter Input Test")
        self.setMinimumSize(800, 600)
        
        # Load parameter definitions
        params_file = Path('src/config/parameters.json')
        with open(params_file, 'r') as f:
            self.param_definitions = json.load(f)
        
         # Load test configuration files
        test_folder = Path('test_cfx_folder')
        config_file = test_folder / 'config.txt'
        self.config_settings = self.load_config_file(config_file)  # Store as class attribute
        
        self.init_ui()

    def load_config_file(self, file_path: Path) -> dict:
        """Load settings from a config file"""
        settings = {}
        try:
            with open(file_path, 'r') as f:
                current_profile = None
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('//'):
                        continue
                    if line.startswith('[profile='):
                        current_profile = int(line[9:-1])
                        settings[current_profile] = {}
                    elif '=' in line and current_profile is not None:
                        key, value = line.split('=', 1)
                        settings[current_profile][key.strip()] = value.strip()
        except Exception as e:
            print(f"Error loading config file: {e}")
        return settings

    def load_font_config(self, file_path: Path) -> dict:
        """Load settings from a font_config file"""
        settings = {}
        try:
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('//') or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, value = line.split('=', 1)
                        settings[key.strip()] = value.strip()
        except Exception as e:
            print(f"Error loading font config: {e}")
        return settings

    def init_ui(self):
        # Load test files
        test_folder = Path('test_cfx_folder')
        # DEBUG PRINT
        print(f"\nLooking for files in: {test_folder.absolute()}")
        config_file = test_folder / 'config.txt'
        font_config_file = test_folder / '1-THE_LIGHT' / 'font_config.txt'
        
        # DEBUG PRINT
        print(f"Config file exists: {config_file.exists()}")
        print(f"Font config file exists: {font_config_file.exists()}")
        
        config_settings = self.load_config_file(config_file)
        font_settings = self.load_font_config(font_config_file)

        # DEBUG PRINT
        print("\nLoaded config settings:", config_settings)
        print('-------------')
        print("Profile 0 settings:", config_settings.get(0, {}))
        print("flks value:", config_settings.get(0, {}).get('flks'))
        print("style_pon value:", config_settings.get(0, {}).get('style_pon'))
        print('-------------')
        print("Profile 1 settings:", config_settings.get(1, {}))
        print("flks value:", config_settings.get(1, {}).get('flks'))
        print("style_pon value:", config_settings.get(1, {}).get('style_pon'))
        print("\nLoaded font settings:", font_settings)
        print('-------------')

        # Create scroll area for content
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QtWidgets.QWidget()
        scroll_layout = QtWidgets.QVBoxLayout(scroll_widget)

        self.input_widgets = {}
        for param_name, param_def in self.param_definitions['blade_profile_parameters'].items():
            current_value = None
            if self.config_settings and 0 in self.config_settings:
                current_value = self.config_settings[0].get(param_name)
                
            container, widget = create_parameter_widget(param_name, param_def, current_value)
            self.input_widgets[param_name] = widget
            scroll_layout.addWidget(container)
        
        # Add OK button
        ok_button = QtWidgets.QPushButton("OK")
        ok_button.clicked.connect(self.on_ok)
        scroll_layout.addWidget(ok_button)

        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll)

    def on_ok(self):
        print(f"flks value: {self.flks_input.value()}")
        print(f"style_pon value: {self.style_pon_input.currentData()}")
        print(f"focl value: {1 if self.focl_input.isChecked() else 0}")
        print(f"mapping_move value: {self.mapping_move_input[0].value()},{self.mapping_move_input[1].value()}")
        print(f"color value: {','.join(str(self.color_input[0][c][1].value()) for c in ['R','G','B','W'])}")
        print(f"twon value: {self.twon_input[0].value()},{self.twon_input[1].value()},{self.twon_input[2].value()}")
        text_value = self.text_input.text()
        print(f"Text value: {text_value}")
        self.close()

def main():
    app = QtWidgets.QApplication([])
    window = TestWindow()
    window.show()
    return app.exec()

if __name__ == "__main__":
    main()