"""
Configuration management for Calvin AI
"""
import os
from pathlib import Path
from dotenv import load_dotenv

def get_config():
    """Load configuration from environment variables"""
    # Find .env.dev file in project root
    current_dir = Path(__file__).parent
    project_root = current_dir.parent.parent.parent  # Go up from src/config to calvin_1, then to project root
    env_file = project_root / '.env.dev'
    
    # Debug print (can be removed later)
    print(f"Looking for .env.dev at: {env_file}")
    print(f"File exists: {env_file.exists()}")
    
    # Load .env.dev file
    load_dotenv(env_file)
    
    # Return config dictionary with all environment variables
    return dict(os.environ)
