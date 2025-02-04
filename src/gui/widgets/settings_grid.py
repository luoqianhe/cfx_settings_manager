from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel, 
    QPushButton, QFrame, QScrollArea
)
from PySide6.QtCore import Signal, Qt, QTimer
from pathlib import Path
import json
from PySide6 import QtWidgets
from ..edit_dialogs import create_edit_dialog


class SettingsGrid(QWidget):
    setting_edit_requested = Signal(str, str, dict)  # param_name, current_value, constraints
    
    def __init__(self, title: str, main_window=None, parent=None):
        super().__init__(parent)
        self.title = title
        self.main_window = main_window  # Store the MainWindow reference
        self.current_settings = {}
        self.param_definitions = {}
        self.load_parameter_definitions()
        self.init_ui()

    def load_parameter_definitions(self):
        """Load parameter definitions from JSON file."""
        try:
            params_file = Path(__file__).parent.parent.parent / 'config' / 'parameters.json'
            with open(params_file, 'r') as f:
                all_params = json.load(f)
                # Select appropriate parameter set based on title
                if 'Font Configuration' in self.title:
                    self.param_definitions = all_params.get('font_config_parameters', {})
                elif 'Blade Profile' in self.title:
                    self.param_definitions = all_params.get('blade_profile_parameters', {})
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error loading parameter definitions: {e}")
            self.param_definitions = {}

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Title
        title_label = QLabel(self.title)
        title_label.setStyleSheet("font-weight: bold; font-size: 14px; padding: 4px;")
        layout.addWidget(title_label)

        # Shared profiles info (for blade profiles)
        if 'Blade Profile' in self.title:
            self.shared_info = QLabel()
            self.shared_info.setStyleSheet("color: #666; font-size: 12px; padding: 4px;")
            layout.addWidget(self.shared_info)

        # Scrollable area for settings
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        # content.setStyleSheet("")  # Add border
        self.grid_layout = QGridLayout(content)
        self.grid_layout.setSpacing(10)  # Add spacing
        self.grid_layout.setColumnStretch(2, 1)  # Make description column stretch
        scroll.setWidget(content)
        layout.addWidget(scroll)

        # Headers
        headers = ["Parameter", "Value", "Description"]
        for col, text in enumerate(headers):
            label = QLabel(text)
            label.setStyleSheet("font-weight: bold;")
            self.grid_layout.addWidget(label, 0, col)

    def update_settings(self, settings: dict, shared_with: list = None):
        """Update displayed settings."""
        for param_name, value in settings.items():
            print(f"  {param_name}: {value}")
        self.current_settings = settings

        # Clear existing settings (except headers)
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item:
                widget = item.widget()
                if widget:
                    widget.deleteLater()

        # Update shared profiles info if applicable
        if hasattr(self, 'shared_info') and shared_with:
            self.shared_info.setText(f"Also used by: {', '.join(shared_with)}")
            self.shared_info.setVisible(bool(shared_with))

        # Add settings
        row = 1
        for param_name, value in settings.items():
            # Parameter name
            name_label = QLabel(param_name)
            name_label.setStyleSheet("font-family: monospace; color: black;")
            self.grid_layout.addWidget(name_label, row, 0)

            # Value
            value_label = QLabel()
            value_label.setStyleSheet("font-family: monospace; color: black; background-color: white; padding: 2px; border: 1px solid #ccc;")
            value_label.setMinimumWidth(100)
            desc = ""
            if param_name in self.param_definitions:
                param_def = self.param_definitions[param_name]
                if param_name == 'start_color':
                    main_window = self.parent().parent()
                    if hasattr(main_window, 'color_profiles'):
                        try:
                            value_int = int(value)
                            if value_int in main_window.color_profiles:
                                color_name = main_window.color_profiles[value_int]['color_name']
                                desc = f" ({color_name})"
                        except ValueError:
                            print(f"Could not convert value to int: {value}")
                elif param_name in ['style_grafx1', 'style_grafx2', 'style_grafx3']:
                    try:
                        value_int = int(value)
                        if hasattr(self.main_window, 'grafx_profiles'):
                            print(f"DEBUG: Available grafx profiles: {self.main_window.grafx_profiles}")
                        
                        if value_int == -1:
                            desc = " (none)"
                        else:
                            if hasattr(self.main_window, 'grafx_profiles') and value_int in self.main_window.grafx_profiles:
                                grafx_name = self.main_window.grafx_profiles[value_int]
                                desc = f" ({grafx_name})"
                            else:
                                print(f"DEBUG: Value {value_int} not in profiles or no profiles available")
                    except ValueError as e:
                        print(f"DEBUG: Error: {e}")
                elif 'values' in param_def and str(value) in param_def['values']:
                    desc = f" ({param_def['values'][str(value)]})"

            full_text = f"{value}{desc}"
            value_label.setText(full_text)
            value_label.show()  # Force show the label
            self.grid_layout.addWidget(value_label, row, 1)

            # Edit button
            edit_btn = QPushButton("✎")
            edit_btn.setFixedWidth(30)
            edit_btn.setStyleSheet("color: black;")
            edit_btn.clicked.connect(lambda checked, p=param_name, v=value: 
                self.edit_setting(p, v))
            self.grid_layout.addWidget(edit_btn, row, 2)

            # Description
            desc = self.param_definitions.get(param_name, {}).get('description', '')
            desc_label = QLabel(desc)
            desc_label.setStyleSheet("color: black;")
            desc_label.setWordWrap(True)
            self.grid_layout.addWidget(desc_label, row, 3)
            
            row += 1

        # Update the layout
        self.grid_layout.update()
        content = self.grid_layout.parentWidget()
        if content:
            content.update()
        scroll = content.parentWidget()
        if scroll:
            scroll.update()
        
        # Force another update after a short delay
        QTimer.singleShot(100, self.grid_layout.update)

    def get_current_settings(self) -> dict:
        """Return current settings."""
        return self.current_settings.copy()

    def update_single_setting(self, param_name: str, new_value: str):
        """Update a single setting value."""
        self.current_settings[param_name] = new_value
        self.update_settings(self.current_settings)

    def edit_setting(self, param_name: str, current_value: str):
        """Show appropriate edit dialog based on parameter type."""
        try:
            constraints = self.param_definitions.get(param_name, {})
            dialog = create_edit_dialog(param_name, current_value, constraints, self)
            
            if dialog.exec() == QtWidgets.QDialog.Accepted:
                new_value = dialog.get_value()
                self.update_single_setting(param_name, new_value)
                
        except Exception as e:
            print(f"Error editing setting: {e}")
            QtWidgets.QMessageBox.warning(
                self,
                "Error",
                f"Failed to edit setting: {str(e)}"
            )
    
    def filter_settings(self, search_text: str):
        """Filter settings based on search text"""
        # Save copy of original settings if we haven't yet
        if not hasattr(self, 'original_settings'):
            self.original_settings = self.current_settings.copy()

        if not search_text.strip():
            # When search is empty, restore all original settings
            self.update_settings(self.original_settings)
            return

        # Case-insensitive search
        search_text = search_text.lower()
        
        # Filter settings that match the search
        filtered_settings = {}
        for param_name, value in self.original_settings.items():  # Search through original settings
            # Check parameter name
            if search_text in param_name.lower():
                filtered_settings[param_name] = value
                continue
                
            # Check parameter description
            desc = self.param_definitions.get(param_name, {}).get('description', '').lower()
            if search_text in desc:
                filtered_settings[param_name] = value
                continue
                
            # Check if it has enumerated values and search their descriptions
            if 'values' in self.param_definitions.get(param_name, {}):
                values_desc = ' '.join(str(v) for v in self.param_definitions[param_name]['values'].values()).lower()
                if search_text in values_desc:
                    filtered_settings[param_name] = value
                    continue

        # Update display with filtered settings
        self.update_settings(filtered_settings)