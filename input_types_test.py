# input_types_test.py
from PySide6 import QtWidgets, QtCore, QtGui

class InputTypesDemo(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CFX Input Types Demo")
        self.setMinimumSize(800, 600)

        # Create central widget
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)

        # Create scroll area
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        
        # Create container for all the input demos
        container = QtWidgets.QWidget()
        container_layout = QtWidgets.QVBoxLayout(container)

        # Add each input type with a label
        container_layout.addWidget(self.create_spinner_demo())
        container_layout.addWidget(self.create_dropdown_demo())
        container_layout.addWidget(self.create_toggle_demo())
        container_layout.addWidget(self.create_range_pair_demo())
        container_layout.addWidget(self.create_triple_range_demo())
        container_layout.addWidget(self.create_color_picker_demo())
        container_layout.addWidget(self.create_text_demo())
        container_layout.addWidget(self.create_grafx_dropdown_demo())

        # Add some spacing at the bottom
        container_layout.addStretch()

        # Set the container as the scroll area widget
        scroll.setWidget(container)
        
        # Add scroll area to main layout
        main_layout.addWidget(scroll)

    def create_section(self, title):
        """Create a section widget with title and content area"""
        section = QtWidgets.QGroupBox(title)
        layout = QtWidgets.QVBoxLayout(section)
        return section, layout

    def create_spinner_demo(self):
        section, layout = self.create_section("Spinner (e.g., flks)")
        
        # Create spinner with range 0-500
        spinner = QtWidgets.QSpinBox()
        spinner.setRange(0, 500)
        spinner.setValue(6)
        spinner.setPrefix("Value: ")
        spinner.setSuffix(" units")
        
        layout.addWidget(spinner)
        return section

    def create_dropdown_demo(self):
        section, layout = self.create_section("Dropdown (e.g., style_pon)")
        
        combo = QtWidgets.QComboBox()
        combo.addItems([
            "0: Normal power-on with scrolling",
            "1: Lightstick style",
            "2: Simple flare style"
        ])
        
        layout.addWidget(combo)
        return section

    def create_toggle_demo(self):
        section, layout = self.create_section("Toggle (e.g., blastm)")
        
        toggle = QtWidgets.QCheckBox("Enable Blaster Move")
        toggle.setMinimumHeight(30)
        layout.addWidget(toggle)
        
        return section

    def create_range_pair_demo(self):
        section, layout = self.create_section("Range Pair (e.g., shmr%)")
        
        min_spin = QtWidgets.QSpinBox()
        min_spin.setRange(0, 100)
        min_spin.setPrefix("Min: ")
        min_spin.setSuffix("%")
        
        max_spin = QtWidgets.QSpinBox()
        max_spin.setRange(0, 100)
        max_spin.setPrefix("Max: ")
        max_spin.setSuffix("%")
        
        hlayout = QtWidgets.QHBoxLayout()
        hlayout.addWidget(min_spin)
        hlayout.addWidget(max_spin)
        
        layout.addLayout(hlayout)
        return section
   
    def create_triple_range_demo(self):
        section, layout = self.create_section("Triple Range (e.g., twon)")
        
        angle_spin = QtWidgets.QSpinBox()
        angle_spin.setRange(-1800, 1800)
        angle_spin.setPrefix("Angle: ")
        
        min_spin = QtWidgets.QSpinBox()
        min_spin.setRange(-90, 90)
        min_spin.setPrefix("Min: ")
        
        max_spin = QtWidgets.QSpinBox()
        max_spin.setRange(-90, 90)
        max_spin.setPrefix("Max: ")
        
        hlayout = QtWidgets.QHBoxLayout()
        hlayout.addWidget(angle_spin)
        hlayout.addWidget(min_spin)
        hlayout.addWidget(max_spin)
        
        layout.addLayout(hlayout)
        return section
    
    def create_color_picker_demo(self):
        section, layout = self.create_section("Color Picker (RGBW)")
        
        # Store sliders and spinboxes to access values
        self.color_inputs = {'R': None, 'G': None, 'B': None, 'W': None}
        
        # Create sliders for each channel
        for channel in ['R', 'G', 'B', 'W']:
            channel_widget = QtWidgets.QWidget()
            channel_layout = QtWidgets.QHBoxLayout(channel_widget)
            channel_layout.setContentsMargins(0, 0, 0, 0)
            
            label = QtWidgets.QLabel(channel)
            label.setMinimumWidth(50)
            
            slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            slider.setRange(0, 1023)
            
            spin = QtWidgets.QSpinBox()
            spin.setRange(0, 1023)
            
            # Store references to inputs
            self.color_inputs[channel] = (slider, spin)
            
            # Connect slider and spinbox
            slider.valueChanged.connect(spin.setValue)
            spin.valueChanged.connect(slider.setValue)
            # Connect to update preview
            slider.valueChanged.connect(self.update_color_preview)
            
            channel_layout.addWidget(label)
            channel_layout.addWidget(slider)
            channel_layout.addWidget(spin)
            
            layout.addWidget(channel_widget)
            
        # Add color preview
        self.color_preview = QtWidgets.QFrame()
        self.color_preview.setMinimumHeight(50)
        self.color_preview.setStyleSheet("background-color: rgb(0, 255, 0);")
        layout.addWidget(self.color_preview)
        
        return section

    def update_color_preview(self):
        """Update color preview based on RGBW values"""
        r = self.color_inputs['R'][0].value() * 255 // 1023
        g = self.color_inputs['G'][0].value() * 255 // 1023
        b = self.color_inputs['B'][0].value() * 255 // 1023
        # W could be used to increase brightness of all channels
        w = self.color_inputs['W'][0].value() * 255 // 1023
        
        # Apply white value to increase brightness
        r = min(255, r + w)
        g = min(255, g + w)
        b = min(255, b + w)
        
        self.color_preview.setStyleSheet(f"background-color: rgb({r}, {g}, {b});")
    def create_text_demo(self):
        section, layout = self.create_section("Text (e.g., pname)")
        
        text = QtWidgets.QLineEdit()
        text.setPlaceholderText("Enter profile name...")
        
        layout.addWidget(text)
        return section

    def create_grafx_dropdown_demo(self):
        section, layout = self.create_section("GraFx Dropdown (e.g., style_grafx1)")
        
        combo = QtWidgets.QComboBox()
        combo.addItem("-1: none")
        combo.addItem("3: ANCIENT-PROPHECIES")
        combo.addItem("4: SHOCK-BATON")
        
        layout.addWidget(combo)
        return section

def main():
    app = QtWidgets.QApplication([])
    window = InputTypesDemo()
    window.show()
    return app.exec()

if __name__ == "__main__":
    main()