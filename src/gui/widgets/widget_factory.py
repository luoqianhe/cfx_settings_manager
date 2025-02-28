# src/gui/widgets/widget_factory.py
from typing import Tuple
from PySide6 import QtWidgets, QtCore
from PySide6.QtWidgets import QWidget

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
        return create_text_input_widget(param_name, param_def)
    else:
        raise ValueError(f"Unknown display type: {display_type} for parameter {param_name}")

def create_spinner_widget(param_name, param_def):
    """Create a spinner widget from parameter definition"""
    container = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(container)
    
    # Create spinner
    spinner = QtWidgets.QSpinBox()
    range_min = param_def.get('range', [0])[0]
    range_max = param_def.get('range', [0, 100])[1]
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
    
    inputs_layout.addWidget(QtWidgets.QLabel("Min:"))
    inputs_layout.addWidget(min_spin)
    inputs_layout.addWidget(QtWidgets.QLabel("Max:"))
    inputs_layout.addWidget(max_spin)
    
    layout.addWidget(inputs_widget)
    return container, (min_spin, max_spin)

def create_color_picker_widget(param_name, param_def):
    container = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(container)

    color_inputs = {}
    preview = QtWidgets.QFrame()
    preview.setMinimumHeight(50)
    preview.setStyleSheet("background-color: rgb(0, 0, 0);")

    def update_color_preview():
        r = color_inputs['R'][0].value() * 255 // 1023
        g = color_inputs['G'][0].value() * 255 // 1023
        b = color_inputs['B'][0].value() * 255 // 1023
        w = color_inputs['W'][0].value() * 255 // 1023
        
        # Apply white value to increase brightness
        r = min(255, r + w)
        g = min(255, g + w)
        b = min(255, b + w)
        
        preview.setStyleSheet(f"background-color: rgb({r}, {g}, {b});")

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
        
        layout.addWidget(channel_widget)

    layout.addWidget(preview)
    
    return container, (color_inputs, preview)

def create_triple_range_widget(param_name, param_def):
    container = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(container)

    inputs_widget = QtWidgets.QWidget()
    inputs_layout = QtWidgets.QHBoxLayout(inputs_widget)
    
    angle_label = QtWidgets.QLabel("Angle:")
    angle_spin = QtWidgets.QSpinBox()
    angle_spin.setRange(-1800, 1800)
    
    min_label = QtWidgets.QLabel("Min:")
    min_spin = QtWidgets.QSpinBox()
    min_spin.setRange(-90, 90)
    
    max_label = QtWidgets.QLabel("Max:")
    max_spin = QtWidgets.QSpinBox()
    max_spin.setRange(-90, 90)
    
    inputs_layout.addWidget(angle_label)
    inputs_layout.addWidget(angle_spin)
    inputs_layout.addWidget(min_label)
    inputs_layout.addWidget(min_spin)
    inputs_layout.addWidget(max_label)
    inputs_layout.addWidget(max_spin)
    
    layout.addWidget(inputs_widget)
    return container, (angle_spin, min_spin, max_spin)

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