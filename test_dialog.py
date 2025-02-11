from PySide6 import QtWidgets, QtGui, QtCore

class InputTestWindow(QtWidgets.QMainWindow):
   def __init__(self):
       super().__init__()
       self.setWindowTitle("Input Test")
       self.setMinimumSize(400, 300)

       # Get background color for styling
       background_color = self.palette().color(QtGui.QPalette.Window).name()
       
       # Set style for group box titles
       self.setStyleSheet(f"""
           QGroupBox {{
               font-weight: bold;
               font-style: italic;
               font-size: 14px;
               color: blue;
           }}
           QGroupBox::title {{
               padding: 0px 3px;
               background-color: {background_color};
           }}
       """)

       # Create central widget and layout
       central = QtWidgets.QWidget()
       self.setCentralWidget(central)
       main_layout = QtWidgets.QVBoxLayout(central)

       # Create scroll area and its widget
       scroll = QtWidgets.QScrollArea()
       scroll.setWidgetResizable(True)
       scroll_widget = QtWidgets.QWidget()
       scroll_layout = QtWidgets.QVBoxLayout(scroll_widget)

       # Spinner section
       spinner_group = QtWidgets.QGroupBox("flks")
       spinner_layout = QtWidgets.QVBoxLayout(spinner_group)
       
       desc = QtWidgets.QLabel("Flicker speed/instability (0=disabled, higher=more chaotic)")
       desc.setWordWrap(True)
       spinner_layout.addWidget(desc)
       
       warning = QtWidgets.QLabel("Note: Minimum value of 6 recommended for LED strips")
       warning.setStyleSheet("color: #666;")
       spinner_layout.addWidget(warning)
       
       self.spinbox = QtWidgets.QSpinBox()
       self.spinbox.setRange(0, 500)
       self.spinbox.setValue(6)
       spinner_layout.addWidget(self.spinbox)
       
       scroll_layout.addWidget(spinner_group)

       # Dropdown section
       dropdown_group = QtWidgets.QGroupBox("style_pon")
       dropdown_layout = QtWidgets.QVBoxLayout(dropdown_group)
       
       desc = QtWidgets.QLabel("Power-on effect style")
       desc.setWordWrap(True)
       dropdown_layout.addWidget(desc)
       
       self.combo = QtWidgets.QComboBox()
       style_options = {
           "0": "Normal/regular power-on with scrolling",
           "1": "Lightstick style",
           "2": "Simple flare style",
           "3": "Base flare style",
           "4": "Tip flare style"
       }
       for value, description in style_options.items():
           self.combo.addItem(f"{value}: {description}", value)
       dropdown_layout.addWidget(self.combo)
       
       scroll_layout.addWidget(dropdown_group)

       # Toggle section
       toggle_group = QtWidgets.QGroupBox("blastm")
       toggle_layout = QtWidgets.QVBoxLayout(toggle_group)
       
       desc = QtWidgets.QLabel("Blaster Move feature")
       desc.setWordWrap(True)
       toggle_layout.addWidget(desc)
       
       self.checkbox = QtWidgets.QCheckBox("Enable Blaster Move")
       toggle_layout.addWidget(self.checkbox)
       
       scroll_layout.addWidget(toggle_group)

       # Range Pair section
       range_pair_group = QtWidgets.QGroupBox("shmr%")
       range_pair_layout = QtWidgets.QVBoxLayout(range_pair_group)
       
       desc = QtWidgets.QLabel("Shimmer depth min and max levels")
       desc.setWordWrap(True)
       range_pair_layout.addWidget(desc)
       
       range_widget = QtWidgets.QWidget()
       range_layout = QtWidgets.QHBoxLayout(range_widget)
       
       min_label = QtWidgets.QLabel("Min:")
       self.min_spin = QtWidgets.QSpinBox()
       self.min_spin.setRange(0, 100)
       self.min_spin.setValue(60)
       self.min_spin.setSuffix("%")
       
       max_label = QtWidgets.QLabel("Max:")
       self.max_spin = QtWidgets.QSpinBox()
       self.max_spin.setRange(0, 100)
       self.max_spin.setValue(99)
       self.max_spin.setSuffix("%")
       
       range_layout.addWidget(min_label)
       range_layout.addWidget(self.min_spin)
       range_layout.addWidget(max_label)
       range_layout.addWidget(self.max_spin)
       
       range_pair_layout.addWidget(range_widget)
       scroll_layout.addWidget(range_pair_group)

       # Color Picker section
       color_group = QtWidgets.QGroupBox("color")
       color_layout = QtWidgets.QVBoxLayout(color_group)
       
       desc = QtWidgets.QLabel("Main blade color values (RGBW)")
       desc.setWordWrap(True)
       color_layout.addWidget(desc)
       
       self.color_inputs = {}
       
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
           
           self.color_inputs[channel[0]] = (slider, spin)
           
           slider.valueChanged.connect(spin.setValue)
           spin.valueChanged.connect(slider.setValue)
           slider.valueChanged.connect(self.update_color_preview)
           
           channel_layout.addWidget(label)
           channel_layout.addWidget(slider)
           channel_layout.addWidget(spin)
           
           color_layout.addWidget(channel_widget)
           
       self.color_preview = QtWidgets.QFrame()
       self.color_preview.setMinimumHeight(50)
       self.color_preview.setStyleSheet("background-color: rgb(0, 0, 0);")
       color_layout.addWidget(self.color_preview)
       
       scroll_layout.addWidget(color_group)

       # Triple Range section
       triple_range_group = QtWidgets.QGroupBox("twon")
       triple_range_layout = QtWidgets.QVBoxLayout(triple_range_group)
       
       desc = QtWidgets.QLabel("Twist-on behavior range")
       desc.setWordWrap(True)
       triple_range_layout.addWidget(desc)
       
       inputs_widget = QtWidgets.QWidget()
       inputs_layout = QtWidgets.QHBoxLayout(inputs_widget)
       
       angle_label = QtWidgets.QLabel("Angle:")
       self.angle_spin = QtWidgets.QSpinBox()
       self.angle_spin.setRange(-1800, 1800)
       self.angle_spin.setValue(-1200)
       
       min_label = QtWidgets.QLabel("Min:")
       self.tr_min_spin = QtWidgets.QSpinBox()
       self.tr_min_spin.setRange(-90, 90)
       self.tr_min_spin.setValue(-90)
       
       max_label = QtWidgets.QLabel("Max:")
       self.tr_max_spin = QtWidgets.QSpinBox()
       self.tr_max_spin.setRange(-90, 90)
       self.tr_max_spin.setValue(90)
       
       inputs_layout.addWidget(angle_label)
       inputs_layout.addWidget(self.angle_spin)
       inputs_layout.addWidget(min_label)
       inputs_layout.addWidget(self.tr_min_spin)
       inputs_layout.addWidget(max_label)
       inputs_layout.addWidget(self.tr_max_spin)
       
       triple_range_layout.addWidget(inputs_widget)
       scroll_layout.addWidget(triple_range_group)
       
       # GraFx Dropdown section
       grafx_group = QtWidgets.QGroupBox("style_grafx1")
       grafx_layout = QtWidgets.QVBoxLayout(grafx_group)
       desc = QtWidgets.QLabel("First GraFx sequence profile")
       desc.setWordWrap(True)
       grafx_layout.addWidget(desc)
       self.grafx_combo = QtWidgets.QComboBox()
       self.grafx_combo.addItem("-1: none")
       self.grafx_combo.addItem("3: ANCIENT-PROPHECIES")
       self.grafx_combo.addItem("4: SHOCK-BATON")
       self.grafx_combo.addItem("5: SHOCK-BATON-Quilon")
       grafx_layout.addWidget(self.grafx_combo)
       
       scroll_layout.addWidget(grafx_group)
       
        # Text Input section
       text_group = QtWidgets.QGroupBox("pname")
       text_layout = QtWidgets.QVBoxLayout(text_group)
       
       desc = QtWidgets.QLabel("Blade profile name")
       desc.setWordWrap(True)
       text_layout.addWidget(desc)
       
       self.text_input = QtWidgets.QLineEdit()
       self.text_input.setPlaceholderText("Enter profile name...")
       text_layout.addWidget(self.text_input)
       
       scroll_layout.addWidget(text_group)

       # Add OK button and finalize layout
       ok_button = QtWidgets.QPushButton("OK")
       ok_button.clicked.connect(self.on_ok)
       scroll_layout.addWidget(ok_button)

       scroll.setWidget(scroll_widget)
       main_layout.addWidget(scroll)

   def update_color_preview(self):
       r = self.color_inputs['R'][0].value() * 255 // 1023
       g = self.color_inputs['G'][0].value() * 255 // 1023
       b = self.color_inputs['B'][0].value() * 255 // 1023
       w = self.color_inputs['W'][0].value() * 255 // 1023
       
       r = min(255, r + w)
       g = min(255, g + w)
       b = min(255, b + w)
       
       self.color_preview.setStyleSheet(f"background-color: rgb({r}, {g}, {b});")

   def on_ok(self):
       spinner_value = self.spinbox.value()
       combo_value = self.combo.currentData()
       toggle_value = 1 if self.checkbox.isChecked() else 0
       range_pair_value = f"{self.min_spin.value()},{self.max_spin.value()}"
       color_value = ",".join(str(self.color_inputs[c][1].value()) 
                            for c in ['R', 'G', 'B', 'W'])
       triple_range_value = f"{self.angle_spin.value()},{self.tr_min_spin.value()},{self.tr_max_spin.value()}"
       grafx_value = self.grafx_combo.currentData() or self.grafx_combo.currentText().split(':')[0]
       text_value = self.text_input.text()
       print(f"Text value: {text_value}")
       
       print(f"GraFx value: {grafx_value}")
       print(f"Spinner value: {spinner_value}")
       print(f"Dropdown value: {combo_value}")
       print(f"Toggle value: {toggle_value}")
       print(f"Range pair value: {range_pair_value}")
       print(f"Color value: {color_value}")
       print(f"Triple range value: {triple_range_value}")
       self.close()

def main():
   app = QtWidgets.QApplication([])
   window = InputTestWindow()
   window.show()
   return app.exec()

if __name__ == "__main__":
   main()