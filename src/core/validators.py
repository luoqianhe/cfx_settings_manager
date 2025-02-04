# src/core/validators.py
from pathlib import Path
from typing import Tuple, List, Dict, Optional

class CFXValidationError(Exception):
    """Custom exception for CFX-specific validation errors."""
    pass

class CFXValidator:
    """Validates CFX folder structure and file contents."""
    
    REQUIRED_FILES = ['config.txt', 'colors.txt']
    
    @staticmethod
    def validate_root_folder(folder_path: str) -> Tuple[bool, List[str]]:
        """Validate the selected root folder structure."""
        errors = []
        path = Path(folder_path)
        
        # Check if folder exists and is readable
        if not path.exists():
            errors.append(f"Folder does not exist: {folder_path}")
            return False, errors
        if not path.is_dir():
            errors.append(f"Selected path is not a folder: {folder_path}")
            return False, errors
            
        # Check for required files
        for required_file in CFXValidator.REQUIRED_FILES:
            if not (path / required_file).is_file():
                errors.append(f"Missing required file: {required_file}")
                
        # Check for at least one sound font folder
        has_font_folder = False
        for item in path.iterdir():
            if item.is_dir() and item.name[0].isdigit() and '-' in item.name:
                has_font_folder = True
                # Validate font folder
                font_errors = CFXValidator.validate_font_folder(item)
                errors.extend(font_errors)
                
        if not has_font_folder:
            errors.append("No valid sound font folders found")
            
        return len(errors) == 0, errors

    @staticmethod
    def validate_font_folder(folder_path: Path) -> List[str]:
        """Validate a sound font folder structure."""
        errors = []
        
        # Check folder name format
        if not CFXValidator.is_valid_font_folder_name(folder_path.name):
            errors.append(f"Invalid font folder name format: {folder_path.name}")
            
        # Check for font_config.txt
        config_file = folder_path / "font_config.txt"
        if not config_file.is_file():
            errors.append(f"Missing font_config.txt in {folder_path.name}")
            
        return errors

    @staticmethod
    def is_valid_font_folder_name(name: str) -> bool:
        """Check if folder name follows the number-NAME format."""
        try:
            number, name = name.split('-', 1)
            return (
                number.isdigit() and 
                name.replace('_', '').isalnum() and
                name.isupper()
            )
        except ValueError:
            return False

    @staticmethod
    def validate_config_file(file_path: Path) -> Tuple[bool, List[str], Optional[Dict]]:
        """Validate config.txt file format and contents."""
        errors = []
        settings = {}
        
        try:
            with open(file_path, 'r') as f:
                lines = f.readlines()
                
            current_profile = None
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                if not line or line.startswith('//'):
                    continue
                    
                if line.startswith('[profile='):
                    try:
                        profile_num = int(line[9:-1])
                        if profile_num in settings:
                            errors.append(f"Duplicate profile number {profile_num} at line {line_num}")
                        current_profile = profile_num
                        settings[current_profile] = {}
                    except ValueError:
                        errors.append(f"Invalid profile number format at line {line_num}")
                elif '=' in line and current_profile is not None:
                    key, value = line.split('=', 1)
                    settings[current_profile][key.strip()] = value.strip()
                        
        except Exception as e:
            errors.append(f"Error reading config file: {str(e)}")
            
        return len(errors) == 0, errors, settings if len(errors) == 0 else None

    @staticmethod
    def validate_colors_file(file_path: Path) -> Tuple[bool, List[str], Optional[Dict]]:
        """Validate colors.txt file format and contents."""
        errors = []
        colors = {}
        
        try:
            with open(file_path, 'r') as f:
                lines = f.readlines()
                
            current_color = None
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                if not line or line.startswith('//'):
                    continue
                    
                if line.startswith('[color='):
                    try:
                        color_num = int(line[7:-1])
                        if color_num in colors:
                            errors.append(f"Duplicate color number {color_num} at line {line_num}")
                        current_color = color_num
                        colors[current_color] = {}
                    except ValueError:
                        errors.append(f"Invalid color number format at line {line_num}")
                elif '=' in line and current_color is not None:
                    key, value = line.split('=', 1)
                    colors[current_color][key.strip()] = value.strip()
                        
        except Exception as e:
            errors.append(f"Error reading colors file: {str(e)}")
            
        return len(errors) == 0, errors, colors if len(errors) == 0 else None

    @staticmethod
    def validate_font_config(file_path: Path) -> Tuple[bool, List[str], Optional[Dict]]:
        """Validate font_config.txt file format and contents."""
        errors = []
        settings = {}
        
        try:
            with open(file_path, 'r') as f:
                lines = f.readlines()
                
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                if not line or line.startswith('//') or line.startswith('#'):
                    continue
                    
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # Validate specific settings
                    if key == 'start_color':
                        try:
                            if not (-1 <= int(value) <= 31):
                                errors.append(f"Invalid start_color value at line {line_num}")
                        except ValueError:
                            errors.append(f"Invalid start_color format at line {line_num}")
                            
                    settings[key] = value
                        
        except Exception as e:
            errors.append(f"Error reading font config file: {str(e)}")
            
        return len(errors) == 0, errors, settings if len(errors) == 0 else None