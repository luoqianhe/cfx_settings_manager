# src/core/validators.py
import re
from pathlib import Path
from typing import Tuple, List, Dict, Optional


class CFXValidationError(Exception):
    """Custom exception for CFX-specific validation errors."""
    pass

class CFXValidator:
    """Validates CFX folder structure and file contents."""

    REQUIRED_FILES = ['config.txt', 'colors.txt']

    BOLT_KEY_RE = re.compile(r'^bolt(\d+)$')

    # Keys that show up in the reference '1-SABERTRIO' font_config.txt but aren't actually
    # required - a font is free to omit these, so they shouldn't be flagged as "missing".
    NOT_REQUIRED_KEYS = {'tridentflk'}

    # Groups of parameters with a documented relationship (see check_cross_parameter_rules).
    # Used by the GUI to know which widgets should trigger live re-validation of each other.
    CROSS_PARAM_RULE_GROUPS = [
        ('qon', 'ignd'),
        ('qoff', 'retd'),
        ('offp', 'offd'),
    ]

    @staticmethod
    def value_out_of_range(param_def: Optional[dict], raw_value: str) -> Optional[str]:
        """Check a raw (string) parameter value against its declared 'range' in
        parameters.json. Handles single values as well as the comma-joined pairs/triples
        used by range_pair and triple_range params. Returns an error message if the value
        falls outside its declared bounds, or None if it's fine / there's nothing to check.

        This deliberately doesn't try to parse values that don't look numeric at all -
        that's a type/format mismatch, a different failure mode already caught by
        widget_factory.set_widget_value().
        """
        if not param_def or 'range' not in param_def:
            return None

        display_type = param_def.get('display_type')
        rng = param_def['range']

        try:
            if display_type in ('range_pair', 'triple_range'):
                parts = [float(p) for p in str(raw_value).split(',')]
            else:
                parts = [float(raw_value)]
        except (ValueError, TypeError):
            return None

        if display_type == 'triple_range' and len(rng) >= 4:
            # [a_min, a_max, b_min, b_max]: first value uses the a-bounds, the rest use b-bounds
            bounds = [(rng[0], rng[1])] + [(rng[2], rng[3])] * (len(parts) - 1)
        else:
            lo = rng[0]
            hi = rng[1] if len(rng) > 1 else rng[0]
            bounds = [(lo, hi)] * len(parts)

        for value, (lo, hi) in zip(parts, bounds):
            if value < lo or value > hi:
                return f"'{raw_value}' is outside the declared range [{lo}, {hi}]"

        return None

    @staticmethod
    def check_bolt_key_gaps(settings: Dict[str, str]) -> Dict[str, str]:
        """bolt<n> keys (per-impact timings for a blaster sound) form a 0-indexed sequence
        of whatever length a font needs - CFX doesn't require any specific count, only that
        the numbering has no gaps (bolt0, bolt1, bolt2, ... is fine at any length; bolt0,
        bolt1, bolt3 with no bolt2 is not). Returns {key: default_value} for each missing
        index below the highest one actually present."""
        indices = set()
        for key in settings:
            match = CFXValidator.BOLT_KEY_RE.match(key)
            if match:
                indices.add(int(match.group(1)))
        if not indices:
            return {}
        return {f'bolt{i}': '1' for i in range(max(indices)) if i not in indices}

    @staticmethod
    def check_missing_font_config_keys(settings: Dict[str, str], reference: Dict[str, str]) -> Dict[str, str]:
        """Compare a font's raw font_config.txt keys against a reference key set (plus any
        gap in its bolt<n> sequence). `reference` should come from
        CFXFileHandler.load_reference_font_config_keys() - the loaded SD card's own
        '1-SABERTRIO' font_config.txt - rather than being hardcoded here, since the exact
        key list a firmware version expects can change between updates; 1-SABERTRIO's file
        is whatever this card's firmware actually needs right now. Returns
        {key: default_value} for every expected key that's absent, so callers can both
        report the gap and offer to fill it in. `settings` should be just the font's own
        font_config.txt contents (not merged with blade/color/global scope), since a key
        can be legitimately absent from font_config.txt while still resolving to a value
        from elsewhere - that's not what this checks. bolt<n> keys in `reference` are
        ignored for the literal presence check (that family's expected length isn't fixed -
        see check_bolt_key_gaps) but still contribute via the gap check. Keys in
        NOT_REQUIRED_KEYS are also excluded, even though the reference font happens to set
        them - they're not actually required."""
        missing = {
            key: default
            for key, default in reference.items()
            if key not in settings and not CFXValidator.BOLT_KEY_RE.match(key)
            and key not in CFXValidator.NOT_REQUIRED_KEYS
        }
        missing.update(CFXValidator.check_bolt_key_gaps(settings))
        return missing

    @staticmethod
    def check_cross_parameter_rules(settings: Dict[str, str]) -> Dict[str, str]:
        """Check relationships between specific parameters that are explicitly documented
        in their parameters.json 'notes'/'description' text. Returns {param_name: message}
        for every parameter involved in a violated rule.

        Deliberately conservative: CFX doesn't define general inter-parameter dependencies
        (per project notes), so only relationships with a clear textual source are checked
        here rather than guessed at.
        """
        errors: Dict[str, str] = {}

        def as_int(name):
            try:
                return int(settings[name])
            except (KeyError, ValueError, TypeError):
                return None

        qon, ignd = as_int('qon'), as_int('ignd')
        if qon is not None and ignd is not None and qon < ignd:
            msg = ("qon (quick-on duration) should be >= ignd (ignition delay) - "
                   "CFX docs: \"Set qon = desired_duration + ignd\"")
            errors['qon'] = msg
            errors['ignd'] = msg

        qoff, retd = as_int('qoff'), as_int('retd')
        if qoff is not None and retd is not None and qoff < retd:
            msg = ("qoff (quick-off duration) should be >= retd (retraction delay) - "
                   "CFX docs: retd is \"similar to ignd, adjust qoff accordingly\"")
            errors['qoff'] = msg
            errors['retd'] = msg

        offp, offd = settings.get('offp'), as_int('offd')
        if offp == '1' and offd is not None and offd != 0:
            msg = ("offd should be 0 when offp (Anti Power-Off Protection) is enabled - "
                   "CFX docs: \"Set to zero if using offp parameter\"")
            errors['offp'] = msg
            errors['offd'] = msg

        return errors
    
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
            # Split only first hyphen to get number
            parts = name.split('-', 1)
            if len(parts) != 2:
                return False
                
            number, name = parts
            
            # Check if starts with a number
            if not number.isdigit():
                return False
                
            # Rest of name can contain hyphens, underscores, and alphanumeric characters
            # We don't care about case
            return True
                
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

        return len(errors) == 0, errors, settings

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

        return len(errors) == 0, errors, colors

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