# src/gui/main_window.py
from PySide6 import QtWidgets, QtCore
from pathlib import Path
from gui.widgets.widget_factory import (
    create_spinner_widget, 
    create_dropdown_widget, 
    create_toggle_widget, 
    create_range_pair_widget,
    create_color_picker_widget,
    create_triple_range_widget,
    create_text_widget,
    create_parameter_widget
)

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
       super().__init__()
       self.folder_path = None
       self.setWindowTitle("CFX Settings Manager")
       self.setMinimumSize(1024, 768)
       
       # Create central widget and main layout
       central = QtWidgets.QWidget()
       self.setCentralWidget(central)
       layout = QtWidgets.QHBoxLayout(central)
       
       # Left sidebar for font list
       self.font_list = QtWidgets.QListWidget()
       self.font_list.itemClicked.connect(self.on_font_selected)
       layout.addWidget(self.font_list, stretch=1)
       
       # Right side for parameters
       self.param_widget = QtWidgets.QScrollArea()
       self.param_widget.setWidgetResizable(True)
       layout.addWidget(self.param_widget, stretch=3)
       
       # Add save button
       save_button = QtWidgets.QPushButton("Save Changes")
       save_button.clicked.connect(self.save_changes)
       
       self.prompt_for_folder()

    def prompt_for_folder(self):
       folder = QtWidgets.QFileDialog.getExistingDirectory(
           self,
           "Select CFX Root Folder"
       )
       if folder:
           self.load_cfx_folder(folder)
    
    def on_font_selected(self, item):
       font_path = item.data(QtCore.Qt.UserRole)
       config_path = Path(font_path) / "font_config.txt"
       if config_path.exists():
           settings = self.load_font_settings(config_path)
           self.display_settings(settings)
           
    def save_changes(self):
        try:
            # Get current font
            current_font = self.font_list.currentItem()
            if not current_font:
                raise Exception("No font selected")
                
            response = QtWidgets.QMessageBox.question(
                self,
                "Save Changes",
                "Are you sure you want to save these changes?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            )
            
            if response == QtWidgets.QMessageBox.Yes:
                # TODO: Implement actual save logic
                QtWidgets.QMessageBox.information(
                    self,
                    "Success",
                    "Changes saved successfully."
                )
                
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                f"Failed to save changes: {str(e)}"
            )

    def load_cfx_folder(self, folder_path):
        try:
            self.folder_path = folder_path # store the folder path
            print("Loading fonts...")
            self.font_list.clear()
            path = Path(folder_path)
            
            # Find and sort font folders
            folders = []
            for item in path.iterdir():
                if item.is_dir() and item.name[0].isdigit():
                    number = int(item.name.split('-')[0])
                    folders.append((number, item))
            
            # Sort by number
            folders.sort(key=lambda x: x[0])
            
            # Add sorted folders to list
            for _, item in folders:
                print(f"Found font folder: {item.name}")
                list_item = QtWidgets.QListWidgetItem(item.name)
                list_item.setData(QtCore.Qt.UserRole, str(item))
                self.font_list.addItem(list_item)
                
        except Exception as e:
            print(f"Error loading fonts: {e}")
            QtWidgets.QMessageBox.warning(None, "Error", f"Failed to load fonts: {str(e)}")

    def load_prefs_file(self):
        """Load preferences from prefs.txt"""
        try:
            prefs = {}
            prefs_path = Path(self.folder_path) / "prefs.txt"
            current_font = None
            
            with open(prefs_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('//'):
                        if line.startswith('[font='):
                            current_font = int(line[6:-1])
                            prefs[current_font] = {}
                        elif '=' in line and current_font is not None:
                            key, value = line.split('=', 1)
                            prefs[current_font][key.strip()] = value.strip()
            
            return prefs
        except Exception as e:
            print(f"Error loading prefs: {e}")
            return {}
    
    def on_font_selected(self, item):
        try:
            path = Path(item.data(QtCore.Qt.UserRole))
            print(f"\nDEBUG: Loading font settings from: {path}")
            
            # Get font number from directory name
            font_num = int(path.name.split('-')[0])
            print(f"DEBUG: Font number: {font_num}")
            
            # Load font config
            config_path = path / "font_config.txt"
            if not config_path.exists():
                print(f"DEBUG: font_config.txt not found in {path}")
                QtWidgets.QMessageBox.warning(self, "Error", f"No font_config.txt found in {path}")
                return
                
            settings = self.load_settings_file(config_path)
            
            # Load prefs
            prefs = self.load_prefs_file()
            font_prefs = prefs.get(font_num, {})
            
            # Determine which blade profile to use
            profile_num = settings.get('start_blade')
            if profile_num == '-1' and 'profile' in font_prefs:
                profile_num = font_prefs['profile']
                print(f"DEBUG: Using profile {profile_num} from prefs.txt")
            
            # Determine which color profile to use
            color_num = settings.get('start_color')
            if color_num == '-1' and 'color' in font_prefs:
                color_num = font_prefs['color']
                print(f"DEBUG: Using color {color_num} from prefs.txt")
                settings['start_color'] = color_num

            # Load blade profile if we have a valid profile number
            if profile_num and profile_num != '-1':
                print(f"DEBUG: Loading blade profile {profile_num}")
                blade_profile = self.load_blade_profile(profile_num)
                if blade_profile:
                    print(f"DEBUG: Successfully loaded blade profile with {len(blade_profile)} parameters")
                    settings.update(blade_profile)
                else:
                    print(f"DEBUG: Failed to load blade profile {profile_num}")
            
            # Load color profile if we have a valid color number
            if color_num and color_num != '-1':
                print(f"DEBUG: Loading color profile {color_num}")
                color_profile = self.load_color_profile(color_num)
                if color_profile:
                    print(f"DEBUG: Successfully loaded color profile with {len(color_profile)} parameters")
                    settings.update(color_profile)
                else:
                    print(f"DEBUG: Failed to load color profile {color_num}")
            
            if settings:
                print(f"DEBUG: Displaying {len(settings)} total parameters")
                self.display_settings(settings)
                        
        except Exception as e:
            print(f"Error loading settings: {e}")
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to load settings: {str(e)}")

    def load_color_profile(self, color_num):
        """Load color profile from colors.txt"""
        try:
            color_num = int(color_num)
            color_path = Path(self.folder_path) / "colors.txt"
            
            if not color_path.exists():
                print("DEBUG: colors.txt not found")
                return None
                
            current_color = None
            color_data = {}
            
            with open(color_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('[color='):
                        current_color = int(line[7:-1])
                    elif '=' in line and current_color == color_num and not line.startswith('//'):
                        key, value = line.split('=', 1)
                        color_data[key.strip()] = value.strip()
                        
            return color_data
            
        except Exception as e:
            print(f"Error loading color profile: {e}")
            return None
    
    def load_settings_file(self, file_path):
        settings = {}
        with open(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('//') and not line.startswith('#'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        settings[key.strip()] = value.strip()
        return settings

    def load_blade_profile(self, profile_num):
        try:
            profile_num = int(profile_num)
            config_path = Path(self.folder_path) / "config.txt"
            
            if not config_path.exists():
                return None
                
            current_profile = None
            profile_data = {}
            
            with open(config_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('[profile='):
                        current_profile = int(line[9:-1])
                    elif '=' in line and current_profile == profile_num:
                        key, value = line.split('=', 1)
                        profile_data[key.strip()] = value.strip()
                        
            return profile_data
            
        except Exception as e:
            print(f"Error loading blade profile: {e}")
            return None
   
    def display_settings(self, settings):
        try:
            print("\nDEBUG: Displaying settings:", settings)
            
            # Create and configure scroll area widget
            scroll_widget = QtWidgets.QWidget()
            scroll_widget.setContentsMargins(0, 0, 0, 0)
            main_layout = QtWidgets.QVBoxLayout(scroll_widget)
            main_layout.setSpacing(0)
            main_layout.setContentsMargins(0, 0, 0, 0)

            # Create settings grid widget
            grid_widget = QtWidgets.QWidget()
            grid_layout = QtWidgets.QGridLayout(grid_widget)
            grid_layout.setSpacing(12)
            grid_layout.setColumnStretch(2, 1)
            
            # Add headers
            headers = ["Parameter", "Value", "Description"]
            for col, text in enumerate(headers):
                label = QtWidgets.QLabel(text)
                label.setStyleSheet("""
                    font-weight: bold;
                    color: #2c3e50;
                    padding: 8px 4px;
                    border-bottom: 2px solid #3498db;
                """)
                grid_layout.addWidget(label, 0, col)

            # Process settings and create widgets
            row = 1
            for param_name, value in settings.items():
                param_def = self.get_parameter_definition(param_name)
                if not param_def:
                    continue

                # Background color for row
                bg_color = "#f8f9fa" if row % 2 == 0 else "white"
                
                # Parameter name
                name_label = QtWidgets.QLabel(param_name)
                name_label.setStyleSheet(f"""
                    font-weight: bold;
                    color: #2c3e50;
                    padding: 8px;
                    background-color: {bg_color};
                """)
                grid_layout.addWidget(name_label, row, 0)
                
                # Get display type and create appropriate widget
                display_type = param_def.get('display_type', 'text')
                container = None
                widget = None
                
                try:
                    from gui.widgets.widget_factory import (
                        create_spinner_widget, 
                        create_dropdown_widget,
                        create_toggle_widget,
                        create_range_pair_widget,
                        create_color_picker_widget,
                        create_triple_range_widget,
                        create_text_widget
                    )

                    if display_type == 'text_input':
                        container, widget = create_text_widget(param_name, param_def)
                    elif display_type == 'spinner':
                        container, widget = create_spinner_widget(param_name, param_def)
                    elif display_type == 'dropdown':
                        container, widget = create_dropdown_widget(param_name, param_def)
                    elif display_type == 'toggle':
                        container, widget = create_toggle_widget(param_name, param_def)
                    elif display_type == 'range_pair':
                        container, widget = create_range_pair_widget(param_name, param_def)
                    elif display_type == 'color_picker':
                        container, widget = create_color_picker_widget(param_name, param_def)
                    elif display_type == 'triple_range':
                        container, widget = create_triple_range_widget(param_name, param_def)

                    if container:
                        # Style container
                        container.setStyleSheet(f"""
                            background-color: {bg_color};
                            padding: 4px;
                        """)
                        grid_layout.addWidget(container, row, 1)
                        
                        # Set value based on widget type
                        if isinstance(widget, QtWidgets.QLineEdit):
                            widget.setText(str(value))
                            print(f"DEBUG: Set text {value} for {param_name}")
                        elif isinstance(widget, QtWidgets.QSpinBox):
                            widget.setValue(int(value))
                            print(f"DEBUG: Set value {value} for {param_name}")
                        elif isinstance(widget, QtWidgets.QComboBox):
                            index = widget.findData(str(value))
                            if index >= 0:
                                widget.setCurrentIndex(index)
                                print(f"DEBUG: Set combo index {index} for {param_name}")
                        elif isinstance(widget, tuple):  # For range_pair or color_picker that return multiple widgets
                            if display_type == 'range_pair':
                                min_val, max_val = map(int, value.split(','))
                                widget[0].setValue(min_val)
                                widget[1].setValue(max_val)
                            elif display_type == 'triple_range':
                                angle, min_val, max_val = map(int, value.split(','))
                                widget[0].setValue(angle)
                                widget[1].setValue(min_val)
                                widget[2].setValue(max_val)
                            elif display_type == 'color_picker':
                                r, g, b, w = map(int, value.split(','))
                                widget[0]['R'][1].setValue(r)
                                widget[0]['G'][1].setValue(g)
                                widget[0]['B'][1].setValue(b)
                                widget[0]['W'][1].setValue(w)

                except Exception as e:
                    print(f"DEBUG: Error creating/setting widget for {param_name}: {e}")

                # Description label
                desc_label = QtWidgets.QLabel(param_def.get('description', ''))
                desc_label.setWordWrap(True)
                desc_label.setStyleSheet(f"""
                    color: #666666;
                    background-color: {bg_color};
                    padding: 8px;
                """)
                grid_layout.addWidget(desc_label, row, 2)
                
                row += 1

            # Add grid widget to main layout
            main_layout.addWidget(grid_widget)

            # Clear any existing widget in the scroll area
            if self.param_widget.widget():
                self.param_widget.widget().deleteLater()

            # Set new widget
            self.param_widget.setWidget(scroll_widget)

        except Exception as e:
            print(f"Error displaying settings: {e}")
            QtWidgets.QMessageBox.warning(self, "Error", f"Failed to display settings: {str(e)}")
    def edit_parameter(self, param_name, current_value):
        try:
            param_def = self.get_parameter_definition(param_name)
            if param_def:
                from gui.edit_dialogs import create_edit_dialog
                dialog = create_edit_dialog(param_name, current_value, param_def, self)
                
                if dialog.exec() == QtWidgets.QDialog.Accepted:
                    new_value = dialog.get_value()
                    self.update_parameter(param_name, new_value)
                    
        except Exception as e:
            print(f"Error editing parameter: {e}")
            QtWidgets.QMessageBox.warning(
                self,
                "Error",
                f"Failed to edit parameter: {str(e)}"
            )

    def get_parameter_definition(self, param_name):
        try:
            import json
            param_file = Path(__file__).parent.parent / 'config' / 'parameters.json'
            with open(param_file) as f:
                params = json.load(f)
                return params.get('blade_profile_parameters', {}).get(param_name)
        except Exception as e:
            print(f"Error loading parameter definition: {e}")
            return None

    def get_parameter_description(self, param_name):
        param_def = self.get_parameter_definition(param_name)
        return param_def.get('description', '') if param_def else ''

    def update_parameter(self, param_name, new_value):
        # Find and update the value label
        scroll_widget = self.param_widget.widget()
        if scroll_widget:
            for i in range(scroll_widget.layout().rowCount()):
                name_item = scroll_widget.layout().itemAtPosition(i, 0)
                if name_item and name_item.widget().text() == param_name:
                    value_layout = scroll_widget.layout().itemAtPosition(i, 1)
                    if value_layout:
                        value_label = value_layout.itemAt(0).widget()
                        value_label.setText(str(new_value))
                    break
                
    def display_blade_profile(self, profile_data):
        try:
            # Create a second scroll area for blade profile parameters
            blade_widget = QtWidgets.QWidget()
            blade_layout = QtWidgets.QGridLayout(blade_widget)
            
            # Headers
            headers = ["Parameter", "Value", "Description"]
            for col, text in enumerate(headers):
                label = QtWidgets.QLabel(text)
                label.setStyleSheet("font-weight: bold;")
                blade_layout.addWidget(label, 0, col)
            
            row = 1
            for param_name, value in profile_data.items():
                param_def = self.get_parameter_definition(param_name)
                if not param_def:
                    continue
                    
                # Parameter name
                name_label = QtWidgets.QLabel(param_name)
                blade_layout.addWidget(name_label, row, 0)
                
                # Create appropriate widget based on display_type
                display_type = param_def.get('display_type', 'text')
                container = None
                
                if display_type == 'spinner':
                    container, widget = create_spinner_widget(param_name, param_def)
                elif display_type == 'dropdown':
                    container, widget = create_dropdown_widget(param_name, param_def)
                elif display_type == 'toggle':
                    container, widget = create_toggle_widget(param_name, param_def)
                elif display_type == 'range_pair':
                    container, widget = create_range_pair_widget(param_name, param_def)
                elif display_type == 'color_picker':
                    container, widget = create_color_picker_widget(param_name, param_def)
                elif display_type == 'triple_range':
                    container, widget = create_triple_range_widget(param_name, param_def)
                    
                if container:
                    blade_layout.addWidget(container, row, 1)
                    
                # Description
                desc_label = QtWidgets.QLabel(param_def.get('description', ''))
                blade_layout.addWidget(desc_label, row, 2)
                
                row += 1
            
            # Add blade profile widget below font settings
            self.param_widget.widget().layout().addWidget(blade_widget)
            
        except Exception as e:
            print(f"Error displaying blade profile: {e}")
            QtWidgets.QMessageBox.warning(self, "Error", f"Failed to display blade profile: {str(e)}")
            
    