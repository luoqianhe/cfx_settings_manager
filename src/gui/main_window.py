# src/gui/main_window.py
from PySide6 import QtWidgets, QtCore, QtGui
from pathlib import Path
import shutil
from datetime import datetime
from core.validators import CFXValidator
from core.file_handler import CFXFileHandler
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
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFileDialog, QMessageBox, QScrollArea,
    QLineEdit, QSpinBox, QComboBox
)
from PySide6.QtCore import Qt
from gui.widgets.settings_grid import SettingsGrid
from gui.widgets.blade_preview import BladePreviewWidget
from gui.validation_report_dialog import ValidationReportDialog
from core.sound_player import SoundPlayer

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.folder_path = None
        self.file_handler = None
        self.backup_path = None  # optional; None means "no backup configured"
        self.current_font_path = None  # the selected font's folder, for sound lookups
        self.sound_player = SoundPlayer(self)
        self.color_profiles = {}
        self.grafx_profiles = {}
        self.grafx_profile_paths = {}
        self.accents_profiles = {}
        self.pixies_profiles = {}
        self.validation_report = None
        self.font_validation_by_path = {}  # str(font_path) -> font_report, for fonts with issues
        self.setWindowTitle("CFX Settings Manager")
        self.setMinimumSize(1024, 768)
        self.resize(1175, 900)
        
        # Apply global stylesheet for dropdown highlighting
        self.setStyleSheet("""
            QComboBox {
                padding: 2px;
            }
            
            QComboBox::drop-down {
                border: none;
            }
            
            QListView::item:selected, QComboBox::item:selected, QComboBox QAbstractItemView::item:selected {
                color: white;
                background-color: #4A90E2;
            }
            
            QListView::item:hover, QComboBox::item:hover, QComboBox QAbstractItemView::item:hover {
                color: white;
                background-color: #5A9AE6;
            }
            
            QComboBox QAbstractItemView {
                selection-color: white;
                selection-background-color: #4A90E2;
                border: 1px solid #C0C0C0;
            }
        """)
        
        # Create central widget and main layout
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QHBoxLayout(central)
        
        # Left sidebar container
        left_container = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_container)
        left_layout.setContentsMargins(8, 8, 8, 8)
        
        # Add Select Font Folder button
        select_folder_button = QtWidgets.QPushButton("Select Root CFX Folder")
        select_folder_button.setFixedWidth(250)  # match the Soundfont Folders section below
        select_folder_button.setStyleSheet("""
            QPushButton {
                background-color: #4A90E2;
                color: white;
                padding: 6px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #357ABD;
            }
        """)
        select_folder_button.clicked.connect(self.prompt_for_folder)
        left_layout.addWidget(select_folder_button)

        # Opens the GraFx Creator wizard - only meaningful once a CFX folder is loaded
        grafx_creator_button = QtWidgets.QPushButton("Create GraFx Resource...")
        grafx_creator_button.setFixedWidth(250)  # match the Soundfont Folders section below
        grafx_creator_button.clicked.connect(self.open_grafx_creator)
        left_layout.addWidget(grafx_creator_button)

        # Opens the GraFx resource editor - edit the BMPs/settings of existing resources
        grafx_editor_button = QtWidgets.QPushButton("Edit GraFx Resources...")
        grafx_editor_button.setFixedWidth(250)
        grafx_editor_button.clicked.connect(self.open_grafx_editor)
        left_layout.addWidget(grafx_editor_button)

        # special.txt (overrides / special modes) and the iSaber music tracks
        special_button = QtWidgets.QPushButton("Special Settings...")
        special_button.setFixedWidth(250)
        special_button.setToolTip("Edit special.txt - blademusicstyle, maxvol, auto-on/off, OLED options, ...")
        special_button.clicked.connect(self.open_special_settings)
        left_layout.addWidget(special_button)
        tracks_button = QtWidgets.QPushButton("Music Tracks (iSaber)...")
        tracks_button.setFixedWidth(250)
        tracks_button.setToolTip("Add songs to /tracks for the iSaber player, which the blade can play along to")
        tracks_button.clicked.connect(self.open_tracks_dialog)
        left_layout.addWidget(tracks_button)

        # Bring a font in from another card, and tidy up the shared profile libraries
        import_font_button = QtWidgets.QPushButton("Add Soundfont...")
        import_font_button.setFixedWidth(250)
        import_font_button.setToolTip("Copy a font from another CFX card, with its color/blade profiles and GraFx")
        import_font_button.clicked.connect(self.open_import_font)
        left_layout.addWidget(import_font_button)
        duplicates_button = QtWidgets.QPushButton("Check Duplicate Profiles...")
        duplicates_button.setFixedWidth(250)
        duplicates_button.setToolTip("Find and merge identical profiles in config.txt and colors.txt")
        duplicates_button.clicked.connect(self.open_duplicate_profiles)
        left_layout.addWidget(duplicates_button)
        sound_check_button = QtWidgets.QPushButton("Check Sounds...")
        sound_check_button.setFixedWidth(250)
        sound_check_button.setToolTip("Find WAV files the board would skip or might stall on, and fix them")
        sound_check_button.clicked.connect(self.open_sound_check)
        left_layout.addWidget(sound_check_button)

        # Soundfont header
        header_label = QtWidgets.QLabel("Soundfont Folders")
        header_label.setStyleSheet("""
            font-weight: bold;
            font-size: 14px;
            padding: 4px;
            background-color: #f0f0f0;
            border: 1px solid #ddd;
        """)
        header_label.setMinimumHeight(30)
        header_label.setAlignment(Qt.AlignCenter)
        header_label.setFixedWidth(250)  # Increased width
        left_layout.addWidget(header_label)
        
        # Font list
        self.font_list = QtWidgets.QListWidget()
        self.font_list.setFixedWidth(250)  # Match header width
        self.font_list.itemClicked.connect(self.on_font_selected)
        left_layout.addWidget(self.font_list, stretch=1)

        # Blade preview
        preview_header = QtWidgets.QLabel("Blade Preview (approximate)")
        preview_header.setStyleSheet("""
            font-weight: bold;
            font-size: 14px;
            padding: 4px;
            background-color: #f0f0f0;
            border: 1px solid #ddd;
        """)
        preview_header.setMinimumHeight(30)
        preview_header.setAlignment(Qt.AlignCenter)
        preview_header.setFixedWidth(250)
        left_layout.addWidget(preview_header)

        self.blade_preview = BladePreviewWidget()
        self.blade_preview.setFixedWidth(250)  # match the Soundfont Folders section above
        self.blade_preview.ignited.connect(self._on_blade_ignited)
        self.blade_preview.preon_started.connect(self._on_preon_started)
        self.blade_preview.poweron_started.connect(self._on_poweron_started)
        self.blade_preview.postoff_started.connect(self._on_postoff_started)
        left_layout.addWidget(self.blade_preview)

        preview_controls = QtWidgets.QWidget()
        preview_controls.setFixedWidth(250)  # match the Soundfont Folders section above
        preview_controls_layout = QtWidgets.QHBoxLayout(preview_controls)
        preview_controls_layout.setContentsMargins(0, 4, 0, 0)

        ignite_button = QtWidgets.QPushButton("Ignite")
        ignite_button.clicked.connect(self._on_ignite_clicked)
        retract_button = QtWidgets.QPushButton("Retract")
        retract_button.clicked.connect(self._on_retract_clicked)

        preview_controls_layout.addWidget(ignite_button, stretch=1)
        preview_controls_layout.addWidget(retract_button, stretch=1)
        left_layout.addWidget(preview_controls)

        reaction_controls = QtWidgets.QWidget()
        reaction_controls.setFixedWidth(250)  # match the Soundfont Folders section above
        reaction_controls_layout = QtWidgets.QHBoxLayout(reaction_controls)
        reaction_controls_layout.setContentsMargins(0, 4, 0, 0)

        clash_button = QtWidgets.QPushButton("Clash")
        clash_button.clicked.connect(self._on_clash_clicked)
        self.lockup_button = QtWidgets.QPushButton("Lockup")
        self.lockup_button.setCheckable(True)
        self.lockup_button.clicked.connect(self._on_lockup_clicked)
        blaster_button = QtWidgets.QPushButton("Blaster Block")
        blaster_button.clicked.connect(self._on_blaster_clicked)

        # Explicit fixed widths rather than layout stretch factors - with the row's total
        # width fixed at 250 and all three buttons' preferred sizes together exceeding that,
        # QHBoxLayout's stretch-based distribution shrinks the higher-stretch (Blaster Block)
        # widget *more*, not less, which is the opposite of what's wanted here. 60+60+118 plus
        # the row's two 6px inter-widget gaps fills the 250px row exactly.
        clash_button.setFixedWidth(60)
        self.lockup_button.setFixedWidth(60)
        blaster_button.setFixedWidth(118)

        reaction_controls_layout.addWidget(clash_button)
        reaction_controls_layout.addWidget(self.lockup_button)
        reaction_controls_layout.addWidget(blaster_button)
        left_layout.addWidget(reaction_controls)

        layout.addWidget(left_container, stretch=1)
        
        # Right side container
        right_container = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_container)
        right_layout.setContentsMargins(8, 8, 8, 8)

        # Create fixed top section for dropdown and headers
        top_section = QtWidgets.QWidget()
        top_layout = QtWidgets.QVBoxLayout(top_section)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        # Dropdown row
        dropdown_row = QtWidgets.QWidget()
        dropdown_layout = QtWidgets.QHBoxLayout(dropdown_row)
        dropdown_layout.setContentsMargins(0, 0, 0, 0)

        # Narrow enough that both dropdowns, their labels, and the Save button all fit
        # side by side without overlapping even at the window's minimum size (1024px wide).
        DROPDOWN_WIDTH = 150

        dropdown_label = QtWidgets.QLabel("Jump to Section:")
        self.category_dropdown = QtWidgets.QComboBox()
        self.category_dropdown.setFixedWidth(DROPDOWN_WIDTH)
        self.category_dropdown.currentTextChanged.connect(self.scroll_to_category)

        param_dropdown_label = QtWidgets.QLabel("Jump to Parameter:")
        self.param_dropdown = QtWidgets.QComboBox()
        self.param_dropdown.setFixedWidth(DROPDOWN_WIDTH)
        self.param_dropdown.currentTextChanged.connect(self.scroll_to_parameter)

        dropdown_layout.addWidget(dropdown_label)
        dropdown_layout.addWidget(self.category_dropdown)
        dropdown_layout.addWidget(param_dropdown_label)
        dropdown_layout.addWidget(self.param_dropdown)
        dropdown_layout.addStretch()

        # Save button
        save_button = QtWidgets.QPushButton("Save Changes")
        save_button.setStyleSheet("""
            QPushButton {
                background-color: #4A90E2;
                color: white;
                padding: 6px 16px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #357ABD;
            }
        """)
        save_button.clicked.connect(self.save_changes)
        dropdown_layout.addWidget(save_button)

        # Sticky section-header bar: mirrors whichever category header ("Blade and Color
        # Profiles", "Battle Fx", etc.) is currently scrolled to the top of the settings
        # grid below, so it - and its "shared parameters"/help-triangle hints - stay visible
        # no matter how far the user has scrolled, instead of a static column-name row.
        sticky_header_row = QtWidgets.QWidget()
        sticky_header_row.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ddd;")
        sticky_header_layout = QtWidgets.QHBoxLayout(sticky_header_row)
        sticky_header_layout.setContentsMargins(8, 4, 8, 4)
        sticky_header_row.setMinimumHeight(30)

        self.sticky_category_label = QtWidgets.QLabel("")
        self.sticky_category_label.setStyleSheet("""
            font-weight: bold;
            font-size: 14px;
            color: #4A90E2;
        """)
        self.sticky_hint_label = QtWidgets.QLabel("Click the triangle next to each parameter for help")
        self.sticky_hint_label.setStyleSheet("""
            color: #888888;
            font-style: italic;
            font-size: 11px;
            padding-left: 20px;
        """)
        self.sticky_shared_warning_label = QtWidgets.QLabel(
            "Highlighted parameters are used by multiple soundfonts")
        self.sticky_shared_warning_label.setStyleSheet("""
            color: #8a6d00;
            font-style: italic;
            padding-left: 20px;
        """)
        self.sticky_shared_warning_label.setVisible(False)

        sticky_header_layout.addWidget(self.sticky_category_label)
        sticky_header_layout.addWidget(self.sticky_hint_label)
        sticky_header_layout.addWidget(self.sticky_shared_warning_label)
        sticky_header_layout.addStretch()

        # Add dropdown and the sticky header bar to top section
        top_layout.addWidget(dropdown_row)
        top_layout.addWidget(sticky_header_row)

        # Scroll area for content
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QtWidgets.QFrame.NoFrame)

        # Container for settings grid
        settings_container = QtWidgets.QWidget()
        settings_layout = QtWidgets.QVBoxLayout(settings_container)
        settings_layout.setContentsMargins(0, 0, 0, 0)

        # Create settings grid with matching column proportions
        self.settings_grid = SettingsGrid(
            "",
            self,
            column_stretches=[1, 2, 2]  # Pass stretch factors to grid
        )
        settings_layout.addWidget(self.settings_grid)

        scroll_area.verticalScrollBar().valueChanged.connect(self._update_sticky_category_header)

        # Placeholder shown instead of the settings grid once a folder is loaded but before
        # any soundfont has been selected from the left pane.
        self.settings_scroll_area = scroll_area
        self.no_font_placeholder = QtWidgets.QLabel("Please select a soundfont from the left pane.")
        self.no_font_placeholder.setAlignment(QtCore.Qt.AlignCenter)
        self.no_font_placeholder.setStyleSheet("color: #888888; font-size: 16px; padding: 40px;")

        self.right_content_stack = QtWidgets.QStackedWidget()
        self.right_content_stack.addWidget(scroll_area)
        self.right_content_stack.addWidget(self.no_font_placeholder)

        # Add everything to right side
        right_layout.addWidget(top_section)  # Fixed top section
        scroll_area.setWidget(settings_container)
        right_layout.addWidget(self.right_content_stack)

        layout.addWidget(right_container, stretch=3)
   
    def _update_sticky_category_header(self, *_args):
        """Keep the sticky header bar in sync with whichever category is currently scrolled
        to the top of the settings grid - connected to the scroll area's scrollbar, and also
        called right after the grid is rebuilt (e.g. a new font is selected), since category
        positions shift even when the scroll value itself doesn't change."""
        scroll_value = self.settings_scroll_area.verticalScrollBar().value()
        category = self.settings_grid.category_at_scroll_position(scroll_value)
        self.sticky_category_label.setText(category or "")
        self.sticky_shared_warning_label.setVisible(
            bool(category and self.settings_grid.category_has_shared_params.get(category))
        )

    def scroll_to_category(self, category: str):
        """Scroll to the selected category"""
        if not category or category == "Jump to section...":
            return

        # Ask the settings grid to scroll to the category
        self.settings_grid.scroll_to_category(category)

    def scroll_to_parameter(self, param_name: str):
        """Scroll to the selected parameter"""
        if not param_name or param_name == "Jump to parameter...":
            return

        self.settings_grid.scroll_to_parameter(param_name)

    def _on_ignite_clicked(self):
        # Don't play poweron here - if a Pre-On phase is about to run, poweron sound has to
        # wait for it to finish (see _on_preon_started/_on_poweron_started below); playing it
        # immediately would step on the preon sound and start it at the wrong moment anyway.
        self.blade_preview.ignite()

    def _on_preon_started(self):
        """Fires from BladePreviewWidget.preon_started - a Pre-On phase just began."""
        self.sound_player.play_one_shot(self.current_font_path, 'preon')

    def _on_poweron_started(self):
        """Fires from BladePreviewWidget.poweron_started - the poweron animation just began,
        either immediately (no Pre-On phase configured) or right after Pre-On finished."""
        self.sound_player.play_one_shot(self.current_font_path, 'poweron')

    def _on_blade_ignited(self):
        """Fires from BladePreviewWidget.ignited - the exact moment the blade finishes
        igniting, which can take longer than qon_ms alone (a Pre-On phase runs first, or a
        GraFx-driven poweron paces itself by its own delay), so hum starts here rather than
        after a guessed timeout."""
        self.sound_player.start_loop('hum', self.current_font_path, 'humM')

    def _on_retract_clicked(self):
        self.sound_player.stop_loop('hum')
        self.sound_player.stop_loop('lockup')
        # Unlike poweron/preon, poweroff always plays right away here - postoff (if any) runs
        # after retraction finishes, not before, so it can't collide with this sound.
        self.sound_player.play_one_shot(self.current_font_path, 'poweroff')
        self.blade_preview.retract()

    def _on_postoff_started(self):
        """Fires from BladePreviewWidget.postoff_started - a Post-Off phase just began, once
        retraction (and its poweroff sound) has fully finished."""
        self.sound_player.play_one_shot(self.current_font_path, 'pstoff')

    def _on_clash_clicked(self):
        self.sound_player.play_one_shot(self.current_font_path, 'clash')
        self.blade_preview.clash()

    def _on_lockup_clicked(self):
        engaged = self.blade_preview.toggle_lockup()
        self.lockup_button.setChecked(engaged)
        if engaged:
            self.sound_player.start_loop('lockup', self.current_font_path, 'lockup')
        else:
            self.sound_player.stop_loop('lockup')

    def _on_blaster_clicked(self):
        self.sound_player.play_one_shot(self.current_font_path, 'blaster')
        self.blade_preview.blaster_deflect()

    def prompt_for_folder(self):
       folder = QtWidgets.QFileDialog.getExistingDirectory(
           self,
           "Select CFX Root Folder"
       )
       if folder:
           if self.load_cfx_folder(folder):
               self._prompt_for_backup_location_on_load()

    def _prompt_for_backup_location_on_load(self):
        """Ask (once, right after a root folder is chosen) whether the user wants to set
        up a backup location. Optional - a 'No' here just leaves self.backup_path unset,
        and save_changes() will nag about it again at save time instead."""
        self.backup_path = None
        response = QtWidgets.QMessageBox.question(
            self,
            "Backup Location",
            "Would you like to choose a folder where the app can back up any files it "
            "changes before overwriting them? This is optional but recommended.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        if response == QtWidgets.QMessageBox.Yes:
            self._pick_backup_location()

    def _pick_backup_location(self):
        """Open a folder picker for the backup location, rejecting anything inside the
        current CFX root folder. Sets self.backup_path on a valid pick; leaves it
        untouched if the user cancels the dialog."""
        while True:
            folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Backup Location")
            if not folder:
                return
            candidate = Path(folder).resolve()
            try:
                root_resolved = self.folder_path.resolve()
            except OSError:
                root_resolved = self.folder_path
            if candidate == root_resolved or root_resolved in candidate.parents:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Invalid Backup Location",
                    "The backup folder can't be inside the CFX root folder. Please choose "
                    "a different location."
                )
                continue
            self.backup_path = candidate
            return

    def _backup_file(self, file_path: Path, font_name: str):
        """Copy file_path's current contents into backup_path/font_name/ before it gets
        overwritten, named with a timestamp so repeated saves don't collide. No-op if no
        backup location is set, or if the file doesn't exist yet (nothing to preserve)."""
        if self.backup_path is None or not file_path.is_file():
            return
        try:
            dest_dir = self.backup_path / font_name
            dest_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            dest_path = dest_dir / f"{file_path.stem}_{timestamp}{file_path.suffix}"
            shutil.copy2(file_path, dest_path)
        except OSError as e:
            print(f"Error backing up {file_path}: {e}")

    def _confirm_no_backup(self) -> bool:
        """Called from save_changes() when no backup location is set. Lets the user pick
        one on the spot, continue without a backup, or cancel the save entirely. Returns
        True if the save should proceed, False to abort it."""
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle("No Backup Location Set")
        box.setText(
            "No backup location is set, so the files this save overwrites won't be "
            "backed up first.\n\nChoose a backup location, or continue without one?"
        )
        choose_button = box.addButton("Choose Backup Location...", QtWidgets.QMessageBox.ActionRole)
        continue_button = box.addButton("Continue Without Backup", QtWidgets.QMessageBox.AcceptRole)
        box.addButton(QtWidgets.QMessageBox.Cancel)
        box.setDefaultButton(continue_button)
        box.exec()

        clicked = box.clickedButton()
        if clicked == choose_button:
            self._pick_backup_location()
            return True
        return clicked == continue_button

    def on_font_selected(self, item):
        try:
            self.right_content_stack.setCurrentWidget(self.settings_scroll_area)
            font_path = Path(item.data(QtCore.Qt.UserRole))
            self.current_font_path = font_path
            # Switching fonts should stop whatever this preview was playing for the
            # previous one, same as it visually resets to unlit below.
            self.sound_player.stop_all()
            self.lockup_button.setChecked(False)


            # More robust font number extraction
            try:
                font_name_parts = font_path.name.split('-')
                font_num = int(font_name_parts[0])
                font_name = '-'.join(font_name_parts[1:])
                print(f"\nSelected font: {font_name} (Font #{font_num})")
            except (ValueError, IndexError) as e:
                print(f"Error parsing font number from path {font_path}: {e}")
                font_num = 0  # Default if we can't extract a valid number
                font_name = font_path.name
            
            # Load font configuration
            settings = self.file_handler.load_font_config(font_path)
            if not settings:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Error",
                    f"No font_config.txt found in {font_path}"
                )
                return
            
            print(f"Raw start_blade value from font_config.txt: '{settings.get('start_blade')}'")
            
            # Load preferences - Adjust for 1-based vs 0-based indexing
            prefs = self.file_handler.load_preferences()
            prefs_font_index = font_num - 1 if font_num > 0 else 0
            font_prefs = prefs.get(prefs_font_index, {})
            print(f"Font {font_num} maps to prefs.txt index {prefs_font_index}")
            print(f"Font prefs for index {prefs_font_index}: {font_prefs}")
            
            # Determine which blade profile to use - accounting for -1 fallback
            profile_num = settings.get('start_blade')
            effective_profile = None
            
            if profile_num == '-1':
                # If start_blade is -1, check preferences
                print(f"Looking up profile in prefs for font index {prefs_font_index}")
                if 'profile' in font_prefs:
                    effective_profile = font_prefs['profile']
                    print(f"Found profile {effective_profile} in prefs")
                    # Update the settings dictionary to show the effective value
                    settings['start_blade'] = effective_profile + " (from prefs)"
                else:
                    print(f"No profile found in prefs for font index {prefs_font_index}")
            else:
                effective_profile = profile_num
                print(f"Using profile {effective_profile} directly from font_config.txt")
            
            # Clear all highlighting first
            for i in range(self.font_list.count()):
                list_item = self.font_list.item(i)
                list_item.setBackground(QtGui.QColor(255, 255, 255))  # White
            
            # Track shared fonts and parameters
            shared_fonts = []
            shared_parameters = set()
            
            # Only highlight shared fonts if we have a valid profile
            if effective_profile is not None and effective_profile != '-1':
                effective_profile_int = int(effective_profile)
                
                # Find which fonts share this effective profile
                for other_font_num, other_font_name, other_font_path in self.file_handler.load_font_folders():
                    # Skip the current font
                    if other_font_num == font_num:
                        continue
                        
                    # Load the other font's configuration
                    other_font_config = self.file_handler.load_font_config(other_font_path)
                    if not other_font_config:
                        continue
                        
                    # Check if other font uses the same profile directly
                    other_profile = other_font_config.get('start_blade')
                    if other_profile == str(effective_profile_int):
                        shared_fonts.append(other_font_name)
                        print(f"Font {other_font_name} directly uses the same profile")
                        continue
                        
                    # If other font has start_blade=-1, check prefs
                    if other_profile == '-1':
                        # Account for the indexing offset
                        other_prefs_index = other_font_num - 1
                        other_font_prefs = prefs.get(other_prefs_index, {})
                        if 'profile' in other_font_prefs and other_font_prefs['profile'] == str(effective_profile_int):
                            shared_fonts.append(other_font_name)
                            print(f"Font {other_font_name} uses the same profile via prefs.txt")
                
                # Highlight the shared fonts
                for i in range(self.font_list.count()):
                    list_item = self.font_list.item(i)
                    item_font_path = Path(list_item.data(QtCore.Qt.UserRole))
                    try:
                        item_font_name = '-'.join(item_font_path.name.split('-')[1:])
                        
                        if item_font_name in shared_fonts:
                            list_item.setBackground(QtGui.QColor(255, 243, 176))  # Light yellow - matches the "shared" color used in the settings grid
                            print(f"Highlighted font: {item_font_name}")
                    except Exception as e:
                        print(f"Error parsing font name for highlighting: {e}")

            # Re-apply validation-error highlighting on top - red wins over the yellow
            # "shared profile" highlight, same priority the settings grid uses for fields.
            self._apply_font_list_validation_highlighting(reset_others=False)

            # Load blade profile if we have a valid profile number
            blade_settings = {}
            if effective_profile is not None and effective_profile != '-1':
                profile_num_int = int(effective_profile)
                blade_profile = self.file_handler.load_blade_profile(profile_num_int)
                if blade_profile:
                    print(f"Loaded profile {effective_profile} with {len(blade_profile)} parameters")
                    blade_settings = blade_profile

                    # If this font shares its profile with other fonts, all blade profile parameters are shared
                    if shared_fonts:
                        shared_parameters.update(blade_settings.keys())
                        print(f"Shared parameters: {len(shared_parameters)}")
                else:
                    print(f"Failed to load blade profile {effective_profile}")
            color_settings = {}
            
            # Handle color profile similarly to blade profile
            color_num = settings.get('start_color')
            effective_color = None
            
            if color_num == '-1':
                if 'color' in font_prefs:
                    effective_color = font_prefs['color']
                    print(f"Using color {effective_color} from prefs.txt (font has start_color=-1)")
                    # Update the settings dictionary to show the effective value
                    settings['start_color'] = effective_color + " (from prefs)"
                else:
                    print("Font has start_color=-1 but no color set in prefs.txt")
            else:
                effective_color = color_num
                print(f"Using color {effective_color} directly from font_config.txt")

            # Load color profile if we have a valid color number
            if effective_color is not None and effective_color != '-1':
                color_num_int = int(effective_color)
                color_profile = self.file_handler.load_color_profile(color_num_int)
                if color_profile:
                    print(f"Loaded color {effective_color} with {len(color_profile)} parameters")
                    color_settings = color_profile
                else:
                    print(f"Failed to load color profile {effective_color}")

            # Global parameters live in the header of config.txt, above any [profile=] section.
            # They apply to every soundfont on the card, not just the one selected here.
            global_settings = self.file_handler.load_master_config()
            print(f"Loaded {len(global_settings)} global config parameters")

            # Combine all settings for display, but remember which file each one came
            # from (font_config.txt / config.txt profile / colors.txt / config.txt header)
            # so Save can route them back correctly.
            #
            # Merge order matters when a name collides across scopes (e.g. omnisabers exists
            # both as a global config.txt parameter and inside every blade profile). The CFX
            # manual's documented SD card parsing order is: config.txt (global header, then
            # blade profiles) -> colors.txt -> font_config.txt, each later file/section able to
            # override same-named values from before it. So the most general scope goes first
            # here and gets overridden by anything more specific, ending with font_config.txt.
            all_settings = global_settings.copy()
            all_settings.update(blade_settings)
            all_settings.update(color_settings)
            all_settings.update(settings)

            param_sources = {}
            param_sources.update({name: 'global' for name in global_settings})
            param_sources.update({name: 'blade' for name in blade_settings})
            param_sources.update({name: 'color' for name in color_settings})
            param_sources.update({name: 'font' for name in settings})

            # Which reference font_config.txt keys (from this card's own 1-SABERTRIO font)
            # this font's own file is missing (checked against the raw font-only settings,
            # not the merged all_settings)
            reference_keys = self.file_handler.load_reference_font_config_keys()
            missing_font_keys = CFXValidator.check_missing_font_config_keys(settings, reference_keys)

            # Feed the blade preview widget from all_settings (not blade_settings/color_settings
            # directly) - a font_config.txt can override a normally blade-or-color-scoped name
            # like style_poff for just that one font, same as any other override. Reading from
            # the unmerged per-file dicts here would silently show the pre-override blade/color
            # value in the preview while the settings grid (which does use all_settings)
            # correctly showed the overridden one - e.g. a font whose font_config.txt sets
            # style_poff=0 would still preview whatever its blade profile's own style_poff was.
            # It only uses a handful of clearly-documented parameters (color, qon/qoff,
            # flkon/flkoff, style_pon/style_poff, unstable, fcolor/lcolor) - see blade_preview.py
            # for what's approximated vs. skipped.
            from core.color_utils import rgbw_to_rgb

            def parse_rgbw(color_str, default=(200, 200, 200)):
                try:
                    r, g, b, w = map(int, color_str.split(','))
                    return rgbw_to_rgb(r, g, b, w)
                except (ValueError, AttributeError):
                    return default

            rgb = parse_rgbw(all_settings.get('color'))
            foc_rgb = parse_rgbw(all_settings.get('fcolor'), default=(255, 255, 255))
            lockup_rgb = parse_rgbw(all_settings.get('lcolor'), default=(255, 140, 0))
            bolt_rgb = parse_rgbw(all_settings.get('bcolor'), default=(255, 60, 0))
            try:
                qon_ms = int(all_settings.get('qon', 300))
            except ValueError:
                qon_ms = 300
            try:
                qoff_ms = int(all_settings.get('qoff', 300))
            except ValueError:
                qoff_ms = 300
            flicker_on = all_settings.get('flkon') == '1'
            flicker_off = all_settings.get('flkoff') == '1'

            # style_grafx1 (main blade) points at an indexed /extra/GRAFX folder - resolve it
            # to an actual path so the preview can play back this font's real GraFx BMPs
            # (style_pon/poff=GraFx sequence, style_lockup=GraFx sequence, unstable=17/18)
            # instead of falling back to a plain color.
            grafx_folder = None
            try:
                grafx_num = int(all_settings.get('style_grafx1', -1))
                if grafx_num >= 0:
                    grafx_folder = self.grafx_profile_paths.get(grafx_num)
            except ValueError:
                pass

            self.blade_preview.set_profile(
                rgb, qon_ms, qoff_ms, flicker_on, flicker_off,
                foc_rgb=foc_rgb, lockup_rgb=lockup_rgb,
                pon_style_id=all_settings.get('style_pon'),
                poff_style_id=all_settings.get('style_poff'),
                unstable_id=all_settings.get('unstable'),
                clash_style_id=all_settings.get('style_clash'),
                lockup_style_id=all_settings.get('style_lockup'),
                pos_lockup=all_settings.get('pos_lockup'),
                size_lockup=all_settings.get('size_lockup'),
                focd_ms=all_settings.get('focd'),
                bolt_rgb=bolt_rgb,
                blaster_style_id=all_settings.get('style_blaster'),
                grafx_folder=grafx_folder,
                preon_style_id=all_settings.get('style_preon'),
                postoff_style_id=all_settings.get('style_postoff'),
            )
            self.blade_preview.reset()

            # Update UI with shared parameter information
            self.settings_grid.update_settings(
                all_settings,
                shared_with=shared_fonts,
                shared_parameters=shared_parameters,
                param_sources=param_sources,
                missing_font_keys=missing_font_keys
            )

            # Selecting a font from the list always jumps back to the top of the
            # parameters view, rather than leaving it scrolled wherever the previous
            # font's view happened to be.
            self.settings_grid.scroll_to_top()
            self._update_sticky_category_header()

        except Exception as e:
            print(f"Error loading settings: {e}")
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                f"Failed to load settings: {str(e)}"
            )

    def _reload_grafx_profiles(self):
        """(Re)scan <cfx_root>/extra/grafx for numbered GraFx resource folders. Called from
        load_cfx_folder, and again after the GraFx Creator wizard writes a new resource so it
        shows up in the style_grafx1/2/3 dropdowns without a full folder reload."""
        print("Loading GraFx profiles...")
        grafx_path = self.folder_path / 'extra' / 'grafx'
        self.grafx_profiles = {}
        self.grafx_profile_paths = {}  # number -> folder Path, for reading grafx1.txt/BMPs
        if grafx_path.exists():
            for item in grafx_path.iterdir():
                if item.is_dir() and item.name[0].isdigit():
                    try:
                        # Extract number and name
                        number = int(item.name.split('-')[0])
                        # Skip any category prefix
                        name = '-'.join(item.name.split('-')[1:])
                        self.grafx_profiles[number] = name
                        self.grafx_profile_paths[number] = item
                        print(f"Found GraFx profile {number}: {name}")
                    except (ValueError, IndexError):
                        continue
        print(f"Loaded {len(self.grafx_profiles)} GraFx profiles")

    def open_grafx_creator(self):
        """Open the GraFx Creator wizard and, if the user finishes it, make the new resource
        immediately selectable in the style_grafx1/2/3 dropdowns."""
        if not self.folder_path:
            QtWidgets.QMessageBox.information(
                self, "No Folder Loaded",
                "Select a CFX root folder first."
            )
            return
        from gui.grafx_creator_dialog import GrafxCreatorDialog
        dialog = GrafxCreatorDialog(self.folder_path, main_window=self)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            apply_specs = dialog.link_apply_specs()
            self._reload_grafx_profiles()
            current_item = self.font_list.currentItem()
            resource_desc = f"'{dialog.created_folder.name}'" if dialog.created_folder else "The resource"

            if current_item is None:
                # Nothing to apply specs to, and nothing to reselect/refresh - the resource
                # still got written to disk, but with no font selected in the list there's no
                # settings grid to push unstable/style_grafx1/2/3 into. Without this message
                # the wizard would just silently close having done nothing visible, leaving
                # the resource created but unlinked from any font.
                QtWidgets.QMessageBox.information(
                    self, "GraFx Resource Created",
                    f"{resource_desc} was created, but no font is currently selected, so it "
                    "wasn't linked to anything. Select a font, then set style_grafx1/2/3 "
                    "(and the matching style_pon/style_poff/unstable/etc.) to it by hand, or "
                    "select a font first and run the wizard again to link automatically."
                )
                return

            self.on_font_selected(current_item)
            if not apply_specs:
                # Reached whenever link_apply_specs() returned {} - the "Automatically set
                # up..." checkbox was left unchecked (or was disabled because no font was
                # selected when the wizard was opened, even if one is selected now). Same
                # silent-no-op risk as the no-font-selected case above.
                QtWidgets.QMessageBox.information(
                    self, "GraFx Resource Created",
                    f"{resource_desc} was created, but wasn't linked to '{current_item.text()}' "
                    "(the \"Automatically set up...\" option wasn't used). Set style_grafx1/2/3 "
                    "(and the matching style_pon/style_poff/unstable/etc.) by hand in the "
                    "settings grid below, then Save Changes."
                )
                return

            # set_parameter_value can fail to find a widget for a param that isn't currently
            # displayed - e.g. a blade profile/font that has never set unstable or
            # style_grafx1/2/3 before won't show them in the grid at all, since it only
            # renders params actually present in the loaded settings. Report that instead of
            # claiming success while quietly doing nothing.
            failed = [param_name for param_name, value in apply_specs.items()
                      if not self.settings_grid.set_parameter_value(param_name, value)]
            if failed:
                QtWidgets.QMessageBox.warning(
                    self, "Couldn't Fully Link GraFx Resource",
                    "The GraFx resource was created, but these parameters aren't "
                    "currently shown for this font/blade profile, so they couldn't be "
                    "set automatically:\n\n" + ", ".join(failed) +
                    "\n\nYou'll need to add and set them by hand (they may need to be "
                    "added to font_config.txt or the blade profile first)."
                )
            else:
                QtWidgets.QMessageBox.information(
                    self, "GraFx Resource Linked",
                    "The new GraFx resource has been linked to this font in the settings "
                    "grid below. Nothing has been written to disk yet - review the "
                    "highlighted parameters and click Save Changes when you're ready."
                )

    def open_grafx_editor(self):
        """Open the GraFx resource editor on the existing /extra/GRAFX resources. Copies it
        makes are new resource folders, so rescan afterwards to make them selectable in the
        style_grafx1/2/3 dropdowns."""
        if not self.folder_path:
            QtWidgets.QMessageBox.information(
                self, "No Folder Loaded",
                "Select a CFX root folder first."
            )
            return
        from gui.grafx_resource_editor_dialog import GrafxResourceEditorDialog
        dialog = GrafxResourceEditorDialog(self.folder_path, main_window=self)
        dialog.exec()
        if dialog.changed_folders:
            self._reload_grafx_profiles()
            copies = sorted(folder.name for folder in dialog.session_copies)
            if copies:
                QtWidgets.QMessageBox.information(
                    self, "GraFx Copies Created",
                    "Your edits were saved to these new resources (the originals are "
                    "unchanged):\n\n" + "\n".join(copies) +
                    "\n\nTo use one, set style_grafx1/2/3 to its number for the font, then "
                    "Save Changes."
                )

    def load_cfx_folder(self, folder_path):
        try:
            self.folder_path = Path(folder_path)
            self.file_handler = CFXFileHandler(self.folder_path)
            
            # Create validator directly
            validator = CFXValidator()
            is_valid, errors = validator.validate_root_folder(str(self.folder_path))
            if not is_valid:
                error_msg = "\n".join(errors)
                QtWidgets.QMessageBox.warning(
                    self,
                    "Invalid Folder Structure",
                    f"The selected folder has the following issues:\n{error_msg}"
                )
                return False

            # Load color profiles
            from core.color_utils import load_color_profiles
            self.color_profiles = load_color_profiles(self.folder_path)
            print(f"Loaded {len(self.color_profiles)} color profiles")
            
            # Load GraFx profiles
            self._reload_grafx_profiles()

            # Load Accent LED and Pixel Accent (Pixies) profiles - same indexed-folder
            # linking scheme as GraFx, referenced by style_accents / style_pixies
            from core.color_utils import load_accents_profiles, load_pixies_profiles
            self.accents_profiles = load_accents_profiles(self.folder_path)
            self.pixies_profiles = load_pixies_profiles(self.folder_path)
            print(f"Loaded {len(self.accents_profiles)} Accent profiles, "
                  f"{len(self.pixies_profiles)} Pixies profiles")

            # Clear and populate font list
            self.font_list.clear()
            for font_num, font_name, font_path in self.file_handler.load_font_folders():
                list_item = QtWidgets.QListWidgetItem(f"{font_num}-{font_name}")
                list_item.setData(QtCore.Qt.UserRole, str(font_path))
                self.font_list.addItem(list_item)

            # No font is selected yet right after a folder loads - show the placeholder
            # instead of an empty settings grid until the user picks one.
            self.right_content_stack.setCurrentWidget(self.no_font_placeholder)

            # Validate every soundfont on the card right away, instead of requiring a
            # separate "Validate All Soundfonts" button click.
            self._run_and_apply_validation()
            return True

        except Exception as e:
            print(f"Error loading CFX folder: {e}")
            QtWidgets.QMessageBox.warning(
                self,
                "Error",
                f"Failed to load CFX folder: {str(e)}"
            )
            return False

    def _resolve_effective_profile_and_color(self, settings, font_num, prefs):
        """Given a font's raw font_config.txt settings, resolve which blade profile and
        color profile it actually uses, accounting for the -1 -> prefs.txt fallback that
        on_font_selected also implements. Returns (effective_profile, effective_color) as
        strings (still needing int()), or None for whichever couldn't be resolved."""
        prefs_font_index = font_num - 1 if font_num > 0 else 0
        font_prefs = prefs.get(prefs_font_index, {})

        profile_num = settings.get('start_blade')
        if profile_num == '-1':
            effective_profile = font_prefs.get('profile')
        else:
            effective_profile = profile_num

        color_num = settings.get('start_color')
        if color_num == '-1':
            effective_color = font_prefs.get('color')
        else:
            effective_color = color_num

        return effective_profile, effective_color

    def _run_and_apply_validation(self):
        """Walk every soundfont on the loaded card and report anything wrong: the same
        parameter-level checks the settings grid highlights red for whichever font is
        currently selected, run across every font, plus config.txt/colors.txt structural
        errors (duplicate profile/color numbers) and blade/color profiles nothing uses.

        Runs automatically after a folder loads (see load_cfx_folder). Colors the font
        list to flag which fonts have problems, and pops the report dialog - same as the
        old "Validate All Soundfonts" button did - only if something was actually found."""
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            report = self._run_full_validation()
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        self.validation_report = report
        self.font_validation_by_path = {
            str(font_report['font_path']): font_report for font_report in report['font_reports']
        }
        self._apply_font_list_validation_highlighting()

        has_issues = bool(
            report['structural_errors'] or report['global_errors'] or report['font_reports']
            or report['orphaned_profiles'] or report['orphaned_colors']
            or report['grafx_warnings']
        )
        if has_issues:
            dialog = ValidationReportDialog(report, self.file_handler, self, backup_fn=self._backup_file)
            dialog.jump_to_font.connect(self._jump_to_font)
            dialog.font_config_changed.connect(self._on_font_config_changed_externally)
            dialog.exec()

    def _apply_font_list_validation_highlighting(self, reset_others=True):
        """Color each font-list row red if that font has validation errors or missing
        font_config.txt keys, per the last validation pass. When reset_others is True
        (e.g. right after loading a folder), every other row goes back to white; when False
        (called from on_font_selected, after its own shared-profile yellow highlighting),
        only the red overlay is applied, so red wins over yellow without erasing it."""
        for i in range(self.font_list.count()):
            item = self.font_list.item(i)
            font_path = item.data(QtCore.Qt.UserRole)
            if font_path in self.font_validation_by_path:
                item.setBackground(QtGui.QColor("#FFB3B3"))  # same red as the settings grid's ERROR_PARAM_COLOR
            elif reset_others:
                item.setBackground(QtGui.QColor(255, 255, 255))

    def _run_full_validation(self):
        report = {
            'structural_errors': [],
            'global_errors': {},
            'font_reports': [],
            'orphaned_profiles': [],
            'orphaned_colors': [],
            'grafx_warnings': [],
            'font_count': 0,
        }

        _, config_errors, profiles_by_num = CFXValidator.validate_config_file(
            self.folder_path / "config.txt"
        )
        report['structural_errors'].extend(f"config.txt: {e}" for e in config_errors)
        all_profile_numbers = set(profiles_by_num.keys())

        _, color_errors, colors_by_num = CFXValidator.validate_colors_file(
            self.folder_path / "colors.txt"
        )
        report['structural_errors'].extend(f"colors.txt: {e}" for e in color_errors)
        all_color_numbers = set(colors_by_num.keys())

        prefs = self.file_handler.load_preferences()
        referenced_profiles = set()
        referenced_colors = set()
        font_folders = self.file_handler.load_font_folders()
        report['font_count'] = len(font_folders)
        reference_keys = self.file_handler.load_reference_font_config_keys()

        for font_num, font_name, font_path in font_folders:
            settings = self.file_handler.load_font_config(font_path)
            if not settings:
                report['font_reports'].append({
                    'font_num': font_num, 'font_name': font_name, 'font_path': font_path,
                    'errors': {'(font_config.txt)': 'Missing or empty font_config.txt'},
                })
                continue

            missing_font_keys = CFXValidator.check_missing_font_config_keys(settings, reference_keys)

            effective_profile, effective_color = self._resolve_effective_profile_and_color(
                settings, font_num, prefs
            )

            blade_settings = {}
            font_errors = {}
            if effective_profile is not None and str(effective_profile) != '-1':
                try:
                    profile_num_int = int(effective_profile)
                    referenced_profiles.add(profile_num_int)
                    blade_settings = self.file_handler.load_blade_profile(profile_num_int) or {}
                    if not blade_settings:
                        font_errors['start_blade'] = (
                            f"Points to blade profile {profile_num_int}, which isn't "
                            f"defined in config.txt"
                        )
                except ValueError:
                    font_errors['start_blade'] = f"'{effective_profile}' isn't a valid profile number"
            elif effective_profile is None:
                font_errors['start_blade'] = (
                    "start_blade=-1 but no matching profile is set in prefs.txt"
                )

            color_settings = {}
            if effective_color is not None and str(effective_color) != '-1':
                try:
                    color_num_int = int(effective_color)
                    referenced_colors.add(color_num_int)
                    color_settings = self.file_handler.load_color_profile(color_num_int) or {}
                    if not color_settings:
                        font_errors['start_color'] = (
                            f"Points to color profile {color_num_int}, which isn't "
                            f"defined in colors.txt"
                        )
                except ValueError:
                    font_errors['start_color'] = f"'{effective_color}' isn't a valid color number"
            elif effective_color is None:
                font_errors['start_color'] = (
                    "start_color=-1 but no matching color is set in prefs.txt"
                )

            global_settings = self.file_handler.load_master_config()

            # Same precedence as on_font_selected: global -> blade -> color -> font_config.txt,
            # matching the manual's documented parsing order (most specific wins).
            all_settings = global_settings.copy()
            all_settings.update(blade_settings)
            all_settings.update(color_settings)
            all_settings.update(settings)

            param_sources = {}
            param_sources.update({n: 'global' for n in global_settings})
            param_sources.update({n: 'blade' for n in blade_settings})
            param_sources.update({n: 'color' for n in color_settings})
            param_sources.update({n: 'font' for n in settings})

            # Reuse the exact same widget-based validation the interactive grid uses, on a
            # throwaway (never-shown) grid, so this can't drift from what the UI highlights.
            grid = SettingsGrid("", main_window=self)
            grid.update_settings(all_settings, param_sources=param_sources)

            # Global (config.txt header) parameters apply to every font on the card, so an
            # error there isn't really "this font's problem" - it's the same one issue,
            # reported once here instead of once per font that happens to inherit it.
            for name, msg in grid.param_errors.items():
                if param_sources.get(name) == 'global':
                    report['global_errors'][name] = msg
                else:
                    font_errors[name] = msg
            grid.deleteLater()

            # GraFx animations this font's blade profile links (style_grafx1/2/3) checked
            # against its refreshfx and sound/qon/qoff timing - warnings, not errors.
            from core.grafx_timing import FontTiming, check_resource
            timing = FontTiming(font_path, all_settings, label=f"{font_num}-{font_name}")
            checked_folders = set()   # the same resource on several slots is one set of warnings
            for slot in (1, 2, 3):
                try:
                    grafx_index = int(str(all_settings.get(f'style_grafx{slot}', -1)).split()[0])
                except (ValueError, IndexError):
                    continue
                folder = self.grafx_profile_paths.get(grafx_index)
                if folder is None or folder in checked_folders:
                    continue
                checked_folders.add(folder)
                for warning in check_resource(folder, timing):
                    report['grafx_warnings'].append({
                        'font_num': font_num, 'font_name': font_name, 'font_path': font_path,
                        'resource': folder.name, 'slot': slot, **warning,
                    })

            if font_errors or missing_font_keys:
                report['font_reports'].append({
                    'font_num': font_num, 'font_name': font_name, 'font_path': font_path,
                    'errors': font_errors,
                    'missing_keys': missing_font_keys,
                })

        report['orphaned_profiles'] = sorted(all_profile_numbers - referenced_profiles)
        report['orphaned_colors'] = sorted(all_color_numbers - referenced_colors)

        return report

    def open_special_settings(self, focus_key: str = None):
        if not self.folder_path:
            QtWidgets.QMessageBox.information(self, "No Folder Loaded", "Select a CFX root folder first.")
            return
        from gui.special_settings_dialog import SpecialSettingsDialog
        SpecialSettingsDialog(self.folder_path, self, focus_key=focus_key).exec()

    def open_tracks_dialog(self):
        if not self.folder_path:
            QtWidgets.QMessageBox.information(self, "No Folder Loaded", "Select a CFX root folder first.")
            return
        from gui.tracks_dialog import TracksDialog
        TracksDialog(self.folder_path, self).exec()

    def open_import_font(self):
        if not self.folder_path:
            QtWidgets.QMessageBox.information(self, "No Folder Loaded", "Select a CFX root folder first.")
            return
        from gui.import_font_dialog import ImportFontDialog
        dialog = ImportFontDialog(self.folder_path, self)
        if dialog.exec() and dialog.imported is not None:
            self.load_cfx_folder(self.folder_path)
            self._jump_to_font(str(dialog.imported))

    def open_duplicate_profiles(self):
        if not self.folder_path:
            QtWidgets.QMessageBox.information(self, "No Folder Loaded", "Select a CFX root folder first.")
            return
        from gui.duplicate_profiles_dialog import DuplicateProfilesDialog
        dialog = DuplicateProfilesDialog(self.folder_path, self)
        dialog.exec()
        if dialog.changed:
            self.load_cfx_folder(self.folder_path)

    def open_sound_check(self):
        if not self.folder_path:
            QtWidgets.QMessageBox.information(self, "No Folder Loaded", "Select a CFX root folder first.")
            return
        from gui.sound_check_dialog import SoundCheckDialog
        SoundCheckDialog(self.folder_path, self).exec()

    def current_setting(self, name: str):
        """A setting's live value: from the settings grid when a font is shown (so unsaved
        edits count), else from config.txt's global header. None if not set."""
        if self.current_font_path is not None:
            value = self.settings_grid.get_current_settings().get(name)
            if value is not None:
                return value
        return self.file_handler.load_master_config().get(name) if self.file_handler else None

    def apply_grid_params(self, params: dict):
        """Put params into the settings grid (highlighted, saved by Save Changes), like
        apply_blade_profile_params but for whichever font is shown - used for settings that
        aren't font-specific, e.g. the iSaber player's loop/shuffle in config.txt.
        Returns (ok, message)."""
        if self.current_font_path is None:
            return False, ("Select any font in the main window first - its settings page is "
                           "where these are changed and saved.")
        failed = [name for name, value in params.items()
                  if not self.settings_grid.set_parameter_value(name, value)]
        if failed:
            return False, f"These aren't shown in the settings, so they couldn't be set: {', '.join(failed)}."
        sources = {self.settings_grid.param_sources.get(name, 'font') for name in params}
        where = {"global": "config.txt (applies to every font)", "blade": "the blade profile",
                 "font": "this font's font_config.txt", "color": "the color profile"}
        settings = ", ".join(f"{k}={v}" for k, v in params.items())
        return True, (f"Set {settings} in {' and '.join(where.get(s, s) for s in sorted(sources))}. "
                      f"Nothing is written yet - click Save Changes in the main window.")

    def apply_blade_profile_params(self, font_path, params: dict):
        """Put params (e.g. SwingBright settings chosen in the GraFx painter's preview) into
        the settings grid for font_path - highlighted as changed, written to disk only by
        Save Changes, like any other edit. Only possible while that font is the one shown.
        Returns (ok, message)."""
        font_path = Path(font_path)
        if self.current_font_path is None or Path(self.current_font_path) != font_path:
            return False, (f"Select {font_path.name} in the main window's font list first - "
                           f"its settings need to be on screen to change them.")
        failed = [name for name, value in params.items()
                  if not self.settings_grid.set_parameter_value(name, value)]
        if failed:
            return False, (f"These aren't shown for {font_path.name}, so they couldn't be set: "
                           f"{', '.join(failed)}. Add them to its blade profile first.")
        sources = {self.settings_grid.param_sources.get(name, 'font') for name in params}
        where = []
        if 'blade' in sources:
            try:
                profile = int(str(self.settings_grid.get_current_settings()
                                  .get('start_blade', '')).split()[0])
                shared = [path.name for path in self._fonts_using_profile(profile)
                          if path != font_path]
                where.append(f"blade profile {profile}" + (
                    f" (also used by: {', '.join(shared)})" if shared else ""))
            except (ValueError, IndexError):
                where.append("its blade profile")
        if 'font' in sources:
            where.append("its font_config.txt (it overrides the blade profile there)")
        settings = ", ".join(f"{k}={v}" for k, v in params.items())
        return True, (f"Set {settings} for {font_path.name} in {' and '.join(where)}. "
                      f"Nothing is written yet - review the highlighted values in the main "
                      f"window and click Save Changes.")

    def _fonts_using_profile(self, profile_num: int):
        """Every font folder whose effective blade profile (start_blade, or prefs.txt when
        that's -1) is profile_num - the same resolution the font list's shared-profile
        highlighting uses."""
        prefs = self.file_handler.load_preferences()
        fonts = []
        for font_num, _font_name, path in self.file_handler.load_font_folders():
            settings = self.file_handler.load_font_config(path) or {}
            profile, _color = self._resolve_effective_profile_and_color(settings, font_num, prefs)
            if str(profile) == str(profile_num):
                fonts.append(Path(path))
        return fonts

    def font_timing(self, font_path):
        """core.grafx_timing.FontTiming for a font: its sounds plus its effective settings
        (global -> blade profile -> color -> font_config.txt). The currently selected font
        uses the live settings grid, so unsaved edits (e.g. to refreshfx or qon) count."""
        from core.grafx_timing import FontTiming
        font_path = Path(font_path)
        label = font_path.name
        if self.current_font_path is not None and Path(self.current_font_path) == font_path:
            return FontTiming(font_path, self.settings_grid.get_current_settings(), label)
        settings = self.file_handler.load_font_config(font_path) or {}
        try:
            font_num = int(font_path.name.split('-')[0])
        except ValueError:
            font_num = 0
        profile, color = self._resolve_effective_profile_and_color(
            settings, font_num, self.file_handler.load_preferences())
        merged = dict(self.file_handler.load_master_config())
        for number, loader in ((profile, self.file_handler.load_blade_profile),
                               (color, self.file_handler.load_color_profile)):
            try:
                merged.update(loader(int(number)) or {})
            except (TypeError, ValueError):
                pass
        merged.update(settings)
        return FontTiming(font_path, merged, label)

    def fonts_linked_to_grafx(self, grafx_index: int):
        """Font folders whose blade profile links this GraFx resource number through
        style_grafx1/2/3 - the fonts whose sounds/refreshfx it plays with."""
        linked = []
        prefs = self.file_handler.load_preferences()
        for font_num, _font_name, font_path in self.file_handler.load_font_folders():
            settings = self.file_handler.load_font_config(font_path) or {}
            profile, _color = self._resolve_effective_profile_and_color(settings, font_num, prefs)
            try:
                blade = self.file_handler.load_blade_profile(int(profile)) or {}
            except (TypeError, ValueError):
                blade = {}
            merged = dict(blade)
            merged.update(settings)
            for slot in (1, 2, 3):
                if str(merged.get(f'style_grafx{slot}', '')).split()[:1] == [str(grafx_index)]:
                    linked.append(font_path)
                    break
        return linked

    def _jump_to_font(self, font_path_str):
        """Select the given font in the list and load it, e.g. from the validation report."""
        for i in range(self.font_list.count()):
            item = self.font_list.item(i)
            if item.data(QtCore.Qt.UserRole) == font_path_str:
                self.font_list.setCurrentItem(item)
                self.on_font_selected(item)
                return

    def _on_font_config_changed_externally(self, font_path_str):
        """A font_config.txt was written to disk from outside the settings grid (e.g. the
        validation report's "insert missing keys" action). Silently re-validates so the
        font-list red highlighting stays accurate, without popping another report dialog on
        top of the one this change likely came from. If a font is currently selected,
        on_font_selected recomputes both its shared-profile and validation highlighting (and
        reloads the grid if the changed font is the one selected); otherwise just re-applies
        the red highlighting directly."""
        if self.file_handler and self.folder_path:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try:
                report = self._run_full_validation()
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
            self.validation_report = report
            self.font_validation_by_path = {
                str(font_report['font_path']): font_report for font_report in report['font_reports']
            }

        current_item = self.font_list.currentItem()
        if current_item:
            self.on_font_selected(current_item)
        else:
            self._apply_font_list_validation_highlighting()

    def save_changes(self):
        try:
            # Get current font
            current_item = self.font_list.currentItem()
            if not current_item:
                raise Exception("No font selected")

            # Get current settings from the UI, split by which file they belong to
            settings_by_source = self.settings_grid.get_settings_split()
            font_settings = settings_by_source['font']
            blade_settings = settings_by_source['blade']
            color_settings = settings_by_source['color']
            global_settings = settings_by_source['global']

            message = "Are you sure you want to save these changes?"
            if global_settings:
                message += ("\n\nThis includes global device settings, which affect "
                             "every soundfont on the card, not just this one.")

            param_errors = self.settings_grid.param_errors
            if param_errors:
                shown = list(param_errors.items())[:10]
                error_lines = "\n".join(f"  - {name}: {msg}" for name, msg in shown)
                if len(param_errors) > len(shown):
                    error_lines += f"\n  ...and {len(param_errors) - len(shown)} more"
                message += (
                    f"\n\n{len(param_errors)} parameter(s) are highlighted red and failed "
                    f"validation:\n{error_lines}\n\nSave anyway?"
                )

            if self.backup_path is None and not self._confirm_no_backup():
                return  # user cancelled the save from the no-backup warning

            response = QtWidgets.QMessageBox.question(
                self,
                "Save Changes",
                message,
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            )

            if response == QtWidgets.QMessageBox.Yes:
                font_path = Path(current_item.data(QtCore.Qt.UserRole))
                font_name = font_path.name

                # Save font configuration
                self._backup_file(font_path / "font_config.txt", font_name)
                if not self.file_handler.save_font_config(font_path, font_settings):
                    raise Exception("Failed to save font configuration")

                # If we have a blade profile, save it. Merge onto a fresh reload of the
                # profile rather than replacing it outright, so any key not represented by
                # a live widget (missing schema entry, or a name that collides with a
                # global-scope param of the same name, e.g. 'omnisabers') isn't dropped.
                if blade_settings and 'start_blade' in font_settings:
                    profile_num = int(font_settings['start_blade'])
                    if profile_num >= 0:  # Only save if it's a valid profile number
                        existing_blade = self.file_handler.load_blade_profile(profile_num) or {}
                        existing_blade.update(blade_settings)
                        self._backup_file(self.folder_path / "config.txt", font_name)
                        if not self.file_handler.save_blade_profile(profile_num, existing_blade):
                            raise Exception(f"Failed to save blade profile {profile_num}")

                # If we have a color profile, save it (same merge-onto-existing approach)
                if color_settings and 'start_color' in font_settings:
                    color_num = int(font_settings['start_color'])
                    if color_num >= 0:  # Only save if it's a valid color number
                        existing_color = self.file_handler.load_color_profile(color_num) or {}
                        existing_color.update(color_settings)
                        self._backup_file(self.folder_path / "colors.txt", font_name)
                        if not self.file_handler.save_color_profile(color_num, existing_color):
                            raise Exception(f"Failed to save color profile {color_num}")

                # Global settings apply to every soundfont on the card
                if global_settings:
                    existing_global = self.file_handler.load_master_config() or {}
                    existing_global.update(global_settings)
                    self._backup_file(self.folder_path / "config.txt", font_name)
                    if not self.file_handler.save_master_config(existing_global):
                        raise Exception("Failed to save global configuration")

                # Re-read everything from disk and re-feed the settings grid/blade preview,
                # the same refresh that happens when re-selecting this font from the list.
                # Without this, the preview keeps showing whatever it was rendering before
                # the save - e.g. a newly-linked GraFx idle animation wouldn't appear until
                # the user clicked away to another font and back.
                self.on_font_selected(current_item)

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
    
    def display_settings(self, settings: dict, shared_with: list = None):
        """Update displayed settings."""
        try:
            # Update both grids
            self.settings_grid.update_settings(settings)
                        
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
            
    def confirm_profile_change(self, param_name, combo_box):
        """Show confirmation dialog for profile change and reload data if confirmed"""
        # Get the original and new values
        original_value = combo_box.property("original_value")
        new_data = combo_box.currentData()
        
        # Only show confirmation if this isn't the initial setting and the value actually changed
        if original_value is not None and new_data != original_value:
            # Create confirmation message
            if param_name == 'start_blade':
                message = "Changing the blade profile will affect all parameters in the current profile.\n\n"
                message += "This change may also affect other sound fonts that use this profile.\n\n"
                message += "Do you want to continue?"
            else:  # start_color
                message = "Changing the color profile will affect all color-related parameters.\n\n"
                message += "Do you want to continue?"
            
            # Show confirmation dialog
            confirm = QtWidgets.QMessageBox.question(
                self, "Confirm Profile Change", message,
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No
            )
            
            if confirm == QtWidgets.QMessageBox.Yes:
                # Get current font selection
                current_item = self.font_list.currentItem()
                if current_item:
                    font_path = Path(current_item.data(QtCore.Qt.UserRole))
                    
                    # Update the profile in settings
                    try:
                        # Get current font configuration
                        settings = self.file_handler.load_font_config(font_path)
                        if settings:
                            # Update the profile number
                            settings[param_name] = new_data

                            # Save the updated settings
                            self._backup_file(font_path / "font_config.txt", font_path.name)
                            self.file_handler.save_font_config(font_path, settings)
                            
                            # Reload the font to display updated settings
                            self.on_font_selected(current_item)
                            
                            # Show success message
                            QtWidgets.QMessageBox.information(
                                self, "Profile Updated", 
                                f"The {param_name} has been updated to {new_data}."
                            )
                    except Exception as e:
                        print(f"Error updating profile: {e}")
                        QtWidgets.QMessageBox.critical(
                            self, "Error", f"Failed to update profile: {str(e)}"
                        )
            else:
                # Revert to original selection if user cancels
                if original_value is not None:
                    # Find the index for the original value
                    original_index = combo_box.findData(original_value)
                    if original_index >= 0:
                        # Block signals to prevent recursive confirmation dialog
                        combo_box.blockSignals(True)
                        combo_box.setCurrentIndex(original_index)
                        combo_box.blockSignals(False)