from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel, 
    QPushButton, QFrame, QScrollArea, QTableWidgetItem, QHeaderView,
    QLineEdit, QSpinBox, QComboBox, QHBoxLayout
)
from PySide6.QtCore import Signal, Qt, QTimer, QPoint
from pathlib import Path
import json
from PySide6 import QtWidgets
from gui.widgets.widget_factory import create_blade_profile_dropdown, create_color_profile_dropdown

# Import widget factory functions
from .widget_factory import (
    create_text_widget,
    create_spinner_widget,
    create_dropdown_widget,
    create_toggle_widget,
    create_range_pair_widget,
    create_color_picker_widget,
    create_triple_range_widget
)
class SettingsGrid(QWidget):
    def __init__(self, title: str, main_window=None, column_stretches=None, parent=None):
        super().__init__(parent)
        self.title = title
        self.main_window = main_window
        self.column_stretches = column_stretches or [1, 2, 2]
        self.current_settings = {}
        self.param_definitions = {}
        self.category_labels = {}
        self.load_parameter_definitions()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        content = QWidget()
        self.grid_layout = QGridLayout(content)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(10)
        
        # Set column stretches to match headers
        for col, stretch in enumerate(self.column_stretches):
            self.grid_layout.setColumnStretch(col, stretch)
            
        layout.addWidget(content)
    
    def color_debug_check(self):
        """Debug function to check all colors in color_profiles against X11_COLORS and STANDARD_COLORS"""
        from core.color_utils import X11_COLORS, STANDARD_COLORS, rgbw_to_rgb
        
        print("\n===== COLOR DEBUG =====")
        
        # Check if standard colors mapping contains color (0,350,1023,0)
        standard_rgbw = (0, 350, 1023, 0)
        if standard_rgbw in STANDARD_COLORS:
            print(f"Color (0,350,1023,0) is a standard color: {STANDARD_COLORS[standard_rgbw]}")
        else:
            print(f"Color (0,350,1023,0) is NOT in standard colors. Available standard colors:")
            for rgbw, name in STANDARD_COLORS.items():
                print(f"  {rgbw} -> {name}")
        
        # Print all color profiles and check against X11 and STANDARD_COLORS
        if self.main_window and hasattr(self.main_window, 'color_profiles'):
            print("\nAll color profiles:")
            for color_num, profile in self.main_window.color_profiles.items():
                color_name = profile.get('color_name', 'unknown')
                print(f"Color {color_num}: name='{color_name}'")
                
                # Check if color name exists in X11_COLORS
                if color_name in X11_COLORS:
                    r, g, b = X11_COLORS[color_name]
                    print(f"  Found in X11_COLORS: rgb({r},{g},{b})")
                else:
                    print(f"  NOT found in X11_COLORS")
                    
                    # Check if the color name is in STANDARD_COLORS values
                    found_in_standard = False
                    for rgbw, std_name in STANDARD_COLORS.items():
                        if std_name == color_name:
                            r, g, b = rgbw_to_rgb(*rgbw)
                            print(f"  Found in STANDARD_COLORS: rgbw={rgbw} -> rgb({r},{g},{b})")
                            found_in_standard = True
                            break
                    
                    if not found_in_standard:
                        print(f"  NOT found in STANDARD_COLORS either")
        
        print("===== END COLOR DEBUG =====\n")
    
    def update_settings(self, settings: dict, shared_with: list = None, shared_parameters: set = None):
        """Update displayed settings."""
        # Debug color lookups
        self.color_debug_check()
    
        # Clear existing settings and category labels
        self.category_labels.clear()
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item.widget():
                item.widget().deleteLater()

        # Initialize shared parameters if not provided
        shared_parameters = shared_parameters or set()
        
        # Extract start_blade and start_color separately
        profiles_params = {}
        if 'start_blade' in settings:
            profiles_params['start_blade'] = settings['start_blade']
        if 'start_color' in settings:
            profiles_params['start_color'] = settings['start_color']
        
        # Group other parameters by category
        categorized_params = {}
        categories = set()
        
        for param_name, value in settings.items():
            # Skip profile params as they'll be shown at the top
            if param_name in ['start_blade', 'start_color']:
                continue
                
            if param_name not in self.param_definitions:
                print(f"Parameter not in JSON: {param_name}")
                continue
            
            param_def = self.param_definitions[param_name]
            category = param_def.get('parameter_category', 'Uncategorized')
            categories.add(category)
            
            if category not in categorized_params:
                categorized_params[category] = []
            categorized_params[category].append((param_name, value))

        # Update dropdown with categories (alphabetically sorted)
        if self.main_window and hasattr(self.main_window, 'category_dropdown'):
            self.main_window.category_dropdown.clear()
            self.main_window.category_dropdown.addItems(sorted(categories))

        row = 0

        # Add profile params at the top if they exist
        if profiles_params:
            # Add "Blade and Color Profiles" header
            profiles_header = QLabel("Blade and Color Profiles")
            profiles_header.setStyleSheet("""
                font-weight: bold;
                font-size: 14px;
                color: #4A90E2;
                padding: 10px 0px 10px 0px;
            """)
            self.grid_layout.addWidget(profiles_header, row, 0, 1, 3)
            self.category_labels["Blade and Color Profiles"] = profiles_header
            row += 1
            
            # Create container for profile parameters
            profiles_container = QWidget()
            profiles_container.setStyleSheet("background-color: #f0f8ff;")  # Light blue background
            profiles_layout = QGridLayout(profiles_container)
            profiles_layout.setContentsMargins(0, 0, 0, 10)
            profiles_layout.setSpacing(10)
            
            # Set column stretches
            for col, stretch in enumerate(self.column_stretches):
                profiles_layout.setColumnStretch(col, stretch)
            
            # Add start_blade and start_color parameters
            param_row = 0
            for param_name, value in profiles_params.items():
                # Get parameter definition from JSON
                param_def = self.param_definitions.get(param_name, {})
                display_type = param_def.get('display_type', 'text')

                # Create parameter name container
                name_container = QWidget()
                name_layout = QVBoxLayout(name_container)
                name_layout.setContentsMargins(0, 4, 4, 4)
                name_layout.setSpacing(2)

                name_label = QLabel(param_name)
                name_label.setStyleSheet("font-weight: bold; font-family: monospace; color: black;")
                name_layout.addWidget(name_label)

                if 'description' in param_def:
                    desc_label = QLabel(f"({param_def['description']})")
                    desc_label.setStyleSheet("font-style: italic; color: #666666; font-size: 11px;")
                    desc_label.setWordWrap(True)
                    name_layout.addWidget(desc_label)

                profiles_layout.addWidget(name_container, param_row, 0)

                # Create appropriate widget based on display_type
                try:
                    container = None  # Initialize container to None
                    widget = None     # Initialize widget to None
                    if param_name == 'start_blade':
                        container, widget = create_blade_profile_dropdown(param_name, param_def, self.main_window)
                    elif param_name == 'start_color':
                        container, widget = create_color_profile_dropdown(param_name, param_def, self.main_window)
                    elif display_type == 'text_input':
                        container, widget = create_text_widget(param_name, param_def)
                    elif display_type == 'spinner':
                        container, widget = create_spinner_widget(param_name, param_def)
                    elif display_type == 'dropdown':
                        container, widget = create_dropdown_widget(param_name, param_def, self.main_window)
                    elif display_type == 'toggle':
                        container, widget = create_toggle_widget(param_name, param_def)
                    elif display_type == 'range_pair':
                        container, widget = create_range_pair_widget(param_name, param_def)
                    elif display_type == 'color_picker':
                        container, widget = create_color_picker_widget(param_name, param_def)
                    elif display_type == 'triple_range':
                        container, widget = create_triple_range_widget(param_name, param_def)
                    else:
                        # Fallback for unknown display types
                        container, widget = create_text_widget(param_name, param_def)

                    if container:
                        container.setFixedWidth(300)
                        
                        # Set value based on widget type
                        if isinstance(widget, QComboBox):
                            # For start_blade and start_color, extract just the number part
                            if param_name in ['start_blade', 'start_color']:
                                # Remove any "(from prefs)" suffix
                                clean_value = value.split(" ")[0] if " " in value else value
                                index = widget.findData(str(clean_value))
                            else:
                                index = widget.findData(str(value))
                                
                            if index >= 0:
                                # Block signals during initial setup
                                widget.blockSignals(True)
                                widget.setCurrentIndex(index)
                                widget.blockSignals(False)
                                
                                # Store original value for change detection
                                if param_name in ['start_blade', 'start_color']:
                                    clean_value = value.split(" ")[0] if " " in value else value
                                    widget.setProperty("original_value", str(clean_value))
                                    
                        if isinstance(widget, QLineEdit):
                            widget.setText(str(value))
                        elif isinstance(widget, QSpinBox):
                            try:
                                # Try to convert to int - this might fail for decimal values
                                widget.setValue(int(value))
                            except ValueError:
                                # For decimal values, try to convert to float and round
                                try:
                                    widget.setValue(round(float(value)))
                                except ValueError:
                                    # Just set text if all else fails
                                    if hasattr(widget, 'setText'):
                                        widget.setText(str(value))
                        elif isinstance(widget, QComboBox):
                            index = widget.findData(str(value))
                            if index >= 0:
                                widget.setCurrentIndex(index)
                        elif isinstance(widget, tuple):
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

                        # Add color preview for start_color parameter
                        if param_name == 'start_color':
                            try:
                                color_value = value.split(" ")[0] if " " in value else value
                                color_num = int(color_value)
                                
                                if color_num >= 0 and color_num <= 31:
                                    if self.main_window and hasattr(self.main_window, 'color_profiles'):
                                        color_profile = self.main_window.color_profiles.get(color_num, {})
                                        
                                        if 'color_name' in color_profile:
                                            color_name = color_profile['color_name']
                                            
                                            # Import X11_COLORS and STANDARD_COLORS from color_utils
                                            from core.color_utils import X11_COLORS, STANDARD_COLORS, rgbw_to_rgb
                                            
                                            # Try to get RGB values from X11_COLORS
                                            if color_name in X11_COLORS:
                                                r, g, b = X11_COLORS[color_name]
                                            else:
                                                # If not in X11_COLORS, check if we have RGBW values for this color
                                                # in the STANDARD_COLORS mapping
                                                rgbw_values = None
                                                for rgbw, name in STANDARD_COLORS.items():
                                                    if name == color_name:
                                                        rgbw_values = rgbw
                                                        break
                                                
                                                if rgbw_values:
                                                    # Convert RGBW to RGB
                                                    r, g, b = rgbw_to_rgb(*rgbw_values)
                                                else:
                                                    # Fallback to a light blue color
                                                    r, g, b = 173, 216, 230  # Light blue
                                            
                                            # Create color preview
                                            color_preview = QFrame()
                                            color_preview.setFixedSize(20, 20)
                                            color_preview.setFrameShape(QFrame.Box)
                                            color_preview.setFrameShadow(QFrame.Plain)
                                            
                                            # Set background color
                                            color_preview.setStyleSheet(f"background-color: rgb({r}, {g}, {b}); border: 1px solid black;")
                                            
                                            # Create a sub-layout for the color display
                                            color_layout = QHBoxLayout()
                                            color_layout.setContentsMargins(0, 0, 0, 0)
                                            color_layout.addWidget(container)
                                            color_layout.addWidget(color_preview)
                                            color_layout.addStretch()
                                            
                                            # Create container for color with preview
                                            color_container = QWidget()
                                            color_container.setLayout(color_layout)
                                            
                                            # Add to profiles layout
                                            profiles_layout.addWidget(color_container, param_row, 1)
                                            # Skip the normal container add
                                            continue
                            except Exception as e:
                                print(f"Error creating color preview: {e}")
                        
                        # Normal container add if not start_color or if color preview failed
                        profiles_layout.addWidget(container, param_row, 1)

                        # Add notes if available
                        if 'notes' in param_def:
                            notes_label = QLabel(param_def['notes'])
                            notes_label.setStyleSheet("font-style: italic; color: #666666; font-size: 11px;")
                            notes_label.setWordWrap(True)
                            notes_label.setFixedWidth(300)
                            profiles_layout.addWidget(notes_label, param_row, 2)
                        
                except Exception as e:
                    print(f"Error creating widget for {param_name}: {e}")
                    value_label = QLabel(str(value))
                    value_label.setStyleSheet("font-family: monospace; color: black; background-color: white; padding: 2px; border: 1px solid #ccc;")
                    value_label.setFixedWidth(300)
                    profiles_layout.addWidget(value_label, param_row, 1)
                    
                param_row += 1
                
            # Add the profiles container to the main grid
            self.grid_layout.addWidget(profiles_container, row, 0, 1, 3)
            row += 1
            
            # Add separator after profiles section
            separator = QFrame()
            separator.setFrameShape(QFrame.HLine)
            separator.setFrameShadow(QFrame.Sunken)
            separator.setStyleSheet("QFrame { color: #cccccc; }")
            self.grid_layout.addWidget(separator, row, 0, 1, 3)
            row += 1

        # Process regular categories
        for index, category in enumerate(sorted(categorized_params.keys())):
            # Check if this category has any shared parameters
            category_has_shared_params = any(param_name in shared_parameters 
                                        for param_name, _ in categorized_params[category])
            
            # Add separator before each category (except the first one after profiles)
            if row > 0 and (profiles_params or index > 0):
                separator = QFrame()
                separator.setFrameShape(QFrame.HLine)
                separator.setFrameShadow(QFrame.Sunken)
                separator.setStyleSheet("QFrame { color: #cccccc; }")
                self.grid_layout.addWidget(separator, row, 0, 1, 3)
                row += 1

            # Category header with enhanced styling
            header_container = QWidget()
            header_layout = QHBoxLayout(header_container)
            header_layout.setContentsMargins(0, 0, 0, 0)
            
            category_label = QLabel(category)
            category_label.setStyleSheet("""
                font-weight: bold;
                font-size: 14px;
                color: #4A90E2;
                padding: 10px 0px 10px 0px;
            """)
            header_layout.addWidget(category_label)
            
            # Add warning label if category has shared parameters
            if category_has_shared_params and shared_with:
                warning_label = QLabel("Highlighted parameters are used by multiple soundfonts")
                warning_label.setStyleSheet("""
                    color: #FF0000;
                    font-style: italic;
                    padding-left: 20px;
                """)
                header_layout.addWidget(warning_label)
            
            header_layout.addStretch()
            self.grid_layout.addWidget(header_container, row, 0, 1, 3)
            
            # Store reference to the category label
            self.category_labels[category] = category_label
            row += 1

            # Create container for this category's parameters with alternating background
            category_container = QWidget()
            bg_color = "#f8f9fa" if index % 2 == 0 else "#ffffff"
            category_container.setStyleSheet(f"background-color: {bg_color};")
            category_layout = QGridLayout(category_container)
            category_layout.setContentsMargins(0, 0, 0, 10)
            category_layout.setSpacing(10)
            
            # Set column stretches to match headers
            for col, stretch in enumerate(self.column_stretches):
                category_layout.setColumnStretch(col, stretch)

            # Sort and add parameters for this category
            param_row = 0
            sorted_params = sorted(categorized_params[category], key=lambda x: x[0])
            
            for param_name, value in sorted_params:
                param_def = self.param_definitions[param_name]
                display_type = param_def.get('display_type', 'text')

                # Create a container for parameter name and description
                name_container = QWidget()
                name_layout = QVBoxLayout(name_container)
                name_layout.setContentsMargins(0, 4, 4, 4)
                name_layout.setSpacing(2)

                # Parameter name in bold
                name_label = QLabel(param_name)
                name_label.setStyleSheet("font-weight: bold; font-family: monospace; color: black;")
                name_layout.addWidget(name_label)

                # Description in italics and parentheses
                if 'description' in param_def:
                    desc_label = QLabel(f"({param_def['description']})")
                    desc_label.setStyleSheet("font-style: italic; color: #666666; font-size: 11px;")
                    desc_label.setWordWrap(True)
                    name_layout.addWidget(desc_label)

                # Highlight shared parameters
                if param_name in shared_parameters and shared_with:
                    name_container.setStyleSheet("background-color: #FFE0E0;")  # Light red background

                category_layout.addWidget(name_container, param_row, 0)

                # Create appropriate widget based on display_type
                try:
                    container = None  # Initialize container
                    widget = None     # Initialize widget
                    
                    if display_type == 'text_input':
                        container, widget = create_text_widget(param_name, param_def)
                    elif display_type == 'spinner':
                        container, widget = create_spinner_widget(param_name, param_def)
                    elif display_type == 'dropdown':
                        container, widget = create_dropdown_widget(param_name, param_def, self.main_window)
                    elif display_type == 'toggle':
                        container, widget = create_toggle_widget(param_name, param_def)
                    elif display_type == 'range_pair':
                        container, widget = create_range_pair_widget(param_name, param_def)
                    elif display_type == 'color_picker':
                        container, widget = create_color_picker_widget(param_name, param_def)
                    elif display_type == 'triple_range':
                        container, widget = create_triple_range_widget(param_name, param_def)
                    else:
                        # Fallback for unknown display types
                        container, widget = create_text_widget(param_name, param_def)

                    if container:
                        container.setFixedWidth(300)
                        
                        # Highlight shared parameters
                        if param_name in shared_parameters and shared_with:
                            container.setStyleSheet("background-color: #FFE0E0;")  # Light red background
                            
                        category_layout.addWidget(container, param_row, 1)
                        
                        # Set value based on widget type
                        if isinstance(widget, QLineEdit):
                            widget.setText(str(value))
                        elif isinstance(widget, QSpinBox):
                            try:
                                # Try to convert to int - this might fail for decimal values
                                widget.setValue(int(value))
                            except ValueError:
                                # For decimal values, try to convert to float and round
                                try:
                                    widget.setValue(round(float(value)))
                                except ValueError:
                                    # Just set text if all else fails
                                    if hasattr(widget, 'setText'):
                                        widget.setText(str(value))
                        elif isinstance(widget, QComboBox):
                            index = widget.findData(str(value))
                            if index >= 0:
                                widget.setCurrentIndex(index)
                        elif isinstance(widget, tuple):
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

                    # Add notes if available
                    if 'notes' in param_def:
                        notes_label = QLabel(param_def['notes'])
                        notes_label.setStyleSheet("font-style: italic; color: #666666; font-size: 11px;")
                        notes_label.setWordWrap(True)
                        notes_label.setFixedWidth(300)
                        category_layout.addWidget(notes_label, param_row, 2)

                except Exception as e:
                    print(f"Error creating widget for {param_name}: {e}")
                    value_label = QLabel(str(value))
                    value_label.setStyleSheet("font-family: monospace; color: black; background-color: white; padding: 2px; border: 1px solid #ccc;")
                    value_label.setFixedWidth(300)
                    category_layout.addWidget(value_label, param_row, 1)

                param_row += 1

            # Add the category container to the main grid
            self.grid_layout.addWidget(category_container, row, 0, 1, 3)
            row += 1
     
    def load_parameter_definitions(self):
        """Load parameter definitions from JSON file."""
        try:
            params_file = Path(__file__).parent.parent.parent / 'config' / 'parameters.json'
            print(f"\nTrying to load parameters from: {params_file}")
            with open(params_file, 'r') as f:
                self.param_definitions = json.load(f)
                print(f"Number of parameter definitions loaded: {len(self.param_definitions)}")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error loading parameter definitions: {e}")
            self.param_definitions = {}
                        
    def get_current_settings(self) -> dict:
        """Return current settings."""
        return self.current_settings.copy()

    def scroll_to_category(self, category: str):
        """Scroll to make the selected category visible"""
        # print(f"Attempting to scroll to category: {category}")  # Debug
        if category in self.category_labels:
            label = self.category_labels[category]
            # print(f"Found label for category")  # Debug
            
            # Find the scroll area by traversing up the parent hierarchy
            current_widget = self
            scroll_area = None
            while current_widget:
                current_widget = current_widget.parent()
                if isinstance(current_widget, QScrollArea):
                    scroll_area = current_widget
                    break
            
            # print(f"Found scroll area: {scroll_area}")  # Debug
            
            if scroll_area:
                # Get the vertical scroll bar
                scrollbar = scroll_area.verticalScrollBar()
                # print(f"Scrollbar range: {scrollbar.minimum()} to {scrollbar.maximum()}")  # Debug
                
                # Calculate position
                pos = label.mapToParent(QPoint(0, 0))
                # print(f"Calculated position: {pos.y()}")  # Debug
                
                # Set the scroll position
                scrollbar.setValue(pos.y())
                # print(f"Set scrollbar value to: {pos.y()}")  # Debug
            
    def filter_settings(self, search_text: str):
        """Filter settings based on search text"""
        if not hasattr(self, 'original_settings'):
            self.original_settings = self.current_settings.copy()

        if not search_text.strip():
            self.update_settings(self.original_settings)
            return

        search_text = search_text.lower()
        filtered_settings = {}
        
        for param_name, value in self.original_settings.items():
            if search_text in param_name.lower():
                filtered_settings[param_name] = value
                continue
                
            desc = self.param_definitions.get(param_name, {}).get('description', '').lower()
            if search_text in desc:
                filtered_settings[param_name] = value
                continue
                
            if 'values' in self.param_definitions.get(param_name, {}):
                values_desc = ' '.join(str(v) for v in self.param_definitions[param_name]['values'].values()).lower()
                if search_text in values_desc:
                    filtered_settings[param_name] = value
                    continue

        self.update_settings(filtered_settings)