# src/gui/widgets/widget_factory.py
from typing import Tuple
from PySide6 import QtWidgets, QtCore
from PySide6.QtWidgets import QWidget

# range_pair params whose two values are independent quantities, not a min/max range - e.g.
# lbolt is (distance from bottom, distance from top), which has no reason to be ordered.
# Confirmed against the manual's parameter descriptions: every other range_pair param
# explicitly documents "min and max"/"low and high"/"lower and upper" semantics; lbolt
# doesn't, and neither do mapping_move/mapping_audio ("range used for mapping X to the fx") -
# for those a reversed pair inverts the mapping curve rather than being invalid data.
UNORDERED_RANGE_PAIR_PARAMS = {'lbolt', 'mapping_move', 'mapping_audio'}

def set_widget_value(widget, display_type, value, param_name=None) -> bool:
    """Push a loaded value into a widget created by this module.

    Returns True if the value was applied faithfully (safe to read back and save later),
    False if it couldn't be represented by this widget - typically because the parameter's
    declared display_type in parameters.json doesn't match the format actually stored on
    disk (e.g. a 'spinner' param whose value is really a comma pair). In that case the
    widget is left at its default and must NOT be trusted as the source of truth on save,
    or the mismatch would silently overwrite the real value with the widget's default.
    """
    if isinstance(widget, QtWidgets.QLineEdit):
        widget.setText(str(value))
        return True
    if isinstance(widget, QtWidgets.QDoubleSpinBox):
        try:
            widget.setValue(float(value))
            return True
        except (TypeError, ValueError):
            return False
    if isinstance(widget, QtWidgets.QSpinBox):
        try:
            widget.setValue(int(value))
            return True
        except (TypeError, ValueError):
            try:
                widget.setValue(round(float(value)))
                return True
            except (TypeError, ValueError):
                return False
    if isinstance(widget, QtWidgets.QComboBox):
        index = widget.findData(str(value))
        if index >= 0:
            widget.setCurrentIndex(index)
            return True
        return False
    if isinstance(widget, QtWidgets.QCheckBox):
        text = str(value).strip()
        if text not in ('0', '1'):
            return False
        widget.setChecked(text == '1')
        return True
    if isinstance(widget, tuple):
        try:
            if display_type == 'range_pair':
                min_val, max_val = map(int, str(value).split(','))
                if min_val > max_val and param_name not in UNORDERED_RANGE_PAIR_PARAMS:
                    return False  # malformed on disk - min > max isn't representable, leave it out of Save
                widget[0].setValue(min_val)
                widget[1].setValue(max_val)
                return True
            if display_type == 'triple_range':
                first_val, min_val, max_val = map(int, str(value).split(','))
                if min_val > max_val:
                    return False
                widget[0].setValue(first_val)
                widget[1].setValue(min_val)
                widget[2].setValue(max_val)
                return True
            if display_type == 'color_picker':
                r, g, b, w = map(int, str(value).split(','))
                widget[0]['R'][1].setValue(r)
                widget[0]['G'][1].setValue(g)
                widget[0]['B'][1].setValue(b)
                widget[0]['W'][1].setValue(w)
                return True
        except (TypeError, ValueError):
            return False
    return False

def get_widget_value(widget, display_type):
    """Read the live value back out of a widget created by this module, formatted the same
    way the CFX config files expect (matches the comma-joined formats used when loading)."""
    if isinstance(widget, QtWidgets.QComboBox):
        return widget.currentData()
    if isinstance(widget, QtWidgets.QLineEdit):
        return widget.text()
    if isinstance(widget, QtWidgets.QDoubleSpinBox):
        return str(round(widget.value(), 2))
    if isinstance(widget, QtWidgets.QSpinBox):
        return str(widget.value())
    if isinstance(widget, QtWidgets.QCheckBox):
        return "1" if widget.isChecked() else "0"
    if isinstance(widget, tuple):
        if display_type == 'range_pair':
            min_spin, max_spin = widget
            return f"{min_spin.value()},{max_spin.value()}"
        if display_type == 'triple_range':
            first_spin, min_spin, max_spin = widget
            return f"{first_spin.value()},{min_spin.value()},{max_spin.value()}"
        if display_type == 'color_picker':
            color_inputs, _preview = widget
            r = color_inputs['R'][1].value()
            g = color_inputs['G'][1].value()
            b = color_inputs['B'][1].value()
            w = color_inputs['W'][1].value()
            return f"{r},{g},{b},{w}"
    return None

def create_parameter_widget(param_name: str, param_def: dict, current_value: str = None) -> Tuple[QWidget, QWidget]:
    """
    Create a widget group for any parameter based on its definition
    
    Args:
        param_name: Name of the parameter
        param_def: Parameter definition dictionary from parameters.json
        current_value: Current value of the parameter (optional)
    
    Returns:
        Tuple of (container widget, input widget)
    """
    display_type = param_def.get('display_type')
    
    if display_type == 'dropdown':
        return create_dropdown_widget(param_name, param_def)
    elif display_type == 'spinner':
        return create_spinner_widget(param_name, param_def)
    elif display_type == 'toggle':
        return create_toggle_widget(param_name, param_def)
    elif display_type == 'range_pair':
        return create_range_pair_widget(param_name, param_def)
    elif display_type == 'triple_range':
        return create_triple_range_widget(param_name, param_def)
    elif display_type == 'color_picker':
        return create_color_picker_widget(param_name, param_def)
    elif display_type == 'text_input':
        return create_text_widget(param_name, param_def)
    else:
        raise ValueError(f"Unknown display type: {display_type} for parameter {param_name}")

def create_spinner_widget(param_name, param_def):
    """Create a spinner widget from parameter definition"""
    container = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(container)

    # Params declared as floats (e.g. smooth_sharp) need decimal precision -
    # a plain QSpinBox truncates them (3.0 -> 3, or worse 2.5 -> 2/3)
    if param_def.get('type') == 'float':
        spinner = QtWidgets.QDoubleSpinBox()
        spinner.setDecimals(2)
        spinner.setSingleStep(0.1)
    else:
        spinner = QtWidgets.QSpinBox()
    range_min = param_def.get('range', [0])[0]
    range_max = param_def.get('range', [0, 100])[1]
    # A couple of catalog entries (sleep, deep) declare a range max that overflows
    # QSpinBox's 32-bit int (e.g. 18446744073709551615) - clamp rather than crash.
    range_min = max(-2_147_483_648, min(2_147_483_647, range_min))
    range_max = max(-2_147_483_648, min(2_147_483_647, range_max))
    spinner.setRange(range_min, range_max)

    # Add warning if min_ledstrip is present
    if 'min_ledstrip' in param_def:
        warning = QtWidgets.QLabel(f"Note: Minimum value of {param_def['min_ledstrip']} recommended for LED strips")
        warning.setStyleSheet("color: #666;")
        layout.addWidget(warning)
    
    layout.addWidget(spinner)
    return container, spinner

def create_dropdown_widget(param_name: str, param_def: dict, main_window=None):
    """Create a dropdown widget from parameter definition."""
    # print(f"\nDEBUG: Creating dropdown for {param_name}")
    # print(f"DEBUG: main_window is {main_window}")
    #if main_window:
    #    print(f"DEBUG: Has color_profiles: {hasattr(main_window, 'color_profiles')}")
    #    if hasattr(main_window, 'color_profiles'):
    #        print(f"DEBUG: Number of color profiles: {len(main_window.color_profiles)}")
    
    container = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(container)
    layout.setContentsMargins(4, 4, 4, 4)
    
    combo = QtWidgets.QComboBox()
    
    # Special handling for color profile selection
    if param_name == 'start_color' and main_window and hasattr(main_window, 'color_profiles'):
        for profile_num in sorted(main_window.color_profiles.keys()):
            if 'color_name' in main_window.color_profiles[profile_num]:
                desc = main_window.color_profiles[profile_num]['color_name']
                display_text = f"Color profile {profile_num} ({desc})"
                combo.addItem(display_text, str(profile_num))
    
    # Special handling for GraFx profiles
    elif param_name in ['style_grafx1', 'style_grafx2', 'style_grafx3']:
        # Add "none" option
        combo.addItem("None", "-1")
        print(f"Creating GraFx dropdown for {param_name}")
        print(f"Main window has grafx profiles: {hasattr(main_window, 'grafx_profiles')}")
        if main_window and hasattr(main_window, 'grafx_profiles'):
            print(f"Number of GraFx profiles: {len(main_window.grafx_profiles)}")
            print(f"GraFx profiles: {main_window.grafx_profiles}")
            for profile_num, name in sorted(main_window.grafx_profiles.items()):
                combo.addItem(f"Profile {profile_num}: {name}", str(profile_num))

    # style_accents / style_pixies don't have a fixed set of meanings - each value points
    # to an indexed resource folder (/extra/accents or /extra/pixies) on this specific SD
    # card, same linking scheme as style_grafx above (CFX manual, "GraFx Sequencer
    # organization and linking" / "Accent LEDs sequencer")
    elif param_name == 'style_accents':
        combo.addItem("None", "-1")
        if main_window and hasattr(main_window, 'accents_profiles'):
            for profile_num, name in sorted(main_window.accents_profiles.items()):
                combo.addItem(f"Profile {profile_num}: {name}", str(profile_num))
    elif param_name == 'style_pixies':
        combo.addItem("None", "-1")
        if main_window and hasattr(main_window, 'pixies_profiles'):
            for profile_num, name in sorted(main_window.pixies_profiles.items()):
                combo.addItem(f"Profile {profile_num}: {name}", str(profile_num))

    # Regular dropdown with values from param_def
    elif 'values' in param_def:
        for value, description in param_def['values'].items():
            combo.addItem(f"{description}", value)
            
    layout.addWidget(combo)
    return container, combo

def create_range_pair_widget(param_name, param_def):
    container = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(container)
    
    inputs_widget = QtWidgets.QWidget()
    inputs_layout = QtWidgets.QHBoxLayout(inputs_widget)
    
    min_spin = QtWidgets.QSpinBox()
    max_spin = QtWidgets.QSpinBox()
    
    range_min = param_def.get('range', [0])[0]
    range_max = param_def.get('range', [0, 100])[1]
    
    min_spin.setRange(range_min, range_max)
    max_spin.setRange(range_min, range_max)

    if param_name in UNORDERED_RANGE_PAIR_PARAMS:
        # These two values are independent quantities, not a min/max range - don't force
        # them to stay ordered (see UNORDERED_RANGE_PAIR_PARAMS).
        first_label, second_label = "From bottom:", "From top:"
    else:
        first_label, second_label = "Min:", "Max:"
        # Keep min <= max at all times: raising min past max drags max up with it, and
        # lowering max past min drags min down with it - never let the pair go invalid.
        min_spin.valueChanged.connect(lambda v: max_spin.value() < v and max_spin.setValue(v))
        max_spin.valueChanged.connect(lambda v: min_spin.value() > v and min_spin.setValue(v))

    inputs_layout.addWidget(QtWidgets.QLabel(first_label))
    inputs_layout.addWidget(min_spin)
    inputs_layout.addWidget(QtWidgets.QLabel(second_label))
    inputs_layout.addWidget(max_spin)

    layout.addWidget(inputs_widget)
    return container, (min_spin, max_spin)

def create_color_picker_widget(param_name, param_def):
    """Build a color_picker widget. The RGBW preview swatch (widget[1]) is returned
    un-parented - callers (settings_grid) place it wherever makes sense (e.g. next to the
    parameter name) rather than inside `container`. The R/G/B/W sliders live inside
    `container` behind a collapsed-by-default toggle, since they take a lot of vertical
    space and are only needed when actually adjusting the color."""
    container = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)

    color_inputs = {}

    preview = QtWidgets.QFrame()
    preview.setFixedSize(28, 28)
    # Explicit black border - without it, a pure-white color is invisible against a
    # white/light window background.
    preview.setStyleSheet("background-color: rgb(0, 0, 0); border: 1px solid black;")

    def update_color_preview():
        r = color_inputs['R'][0].value() * 255 // 1023
        g = color_inputs['G'][0].value() * 255 // 1023
        b = color_inputs['B'][0].value() * 255 // 1023
        w = color_inputs['W'][0].value() * 255 // 1023

        # Apply white value to increase brightness
        r = min(255, r + w)
        g = min(255, g + w)
        b = min(255, b + w)

        preview.setStyleSheet(f"background-color: rgb({r}, {g}, {b}); border: 1px solid black;")

    toggle_button = QtWidgets.QToolButton()
    toggle_button.setArrowType(QtCore.Qt.RightArrow)
    toggle_button.setCheckable(True)
    toggle_button.setChecked(False)
    toggle_button.setAutoRaise(True)
    toggle_button.setText("Adjust RGBW values")
    toggle_button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
    toggle_button.setStyleSheet("QToolButton { border: none; font-size: 11px; color: #666666; }")

    sliders_container = QtWidgets.QWidget()
    sliders_layout = QtWidgets.QVBoxLayout(sliders_container)
    sliders_layout.setContentsMargins(0, 4, 0, 0)
    sliders_container.setVisible(False)  # hidden by default

    def on_toggled(checked):
        sliders_container.setVisible(checked)
        toggle_button.setArrowType(QtCore.Qt.DownArrow if checked else QtCore.Qt.RightArrow)
    toggle_button.toggled.connect(on_toggled)

    for channel in ['Red', 'Green', 'Blue', 'White']:
        channel_widget = QtWidgets.QWidget()
        channel_layout = QtWidgets.QHBoxLayout(channel_widget)
        channel_layout.setContentsMargins(2, 2, 2, 2)

        label = QtWidgets.QLabel(channel)
        label.setMinimumWidth(50)
        label.setMinimumHeight(25)

        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(0, 1023)

        spin = QtWidgets.QSpinBox()
        spin.setRange(0, 1023)

        color_inputs[channel[0]] = (slider, spin)

        slider.valueChanged.connect(spin.setValue)
        spin.valueChanged.connect(slider.setValue)
        slider.valueChanged.connect(update_color_preview)  # Add this connection

        channel_layout.addWidget(label)
        channel_layout.addWidget(slider)
        channel_layout.addWidget(spin)

        sliders_layout.addWidget(channel_widget)

    layout.addWidget(toggle_button)
    layout.addWidget(sliders_container)

    return container, (color_inputs, preview)

def create_triple_range_widget(param_name, param_def):
    container = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(container)

    inputs_widget = QtWidgets.QWidget()
    inputs_layout = QtWidgets.QHBoxLayout(inputs_widget)
    
    # Check if this is a threshold-based parameter like hdrag/hstab
    format_type = param_def.get('format', 'angle,min,max')
    is_threshold_param = format_type == 'threshold,min_angle,max_angle' or param_name in ['hdrag', 'hstab']
    
    # Get ranges from parameter definition if available
    range_values = param_def.get('range', [-1800, 1800, -90, 90] if not is_threshold_param else [0, 2000, -90, 90])
    
    # First spinner
    if is_threshold_param:
        first_label = QtWidgets.QLabel("Threshold:")
        first_spin = QtWidgets.QSpinBox()
        first_min = range_values[0] if len(range_values) >= 1 else 0
        first_max = range_values[1] if len(range_values) >= 2 else 2000
        first_spin.setRange(first_min, first_max)
    else:
        first_label = QtWidgets.QLabel("Angle:")
        first_spin = QtWidgets.QSpinBox()
        first_min = range_values[0] if len(range_values) >= 1 else -1800
        first_max = range_values[1] if len(range_values) >= 2 else 1800
        first_spin.setRange(first_min, first_max)
    
    # Min angle spinner
    min_label = QtWidgets.QLabel("Min:")
    min_spin = QtWidgets.QSpinBox()
    min_min = range_values[2] if len(range_values) >= 3 else -90
    min_max = range_values[3] if len(range_values) >= 4 else 90
    min_spin.setRange(min_min, min_max)
    min_spin.setSuffix("°")
    
    # Max angle spinner
    max_label = QtWidgets.QLabel("Max:")
    max_spin = QtWidgets.QSpinBox()
    max_min = range_values[2] if len(range_values) >= 3 else -90  # Use same range as min
    max_max = range_values[3] if len(range_values) >= 4 else 90
    max_spin.setRange(max_min, max_max)
    max_spin.setSuffix("°")

    # Keep min <= max at all times, same as the plain range-pair widget
    min_spin.valueChanged.connect(lambda v: max_spin.value() < v and max_spin.setValue(v))
    max_spin.valueChanged.connect(lambda v: min_spin.value() > v and min_spin.setValue(v))

    inputs_layout.addWidget(first_label)
    inputs_layout.addWidget(first_spin)
    inputs_layout.addWidget(min_label)
    inputs_layout.addWidget(min_spin)
    inputs_layout.addWidget(max_label)
    inputs_layout.addWidget(max_spin)
    
    layout.addWidget(inputs_widget)
    return container, (first_spin, min_spin, max_spin)

def create_text_widget(param_name, param_def):
    """Create a text input widget"""
    container = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(container)
    
    # Create text input
    text_input = QtWidgets.QLineEdit()
    layout.addWidget(text_input)
    
    return container, text_input

def create_toggle_widget(param_name, param_def):
    container = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(container)
    
    toggle = QtWidgets.QCheckBox(param_def['values']['1'])
    layout.addWidget(toggle)
    
    return container, toggle

def create_blade_profile_dropdown(param_name, param_def, main_window=None):
    """Create dropdown for blade profiles with profile numbers and names"""
    container = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(container)
    layout.setContentsMargins(4, 4, 4, 4)
    
    combo = QtWidgets.QComboBox()
    
    # Store the original value to detect changes
    combo.setProperty("original_value", None)
    
    # Add special "-1" option
    combo.addItem("Default (-1)", "-1")
    
    # Add blade profiles with names if available
    if main_window and hasattr(main_window, 'file_handler'):
        # Get all blade profiles with names
        blade_profiles = {}
        config_path = main_window.folder_path / "config.txt"
        
        try:
            if config_path.exists():
                current_profile = None
                with open(config_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith('[profile='):
                            try:
                                current_profile = int(line[9:-1])
                                blade_profiles[current_profile] = f"Profile {current_profile}"
                            except ValueError:
                                continue
                        elif '=' in line and current_profile is not None:
                            key, value = line.split('=', 1)
                            key = key.strip()
                            if key == 'pname':
                                blade_profiles[current_profile] = f"Profile {current_profile} ({value.strip()})"
                
                # Add profiles to dropdown
                for profile_num in sorted(blade_profiles.keys()):
                    combo.addItem(blade_profiles[profile_num], str(profile_num))
        except Exception as e:
            print(f"Error loading blade profiles for dropdown: {e}")
    
    # Connect change signal to confirmation handler
    if main_window:
        combo.currentIndexChanged.connect(
            lambda index: main_window.confirm_profile_change(param_name, combo)
        )
    
    layout.addWidget(combo)
    return container, combo

def create_color_profile_dropdown(param_name, param_def, main_window=None):
    """Create dropdown for color profiles with profile numbers and color names"""
    container = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(container)
    layout.setContentsMargins(4, 4, 4, 4)
    
    combo = QtWidgets.QComboBox()
    
    # Store the original value to detect changes
    combo.setProperty("original_value", None)
    
    # Add special "-1" option
    combo.addItem("Default (-1)", "-1")
    
    # Add color profiles with names if available
    if main_window and hasattr(main_window, 'color_profiles'):
        for profile_num in sorted(main_window.color_profiles.keys()):
            profile = main_window.color_profiles.get(profile_num, {})
            color_name = profile.get('color_name', 'Unknown')
            combo.addItem(f"Color {profile_num} ({color_name})", str(profile_num))
    
    # Connect change signal to confirmation handler
    if main_window:
        combo.currentIndexChanged.connect(
            lambda index: main_window.confirm_profile_change(param_name, combo)
        )
    
    layout.addWidget(combo)
    return container, combo
    """Create dropdown for color profiles with profile numbers and color names"""
    container = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(container)
    layout.setContentsMargins(4, 4, 4, 4)

    combo = QtWidgets.QComboBox()

    # Add special "-1" option
    combo.addItem("Default (-1)", "-1")

    # Add color profiles with names if available
    if main_window and hasattr(main_window, 'color_profiles'):
        for profile_num in sorted(main_window.color_profiles.keys()):
            profile = main_window.color_profiles.get(profile_num, {})
            color_name = profile.get('color_name', 'Unknown')
            combo.addItem(f"Color {profile_num} ({color_name})", str(profile_num))

    layout.addWidget(combo)
    return container, combo


def create_rgb_picker_widget(label: str, initial_rgb=(255, 255, 255)):
    """A plain 0-255 RGB picker: three slider+spinbox rows plus a bordered swatch preview.
    Used by the GraFx Creator wizard for preset colors - GraFx BMP pixels are literal RGB,
    unlike the RGBW (0-1023) format create_color_picker_widget builds for font_config.txt
    color params, so this is a separate, simpler widget rather than a shared one.

    Returns (container, (r_spin, g_spin, b_spin, swatch))."""
    container = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)

    if label:
        title = QtWidgets.QLabel(label)
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

    swatch = QtWidgets.QFrame()
    swatch.setFixedSize(28, 28)

    spins = {}

    def update_swatch():
        r, g, b = (spins[c].value() for c in 'RGB')
        swatch.setStyleSheet(f"background-color: rgb({r}, {g}, {b}); border: 1px solid black;")

    for channel, initial in zip('RGB', initial_rgb):
        row = QtWidgets.QWidget()
        row_layout = QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(2, 2, 2, 2)

        channel_label = QtWidgets.QLabel(channel)
        channel_label.setMinimumWidth(20)

        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(0, 255)
        slider.setValue(initial)

        spin = QtWidgets.QSpinBox()
        spin.setRange(0, 255)
        spin.setValue(initial)

        slider.valueChanged.connect(spin.setValue)
        spin.valueChanged.connect(slider.setValue)
        spin.valueChanged.connect(update_swatch)

        spins[channel] = spin

        row_layout.addWidget(channel_label)
        row_layout.addWidget(slider)
        row_layout.addWidget(spin)
        layout.addWidget(row)

    layout.addWidget(swatch)
    update_swatch()

    return container, (spins['R'], spins['G'], spins['B'], swatch)