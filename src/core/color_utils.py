from math import sqrt
from pathlib import Path
from typing import Tuple, Dict

# X11 colors for non-standard colors
X11_COLORS: Dict[str, Tuple[int, int, int]] = {
    # Reds
    'red': (255, 0, 0),
    'darkred': (139, 0, 0),
    'crimson': (220, 20, 60),
    'firebrick': (178, 34, 34),
    'indianred': (205, 92, 92),
    'lightcoral': (240, 128, 128),

    # Oranges
    'orange': (255, 165, 0),
    'darkorange': (255, 140, 0),
    'coral': (255, 127, 80),
    'tomato': (255, 99, 71),

    # Yellows
    'yellow': (255, 255, 0),
    'gold': (255, 215, 0),
    'lightyellow': (255, 255, 224),
    'lemonchiffon': (255, 250, 205),

    # Greens
    'green': (0, 128, 0),
    'lime': (0, 255, 0),
    'limegreen': (50, 205, 50),
    'forestgreen': (34, 139, 34),
    'lightgreen': (144, 238, 144),
    'springgreen': (0, 255, 127),
    'mediumspringgreen': (0, 250, 154),
    'seagreen': (46, 139, 87),

    # Cyans
    'cyan': (0, 255, 255),
    'aqua': (0, 255, 255),
    'turquoise': (64, 224, 208),
    'lightcyan': (224, 255, 255),
    'teal': (0, 128, 128),

    # Blues
    'blue': (0, 0, 255),
    'navy': (0, 0, 128),
    'royalblue': (65, 105, 225),
    'steelblue': (70, 130, 180),
    'deepskyblue': (0, 191, 255),
    'lightskyblue': (135, 206, 235),
    'cornflowerblue': (100, 149, 237),
    'dodgerblue': (30, 144, 255),

    # Purples
    'purple': (128, 0, 128),
    'magenta': (255, 0, 255),
    'darkmagenta': (139, 0, 139),
    'mediumorchid': (186, 85, 211),
    'darkviolet': (148, 0, 211),
    'blueviolet': (138, 43, 226),
    'indigo': (75, 0, 130),

    # Pinks
    'pink': (255, 192, 203),
    'hotpink': (255, 105, 180),
    'deeppink': (255, 20, 147),

    # Whites/Grays
    'white': (255, 255, 255),
    'snow': (255, 250, 250),
    'ivory': (255, 255, 240),
    'silver': (192, 192, 192),
}

# The 16 standard CFX colors with their exact RGBW values
STANDARD_COLORS = {
    (0, 1023, 0, 0): "green",
    (350, 1023, 0, 0): "lime",
    (1023, 750, 0, 0): "yellow",
    (1023, 450, 0, 0): "amber",
    (1023, 125, 0, 0): "tangerine",
    (1023, 30, 0, 0): "blood orange",
    (1023, 0, 0, 0): "red",
    (1023, 0, 350, 0): "pink",
    (1023, 0, 600, 0): "magenta",
    (1023, 0, 1023, 0): "purple",
    (0, 0, 1023, 0): "royal blue",
    (0, 150, 1023, 0): "ice blue",
    (0, 350, 1023, 0): "light blue",
    (0, 1023, 1023, 0): "cyan",
    (800, 800, 800, 0): "white",
    (0, 1023, 75, 0): "viridian"
}

def rgbw_to_rgb(r: int, g: int, b: int, w: int = 0) -> Tuple[int, int, int]:
    """Convert RGBW (0-1023) to RGB (0-255)"""
    return (
        min(255, int(r * 255 / 1023)),
        min(255, int(g * 255 / 1023)),
        min(255, int(b * 255 / 1023))
    )

def color_distance(c1: Tuple[int, int, int], c2: Tuple[int, int, int]) -> float:
    """Calculate Euclidean distance between two RGB colors"""
    return sqrt(sum((a - b) ** 2 for a, b in zip(c1, c2)))

def get_x11_color_name(r: int, g: int, b: int) -> str:
    """Find closest X11 color name for given RGB values"""
    rgb = rgbw_to_rgb(r, g, b, 0)
    closest_color = min(X11_COLORS.items(), 
                       key=lambda x: color_distance(rgb, x[1]))
    return closest_color[0]

def interpret_color(r: int, g: int, b: int, w: int = 0) -> str:
    """Convert RGBW values to a color name."""
    # Check if it's one of the 16 standard colors
    color_values = (r, g, b, w)
    if color_values in STANDARD_COLORS:
        return STANDARD_COLORS[color_values]
        
    # If not a standard color, use X11 naming
    return get_x11_color_name(r, g, b)

def load_color_profiles(root_path: Path) -> dict:
    """Load color profiles from colors.txt."""
    profiles = {}
    current_profile = None
    print('COLOR.TXT PATH:', root_path)
    
    try:
        with open(root_path / "colors.txt", "r") as f:
            for line in f:
                line = line.strip()
                
                # Only process color profile headers and color values
                if line.startswith('[color='):
                    current_profile = int(line[7:-1])
                    profiles[current_profile] = {}
                elif '=' in line and current_profile is not None:
                    key, value = line.split('=', 1)
                    if key == 'color':  # Main blade color
                        try:
                            r, g, b, w = map(int, value.split(','))
                            # Always use interpret_color, which will check standard colors first
                            # then fall back to X11 naming
                            color_name = interpret_color(r, g, b, w)
                            profiles[current_profile]['color_name'] = color_name
                        except ValueError:
                            profiles[current_profile]['color_name'] = "unknown"
                            
    except Exception as e:
        print(f"Error loading color profiles: {e}")
    
    return profiles

def load_grafx_profiles(root_path: Path) -> dict:
    """Load grafx profile names from the grafx folder."""
    profiles = {}
    try:
        print(f"\nLooking for grafx folder in: {root_path}")
        grafx_path = root_path / 'extra' / 'grafx'
        print(f"Checking path: {grafx_path}")
        if not grafx_path.exists():
            print("Grafx path not found")
            return profiles

        print("Found grafx folder, checking contents:")
        for item in grafx_path.iterdir():
            print(f"Found item: {item.name}")
            if item.is_dir() and item.name[0].isdigit():
                try:
                    # Extract number and name
                    number = int(item.name.split('-')[0])
                    name = '-'.join(item.name.split('-')[2:])
                    profiles[number] = name
                    print(f"Added profile {number}: {name}")
                except (ValueError, IndexError):
                    continue

        print(f"Final profiles dictionary: {profiles}")

    except Exception as e:
        print(f"Error loading grafx profiles: {e}")
    
    return profiles