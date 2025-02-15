import sys
from pathlib import Path

# Add parent directory to Python path so we can import src.core
parent_dir = Path(__file__).parent.parent
sys.path.append(str(parent_dir))

from src.core.color_utils import load_color_profiles

def test_color_profiles():
    # Use current directory as test folder
    test_folder = Path(__file__).parent
    
    print("\nReading color profiles from:", test_folder.absolute())
    
    # Load color profiles
    profiles = load_color_profiles(test_folder)
    
    print("\nFound color profiles:")
    print("-" * 50)
    
    # Print each profile
    for profile_num in sorted(profiles.keys()):
        profile = profiles[profile_num]
        print(f"Profile {profile_num}: {profile.get('color_name', 'unnamed')}")
        
    print("-" * 50)
    print(f"Total profiles found: {len(profiles)}")

if __name__ == "__main__":
    test_color_profiles()