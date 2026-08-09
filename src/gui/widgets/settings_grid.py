from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QTableWidgetItem, QHeaderView,
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QHBoxLayout, QCheckBox
)
from PySide6.QtCore import Signal, Qt, QTimer, QPoint
from pathlib import Path
from typing import Optional
import json
import re
from PySide6 import QtWidgets
from gui.widgets.widget_factory import create_blade_profile_dropdown, create_color_profile_dropdown
from core.validators import CFXValidator

# Import widget factory functions
from .widget_factory import (
    create_text_widget,
    create_spinner_widget,
    create_dropdown_widget,
    create_toggle_widget,
    create_range_pair_widget,
    create_color_picker_widget,
    create_triple_range_widget,
    get_widget_value,
    set_widget_value
)

# Highlighting colors used in the parameter grid
SHARED_PARAM_COLOR = "#FFF3B0"   # yellow - value is shared with other soundfonts/profiles
ERROR_PARAM_COLOR = "#FFB3B3"    # red - value fails validation (out of range, malformed, etc.)
SHARED_PARAM_TEXT_COLOR = "#8a6d00"
ERROR_PARAM_TEXT_COLOR = "#B00020"

# Dropdown params whose options are looked up from indexed resource folders on the loaded
# SD card (/extra/grafx, /extra/accents, /extra/pixies) rather than a fixed set of meanings -
# see widget_factory.create_dropdown_widget. A value that doesn't match here means "points to
# a profile number that wasn't found among that folder's contents", not a real type mismatch.
DYNAMIC_FOLDER_DROPDOWN_PARAMS = {
    'style_grafx1', 'style_grafx2', 'style_grafx3', 'style_accents', 'style_pixies'
}

# The RICE schema documents a handful of parameters as a numbered family rather than a single
# name - e.g. bolt<n> for a blaster sound's per-impact timings (bolt0, bolt1, ...), one entry
# per numbered slot rather than a fixed name. parameters.json carries these through verbatim
# as the literal '<n>'-suffixed template name rather than expanding them (there's no fixed
# upper bound to expand to), so a real on-disk name like 'bolt3' has to be resolved back to
# its 'bolt<n>' template.
INDEXED_PARAM_NAME_RE = re.compile(r'^(.*?)(\d+)$')
class SettingsGrid(QWidget):
    def __init__(self, title: str, main_window=None, column_stretches=None, parent=None):
        super().__init__(parent)
        self.title = title
        self.main_window = main_window
        self.column_stretches = column_stretches or [1, 2, 2]
        self.current_settings = {}
        self.param_definitions = {}
        self.category_labels = {}
        self.param_widgets = {}  # param_name -> (widget, display_type), for reading live values back
        self.param_sources = {}  # param_name -> 'font' | 'blade' | 'color' | 'global', which file it saves to
        self.param_containers = {}  # param_name -> (name_container, value_container), for validation highlighting
        self.param_control_widgets = {}  # param_name -> raw input widget(s), so tooltips reach what's under the cursor
        self.static_param_errors = {}  # param_name -> message, computed once when the grid is built
        self.param_errors = {}  # static_param_errors + live cross-parameter rule violations
        self.shared_parameters = set()
        self.shared_with = None
        self.category_params = {}  # category -> [(param_name, value), ...], for the error banner
        self.category_header_layouts = {}  # category -> QHBoxLayout, so the error banner can be added/removed live
        self.category_error_banner_labels = {}  # category -> QLabel currently shown, or absent
        self.unknown_params = []  # [(param_name, value), ...] not found in parameters.json
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
    
    def update_settings(self, settings: dict, shared_with: list = None, shared_parameters: set = None, param_sources: dict = None):
        """Update displayed settings."""
        # Debug color lookups
        self.color_debug_check()

        # Clear existing settings and category labels
        self.category_labels.clear()
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item.widget():
                item.widget().deleteLater()

        # Snapshot of loaded values (source of truth for any param whose widget failed to build)
        # and which file each param belongs to, so Save can route values to the right file.
        self.current_settings = settings.copy()
        self.param_sources = param_sources or {}
        self.param_widgets = {}
        self.param_containers = {}
        self.param_control_widgets = {}
        self.static_param_errors = {}
        self.param_errors = {}
        self.category_params = {}
        self.category_header_layouts = {}
        self.category_error_banner_labels = {}

        # Initialize shared parameters if not provided
        shared_parameters = shared_parameters or set()
        self.shared_parameters = shared_parameters
        self.shared_with = shared_with
        
        # Extract start_blade and start_color separately
        profiles_params = {}
        if 'start_blade' in settings:
            profiles_params['start_blade'] = settings['start_blade']
        if 'start_color' in settings:
            profiles_params['start_color'] = settings['start_color']
        
        # Group other parameters by category
        categorized_params = {}
        categories = set()
        # Parameter names found in the loaded files that aren't in parameters.json. Usually a
        # typo or corruption in a hand-edited config/Special.txt file, but parameters.json -
        # generated from the RICE schema export - isn't guaranteed complete either (e.g.
        # ls1_timings/ls2_timings are documented master config.txt parameters RICE itself
        # doesn't list), so this isn't proof the name is invalid. Tracked instead of silently
        # dropped so the user can actually see it and judge which case it is.
        self.unknown_params = []

        for param_name, value in settings.items():
            # Skip profile params as they'll be shown at the top
            if param_name in ['start_blade', 'start_color']:
                continue

            param_def = self._lookup_param_def(param_name)
            if param_def is None:
                print(f"Parameter not in JSON: {param_name}")
                self.unknown_params.append((param_name, value))
                continue

            category = param_def.get('parameter_category', 'Uncategorized')
            categories.add(category)

            if category not in categorized_params:
                categorized_params[category] = []
            categorized_params[category].append((param_name, value))

        if self.unknown_params:
            categories.add("Unrecognized Parameters")

        # Update dropdown with categories (alphabetically sorted)
        if self.main_window and hasattr(self.main_window, 'category_dropdown'):
            self.main_window.category_dropdown.blockSignals(True)  # Block signals temporarily
            self.main_window.category_dropdown.clear()
            
            # First add a placeholder item if needed
            if len(categories) > 1:  # Only add if we have multiple categories
                self.main_window.category_dropdown.addItem("Jump to section...")
                
            # Add all categories alphabetically
            for category in sorted(categories):
                self.main_window.category_dropdown.addItem(category)
                
            self.main_window.category_dropdown.blockSignals(False)  # Unblock signals

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

                        # Set value based on widget type. Only remember the widget for saving
                        # later (param_widgets) if we could faithfully load the value into it -
                        # otherwise the parameter's declared display_type doesn't match what's
                        # actually stored on disk, and reading a default back out on save would
                        # silently corrupt it.
                        value_applied = False
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
                                value_applied = True

                                # Store original value for change detection
                                if param_name in ['start_blade', 'start_color']:
                                    clean_value = value.split(" ")[0] if " " in value else value
                                    widget.setProperty("original_value", str(clean_value))
                        else:
                            value_applied = set_widget_value(widget, display_type, value, param_name)

                        self.param_containers[param_name] = (name_container, container)
                        self.param_control_widgets[param_name] = widget

                        if value_applied:
                            self.param_widgets[param_name] = (widget, display_type)
                            range_error = CFXValidator.value_out_of_range(param_def, value)
                            if range_error:
                                self.static_param_errors[param_name] = range_error
                        else:
                            self.static_param_errors[param_name] = self._mismatch_message(
                                param_name, display_type, value)
                            print(f"Value '{value}' doesn't match declared display_type "
                                  f"'{display_type}' for {param_name} - leaving it out of Save")

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
            self.category_params[category] = categorized_params[category]

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
                warning_label.setStyleSheet(f"""
                    color: {SHARED_PARAM_TEXT_COLOR};
                    font-style: italic;
                    padding-left: 20px;
                """)
                header_layout.addWidget(warning_label)

            header_layout.addStretch()
            self.grid_layout.addWidget(header_container, row, 0, 1, 3)

            # Store reference to the category label and header layout (the error banner,
            # if any, gets added/removed from this layout later once validation runs)
            self.category_labels[category] = category_label
            self.category_header_layouts[category] = header_layout
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
                param_def = self._lookup_param_def(param_name)
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
                        category_layout.addWidget(container, param_row, 1)
                        self.param_containers[param_name] = (name_container, container)
                        self.param_control_widgets[param_name] = widget

                        # Set value based on widget type. Only remember the widget for saving
                        # later (param_widgets) if we could faithfully load the value into it -
                        # otherwise the parameter's declared display_type doesn't match what's
                        # actually stored on disk, and reading a default back out on save would
                        # silently corrupt it.
                        if widget is not None:
                            if set_widget_value(widget, display_type, value, param_name):
                                self.param_widgets[param_name] = (widget, display_type)
                                range_error = CFXValidator.value_out_of_range(param_def, value)
                                if range_error:
                                    self.static_param_errors[param_name] = range_error
                            else:
                                self.static_param_errors[param_name] = self._mismatch_message(
                                    param_name, display_type, value)
                                print(f"Value '{value}' doesn't match declared display_type "
                                      f"'{display_type}' for {param_name} - leaving it out of Save")

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

        if self.unknown_params:
            row = self._add_unknown_params_section(row)

        self._connect_cross_param_rules()
        self._revalidate()

    def _add_unknown_params_section(self, row: int) -> int:
        """Render self.unknown_params - parameter names loaded from disk that aren't in
        parameters.json - as a distinct, clearly-flagged section instead of the silent
        drop this used to be. These are read-only here (no schema means no display_type to
        build a real input widget from); the point is visibility, not editing. The raw
        value is preserved as-is in current_settings and will round-trip through Save
        untouched, same as before this section existed."""
        if row > 0:
            separator = QFrame()
            separator.setFrameShape(QFrame.HLine)
            separator.setFrameShadow(QFrame.Sunken)
            separator.setStyleSheet("QFrame { color: #cccccc; }")
            self.grid_layout.addWidget(separator, row, 0, 1, 3)
            row += 1

        header_container = QWidget()
        header_layout = QHBoxLayout(header_container)
        header_layout.setContentsMargins(0, 0, 0, 0)

        header_label = QLabel("Unrecognized Parameters")
        header_label.setStyleSheet(f"""
            font-weight: bold;
            font-size: 14px;
            color: {ERROR_PARAM_TEXT_COLOR};
            padding: 10px 0px 10px 0px;
        """)
        header_layout.addWidget(header_label)

        warning_label = QLabel(
            "Not found in the CFX parameter schema - often a typo or a stray line in a "
            "hand-edited file, but the schema itself isn't guaranteed complete either. "
            "Values are preserved as-is but can't be edited here."
        )
        warning_label.setStyleSheet(f"color: {ERROR_PARAM_TEXT_COLOR}; font-style: italic; padding-left: 20px;")
        header_layout.addWidget(warning_label)
        header_layout.addStretch()

        self.grid_layout.addWidget(header_container, row, 0, 1, 3)
        self.category_labels["Unrecognized Parameters"] = header_label
        row += 1

        section_container = QWidget()
        section_container.setStyleSheet(f"background-color: {ERROR_PARAM_COLOR};")
        section_layout = QGridLayout(section_container)
        section_layout.setContentsMargins(0, 0, 0, 10)
        section_layout.setSpacing(10)
        for col, stretch in enumerate(self.column_stretches):
            section_layout.setColumnStretch(col, stretch)

        for param_row, (param_name, value) in enumerate(sorted(self.unknown_params)):
            name_label = QLabel(param_name)
            name_label.setStyleSheet("font-weight: bold; font-family: monospace; color: black;")
            section_layout.addWidget(name_label, param_row, 0)

            value_label = QLabel(str(value))
            value_label.setStyleSheet(
                "font-family: monospace; color: black; background-color: white; "
                "padding: 2px; border: 1px solid #ccc;"
            )
            value_label.setFixedWidth(300)
            section_layout.addWidget(value_label, param_row, 1)

            tooltip = (f"'{param_name}' isn't in this app's parameter schema - could be a typo, "
                       f"or a parameter the schema doesn't cover yet. Preserved as-is on Save.")
            name_label.setToolTip(tooltip)
            value_label.setToolTip(tooltip)
            self.static_param_errors[param_name] = tooltip

        self.grid_layout.addWidget(section_container, row, 0, 1, 3)
        row += 1
        return row

    def _connect_cross_param_rules(self):
        """Wire up live re-validation: whenever a widget involved in a documented
        cross-parameter rule (see CFXValidator.CROSS_PARAM_RULE_GROUPS) changes, re-check
        that rule and restyle the affected fields - without needing a full grid rebuild."""
        for group in CFXValidator.CROSS_PARAM_RULE_GROUPS:
            for param_name in group:
                if param_name not in self.param_widgets:
                    continue
                widget, _display_type = self.param_widgets[param_name]
                self._connect_change_signal(widget, self._revalidate)

    def _connect_change_signal(self, widget, slot):
        """Connect the appropriate 'value changed' signal for whatever widget type this is."""
        if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.valueChanged.connect(slot)
        elif isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(slot)
        elif isinstance(widget, QCheckBox):
            widget.stateChanged.connect(slot)
        elif isinstance(widget, QLineEdit):
            widget.textChanged.connect(slot)
        elif isinstance(widget, tuple):
            for sub_widget in widget:
                if hasattr(sub_widget, 'valueChanged'):
                    sub_widget.valueChanged.connect(slot)

    def _revalidate(self, *_args):
        """Recompute cross-parameter rule violations against the live widget values, merge
        them with the static (structural/range) errors found when the grid was built, and
        restyle every affected field and category banner accordingly."""
        cross_errors = CFXValidator.check_cross_parameter_rules(self.get_current_settings())
        self.param_errors = {**self.static_param_errors, **cross_errors}

        for param_name, containers in self.param_containers.items():
            self._style_containers(param_name, containers)

        for category in self.category_header_layouts:
            self._update_category_error_banner(category)

    def _style_containers(self, param_name, containers):
        """Apply the error/shared/normal background+tooltip to a param's name and value
        containers. Red wins over yellow: a param that's both invalid and shared with other
        soundfonts is still something that needs fixing first."""
        if param_name in self.param_errors:
            style = f"background-color: {ERROR_PARAM_COLOR};"
            tooltip = self.param_errors[param_name]
        elif param_name in self.shared_parameters and self.shared_with:
            style = f"background-color: {SHARED_PARAM_COLOR};"
            tooltip = "This value is shared with other soundfonts using the same profile"
        else:
            style = ""
            tooltip = ""

        for container in containers:
            container.setStyleSheet(style)
            container.setToolTip(tooltip)

        # A tooltip set on the row container only shows over its own empty margin - the
        # actual spinner/dropdown/checkbox on top of it needs its own tooltip too, or
        # hovering the control itself (the natural thing to do) shows nothing.
        self._apply_tooltip(self.param_control_widgets.get(param_name), tooltip)

    def _apply_tooltip(self, widget, tooltip):
        if widget is None:
            return
        if isinstance(widget, (tuple, list)):
            for sub_widget in widget:
                self._apply_tooltip(sub_widget, tooltip)
        elif isinstance(widget, dict):
            for sub_widget in widget.values():
                self._apply_tooltip(sub_widget, tooltip)
        elif hasattr(widget, 'setToolTip'):
            widget.setToolTip(tooltip)

    def _update_category_error_banner(self, category):
        """Show/hide the 'this category has invalid parameters' banner for one category,
        based on the current self.param_errors. Mirrors the shared-parameters banner, which
        doesn't need this treatment since shared_parameters is known before the grid is built."""
        header_layout = self.category_header_layouts.get(category)
        if header_layout is None:
            return

        params = self.category_params.get(category, [])
        has_error = any(name in self.param_errors for name, _ in params)
        existing_label = self.category_error_banner_labels.get(category)

        if has_error and existing_label is None:
            warning_label = QLabel("Highlighted parameters failed validation - hover for details")
            warning_label.setStyleSheet(f"""
                color: {ERROR_PARAM_TEXT_COLOR};
                font-style: italic;
                font-weight: bold;
                padding-left: 20px;
            """)
            # Insert before the trailing stretch so it stays grouped with the category name
            header_layout.insertWidget(header_layout.count() - 1, warning_label)
            self.category_error_banner_labels[category] = warning_label
        elif not has_error and existing_label is not None:
            existing_label.setParent(None)
            existing_label.deleteLater()
            del self.category_error_banner_labels[category]

    def _mismatch_message(self, param_name, display_type, value):
        """Build the static-error message for a value that couldn't be loaded into its widget."""
        if param_name in DYNAMIC_FOLDER_DROPDOWN_PARAMS:
            return (f"Points to profile {value}, which wasn't found among this SD card's "
                    f"indexed resource folders for {param_name} - either the card wasn't "
                    f"loaded, or that folder is missing. Left out of Save.")
        return (f"Stored value '{value}' doesn't match this parameter's declared type "
                f"('{display_type}') - left out of Save so it won't be overwritten with "
                f"something wrong")

    def _lookup_param_def(self, param_name: str) -> Optional[dict]:
        """Resolve a parameter's schema entry, falling back to a matching '<prefix><n>'
        template (see INDEXED_PARAM_NAME_RE) when there's no literal entry for this specific
        numbered name. Returns None if neither is found."""
        param_def = self.param_definitions.get(param_name)
        if param_def is not None:
            return param_def
        match = INDEXED_PARAM_NAME_RE.match(param_name)
        if match:
            return self.param_definitions.get(match.group(1) + '<n>')
        return None

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
        """Return current settings, reading live values out of the input widgets.
        Falls back to the last-loaded value for any param whose widget couldn't be built."""
        result = self.current_settings.copy()
        for param_name, (widget, display_type) in self.param_widgets.items():
            value = get_widget_value(widget, display_type)
            if value is not None:
                result[param_name] = value
        return result

    def get_settings_split(self) -> dict:
        """Split current settings by which file they belong to, using the provenance
        recorded when they were loaded. Returns {'font': {...}, 'blade': {...}, 'color': {...}, 'global': {...}}."""
        split = {'font': {}, 'blade': {}, 'color': {}, 'global': {}}
        for param_name, value in self.get_current_settings().items():
            source = self.param_sources.get(param_name, 'font')
            split.setdefault(source, {})[param_name] = value
        return split

    def scroll_to_category(self, category: str):
        """Scroll to make the selected category visible"""
        if category in self.category_labels:
            label = self.category_labels[category]
            # Find the scroll area
            current_widget = self
            scroll_area = None
            while current_widget:
                current_widget = current_widget.parent()
                if isinstance(current_widget, QScrollArea):
                    scroll_area = current_widget
                    break
            
            if scroll_area:
                # Get the vertical scroll bar
                scrollbar = scroll_area.verticalScrollBar()
                
                # Calculate position
                pos = label.mapTo(scroll_area.widget(), QPoint(0, 0))
                
                # Set the scroll position
                scrollbar.setValue(pos.y())  
   
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