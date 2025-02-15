# src/core/file_handler.py
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from core.validators import CFXValidator

print("In file_handler.py")
print("Imported validators:", vars())
print("CFXValidator imported:", 'CFXValidator' in vars())
print("Local variables:", locals())

class CFXFileHandler:
    """Handles all file operations for CFX settings."""
    
    def __init__(self, root_path: Path):
        self.root_path = Path(root_path)
        # self.validator = CFXValidator()
        
    def load_font_folders(self) -> List[Tuple[int, str, Path]]:
        """
        Load all font folders from the root directory.
        Returns: List of tuples (number, name, path)
        """
        folders = []
        try:
            for item in self.root_path.iterdir():
                if item.is_dir() and item.name[0].isdigit():
                    try:
                        number = int(item.name.split('-')[0])
                        name = '-'.join(item.name.split('-')[1:])
                        folders.append((number, name, item))
                    except (ValueError, IndexError):
                        continue
                        
            return sorted(folders, key=lambda x: x[0])
            
        except Exception as e:
            print(f"Error loading font folders: {e}")
            return []

    def load_font_config(self, font_path: Path) -> Dict:
        """Load font configuration from font_config.txt"""
        settings = {}
        config_path = font_path / "font_config.txt"
        
        try:
            if not config_path.exists():
                return settings
                
            with open(config_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('//') and not line.startswith('#'):
                        if '=' in line:
                            key, value = line.split('=', 1)
                            settings[key.strip()] = value.strip()
                            
        except Exception as e:
            print(f"Error loading font config: {e}")
            
        return settings

    def load_preferences(self) -> Dict:
        """Load preferences from prefs.txt"""
        prefs = {}
        prefs_path = self.root_path / "prefs.txt"
        
        try:
            if not prefs_path.exists():
                return prefs
                
            current_font = None
            with open(prefs_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('//'):
                        if line.startswith('[font='):
                            current_font = int(line[6:-1])
                            prefs[current_font] = {}
                        elif '=' in line and current_font is not None:
                            key, value = line.split('=', 1)
                            prefs[current_font][key.strip()] = value.strip()
                            
        except Exception as e:
            print(f"Error loading preferences: {e}")
            
        return prefs

    def load_blade_profile(self, profile_num: int) -> Optional[Dict]:
        """Load blade profile from config.txt"""
        try:
            config_path = self.root_path / "config.txt"
            
            if not config_path.exists():
                return None
                
            current_profile = None
            profile_data = {}
            
            with open(config_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('[profile='):
                        try:
                            current_profile = int(line[9:-1])
                        except ValueError:
                            continue
                    elif '=' in line and current_profile == profile_num:
                        key, value = line.split('=', 1)
                        profile_data[key.strip()] = value.strip()
                        
            return profile_data if profile_data else None
            
        except Exception as e:
            print(f"Error loading blade profile: {e}")
            return None

    def load_color_profile(self, color_num: int) -> Optional[Dict]:
        """Load color profile from colors.txt"""
        try:
            color_path = self.root_path / "colors.txt"
            
            if not color_path.exists():
                return None
                
            current_color = None
            color_data = {}
            
            with open(color_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('[color='):
                        try:
                            current_color = int(line[7:-1])
                        except ValueError:
                            continue
                    elif '=' in line and current_color == color_num:
                        key, value = line.split('=', 1)
                        color_data[key.strip()] = value.strip()
                        
            return color_data if color_data else None
            
        except Exception as e:
            print(f"Error loading color profile: {e}")
            return None

    def save_font_config(self, font_path: Path, settings: Dict) -> bool:
        """Save font configuration to font_config.txt"""
        try:
            config_path = font_path / "font_config.txt"
            
            # Read existing file to preserve comments
            existing_lines = []
            if config_path.exists():
                with open(config_path, 'r') as f:
                    existing_lines = f.readlines()
            
            # Update or add settings
            new_lines = []
            settings_added = set()
            
            for line in existing_lines:
                line = line.strip()
                if not line or line.startswith('//') or line.startswith('#'):
                    new_lines.append(line + '\n')
                    continue
                    
                if '=' in line:
                    key = line.split('=')[0].strip()
                    if key in settings:
                        new_lines.append(f"{key}={settings[key]}\n")
                        settings_added.add(key)
                    else:
                        new_lines.append(line + '\n')
            
            # Add any new settings that weren't in the original file
            for key, value in settings.items():
                if key not in settings_added:
                    new_lines.append(f"{key}={value}\n")
            
            # Write back to file
            with open(config_path, 'w') as f:
                f.writelines(new_lines)
                
            return True
            
        except Exception as e:
            print(f"Error saving font config: {e}")
            return False

    def save_blade_profile(self, profile_num: int, profile_data: Dict) -> bool:
        """Save blade profile to config.txt"""
        try:
            config_path = self.root_path / "config.txt"
            
            # Read existing file
            with open(config_path, 'r') as f:
                lines = f.readlines()
            
            # Find profile section and update
            new_lines = []
            in_target_profile = False
            profile_updated = False
            
            for line in lines:
                line = line.strip()
                
                if line.startswith('[profile='):
                    current_profile = int(line[9:-1])
                    in_target_profile = (current_profile == profile_num)
                    if in_target_profile and not profile_updated:
                        # Add profile header
                        new_lines.append(f"[profile={profile_num}]\n")
                        # Add all profile data
                        for key, value in profile_data.items():
                            new_lines.append(f"{key}={value}\n")
                        profile_updated = True
                        continue
                
                if not in_target_profile:
                    new_lines.append(line + '\n')
            
            # If profile wasn't found, add it at the end
            if not profile_updated:
                new_lines.append(f"\n[profile={profile_num}]\n")
                for key, value in profile_data.items():
                    new_lines.append(f"{key}={value}\n")
            
            # Write back to file
            with open(config_path, 'w') as f:
                f.writelines(new_lines)
                
            return True
            
        except Exception as e:
            print(f"Error saving blade profile: {e}")
            return False

    def save_color_profile(self, color_num: int, color_data: Dict) -> bool:
        """Save color profile to colors.txt"""
        try:
            color_path = self.root_path / "colors.txt"
            
            # Read existing file
            with open(color_path, 'r') as f:
                lines = f.readlines()
            
            # Find color section and update
            new_lines = []
            in_target_color = False
            color_updated = False
            
            for line in lines:
                line = line.strip()
                
                if line.startswith('[color='):
                    current_color = int(line[7:-1])
                    in_target_color = (current_color == color_num)
                    if in_target_color and not color_updated:
                        # Add color header
                        new_lines.append(f"[color={color_num}]\n")
                        # Add all color data
                        for key, value in color_data.items():
                            new_lines.append(f"{key}={value}\n")
                        color_updated = True
                        continue
                
                if not in_target_color:
                    new_lines.append(line + '\n')
            
            # If color wasn't found, add it at the end
            if not color_updated:
                new_lines.append(f"\n[color={color_num}]\n")
                for key, value in color_data.items():
                    new_lines.append(f"{key}={value}\n")
            
            # Write back to file
            with open(color_path, 'w') as f:
                f.writelines(new_lines)
                
            return True
            
        except Exception as e:
            print(f"Error saving color profile: {e}")
            return False

    def get_shared_profiles(self, profile_num: int) -> List[str]:
        """
        Find which font folders share the same blade profile
        Returns: List of font names using this profile
        """
        shared_fonts = []
        
        try:
            for font_num, font_name, font_path in self.load_font_folders():
                font_config = self.load_font_config(font_path)
                if font_config.get('start_blade') == str(profile_num):
                    shared_fonts.append(font_name)
                    
        except Exception as e:
            print(f"Error finding shared profiles: {e}")
            
        return shared_fonts

print("In file_handler.py")
print("Imported validators:", vars())