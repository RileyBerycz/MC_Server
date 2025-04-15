import os
import json

def load_config(file_path):
    """Load a JSON configuration file."""
    if not os.path.exists(file_path):
        return {}
    
    with open(file_path, 'r') as f:
        return json.load(f)

def save_config(file_path, config):
    """Save a JSON configuration file."""
    with open(file_path, 'w') as f:
        json.dump(config, f, indent=2)

def update_config(file_path, updates):
    """Update a JSON configuration file with new values."""
    config = load_config(file_path)
    config.update(updates)
    save_config(file_path, config)

def get_default_config():
    """Get the default configuration settings."""
    default_config_path = os.path.join('server_configs', 'default_config.json')
    return load_config(default_config_path)