# src/gui/edit_dialogs.py
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QSpinBox, QComboBox, QDialogButtonBox,
    QWidget, QSlider
)
from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import Qt, Signal

class BaseEditDialog(QtWidgets.QDialog):
    def __init__(self, param_name: str, current_value: str, constraints: dict, parent=None):
        super().__init__(parent)
        self.param_name = param_name
        self.current_value = current_value
        self.constraints = constraints
        self.init_ui()
        self.setModal(True)

    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        
        # Title
        title = QtWidgets.QLabel(f"Edit {self.param_name}")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        # Description if available
        if 'description' in self.constraints:
            desc = QtWidgets.QLabel(self.constraints['description'])
            desc.setWordWrap(True)
            desc.setStyleSheet("color: #666; margin-bottom: 10px;")
            layout.addWidget(desc)

        # Content area (to be implemented by subclasses)
        self.content_area = QtWidgets.QWidget()
        self.content_layout = QtWidgets.QVBoxLayout(self.content_area)
        layout.addWidget(self.content_area)

        # Buttons
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_value(self):
        """Override in subclasses to return the edited value"""
        raise NotImplementedError
    
class NumberEditDialog(BaseEditDialog):
    """Dialog for editing numeric values."""
    def init_ui(self):
        super().init_ui()
        
        range_min = self.constraints.get('range', [0])[0]
        range_max = self.constraints.get('range', [0, 100])[1]
        
        spinbox = QSpinBox()
        spinbox.setRange(range_min, range_max)
        spinbox.setValue(int(self.current_value))
        self.spinbox = spinbox
        
        if 'min_ledstrip' in self.constraints:
            warning = QLabel(f"Note: Minimum value of {self.constraints['min_ledstrip']} recommended for LED strips")
            warning.setStyleSheet("color: #666;")
            self.content_layout.addWidget(warning)
            
        self.content_layout.addWidget(spinbox)

    def get_value(self):
        return str(self.spinbox.value())

class RangePairEditDialog(BaseEditDialog):
    """Dialog for editing min/max range pairs."""
    def init_ui(self):
        super().init_ui()
        
        range_min = self.constraints.get('range', [0])[0]
        range_max = self.constraints.get('range', [0, 100])[1]
        
        current_min, current_max = map(int, self.current_value.split(','))
        
        # Min value
        min_layout = QHBoxLayout()
        min_layout.addWidget(QLabel("Minimum:"))
        min_spinbox = QSpinBox()
        min_spinbox.setRange(range_min, range_max)
        min_spinbox.setValue(current_min)
        self.min_spinbox = min_spinbox
        min_layout.addWidget(min_spinbox)
        self.content_layout.addLayout(min_layout)
        
        # Max value
        max_layout = QHBoxLayout()
        max_layout.addWidget(QLabel("Maximum:"))
        max_spinbox = QSpinBox()
        max_spinbox.setRange(range_min, range_max)
        max_spinbox.setValue(current_max)
        self.max_spinbox = max_spinbox
        max_layout.addWidget(max_spinbox)
        self.content_layout.addLayout(max_layout)
        
        # Connect signals to ensure min <= max
        min_spinbox.valueChanged.connect(self._on_min_changed)
        max_spinbox.valueChanged.connect(self._on_max_changed)

    def _on_min_changed(self, value):
        if value > self.max_spinbox.value():
            self.max_spinbox.setValue(value)

    def _on_max_changed(self, value):
        if value < self.min_spinbox.value():
            self.min_spinbox.setValue(value)

    def get_value(self):
        return f"{self.min_spinbox.value()},{self.max_spinbox.value()}"

class EnumEditDialog(BaseEditDialog):
    """Dialog for editing enumerated values."""
    def __init__(self, param_name: str, current_value: str, constraints: dict, parent=None, main_window=None):
        self.main_window = main_window
        super().__init__(param_name, current_value, constraints, parent)
        
    def init_ui(self):
        super().init_ui()
        container, combo = create_dropdown_widget(self.param_name, self.constraints, self.main_window)
        self.combo = combo
            
        # Set current value
        index = self.combo.findData(self.current_value)
        if index >= 0:
            self.combo.setCurrentIndex(index)
            
        self.content_layout.addWidget(container)

    def get_value(self):
        return self.combo.currentData()
    
class ColorEditDialog(BaseEditDialog):
    """Dialog for editing RGBW color values."""
    def init_ui(self):
        super().init_ui()
        
        self.sliders = []
        self.spinboxes = []
        current_values = list(map(int, self.current_value.split(',')))
        
        for i, color in enumerate(['Red', 'Green', 'Blue', 'White']):
            row_layout = QHBoxLayout()
            
            # Label
            row_layout.addWidget(QLabel(color))
            
            # Spinbox
            spinbox = QSpinBox()
            spinbox.setRange(0, 1023)
            spinbox.setValue(current_values[i] if i < len(current_values) else 0)
            self.spinboxes.append(spinbox)
            row_layout.addWidget(spinbox)
            
            # Slider
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 1023)
            slider.setValue(current_values[i] if i < len(current_values) else 0)
            self.sliders.append(slider)
            row_layout.addWidget(slider)
            
            # Connect signals
            slider.valueChanged.connect(spinbox.setValue)
            spinbox.valueChanged.connect(slider.setValue)
            
            self.content_layout.addLayout(row_layout)

    def get_value(self):
        return ','.join(str(spinbox.value()) for spinbox in self.spinboxes)

# Function to create appropriate dialog based on parameter type
    def create_edit_dialog(param_name: str, current_value: str, constraints: dict, parent=None, main_window=None) -> BaseEditDialog:
        param_type = constraints.get('type', 'text')  # Default to text instead of number
        
        # Handle special parameter names that we know aren't integers
        if param_name in ['pname', 'twon', 'twoff', 'pof', 'wagon', 'wagoff']:
            return TextEditDialog(param_name, current_value, constraints, parent)
        
        dialog_classes = {
            'integer': NumberEditDialog,
            'range_pair': RangePairEditDialog,
            'text': TextEditDialog
        }
        
        if 'values' in constraints or param_name == 'color':
            return EnumEditDialog(param_name, current_value, constraints, parent, main_window)
        
        return dialog_classes.get(param_type, TextEditDialog)(
            param_name, current_value, constraints, parent
        )

class TextEditDialog(BaseEditDialog):
    """Dialog for editing text values."""
    def init_ui(self):
        super().init_ui()
        
        # Line edit for text input
        from PySide6.QtWidgets import QLineEdit
        self.text_input = QLineEdit()
        self.text_input.setText(self.current_value)
        self.content_layout.addWidget(self.text_input)

    def get_value(self):
        return self.text_input.text()
    
class SpinnerDialog(BaseEditDialog):
    def init_ui(self):
        super().init_ui()
        
        range_min = self.constraints.get('range', [0])[0]
        range_max = self.constraints.get('range', [0, 100])[1]
        
        # Create spinner
        self.spinbox = QtWidgets.QSpinBox()
        self.spinbox.setRange(range_min, range_max)
        self.spinbox.setValue(int(self.current_value))
        
        # Add units or notes if specified
        if 'min_ledstrip' in self.constraints:
            warning = QtWidgets.QLabel(f"Note: Minimum value of {self.constraints['min_ledstrip']} recommended for LED strips")
            warning.setStyleSheet("color: #666;")
            self.content_layout.addWidget(warning)
            
        self.content_layout.addWidget(self.spinbox)

    def get_value(self):
        return str(self.spinbox.value())

class DropdownDialog(BaseEditDialog):
    def init_ui(self):
        super().init_ui()
        
        # Create combobox
        self.combo = QtWidgets.QComboBox()
        
        # Add items from constraints
        if 'values' in self.constraints:
            for value, description in self.constraints['values'].items():
                self.combo.addItem(f"{value}: {description}", value)
            
            # Set current value
            current_idx = self.combo.findData(str(self.current_value))
            if current_idx >= 0:
                self.combo.setCurrentIndex(current_idx)
            
        self.content_layout.addWidget(self.combo)

    def get_value(self):
        return self.combo.currentData()