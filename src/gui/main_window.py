# src/gui/main_window.py
from core.color_utils import interpret_color, load_color_profiles, load_grafx_profiles
from PySide6 import QtWidgets, QtCore, QtGui
from pathlib import Path
from os import sys
from .widgets.settings_grid import SettingsGrid
import core.color_utils as color_utils

class FontListWidget(QtWidgets.QWidget):
    font_selected = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.list_widget = QtWidgets.QListWidget()  # Create list_widget first
        self.init_ui()

    def init_ui(self):
        # Single layout for the whole widget
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)  # Remove all margins
        layout.setSpacing(0)  # Remove spacing between widgets
        
        # Add the list widget directly - no additional containers
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.list_widget.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        
        # Add title to the list widget instead of as separate widget
        self.list_widget.addItem("Sound Fonts")
        self.list_widget.item(0).setFlags(QtCore.Qt.NoItemFlags)  # Make title non-selectable
        self.list_widget.item(0).setBackground(QtGui.QColor("#f0f0f0"))
        self.list_widget.item(0).setFont(QtGui.QFont("", -1, QtGui.QFont.Bold))
        
        layout.addWidget(self.list_widget)

    def _on_item_clicked(self, item):
        if item:
            folder_path = item.data(QtCore.Qt.UserRole)
            print(f"DEBUG: Font selected: {folder_path}")
            self.font_selected.emit(folder_path)

    def load_fonts(self, folder_path):
        try:
            print("Loading fonts...")
            self.list_widget.clear()
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
                self.list_widget.addItem(list_item)
        except Exception as e:
            print(f"Error loading fonts: {e}")
            QtWidgets.QMessageBox.warning(None, "Error", f"Failed to load fonts: {str(e)}")
    
    def get_selected_font(self) -> Path:
        """Return the currently selected font folder path."""
        current = self.list_widget.currentItem()
        if current:
            return Path(current.data(QtCore.Qt.UserRole))
        return None
    

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.folder_path = None
        self.color_profiles = {}  # Initialize here
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("CFX Settings Manager")
        self.setMinimumSize(1024, 768)

        # Create central widget and main layout
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QVBoxLayout(central_widget)

        # Add search bar at top
        search_widget = QtWidgets.QWidget()
        search_layout = QtWidgets.QHBoxLayout(search_widget)
        search_layout.setContentsMargins(0, 0, 0, 0)
        
        right_side_search = QtWidgets.QWidget()
        right_search_layout = QtWidgets.QHBoxLayout(right_side_search)
        right_search_layout.setContentsMargins(0, 0, 0, 0)
        
        search_label = QtWidgets.QLabel("Search:")
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Search parameters and descriptions...")
        self.search_input.textChanged.connect(self.on_search)
        
        right_search_layout.addWidget(search_label)
        right_search_layout.addWidget(self.search_input)
        
        search_layout.addWidget(QtWidgets.QWidget(), 1)  # Placeholder with stretch 1
        search_layout.addWidget(right_side_search, 2)    # Search with stretch 2
        
        main_layout.addWidget(search_widget)

        # Content area
        content_widget = QtWidgets.QWidget()
        content_layout = QtWidgets.QHBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # Left panel
        left_panel = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # Font list
        self.font_list = FontListWidget()
        self.font_list.font_selected.connect(self.on_font_selected)
        left_layout.addWidget(self.font_list)
        
        # Select button
        select_button = QtWidgets.QPushButton("Select Folder")
        select_button.clicked.connect(self.select_folder)
        left_layout.addWidget(select_button)
        
        content_layout.addWidget(left_panel)

        # Right panel
        right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        
        # Font config grid - now passing main_window reference
        self.font_config_grid = SettingsGrid("Font Configuration", main_window=self)
        right_layout.addWidget(self.font_config_grid)
        
        # Blade profile grid - now passing main_window reference
        self.blade_profile_grid = SettingsGrid("Blade Profile Settings", main_window=self)
        right_layout.addWidget(self.blade_profile_grid)
        
        # Save and Donate buttons
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.setAlignment(QtCore.Qt.AlignCenter)

        save_button = QtWidgets.QPushButton("Save Changes")
        save_button.clicked.connect(self.save_changes)
        save_button.setFixedWidth(200)

        donate_button = QtWidgets.QPushButton("Donate")
        donate_button.setFixedWidth(200)
        donate_button.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 5px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:pressed {
                background-color: #1565C0;
            }
        """)
        # IMPLEMENT NEXT: donate_button.clicked.connect(self.on_donate_clicked)

        button_layout.addWidget(save_button)
        button_layout.addWidget(donate_button)
        right_layout.addLayout(button_layout)
        
        content_layout.addWidget(right_panel)

        # Add content widget to main layout
        main_layout.addWidget(content_widget)

        # Set stretch factors
        content_layout.setStretch(0, 1)  # Left panel
        content_layout.setStretch(1, 2)  # Right panel

    def on_search(self, text):
        """Handle search text changes"""
        # Apply filter to both grids
        self.font_config_grid.filter_settings(text)
        self.blade_profile_grid.filter_settings(text)

    def on_font_selected(self, folder_path):
        try:
            path = Path(folder_path)
            print("\nDEBUG: Loading font settings from:", path)
            
            # Load font config
            config_path = path / "font_config.txt"
            print(f'DEBUG: Config_path: {config_path}')
            if config_path.exists():
                settings = self.load_settings_file(config_path)
                self.font_config_grid.update_settings(settings)
                
                # Load associated blade profile
                if 'start_blade' in settings:
                    blade_profile = self.load_blade_profile(settings['start_blade'])
                    if blade_profile:
                        self.blade_profile_grid.update_settings(blade_profile)
        except Exception as e:
            print(f"Error loading settings: {e}")
            QtWidgets.QMessageBox.warning(self, "Error", f"Failed to load settings: {str(e)}")

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
    
    def select_folder(self):
        try:
            folder = QtWidgets.QFileDialog.getExistingDirectory(
                self,
                "Select CFX Root Folder"
            )
            
            if folder:
                self.folder_path = folder
                
                self.grafx_profiles = color_utils.load_grafx_profiles(Path(folder))
                
                # Load color profiles
                self.color_profiles = color_utils.load_color_profiles(Path(folder))
                self.font_list.load_fonts(folder)
                
        except Exception as e:
            print(f"Error selecting folder: {e}")
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

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

    def save_changes(self):
        try:
            # Get current font
            current_font = self.font_list.get_selected_font()
            if not current_font:
                raise Exception("No font selected")
                
            response = QtWidgets.QMessageBox.question(
                self,
                "Save Changes",
                "Are you sure you want to save these changes?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            )
            
            if response == QtWidgets.QMessageBox.Yes:
                # Save font config
                font_settings = self.font_config_grid.get_current_settings()
                self.save_font_config(current_font, font_settings)
                
                # Save blade profile if we have one
                if 'start_blade' in font_settings:
                    profile_num = int(font_settings['start_blade'])
                    blade_settings = self.blade_profile_grid.get_current_settings()
                    self.save_blade_profile(profile_num, blade_settings)
                
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

    def save_font_config(self, font_path: Path, settings: dict):
        """Save font configuration while preserving file format and comments."""
        try:
            # Read existing file to preserve comments and format
            with open(font_path / "font_config.txt", 'r') as f:
                lines = f.readlines()
                
            # Update values while preserving structure
            new_lines = []
            for line in lines:
                line = line.strip()
                if line and not line.startswith('//') and not line.startswith('#'):
                    if '=' in line:
                        key = line.split('=')[0].strip()
                        if key in settings:
                            line = f"{key}={settings[key]}"
                new_lines.append(line + '\n')
                
            # Write back to file
            with open(font_path / "font_config.txt", 'w') as f:
                f.writelines(new_lines)
                
        except Exception as e:
            raise Exception(f"Failed to save font config: {str(e)}")
        
    def save_blade_profile(self, profile_num: int, settings: dict):
        """Save blade profile while preserving file format and comments."""
        try:
            config_path = Path(self.folder_path) / "config.txt"
            
            # Read existing file
            with open(config_path, 'r') as f:
                lines = f.readlines()
                
            # Update profile values while preserving structure
            new_lines = []
            in_target_profile = False
            for line in lines:
                original_line = line
                line = line.strip()
                
                if line.startswith('[profile='):
                    current_profile = int(line[9:-1])
                    in_target_profile = (current_profile == profile_num)
                    
                if in_target_profile and '=' in line and not line.startswith('//'):
                    key = line.split('=')[0].strip()
                    if key in settings:
                        line = f"{key}={settings[key]}"
                        original_line = line + '\n'
                        
                new_lines.append(original_line)
                
            # Write back to file
            with open(config_path, 'w') as f:
                f.writelines(new_lines)
                
        except Exception as e:
            raise Exception(f"Failed to save blade profile: {str(e)}")